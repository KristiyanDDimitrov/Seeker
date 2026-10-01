import re
from dataclasses import dataclass

from seeker.audio.formats import (
    is_downloadable_extension,
    quality_tier_for_format,
)
from seeker.matching import (
    AUTO_MATCH_THRESHOLD,
    NEEDS_REVIEW_THRESHOLD,
    artist_matches,
    score_title,
)
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track

# Untuned starting guess — revisit once real download data shows how queue
# depth actually correlates with practical wait time.
DEFAULT_MAX_QUEUE = 200


def normalize_soulseek_title(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]

    if "." in basename:
        basename = basename.rsplit(".", 1)[0]

    basename = basename.lower()
    basename = re.sub(r"\s+", " ", basename)

    return basename.strip()


def _score_candidate(track: Track, file: SoulseekFile) -> float | None:
    # Shared by filter_candidates (auto tier) and
    # find_best_needs_review_candidate (needs_review tier) — same
    # extension + artist gate and fuzzy title score, just a different
    # cutoff applied by each caller. Mirrors library/matcher.py's
    # find_best_match, which does the equivalent for local files.
    # Returns None when the file isn't audio or the artist doesn't match
    # at all (not just "scored too low") — distinct from a real score of
    # 0, so callers never have to special-case "no signal at all."
    # DOWNLOADABLE_EXTENSIONS, not the wider AUDIO_EXTENSIONS the
    # library scanner uses: this gates a NEW file being fetched from
    # SoulSeek, where "can Seeker finish tagging/indexing this
    # afterward" matters, not just "is this audio." HISTORY §94.
    if not is_downloadable_extension(file.extension):
        return None

    normalized_title = normalize_soulseek_title(file.filename)

    if not artist_matches(track.artist, normalized_title):
        return None

    return score_title(track.artist, track.title, normalized_title)


def filter_candidates(
        track: Track,
        files: list[SoulseekFile],
        auto_match_threshold: float = AUTO_MATCH_THRESHOLD,
) -> list[SoulseekFile]:
    candidates = []

    for file in files:
        score = _score_candidate(track, file)

        if score is None or score < auto_match_threshold:
            continue

        candidates.append(file)

    return candidates


# The best needs-review file, its score, and the runner-up file and
# score when there is one.
NeedsReviewCandidate = tuple[
    SoulseekFile, float, tuple[SoulseekFile, float] | None,
]


@dataclass(frozen=True)
class DownloadSelection:
    """What `select_downloads` picked for one track.

    `settled` is the file to request now (unlocked; practical when any
    candidate is). `upgrade_shortlist` ranks up to
    `MAX_UPGRADE_SHORTLIST` better-or-equal files to chase later; when
    `settled` is None it holds every locked candidate instead.
    `needs_review` is independent of both: the best below-auto-threshold
    candidate, for a human to judge.
    """
    settled: SoulseekFile | None
    upgrade_shortlist: list[SoulseekFile]
    needs_review: NeedsReviewCandidate | None


def find_best_needs_review_candidate(
        track: Track,
        files: list[SoulseekFile],
        needs_review_threshold: float = NEEDS_REVIEW_THRESHOLD,
        auto_match_threshold: float = AUTO_MATCH_THRESHOLD,
) -> NeedsReviewCandidate | None:
    # The Soulseek equivalent of library/matcher.py's needs_review tier:
    # a real, artist-matching candidate that's plausible but not
    # confident enough to auto-download (70 <= score < 90 by default).
    # Purely informational — nothing in this tier is ever requested from
    # slskd by select_downloads/download_playlist; it's surfaced
    # read-only via `seeker check` for a human to go find and grab
    # manually. Returns the best-scoring candidate across ALL files
    # (not just the auto-tier-filtered ones), since a track with zero
    # auto-tier candidates would otherwise have nothing left to search
    # here, plus the runner-up — the second-best-scoring candidate
    # still within the same band, round 8 §12.10 — so a human deciding
    # whether to confirm the winner can see what it beat, not just its
    # own score in isolation. None when only one real candidate exists.
    #
    # Both thresholds are plain optional parameters, not read from
    # config here — this module stays as decoupled from config/
    # filesystem concerns as matching.py itself. DownloadService, the
    # one real caller, resolves config-or-default once per
    # download_playlist() run and passes the numbers in explicitly.
    best: tuple[SoulseekFile, float] | None = None
    runner_up: tuple[SoulseekFile, float] | None = None

    for file in files:
        score = _score_candidate(track, file)

        if score is None:
            continue

        if not (needs_review_threshold <= score < auto_match_threshold):
            continue

        if best is None or score > best[1]:
            runner_up = best
            best = (file, score)
        elif runner_up is None or score > runner_up[1]:
            runner_up = (file, score)

    if best is None:
        return None

    return (best[0], best[1], runner_up)


def quality_tier(file: SoulseekFile) -> int:
    return quality_tier_for_format(file.extension)


def effective_bitrate(file: SoulseekFile) -> int:
    if (
            file.bit_rate is not None
            and 0 < file.bit_rate <= 320
            and not file.is_variable_bitrate
    ):
        return file.bit_rate

    return 0


def is_practical(
        file: SoulseekFile,
        max_queue: int = DEFAULT_MAX_QUEUE,
) -> bool:
    return file.queue_length <= max_queue


# Untuned starting constant — how many upgrade candidates to shortlist
# beyond the immediately-requested top one; revisit once real cascade
# data (Phase 4) shows how often rank 2/3 actually get used.
MAX_UPGRADE_SHORTLIST = 3


def _sort_key(file: SoulseekFile) -> tuple[int, int, int, int]:
    # A locked file only outranks an otherwise-equal unlocked one when
    # it's genuinely higher quality, not merely tied — being locked is a
    # harder blocker (real, confirmed rejection: "File not shared") than
    # a long queue, so ties go to the candidate that's actually
    # downloadable right now. Among remaining ties (tier + bitrate + lock
    # status all equal), prefer the shorter queue — previously these fell
    # through to incidental list order rather than genuinely preferring
    # the faster candidate.
    return (
        quality_tier(file),
        effective_bitrate(file),
        0 if file.locked else 1,
        -file.queue_length,
    )


def score_candidate(track: Track, file: SoulseekFile) -> float | None:
    """The public form of `_score_candidate`, the same per-candidate
    score `filter_candidates`/select_downloads use internally. The
    manual-search UI's results table shows this per-row so a real
    number backs the ranking it displays, not just an opaque sort
    order. HISTORY §82."""
    return _score_candidate(track, file)


def rank_candidates(files: list[SoulseekFile]) -> list[SoulseekFile]:
    """The public form of the same ranking `select_downloads` uses
    internally (`_sort_key`, best-first: tier, bitrate, lock status,
    queue length). The manual-search UI's results table needs to
    display candidates in this exact order without a second, drifting
    copy of the tiebreak logic. Also filters to DOWNLOADABLE_EXTENSIONS
    before ranking, so an unsupported format (e.g. a peer's .ogg) is
    never listed as pickable — the one gate raw SEARCH results had
    never had at all. HISTORY §82, §94.
    """
    downloadable = [
        file for file in files if is_downloadable_extension(file.extension)
    ]
    return sorted(downloadable, key=_sort_key, reverse=True)


def select_downloads(
        track: Track,
        files: list[SoulseekFile],
        auto_match_threshold: float = AUTO_MATCH_THRESHOLD,
        needs_review_threshold: float = NEEDS_REVIEW_THRESHOLD,
) -> DownloadSelection:
    # needs_review is computed independently of the auto-tier logic below
    # and included unchanged in every return point — the settled/upgrade
    # ranking never considers it, it's purely extra information for
    # callers (download_playlist) to act on when there's no auto
    # candidate at all.
    filtered = filter_candidates(track, files, auto_match_threshold)
    needs_review = find_best_needs_review_candidate(
        track, files, needs_review_threshold, auto_match_threshold,
    )

    if not filtered:
        return DownloadSelection(None, [], needs_review)

    ranked = rank_candidates(filtered)
    top = ranked[0]

    # Locked candidates are never eligible as "settled" — they can't be
    # downloaded at all right now, which is a harder blocker than a long
    # queue, so it's checked separately from is_practical().
    if not top.locked and is_practical(top):
        return DownloadSelection(top, [], needs_review)

    settled_eligible = [
        file for file in ranked if not file.locked and is_practical(file)
    ]

    settled: SoulseekFile | None

    if settled_eligible:
        settled = settled_eligible[0]
    else:
        # Nothing practical among the unlocked candidates — Phase 1
        # fallback, scoped to unlocked only: settle for the best
        # unlocked candidate (still downloadable, just slow) rather than
        # a locked top pick (not downloadable at all right now).
        unlocked = [file for file in ranked if not file.locked]
        settled = unlocked[0] if unlocked else None

    if settled is None:
        # Every filtered candidate is locked — nothing downloadable
        # right now, but the whole ranked list is upgrade-shortlist
        # material for the Phase 3/4 retry cycle.
        return DownloadSelection(
            None, ranked[:MAX_UPGRADE_SHORTLIST], needs_review,
        )

    # Everything ranked ahead of settled (by the same tiebreak-aware key)
    # is genuinely better-or-equal and worth chasing as an upgrade;
    # anything ranked behind it is a downgrade, not an upgrade.
    settled_index = next(i for i, f in enumerate(ranked) if f is settled)
    shortlist = ranked[:settled_index][:MAX_UPGRADE_SHORTLIST]

    return DownloadSelection(settled, shortlist, needs_review)

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mutagen
import numpy as np

from seeker.audio_formats import is_downloadable_extension
from seeker.matching import (
    AUTO_MATCH_THRESHOLD,
    NEEDS_REVIEW_THRESHOLD,
    artist_matches,
    score_title,
)
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track

# "aiff"/"aif" only, deliberately not "aifc" — see audio_formats.py's
# own comment on why AIFF-C isn't automatically lossless the way AIFF
# is. HISTORY §85.
LOSSLESS_EXTENSIONS = {"flac", "wav", "aiff", "aif"}
LOSSY_EXTENSIONS = {"mp3", "m4a", "aac", "ogg"}

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


def find_best_needs_review_candidate(
        track: Track,
        files: list[SoulseekFile],
        needs_review_threshold: float = NEEDS_REVIEW_THRESHOLD,
        auto_match_threshold: float = AUTO_MATCH_THRESHOLD,
) -> tuple[SoulseekFile, float] | None:
    # The Soulseek equivalent of library/matcher.py's needs_review tier:
    # a real, artist-matching candidate that's plausible but not
    # confident enough to auto-download (70 <= score < 90 by default).
    # Purely informational — nothing in this tier is ever requested from
    # slskd by select_downloads/download_playlist; it's surfaced
    # read-only via `seeker check` for a human to go find and grab
    # manually. Returns only the single best-scoring candidate across
    # ALL files (not just the auto-tier-filtered ones), since a track
    # with zero auto-tier candidates would otherwise have nothing left
    # to search here.
    #
    # Both thresholds are plain optional parameters, not read from
    # config here — this module stays as decoupled from config/
    # filesystem concerns as matching.py itself. DownloadService, the
    # one real caller, resolves config-or-default once per
    # download_playlist() run and passes the numbers in explicitly.
    best: tuple[SoulseekFile, float] | None = None

    for file in files:
        score = _score_candidate(track, file)

        if score is None:
            continue

        if not (needs_review_threshold <= score < auto_match_threshold):
            continue

        if best is None or score > best[1]:
            best = (file, score)

    return best


def quality_tier_for_format(extension: str) -> int:
    """Lossless(2)/lossy(1)/unknown(0) tiering keyed by a bare format
    string (e.g. LocalFile.format, which is already stored exactly
    this way — see library/scanner.py) rather than a SoulseekFile.
    Factored out so the local-duplicate detector can reuse this
    project's one real "is this file better" ranking instead of
    writing a third copy of it — same drift lesson matching.py's own
    consolidation already taught this codebase once. HISTORY §5."""
    normalized = extension.lower().lstrip(".")

    if normalized in LOSSLESS_EXTENSIONS:
        return 2

    if normalized in LOSSY_EXTENSIONS:
        return 1

    return 0


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
) -> tuple[
    SoulseekFile | None,
    list[SoulseekFile],
    tuple[SoulseekFile, float] | None,
]:
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
        return (None, [], needs_review)

    ranked = rank_candidates(filtered)
    top = ranked[0]

    # Locked candidates are never eligible as "settled" — they can't be
    # downloaded at all right now, which is a harder blocker than a long
    # queue, so it's checked separately from is_practical().
    if not top.locked and is_practical(top):
        return (top, [], needs_review)

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
        return (None, ranked[:MAX_UPGRADE_SHORTLIST], needs_review)

    # Everything ranked ahead of settled (by the same tiebreak-aware key)
    # is genuinely better-or-equal and worth chasing as an upgrade;
    # anything ranked behind it is a downgrade, not an upgrade.
    settled_index = next(i for i, f in enumerate(ranked) if f is settled)
    shortlist = ranked[:settled_index][:MAX_UPGRADE_SHORTLIST]

    return (settled, shortlist, needs_review)


# --- Local-file quality analysis ---------------------------------------
#
# Everything above this point ranks remote SoulSeek search results;
# this section adds what's missing to rank real files already on disk
# for the duplicate detector — reusing quality_tier_for_format() above
# rather than a third copy of tiering logic, and reading real bitrate/
# bit-depth via mutagen (already a project dependency) plus a real
# clipping heuristic, since a SoulseekFile's remote-reported bit_rate/
# is_variable_bitrate fields don't exist for a file that's just sitting
# on disk — the file itself has to be opened.

# Untuned heuristic threshold, flagged the same as every other constant
# in this codebase — a sample at or above this fraction of full-scale
# (16-bit) counts toward clipping_ratio. Revisit once this sees more
# real library data than item 5's own small real spot-check.
CLIPPING_AMPLITUDE_THRESHOLD = 0.999


@dataclass
class LocalFileQuality:
    tier: int
    bitrate_kbps: int | None
    bit_depth: int | None
    sample_rate: int | None
    # Fraction of samples at/near full-scale amplitude — a heuristic
    # signal that a lossy source was over-compressed/limited before
    # encoding, not a certainty (some masters are legitimately loud).
    clipping_ratio: float
    # Informational only, per the task's own scoping — never a primary
    # signal in any ranking decision. None when pyloudnorm can't
    # measure it (e.g. audio too short/silent for a real ITU-R BS.1770
    # gated measurement).
    integrated_loudness_lufs: float | None


def analyze_local_file_quality(path: str | Path) -> LocalFileQuality:
    extension = Path(path).suffix
    tier = quality_tier_for_format(extension)

    bitrate_kbps: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None

    # mutagen ships no type annotations at all (no py.typed marker, no
    # types-mutagen package on PyPI — same real gap metadata.py's own
    # module docstring already documents); mutagen_file/info are typed
    # Any here rather than scattering per-line ignores across this one
    # small, self-contained function.
    mutagen_file: Any = mutagen.File(str(path))

    if mutagen_file is not None and mutagen_file.info is not None:
        info = mutagen_file.info
        sample_rate = getattr(info, "sample_rate", None)

        # Confirmed live: mutagen 1.48.1's AIFFInfo already computes
        # `bitrate = channels * sample_size * sample_rate` in its own
        # __init__ and exposes it as `.bitrate` — no AIFF-specific
        # branch needed here. HISTORY §85.
        raw_bitrate = getattr(info, "bitrate", None)
        if raw_bitrate:
            bitrate_kbps = int(raw_bitrate // 1000)

        bit_depth = getattr(info, "bits_per_sample", None)

    return LocalFileQuality(
        tier=tier,
        bitrate_kbps=bitrate_kbps,
        bit_depth=bit_depth,
        sample_rate=sample_rate,
        clipping_ratio=_measure_clipping_ratio(path),
        integrated_loudness_lufs=_measure_integrated_loudness(path),
    )


def _measure_clipping_ratio(path: str | Path) -> float:
    # Deferred (PLC0415, suppressed): soundfile is a heavy scientific
    # dependency this module only needs for the rare candidate that
    # reaches quality measurement at all — importing it at module level
    # would put it on every startup path that merely imports quality.py.
    import soundfile as sf  # noqa: PLC0415

    data, _ = sf.read(str(path), dtype="int16", always_2d=True)

    if data.size == 0:
        return 0.0

    full_scale = np.iinfo(np.int16).max
    threshold = CLIPPING_AMPLITUDE_THRESHOLD * full_scale
    clipped_samples = np.abs(data) >= threshold

    return float(clipped_samples.sum()) / float(data.size)


def _measure_integrated_loudness(path: str | Path) -> float | None:
    # Deferred (PLC0415, suppressed) for the same reason as
    # _measure_clipping_ratio above: pyloudnorm/soundfile are heavy
    # scientific dependencies this module only needs this deep in the
    # rare quality-measurement path, not on every import of quality.py.
    import pyloudnorm  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    data, rate = sf.read(str(path))

    try:
        meter = pyloudnorm.Meter(rate)
        loudness = float(meter.integrated_loudness(data))
    except ValueError:
        # pyloudnorm raises on audio too short for a real ITU-R
        # BS.1770 gated measurement — informational-only, so a missing
        # value here is fine, not an error worth surfacing.
        return None

    # Confirmed live, not assumed: digital silence doesn't raise —
    # it returns a real, mathematically-correct -inf (ln(0) diverging),
    # which isn't a meaningful value to show or compare against other
    # files. NaN is the same "not meaningful" case for any other
    # degenerate input.
    if not math.isfinite(loudness):
        return None

    return loudness

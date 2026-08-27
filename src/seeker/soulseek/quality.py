import re

from seeker.audio_formats import AUDIO_EXTENSIONS
from seeker.matching import (
    AUTO_MATCH_THRESHOLD,
    artist_matches,
    score_title,
)
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track


LOSSLESS_EXTENSIONS = {"flac", "wav"}
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


def filter_candidates(
        track: Track,
        files: list[SoulseekFile],
) -> list[SoulseekFile]:
    candidates = []

    for file in files:
        if f".{file.extension.lower()}" not in AUDIO_EXTENSIONS:
            continue

        normalized_title = normalize_soulseek_title(file.filename)

        if not artist_matches(track.artist, normalized_title):
            continue

        score = score_title(track.artist, track.title, normalized_title)

        if score < AUTO_MATCH_THRESHOLD:
            continue

        candidates.append(file)

    return candidates


def quality_tier(file: SoulseekFile) -> int:
    extension = file.extension.lower()

    if extension in LOSSLESS_EXTENSIONS:
        return 2

    if extension in LOSSY_EXTENSIONS:
        return 1

    return 0


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


def select_downloads(
        track: Track,
        files: list[SoulseekFile],
) -> tuple[SoulseekFile | None, list[SoulseekFile]]:
    filtered = filter_candidates(track, files)

    if not filtered:
        return (None, [])

    ranked = sorted(filtered, key=_sort_key, reverse=True)
    top = ranked[0]

    # Locked candidates are never eligible as "settled" — they can't be
    # downloaded at all right now, which is a harder blocker than a long
    # queue, so it's checked separately from is_practical().
    if not top.locked and is_practical(top):
        return (top, [])

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
        return (None, ranked[:MAX_UPGRADE_SHORTLIST])

    # Everything ranked ahead of settled (by the same tiebreak-aware key)
    # is genuinely better-or-equal and worth chasing as an upgrade;
    # anything ranked behind it is a downgrade, not an upgrade.
    settled_index = next(i for i, f in enumerate(ranked) if f is settled)
    shortlist = ranked[:settled_index][:MAX_UPGRADE_SHORTLIST]

    return (settled, shortlist)

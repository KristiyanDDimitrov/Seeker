"""Build a filename from a track's canonical Spotify metadata, matching
what the file's own tags say rather than whatever a SoulSeek peer named
it.

Roadmap item 67 (Phase 6.1) — a pure function, no I/O, no Qt, no DB
access, so it's directly testable and can't grow a second copy the way
matching.py's own consolidation history (see CLAUDE.md) already
documents happening once for artist/title matching. Composes with
filename_sanitize.py's shared character-cleaning logic rather than
duplicating it.
"""

import re

from seeker.filename_sanitize import clean_path_component

# Convention, decided (roadmap item 67): "{artists} - {title}.{ext}".
# artists is every Spotify artist, in Spotify's own credited order,
# joined with ", " — Track.artist already holds exactly this (item 9).
# title is Spotify's title verbatim, which already carries "(feat. X)"
# when Spotify credits it that way.

# Matches a parenthesized feat/ft/featuring clause — the overwhelming
# real-world convention for how Spotify (and most metadata sources)
# credit a featured artist inside a title string.
_FEAT_CLAUSE_PATTERN = re.compile(
    r"\((?:feat\.|ft\.|featuring)\s+([^)]+)\)", re.IGNORECASE,
)

# Filesystem limit this targets — 255 bytes is the real ceiling on most
# modern filesystems (APFS, ext4, NTFS all use it, though NTFS's is
# technically UTF-16 code units, not UTF-8 bytes — untested against a
# real NTFS volume, a disclosed gap, not assumed correct). UTF-8 bytes,
# not characters: this library's own accented artist/track names (René
# Amesz, Mangueleña, ...) make that difference real, not theoretical —
# see docs/HISTORY.md item 39's own 0-byte-file investigation for two
# real examples already in this exact library.
MAX_FILENAME_BYTES = 255


def build_track_filename(
        artists: str, title: str, extension: str,
) -> str | None:
    """Returns the target filename, or None when there's nothing usable
    to build one from (empty/whitespace-only artist or title) — the
    caller's job to leave the file alone in that case, never produce a
    filename like " - .flac".
    """
    artists = artists.strip()
    title = title.strip()

    if not artists or not title:
        return None

    artist_list = [name.strip() for name in artists.split(", ") if name.strip()]

    if not artist_list:
        return None

    # feat-dedupe heuristic (roadmap item 67): if an artist beyond the
    # first is already named inside the title's own "(feat. X)" clause,
    # drop it from the artist prefix — avoids "A, B - Title (feat. B)".
    # Always keeps the first artist regardless. Real example from this
    # library: Spotify credits "A-Cray, Zigi SC" as the artist for
    # "Bit Perfect (Original Mix)" with no feat clause at all (nothing
    # to dedupe there); a track that DOES carry one, e.g. artists
    # "Alex Hoing, Sebastian Reza, Bluckther" with a hypothetical title
    # "La Mangueleña (feat. Bluckther)", would drop "Bluckther" from the
    # prefix, producing "Alex Hoing, Sebastian Reza - La Mangueleña
    # (feat. Bluckther).mp3" instead of repeating the name twice.
    feat_match = _FEAT_CLAUSE_PATTERN.search(title)
    feat_text = feat_match.group(1).lower() if feat_match else ""

    kept_artists = [artist_list[0]]
    for artist in artist_list[1:]:
        if feat_text and artist.lower() in feat_text:
            continue
        kept_artists.append(artist)

    artist_prefix = ", ".join(kept_artists)
    ext = extension.lower().lstrip(".")

    base = clean_path_component(f"{artist_prefix} - {title}")
    # Collapse any whitespace run (illegal-char replacement above can
    # itself introduce runs, e.g. "A / B" -> "A - B" colliding with the
    # literal " - " separator) into a single space.
    base = re.sub(r"\s+", " ", base).strip()

    if not base:
        return None

    return f"{_truncate_to_byte_budget(base, ext)}.{ext}"


def _truncate_to_byte_budget(base: str, ext: str) -> str:
    # The extension is never touched — only base (artist + title) gives
    # up bytes to fit MAX_FILENAME_BYTES.
    suffix_bytes = len(f".{ext}".encode("utf-8"))
    budget = MAX_FILENAME_BYTES - suffix_bytes

    encoded = base.encode("utf-8")

    if len(encoded) <= budget:
        return base

    truncated = encoded[:budget]

    # Never split a multi-byte UTF-8 character in half.
    while truncated:
        try:
            decoded = truncated.decode("utf-8")
            break
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    else:
        decoded = ""

    # A truncation landing mid-word or right after the separator is
    # still a valid filename either way — no attempt to truncate on a
    # word boundary, matching this codebase's other length caps (e.g.
    # filename_sanitize.MAX_LENGTH), which don't either.
    return decoded.rstrip(" .-")

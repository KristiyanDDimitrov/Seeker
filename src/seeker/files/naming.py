"""Build a filename from a track's canonical Spotify metadata, matching
what the file's own tags say rather than whatever a SoulSeek peer named
it, and clean a peer's own name for the placement that comes first.

A pure function, no I/O, no Qt, no DB access, so it's directly
testable and stays the one copy of the naming rule. Composes with
files/sanitize.py's shared character-cleaning logic rather than
duplicating it. See HISTORY §67.
"""

import re
import unicodedata

from seeker.files.sanitize import clean_path_component

# Convention: "{artists} - {title}.{ext}". artists is every Spotify
# artist, in Spotify's own credited order, joined with ", " —
# Track.artist already holds exactly this (HISTORY §9).
# title is Spotify's title verbatim, which already carries "(feat. X)"
# when Spotify credits it that way.

# Matches a parenthesized feat/ft/featuring clause — the overwhelming
# real-world convention for how Spotify (and most metadata sources)
# credit a featured artist inside a title string.
_FEAT_CLAUSE_PATTERN = re.compile(
    r"\((?:feat\.|ft\.|featuring)\s+([^)]+)\)", re.IGNORECASE,
)

# 255 UTF-8 bytes is ext4's limit, the strictest a library drive is
# likely to have: APFS counts 255 characters instead (observed: it took
# a 504-byte name of "é"), and NTFS and ExFAT count UTF-16 units
# (UNVERIFIED, no such volume tested). A name within the byte budget
# fits all of them. Bytes, not characters: this library's own accented
# names (René Amesz, Mangueleña, ...) make the difference real
# (HISTORY §39).
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

    artist_list = [
            name.strip() for name in artists.split(", ") if name.strip()
    ]

    if not artist_list:
        return None

    # feat-dedupe heuristic: if an artist beyond the first is already
    # named inside the title's own "(feat. X)" clause, drop it from the
    # artist prefix — avoids "A, B - Title (feat. B)". Always keeps the
    # first artist regardless. Real example from this library: Spotify
    # credits "A-Cray, Zigi SC" as the artist for "Bit Perfect (Original
    # Mix)" with no feat clause at all (nothing to dedupe there); a
    # track that DOES carry one, e.g. artists "Alex Hoing, Sebastian
    # Reza, Bluckther" with a hypothetical title "La Mangueleña (feat.
    # Bluckther)", would drop "Bluckther" from the prefix, producing
    # "Alex Hoing, Sebastian Reza - La Mangueleña (feat. Bluckther).mp3"
    # instead of repeating the name twice.
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


# Control (Cc) and format (Cf) characters: invisible in a file browser,
# and Cf holds the bidi overrides (U+202E makes "song\u202egpj.mp3" read
# as "song3pm.jpg") and zero-width characters.
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf"})

_FALLBACK_STEM = "Untitled"


def clean_peer_filename(basename: str) -> str:
    """A SoulSeek peer's file name, made safe to place in a library.

    Drops control and format characters, then applies
    `clean_path_component` (no separator or reserved character, never
    a leading dot) and the 255-byte budget, keeping the extension. Only
    the placed name changes: slskd wrote the raw name, and locating the
    finished file still matches that.
    """
    visible = "".join(
        character for character in basename
        if unicodedata.category(character) not in _INVISIBLE_CATEGORIES
    )
    # Split on the last dot first, as the extension gate does
    # (client.derive_extension): cleaning the whole name would turn
    # ".mp3" into "_mp3", a file the scanner never indexes.
    stem, dot, ext = visible.rpartition(".")
    if not dot:
        stem, ext = visible, ""
    stem = clean_path_component(stem) or _FALLBACK_STEM
    ext = clean_path_component(ext)

    if ext:
        stem = _truncate_to_byte_budget(stem, ext) or _FALLBACK_STEM
        return f"{stem}.{ext}"
    return _truncate_to_byte_budget(stem, "") or _FALLBACK_STEM


def _truncate_to_byte_budget(base: str, ext: str) -> str:
    # The extension is never touched — only base (artist + title) gives
    # up bytes to fit MAX_FILENAME_BYTES.
    suffix_bytes = len(f".{ext}".encode())
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
    # sanitize.MAX_LENGTH), which don't either.
    return decoded.rstrip(" .-")

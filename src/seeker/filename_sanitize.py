"""Sanitize a string for safe use as a single filesystem path component
(one folder or file name — never a full path with its own separators).

Used by DownloadService's destination resolution (roadmap item 6) to
turn a playlist name into a real, safe folder name — a real playlist
in this project's own database, "240KM/H", contains a literal '/' that
would otherwise be silently interpreted as a path separator rather
than part of the name (creating a "240KM" folder with an "H"
subfolder inside, not a single "240KM/H"-named one).
"""

import re

# Characters invalid (or actively dangerous to interpret positionally)
# in a path component on at least one of macOS/Windows/Linux: both
# real path separators, Windows' reserved punctuation, and ASCII
# control characters (0x00-0x1F). Not scoped to Windows-only concerns
# even though this app's own Windows packaging is still unverified
# (CLAUDE.md item 36) — a macOS-only user can still end up moving a
# library onto a Windows-formatted drive.
_INVALID_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Untuned constant — a generous ceiling well under real filesystem
# limits (255 bytes on most modern filesystems), just a sanity bound
# against a pathologically long playlist name.
MAX_LENGTH = 200

_FALLBACK_NAME = "Untitled"


def clean_path_component(name: str) -> str:
    """The part of sanitization that has nothing to do with length:
    illegal-character replacement plus the Windows trailing-dot/space
    strip. Factored out (roadmap item 67, Phase 6.1) so
    filename_format.py::build_track_filename can reuse this exact
    cleaning logic under its own, different length rule (255 UTF-8
    BYTES, not this module's MAX_LENGTH characters) without a second
    copy of the illegal-character regex — the same "shared thing lives
    in exactly one place" discipline this module's own docstring
    already follows.
    """
    sanitized = _INVALID_CHARS_PATTERN.sub("-", name)

    # Windows silently strips trailing dots/spaces from a folder name
    # at creation time — a real, confirmed failure mode (not merely
    # cosmetic) if left in: the folder that actually gets created
    # doesn't match the name this app thinks it just used, and a later
    # lookup by the original (unstripped) name would miss it.
    return sanitized.rstrip(" .")


def sanitize_path_component(name: str) -> str:
    """Replace anything unsafe with '-', strip Windows-illegal trailing
    dots/spaces, and fall back to a real, non-empty name if nothing
    usable survives (e.g. a name that was entirely invalid characters).
    """
    sanitized = clean_path_component(name)
    sanitized = sanitized[:MAX_LENGTH].rstrip(" .")

    return sanitized or _FALLBACK_NAME

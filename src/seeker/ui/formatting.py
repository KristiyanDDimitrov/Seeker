"""Shared presentation-layer formatting: timestamps, file sizes,
transfer speeds, durations. One place, per this project's standing
"shared thing lives in exactly one place" discipline (matching.py,
download_dedup.py, file_deletion.py) — used by the Dashboard's tagged-
at display, the History page, and the Downloads tab's ETA/speed
display.

No DB access, no repository imports — pure functions only, safe to
call from any presentation-layer widget without violating the
layering rule.
"""

from datetime import datetime


def format_timestamp(value: str | None) -> str:
    """Render a stored ISO 8601 timestamp (this codebase's own standing
    convention — matched_at/completed_at/tagged_at are all real,
    timezone-AWARE UTC strings via `datetime.now(timezone.utc)
    .isoformat()`, never naive) in the viewer's local time. `None` (or
    an unparseable value, defensively) renders as "Never" rather than
    raising — every call site here is display-only.
    """
    if value is None:
        return "Never"

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "Never"

    # A genuinely naive value would be a data bug elsewhere (this
    # codebase always writes timezone-aware UTC) — treat it as already
    # local rather than guessing a timezone that isn't ours to guess.
    local = parsed.astimezone() if parsed.tzinfo is not None else parsed

    return local.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")


# Untuned constant, same convention as every threshold elsewhere in
# this codebase — the binary-vs-decimal boundary for "MB" display.
# 1024-based (binary) to match what Finder/Explorer/most download
# tools already show for file sizes.
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_file_size(size_bytes: int | float | None) -> str:
    if size_bytes is None:
        return "?"

    size = float(size_bytes)

    for unit in _SIZE_UNITS:
        if size < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024

    return f"{size:.1f} {_SIZE_UNITS[-1]}"  # pragma: no cover - unreachable


def format_speed(bytes_per_second: float | None) -> str:
    if bytes_per_second is None or bytes_per_second <= 0:
        return "?"

    return f"{format_file_size(bytes_per_second)}/s"


def format_duration_seconds(seconds: float) -> str:
    """`42` -> "42s", `125` -> "2m 5s", `3725` -> "1h 2m". Never
    negative — a caller passing a stale/negative remaining-time value
    gets "0s" rather than a confusing negative duration.
    """
    total_seconds = max(round(seconds), 0)

    if total_seconds < 60:
        return f"{total_seconds}s"

    minutes, secs = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"

    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"

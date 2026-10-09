"""When a periodic job is due: the daily sweep, the update check."""
from datetime import datetime, timedelta


def is_due(now: datetime, last: str | None, interval: timedelta) -> bool:
    """Whether a job last run at `last` (UTC ISO-8601, None if never)
    is due again at `now` (timezone-aware).

    Due when it has never run, or `interval` has passed. A `last` that
    does not parse as an aware time, or lies in the future (the clock
    went back), counts as due: the job's own stamp then repairs it.
    """
    if last is None:
        return True

    try:
        last_time = datetime.fromisoformat(last)
    except ValueError:
        return True

    if last_time.tzinfo is None or last_time > now:
        return True

    return now - last_time >= interval

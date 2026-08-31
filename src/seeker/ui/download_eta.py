"""In-memory download speed/ETA estimation for the Downloads tab.

Deliberately presentation-only, per Task 2's own scoping — no DB
changes, no persistence. `DownloadEtaTracker` is fed one (bytes,
timestamp) sample per `download_request_id` on every real
`poll_downloads()` cycle (MainWindow's 20s `BACKEND_POLL_INTERVAL_MS`
timer, not the 2s display-refresh one — sampling on the 2s tick would
just re-diff against the same DB row `poll_downloads()` hasn't touched
yet, producing a meaningless zero-delta sample). `describe()` is then
called on every 2s render tick to turn the last two samples into a
speed/ETA string, with no new I/O.
"""

from dataclasses import dataclass
from datetime import datetime

# format_duration_seconds now lives in ui/formatting.py, shared with the
# History page and the Downloads tab's other size/speed display — this
# re-export keeps every existing call site (including this module's own
# describe() below and every test importing format_eta_seconds from
# here) byte-for-byte unchanged.
from seeker.ui.formatting import format_duration_seconds as format_eta_seconds


@dataclass
class _Sample:
    bytes_transferred: int
    timestamp: datetime


# Untuned constant, same convention as every other threshold in this
# codebase — how many consecutive same-bytes samples (spanning this
# many real 20s poll cycles) before a download is reported "Stalled"
# instead of showing a frozen, increasingly-wrong ETA. Also doubles as
# the cap on how many samples are retained per request — describe()
# never needs more than this many.
STALL_SAMPLE_COUNT = 3


class DownloadEtaTracker:
    """Keyed by `download_requests.id`. Pure in-memory state — safe to
    recreate per MainWindow session, and deliberately never persisted.
    """

    def __init__(self) -> None:
        self._history: dict[int, list[_Sample]] = {}

    def record(
            self,
            request_id: int,
            bytes_transferred: int,
            timestamp: datetime,
    ) -> None:
        samples = self._history.setdefault(request_id, [])
        samples.append(_Sample(bytes_transferred, timestamp))
        # Bounded even without eviction — describe() only ever looks at
        # the last STALL_SAMPLE_COUNT samples.
        del samples[:-STALL_SAMPLE_COUNT]

    def evict_except(self, active_request_ids: set[int]) -> None:
        """Drop every tracked id that's no longer in the current
        get_active_downloads() result — a completed/failed/superseded
        request has nothing left to estimate, and keeping it around
        forever would grow this dict unboundedly over a long session
        (the exact leak class items 29/32 already hunted once for real
        Qt objects — this is the same discipline applied here)."""
        for request_id in list(self._history):
            if request_id not in active_request_ids:
                del self._history[request_id]

    def describe(self, request_id: int, total_bytes: int) -> str:
        samples = self._history.get(request_id, [])

        if len(samples) < 2:
            return "Calculating…"

        if _is_stalled(samples):
            return "Stalled"

        latest, previous = samples[-1], samples[-2]
        delta_bytes = latest.bytes_transferred - previous.bytes_transferred
        delta_seconds = (latest.timestamp - previous.timestamp).total_seconds()

        if delta_bytes <= 0 or delta_seconds <= 0:
            # Not enough evidence of real progress yet to estimate a
            # speed — not necessarily stalled (see _is_stalled's own,
            # stricter, multi-sample threshold above), just unknown.
            return "Calculating…"

        speed = delta_bytes / delta_seconds
        remaining = max(total_bytes - latest.bytes_transferred, 0)

        return format_eta_seconds(remaining / speed)


def _is_stalled(samples: list[_Sample]) -> bool:
    if len(samples) < STALL_SAMPLE_COUNT:
        return False

    recent = samples[-STALL_SAMPLE_COUNT:]
    return len({sample.bytes_transferred for sample in recent}) == 1

"""In-memory upload speed estimation for the Sharing page's Uploads
table — roadmap item 62 (Phase 7.6).

Deliberately a SEPARATE tracker from DownloadEtaTracker (ui/download_eta.py),
not a reuse of it, even though the sampling shape is nearly identical:
DownloadEtaTracker is keyed by `download_requests.id`, a real DB primary
key. An upload has no such row in this app's own database at all — it's
purely live slskd-side state, so this tracker is keyed by
`(username, filename)` instead, the same real, stable pairing
`download_dedup.py` already uses to identify one candidate transfer
elsewhere in this codebase. Sharing that keyspace with DownloadEtaTracker
would risk a real collision (an int download_requests.id could coincide
with... nothing, since the types differ, but conflating "this app's own
download" state with "a peer's live upload of MY files" is a real
category error worth keeping structurally impossible, not just avoided
by convention).
"""

from dataclasses import dataclass
from datetime import datetime

from seeker.ui.formatting import format_duration_seconds as format_eta_seconds

# Same convention/value as DownloadEtaTracker's STALL_SAMPLE_COUNT —
# consecutive same-bytes samples (each one real BACKEND_POLL_INTERVAL_MS
# tick apart) before an upload is reported "Stalled" rather than a
# frozen, increasingly-wrong ETA.
STALL_SAMPLE_COUNT = 3

UploadKey = tuple[str, str]


@dataclass
class _Sample:
    bytes_transferred: int
    timestamp: datetime


class UploadEtaTracker:
    def __init__(self) -> None:
        self._history: dict[UploadKey, list[_Sample]] = {}

    def record(
            self,
            key: UploadKey,
            bytes_transferred: int,
            timestamp: datetime,
    ) -> None:
        samples = self._history.setdefault(key, [])
        samples.append(_Sample(bytes_transferred, timestamp))
        del samples[:-STALL_SAMPLE_COUNT]

    def evict_except(self, active_keys: set[UploadKey]) -> None:
        for key in list(self._history):
            if key not in active_keys:
                del self._history[key]

    def describe(self, key: UploadKey, total_bytes: int | None) -> str:
        samples = self._history.get(key, [])

        if len(samples) < 2:
            return "Calculating…"

        if _is_stalled(samples):
            return "Stalled"

        latest, previous = samples[-1], samples[-2]
        delta_bytes = latest.bytes_transferred - previous.bytes_transferred
        delta_seconds = (latest.timestamp - previous.timestamp).total_seconds()

        if delta_bytes <= 0 or delta_seconds <= 0 or total_bytes is None:
            return "Calculating…"

        remaining = max(total_bytes - latest.bytes_transferred, 0)
        speed = delta_bytes / delta_seconds

        return format_eta_seconds(remaining / speed)


def _is_stalled(samples: list[_Sample]) -> bool:
    if len(samples) < STALL_SAMPLE_COUNT:
        return False

    recent = samples[-STALL_SAMPLE_COUNT:]
    return len({sample.bytes_transferred for sample in recent}) == 1

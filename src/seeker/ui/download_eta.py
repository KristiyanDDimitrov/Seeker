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
from enum import Enum, auto

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


class _ContributionState(Enum):
    """A single download's real, current relationship to an ETA
    estimate — factored out of describe() (Task 2) so aggregate() (Task
    9) can classify every active download the same way describe()
    already does for one, instead of re-deriving the same three cases a
    second time from scratch.
    """
    CALCULATING = auto()  # < 2 samples, or no positive progress yet
    STALLED = auto()
    CONTRIBUTING = auto()  # has a real, current speed


@dataclass
class _Contribution:
    state: _ContributionState
    # speed/latest_bytes are only ever set together, and only when
    # state is CONTRIBUTING — describe()/aggregate() both only read
    # them in that branch.
    speed_bytes_per_second: float | None = None
    latest_bytes_transferred: int | None = None


@dataclass
class AggregateEta:
    """Task 9's aggregate remaining-time estimate across every currently
    active download shown on the Downloads page. Pure data — no Qt —
    so it (and format_aggregate_header() below) can be unit-tested with
    synthetic samples alone.
    """
    eta_seconds: float | None
    transferring_count: int
    # Everything NOT contributing to the estimate — genuinely queued
    # (no bytes yet), still calculating (too few samples), stalled, or
    # missing a known total_bytes entirely. Deliberately one bucket,
    # not several — see format_aggregate_header()'s own docstring for
    # why splitting it further wouldn't give the user anything actionable.
    no_estimate_count: int
    # True only when every non-contributing download is specifically
    # STALLED (not just "hasn't started yet") — distinguishes "waiting
    # for transfers to start" from the more alarming "everything that
    # WAS moving has stopped".
    all_non_contributors_stalled: bool


# Untuned constant, same convention as every other threshold in this
# codebase — the tooltip explaining why queued transfers are excluded
# from the aggregate estimate rather than folded in to produce a
# rounder-looking number. Soulseek queue wait times aren't predictable
# (no reliable "your turn in N minutes" signal exists — see this
# module's own recon note in HISTORY for Task 9), so including them
# would make the estimate look more precise than it actually is.
AGGREGATE_ETA_TOOLTIP = (
    "Queued transfers aren't included in this estimate — Soulseek "
    "queue wait times aren't predictable, so folding them in would "
    "make the number look more precise than it really is."
)


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

    def evict(self, request_id: int) -> None:
        """Drop one tracked id immediately — roadmap item 56 Phase 5.4:
        a row that just reached a terminal status (completed/failed/
        ready_for_review) will never report new progress again, so
        continuing to sample it would eventually misclassify it as
        "Stalled" (3 identical-bytes samples, the same signal a
        genuinely stuck in-progress download would produce) rather than
        just correctly reading as finished. Called the moment a row's
        status is seen to be terminal, not left to evict_except()'s own
        once-per-poll sweep.
        """
        self._history.pop(request_id, None)

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

    def _classify(self, request_id: int) -> _Contribution:
        samples = self._history.get(request_id, [])

        if len(samples) < 2:
            return _Contribution(_ContributionState.CALCULATING)

        if _is_stalled(samples):
            return _Contribution(_ContributionState.STALLED)

        latest, previous = samples[-1], samples[-2]
        delta_bytes = latest.bytes_transferred - previous.bytes_transferred
        delta_seconds = (latest.timestamp - previous.timestamp).total_seconds()

        if delta_bytes <= 0 or delta_seconds <= 0:
            # Not enough evidence of real progress yet to estimate a
            # speed — not necessarily stalled (see _is_stalled's own,
            # stricter, multi-sample threshold above), just unknown.
            return _Contribution(_ContributionState.CALCULATING)

        return _Contribution(
            _ContributionState.CONTRIBUTING,
            speed_bytes_per_second=delta_bytes / delta_seconds,
            latest_bytes_transferred=latest.bytes_transferred,
        )

    def describe(self, request_id: int, total_bytes: int) -> str:
        contribution = self._classify(request_id)

        if contribution.state == _ContributionState.CALCULATING:
            return "Calculating…"

        if contribution.state == _ContributionState.STALLED:
            return "Stalled"

        assert contribution.speed_bytes_per_second is not None
        assert contribution.latest_bytes_transferred is not None
        remaining = max(
            total_bytes - contribution.latest_bytes_transferred, 0,
        )

        return format_eta_seconds(
            remaining / contribution.speed_bytes_per_second,
        )

    def aggregate(
            self, downloads: list[tuple[int, int | None]],
    ) -> AggregateEta:
        """downloads: (request_id, total_bytes) for every currently
        active download shown on the Downloads page — queued and
        stalled ones included, not just ones with a real speed. Only
        actively-transferring downloads (>= 2 samples, a positive
        latest delta, not stalled, AND a known total_bytes to measure
        "remaining" against) contribute to the estimate itself; every
        other download is counted but not included in the sum.
        """
        total = len(downloads)
        total_remaining = 0
        total_speed = 0.0
        contributing = 0
        stalled = 0

        for request_id, total_bytes in downloads:
            if total_bytes is None:
                # No known size to measure "remaining bytes" against —
                # can't contribute regardless of transfer state. Not
                # counted toward `stalled` either: an unknown size
                # isn't evidence the transfer has stopped.
                continue

            contribution = self._classify(request_id)

            if contribution.state == _ContributionState.CONTRIBUTING:
                assert contribution.speed_bytes_per_second is not None
                assert contribution.latest_bytes_transferred is not None
                total_remaining += max(
                    total_bytes - contribution.latest_bytes_transferred, 0,
                )
                total_speed += contribution.speed_bytes_per_second
                contributing += 1
            elif contribution.state == _ContributionState.STALLED:
                stalled += 1

        no_estimate_count = total - contributing

        if contributing == 0:
            return AggregateEta(
                eta_seconds=None,
                transferring_count=0,
                no_estimate_count=no_estimate_count,
                all_non_contributors_stalled=(
                    no_estimate_count > 0 and stalled == no_estimate_count
                ),
            )

        # contributing > 0 implies total_speed > 0 — every CONTRIBUTING
        # classification has a strictly positive delta_bytes/delta_seconds
        # (see _classify above), so this can never divide by zero.
        return AggregateEta(
            eta_seconds=total_remaining / total_speed,
            transferring_count=contributing,
            no_estimate_count=no_estimate_count,
            all_non_contributors_stalled=False,
        )


def format_aggregate_header(result: AggregateEta) -> str:
    """Task 9's Downloads-page header line, e.g. "About 12m 0s
    remaining · 3 transferring · 5 queued (no estimate)". A pure
    function over AggregateEta so it's testable with no Qt, matching
    this module's existing style.

    The non-contributing bucket is always labelled "queued" in the
    header regardless of whether a given download's real DB status is
    literally `queued` — a download that's technically `downloading`
    but has zero bytes yet (or is stalled) reads identically to the
    user either way: "not currently making progress I can estimate",
    which is the only thing this header is trying to communicate.
    """
    if result.eta_seconds is not None:
        headline = f"About {format_eta_seconds(result.eta_seconds)} remaining"
    elif result.all_non_contributors_stalled:
        headline = "All active transfers stalled"
    else:
        headline = "Waiting for transfers to start"

    parts = [headline, f"{result.transferring_count} transferring"]
    if result.no_estimate_count > 0:
        parts.append(f"{result.no_estimate_count} queued (no estimate)")

    return " · ".join(parts)


def _is_stalled(samples: list[_Sample]) -> bool:
    if len(samples) < STALL_SAMPLE_COUNT:
        return False

    recent = samples[-STALL_SAMPLE_COUNT:]
    return len({sample.bytes_transferred for sample in recent}) == 1

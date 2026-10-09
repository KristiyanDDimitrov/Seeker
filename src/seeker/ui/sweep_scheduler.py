"""Runs the daily sweep (`soulseek/sweep.py`) while Seeker is open.

The shell owns the hourly timer and calls `check()` on it, and
`on_backend_poll_reached_slskd()` after every backend poll that reached
slskd. This decides whether a sweep is due and keeps one at a time.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from seeker.application import Application
from seeker.models.sweep_result import SweepResult
from seeker.soulseek.sweep import sweep_due
from seeker.ui.busy_actions import BusyActionRegistry
from seeker.ui.slskd_status import SlskdStatus

logger = logging.getLogger(__name__)

SWEEP_KEY = "sweep"

# How often the shell asks whether a sweep is due. A sweep runs at most
# daily, so an hour is fine-grained enough; turning the sweep on in
# Settings starts the first one within this long.
SWEEP_CHECK_INTERVAL_MS = 60 * 60 * 1000


@dataclass(frozen=True)
class SweepSchedulerHost:
    """What the scheduler needs from the shell: its busy registry (the
    one record of a running sweep), the backend poll's slskd status,
    `MainWindow._run_busy_worker`, which runs on the shell's pool, and
    the tray's summary of a sweep that requested downloads."""
    application: Application
    busy_actions: BusyActionRegistry
    slskd_status: SlskdStatus
    run_busy_worker: Callable[..., None]
    notify_requested: Callable[[int], None]


class SweepScheduler:
    def __init__(self, host: SweepSchedulerHost) -> None:
        self._host = host
        # Set on quit: a running sweep ends before its next search, and
        # no other starts.
        self._stop = threading.Event()
        self._slskd_answered = False

    def on_backend_poll_reached_slskd(self) -> None:
        """The startup check: the first poll that reached slskd."""
        if self._slskd_answered:
            return

        self._slskd_answered = True
        self.check()

    def check(self) -> None:
        """Starts a sweep when one is due and none is running."""
        if self._stop.is_set() or not self._slskd_answered:
            return

        if self._host.busy_actions.is_running(SWEEP_KEY):
            return

        application = self._host.application

        if not application.soulseek_configured:
            return

        # An outage would fail the first search; the poll that sees
        # slskd answer again does not restart the sweep, the next
        # hourly check does.
        if self._host.slskd_status.unreachable_message is not None:
            return

        settings = application.settings

        if not sweep_due(
                datetime.now(UTC), settings.last_sweep_at,
                settings.auto_sweep_enabled,
        ):
            return

        logger.info("Daily sweep due: starting it.")
        stop = self._stop
        self._host.run_busy_worker(
            SWEEP_KEY, None,
            lambda: application.sweep_service.run_sweep(stop),
            on_finished=self._on_sweep_finished,
            on_error=self._on_sweep_failed,
        )

    def stop(self) -> None:
        """Called on quit (see `_stop`)."""
        self._stop.set()

    def _on_sweep_finished(self, result: SweepResult) -> None:
        # One notice for a sweep that found something; one that found
        # nothing stays silent. The service logs either at INFO.
        if result.requested:
            self._host.notify_requested(len(result.requested))

    def _on_sweep_failed(self, message: str) -> None:
        # An outage reaches the user through the backend poll's own
        # notice; this only records that the sweep gave up.
        logger.warning("Daily sweep failed: %s", message)

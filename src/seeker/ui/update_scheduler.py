"""Runs the automatic update check (`update_check.py`) at startup.

The shell calls `run()` once, after construction. This decides whether
a check is due, stamps it, and runs it on the shell's pool; only an
available update reaches the user.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from seeker.application import Application
from seeker.update_check import (
    UpdateCheckResult,
    UpdateStatus,
    check_for_update,
    update_check_due,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateSchedulerHost:
    """What the scheduler needs from the shell: a way to run work on
    its pool (`run_worker` bound to `MainWindow.thread_pool`) and what
    to do with an available update (the tray notice and the Help menu
    entry)."""
    application: Application
    run_worker: Callable[..., object]
    on_update_available: Callable[[UpdateCheckResult], None]


class UpdateScheduler:
    def __init__(self, host: UpdateSchedulerHost) -> None:
        self._host = host

    def run(self) -> None:
        """The startup check: runs one when enabled and due."""
        application = self._host.application
        settings = application.settings
        now = datetime.now(UTC)

        if not update_check_due(
                now, settings.last_update_check_at, settings.auto_update_check,
        ):
            return

        # Stamped before the request, so a check counts whatever it
        # returns: at most one a day, even offline.
        application.update_settings(last_update_check_at=now.isoformat())
        logger.info("Automatic update check due: asking GitHub.")
        self._host.run_worker(
            check_for_update,
            on_finished=self._on_checked,
            on_error=self._on_failed,
        )

    def _on_checked(self, result: UpdateCheckResult) -> None:
        if result.status is UpdateStatus.UPDATE_AVAILABLE:
            logger.info(
                "Automatic update check: UPDATE_AVAILABLE, %s (installed %s).",
                result.latest_version, result.installed_version,
            )
            self._host.on_update_available(result)
            return

        # Silent: a failure here is not the user's to act on, and Help
        # > Check for updates… shows the same answer on request.
        logger.info(
            "Automatic update check: %s%s", result.status.name,
            f" ({result.reason})" if result.reason else "",
        )

    def _on_failed(self, message: str) -> None:
        # check_for_update() never raises; this covers run_worker's own
        # dispatch failing.
        logger.warning("Automatic update check failed: %s", message)

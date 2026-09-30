"""Whether slskd answered the last backend poll, and the Start slskd
action every outage notice offers (HISTORY §151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QAbstractButton

if TYPE_CHECKING:
    # context.py imports SlskdStatus from here at runtime.
    from seeker.ui.notice import FeedbackTarget
    from seeker.ui.pages.context import PageContext

START_SLSKD_KEY = "start_slskd"

START_SLSKD_TEXT = "Start slskd"

SLSKD_STARTING_MESSAGE = (
    "slskd is starting. Downloads resume as soon as it answers."
)


class SlskdStatus(QObject):
    """Owned by the shell (`MainWindow.slskd_status`) and written only by
    its backend poll; Dashboard and Downloads read it through
    `PageContext.slskd_status`. `changed` fires on an edge only, and the
    `mark_*` methods return whether this call was one, so a caller can
    act once per outage rather than once per poll."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._unreachable_message: str | None = None

    @property
    def unreachable_message(self) -> str | None:
        return self._unreachable_message

    def mark_unreachable(self, message: str) -> bool:
        if self._unreachable_message is not None:
            return False

        self._unreachable_message = message
        self.changed.emit()
        return True

    def mark_reachable(self) -> bool:
        if self._unreachable_message is None:
            return False

        self._unreachable_message = None
        self.changed.emit()
        return True


def start_slskd(
        context: PageContext,
        button: QAbstractButton,
        feedback: FeedbackTarget,
) -> None:
    """Run `Application.restart_slskd` for an outage notice's action,
    reporting on the page it was started from. The outage itself clears
    on the next poll that reaches slskd, not here: the container takes
    a few seconds to answer after Compose returns."""
    if context.busy_actions.is_running(START_SLSKD_KEY):
        return

    context.run_busy_worker(
        START_SLSKD_KEY, button, context.application.restart_slskd,
        status_label=feedback.status_label,
        on_finished=lambda _: feedback.show_outcome(
            SLSKD_STARTING_MESSAGE, kind="success",
        ),
        on_error=feedback.show_error,
    )

"""Whether slskd answered the last backend poll, and the Start slskd
action every outage notice offers (HISTORY §151)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QAbstractButton

from seeker.error_text import describe_error
from seeker.soulseek.docker_setup import SlskdSetupNeededError
from seeker.ui.settings_window import SETTINGS_TAB_CONNECTIONS

if TYPE_CHECKING:
    # context.py imports SlskdStatus from here at runtime.
    from seeker.application import Application
    from seeker.ui.notice import FeedbackTarget
    from seeker.ui.pages.context import PageContext

START_SLSKD_KEY = "start_slskd"

START_SLSKD_TEXT = "Start slskd"

SLSKD_STARTING_MESSAGE = (
    "slskd is starting. Downloads resume as soon as it answers."
)

OPEN_CONNECTIONS_TEXT = "Open Settings"


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
    a few seconds to answer after Compose returns.

    A refusal Settings → Connections resolves offers to open it there;
    any other failure is a plain error."""
    if context.busy_actions.is_running(START_SLSKD_KEY):
        return

    def open_connections() -> None:
        feedback.notice.dismiss()
        context.open_settings(SETTINGS_TAB_CONNECTIONS)

    def on_finished(refusal: str | None) -> None:
        if refusal is None:
            feedback.show_outcome(SLSKD_STARTING_MESSAGE, kind="success")
        else:
            feedback.show_outcome(
                refusal,
                kind="error",
                action_text=OPEN_CONNECTIONS_TEXT,
                on_action=open_connections,
            )

    context.run_busy_worker(
        START_SLSKD_KEY, button,
        lambda: _restart_or_refusal(context.application),
        status_label=feedback.status_label,
        on_finished=on_finished,
        on_error=feedback.show_error,
    )


def _restart_or_refusal(application: Application) -> str | None:
    """None once slskd is starting; the refusal's text when only
    Settings → Connections can resolve it. Runs on the worker."""
    try:
        application.restart_slskd()
    except SlskdSetupNeededError as refusal:
        return describe_error(refusal)

    return None

import threading
from collections.abc import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from seeker.application import Application
from seeker.ui import help_text
from seeker.ui.plain_text import PlainLabel
from seeker.ui.workers import run_worker


class SpotifyAuthorizationWait(QWidget):
    """Runs one `connect_spotify` attempt, shared by the wizard's
    Connect and Settings' Re-authorize, and shows its Cancel button and
    hint while it waits for the browser.

    The trigger button stays disabled until the attempt ends: the
    callback port is held for the whole wait, so a second attempt could
    only fail to bind it. `trigger_enabled` says what the button should
    be once the attempt is over (the wizard's needs a Client ID).
    """

    def __init__(
            self,
            application: Application,
            thread_pool: QThreadPool,
            trigger_button: QAbstractButton,
            status_label: QLabel,
            trigger_enabled: Callable[[], bool] = lambda: True,
    ) -> None:
        super().__init__()
        self._application = application
        self._thread_pool = thread_pool
        self._trigger_button = trigger_button
        self._status_label = status_label
        self._trigger_enabled = trigger_enabled
        self._cancel: threading.Event | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip(
            help_text.TOOLTIP_CANCEL_SPOTIFY_AUTHORIZATION
        )
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        layout.addWidget(self.cancel_button)

        self.hint_label = PlainLabel(help_text.SPOTIFY_AUTHORIZATION_HINT)
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label, 1)

        self.hide()

    @property
    def is_waiting(self) -> bool:
        return self._cancel is not None

    def start(
            self,
            client_id: str,
            on_connected: Callable[[], None],
            force_reauthorize: bool = False,
            on_error: Callable[[str], None] | None = None,
    ) -> None:
        """`on_error` hears a failed attempt, never a cancelled one:
        the cancellation answers the user's own click, in the status
        label beside it."""
        if self._cancel is not None:
            return

        cancel = threading.Event()
        self._cancel = cancel
        self._trigger_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.show()

        def on_finished(_result: object) -> None:
            self._end()
            on_connected()

        # Not run_worker's button=: its finish handler would re-enable
        # the trigger regardless of trigger_enabled.
        run_worker(
            self._thread_pool,
            lambda: self._application.connect_spotify(
                client_id,
                force_reauthorize=force_reauthorize,
                cancel=cancel,
            ),
            status_label=self._status_label,
            on_finished=on_finished,
            on_error=lambda message: self._on_attempt_failed(
                cancel, message, on_error,
            ),
        )
        self._status_label.setText(help_text.SPOTIFY_AUTHORIZATION_WAITING)

    def _on_attempt_failed(
            self,
            cancel: threading.Event,
            message: str,
            on_error: Callable[[str], None] | None,
    ) -> None:
        self._end()
        if on_error is not None and not cancel.is_set():
            on_error(message)

    def _on_cancel_clicked(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self.cancel_button.setEnabled(False)

    def _end(self) -> None:
        self._cancel = None
        self.hide()
        self._trigger_button.setEnabled(self._trigger_enabled())

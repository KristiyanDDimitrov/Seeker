"""InlineNotice — a persistent, dismissible banner for anything a user
needs to read and act on: errors, warnings, results, confirmations.

Why this exists (found live while building Phase 3, not hypothesized):
`ui/workers.py::run_worker()` clears its target `status_label` to ""
unconditionally at the START of every call, before the background
task even runs. `MainWindow._poll_selected_playlist()` — which passes
`status_label=self.status_label` — runs on both the 2s display-refresh
timer AND after every real backend poll, completely independent of
whatever the user was just shown. So any validation error or tag
result written to that same shared `status_label` had at most ~2
seconds before the next poll tick silently wiped it, regardless of
severity — not a rendering bug, a genuine structural one: a single
shared label was being used for both "ephemeral progress" and
"something the user needs to read." InlineNotice fixes this
structurally, not just by extending a timeout: it lives outside the
poll's reach entirely, and only ever clears when the user dismisses it
or the caller explicitly replaces/clears it.

`status_label` remains for genuinely transient, disposable progress
text ("Syncing...", "Tagging 3 selected track(s)...") — nothing a user
needs to still see a few seconds later belongs there anymore.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from seeker.ui import theme

_KIND_COLORS = {
    "info": theme.ACCENT,
    "success": theme.SUCCESS,
    "warning": theme.WARNING,
    "error": theme.DANGER,
}


class InlineNotice(QWidget):
    """A single persistent banner. Starts hidden; call `show_message()`
    to display, `dismiss()` (or the built-in close button) to hide.
    Add once per page/dialog near the top of its layout — it manages
    its own visibility, so the caller never needs to show/hide the
    widget itself, only call `show_message`/`dismiss`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # A plain QWidget subclass does NOT paint its own stylesheet
        # background/border by default — Qt skips that pass for custom
        # widgets for performance reasons unless told otherwise. Found
        # live: without this, show_message()'s per-instance
        # setStyleSheet() (the colored border/background below) was
        # silently a no-op, rendering as a plain unstyled row.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_SM,
            theme.SPACING_MD, theme.SPACING_SM,
        )
        layout.setSpacing(theme.SPACING_SM)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label, 1)

        self._action_button = QPushButton("")
        self._action_button.setProperty("variant", "primary")
        self._action_button.hide()
        layout.addWidget(self._action_button)
        # Tracked explicitly rather than relying on disconnect()'s own
        # exception behavior to detect "nothing connected yet" — PySide6
        # only emits a RuntimeWarning there, not a catchable exception,
        # so a bare try/except around disconnect() doesn't actually
        # suppress the noise.
        self._action_connected = False

        # Plain ASCII "X" rather than a Unicode "✕"/"×" glyph — the
        # theme's global QPushButton rule (padding: 6px 14px) needs no
        # special-casing for a plain ASCII glyph, and this avoids
        # depending on Unicode multiplication-sign coverage in whatever
        # font a given platform falls back to.
        #
        # Deliberately no setFixedWidth() here — found live that a
        # fixed width narrower than the global QPushButton rule's own
        # horizontal padding (14px + 14px = 28px alone) left zero space
        # for the glyph itself, silently clipping it to nothing. Sized
        # by its own sizeHint (padding + glyph) instead, like every
        # other themed button.
        self._dismiss_button = QPushButton("X")
        self._dismiss_button.setToolTip("Dismiss")
        self._dismiss_button.clicked.connect(self.dismiss)
        layout.addWidget(self._dismiss_button)

        self.hide()

    def show_message(
            self,
            text: str,
            kind: str = "info",
            action_text: str | None = None,
            on_action: Callable[[], None] | None = None,
    ) -> None:
        color = _KIND_COLORS.get(kind, theme.ACCENT)
        self.setStyleSheet(
            f"InlineNotice {{"
            f"  background-color: {theme.BG_SURFACE_2};"
            f"  border: 1px solid {color};"
            f"  border-left: 3px solid {color};"
            f"  border-radius: {theme.RADIUS_CONTROL}px;"
            f"}}"
        )
        self._message_label.setText(text)

        if action_text is not None and on_action is not None:
            self._action_button.setText(action_text)
            if self._action_connected:
                self._action_button.clicked.disconnect()
            self._action_button.clicked.connect(on_action)
            self._action_connected = True
            self._action_button.show()
        else:
            self._action_button.hide()

        self.show()

    def dismiss(self) -> None:
        self.hide()

    def text(self) -> str:
        return self._message_label.text()

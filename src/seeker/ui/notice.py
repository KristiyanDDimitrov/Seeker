"""InlineNotice — a persistent, dismissible banner for anything a user
needs to read and act on: errors, warnings, results, confirmations.

Why this exists: `ui/workers.py::run_worker()` clears its target
`status_label` at the start of every call, so a label shared with any
other caller is wiped by that caller's next run; a periodic caller
wipes it within seconds. InlineNotice lives outside that plumbing: it clears only when
the user dismisses it or the caller replaces it (HISTORY §47).

`status_label` remains for genuinely transient, disposable progress
text ("Syncing…", "Tagging 3 selected track(s)…") — nothing a user
needs to still see a few seconds later belongs there anymore.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker.ui import theme
from seeker.ui.plain_text import PlainLabel
from seeker.ui.widgets import CloseButton

_VALID_KINDS = {"info", "success", "warning", "error"}


class InlineNotice(QWidget):
    """A single persistent banner. Starts hidden; call `show_message()`
    to display, `dismiss()` (or the built-in close button) to hide.
    Add once per page/dialog near the top of its layout, outside any
    scroll area (`pinned_notices`) — it manages its own visibility, so
    the caller never needs to show/hide the widget itself, only call
    `show_message`/`dismiss`.
    """

    # Emitted from dismiss() (both the X button and any programmatic
    # call) so a poll-driven caller can remember "the user dismissed
    # this" instead of blindly re-showing on the next tick. A signal,
    # not a caller reaching into `_dismiss_button` directly — other
    # pages use this widget too and would need the same thing.
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # A plain QWidget subclass does NOT paint its own stylesheet
        # background/border by default — Qt skips that pass for custom
        # widgets for performance reasons unless told otherwise. Found
        # live: without this, the colored border/background (now the
        # global stylesheet's own `InlineNotice[variant="..."]` rules,
        # see show_message — was originally a per-instance
        # setStyleSheet() call) was silently a no-op, rendering as a
        # plain unstyled row.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_SM,
            theme.SPACING_MD, theme.SPACING_SM,
        )
        layout.setSpacing(theme.SPACING_SM)

        self._message_label = PlainLabel("")
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

        self._dismiss_button = CloseButton("Dismiss")
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
        # Never a per-instance setStyleSheet() computed from `kind`,
        # which would bake a concrete hex color into a string a runtime
        # theme switch could never revisit. Routed through the SAME
        # `variant` dynamic-property mechanism QPushButton's
        # primary/danger variants already use — real rules live in
        # theme.py's `InlineNotice[variant="..."]` selectors, re-applied
        # automatically whenever the global stylesheet changes.
        theme.set_variant(
            self, kind if kind in _VALID_KINDS else "info",
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
        self.dismissed.emit()

    def text(self) -> str:
        return self._message_label.text()

    @property
    def action_button(self) -> QPushButton:
        # Public so an action started from the notice can hand its own
        # button to the busy-action registry.
        return self._action_button


class NoticeStrip(QWidget):
    """Notices stacked above a page's scrolling body, shown only while
    one of them is: an idle page keeps no gap above its body."""

    def __init__(self, *notices: InlineNotice) -> None:
        super().__init__()
        self._notices = notices
        layout = QVBoxLayout(self)
        # The body's own top margin spaces the last notice from it.
        margins = layout.contentsMargins()
        layout.setContentsMargins(
            margins.left(), margins.top(), margins.right(), 0,
        )

        for notice in notices:
            layout.addWidget(notice)
            # ShowToParent/HideToParent, not Show/Hide: a notice's
            # Show never fires while this strip is hidden (observed
            # offscreen), and showing the strip is what this is for.
            notice.installEventFilter(self)

        self._follow_notices()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (
                QEvent.Type.ShowToParent, QEvent.Type.HideToParent,
        ):
            self._follow_notices()
        return False

    def _follow_notices(self) -> None:
        self.setVisible(
            any(not notice.isHidden() for notice in self._notices),
        )


def pinned_notices(
        body: QWidget, *notices: InlineNotice, reading_measure: bool,
) -> QWidget:
    """`body` scrolling under `notices`, which stay in view however
    far it scrolls: an action at the bottom of a tall page reports to a
    notice the user can see. `reading_measure` caps both at
    `theme.reading_column`'s width, so the notices line up with the
    body."""
    strip: QWidget = NoticeStrip(*notices)
    if reading_measure:
        strip = theme.reading_column(strip)
        body = theme.reading_column(body)

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    # A hidden strip leaves its reading row zero tall; spacing would
    # still open a gap above the body.
    layout.setSpacing(0)
    layout.addWidget(strip)
    layout.addWidget(theme.scrollable(body), 1)
    return page


@dataclass(frozen=True)
class FeedbackTarget:
    """Where one action reports: the page it was started from. A panel
    whose actions can be triggered from another page (TaggingPanel's
    Tag, from a Dashboard row) takes one from its caller, so the outcome
    lands where the user is looking, not on the panel's own page.

    `status_label` carries in-progress text only; the outcome, success
    or error, goes to `notice` and clears the label."""

    status_label: QLabel
    notice: InlineNotice

    def show_progress(self, text: str) -> None:
        self.status_label.setText(text)

    def show_outcome(
            self,
            text: str,
            kind: str = "info",
            action_text: str | None = None,
            on_action: Callable[[], None] | None = None,
    ) -> None:
        self.status_label.setText("")
        self.notice.show_message(
            text, kind=kind, action_text=action_text, on_action=on_action,
        )

    def show_error(self, message: str) -> None:
        self.show_outcome(message, kind="error")

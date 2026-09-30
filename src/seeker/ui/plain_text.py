"""Labels, tooltips and message boxes that never guess their format.

Qt's default `AutoText` renders a string as HTML when anything
tag-like appears before its first line break. Much of what Seeker
shows comes from outside it: a peer's filename or username, a
playlist name, slskd's log text, a release's version string. Under
`AutoText`, a peer's filename `<a href="…">Update Seeker</a>.mp3`
becomes a styled link inside an error message.

So every label in `ui/` is a `PlainLabel`, or a `RichLabel` for
Seeker's own markup (any data placed inside it is `html.escape`d);
every message box built from text goes through `question`,
`information` or `warning` here; every tooltip built from data goes
through `plain_tooltip`. `tests/test_plain_text.py` enforces all three
across `ui/`.
"""

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget


class PlainLabel(QLabel):
    """A label that shows its text exactly as given."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)


class RichLabel(QLabel):
    """A label for Seeker's own HTML. Escape any data put inside it."""

    def __init__(self, html: str = "", parent: QWidget | None = None) -> None:
        super().__init__(html, parent)
        self.setTextFormat(Qt.TextFormat.RichText)


def plain_tooltip(text: str) -> str:
    """`text` as tooltip HTML that renders it literally.

    Escaping alone is not enough: a tooltip also guesses, and an
    escaped string with no tag in it is shown with its entities
    visible. Converting to explicit HTML settles the format;
    `WhiteSpaceNormal` keeps ordinary spaces, so a long tooltip still
    wraps.
    """
    if not text:
        return ""  # Qt hides a tooltip only when its text is empty.
    return Qt.convertFromPlainText(text, Qt.WhiteSpaceMode.WhiteSpaceNormal)


def _plain_box(
        icon: QMessageBox.Icon,
        parent: QWidget | None,
        title: str,
        text: str,
        buttons: QMessageBox.StandardButton,
) -> QMessageBox:
    box = QMessageBox(icon, title, text, buttons, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)
    return box


def question(
        parent: QWidget | None, title: str, text: str,
) -> QMessageBox.StandardButton:
    """`QMessageBox.question`, with `text` shown literally."""
    box = _plain_box(
        QMessageBox.Icon.Question, parent, title, text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return QMessageBox.StandardButton(box.exec())


def information(parent: QWidget | None, title: str, text: str) -> None:
    """`QMessageBox.information`, with `text` shown literally."""
    _plain_box(
        QMessageBox.Icon.Information, parent, title, text,
        QMessageBox.StandardButton.Ok,
    ).exec()


def warning(parent: QWidget | None, title: str, text: str) -> None:
    """`QMessageBox.warning`, with `text` shown literally."""
    _plain_box(
        QMessageBox.Icon.Warning, parent, title, text,
        QMessageBox.StandardButton.Ok,
    ).exec()

"""A titled section the user opens and closes: background reading a
page keeps out of the way of its working content."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class Disclosure(QWidget):
    """A chevron toggle with `title`, and `body` below it while open.

    `toggled` fires on the user's click only, so a page can remember
    the choice without saving the state it restored."""

    toggled = Signal(bool)

    def __init__(
            self, title: str, body: QWidget, *, expanded: bool = False,
            parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.body = body

        self.toggle = QToolButton()
        # QToolButton#disclosureToggle in theme.py.
        self.toggle.setObjectName("disclosureToggle")
        self.toggle.setText(title)
        self.toggle.setAccessibleName(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon,
        )
        # Like every button under _SeekerStyle: a click leaves no ring.
        self.toggle.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(body)

        self.set_expanded(expanded)
        self.toggle.clicked.connect(self._on_clicked)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow,
        )
        self.body.setVisible(expanded)

    def _on_clicked(self, checked: bool) -> None:
        self.set_expanded(checked)
        self.toggled.emit(checked)

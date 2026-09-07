"""FlowLayout — the standard Qt reflowing-row layout pattern (ported
from Qt's own C++ "Flow Layout" example), for any control row that
should wrap onto more rows as available width shrinks rather than
imposing a fixed floor on its parent.

Roadmap item 72 (P1) — built specifically to fix the tagging controls
row (main_window.py's _build_tagging_controls): a plain QHBoxLayout's
minimum width is the SUM of its children's minimum widths (stretch
factors only distribute space above each item's minimum, never shrink
below it), so a row of 9 fixed-size controls imposed a ~900-1000px
floor on its entire parent page, squeezing the playlist panel next to
it down to almost nothing. FlowLayout fixes this at the source:
minimumSize() below returns the WIDEST SINGLE ITEM, not the sum, and
heightForWidth() grows the row to 2+ lines instead of overflowing
horizontally — no resolution detection, no resizeEvent hooks, no
breakpoint constants to tune, purely derived from Qt's own layout pass.
"""

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QStyle,
    QWidget,
)


class FlowLayout(QLayout):
    def __init__(
            self,
            parent: QWidget | None = None,
            margin: int = -1,
            h_spacing: int = -1,
            v_spacing: int = -1,
    ) -> None:
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._item_list: list[QLayoutItem] = []
        if margin >= 0:
            self.setContentsMargins(
                QMargins(margin, margin, margin, margin)
            )

    def addItem(self, item: QLayoutItem) -> None:
        self._item_list.append(item)

    def horizontalSpacing(self) -> int:
        if self._h_spacing >= 0:
            return self._h_spacing
        return self._smart_spacing(
            QSizePolicy.ControlType.PushButton, Qt.Orientation.Horizontal,
        )

    def verticalSpacing(self) -> int:
        if self._v_spacing >= 0:
            return self._v_spacing
        return self._smart_spacing(
            QSizePolicy.ControlType.PushButton, Qt.Orientation.Vertical,
        )

    def count(self) -> int:
        return len(self._item_list)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._item_list):
            return self._item_list[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._item_list):
            return self._item_list.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        # The load-bearing part of this whole class: expandedTo() takes
        # the max width and max height ACROSS items independently, so
        # this is "the widest single item" — never the sum a QHBoxLayout
        # would report.
        size = QSize()
        for item in self._item_list:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(
            margins.left(), margins.top(),
            -margins.right(), -margins.bottom(),
        )
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._item_list:
            # This layout is only ever populated via addWidget() (see
            # _build_tagging_controls) -- never addLayout() -- so every
            # item genuinely wraps a real widget.
            widget = item.widget()
            assert widget is not None

            h_space = self.horizontalSpacing()
            if h_space == -1:
                h_space = widget.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Horizontal,
                )
            v_space = self.verticalSpacing()
            if v_space == -1:
                v_space = widget.style().layoutSpacing(
                    QSizePolicy.ControlType.PushButton,
                    QSizePolicy.ControlType.PushButton,
                    Qt.Orientation.Vertical,
                )

            next_x = x + item.sizeHint().width() + h_space

            if next_x - h_space > effective_rect.right() and line_height > 0:
                x = effective_rect.x()
                y = y + line_height + v_space
                next_x = x + item.sizeHint().width() + h_space
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = next_x
            line_height = max(line_height, item.sizeHint().height())

        return y + line_height - rect.y() + margins.bottom()

    def _smart_spacing(
            self, control_type: QSizePolicy.ControlType,
            orientation: Qt.Orientation,
    ) -> int:
        parent = self.parent()
        if parent is None:
            return -1
        if isinstance(parent, QWidget):
            metric = (
                QStyle.PixelMetric.PM_LayoutHorizontalSpacing
                if orientation == Qt.Orientation.Horizontal
                else QStyle.PixelMetric.PM_LayoutVerticalSpacing
            )
            return parent.style().pixelMetric(metric, None, parent)
        return -1

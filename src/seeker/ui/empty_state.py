"""What an empty table shows instead of a bare grid: a glyph, one
sentence saying why it is empty or what to do next, and an optional
action.

`EmptyState` lives inside the table's own viewport and shows itself
whenever the table has no rows, so a page never switches it by hand
and the column headers stay where the rows will appear.
"""

from enum import StrEnum

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from seeker.ui import theme
from seeker.ui.plain_text import PlainLabel

_GLYPH_SIZE = 40
# Long enough for one sentence on two lines at the body size, short
# enough to keep the line comfortably readable in a wide table.
_TEXT_MAX_WIDTH = 420


class EmptyGlyph(StrEnum):
    SEARCH = "search"
    RECORD = "record"
    SHARE = "share"
    DONE = "done"


class _Glyph(QWidget):
    """Drawn with `QPainter` in `theme.TEXT_MUTED`, read on every
    paint, like `ThemeToggleButton`: it follows a theme switch without
    shipping an asset per palette."""

    def __init__(self, kind: EmptyGlyph, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(_GLYPH_SIZE, _GLYPH_SIZE)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.TEXT_MUTED)
        pen = QPen(color, 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        rect = QRectF(self.rect()).adjusted(3, 3, -3, -3)

        if self.kind is EmptyGlyph.SEARCH:
            _paint_search(painter, rect)
        elif self.kind is EmptyGlyph.RECORD:
            _paint_record(painter, rect, color)
        elif self.kind is EmptyGlyph.SHARE:
            _paint_share(painter, rect)
        else:
            _paint_done(painter, rect)
        painter.end()


def _paint_search(painter: QPainter, rect: QRectF) -> None:
    side = rect.width() * 0.68
    lens = QRectF(rect.left(), rect.top(), side, side)
    painter.drawEllipse(lens)
    inset = side * 0.15
    painter.drawLine(
        QPointF(lens.right() - inset, lens.bottom() - inset),
        rect.bottomRight(),
    )


def _paint_record(painter: QPainter, rect: QRectF, color: QColor) -> None:
    painter.drawEllipse(rect)
    center = rect.center()
    # Two grooves, drawn as arcs so the disc reads as vinyl, not a
    # target.
    for scale, start in ((0.72, 30), (0.52, 210)):
        side = rect.width() * scale
        groove = QRectF(0, 0, side, side)
        groove.moveCenter(center)
        painter.drawArc(groove, start * 16, 110 * 16)
    label = QRectF(0, 0, rect.width() * 0.3, rect.width() * 0.3)
    label.moveCenter(center)
    painter.setBrush(color)
    painter.drawEllipse(label)


def _paint_share(painter: QPainter, rect: QRectF) -> None:
    rim = rect.top() + rect.height() * 0.55
    tray = QPainterPath()
    tray.moveTo(rect.left(), rim)
    tray.lineTo(rect.left(), rect.bottom())
    tray.lineTo(rect.right(), rect.bottom())
    tray.lineTo(rect.right(), rim)
    painter.drawPath(tray)
    middle = rect.center().x()
    tip = QPointF(middle, rect.top())
    painter.drawLine(tip, QPointF(middle, rect.top() + rect.height() * 0.72))
    arm = rect.width() * 0.22
    painter.drawLine(tip, QPointF(middle - arm, rect.top() + arm))
    painter.drawLine(tip, QPointF(middle + arm, rect.top() + arm))


def _paint_done(painter: QPainter, rect: QRectF) -> None:
    painter.drawEllipse(rect)
    left, top = rect.left(), rect.top()
    width, height = rect.width(), rect.height()
    check = QPainterPath()
    check.moveTo(left + width * 0.28, top + height * 0.52)
    check.lineTo(left + width * 0.44, top + height * 0.68)
    check.lineTo(left + width * 0.73, top + height * 0.36)
    painter.drawPath(check)


class EmptyState(QWidget):
    """The empty state of `table`: built once per table, then only its
    sentence changes (`set_text`) as the reason for the emptiness
    does. It covers the viewport while the table has no rows and hides
    itself as soon as one arrives.

    The table keeps a minimum height that fits the sentence and the
    action, so a squeezed page never clips them; a viewport too short
    for the glyph as well drops the glyph."""

    def __init__(
            self,
            table: QAbstractItemView,
            glyph: EmptyGlyph,
            text: str,
            action: QPushButton | None = None,
    ) -> None:
        viewport = table.viewport()
        super().__init__(viewport)
        self._table = table
        self._action = action

        self.glyph = _Glyph(glyph)
        self.label = PlainLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        # QLabel[badge="muted"] in theme.py.
        self.label.setProperty("badge", "muted")

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(theme.SPACING_SM)
        self._layout.addStretch()
        self._layout.addLayout(_centered(self.glyph))
        self._layout.addLayout(_centered(self.label))
        if action is not None:
            self._layout.addLayout(_centered(action))
        self._layout.addStretch()

        viewport.installEventFilter(self)
        model = table.model()
        model.rowsInserted.connect(self._sync)
        model.rowsRemoved.connect(self._sync)
        model.modelReset.connect(self._sync)
        self.setGeometry(viewport.rect())
        self._fit()
        self._sync()

    def text(self) -> str:
        return self.label.text()

    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self._fit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(self._table.viewport().rect())
            self._fit()
        return False

    def _sync(self, *_args: object) -> None:
        empty = self._table.model().rowCount() == 0
        self.setVisible(empty)
        if empty:
            self.raise_()

    def _fit(self) -> None:
        # A word-wrapped label centred in a row gets only its size
        # hint's width and wraps after two words; it is given the
        # width it can really use instead.
        margins = self._layout.contentsMargins()
        spacing = self._layout.spacing()
        available = self.width() - margins.left() - margins.right()
        width = max(min(available, _TEXT_MAX_WIDTH), 1)
        self.label.setFixedWidth(width)

        compact = (
            margins.top() + margins.bottom()
            + self.label.heightForWidth(width)
        )
        if self._action is not None:
            compact += spacing + self._action.sizeHint().height()
        self.glyph.setVisible(self.height() >= compact + _GLYPH_SIZE + spacing)

        chrome = self._table.height() - self._table.viewport().height()
        self._table.setMinimumHeight(chrome + compact)


def _centered(widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addStretch()
    row.addWidget(widget)
    row.addStretch()
    return row

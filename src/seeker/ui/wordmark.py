"""The sidebar wordmark: "Seeker" in the display face, with the app
icon's two brows over its "ee", so the name carries the Dock icon's
mark.

The word is a plain `QLabel`, styled by `QLabel#wordmark`, and the
brows are a child overlay it never measures: a label sizes itself from
its own font, so nothing drawn here can clip the word (HISTORY §114,
where one painted widget drawing both did).
"""

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import QWidget

from seeker.ui import theme
from seeker.ui.plain_text import PlainLabel

# The two strokes' centre lines, from packaging/icons/seeker_brows.svg
# (traced off seeker_icon.icns), normalised to a unit box: each brow
# falls toward the middle, with a gap between them.
_LEFT_BROW = QLineF(0.0, 0.0, 167 / 483, 1.0)
_RIGHT_BROW = QLineF(316 / 483, 1.0, 1.0, 0.0)
# The centre lines' height over their width in that file.
_BROW_ASPECT = 123.4 / 483
# The brows span less than the "ee" and stand well clear of it, as
# on the icon, where they sit an eye's height above the eyes: close
# over each letter they read as accents ("Sèéker"). The pen is in
# proportion to the x-height, a little under the word's own stem.
_SPAN_OF_EE = 0.9
_PEN_PER_X_HEIGHT = 0.15
_GAP_PER_X_HEIGHT = 0.3
# Room for the brows above the word's own ascent. The sidebar takes it
# back from its top margin, so the word stays level with the page title.
BROW_ROOM_PX = 6


class _Brows(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pen_width = 2.0

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(theme.active_palette().ACCENT), self.pen_width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(pen)
        inset = self.pen_width / 2
        box = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        for line in (_LEFT_BROW, _RIGHT_BROW):
            painter.drawLine(QLineF(
                _in_box(line.p1(), box), _in_box(line.p2(), box),
            ))


def _in_box(point: QPointF, box: QRectF) -> QPointF:
    return QPointF(
        box.left() + point.x() * box.width(),
        box.top() + point.y() * box.height(),
    )


class Wordmark(PlainLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Seeker", parent)
        self.setObjectName("wordmark")
        # The brows are placed from where this alignment puts the text.
        self.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )
        self.setContentsMargins(0, BROW_ROOM_PX, 0, 0)
        self._brows = _Brows(self)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_brows()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        # The stylesheet sets the display face, so the font arrives
        # after construction and again on every theme switch.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._place_brows()

    def _place_brows(self) -> None:
        metrics = QFontMetricsF(self.font())
        area = QRectF(self.contentsRect())
        baseline = (
            area.top() + (area.height() - metrics.height()) / 2
            + metrics.ascent()
        )
        ee = metrics.tightBoundingRect("ee")
        span = ee.width() * _SPAN_OF_EE
        centre = (
            area.left() + metrics.horizontalAdvance("S") + ee.center().x()
        )
        pen = max(1.5, metrics.xHeight() * _PEN_PER_X_HEIGHT)
        height = span * _BROW_ASPECT + pen
        # ee.top() is the letters' ink top, overshoot included.
        bottom = baseline + ee.top() - metrics.xHeight() * _GAP_PER_X_HEIGHT
        self._brows.pen_width = pen
        self._brows.setGeometry(QRectF(
            centre - (span + pen) / 2, bottom - height, span + pen, height,
        ).toAlignedRect())
        self._brows.update()

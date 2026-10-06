"""Small custom-painted widgets shared by the shell and its pages."""

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import (
    QProgressBar,
    QPushButton,
    QStyle,
    QStyleOptionProgressBar,
    QWidget,
)

from seeker.ui import theme
from seeker.ui.plain_text import plain_tooltip

_THEME_MODE_LABELS = {
    "system": "Follow system",
    "light": "Light",
    "dark": "Dark",
}


class ThemeToggleButton(QPushButton):
    """A conventional sun/moon/split-circle glyph set, drawn with
    `QPainter` rather than shipped as SVG/PNG assets, so it's
    resolution-independent and tints with the active palette for free
    (reads `theme.TEXT_MUTED` fresh on every paint — this widget draws
    its own glyph rather than using a palette-driven QSS icon).

    A logo-derived glyph (one eye from the mark, solid/outlined/half-
    filled per mode) was tried first and rejected: at real sidebar
    size the eye shape is a flat sliver whose outline carries no eye
    identity, and a half-fill reads as a broken shape, not a state —
    inspected at real size on both grounds before deciding against it.
    A three-state control with no label is otherwise a guess, so the
    tooltip always names the mode in words; the icon alone shows
    which of the three is CURRENT, not a boolean on/off.
    """

    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(28, 28)
        # Scoped via objectName, never a selector-less setStyleSheet()
        # string, which Qt parses as a universal `*` rule that strips
        # borders off descendants (HISTORY §114). This button paints its
        # own glyph with no children, but the ui-wide selector-less
        # setStyleSheet sweep holds for it too rather than depending on
        # it staying childless.
        self.setObjectName("themeToggleButton")
        self._mode = mode
        self._describe_mode()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._describe_mode()
        self.update()

    def _describe_mode(self) -> None:
        label = _THEME_MODE_LABELS.get(self._mode, self._mode)
        self.setToolTip(plain_tooltip(f"Theme: {label} (click to change)"))
        self.setAccessibleName(f"Theme: {label}")

    def paintEvent(self, event: QPaintEvent) -> None:
        # The stylesheet's box first: transparent, except for the
        # `#themeToggleButton:focus` ring.
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - 8
        rect = QRectF(
            (self.width() - side) / 2, (self.height() - side) / 2,
            side, side,
        )
        pen_color = QColor(theme.TEXT_MUTED)
        pen = painter.pen()
        pen.setColor(pen_color)
        pen.setWidthF(max(1.5, side * 0.09))
        painter.setPen(pen)

        if self._mode == "light":
            self._paint_sun(painter, rect)
        elif self._mode == "dark":
            self._paint_moon(painter, rect)
        else:
            self._paint_split_circle(painter, rect, pen_color)
        painter.end()

    def _paint_sun(self, painter: QPainter, rect: QRectF) -> None:
        core = rect.adjusted(
            rect.width() * 0.28, rect.height() * 0.28,
            -rect.width() * 0.28, -rect.height() * 0.28,
        )
        painter.setBrush(painter.pen().color())
        painter.drawEllipse(core)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center = rect.center()
        radius = rect.width() / 2
        for i in range(8):
            angle = i * math.pi / 4
            p1 = QPointF(
                center.x() + math.cos(angle) * radius * 0.75,
                center.y() + math.sin(angle) * radius * 0.75,
            )
            p2 = QPointF(
                center.x() + math.cos(angle) * radius,
                center.y() + math.sin(angle) * radius,
            )
            painter.drawLine(p1, p2)

    def _paint_moon(self, painter: QPainter, rect: QRectF) -> None:
        full = QPainterPath()
        full.addEllipse(rect)
        cutout = QPainterPath()
        offset = rect.width() * 0.32
        cutout.addEllipse(rect.translated(offset, -offset * 0.4))
        crescent = full.subtracted(cutout)
        painter.setBrush(painter.pen().color())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(crescent)

    def _paint_split_circle(
            self, painter: QPainter, rect: QRectF, pen_color: QColor,
    ) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)
        # Right half filled (the "on" side), left half left as an
        # outline only — reads as a real half-filled circle, the
        # conventional "system/auto" glyph.
        half = QPainterPath()
        half.moveTo(rect.center())
        half.arcTo(rect, 90, 180)
        half.closeSubpath()
        painter.setBrush(pen_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(half)


class TwoToneProgressBar(QProgressBar):
    """A progress bar whose percentage reads on both of its
    backgrounds: `ON_ACCENT` over the ACCENT fill, `TEXT` over the
    track. The stylesheet painter draws a styled bar's label in one
    colour, and no one colour clears both (`TEXT` on the light
    ACCENT is 3.13:1), so this bar paints its own label twice, each
    pass clipped to one side of the fill's edge. Indeterminate, it has
    no label (`text()` is empty) and paints as a plain bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        text = self.text()
        if not text:
            return

        option = QStyleOptionProgressBar()
        self.initStyleOption(option)
        contents = self.style().subElementRect(
            QStyle.SubElement.SE_ProgressBarContents, option, self,
        )
        span = self.maximum() - self.minimum()
        filled = round(contents.width() * (self.value() - self.minimum()) / span)
        split = contents.left() + filled
        whole = self.rect()

        painter = QPainter(self)
        for color, side in (
                (theme.ON_ACCENT, QRect(0, 0, split, whole.height())),
                (theme.TEXT, QRect(split, 0, whole.width() - split, whole.height())),
        ):
            painter.setClipRect(side)
            painter.setPen(QColor(color))
            painter.drawText(whole, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

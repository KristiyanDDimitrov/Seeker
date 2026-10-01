"""Small custom-painted widgets shared by the shell."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QPushButton, QWidget

from seeker.ui import theme
from seeker.ui.plain_text import plain_tooltip

_THEME_MODE_LABELS = {
    "system": "Follow system",
    "light": "Light",
    "dark": "Dark",
}


class ThemeToggleButton(QPushButton):
    """Roadmap item C5.10 (round 5) — a conventional sun/moon/split-
    circle glyph set, drawn with `QPainter` rather than shipped as SVG/
    PNG assets, so it's resolution-independent and tints with the
    active palette for free (reads `theme.TEXT_MUTED` fresh on every
    paint — this widget draws its own glyph rather than using a
    palette-driven QSS icon).

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
        # Roadmap item E3.6 (round 7) — a selector-less setStyleSheet()
        # string is the exact mechanism item E3 found stripping borders
        # off a QProgressBar's track (Qt parses it as a universal `*`
        # rule). This button paints its own glyph with no children, so
        # there was never anything for it to cascade onto — but scoped
        # via objectName anyway, so the new ui-wide regression test
        # (theme.py's own selector-less-setStyleSheet sweep) can't be
        # tripped by a control that happens to be safe today only
        # because it's childless.
        self.setObjectName("themeToggleButton")
        self._mode = mode
        self._update_tooltip()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._update_tooltip()
        self.update()

    def _update_tooltip(self) -> None:
        label = _THEME_MODE_LABELS.get(self._mode, self._mode)
        self.setToolTip(plain_tooltip(f"Theme: {label} (click to change)"))

    def paintEvent(self, event: QPaintEvent) -> None:
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

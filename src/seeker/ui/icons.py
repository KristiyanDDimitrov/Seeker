"""Bundled line icons, drawn in the active palette's colours.

The sidebar's icons are Lucide's (ISC), vendored unchanged under
`packaging/icons/lucide/` with their licence. A Lucide file strokes in
`currentColor`, which Qt's SVG renderer does not resolve, so
`TokenIconEngine` substitutes a palette colour each time it draws.
Reading the palette at draw time means a theme switch recolours every
icon with no code of its own, and one file serves both palettes.
"""

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from seeker.ui import theme

logger = logging.getLogger(__name__)

LUCIDE_DIR = theme.bundled_dir("icons") / "lucide"

# Sidebar key -> Lucide icon name. Every page has one; the test suite
# fails if a name here has no vendored file, or a vendored file no name.
NAV_ICONS: dict[str, str] = {
    "dashboard": "layout-dashboard",
    "library": "library",
    "search": "search",
    "downloads": "download",
    "review": "list-checks",
    "duplicates": "copy",
    "sharing": "share-2",
    "history": "history",
    "help": "circle-help",
    "support": "life-buoy",
    "settings": "settings",
}

ColourToken = Literal["TEXT", "TEXT_MUTED", "TEXT_FAINT", "ACCENT"]


@dataclass(frozen=True)
class IconColours:
    """The palette token an icon is drawn in, per state. `on` is a
    checked button's icon."""

    off: ColourToken
    on: ColourToken
    disabled: ColourToken = "TEXT_FAINT"

    def token_for(self, mode: QIcon.Mode, state: QIcon.State) -> ColourToken:
        if mode == QIcon.Mode.Disabled:
            return self.disabled
        return self.on if state == QIcon.State.On else self.off


# A nav item: the checked page's icon lights in the accent, the rest
# stay as muted as their labels.
NAV_COLOURS = IconColours(off="TEXT_MUTED", on="ACCENT")


@cache
def _svg_source(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        logger.warning("Could not read the bundled icon %s", path)
        return None


@cache
def _renderer(path: Path, colour: str) -> QSvgRenderer | None:
    source = _svg_source(path)
    if source is None:
        return None
    recoloured = source.replace(b"currentColor", colour.encode("ascii"))
    renderer = QSvgRenderer(QByteArray(recoloured))
    if not renderer.isValid():
        logger.warning("Could not parse the bundled icon %s", path)
        return None
    return renderer


class TokenIconEngine(QIconEngine):
    """Draws one SVG in the colour `colours` names for the requested
    mode and state, read from `theme.active_palette()` on every draw.
    A file that cannot be read or parsed draws nothing (logged once)
    rather than failing the widget that shows it."""

    def __init__(self, path: Path, colours: IconColours) -> None:
        super().__init__()
        self._path = path
        self._colours = colours

    def paint(
            self,
            painter: QPainter,
            rect: QRect,
            mode: QIcon.Mode,
            state: QIcon.State,
    ) -> None:
        token = self._colours.token_for(mode, state)
        colour: str = getattr(theme.active_palette(), token)
        renderer = _renderer(self._path, colour)
        if renderer is not None:
            renderer.render(painter, QRectF(rect))

    def pixmap(
            self, size: QSize, mode: QIcon.Mode, state: QIcon.State,
    ) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(
            self,
            size: QSize,
            mode: QIcon.Mode,
            state: QIcon.State,
            scale: float,
    ) -> QPixmap:
        pixmap = QPixmap(size * scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint(painter, QRect(0, 0, pixmap.width(), pixmap.height()), mode, state)
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        return pixmap

    def clone(self) -> QIconEngine:
        return TokenIconEngine(self._path, self._colours)


def token_icon(path: Path, colours: IconColours) -> QIcon:
    return QIcon(TokenIconEngine(path, colours))


def nav_icon(key: str) -> QIcon:
    """The sidebar icon for page `key`."""
    return token_icon(LUCIDE_DIR / f"{NAV_ICONS[key]}.svg", NAV_COLOURS)

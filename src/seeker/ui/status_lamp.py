"""Status lamps: each track and download state shown as a panel LED
beside its label, in the vocabulary of a DJ's own hardware
(docs/design/visual-direction.md).

Lit means the state holds or is moving: green for play (in the
library), amber for cue (working), red for a fault. An amber ring
means the state waits on you. Colour is never the only signal: the
label always sits beside the lamp, and lit versus ring is a shape
difference, so the review states never depend on telling amber from
green.
"""

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

from seeker.models import track_status
from seeker.models.download_request import DownloadStatus
from seeker.ui.theme import Palette

LampColour = Literal["SUCCESS", "WARNING", "DANGER", "TEXT_FAINT"]


@dataclass(frozen=True)
class Lamp:
    colour: LampColour
    lit: bool

    def colour_in(self, palette: Palette) -> str:
        colour: str = getattr(palette, self.colour)
        return colour


PLAY = Lamp("SUCCESS", lit=True)
CUE = Lamp("WARNING", lit=True)
CUE_WAITING = Lamp("WARNING", lit=False)
FAULT = Lamp("DANGER", lit=True)
# Out of play: a request another one replaced.
STANDBY = Lamp("TEXT_FAINT", lit=False)

TRACK_LAMPS: dict[str, Lamp] = {
    track_status.IN_LIBRARY: PLAY,
    track_status.DOWNLOADING: CUE,
    track_status.RETRYING: CUE,
    track_status.AWAITING_REVIEW: CUE_WAITING,
    track_status.NEEDS_REVIEW: CUE_WAITING,
    track_status.REVIEW_CANDIDATE: CUE_WAITING,
    track_status.NOT_FOUND: FAULT,
}

# Queued counts as working: the user's part is done, and the wait is
# on the network.
DOWNLOAD_LAMPS: dict[DownloadStatus, Lamp] = {
    DownloadStatus.QUEUED: CUE,
    DownloadStatus.DOWNLOADING: CUE,
    DownloadStatus.LOCKED: CUE,
    DownloadStatus.SHORTLISTED: CUE,
    DownloadStatus.READY_FOR_REVIEW: CUE_WAITING,
    DownloadStatus.COMPLETED: PLAY,
    DownloadStatus.FAILED: FAULT,
    DownloadStatus.UNAVAILABLE: FAULT,
    DownloadStatus.SUPERSEDED: STANDBY,
}

LAMP_SIZE = 14
_DOT_RADIUS = 3.6
_HALO_RADIUS = 6.0
_HALO_ALPHA = 60
_RING_WIDTH = 1.6


def lamp_icon(lamp: Lamp, palette: Palette) -> QIcon:
    """The lamp drawn for `palette`, at twice the logical size so it
    stays sharp on a Retina display. A lit lamp is a dot with a soft
    halo; a waiting one is a hollow ring of the same size. Build it
    at render time: it bakes in the palette's colour."""
    pixmap = QPixmap(LAMP_SIZE * 2, LAMP_SIZE * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    centre = QPointF(LAMP_SIZE / 2, LAMP_SIZE / 2)
    colour = QColor(lamp.colour_in(palette))
    if lamp.lit:
        halo = QColor(colour)
        halo.setAlpha(_HALO_ALPHA)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, _HALO_RADIUS, _HALO_RADIUS)
        painter.setBrush(colour)
        painter.drawEllipse(centre, _DOT_RADIUS, _DOT_RADIUS)
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(colour, _RING_WIDTH))
        painter.drawEllipse(centre, _DOT_RADIUS, _DOT_RADIUS)
    painter.end()
    return QIcon(pixmap)

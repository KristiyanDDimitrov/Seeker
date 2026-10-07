"""The status lamp system: every track and download state has a lamp,
waiting-on-you states are rings, and every lamp reads as a mark."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from seeker.models import track_status
from seeker.models.download_request import DownloadStatus
from seeker.ui import status_lamp, theme

_TRACK_STATES = [
    track_status.IN_LIBRARY,
    track_status.DOWNLOADING,
    track_status.AWAITING_REVIEW,
    track_status.RETRYING,
    track_status.NEEDS_REVIEW,
    track_status.REVIEW_CANDIDATE,
    track_status.NOT_FOUND,
]

_PALETTES = pytest.mark.parametrize(
        "palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"],
)


def test_every_track_state_has_a_lamp():
    assert set(status_lamp.TRACK_LAMPS) == set(_TRACK_STATES)


def test_every_download_status_has_a_lamp():
    assert set(status_lamp.DOWNLOAD_LAMPS) == set(DownloadStatus)


@pytest.mark.parametrize(
        "lamp",
        [
            status_lamp.TRACK_LAMPS[track_status.AWAITING_REVIEW],
            status_lamp.TRACK_LAMPS[track_status.NEEDS_REVIEW],
            status_lamp.TRACK_LAMPS[track_status.REVIEW_CANDIDATE],
            status_lamp.DOWNLOAD_LAMPS[DownloadStatus.READY_FOR_REVIEW],
        ],
)
def test_a_state_waiting_on_you_is_a_ring(lamp):
    # The same amber as "working", told apart by shape, not hue.
    assert lamp == status_lamp.CUE_WAITING
    assert not lamp.lit


@pytest.mark.parametrize(
        ("state", "lamp"),
        [
            (track_status.IN_LIBRARY, status_lamp.PLAY),
            (track_status.DOWNLOADING, status_lamp.CUE),
            (track_status.RETRYING, status_lamp.CUE),
            (track_status.NOT_FOUND, status_lamp.FAULT),
        ],
)
def test_settled_and_working_track_states_are_lit(state, lamp):
    assert status_lamp.TRACK_LAMPS[state] == lamp
    assert lamp.lit


@_PALETTES
@pytest.mark.parametrize(
        "lamp",
        [
            status_lamp.PLAY,
            status_lamp.CUE,
            status_lamp.CUE_WAITING,
            status_lamp.FAULT,
            status_lamp.STANDBY,
        ],
)
@pytest.mark.parametrize("ground", ["BG_SURFACE", "BG_APP", "ACCENT_SUBTLE"])
def test_every_lamp_reads_as_a_mark_on_every_ground(palette, lamp, ground):
    # WCAG 1.4.11's 3:1 for a non-text mark, on a table row, the page
    # ground, and a selected row.
    assert theme.contrast_ratio(
            lamp.colour_in(palette), getattr(palette, ground),
    ) >= 3.0


def _centre_and_ring(lamp, palette, qapp):
    icon = status_lamp.lamp_icon(lamp, palette)
    image = icon.pixmap(QSize(14, 14), 2.0).toImage()
    scale = image.width() / 14
    centre = image.pixelColor(round(7 * scale), round(7 * scale))
    # On the ring's stroke: 3.6 px right of centre.
    ring = image.pixelColor(round(10.6 * scale), round(7 * scale))
    return centre, ring


@_PALETTES
def test_a_lit_lamp_is_a_solid_dot_in_its_colour(palette, qapp):
    centre, _ = _centre_and_ring(status_lamp.PLAY, palette, qapp)
    assert centre == QColor(palette.SUCCESS)


@_PALETTES
def test_a_ring_lamp_is_hollow(palette, qapp):
    centre, ring = _centre_and_ring(status_lamp.CUE_WAITING, palette, qapp)
    assert centre.alpha() == 0
    assert ring.alpha() > 0
    assert (ring.red(), ring.green(), ring.blue()) == QColor(
            palette.WARNING,
    ).getRgb()[:3]


@_PALETTES
def test_a_lamp_widget_paints_its_lamp_in_the_active_palette(
        palette, qtbot, monkeypatch,
):
    monkeypatch.setattr(theme, "active_palette", lambda: palette)
    widget = status_lamp.StatusLamp(status_lamp.CUE)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    image = widget.grab().toImage()
    centre = image.pixelColor(image.width() // 2, image.height() // 2)

    assert widget.size() == QSize(status_lamp.LAMP_SIZE, status_lamp.LAMP_SIZE)
    assert centre == QColor(palette.WARNING)

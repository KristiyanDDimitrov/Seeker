"""The sidebar wordmark: "Seeker" with the app icon's brows over its
"ee" (ui/wordmark.py)."""

import pytest
from PySide6.QtGui import QColor, QFontMetricsF, QImage
from PySide6.QtWidgets import QWidget

from fakes import FakeApplication
from seeker.ui import theme
from seeker.ui.main_window import MainWindow
from seeker.ui.wordmark import Wordmark


def _near(pixel: QColor, hex_color: str, tolerance: int = 24) -> bool:
    target = QColor(hex_color)
    return (
        abs(pixel.red() - target.red()) <= tolerance
        and abs(pixel.green() - target.green()) <= tolerance
        and abs(pixel.blue() - target.blue()) <= tolerance
    )


def _pixels(image: QImage, hex_color: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(image.height()) for x in range(image.width())
        if _near(image.pixelColor(x, y), hex_color)
    ]


def _shown_wordmark(
        qtbot, palette: theme.Palette,
) -> tuple[QWidget, Wordmark]:
    # Inside a host whose stylesheet sets the ground, so a grab shows
    # the brows against BG_SIDEBAR rather than an unpainted background.
    host = QWidget()
    host.setObjectName("sidebarPanel")
    qtbot.addWidget(host)
    host.setStyleSheet(theme.build_stylesheet(palette))
    wordmark = Wordmark(host)
    wordmark.resize(wordmark.sizeHint())
    host.resize(wordmark.sizeHint())
    host.show()
    qtbot.waitExposed(host)
    # The host too: qtbot holds widgets weakly.
    return host, wordmark


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_the_brows_sit_over_the_ee_and_clear_its_ink(qtbot, monkeypatch, palette):
    monkeypatch.setattr(theme, "active_palette", lambda: palette)
    _host, wordmark = _shown_wordmark(qtbot, palette)
    image = wordmark.grab().toImage()
    scale = image.width() / wordmark.width()

    metrics = QFontMetricsF(wordmark.font())
    ee_left = metrics.horizontalAdvance("S") * scale
    ee_right = metrics.horizontalAdvance("See") * scale
    brows = _pixels(image, palette.ACCENT)
    ee_ink = [
        (x, y) for x, y in _pixels(image, palette.TEXT)
        if ee_left <= x < ee_right
    ]

    assert brows, "no brow was drawn"
    assert ee_ink
    assert all(ee_left <= x < ee_right for x, _ in brows)
    assert max(y for _, y in brows) < min(y for _, y in ee_ink)
    # Two strokes with a gap between them, as on the icon.
    middle = (ee_left + ee_right) / 2
    assert any(x < middle for x, _ in brows)
    assert any(x > middle for x, _ in brows)


def test_the_brows_recolour_on_a_theme_switch(qtbot, monkeypatch):
    monkeypatch.setattr(theme, "active_palette", lambda: theme.DARK)
    host, wordmark = _shown_wordmark(qtbot, theme.DARK)
    assert _pixels(wordmark.grab().toImage(), theme.DARK.ACCENT)

    monkeypatch.setattr(theme, "active_palette", lambda: theme.LIGHT)
    host.setStyleSheet(theme.build_stylesheet(theme.LIGHT))

    assert _pixels(wordmark.grab().toImage(), theme.LIGHT.ACCENT)


def test_the_sidebar_wordmark_is_the_brow_wordmark(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    assert isinstance(window._wordmark, Wordmark)
    assert window._wordmark.objectName() == "wordmark"
    assert window._wordmark.text() == "Seeker"

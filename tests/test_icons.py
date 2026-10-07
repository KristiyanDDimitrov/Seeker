"""Bundled line icons drawn in the active palette (ui/icons.py)."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QImage

from seeker.ui import icons, theme


def _opaque_colour(icon: QIcon, mode: QIcon.Mode, state: QIcon.State) -> str:
    """The colour of the icon's most opaque pixel: a stroke's centre,
    where antialiasing has not blended it with the transparent ground."""
    image = icon.pixmap(QSize(48, 48), mode, state).toImage().convertToFormat(
        QImage.Format.Format_ARGB32,
    )
    best = QColor(0, 0, 0, 0)
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if pixel.alpha() > best.alpha():
                best = pixel
    assert best.alpha() == 255, "the icon drew no fully opaque stroke"
    return best.name().upper()


def test_every_nav_icon_is_vendored_and_every_vendored_icon_is_used():
    vendored = {path.stem for path in icons.LUCIDE_DIR.glob("*.svg")}

    assert vendored == set(icons.NAV_ICONS.values())


def test_the_lucide_licence_ships_beside_the_icons():
    licence = (icons.LUCIDE_DIR / "LICENSE").read_text()

    assert "ISC License" in licence
    assert "Lucide Icons and Contributors" in licence


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_a_nav_icon_is_muted_off_and_accent_on(monkeypatch, palette):
    monkeypatch.setattr(theme, "active_palette", lambda: palette)
    icon = icons.nav_icon("dashboard")

    off = _opaque_colour(icon, QIcon.Mode.Normal, QIcon.State.Off)
    on = _opaque_colour(icon, QIcon.Mode.Normal, QIcon.State.On)

    assert off == palette.TEXT_MUTED
    assert on == palette.ACCENT


def test_a_nav_icon_follows_a_theme_switch_without_being_rebuilt(monkeypatch):
    monkeypatch.setattr(theme, "active_palette", lambda: theme.DARK)
    icon = icons.nav_icon("settings")
    assert _opaque_colour(
        icon, QIcon.Mode.Normal, QIcon.State.On,
    ) == theme.DARK.ACCENT

    monkeypatch.setattr(theme, "active_palette", lambda: theme.LIGHT)

    assert _opaque_colour(
        icon, QIcon.Mode.Normal, QIcon.State.On,
    ) == theme.LIGHT.ACCENT


def test_a_disabled_nav_icon_is_faint(monkeypatch):
    monkeypatch.setattr(theme, "active_palette", lambda: theme.DARK)
    icon = icons.nav_icon("search")

    assert _opaque_colour(
        icon, QIcon.Mode.Disabled, QIcon.State.Off,
    ) == theme.DARK.TEXT_FAINT


def test_a_high_dpi_pixmap_is_drawn_at_its_device_pixel_ratio():
    icon = icons.nav_icon("history")

    pixmap = icon.pixmap(QSize(18, 18), 2.0)

    assert pixmap.devicePixelRatio() == 2.0
    assert (pixmap.width(), pixmap.height()) == (36, 36)


def test_a_missing_svg_draws_nothing_and_does_not_raise(tmp_path: Path, caplog):
    icon = icons.token_icon(tmp_path / "gone.svg", icons.NAV_COLOURS)

    image = icon.pixmap(QSize(24, 24)).toImage()

    assert all(
        image.pixelColor(x, y).alpha() == 0
        for y in range(image.height()) for x in range(image.width())
    )
    assert "gone.svg" in caplog.text

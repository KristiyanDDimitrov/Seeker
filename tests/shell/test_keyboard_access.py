"""Keyboard and screen-reader access: where focus starts, and what
every button is called."""
import pytest
from PySide6.QtWidgets import QAbstractButton, QWidget

from fakes import FakeApplication
from seeker.ui import theme
from seeker.ui.main_window import MainWindow
from seeker.ui.widgets import ThemeToggleButton


def test_the_window_opens_with_focus_on_the_playlist_list(qtbot):
    # Otherwise Qt hands focus to the first focusable widget in the
    # chain, the sidebar's theme toggle, which then wears a focus ring
    # from launch.
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    assert window.focusWidget() is window._dashboard_page.playlist_list


def test_the_theme_toggle_is_named_for_its_current_mode(qtbot):
    toggle = ThemeToggleButton("dark")
    qtbot.addWidget(toggle)
    assert toggle.accessibleName() == "Theme: Dark"

    toggle.set_mode("system")
    assert toggle.accessibleName() == "Theme: Follow system"


def _in_cell_widget(button: QAbstractButton) -> bool:
    parent = button.parentWidget()
    return parent is not None and parent.objectName() == "cellWidgetContainer"


def _unnamed(screen: str, root: QWidget) -> list[str]:
    found = []
    for button in root.findChildren(QAbstractButton):
        # A hidden button is skipped only because the walk loads every
        # screen with demo data: each per-row button and icon control
        # is visible on at least one screen.
        if not button.isVisible():
            continue
        text = button.text().replace("&", "")
        name = button.accessibleName()
        if _in_cell_widget(button):
            # "Confirm" alone, read in a table, does not say which row.
            if not (name.startswith(text) and len(name) > len(text) + 1):
                found.append(f"{screen}: row button {text!r} named {name!r}")
        elif sum(char.isalpha() for char in text) < 2 and not name:
            found.append(
                f"{screen}: {type(button).__name__} {text!r} has no name",
            )
    return found


@pytest.fixture
def _restore_theme(qapp):
    yield
    theme.apply_theme(qapp)


@pytest.mark.usefixtures("_restore_theme")
def test_every_icon_and_row_button_has_an_accessible_name(qapp, screenshots):
    unnamed: list[str] = []
    application = screenshots.build_demo_application()
    theme.apply_theme(qapp, "dark")
    window = MainWindow(application)
    try:
        window.resize(1280, 820)
        window.show()
        screenshots.settle(qapp, window, 1.0)
        for screen in screenshots.SCREENS:
            for step in screen.steps:
                step(window)
                screenshots.settle(qapp, window)
            unnamed += _unnamed(screen.name, window)
    finally:
        screenshots.close(qapp, window)

    assert sorted(set(unnamed)) == []

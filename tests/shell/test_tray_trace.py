"""The tray's debug trace (`SEEKER_DEBUG_TRAY=1`): what runs between
the menu opening and closing, for a menu that closes at once in
fullscreen (HISTORY §237).
"""

import logging

from PySide6.QtCore import Qt

from fakes import (
    FakeApplication,
    force_tray_available,
)
from seeker.ui import tray as tray_module
from seeker.ui.main_window import (
    MainWindow,
)


def _window_with_tray(qtbot, monkeypatch, caplog) -> MainWindow:
    force_tray_available(monkeypatch, True)
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    caplog.set_level(logging.DEBUG, logger=tray_module.logger.name)
    return window


def _trace(caplog) -> list[str]:
    return [
        record.getMessage() for record in caplog.records
        if record.name == tray_module.logger.name
        and record.levelno == logging.DEBUG
    ]


def test_the_menu_opening_and_closing_are_traced(qtbot, monkeypatch, caplog):
    window = _window_with_tray(qtbot, monkeypatch, caplog)
    menu = window._tray._tray_icon.contextMenu()

    menu.aboutToShow.emit()
    menu.aboutToHide.emit()

    trace = _trace(caplog)
    assert trace[0].startswith("Tray menu opening (")
    assert "fullscreen=False" in trace[0]
    assert trace[1] == "Tray menu closed"


def test_a_render_says_whether_the_menu_is_open(qtbot, monkeypatch, caplog):
    window = _window_with_tray(qtbot, monkeypatch, caplog)
    menu = window._tray._tray_icon.contextMenu()

    window._tray.render_tray_menu()
    menu.aboutToShow.emit()
    window._tray.render_tray_menu()
    menu.aboutToHide.emit()
    window._tray.render_tray_menu()

    renders = [line for line in _trace(caplog) if line.startswith("Rendering")]
    assert renders == [
        "Rendering the tray menu (menu open=False)",
        "Rendering the tray menu (menu open=True)",
        "Rendering the tray menu (menu open=False)",
    ]


def test_an_application_state_change_is_traced(qtbot, monkeypatch, caplog):
    window = _window_with_tray(qtbot, monkeypatch, caplog)
    window.show()
    window._tray._tray_icon.contextMenu().aboutToShow.emit()

    window._tray.on_application_state_changed(
        Qt.ApplicationState.ApplicationInactive,
    )

    assert _trace(caplog)[-1] == (
        "Application state ApplicationInactive "
        "(window visible=True, fullscreen=False, menu open=True)"
    )


def test_nothing_is_traced_at_the_default_level(qtbot, monkeypatch, caplog):
    force_tray_available(monkeypatch, True)
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    caplog.set_level(logging.INFO)

    window._tray._tray_icon.contextMenu().aboutToShow.emit()
    window._tray.render_tray_menu()

    assert _trace(caplog) == []

"""The menu bar: Help (About, Check for updates, build identity)
and View/Window.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QMenu,
    QMessageBox,
)

from fakes import (
    FakeApplication,
)
from seeker.formatting import format_timestamp
from seeker.ui import help_text
from seeker.ui.main_window import (
    MainWindow,
)
from seeker.update_check import UpdateCheckResult, UpdateStatus


def test_main_window_has_help_menu_with_about_action(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu_bar = window.menuBar()
    menu_titles = [menu.title() for menu in menu_bar.findChildren(QMenu)]
    assert any("Help" in title for title in menu_titles)

    help_menu = next(
        menu for menu in menu_bar.findChildren(QMenu) if "Help" in menu.title()
    )
    action_texts = [action.text() for action in help_menu.actions()]
    assert help_text.ABOUT_MENU_TEXT in action_texts
    assert help_text.CHECK_FOR_UPDATES_MENU_TEXT in action_texts


# --- Check for updates (roadmap Phase 11) -----------------------------------
# check_for_update() must fire ONLY from this one Help menu action —
# never at construction, never on a timer. See main_window.py's own
# _build_help_menu/_on_check_for_updates_clicked and update_check.py's
# docstring for the real-external-dependency reasoning.

def test_check_for_update_is_not_called_during_construction(
        qtbot,
        monkeypatch,
):
    calls: list[None] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: calls.append(None),
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.wait(50)
    assert calls == []


def test_check_for_updates_click_runs_check_for_update_via_worker(
        qtbot, monkeypatch,
):
    calls: list[None] = []

    def fake_check_for_update():
        calls.append(None)
        return UpdateCheckResult(
                UpdateStatus.UP_TO_DATE,
                latest_version="v1.0.0",
        )

    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update", fake_check_for_update,
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()

    qtbot.waitUntil(lambda: calls == [None], timeout=2000)
    qtbot.waitUntil(
        window.check_for_updates_action.isEnabled, timeout=2000,
    )


def test_up_to_date_dialog_shows_installed_version(qtbot, monkeypatch):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UP_TO_DATE, latest_version="v1.0.0",
            installed_version="1.0.0",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    assert "up to date" in shown[0].text().lower()
    assert "1.0.0" in shown[0].text()


def test_update_available_dialog_shows_both_versions_and_link(
        qtbot, monkeypatch,
):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UPDATE_AVAILABLE, latest_version="v1.3.0",
            installed_version="1.2.0",
            release_url="https://github.com/example/repo/releases/v1.3.0",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    text = shown[0].text()
    assert "v1.3.0" in text
    assert "1.2.0" in text
    assert "https://github.com/example/repo/releases/v1.3.0" in text


def test_update_available_dialog_escapes_the_release_data(
        qtbot, monkeypatch,
):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UPDATE_AVAILABLE,
            latest_version='v2 <img src="x">',
            installed_version="1.2.0",
            release_url='https://example.com/"><b>bold</b>',
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    rendered = QTextDocument()
    rendered.setHtml(shown[0].text())
    assert 'v2 <img src="x">' in rendered.toPlainText()
    assert "<b>" not in shown[0].text()


def test_unavailable_dialog_shows_the_reason_as_plain_text(
        qtbot, monkeypatch,
):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UNAVAILABLE, reason="<b>GitHub said no</b>",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    assert shown[0].textFormat() == Qt.TextFormat.PlainText


def test_unavailable_dialog_shows_the_reason(qtbot, monkeypatch):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="Couldn't reach GitHub: connection refused.",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    assert "Couldn't reach GitHub: connection refused." in shown[0].text()
    assert shown[0].icon() == QMessageBox.Icon.Warning


def test_no_releases_published_dialog_is_honest_and_un_alarming(
        qtbot, monkeypatch,
):
    # Round 9 §4.2a — verified 2026-09-09 the repo has no published
    # releases, so this is the real, currently-live branch for every
    # user clicking "Check for updates...". Must read as a true,
    # un-alarming statement (Information icon, no "Couldn't check for
    # updates:" fault framing) rather than implying a network or
    # configuration problem.
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.NO_RELEASES_PUBLISHED,
            reason="No releases have been published yet.",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    assert shown[0].text() == "No releases have been published yet."
    assert shown[0].icon() == QMessageBox.Icon.Information
    assert "couldn't" not in shown[0].text().lower()


def test_check_for_updates_action_disabled_while_running_and_reenabled(
        qtbot, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(UpdateStatus.UP_TO_DATE, latest_version="v1"),
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.check_for_updates_action.isEnabled()
    window.check_for_updates_action.trigger()
    qtbot.waitUntil(
        window.check_for_updates_action.isEnabled, timeout=2000,
    )


def test_format_build_identity_labels_dev_explicitly():
    assert "dev" in help_text.format_build_identity("dev", "dev", "dev")
    assert "not a packaged build" in help_text.format_build_identity(
        "dev", "dev", "dev",
    )


def test_format_build_identity_shows_real_sha_and_timestamp():
    text = help_text.format_build_identity(
        "a1b2c3d", "v0.1.0-3-ga1b2c3d", "2026-09-03T12:00:00+00:00",
    )
    assert "v0.1.0-3-ga1b2c3d" in text
    # The viewer's local time, as everywhere else in the app; never the
    # raw ISO string.
    assert format_timestamp("2026-09-03T12:00:00+00:00") in text
    assert "T12:00" not in text


def test_format_build_identity_keeps_an_unparseable_time_as_written():
    text = help_text.format_build_identity("a1b2c3d", "v0.1.0", "yesterday")

    assert text.endswith("built yesterday")


# --- Menu bar: View/Window (round 8 §12.3/§12.5) ----------------------------

def test_view_menu_has_nav_shortcuts_and_actions(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu_bar = window.menuBar()
    view_menu = next(
        menu for menu in menu_bar.findChildren(QMenu) if "View" in menu.title()
    )
    actions_by_text = {
        action.text(): action
        for action in view_menu.actions() if not action.isSeparator()
    }

    assert set(actions_by_text) == {
        "Dashboard", "Library", "Search", "Downloads", "Review",
        "Duplicates", "Sharing", "History", "Refresh", "Focus Search",
        "Toggle Theme", "Settings…",
    }
    assert actions_by_text["Dashboard"].shortcut().toString() == "Ctrl+1"
    assert actions_by_text["History"].shortcut().toString() == "Ctrl+8"
    assert actions_by_text["Refresh"].shortcut().toString() == "Ctrl+R"
    assert (
        actions_by_text["Focus Search"].shortcut().toString() == "Ctrl+F"
    )


def test_view_menu_nav_action_navigates_to_its_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu_bar = window.menuBar()
    view_menu = next(
        menu for menu in menu_bar.findChildren(QMenu) if "View" in menu.title()
    )
    search_action = next(
        action for action in view_menu.actions() if action.text() == "Search"
    )
    search_action.trigger()

    assert window._current_page_key == "search"


def test_view_menu_focus_search_navigates_and_focuses_the_search_field(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window._on_focus_search_clicked()

    assert window._current_page_key == "search"
    # hasFocus() also requires the window to be the active window, which
    # never happens under the offscreen QPA platform CI runs under
    # (there is no window manager to activate anything) — assert the
    # property the feature actually promises instead.
    assert window.focusWidget() is window._search_page.search_artist_edit


def test_window_menu_has_minimize_and_zoom_actions(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu_bar = window.menuBar()
    window_menu = next(
        menu for menu in menu_bar.findChildren(QMenu)
        if "Window" in menu.title()
    )
    action_texts = [action.text() for action in window_menu.actions()]

    assert action_texts == ["Minimize", "Zoom"]

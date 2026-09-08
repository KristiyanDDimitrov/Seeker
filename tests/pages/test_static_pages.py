"""Tests for the Help and Support pages (seeker.ui.pages.static_pages).
Moved verbatim out of test_ui_smoke.py (round 8, §9.3.4, session
S11.1) — the mirror of §9.3.1's own Help/Support extraction (S5).
"""

from PySide6.QtWidgets import QLabel, QPushButton

from seeker.ui import help_text
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication


def test_history_and_help_pages_exist_with_their_own_subtitles(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    history_labels = [
        w.text() for w in window._history_page.findChildren(QLabel)
    ]
    assert help_text.HISTORY_PAGE_SUBTITLE in history_labels

    help_labels = [w.text() for w in window._help_page.findChildren(QLabel)]
    assert help_text.HELP_PAGE_SUBTITLE in help_labels


# --- Help page (roadmap Phase 11 §Help) -------------------------------------

def test_help_page_shows_walkthrough_and_troubleshooting(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    labels_html = "\n".join(
        w.text() for w in window._help_page.findChildren(QLabel)
    )

    assert "How Seeker works" in labels_html
    assert "Troubleshooting" in labels_html
    assert "Sync" in labels_html and "Match" in labels_html


def test_help_page_shows_the_real_resolved_data_paths(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    labels_text = [w.text() for w in window._help_page.findChildren(QLabel)]

    locations = application.data_locations
    assert str(locations.database_path) in labels_text
    assert str(locations.config_path) in labels_text
    assert str(locations.spotify_token_path) in labels_text
    assert str(locations.slskd_data_dir) in labels_text
    assert str(locations.log_dir) in labels_text


def test_open_in_file_manager_dispatches_by_platform(tmp_path, monkeypatch):
    # _open_in_file_manager (round 8 §9.3.1) now lives in
    # seeker.ui.pages.static_pages, alongside the Help page that's its
    # only caller.
    from seeker.ui.pages.static_pages import _open_in_file_manager

    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        "seeker.ui.pages.static_pages.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    target = tmp_path / "does" / "not" / "exist" / "yet"

    monkeypatch.setattr("seeker.ui.pages.static_pages.sys.platform", "darwin")
    _open_in_file_manager(target)
    assert calls[-1] == (["open", str(target)], {"check": False})
    assert target.is_dir()  # created on demand, per the docstring

    monkeypatch.setattr("seeker.ui.pages.static_pages.sys.platform", "win32")
    _open_in_file_manager(target)
    assert calls[-1] == (["explorer", str(target)], {"check": False})

    monkeypatch.setattr("seeker.ui.pages.static_pages.sys.platform", "linux")
    _open_in_file_manager(target)
    assert calls[-1] == (["xdg-open", str(target)], {"check": False})


def test_open_data_folder_button_calls_the_file_manager_opener(
        qtbot, monkeypatch,
):
    # HelpPage's click handler resolves _open_in_file_manager from its
    # own module's globals (seeker.ui.pages.static_pages), not
    # main_window's — see the identical note above.
    from seeker.ui.pages import static_pages as static_pages_module

    opened: list = []
    monkeypatch.setattr(
        static_pages_module, "_open_in_file_manager",
        opened.append,
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    button = next(
        widget for widget in window._help_page.findChildren(QPushButton)
        if widget.text() == help_text.OPEN_DATA_FOLDER_BUTTON_TEXT
    )
    button.click()

    assert opened == [application.data_locations.base_dir]


def test_open_log_folder_button_calls_the_file_manager_opener(
        qtbot, monkeypatch,
):
    from seeker.ui.pages import static_pages as static_pages_module

    opened: list = []
    monkeypatch.setattr(
        static_pages_module, "_open_in_file_manager",
        opened.append,
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    button = next(
        widget for widget in window._help_page.findChildren(QPushButton)
        if widget.text() == help_text.OPEN_LOG_FOLDER_BUTTON_TEXT
    )
    button.click()

    assert opened == [application.data_locations.log_dir]


def test_help_page_shows_build_identity_and_per_account_note(qtbot):
    # Roadmap item 81 (0.1/0.2)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    combined = "\n".join(
        widget.text() for widget in window._help_page.findChildren(QLabel)
    )

    assert "Build:" in combined
    assert "per macOS user account" in combined


# --- Support page (roadmap item 64) -----------------------------------

def test_support_page_exists_directly_below_help_in_the_sidebar(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert "support" in window._page_indices
    labels = [
        w.text() for w in window._support_page.findChildren(QLabel)
    ]
    assert help_text.SUPPORT_TAB_SUBTITLE in labels

    # Directly below Help — both individually-built (not part of the
    # generic _NAV_PAGES loop), so this checks real sidebar layout order
    # rather than just dict/insertion order.
    sidebar = window._nav_buttons["help"].parentWidget()
    assert sidebar is window._nav_buttons["support"].parentWidget()
    layout = sidebar.layout()
    assert layout is not None
    indices = [
        layout.indexOf(window._nav_buttons[key]) for key in ("help", "support")
    ]
    assert indices[1] == indices[0] + 1


def test_support_page_shows_honest_framing_and_non_financial_help(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    labels_html = "\n".join(
            w.text() for w in window._support_page.findChildren(QLabel)
    )

    assert "no telemetry" in labels_html
    assert "no paid tier" in labels_html
    assert "thank-you, not a purchase" in labels_html
    assert "Report a bug" in labels_html
    assert "github.com/KristiyanDDimitrov/Seeker/issues" in labels_html
    assert "Share your library back on SoulSeek" in labels_html
    assert "Kristiyan Dimitrov" in labels_html  # ABOUT_DIALOG_AUTHOR_LINE, reused


def test_support_page_renders_a_button_for_every_real_support_link(
        qtbot, monkeypatch,
):
    # build_support_links_row() (round 8 §9.3.1) lives in seeker.ui.dialogs
    # now, shared from there by both AboutDialog and the Support page —
    # patch the module that actually calls webbrowser.open, not
    # main_window (webbrowser is a stdlib singleton module either way,
    # so this patches the same real object regardless of which name
    # reaches it).
    from seeker.ui import dialogs as dialogs_module

    opened: list[str] = []
    monkeypatch.setattr(
        dialogs_module.webbrowser, "open", opened.append
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    buttons = [
        widget
        for widget in window._support_page.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert len(buttons) == len(help_text.SUPPORT_LINKS)
    assert {button.text() for button in buttons} == {
        f"Support on {name}" for name in help_text.SUPPORT_LINKS
    }

    for button in buttons:
        button.click()

    assert set(opened) == set(help_text.SUPPORT_LINKS.values())


def test_support_page_go_to_sharing_button_navigates_to_sharing_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("support")
    assert window.stacked_widget.currentIndex() == window._page_indices[
            "support"
    ]

    go_button = next(
        widget for widget in window._support_page.findChildren(QPushButton)
        if widget.text() == help_text.SUPPORT_PAGE_GO_TO_SHARING_BUTTON_TEXT
    )
    go_button.click()

    assert window.stacked_widget.currentIndex() == window._page_indices[
            "sharing"
    ]

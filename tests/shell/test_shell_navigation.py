"""MainWindow's shell: construction, sidebar navigation and badges,
the activity strip, page subtitles, and the Settings page's
entry and exit.
"""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
)

from fakes import (
    FakeApplication,
    make_active_download,
    make_needs_review_match,
    make_review_candidate,
    make_track,
    make_upgrade_details,
)
from seeker.ui import help_text, theme
from seeker.ui.icons import nav_icon
from seeker.ui.main_window import (
    MainWindow,
)


def test_main_window_constructs_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Roadmap item 98 (B10) — reversed from item 81 (0.1): a commit SHA
    # in the window title looked like a bug even when it wasn't one.
    # Build identity's real home is Help -> About Seeker (see
    # test_about_dialog_shows_build_identity), unaffected by this.
    assert window.windowTitle() == "Seeker"


# --- Sidebar shell (Phase 4) ------------------------------------------------

def test_default_and_minimum_window_size(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert (window.width(), window.height()) == (1180, 760)
    assert window.minimumWidth() == 960
    assert window.minimumHeight() == 640


def test_dashboard_is_the_default_active_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.stacked_widget.currentIndex() == window._page_indices[
            "dashboard"
    ]
    assert window._nav_buttons["dashboard"].isChecked()


def test_show_page_switches_stack_and_updates_checked_nav_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("downloads")

    assert window.stacked_widget.currentIndex() == window._page_indices[
            "downloads"
    ]
    assert window._nav_buttons["downloads"].isChecked()
    assert not window._nav_buttons["dashboard"].isChecked()


def test_nav_buttons_are_mutually_exclusive_including_settings(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Every real page (Dashboard/Library/Search/Downloads/Review/
    # Duplicates/Sharing/History) plus Help, Support, and Settings share
    # one exclusive QButtonGroup — roadmap item 56 Phase 3 reversed item
    # 48's "Settings stays a separate dialog" decision, so it's now a
    # real, checkable nav-group member like every other page; item 64
    # added Support the same way, item 82 added Search the same way,
    # round 8 §12.6 added Library the same way.
    assert set(window._nav_buttons) == {
        "dashboard", "library", "search", "downloads", "review",
        "duplicates", "sharing", "history", "help", "support", "settings",
    }
    assert window._nav_group.exclusive()
    for key in window._nav_buttons:
        assert window._nav_buttons[key] in window._nav_group.buttons()
    assert window.settings_button.isCheckable()


def test_every_sidebar_button_carries_its_pages_icon(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    for key, button in window._nav_buttons.items():
        assert not button.icon().isNull(), key
        assert button.iconSize() == QSize(
            theme.NAV_ICON_PX, theme.NAV_ICON_PX,
        ), key
        # The same drawing nav_icon(key) makes: compared as pixels,
        # since each QIcon is a separate engine instance.
        assert button.icon().pixmap(QSize(18, 18)).toImage() == (
            nav_icon(key).pixmap(QSize(18, 18)).toImage()
        ), key


def test_downloads_and_review_nav_badges_show_live_counts(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._nav_buttons["downloads"].text() == "Downloads"
    assert window._nav_buttons["review"].text() == "Review"

    window._downloads_page._render_active_downloads(
        [make_active_download(track_id="d1"), make_active_download(track_id="d2")]
    )
    assert window._nav_buttons["downloads"].text() == "Downloads  (2)"

    window._review_page._render_review_items(
        ([(make_track("t1"), make_review_candidate("t1"))], [], [])
    )
    assert window._nav_buttons["review"].text() == "Review  (1)"

    # Back to zero must drop the badge entirely, not show "(0)".
    window._downloads_page._render_active_downloads([])
    assert window._nav_buttons["downloads"].text() == "Downloads"


# --- Busy-action registry / activity strip (roadmap item 65, Phase 2) -----

def test_activity_strip_hidden_when_nothing_running(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_activity_strip()
    assert window.activity_strip.isHidden()


def test_activity_strip_shows_label_for_a_single_running_action(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin("scan", window._dashboard_page.scan_button, "Scanning…")
    window._render_activity_strip()

    assert not window.activity_strip.isHidden()
    assert (
        window.activity_strip_label.text()
        == "Scanning library and matching tracks…"
    )
    assert window.activity_strip_bar.minimum() == 0
    assert window.activity_strip_bar.maximum() == 0  # indeterminate

    window.busy_actions.end("scan")
    window._render_activity_strip()
    assert window.activity_strip.isHidden()


def test_activity_strip_shows_a_count_for_multiple_running_actions(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin("scan", window._dashboard_page.scan_button)
    window.busy_actions.begin("sync", window._dashboard_page.sync_button)
    window._render_activity_strip()

    assert not window.activity_strip.isHidden()
    assert window.activity_strip_label.text() == "2 actions running"


def test_activity_strip_renders_real_progress_when_reported(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin(
        "compute_fingerprints",
        window._duplicates_page.compute_fingerprints_button,
    )
    window._on_activity_progress("compute_fingerprints", "Decoding", 40, 100)

    assert not window.activity_strip.isHidden()
    assert "40/100" in window.activity_strip_label.text()
    assert window.activity_strip_bar.minimum() == 0
    assert window.activity_strip_bar.maximum() == 100
    assert window.activity_strip_bar.value() == 40


def test_main_window_has_a_settings_button(qtbot):
    # Thin glue coverage only — opening the real SettingsWindow needs a
    # real Application (library_service.list_locations, sync_service,
    # download_service, _config_store, etc.), which this file's simpler
    # FakeApplication doesn't model. The real substance is covered
    # directly in tests/test_settings_window.py against a real
    # Application; this just confirms the entry point exists.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.settings_button.text() == "Settings"
    assert window.settings_button.isEnabled()


def test_main_window_global_action_buttons_have_tooltips(qtbot):
    # Task 1 — every clickable control gets a setToolTip(); spot-check
    # the Dashboard's global action row (roadmap item 7 relocated these
    # off the old QToolBar) rather than every single control (per-row/
    # per-tab controls are covered by their own dedicated tests below).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    for button in (
            window._dashboard_page.sync_button,
            window._dashboard_page.scan_button,
            window._dashboard_page.match_button,
            window._dashboard_page.download_button,
            window.settings_button,
    ):
        assert button.toolTip() != ""


def test_next_step_action_button_opens_settings_on_the_connection_tab(
        qtbot, monkeypatch,
):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window._dashboard_page.next_step_notice.isHidden(), timeout=2000,
    )
    # Drive the dispatch method directly — exercising the exact click
    # path a real InlineNotice action button takes without needing to
    # locate/click the dynamically-built button widget itself.
    window._dashboard_page._on_next_step_action("settings_connection")

    # Roadmap item 56 Phase 3 — Settings is now a persistent page, not a
    # per-open window, so the assertion is against the real navigation
    # (current page) and the same long-lived settings_page instance.
    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["settings"]
    )
    from seeker.ui.settings_window import SETTINGS_TAB_CONNECTIONS
    assert window.settings_page.tabs.tabText(
        window.settings_page.tabs.currentIndex()
    ) == SETTINGS_TAB_CONNECTIONS


def test_settings_page_shows_its_subtitle_via_build_page(qtbot):
    # SettingsPage itself no longer renders its own subtitle (§3.2) —
    # it comes from the shared _build_page() wrapper, same as every
    # other page's header.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    settings_wrapper = window.stacked_widget.widget(
        window._page_indices["settings"]
    )
    labels = [
        widget.text() for widget in settings_wrapper.findChildren(QLabel)
    ]
    assert help_text.SETTINGS_WINDOW_SUBTITLE in labels


def test_settings_is_left_through_the_sidebar_alone(qtbot):
    # One navigation model: every page Settings can be opened from has
    # a sidebar button, so a Back button would only duplicate one.
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    assert set(window._nav_buttons) == set(window._page_indices)
    settings_wrapper = window.stacked_widget.widget(
        window._page_indices["settings"]
    )
    assert not [
        button for button in settings_wrapper.findChildren(QPushButton)
        if "Back" in button.text()
    ]


def test_leaving_settings_refreshes_duplicates_locations_and_next_step(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("settings")
    window._show_page("dashboard")

    qtbot.waitUntil(
        lambda: application.library_service.list_locations_calls >= 1,
        timeout=2000,
    )


def test_settings_about_button_is_wired_to_mainwindows_about_dialog(qtbot):
    # Reuses the exact same AboutDialog/copy as the Help-menu route
    # (§3.4) — checked via the wiring itself (settings_page's callback
    # is literally MainWindow's own _on_about_clicked), not a second
    # dialog construction path.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.settings_page._on_about_requested == window._on_about_clicked

    triggered = []
    window.settings_page._on_about_requested = lambda: triggered.append(True)
    window.settings_page.about_button.click()

    assert triggered == [True]


def test_dashboard_downloads_review_pages_have_persistent_subtitles(qtbot):
    # Task 1 — a short, persistent (not hover-dependent) one-liner under
    # each page's own header. Phase 4 moved these from a QTabWidget into
    # a sidebar-driven QStackedWidget — each page is looked up by its
    # own registered index, not a bare tab position.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    stack = window.stacked_widget
    dashboard_labels = [
        widget.text()
        for widget in stack.widget(window._page_indices["dashboard"])
        .findChildren(QLabel)
    ]
    assert help_text.DASHBOARD_TAB_SUBTITLE in dashboard_labels

    downloads_labels = [
        widget.text()
        for widget in stack.widget(window._page_indices["downloads"])
        .findChildren(QLabel)
    ]
    assert help_text.DOWNLOADS_TAB_SUBTITLE in downloads_labels

    review_labels = [
        widget.text()
        for widget in stack.widget(window._page_indices["review"])
        .findChildren(QLabel)
    ]
    assert help_text.REVIEW_TAB_SUBTITLE in review_labels


def test_review_nav_badge_counts_all_three_sections(qtbot):
    application = FakeApplication(
        review_candidates=[
            (make_track(track_id="tc"), make_review_candidate(track_id="tc"))
        ],
        pending_upgrades=[make_upgrade_details(request_id=5)],
        needs_review_matches=[make_needs_review_match(track_id="tl")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._nav_buttons["review"].text() == "Review  (3)",
        timeout=2000,
    )

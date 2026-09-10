"""Tests for the History page (seeker.ui.pages.history_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.1) — the
mirror of §9.3.1's own History extraction (S5).

`_make_history_event` stays defined in test_ui_smoke.py rather than
moving here — Tray's own download-notification tests (staying there
until S11.7) use it too, and there is no shared fixtures module yet for
a factory two future test files both need. Imported from there below.
"""

from PySide6.QtCore import Qt
from pytestqt.exceptions import TimeoutError as QtBotTimeoutError

from seeker.models.history_event import DOWNLOADED, TAGGED
from seeker.ui import workers
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication, _make_history_event


def test_history_table_sorts_the_when_column_chronologically(qtbot):
    # Round 8 §12.2 — "When" displays a formatted "Feb 01, 2026" label,
    # which sorts "Feb" before "Jan" as plain text (alphabetically
    # wrong — January is chronologically first). SortKeyItem's real
    # ISO occurred_at sort key is what must actually drive the sort.
    events = [
        _make_history_event(occurred_at="2026-02-01T00:00:00+00:00"),
        _make_history_event(occurred_at="2026-01-15T00:00:00+00:00"),
    ]
    application = FakeApplication(history_events=events)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("history")

    qtbot.waitUntil(
        lambda: window._history_page.history_table.rowCount() == 2, timeout=2000,
    )

    window._history_page.history_table.sortItems(0, Qt.SortOrder.AscendingOrder)

    assert "Jan 15" in window._history_page.history_table.item(0, 0).text()
    assert "Feb 1," in window._history_page.history_table.item(1, 0).text()


def test_history_page_has_the_right_table_columns(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    labels = [
        window._history_page.history_table.horizontalHeaderItem(i).text()
        for i in range(window._history_page.history_table.columnCount())
    ]
    assert labels == ["When", "What", "Track", "Detail"]


def test_history_page_fetches_and_renders_events_on_first_visit(qtbot):
    events = [
        _make_history_event(),
        _make_history_event(
            event_type=TAGGED, occurred_at="2026-01-01T00:00:00+00:00",
            track_artist="Kamäleon", track_title="Quadrat",
            playlist_name="Test", detail="Tagged with Spotify metadata",
        ),
    ]
    application = FakeApplication(history_events=events)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")

    history_table = window._history_page.history_table
    qtbot.waitUntil(lambda: history_table.rowCount() == 2, timeout=2000)
    # Roadmap item R7.5 — MainWindow's own construction already makes
    # one real get_recent_events(limit=1) call to silently seed the
    # download-notification cutoff (see _seed_notification_cutoff), so
    # the History page's own first real fetch is real call #2, not #1.
    assert application.history_service.get_recent_events_calls == 2
    assert history_table.item(0, 1).text() == "Downloaded"
    assert "ZENEA - INFINITE" in history_table.item(0, 2).text()
    assert history_table.item(1, 1).text() == "Tagged"

    # Lazy-load-once, same precedent as Duplicates — switching away and
    # back must not refetch.
    window._show_page("dashboard")
    window._show_page("history")
    assert application.history_service.get_recent_events_calls == 2


def test_history_page_empty_state_message(qtbot):
    application = FakeApplication(history_events=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")

    qtbot.waitUntil(
        lambda: "no downloaded or tagged" in
        window._history_page.history_status_label.text().lower(),
        timeout=2000,
    )
    assert window._history_page.history_table.rowCount() == 0


def test_history_filter_combo_filters_by_event_type(qtbot):
    events = [
        _make_history_event(event_type=DOWNLOADED),
        _make_history_event(event_type=TAGGED),
    ]
    application = FakeApplication(history_events=events)
    window = MainWindow(application)
    qtbot.addWidget(window)

    history_table = window._history_page.history_table
    filter_combo = window._history_page.history_filter_combo
    window._show_page("history")
    qtbot.waitUntil(lambda: history_table.rowCount() == 2, timeout=2000)

    downloaded_index = filter_combo.findData(DOWNLOADED)
    filter_combo.setCurrentIndex(downloaded_index)

    assert history_table.rowCount() == 1
    assert history_table.item(0, 1).text() == "Downloaded"

    all_index = filter_combo.findData(None)
    filter_combo.setCurrentIndex(all_index)
    assert history_table.rowCount() == 2


def test_history_refresh_button_refetches(qtbot):
    application = FakeApplication(history_events=[_make_history_event()])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")
    # Roadmap item R7.5 — call #1 is MainWindow construction's own
    # silent notification-cutoff seed (see _seed_notification_cutoff);
    # this page visit is real call #2.
    qtbot.waitUntil(
        lambda: application.history_service.get_recent_events_calls == 2,
        timeout=2000,
    )

    window._history_page.history_refresh_button.click()

    # HISTORY §116/§1.4 (round 9) — this is the ~1-in-8 to 1-in-10
    # flake CLAUDE.md's Open issues tracks. On a timeout, dump the
    # dispatcher's own live state before letting the assertion fail, so
    # a real recurrence carries evidence instead of just a stack trace.
    try:
        qtbot.waitUntil(
            lambda: application.history_service.get_recent_events_calls == 3,
            timeout=2000,
        )
    except QtBotTimeoutError:
        print(
            "test_history_refresh_button_refetches timed out — "
            "worker snapshot:\n" + workers.debug_snapshot(window.thread_pool),
        )
        raise

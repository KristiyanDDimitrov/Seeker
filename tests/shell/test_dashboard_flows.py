"""The Dashboard flows MainWindow still owns: Scan, Download (its
destination dialog and result notices), the backend poll's
Dashboard refresh, and double-click through to Review.
"""
import threading
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
)

from fakes import (
    FakeApplication,
    FakeDashboardService,
    make_needs_review_match,
    make_track_status,
)
from seeker.models.download_result import (
    PlaylistDownloadResult,
    PollResult,
    TrackFailure,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_status import (
    IN_LIBRARY,
    NEEDS_REVIEW,
    TrackStatus,
)
from seeker.ui.main_window import (
    DestinationDialog,
    MainWindow,
)


def test_scan_button_click_calls_scan_and_match_not_scan_all(qtbot):
    # Roadmap item 56 — the guided scan action must chain into a match
    # pass in one call, not leave newly-scanned files unmatched until a
    # separate "Re-match library" click.
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(window._dashboard_page.scan_button.isEnabled, timeout=2000)
    window._dashboard_page.scan_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.scan_and_match_calls == 1,
        timeout=2000,
    )
    assert application.library_service.scan_all_calls == 0


def _select_first_playlist(window, qtbot) -> None:
    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    # Selecting also kicks off the "next step" facts fetch
    # (_poll_next_step), which independently enables/disables
    # download_button — wait for it to actually land rather than
    # racing a click against a button that may still be disabled from
    # the pre-selection (no playlist selected) render.
    qtbot.waitUntil(window._dashboard_page.download_button.isEnabled, timeout=2000)


def test_download_with_no_selection_shows_a_warning_notice(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page.download_button.click()

    assert "playlist" in window._dashboard_page.dashboard_notice.text().lower()
    assert not window._dashboard_page.dashboard_notice.isHidden()


def test_download_with_its_own_destination_skips_the_dialog(qtbot):
    # Roadmap item 65 (Phase 3.2) — the ONLY case that skips the dialog:
    # the playlist already has its own destination
    # (download_location_id set on the Playlist itself, loaded from the
    # DB). A resolvable configured DEFAULT alone is no longer enough to
    # skip it — see test_download_with_a_resolvable_default_still_
    # prompts_once below.
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists, resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.download_playlist_calls == ["Test"]
    # No destination needed setting — it was already the playlist's own.
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == []


def test_download_with_a_resolvable_default_still_prompts_once(
        qtbot, monkeypatch,
):
    # Roadmap item 65 (Phase 3.2) — the real, decided behavior: a
    # playlist with NO destination of its own always prompts first, even
    # when the configured default would already resolve — never a
    # silent fallback. Pre-filled with the exact real fallback (location
    # + sanitized subfolder), not just the raw playlist name.
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    dialog = opened_dialogs[0]
    assert dialog.selected_location_id() == 1
    assert dialog.subfolder_field.text() == "Test"
    # Rejected -- never silently downloaded without the user seeing it.
    assert application.download_service.download_playlist_calls == []


# --- Roadmap item 56 Phase 5.1: download button feedback -------------------

def test_download_button_shows_starting_immediately_on_click(qtbot):
    # Roadmap item 56 Phase 5.1 — the real bug: the button previously
    # gave no feedback that anything had started.
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists, resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    # Synchronous, main-thread state set at click time — true
    # immediately, not just eventually once some worker lands.
    assert window._dashboard_page.download_button.text() == "Starting download…"
    assert not window._dashboard_page.download_button.isEnabled()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.download_button.text()
            == "Download selected playlist"
        ),
        timeout=2000,
    )
    assert window._dashboard_page.download_button.isEnabled()


def test_download_button_resets_when_dialog_is_cancelled(qtbot, monkeypatch):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        DestinationDialog, "exec", lambda self: QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.download_button.text()
            == "Download selected playlist"
        ),
        timeout=2000,
    )
    assert window._dashboard_page.download_button.isEnabled()
    assert application.download_service.download_playlist_calls == []


def test_download_result_notice_reports_already_in_progress_tracks(qtbot):
    # Roadmap item 56 Phase 5.1 — how many downloads were requested,
    # and how many tracks were skipped because they were already in
    # flight (Phase 5.2's own real dedup guard reports through here).
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result=PlaylistDownloadResult(
            requested=2, skipped=3, total=5,
            already_in_progress=[
                "Artist A - Title A", "Artist B - Title B", "Artist C - Title C",
            ],
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden()
        and "Requested 2" in window._dashboard_page.dashboard_notice.text(),
        timeout=2000,
    )
    assert (
        "3 already downloading/downloaded"
        in window._dashboard_page.dashboard_notice.text()
    )


def test_download_result_notice_warns_and_lists_failed_tracks(qtbot):
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result=PlaylistDownloadResult(
            requested=1, total=2,
            failures=[TrackFailure("Artist A - Title A", "Search timed out.")],
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    notice = window._dashboard_page.dashboard_notice
    qtbot.waitUntil(
        lambda: not notice.isHidden() and "1 failed" in notice.text(),
        timeout=2000,
    )
    assert "Artist A - Title A: Search timed out." in notice.text()
    assert notice.property("variant") == "warning"


def test_download_result_notice_reports_needs_review_separately_from_skipped(
        qtbot,
):
    # Roadmap item 66 (Phase 4.2) — the real fix: "Requested 16, skipped
    # 12 (no candidates found)" was wrong when several of those 12 had
    # actually become real Review candidates, not "nothing found."
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result=PlaylistDownloadResult(
            requested=4, skipped=6, total=10,
            already_in_progress=[],
            needs_review=[
                "Prdk - ONE MORE NIGHT", "Zigi SC, A-Cray - Bit Perfect",
            ],
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden()
        and "Requested 4" in window._dashboard_page.dashboard_notice.text(),
        timeout=2000,
    )
    text = window._dashboard_page.dashboard_notice.text()
    assert "2 sent to Review" in text
    # 6 skipped total - 0 already-in-progress - 2 needs-review = 4 with
    # genuinely no candidate at all.
    assert "4 no candidate found" in text
    assert "Review page" in text


def test_download_with_no_destination_opens_dialog_prefilled_with_playlist_name(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    dialog = opened_dialogs[0]
    # Prefilled: the only real location, and the subfolder defaults to
    # the playlist's own name.
    assert dialog.selected_location_id() == 1
    assert dialog.subfolder_field.text() == "Test"
    assert dialog.remember_checkbox.isChecked()
    # Rejected — no destination call, no download.
    assert application.download_service.set_destination_calls == []
    assert application.download_service.download_playlist_calls == []


def test_download_dialog_prefills_the_configured_default_location(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    main_location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    other_location = LibraryLocation(
        id=2, name="Other", path="/other", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(main_location, True), (other_location, True)],
        resolved_destination=None,
    )
    application._config_store = replace(
        application._config_store, default_download_location_id=2,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    assert opened_dialogs[0].selected_location_id() == 2


def test_download_dialog_confirmed_with_remember_calls_set_destination_then_downloads(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.set_destination_calls == [
        ("Test", "Main", "Test"),
    ]
    assert application.persist_default_destination_calls == []
    assert application.download_service.download_playlist_calls == ["Test"]


def test_download_dialog_confirmed_without_remember_persists_the_default(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    def fake_exec(self):
        self.remember_checkbox.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DestinationDialog, "exec", fake_exec)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == [(1, True)]
    assert application.download_service.download_playlist_calls == ["Test"]


def test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_dialog(
        qtbot,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(
        playlists=playlists, locations=[], resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden(), timeout=2000,
    )
    assert "location" in window._dashboard_page.dashboard_notice.text().lower()


def test_backend_poll_runs_poll_downloads_off_the_main_thread(qtbot):
    recorded: dict[str, threading.Thread] = {}

    class RecordingDownloadService:
        def poll_downloads(self) -> PollResult:
            recorded["thread"] = threading.current_thread()
            return PollResult()

    application = FakeApplication(soulseek_configured=True)
    application.download_service = RecordingDownloadService()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    # Wait for the FULL round trip (the queued completion signal
    # actually delivered on the main thread), not just for the
    # background function itself to have returned — `recorded["thread"]`
    # is set inside poll_downloads() on the worker thread, microseconds
    # before run_worker()'s completion signal is even emitted, so
    # waiting on it alone raced ahead of signal delivery (confirmed
    # live: this caused a real, reproducible segfault in a LATER test's
    # teardown, when the still-queued signal was finally delivered
    # against this test's already-destroyed window/button — see
    # CLAUDE.md/docs/HISTORY.md item 39). `_backend_poll_in_progress`
    # only flips False from the main-thread on_finished callback, so
    # waiting on it — same as test_backend_poll_overlap_guard_skips_
    # concurrent_tick already correctly does — guarantees the signal
    # was actually processed before the test ends.
    qtbot.waitUntil(
        lambda: "thread" in recorded and not window._backend_poll_in_progress,
        timeout=2000,
    )

    assert recorded["thread"] != threading.main_thread()


def test_backend_poll_refreshes_selected_playlist_track_table(qtbot):
    # Phase 1 UI follow-on: a settled download completing during a real
    # backend poll should flip the Dashboard to IN_LIBRARY immediately,
    # not wait up to the 2s display tick to happen to catch it.
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page.selected_playlist = Playlist(
        id="p1", name="Test Playlist", track_count=1,
    )
    dashboard_service = application.dashboard_service
    assert isinstance(dashboard_service, FakeDashboardService)
    dashboard_service.calls.clear()

    window._trigger_backend_poll()

    qtbot.waitUntil(
        lambda: "Test Playlist" in dashboard_service.calls, timeout=2000,
    )


def test_backend_poll_skipped_when_soulseek_not_configured(qtbot):
    application = FakeApplication(soulseek_configured=False)
    calls = []
    application.download_service.poll_downloads = lambda: calls.append(1)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    assert calls == []


def test_backend_poll_overlap_guard_skips_concurrent_tick(qtbot):
    call_count = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    class SlowDownloadService:
        def poll_downloads(self) -> PollResult:
            call_count["n"] += 1
            started.set()
            release.wait(timeout=5)
            return PollResult()

    application = FakeApplication(soulseek_configured=True)
    application.download_service = SlowDownloadService()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()
    assert started.wait(timeout=2)

    # A second tick while the first poll_downloads() call is still
    # running must be skipped, not start a second concurrent writer.
    window._trigger_backend_poll()

    release.set()
    qtbot.waitUntil(
        lambda: not window._backend_poll_in_progress, timeout=2000,
    )

    assert call_count["n"] == 1


# --- Roadmap item 56 §2.4: Dashboard double-click -> Review -----------------

def test_double_clicking_needs_review_row_navigates_to_review_and_selects_it(
        qtbot,
):
    status = make_track_status(track_id="t1", state=NEEDS_REVIEW)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
        needs_review_matches=[make_needs_review_match(track_id="t1")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 1, timeout=2000,
    )
    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["review"]
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.selectedItems() != [],
        timeout=2000,
    )
    assert window._review_page.review_local_table.currentRow() == 0


def test_double_clicking_in_library_row_is_a_no_op(qtbot):
    status = make_track_status(track_id="t1", state=IN_LIBRARY)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 1, timeout=2000,
    )
    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["dashboard"]
    )


def test_double_click_after_sorting_the_track_table_navigates_to_the_right_row(
        qtbot,
):
    # Round 8 §12.2 — the track table is now sortable; a row-position
    # lookup into _current_track_statuses (this table's insertion-order
    # list) would resolve the WRONG track the moment a user sorts.
    # track_table's own row-anchor (UserRole data set in
    # _render_track_statuses) is what must be read instead.
    status_a = TrackStatus(
        track=Track(
            id="ta", title="Zzz Last", artist="Zzz Artist", album="Album",
            duration_ms=200_000,
        ),
        state=IN_LIBRARY,
    )
    status_b = TrackStatus(
        track=Track(
            id="tb", title="Aaa First", artist="Aaa Artist", album="Album",
            duration_ms=200_000,
        ),
        state=NEEDS_REVIEW,
    )
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=2)],
        statuses=[status_a, status_b],
        needs_review_matches=[make_needs_review_match(track_id="tb")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 2, timeout=2000,
    )
    # Sort ascending by the Track column — "Aaa Artist..." (status_b,
    # inserted second) now sits at row 0.
    window._dashboard_page.track_table.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert (
        window._dashboard_page.track_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        == "tb"
    )

    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["review"]
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )

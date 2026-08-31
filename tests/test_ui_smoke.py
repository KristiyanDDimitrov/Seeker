import threading
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QRadioButton,
)

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_status import (
    IN_LIBRARY,
    NOT_FOUND,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.ui import help_text
from seeker.ui.main_window import AboutDialog, MainWindow
from seeker.ui import workers as workers_module
from seeker.ui.workers import Worker, run_worker


# Per this project's own testing philosophy, applied to the UI layer:
# widget construction/wiring is thin glue around already-tested
# services (cli.py/main.py's argparse dispatch gets the same light
# treatment) — these are smoke tests confirming the window builds and
# the worker abstraction's signals fire correctly, not deep Qt coverage.


class FakeSyncService:
    def __init__(self, playlists: list[Playlist] | None = None):
        self._playlists = playlists or []
        self.sync_playlists_calls = 0
        self.sync_playlist_tracks_calls: list[Playlist] = []

    def list_playlists(self) -> list[Playlist]:
        return self._playlists

    def sync_playlists(self) -> None:
        self.sync_playlists_calls += 1

    def sync_playlist_tracks(self, playlist: Playlist) -> None:
        self.sync_playlist_tracks_calls.append(playlist)


class FakeDashboardService:
    def __init__(
            self,
            statuses: list | None = None,
            active_downloads: list | None = None,
    ):
        self._statuses = statuses or []
        self._active_downloads = active_downloads or []
        self.calls: list[str] = []

    def get_playlist_track_status(self, playlist_name: str) -> list:
        self.calls.append(playlist_name)
        return self._statuses

    def get_active_downloads(self) -> list:
        return self._active_downloads


class FakeLibraryService:
    def __init__(self, locations: list | None = None):
        self._locations = locations or []

    def scan_all(self) -> None:
        pass

    def list_locations(self) -> list:
        return self._locations


class FakeDuplicateService:
    def __init__(
            self,
            fingerprint_result: dict | None = None,
            groups: list | None = None,
            delete_result: dict | None = None,
    ):
        self._fingerprint_result = fingerprint_result or {
            "computed": 0, "skipped_already_computed": 0, "failed": 0,
            "details": [],
        }
        self._groups = groups or []
        self._delete_result = delete_result or {
            "deleted": 0, "failed": 0, "details": [],
        }
        self.compute_fingerprints_calls: list[str] = []
        self.find_duplicate_groups_calls: list[str] = []
        self.delete_local_files_calls: list[tuple[list[int], int | None]] = []

    def compute_fingerprints(self, location_name: str) -> dict:
        self.compute_fingerprints_calls.append(location_name)
        return self._fingerprint_result

    def find_duplicate_groups(self, location_name: str) -> list:
        self.find_duplicate_groups_calls.append(location_name)
        return self._groups

    def delete_local_files(
            self,
            local_file_ids: list[int],
            keep_local_file_id: int | None = None,
    ) -> dict:
        self.delete_local_files_calls.append((local_file_ids, keep_local_file_id))
        return self._delete_result


class FakeTrackMatcher:
    def match_all(self) -> dict:
        return {"auto": 0, "needs_review": 0, "unmatched": 0}


class FakeDownloadService:
    def __init__(
            self,
            review_candidates: list | None = None,
            pending_upgrades: list | None = None,
    ):
        self._review_candidates = review_candidates or []
        self._pending_upgrades = pending_upgrades or []
        self.confirm_review_candidate_calls: list[str] = []
        self.reject_review_candidate_calls: list[str] = []
        self.apply_upgrade_decision_calls: list[tuple[int, bool, bool]] = []
        self.apply_upgrade_decision_result: str | None = "Replaced with /new/path"

    def download_playlist(self, playlist_name: str) -> dict:
        return {"requested": 0, "skipped": 0, "failed": 0, "total": 0}

    def poll_downloads(self) -> dict:
        return {}

    def get_review_candidates(self) -> list:
        return self._review_candidates

    def get_pending_upgrade_reviews(self) -> list:
        return self._pending_upgrades

    def confirm_review_candidate(self, track_id: str) -> None:
        self.confirm_review_candidate_calls.append(track_id)

    def reject_review_candidate(self, track_id: str) -> None:
        self.reject_review_candidate_calls.append(track_id)

    def apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool = False,
    ) -> str | None:
        self.apply_upgrade_decision_calls.append((request_id, replace, delete_old))
        return self.apply_upgrade_decision_result if replace else None


_EMPTY_TAG_RESULT = {
    "tagged": 0,
    "skipped_no_match": 0,
    "skipped_format_unsupported": 0,
    "skipped_already_tagged": 0,
    "skipped_already_analyzed": 0,
    "failed": 0,
    "details": [],
}


class FakeMetadataService:
    def __init__(self, tag_result: dict | None = None):
        self._tag_result = tag_result or dict(_EMPTY_TAG_RESULT)
        self.tag_tracks_calls: list[tuple[list[str], bool, tuple | None]] = []
        self.tag_playlist_calls: list[tuple[str, bool, tuple | None]] = []

    def tag_tracks(
            self,
            track_ids: list[str],
            analyze_audio: bool = False,
            expected_bpm_range: tuple | None = None,
            force: bool = False,
    ) -> dict:
        self.tag_tracks_calls.append(
            (track_ids, analyze_audio, expected_bpm_range)
        )
        return self._tag_result

    def tag_playlist(
            self,
            playlist_name: str,
            analyze_audio: bool = False,
            expected_bpm_range: tuple | None = None,
            force: bool = False,
    ) -> dict:
        self.tag_playlist_calls.append(
            (playlist_name, analyze_audio, expected_bpm_range)
        )
        return self._tag_result


class FakeApplication:
    def __init__(
            self,
            playlists: list[Playlist] | None = None,
            statuses: list | None = None,
            active_downloads: list | None = None,
            soulseek_configured: bool = False,
            review_candidates: list | None = None,
            pending_upgrades: list | None = None,
            tag_result: dict | None = None,
            locations: list | None = None,
            fingerprint_result: dict | None = None,
            duplicate_groups: list | None = None,
    ):
        self.sync_service = FakeSyncService(playlists)
        self.dashboard_service = FakeDashboardService(
            statuses, active_downloads,
        )
        self.library_service = FakeLibraryService(locations)
        self.track_matcher = FakeTrackMatcher()
        self.download_service = FakeDownloadService(
            review_candidates, pending_upgrades,
        )
        self.metadata_service = FakeMetadataService(tag_result)
        self.duplicate_service = FakeDuplicateService(
            fingerprint_result, duplicate_groups,
        )
        self.soulseek_configured = soulseek_configured


def test_main_window_constructs_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.windowTitle() == "Seeker"


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


def test_main_window_toolbar_buttons_have_tooltips(qtbot):
    # Task 1 — every clickable control gets a setToolTip(); spot-check
    # the toolbar rather than every single control (per-row/per-tab
    # controls are covered by their own dedicated tests below).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    for button in (
            window.sync_button,
            window.scan_button,
            window.match_button,
            window.download_button,
            window.settings_button,
    ):
        assert button.toolTip() != ""


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


def test_about_dialog_opens_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dialog = AboutDialog(window)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == help_text.ABOUT_DIALOG_TITLE


def test_about_dialog_support_buttons_open_placeholder_links(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module.webbrowser, "open", lambda url: opened.append(url)
    )

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    buttons = [
        widget
        for widget in dialog.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert len(buttons) == len(help_text.SUPPORT_LINKS)

    for button in buttons:
        button.click()

    assert set(opened) == set(help_text.SUPPORT_LINKS.values())


def test_dashboard_downloads_review_tabs_have_persistent_subtitles(qtbot):
    # Task 1 — a short, persistent (not hover-dependent) one-liner under
    # each tab's own header.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    tabs = window.centralWidget()
    dashboard_labels = [
        widget.text()
        for widget in tabs.widget(0).findChildren(QLabel)
    ]
    assert help_text.DASHBOARD_TAB_SUBTITLE in dashboard_labels

    downloads_labels = [
        widget.text()
        for widget in tabs.widget(1).findChildren(QLabel)
    ]
    assert help_text.DOWNLOADS_TAB_SUBTITLE in downloads_labels

    review_labels = [
        widget.text()
        for widget in tabs.widget(2).findChildren(QLabel)
    ]
    assert help_text.REVIEW_TAB_SUBTITLE in review_labels


def test_main_window_populates_playlist_list_from_service(qtbot):
    playlists = [Playlist(id="p1", name="Test Playlist", track_count=3)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)

    assert "Test Playlist" in window.playlist_list.item(0).text()


def test_main_window_shows_sync_tracks_prompt_when_playlist_has_no_tracks(
        qtbot,
):
    # No auto-fetch of Spotify tracks on selection — an explicit button
    # instead (roadmap item 1's scoped-sync-tracks split).
    playlists = [Playlist(id="p1", name="Empty Playlist", track_count=0)]
    application = FakeApplication(playlists=playlists, statuses=[])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)

    qtbot.waitUntil(
        lambda: window.sync_tracks_button.isVisible(), timeout=2000,
    )
    assert application.sync_service.sync_playlist_tracks_calls == []


def test_worker_emits_finished_with_result():
    # Worker no longer owns a per-instance `.signals` object — every
    # worker reports through the one shared, permanently-connected
    # `_dispatcher` (see workers.py's own docstring for why: a fresh
    # per-task QObject+connect()/disconnect() cycle was confirmed live
    # to cause a real, reproducible deadlock). Connect directly to the
    # dispatcher and filter by task_id, the same way _handle_task_finished
    # itself does — the signal carries a plain int, never the Worker
    # instance itself (see Worker's own docstring for why).
    worker = Worker(lambda: 42)
    results = []

    def on_finished(task_id: int, result: object) -> None:
        if task_id == worker.task_id:
            results.append(result)

    # Disconnected in finally — this connects to the one PERMANENT,
    # shared dispatcher, so a test-local connection left dangling would
    # linger for the rest of the process, not just this test.
    workers_module._dispatcher.task_finished.connect(on_finished)
    try:
        worker.run()
    finally:
        workers_module._dispatcher.task_finished.disconnect(on_finished)

    assert results == [42]


def test_worker_emits_error_on_exception():
    def boom():
        raise RuntimeError("simulated failure")

    worker = Worker(boom)
    errors = []

    def on_error(task_id: int, message: str) -> None:
        if task_id == worker.task_id:
            errors.append(message)

    workers_module._dispatcher.task_error.connect(on_error)
    try:
        worker.run()
    finally:
        workers_module._dispatcher.task_error.disconnect(on_error)

    assert errors == ["simulated failure"]


def test_run_worker_disables_button_while_running_and_reenables(qtbot):
    button = QPushButton("Go")
    qtbot.addWidget(button)

    button_state_during_run = []

    class SynchronousPool:
        def start(self, worker):
            button_state_during_run.append(button.isEnabled())
            worker.run()

    run_worker(SynchronousPool(), lambda: "done", button=button)

    assert button_state_during_run == [False]
    assert button.isEnabled() is True


def test_run_worker_error_sets_status_label_and_reenables_button(qtbot):
    from PySide6.QtWidgets import QLabel

    button = QPushButton("Go")
    label = QLabel("")
    qtbot.addWidget(button)
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise RuntimeError("real failure text")

    run_worker(SynchronousPool(), boom, button=button, status_label=label)

    assert label.text() == "real failure text"
    assert button.isEnabled() is True


def test_run_worker_registry_releases_worker_on_both_success_and_error():
    # _callbacks (see workers.py's own comment) holds each in-flight
    # task's callback entry, keyed by task_id, until that task's own
    # completion pops it — if cleanup only fired on the success path, a
    # worker that raises would stay referenced forever, a real leak on
    # every failed sync/scan/match/download. Asserted directly against
    # the registry itself, not just inferred from button/label side
    # effects.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    run_worker(SynchronousPool(), lambda: "ok")
    assert len(workers_module._callbacks) == baseline

    def boom():
        raise RuntimeError("simulated failure")

    run_worker(SynchronousPool(), boom)
    assert len(workers_module._callbacks) == baseline


def test_run_worker_on_finished_exception_does_not_propagate(qtbot):
    # A bug in a render/completion callback (not the fetch itself) must
    # not escape run_worker uncontrolled — confirmed live this doesn't
    # crash the app or stop the triggering QTimer either way, but
    # nothing in this codebase's own code caught it before this fix;
    # only PySide6's own default exception hook did, an implicit safety
    # net rather than an intentional one.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    # Must not raise out of this call.
    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)


def test_run_worker_on_finished_exception_surfaces_to_status_label(qtbot):
    from PySide6.QtWidgets import QLabel

    label = QLabel("")
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(
        SynchronousPool(),
        lambda: "ok",
        status_label=label,
        on_finished=render_that_raises,
    )

    assert "malformed render data" in label.text()


def test_run_worker_on_finished_exception_without_status_label_still_safe(qtbot):
    # The periodic-poll shape (e.g. the Downloads/Review tabs' 2s
    # refresh) — no status_label wired at all, by design, so a fetch
    # error doesn't flash a noisy message every tick. A render bug must
    # still not propagate even here.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)


def test_run_worker_on_error_exception_does_not_propagate(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise RuntimeError("fetch failed")

    def on_error_that_raises(message):
        raise ValueError("bug in on_error handling")

    # Must not raise out of this call either.
    run_worker(SynchronousPool(), boom, on_error=on_error_that_raises)


def test_run_worker_on_finished_exception_still_releases_worker_registry(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)

    assert len(workers_module._callbacks) == baseline


def _make_active_download(
        track_id: str = "t1",
        status: str = "downloading",
        role: str = "settled",
        bytes_transferred: int | None = 500,
        total_bytes: int | None = 1_000,
        playlist_name: str = "Playlist A",
) -> ActiveDownload:
    return ActiveDownload(
        request=DownloadRequest(
            track_id=track_id,
            username="peer1",
            filename="file.flac",
            format="flac",
            role=role,
            status=status,
            requested_at="2026-01-01T00:00:00+00:00",
            bytes_transferred=bytes_transferred,
            total_bytes=total_bytes,
        ),
        track=Track(
            id=track_id, title="Title", artist="Artist", album="Album",
            duration_ms=200_000,
        ),
        playlist_name=playlist_name,
    )


def test_downloads_tab_renders_rows_across_playlists(qtbot):
    downloads = [
        _make_active_download(track_id="t1", playlist_name="Playlist A"),
        _make_active_download(
            track_id="t2", status="locked", role="upgrade",
            bytes_transferred=None, total_bytes=None,
            playlist_name="Playlist B",
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads(downloads)

    assert window.downloads_table.rowCount() == 2
    assert window.downloads_table.item(0, 1).text() == "Playlist A"
    assert window.downloads_table.item(1, 1).text() == "Playlist B"
    # A raw "locked" status gets a plain-language note, not the raw
    # state string.
    assert window.downloads_table.item(1, 3).text() == "Retrying (locked)"


def test_downloads_tab_progress_bar_indeterminate_with_no_bytes_yet(qtbot):
    download = _make_active_download(
        status="queued", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    bar = window.downloads_table.cellWidget(0, 4)
    assert isinstance(bar, QProgressBar)
    assert bar.minimum() == 0
    assert bar.maximum() == 0


def test_downloads_tab_progress_bar_determinate_with_real_bytes(qtbot):
    # A determinate bar is wrapped in a container alongside the ETA
    # label (Task 2) — the bar itself is a child widget, not the cell
    # widget directly (unlike the indeterminate/no-progress cases above,
    # which are left unchanged).
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.maximum() == 1_000
    assert bar.value() == 500


def test_downloads_tab_locked_row_has_no_progress_bar(qtbot):
    # Locked/shortlisted rows have no real, current transfer — a
    # progress claim there would be misleading.
    download = _make_active_download(
        status="locked", role="upgrade",
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    bar = window.downloads_table.cellWidget(0, 4)
    assert not isinstance(bar, QProgressBar)


def test_downloads_tab_eta_shows_calculating_before_second_sample(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "Calculating…"


def test_downloads_tab_eta_shows_estimate_after_two_samples(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(timezone.utc)
    # 400 bytes/second over the last interval, 400 bytes remaining ->
    # a clean 1s ETA, easy to assert on exactly.
    window._eta_tracker.record(1, 200, now - timedelta(seconds=1))
    window._eta_tracker.record(1, 600, now)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "1s"


def test_downloads_tab_eta_shows_stalled_after_flat_samples(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(timezone.utc)
    for offset in (2, 1, 0):
        window._eta_tracker.record(1, 600, now - timedelta(seconds=offset))

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "Stalled"


def test_record_eta_samples_evicts_ids_no_longer_active(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(timezone.utc)
    window._eta_tracker.record(1, 100, now)
    window._eta_tracker.record(1, 200, now)

    # request id 1 has since disappeared from get_active_downloads() —
    # completed, failed, or superseded — so a fresh sampling pass with
    # no row for it must drop its history rather than keep it forever
    # (Task 2's own explicit leak-prevention requirement).
    window._record_eta_samples([])

    assert window._eta_tracker.describe(1, 1_000) == "Calculating…"


def test_trigger_backend_poll_samples_eta_after_poll_succeeds(qtbot):
    download = _make_active_download(bytes_transferred=500, total_bytes=1_000)
    download.request.id = 7

    application = FakeApplication(
        soulseek_configured=True, active_downloads=[download],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    qtbot.waitUntil(lambda: 7 in window._eta_tracker._history, timeout=2000)


def test_backend_poll_runs_poll_downloads_off_the_main_thread(qtbot):
    recorded: dict[str, threading.Thread] = {}

    class RecordingDownloadService:
        def poll_downloads(self) -> dict:
            recorded["thread"] = threading.current_thread()
            return {}

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

    window.selected_playlist = Playlist(
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
        def poll_downloads(self) -> dict:
            call_count["n"] += 1
            started.set()
            release.wait(timeout=5)
            return {}

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


def _make_track(track_id: str = "t1") -> Track:
    return Track(
        id=track_id, title="Title", artist="Artist", album="Album",
        duration_ms=200_000,
    )


def _make_review_candidate(
        track_id: str = "t1",
        score: float = 73.2,
) -> SoulseekReviewCandidate:
    return SoulseekReviewCandidate(
        track_id=track_id,
        username="peer1",
        filename="Artist - Title (Original Mix).flac",
        score=score,
        quality_descriptor="flac",
        found_at="2026-01-01T00:00:00+00:00",
        size=1_000_000,
    )


def _make_upgrade_details(
        request_id: int = 1,
        old_file_path: str | None = "/music/old.mp3",
) -> UpgradeReviewDetails:
    return UpgradeReviewDetails(
        request_id=request_id,
        track=_make_track(),
        quality_descriptor="flac 1000kbps",
        current_description="mp3",
        old_file_path=old_file_path,
    )


def test_review_tab_renders_needs_review_candidates(qtbot):
    candidates = [(_make_track(), _make_review_candidate())]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_needs_review_candidates(candidates)

    assert window.review_needs_table.rowCount() == 1
    assert window.review_needs_table.item(0, 0).text() == "Artist - Title"
    assert window.review_needs_table.item(0, 1).text() == "73.2"
    assert "peer1" in window.review_needs_table.item(0, 2).text()

    actions = window.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    assert set(buttons) == {"Confirm", "Reject"}


def test_review_tab_confirm_button_calls_confirm_review_candidate(qtbot):
    candidates = [(_make_track(track_id="t7"), _make_review_candidate(track_id="t7"))]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_needs_review_candidates(candidates)

    actions = window.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Confirm"].click()

    qtbot.waitUntil(
        lambda: application.download_service.confirm_review_candidate_calls == ["t7"],
        timeout=2000,
    )
    assert application.download_service.reject_review_candidate_calls == []


def test_review_tab_reject_button_calls_reject_review_candidate(qtbot):
    candidates = [(_make_track(track_id="t9"), _make_review_candidate(track_id="t9"))]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_needs_review_candidates(candidates)

    actions = window.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Reject"].click()

    qtbot.waitUntil(
        lambda: application.download_service.reject_review_candidate_calls == ["t9"],
        timeout=2000,
    )
    assert application.download_service.confirm_review_candidate_calls == []


def test_review_tab_renders_pending_upgrades_with_delete_checkbox_when_old_file_exists(
        qtbot,
):
    details = [_make_upgrade_details(old_file_path="/music/old.mp3")]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    assert window.review_upgrades_table.rowCount() == 1
    assert window.review_upgrades_table.item(0, 1).text() == "mp3"
    assert window.review_upgrades_table.item(0, 2).text() == "flac 1000kbps"

    actions = window.review_upgrades_table.cellWidget(0, 3)
    assert len(actions.findChildren(QCheckBox)) == 1
    buttons = {b.text() for b in actions.findChildren(QPushButton)}
    assert buttons == {"Replace", "Decline"}


def test_review_tab_renders_pending_upgrades_without_delete_checkbox_when_no_old_file(
        qtbot,
):
    # Mirrors the CLI's own guard around its second input() prompt —
    # there's nothing to offer deleting when there's no current file.
    details = [_make_upgrade_details(old_file_path=None)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    assert actions.findChildren(QCheckBox) == []


def test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag(
        qtbot,
):
    details = [_make_upgrade_details(request_id=42, old_file_path="/music/old.mp3")]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    checkbox = actions.findChildren(QCheckBox)[0]
    checkbox.setChecked(True)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Replace"].click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decision_calls
        == [(42, True, True)],
        timeout=2000,
    )
    assert window.status_label.text() == "Replaced with /new/path"


def test_review_tab_decline_button_calls_apply_upgrade_decision_with_replace_false(
        qtbot,
):
    details = [_make_upgrade_details(request_id=99)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Decline"].click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decision_calls
        == [(99, False, False)],
        timeout=2000,
    )
    # A decline returns None from apply_upgrade_decision — no status
    # message should be surfaced, unlike a real replace.
    assert window.status_label.text() == ""


def test_review_tab_populates_both_sections_on_construction(qtbot):
    # _poll_review_items() runs once in __init__ (like the Downloads
    # tab's own initial call) so the Review tab isn't empty for the
    # first poll interval either.
    candidates = [(_make_track(track_id="tc"), _make_review_candidate(track_id="tc"))]
    upgrades = [_make_upgrade_details(request_id=5)]
    application = FakeApplication(
        review_candidates=candidates, pending_upgrades=upgrades,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.review_needs_table.rowCount() == 1, timeout=2000,
    )
    assert window.review_upgrades_table.rowCount() == 1


def _make_track_status(track_id: str = "t1", state: str = IN_LIBRARY) -> TrackStatus:
    return TrackStatus(track=_make_track(track_id), state=state)


def test_tag_button_appears_only_for_in_library_tracks(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY),
        _make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    in_library_actions = window.track_table.cellWidget(0, 3)
    assert [b.text() for b in in_library_actions.findChildren(QPushButton)] == ["Tag"]

    not_found_actions = window.track_table.cellWidget(1, 3)
    assert not_found_actions.findChildren(QPushButton) == []


def test_tag_track_button_calls_tag_tracks_with_correct_args(qtbot):
    statuses = [_make_track_status(track_id="t7", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    actions = window.track_table.cellWidget(0, 3)
    tag_button = actions.findChildren(QPushButton)[0]
    tag_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t7"], False, None),
    ]


def test_bpm_range_fields_hidden_until_analyze_audio_checked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    # isVisible() reflects actual on-screen visibility, which requires
    # a shown top-level window — isHidden() reflects the widget's own
    # explicit hide/show state regardless of ancestor visibility, which
    # is what this test actually cares about, so window.show() isn't
    # needed here.
    assert window.bpm_min_edit.isHidden()
    assert window.bpm_max_edit.isHidden()

    window.analyze_audio_checkbox.setChecked(True)

    assert not window.bpm_min_edit.isHidden()
    assert not window.bpm_max_edit.isHidden()

    window.analyze_audio_checkbox.setChecked(False)

    assert window.bpm_min_edit.isHidden()
    assert window.bpm_max_edit.isHidden()


def test_tag_track_with_analyze_audio_and_bpm_range_passes_options(qtbot):
    statuses = [_make_track_status(track_id="t9", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    window.analyze_audio_checkbox.setChecked(True)
    window.bpm_min_edit.setText("160")
    window.bpm_max_edit.setText("180")

    actions = window.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t9"], True, (160.0, 180.0)),
    ]


def test_bpm_range_partial_input_blocks_the_call_with_an_error(qtbot):
    statuses = [_make_track_status(track_id="t3", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    window.analyze_audio_checkbox.setChecked(True)
    window.bpm_min_edit.setText("160")
    # bpm_max_edit deliberately left blank.

    actions = window.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "both" in window.status_label.text().lower()


def test_tag_selected_calls_tag_tracks_with_selected_ids(qtbot):
    statuses = [
        _make_track_status(track_id="s1", state=IN_LIBRARY),
        _make_track_status(track_id="s2", state=IN_LIBRARY),
        _make_track_status(track_id="s3", state=IN_LIBRARY),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    # Select rows 0 and 2 additively through the selection model itself
    # (QItemSelectionModel.Select | .Rows) — selectRow() replaces the
    # existing selection instead of adding to it, which isn't what a
    # real ctrl/shift-click multi-select produces.
    selection_model = window.track_table.selectionModel()
    for row in (0, 2):
        selection_model.select(
            window.track_table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    window.tag_selected_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    track_ids, analyze_audio, bpm_range = application.metadata_service.tag_tracks_calls[0]
    assert set(track_ids) == {"s1", "s3"}
    assert analyze_audio is False
    assert bpm_range is None


def test_tag_selected_with_no_selection_shows_message_and_makes_no_call(qtbot):
    statuses = [_make_track_status(track_id="s1", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    window.tag_selected_button.click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "select" in window.status_label.text().lower()


def test_tag_playlist_calls_tag_playlist_with_playlist_name(qtbot):
    playlists = [Playlist(id="p1", name="240KM/H", track_count=5)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)

    window.tag_playlist_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_playlist_calls == [
        ("240KM/H", False, None),
    ]


def test_tag_playlist_without_selection_shows_message_and_makes_no_call(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.tag_playlist_button.click()

    assert application.metadata_service.tag_playlist_calls == []
    assert "playlist" in window.status_label.text().lower()


def test_results_panel_renders_breakdown_and_per_item_reasons(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = {
        "tagged": 2,
        "skipped_no_match": 1,
        "skipped_format_unsupported": 1,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 1,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_no_match",
                "message": "Artist A - Title A: no matched local file",
            },
            {
                "track_id": "t2",
                "reason": "failed",
                "message": "Artist B - Title B: disk read error",
            },
        ],
    }

    window._render_tag_result(result)

    text = window.tagging_results.toPlainText()
    assert "Tagged: 2" in text
    assert "Failed: 1" in text
    assert "[skipped_no_match] Artist A - Title A: no matched local file" in text
    assert "[failed] Artist B - Title B: disk read error" in text


# --- Duplicates tab (roadmap item 5) ---------------------------------------
#
# Locations load lazily, only once the tab is actually shown (see
# main_window.py's own comment on _on_tab_changed for why — an eager
# worker here, run during every MainWindow construction, was confirmed
# live to cause a real, reproducible deadlock under this test suite's
# own rapid-fire construction pattern). Tests below drive that
# explicitly rather than relying on construction alone.

def _switch_to_duplicates_tab(window) -> None:
    tabs = window.centralWidget()
    tabs.setCurrentIndex(window._duplicates_tab_index)


def test_duplicates_tab_has_persistent_subtitle(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    tabs = window.centralWidget()
    duplicates_tab = tabs.widget(window._duplicates_tab_index)
    labels = [w.text() for w in duplicates_tab.findChildren(QLabel)]

    assert help_text.DUPLICATES_TAB_SUBTITLE in labels


def test_duplicates_tab_controls_have_tooltips(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.duplicates_location_combo.toolTip() != ""
    assert window.compute_fingerprints_button.toolTip() != ""
    assert window.find_duplicates_button.toolTip() != ""


def test_switching_to_duplicates_tab_loads_locations_lazily(qtbot):
    location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.duplicates_location_combo.count() == 0

    _switch_to_duplicates_tab(window)

    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 1, timeout=2000,
    )
    assert window.duplicates_location_combo.itemText(0) == "Main"


def test_switching_to_duplicates_tab_twice_loads_locations_once(qtbot):
    # Deliberately does NOT drive a second real tab-switch/worker round
    # trip — see main_window.py's own _on_tab_changed comment: spawning
    # overlapping run_worker() calls in tight succession was confirmed
    # live to risk a real Qt-connection-mutex/GIL deadlock under this
    # suite's own rapid MainWindow churn (CLAUDE.md/docs/HISTORY.md).
    # The "loaded once" guard is a plain if-check on
    # _duplicates_locations_loaded, so it's verified directly, the same
    # way a pure function would be, without needing a second live
    # worker to prove it.
    location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_tab_changed(window._duplicates_tab_index)
    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 1, timeout=2000,
    )

    assert window._duplicates_locations_loaded is True

    # A second call must be a pure no-op — checked by asserting the
    # combo's contents are untouched, not by spawning another worker.
    window.duplicates_location_combo.clear()
    window._on_tab_changed(window._duplicates_tab_index)

    assert window.duplicates_location_combo.count() == 0


def test_compute_fingerprints_without_selection_shows_message(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_compute_fingerprints_clicked()

    assert "Select a library location" in window.duplicates_status_label.text()
    assert application.duplicate_service.compute_fingerprints_calls == []


def test_compute_fingerprints_calls_service_with_selected_location(qtbot):
    application = FakeApplication(
        fingerprint_result={
            "computed": 3, "skipped_already_computed": 1, "failed": 0,
            "details": [],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: application.duplicate_service.compute_fingerprints_calls == ["Main"],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: "Fingerprinted: 3" in window.duplicates_status_label.text(),
        timeout=2000,
    )


def test_find_duplicates_without_selection_shows_message(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_find_duplicates_clicked()

    assert "Select a library location" in window.duplicates_status_label.text()
    assert application.duplicate_service.find_duplicate_groups_calls == []


def test_find_duplicates_renders_no_duplicates_message(qtbot):
    application = FakeApplication(duplicate_groups=[])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._on_find_duplicates_clicked()

    qtbot.waitUntil(
        lambda: "No duplicates found" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    assert window.duplicates_table.rowCount() == 0


def _make_duplicate_group():
    from seeker.library.duplicate_service import DuplicateFile, DuplicateGroup
    from seeker.soulseek.quality import LocalFileQuality

    return DuplicateGroup(
        files=[
            DuplicateFile(
                local_file=LocalFile(
                    id=101,
                    location_id=1, relative_path="a.flac", filename="a.flac",
                    format="flac", size_bytes=1, mtime=0.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                ),
                quality=LocalFileQuality(
                    tier=2, bitrate_kbps=1000, bit_depth=16,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=None,
                ),
            ),
            DuplicateFile(
                local_file=LocalFile(
                    id=102,
                    location_id=1, relative_path="a.mp3", filename="a.mp3",
                    format="mp3", size_bytes=1, mtime=0.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                ),
                quality=LocalFileQuality(
                    tier=1, bitrate_kbps=320, bit_depth=None,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=None,
                ),
            ),
        ],
        similarity=0.987,
    )


def test_render_duplicate_groups_populates_table(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    assert window.duplicates_table.rowCount() == 2
    assert window.duplicates_table.item(0, 1).text() == "a.flac"
    assert window.duplicates_table.item(1, 1).text() == "a.mp3"
    assert window.duplicates_table.item(0, 4).text() == "98.7%"


def test_render_duplicate_groups_preselects_the_best_quality_file_to_keep(
        qtbot,
):
    # group.files is already best-quality-first (a.flac, tier 2, over
    # a.mp3, tier 1) -- the radio on row 0 must be pre-checked, row 1
    # must not be, and neither is auto-applied without a later click.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    keep_radio_0 = window.duplicates_table.cellWidget(0, 5)
    keep_radio_1 = window.duplicates_table.cellWidget(1, 5)
    assert isinstance(keep_radio_0, QRadioButton)
    assert isinstance(keep_radio_1, QRadioButton)
    assert keep_radio_0.isChecked() is True
    assert keep_radio_1.isChecked() is False


def test_render_duplicate_groups_actions_only_on_group_first_row(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    first_row_actions = window.duplicates_table.cellWidget(0, 6)
    other_row_actions = window.duplicates_table.cellWidget(1, 6)
    assert first_row_actions.findChildren(QPushButton)
    assert not other_row_actions.findChildren(QPushButton)


def test_delete_duplicates_without_confirm_checkbox_does_not_delete(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 6)
    delete_button = actions.findChildren(QPushButton)[0]
    delete_button.click()

    assert application.duplicate_service.delete_local_files_calls == []
    assert "Confirm delete" in window.duplicates_status_label.text()


def test_delete_duplicates_with_confirm_checkbox_deletes_non_kept_files(
        qtbot,
):
    # a.flac (id 101) is pre-selected to keep (best quality) -- clicking
    # Delete with the checkbox checked must delete only a.mp3 (id 102).
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service.delete_local_files_calls = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 6)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    assert application.duplicate_service.delete_local_files_calls == [([102], 101)]


def test_delete_duplicates_respects_a_changed_keep_selection(qtbot):
    # Moving the radio to a.mp3 (id 102) before deleting must delete
    # a.flac (id 101) instead of the pre-selected default.
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    window.duplicates_table.cellWidget(1, 5).setChecked(True)

    actions = window.duplicates_table.cellWidget(0, 6)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    assert application.duplicate_service.delete_local_files_calls == [([101], 102)]


def test_delete_duplicates_finished_removes_group_locally_without_refetch(
        qtbot,
):
    # Deliberately NOT a find_duplicate_groups() re-fetch after a
    # single-group resolution -- that call recomputes an entire
    # location's clustering from scratch every time, confirmed live to
    # cost ~10 real minutes over a real ~3,100-file/344-group library
    # (docs/HISTORY.md item 39). Resolving groups one at a time must
    # drop each one from the in-memory list this tab already holds
    # instead, with zero additional service calls.
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service._delete_result = {
        "deleted": 1, "failed": 0, "details": [],
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 6)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: "Deleted: 1, Failed: 0" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    assert application.duplicate_service.find_duplicate_groups_calls == []
    assert window.duplicates_table.rowCount() == 0
    assert window._current_duplicate_groups == []


def test_delete_duplicates_partial_failure_keeps_group_visible(qtbot):
    # A partial failure means the group's real DB/disk state may not
    # actually match "fully resolved" -- it must stay visible rather
    # than being dropped as if it were.
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service._delete_result = {
        "deleted": 0, "failed": 1, "details": [],
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 6)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: "Deleted: 0, Failed: 1" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    assert window.duplicates_table.rowCount() == 2
    assert len(window._current_duplicate_groups) == 1

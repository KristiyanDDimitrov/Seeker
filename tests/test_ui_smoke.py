import threading

from PySide6.QtWidgets import QProgressBar, QPushButton

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.ui.main_window import MainWindow
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
    def scan_all(self) -> None:
        pass


class FakeTrackMatcher:
    def match_all(self) -> dict:
        return {"auto": 0, "needs_review": 0, "unmatched": 0}


class FakeDownloadService:
    def download_playlist(self, playlist_name: str) -> dict:
        return {"requested": 0, "skipped": 0, "failed": 0, "total": 0}

    def poll_downloads(self) -> dict:
        return {}


class FakeApplication:
    def __init__(
            self,
            playlists: list[Playlist] | None = None,
            statuses: list | None = None,
            active_downloads: list | None = None,
            soulseek_configured: bool = False,
    ):
        self.sync_service = FakeSyncService(playlists)
        self.dashboard_service = FakeDashboardService(
            statuses, active_downloads,
        )
        self.library_service = FakeLibraryService()
        self.track_matcher = FakeTrackMatcher()
        self.download_service = FakeDownloadService()
        self.soulseek_configured = soulseek_configured


def test_main_window_constructs_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.windowTitle() == "Seeker"


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
    worker = Worker(lambda: 42)
    results = []
    worker.signals.finished.connect(results.append)

    worker.run()

    assert results == [42]


def test_worker_emits_error_on_exception():
    def boom():
        raise RuntimeError("simulated failure")

    worker = Worker(boom)
    errors = []
    worker.signals.error.connect(errors.append)

    worker.run()

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
    # The whole point of _active_workers (see workers.py's own comment)
    # is to hold a strong reference until a worker is genuinely done —
    # if cleanup only fired on the success path, a worker that raises
    # would stay referenced forever, a real leak on every failed
    # sync/scan/match/download. Asserted directly against the registry
    # itself, not just inferred from button/label side effects.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._active_workers)

    run_worker(SynchronousPool(), lambda: "ok")
    assert len(workers_module._active_workers) == baseline

    def boom():
        raise RuntimeError("simulated failure")

    run_worker(SynchronousPool(), boom)
    assert len(workers_module._active_workers) == baseline


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
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    bar = window.downloads_table.cellWidget(0, 4)
    assert isinstance(bar, QProgressBar)
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

    qtbot.waitUntil(lambda: "thread" in recorded, timeout=2000)

    assert recorded["thread"] != threading.main_thread()


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

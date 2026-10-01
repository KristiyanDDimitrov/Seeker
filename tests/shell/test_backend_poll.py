"""The backend poll: `poll_downloads` off the main thread, its
overlap guard, and the Dashboard refresh it triggers.
"""
import threading

from fakes import (
    FakeApplication,
    FakeDashboardService,
)
from seeker.models.download_result import (
    PollResult,
)
from seeker.models.playlist import Playlist
from seeker.ui.main_window import (
    MainWindow,
)


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

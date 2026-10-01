"""Quitting: cleanup_before_quit, and the confirmation shown when a
download is still running.
"""
import logging

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QMessageBox,
)

from fakes import (
    FakeApplication,
    force_tray_available,
)
from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.track import Track
from seeker.ui.main_window import (
    MainWindow,
)


def test_cleanup_before_quit_stops_timers_and_hides_tray(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    assert window.poll_timer.isActive()
    assert window.backend_poll_timer.isActive()

    window.cleanup_before_quit()

    assert not window.poll_timer.isActive()
    assert not window.backend_poll_timer.isActive()


def test_cleanup_before_quit_logs_thread_pool_state_and_duration(
        qtbot, monkeypatch, caplog,
):
    # Round 9 §2.3 — instrumentation added for the unreproduced "not
    # responding" quit hang. A real recurrence needs these two lines in
    # seeker.log to localize the hang: both present quickly points away
    # from this method's own body (see its own comment for why).
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    with caplog.at_level(logging.INFO, logger="seeker.ui.window_lifecycle"):
        window.cleanup_before_quit()

    # Deliberately not asserting an exact active-thread count: a
    # freshly-constructed window can have its own real initial-load
    # worker still in flight on `window.thread_pool`, so 0 isn't
    # guaranteed even here — only the log shape itself is the contract.
    assert "cleanup_before_quit: starting, thread_pool active=" in (
        caplog.text
    )
    assert " max=" in caplog.text
    assert "cleanup_before_quit: finished in " in caplog.text


# --- Quit-while-downloading confirmation (round 9 §2.2, HISTORY §123) ------

def _active_download(status: str) -> ActiveDownload:
    return ActiveDownload(
        request=DownloadRequest(
            track_id="t1", username="peer", filename="file.flac",
            format="flac", requested_at="2026-01-01T00:00:00+00:00",
            status=status,
        ),
        track=Track(
            id="t1", title="Song", artist="Artist", album="Album",
            duration_ms=200_000,
        ),
        playlist_name="My Playlist",
    )


def test_quit_confirmation_skipped_when_nothing_downloading(qtbot, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", shown.append)
    application = FakeApplication(active_downloads=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._lifecycle.confirm_quit_if_downloads_active() is True
    assert shown == []


def test_quit_confirmation_skipped_for_non_downloading_statuses(
        qtbot, monkeypatch,
):
    # Mirrors downloads_page.active_downloads_count's own definition of
    # "in progress" exactly (status == "downloading") — a queued or
    # already-completed row must not trigger the dialog.
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", shown.append)
    application = FakeApplication(
        active_downloads=[
            _active_download("queued"), _active_download("completed"),
        ],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._lifecycle.confirm_quit_if_downloads_active() is True
    assert shown == []


def test_quit_confirmation_shown_with_real_count_and_no_word_lose(
        qtbot, monkeypatch,
):
    shown: list[QMessageBox] = []

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    application = FakeApplication(
        active_downloads=[
            _active_download("downloading"), _active_download("downloading"),
        ],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._lifecycle.confirm_quit_if_downloads_active()

    assert len(shown) == 1
    box = shown[0]
    assert "2" in box.text()
    assert "lose" not in box.text().lower()
    assert "lose" not in box.informativeText().lower()
    button_labels = {button.text() for button in box.buttons()}
    assert "Quit Anyway" in button_labels
    assert "Keep Seeker Open" in button_labels
    # The safe choice is the default — an Enter/Return keypress must
    # never quit out from under an in-progress download.
    assert box.defaultButton().text() == "Keep Seeker Open"


def test_quit_confirmation_quit_anyway_allows_the_quit(qtbot, monkeypatch):
    def fake_exec(self):
        return None

    def fake_clicked_button(self):
        for button in self.buttons():
            if button.text() == "Quit Anyway":
                return button
        return None

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked_button)
    application = FakeApplication(
        active_downloads=[_active_download("downloading")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._lifecycle.confirm_quit_if_downloads_active() is True


def test_quit_confirmation_keep_open_cancels_the_quit(qtbot, monkeypatch):
    def fake_exec(self):
        return None

    def fake_clicked_button(self):
        for button in self.buttons():
            if button.text() == "Keep Seeker Open":
                return button
        return None

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked_button)
    application = FakeApplication(
        active_downloads=[_active_download("downloading")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._lifecycle.confirm_quit_if_downloads_active() is False


def test_event_filter_ignores_events_other_than_app_quit(qtbot):
    from PySide6.QtWidgets import QApplication

    # The filter must not swallow ordinary events for whatever else the
    # QApplication instance happens to be watched by/dispatch to.
    application = FakeApplication(
        active_downloads=[_active_download("downloading")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    event = QEvent(QEvent.Type.ApplicationStateChange)
    assert window.eventFilter(QApplication.instance(), event) is False


def test_event_filter_consumes_quit_event_when_declined(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: None)
    application = FakeApplication(
        active_downloads=[_active_download("downloading")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    event = QEvent(QEvent.Type.Quit)
    # True = consumed = the quit is cancelled.
    assert window.eventFilter(QApplication.instance(), event) is True


def test_event_filter_lets_quit_event_through_when_nothing_downloading(
        qtbot,
):
    from PySide6.QtWidgets import QApplication

    application = FakeApplication(active_downloads=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    event = QEvent(QEvent.Type.Quit)
    # False = not consumed = the real quit proceeds to aboutToQuit.
    assert window.eventFilter(QApplication.instance(), event) is False

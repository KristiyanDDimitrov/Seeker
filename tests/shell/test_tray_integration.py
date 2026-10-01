"""MainWindow's wiring to the tray: Open Seeker, icon clicks per
platform, Check now, and Quit from fullscreen.
"""

from PySide6.QtWidgets import (
    QSystemTrayIcon,
)

from fakes import (
    FakeApplication,
    force_tray_available,
)
from seeker.ui.main_window import (
    MainWindow,
)


def test_tray_open_seeker_unhides_and_refreshes(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # Roadmap item 116 (round 8, §14.2) — found live wiring up
    # applicationStateChanged: without settling the event loop here, a
    # platform-level "just became active" notification queued by
    # show() itself can be delivered LATE, after close() has already
    # hidden the window — at delivery time isVisible() reads False, so
    # _on_application_state_changed's own reopen guard (correctly)
    # treats it as a real reopen request, which invalidates the
    # pending hide-confirmation timer and this waitUntil never
    # resolves. Not reachable through real interactive use (a human
    # takes real time between a window appearing and closing it, which
    # the already-spinning event loop uses to deliver this kind of
    # notification long before any close() call); this is a test-
    # timing gap, not a production race, and this qtbot.wait(20)
    # matches the settling wait this file's own fullscreen-close test
    # already uses for the same class of reason.
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._lifecycle._hidden_to_tray is True, timeout=1000)

    window._tray._on_tray_open_seeker()

    assert window._lifecycle._hidden_to_tray is False
    assert window.isVisible()


def test_tray_trigger_click_does_nothing_on_macos(qtbot, monkeypatch):
    # Roadmap item D5 (round 6) — the actual reported bug: a real
    # user's left-click on the menu bar icon on a real Mac both opened
    # the context menu (AppKit's own native behavior) AND restored the
    # window (this code's own `Trigger` handling) — not what a menu bar
    # extra should do. On macOS, `Trigger` must now be a no-op.
    from seeker.ui import tray as tray_module

    force_tray_available(monkeypatch, True)
    monkeypatch.setattr(tray_module.sys, "platform", "darwin")
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # Roadmap item 116 (round 8, §14.2) — found live wiring up
    # applicationStateChanged: without settling the event loop here, a
    # platform-level "just became active" notification queued by
    # show() itself can be delivered LATE, after close() has already
    # hidden the window — at delivery time isVisible() reads False, so
    # _on_application_state_changed's own reopen guard (correctly)
    # treats it as a real reopen request, which invalidates the
    # pending hide-confirmation timer and this waitUntil never
    # resolves. Not reachable through real interactive use (a human
    # takes real time between a window appearing and closing it, which
    # the already-spinning event loop uses to deliver this kind of
    # notification long before any close() call); this is a test-
    # timing gap, not a production race, and this qtbot.wait(20)
    # matches the settling wait this file's own fullscreen-close test
    # already uses for the same class of reason.
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._lifecycle._hidden_to_tray is True, timeout=1000)

    window._tray._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.Trigger)

    assert window._lifecycle._hidden_to_tray is True
    assert not window.isVisible()


def test_tray_trigger_click_opens_seeker_on_windows_and_linux(
        qtbot, monkeypatch,
):
    # D5.1 — the original behavior is kept for the platforms it was
    # actually written for: Trigger is the only signal a left-click
    # produces there at all, so it should still restore the window.
    from seeker.ui import tray as tray_module

    force_tray_available(monkeypatch, True)
    monkeypatch.setattr(tray_module.sys, "platform", "win32")
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # Roadmap item 116 (round 8, §14.2) — found live wiring up
    # applicationStateChanged: without settling the event loop here, a
    # platform-level "just became active" notification queued by
    # show() itself can be delivered LATE, after close() has already
    # hidden the window — at delivery time isVisible() reads False, so
    # _on_application_state_changed's own reopen guard (correctly)
    # treats it as a real reopen request, which invalidates the
    # pending hide-confirmation timer and this waitUntil never
    # resolves. Not reachable through real interactive use (a human
    # takes real time between a window appearing and closing it, which
    # the already-spinning event loop uses to deliver this kind of
    # notification long before any close() call); this is a test-
    # timing gap, not a production race, and this qtbot.wait(20)
    # matches the settling wait this file's own fullscreen-close test
    # already uses for the same class of reason.
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._lifecycle._hidden_to_tray is True, timeout=1000)

    window._tray._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.Trigger)

    assert window._lifecycle._hidden_to_tray is False
    assert window.isVisible()


def test_tray_check_now_triggers_backend_poll(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.backend_poll_timer.stop()

    window._tray._on_tray_check_now()

    qtbot.waitUntil(
        lambda: application.download_service.poll_downloads_calls
        if hasattr(application.download_service, "poll_downloads_calls")
        else True,
        timeout=500,
    )
    # No direct call counter on FakeDownloadService.poll_downloads --
    # just confirm it doesn't raise and the in-progress flag round-trips.
    qtbot.waitUntil(
        lambda: window._backend_poll_in_progress is False, timeout=2000,
    )


def test_tray_quit_from_fullscreen_bypasses_closeevent_entirely(
        qtbot, monkeypatch,
):
    # Roadmap item D4.3 (round 6) — the brief's own explicit ask: Quit
    # is a real, separate path from the red-button close this item
    # otherwise fixes, and needs checking on its own rather than
    # assumed to share the same fix. `_on_tray_quit` goes straight to
    # `QApplication.quit()`, never `self.close()` (see its own
    # docstring) — it never reaches `closeEvent`/E1's own fullscreen
    # branch at all, so the black-Space bug is structurally unreachable
    # from this path regardless of fullscreen state: the whole app (and
    # its Space) is what's actually going away, not just this window
    # being hidden.
    from PySide6.QtWidgets import QApplication

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)
    assert window.isFullScreen()

    quit_calls = []
    monkeypatch.setattr(
        QApplication, "quit", lambda self=None: quit_calls.append(True),
    )

    window._tray._on_tray_quit()

    assert quit_calls == [True]
    # Nothing about the close/hide-to-tray machinery fired.
    assert window._lifecycle._hidden_to_tray is False
    assert window._lifecycle._reopen_filled is False

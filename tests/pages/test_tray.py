"""Tests for the tray/notification group (seeker.ui.tray). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.7) — the
mirror of §9.3.2's own tray extraction (S11).

closeEvent and the hide-to-tray verification (round 7's E1) stay in
test_ui_smoke.py, per tray.py's own module docstring — that logic is
about the *window*, not the tray. So do the tests that exercise it,
even where they trigger a TrayController action along the way
(_on_tray_open_seeker, _on_tray_icon_activated, _on_tray_check_now,
_on_tray_quit from a fullscreen state, _on_application_state_changed,
cleanup_before_quit): each of those asserts on MainWindow's own
_hidden_to_tray/isVisible/_pre_fullscreen_geometry/_app_state_connected/
poll-timer state, not on anything TrayController owns, so they belong
with the window-side machinery they are actually verifying.
"""

from dataclasses import replace

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.ui.main_window import MainWindow
from seeker.ui.tray import _resolve_tray_icon_path
from test_ui_smoke import (
    FakeApplication,
    _force_tray_available,
    _make_history_event,
    _make_review_candidate,
    _make_track,
    _make_upgrade_details,
)


def test_tray_icon_not_built_when_unavailable(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._tray._tray_icon is None


def test_tray_pause_action_reflects_and_persists_config(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._tray._tray_pause_action.isChecked() is False

    window._tray._tray_pause_action.setChecked(True)

    assert application.set_downloads_paused_calls == [True]
    assert application.downloads_paused is True


def test_tray_menu_status_shows_idle_with_nothing_active(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([])
    window._tray._render_tray_menu()

    assert window._tray._tray_status_action.text() == "Idle"


def test_tray_menu_status_shows_downloading_count(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    downloads = [
        ActiveDownload(
            track=_make_track("t1"),
            request=DownloadRequest(
                track_id="t1", username="peer1", filename="a.flac",
                format="flac", quality_descriptor="flac", role="settled",
                status="downloading", requested_at="2026-01-01",
            ),
            playlist_name="Test",
        ),
    ]
    window._downloads_page._render_active_downloads(downloads)
    window._tray._render_tray_menu()

    assert window._tray._tray_status_action.text() == "1 downloading"


def test_tray_menu_status_shows_paused_suffix(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, downloads_paused=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._tray._render_tray_menu()

    assert "(paused)" in window._tray._tray_status_action.text()


def test_tray_menu_review_and_upgrades_counts_are_distinct(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_review_items((
        [(_make_track(), _make_review_candidate())],
        [_make_upgrade_details(), _make_upgrade_details(request_id=2)],
        [],
    ))
    window._tray._render_tray_menu()

    assert window._tray._tray_review_action.text() == "Review (1)"
    assert window._tray._tray_upgrades_action.text() == "Upgrades (2)"


def test_tray_check_now_action_is_named_unambiguously(qtbot, monkeypatch):
    # Roadmap item 98 (B9.5) — "Check now" was ambiguous with the Help
    # menu's own "Check for updates…" (a completely different action).
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu = window._tray._tray_icon.contextMenu()
    actions_by_text = {action.text(): action for action in menu.actions()}

    assert "Check now" not in actions_by_text
    assert "Check downloads now" in actions_by_text
    assert actions_by_text["Check downloads now"].toolTip() != ""


def test_tray_quit_calls_qapplication_quit(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    quit_calls = []
    monkeypatch.setattr(
            QApplication, "quit", lambda self=None: quit_calls.append(True)
    )

    window._tray._on_tray_quit()

    assert quit_calls == [True]


def test_needs_decision_notification_fires_only_on_increase(
        qtbot,
        monkeypatch,
):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._tray.check_for_needs_decision_notification(3)
    assert len(messages) == 1
    assert "3 item" in messages[0]

    # Same count again -- no repeat notification.
    window._tray.check_for_needs_decision_notification(3)
    assert len(messages) == 1

    # A genuine increase -- notifies again.
    window._tray.check_for_needs_decision_notification(5)
    assert len(messages) == 2

    # A decrease resets the baseline silently.
    window._tray.check_for_needs_decision_notification(1)
    assert len(messages) == 2


def test_needs_decision_notification_respects_config_toggle(
        qtbot,
        monkeypatch,
):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, notify_needs_decision=False,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._tray.check_for_needs_decision_notification(3)

    assert messages == []


def test_error_notification_is_rate_limited(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._tray.notify_error("slskd unreachable")
    window._tray.notify_error("slskd unreachable")

    assert len(messages) == 1


def test_error_notification_respects_config_toggle(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, notify_errors=False,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._tray.notify_error("slskd unreachable")

    assert messages == []


def test_download_notifications_batch_per_playlist(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    # Seeding (construction-time) found nothing -- simulate the cutoff
    # already being set, as it would be after a real seed with no
    # existing history.
    window._tray._last_notified_download_at = "2026-01-01T00:00:00+00:00"

    messages = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    events = [
        _make_history_event(
            occurred_at="2026-01-02T00:00:02+00:00", playlist_name="A",
        ),
        _make_history_event(
            occurred_at="2026-01-02T00:00:01+00:00", playlist_name="A",
        ),
        _make_history_event(
            occurred_at="2026-01-02T00:00:00+00:00", playlist_name="B",
        ),
    ]
    window._tray._on_download_notification_events(events)

    assert len(messages) == 1
    assert "A: 2 tracks downloaded" in messages[0]
    assert "B: 1 track downloaded" in messages[0]
    assert window._tray._last_notified_download_at == "2026-01-02T00:00:02+00:00"


def test_download_notifications_skip_events_before_cutoff(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._tray._last_notified_download_at = "2026-01-02T00:00:00+00:00"

    messages = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    # Every event is at or before the cutoff -- nothing new.
    events = [_make_history_event(occurred_at="2026-01-02T00:00:00+00:00")]
    window._tray._on_download_notification_events(events)

    assert messages == []


def test_resolve_tray_icon_path_dev_mode_points_at_real_repo_file():
    # Roadmap item 98 (B9.1) — the real template asset, not the
    # full-colour app .icns (setIsMask(True) against the .icns produced
    # a solid filled squircle instead of a legible glyph).
    import sys

    assert not getattr(sys, "frozen", False)
    path = _resolve_tray_icon_path()

    assert path.name == "seeker_menubar_Template.png"
    assert path.exists()


def test_resolve_tray_icon_path_frozen_mode_uses_meipass(
        monkeypatch,
        tmp_path,
):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    path = _resolve_tray_icon_path()

    assert path == tmp_path / "icons" / "seeker_menubar_Template.png"

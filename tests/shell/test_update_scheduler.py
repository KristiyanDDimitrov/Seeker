"""The automatic update check: once, at startup, when turned on and a
day has passed; an available update gets a tray notice and a Help menu
entry, every other answer stays silent.
"""
import logging
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QMenu, QMessageBox

from fakes import FakeApplication, force_tray_available
from seeker.ui.main_window import MainWindow
from seeker.update_check import UpdateCheckResult, UpdateStatus

AVAILABLE = UpdateCheckResult(
    UpdateStatus.UPDATE_AVAILABLE,
    latest_version="0.2.0",
    release_url="https://github.com/KristiyanDDimitrov/Seeker/releases/tag/0.2.0",
    installed_version="0.1.0",
)


def _patch_check(monkeypatch, result):
    calls: list[str] = []

    def check():
        calls.append(threading.current_thread().name)
        return result

    monkeypatch.setattr("seeker.ui.update_scheduler.check_for_update", check)
    return calls


def _window(qtbot, *, enabled=True, last_update_check_at=None):
    application = FakeApplication()
    application._config_store = replace(
        application._config_store,
        auto_update_check=enabled,
        last_update_check_at=last_update_check_at,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    return window, application


def _tray_messages(monkeypatch, window):
    messages: list[str] = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, message, *a, **k: messages.append(message),
    )
    return messages


def _wait_for_the_logged_outcome(qtbot, caplog):
    qtbot.waitUntil(
        lambda: "Automatic update check:" in caplog.text, timeout=2000,
    )


def test_a_due_check_runs_after_construction_off_the_ui_thread(
        qtbot, monkeypatch, caplog,
):
    calls = _patch_check(monkeypatch, AVAILABLE)
    caplog.set_level(logging.INFO, logger="seeker.ui.update_scheduler")

    window, _ = _window(qtbot)
    assert calls == []

    qtbot.waitUntil(window.update_available_action.isVisible, timeout=2000)
    assert len(calls) == 1
    assert calls[0] != threading.main_thread().name


def test_a_started_check_is_stamped_whatever_it_returns(
        qtbot, monkeypatch, caplog,
):
    _patch_check(monkeypatch, UpdateCheckResult(
        UpdateStatus.UNAVAILABLE, reason="Timed out reaching GitHub.",
    ))
    caplog.set_level(logging.INFO, logger="seeker.ui.update_scheduler")
    before = datetime.now(UTC)

    _, application = _window(qtbot)
    _wait_for_the_logged_outcome(qtbot, caplog)

    stamped = datetime.fromisoformat(
        application.settings.last_update_check_at
    )
    assert before <= stamped <= datetime.now(UTC)


@pytest.mark.parametrize(("enabled", "hours_ago"), [
    (False, None),
    (False, 48),
    (True, 23),
])
def test_no_check_when_off_or_checked_within_a_day(
        qtbot, monkeypatch, enabled, hours_ago,
):
    calls = _patch_check(monkeypatch, AVAILABLE)
    last = (
        None if hours_ago is None
        else (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    )

    window, application = _window(
        qtbot, enabled=enabled, last_update_check_at=last,
    )
    qtbot.wait(50)
    assert window.thread_pool.waitForDone(2000)

    assert calls == []
    assert application.settings.last_update_check_at == last
    assert application.update_settings_calls == []


def test_a_check_a_day_after_the_last_one_runs(qtbot, monkeypatch):
    calls = _patch_check(monkeypatch, AVAILABLE)
    last = (datetime.now(UTC) - timedelta(hours=25)).isoformat()

    window, _ = _window(qtbot, last_update_check_at=last)

    qtbot.waitUntil(window.update_available_action.isVisible, timeout=2000)
    assert len(calls) == 1


def test_an_available_update_sends_one_notice_and_shows_in_help(
        qtbot, monkeypatch, caplog,
):
    force_tray_available(monkeypatch, True)
    _patch_check(monkeypatch, AVAILABLE)
    caplog.set_level(logging.INFO, logger="seeker.ui.update_scheduler")
    window, _ = _window(qtbot)
    messages = _tray_messages(monkeypatch, window)

    _wait_for_the_logged_outcome(qtbot, caplog)

    assert messages == [
        "Seeker 0.2.0 is available. The Help menu has the link."
    ]
    assert window.update_available_action.isVisible()
    assert window.update_available_action.text() == "Update available: 0.2.0…"
    help_menu = next(
        menu for menu in window.menuBar().findChildren(QMenu)
        if "Help" in menu.title()
    )
    actions = help_menu.actions()
    assert actions.index(window.update_available_action) < (
        actions.index(window.check_for_updates_action)
    )


def test_the_help_menu_entry_shows_the_release_without_asking_again(
        qtbot, monkeypatch, caplog,
):
    calls = _patch_check(monkeypatch, AVAILABLE)
    caplog.set_level(logging.INFO, logger="seeker.ui.update_scheduler")
    window, _ = _window(qtbot)
    _wait_for_the_logged_outcome(qtbot, caplog)
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "exec", lambda box: shown.append(box.text()),
    )

    window.update_available_action.trigger()

    assert len(calls) == 1
    assert len(shown) == 1
    assert "0.2.0" in shown[0]
    assert AVAILABLE.release_url in shown[0]


@pytest.mark.parametrize("result", [
    UpdateCheckResult(
        UpdateStatus.UP_TO_DATE, latest_version="0.1.0",
        installed_version="0.1.0",
    ),
    UpdateCheckResult(
        UpdateStatus.NO_RELEASES_PUBLISHED,
        reason="No releases have been published yet.",
    ),
    UpdateCheckResult(
        UpdateStatus.UNAVAILABLE,
        reason="GitHub rate-limited this check — try again later.",
    ),
], ids=lambda result: result.status.name)
def test_every_other_answer_is_silent_and_logged_at_info(
        qtbot, monkeypatch, caplog, result,
):
    force_tray_available(monkeypatch, True)
    _patch_check(monkeypatch, result)
    caplog.set_level(logging.INFO, logger="seeker.ui.update_scheduler")
    window, _ = _window(qtbot)
    messages = _tray_messages(monkeypatch, window)

    _wait_for_the_logged_outcome(qtbot, caplog)

    assert messages == []
    assert not window.update_available_action.isVisible()
    record = next(
        record for record in caplog.records
        if record.getMessage().startswith("Automatic update check:")
    )
    assert record.levelno == logging.INFO
    assert result.status.name in record.getMessage()

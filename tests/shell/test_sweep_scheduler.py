"""The shell's daily sweep: due checks after the first good backend
poll and then hourly, one sweep at a time, stopped on quit.
"""
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fakes import FakeApplication, FakeSweepService
from seeker.ui.main_window import MainWindow
from seeker.ui.sweep_scheduler import SWEEP_KEY


def _window(qtbot, *, enabled=True, last_sweep_at=None, configured=True):
    application = FakeApplication(soulseek_configured=configured)
    application._config_store = replace(
        application._config_store,
        auto_sweep_enabled=enabled,
        last_sweep_at=last_sweep_at,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    return window, application.sweep_service


def _wait_for_the_sweep_to_end(qtbot, window):
    qtbot.waitUntil(
        lambda: not window.busy_actions.is_running(SWEEP_KEY), timeout=2000,
    )


def _first_good_poll(qtbot, window):
    window._trigger_backend_poll()
    qtbot.waitUntil(
        lambda: not window._backend_poll_in_progress, timeout=2000,
    )


def test_the_first_good_backend_poll_starts_a_due_sweep(qtbot):
    window, sweeps = _window(qtbot)

    _first_good_poll(qtbot, window)
    _wait_for_the_sweep_to_end(qtbot, window)

    assert len(sweeps.calls) == 1


def test_no_sweep_runs_before_the_first_good_backend_poll(qtbot):
    window, sweeps = _window(qtbot)

    window.sweep_timer.timeout.emit()

    assert sweeps.calls == []
    assert not window.busy_actions.is_running(SWEEP_KEY)


def test_a_sweep_that_is_not_due_does_not_run(qtbot):
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    window, sweeps = _window(qtbot, last_sweep_at=recent)

    _first_good_poll(qtbot, window)
    window.sweep_timer.timeout.emit()

    assert sweeps.calls == []


def test_a_disabled_sweep_does_not_run(qtbot):
    window, sweeps = _window(qtbot, enabled=False)

    _first_good_poll(qtbot, window)
    window.sweep_timer.timeout.emit()

    assert sweeps.calls == []


def test_the_hourly_check_starts_a_sweep_that_became_due(qtbot):
    recent = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    window, sweeps = _window(qtbot, last_sweep_at=recent)
    _first_good_poll(qtbot, window)
    assert sweeps.calls == []

    window.application.update_settings(
        last_sweep_at=(datetime.now(UTC) - timedelta(hours=25)).isoformat(),
    )
    window.sweep_timer.timeout.emit()
    _wait_for_the_sweep_to_end(qtbot, window)

    assert len(sweeps.calls) == 1


def test_a_check_while_a_sweep_runs_starts_no_second_one(qtbot):
    window, sweeps = _window(qtbot)
    sweeps.hold = threading.Event()
    _first_good_poll(qtbot, window)
    qtbot.waitUntil(lambda: len(sweeps.calls) == 1, timeout=2000)

    window.sweep_timer.timeout.emit()
    window.sweep_timer.timeout.emit()
    sweeps.hold.set()
    _wait_for_the_sweep_to_end(qtbot, window)

    assert len(sweeps.calls) == 1


def test_a_running_sweep_shows_on_the_activity_strip(qtbot):
    window, sweeps = _window(qtbot)
    window.show()
    sweeps.hold = threading.Event()
    _first_good_poll(qtbot, window)

    assert window.activity_strip.isVisible()
    assert window.activity_strip_label.text() == (
        "Looking again for missing tracks…"
    )

    sweeps.hold.set()
    _wait_for_the_sweep_to_end(qtbot, window)


def test_quitting_stops_a_running_sweep_and_starts_no_other(qtbot):
    window, sweeps = _window(qtbot)
    sweeps.hold = threading.Event()
    _first_good_poll(qtbot, window)
    qtbot.waitUntil(lambda: len(sweeps.calls) == 1, timeout=2000)
    stop = sweeps.calls[0]
    assert stop is not None and not stop.is_set()

    window._release_for_quit()

    assert stop.is_set()
    assert not window.sweep_timer.isActive()
    sweeps.hold.set()
    _wait_for_the_sweep_to_end(qtbot, window)
    window._sweep_scheduler.check()
    assert len(sweeps.calls) == 1


def test_no_sweep_without_soulseek_configured(qtbot):
    window, sweeps = _window(qtbot, configured=False)

    _first_good_poll(qtbot, window)
    window.sweep_timer.timeout.emit()

    assert sweeps.calls == []
    assert isinstance(sweeps, FakeSweepService)

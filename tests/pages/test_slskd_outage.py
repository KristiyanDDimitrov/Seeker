"""An unreachable slskd: the shared outage state, the Dashboard and
Downloads notices, the tray's once-per-outage notification, and the
Start slskd action (HISTORY §151)."""

from dataclasses import replace

from seeker.docker_setup import SlskdStartRefusedError
from seeker.soulseek.client import SlskdUnreachableError
from seeker.ui.main_window import MainWindow
from seeker.ui.slskd_status import SlskdStatus
from test_ui_smoke import FakeApplication, _force_tray_available

OUTAGE = str(SlskdUnreachableError("http://localhost:5030"))


def _raise_outage() -> dict:
    raise SlskdUnreachableError("http://localhost:5030")


def _poll(qtbot, window: MainWindow) -> None:
    window._trigger_backend_poll()
    qtbot.waitUntil(
        lambda: not window._backend_poll_in_progress, timeout=2000,
    )


def _outage_window(qtbot, monkeypatch) -> tuple[FakeApplication, MainWindow]:
    _force_tray_available(monkeypatch, True)
    application = FakeApplication(soulseek_configured=True)
    application.download_service.poll_downloads = _raise_outage
    window = MainWindow(application)
    qtbot.addWidget(window)
    return application, window


def _record_tray_messages(monkeypatch, window: MainWindow) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(
        window._tray._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )
    return messages


def test_slskd_status_reports_and_signals_only_edges(qtbot):
    status = SlskdStatus()

    with qtbot.waitSignal(status.changed, timeout=500):
        assert status.mark_unreachable(OUTAGE) is True
    assert status.unreachable_message == OUTAGE

    with qtbot.assertNotEmitted(status.changed):
        assert status.mark_unreachable(OUTAGE) is False

    with qtbot.waitSignal(status.changed, timeout=500):
        assert status.mark_reachable() is True
    assert status.unreachable_message is None

    with qtbot.assertNotEmitted(status.changed):
        assert status.mark_reachable() is False


def test_outage_shows_on_dashboard_and_downloads(qtbot, monkeypatch):
    _, window = _outage_window(qtbot, monkeypatch)

    _poll(qtbot, window)

    next_step = window._dashboard_page.next_step_notice
    qtbot.waitUntil(lambda: next_step.text() == OUTAGE, timeout=2000)
    assert not next_step.isHidden()
    assert next_step.action_button.text() == "Start slskd"

    outage_notice = window._downloads_page.outage_notice
    assert outage_notice.text() == OUTAGE
    assert not outage_notice.isHidden()
    assert outage_notice.action_button.text() == "Start slskd"


def test_tray_notifies_once_per_outage(qtbot, monkeypatch):
    application, window = _outage_window(qtbot, monkeypatch)
    messages = _record_tray_messages(monkeypatch, window)

    _poll(qtbot, window)
    _poll(qtbot, window)
    assert messages == [OUTAGE]

    # A recovery re-arms the notification without notifying itself.
    application.download_service.poll_downloads = lambda: {}
    _poll(qtbot, window)
    assert messages == [OUTAGE]

    application.download_service.poll_downloads = _raise_outage
    _poll(qtbot, window)
    assert messages == [OUTAGE, OUTAGE]


def test_outage_notification_honours_the_errors_setting(
        qtbot,
        monkeypatch,
):
    application, window = _outage_window(qtbot, monkeypatch)
    application._config_store = replace(
        application._config_store, notify_errors=False,
    )
    messages = _record_tray_messages(monkeypatch, window)

    _poll(qtbot, window)

    assert window.slskd_status.unreachable_message == OUTAGE
    assert messages == []


def test_first_successful_poll_clears_the_outage(qtbot, monkeypatch):
    application, window = _outage_window(qtbot, monkeypatch)
    _poll(qtbot, window)
    next_step = window._dashboard_page.next_step_notice
    qtbot.waitUntil(lambda: next_step.text() == OUTAGE, timeout=2000)

    application.download_service.poll_downloads = lambda: {}
    _poll(qtbot, window)

    assert window.slskd_status.unreachable_message is None
    assert window._downloads_page.outage_notice.isHidden()
    qtbot.waitUntil(lambda: next_step.text() != OUTAGE, timeout=2000)


def test_other_poll_errors_are_not_an_outage(qtbot, monkeypatch):
    application, window = _outage_window(qtbot, monkeypatch)
    messages = _record_tray_messages(monkeypatch, window)

    def fail() -> dict:
        raise RuntimeError("The database is busy.")

    application.download_service.poll_downloads = fail
    _poll(qtbot, window)

    assert window.slskd_status.unreachable_message is None
    assert window._downloads_page.outage_notice.isHidden()
    assert messages == ["The database is busy."]


def test_start_slskd_from_dashboard_calls_the_bring_up(qtbot, monkeypatch):
    application, window = _outage_window(qtbot, monkeypatch)
    _poll(qtbot, window)
    next_step = window._dashboard_page.next_step_notice
    qtbot.waitUntil(lambda: next_step.text() == OUTAGE, timeout=2000)

    next_step.action_button.click()

    dashboard_notice = window._dashboard_page.dashboard_notice
    qtbot.waitUntil(
        lambda: "starting" in dashboard_notice.text().lower(), timeout=2000,
    )
    assert application.restart_slskd_calls == 1
    assert not window.busy_actions.is_running("start_slskd")


def test_start_slskd_refusal_reports_on_downloads(qtbot, monkeypatch):
    application, window = _outage_window(qtbot, monkeypatch)
    refusal = "Docker isn't running. Open Docker Desktop, then try again."
    application.restart_slskd_error = SlskdStartRefusedError(refusal)
    _poll(qtbot, window)

    window._downloads_page.outage_notice.action_button.click()

    notice = window._downloads_page.notice
    qtbot.waitUntil(lambda: notice.text() == refusal, timeout=2000)
    assert application.restart_slskd_calls == 1
    assert window._dashboard_page.dashboard_notice.isHidden()

import logging
import sys
import threading
from dataclasses import dataclass
from importlib.metadata import version
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace
from typing import ClassVar

import platformdirs
import pytest

from seeker import main_ui
from seeker.soulseek import poller


def test_application_identity_is_seekers_own(qapp):
    previous = (
        qapp.applicationName(),
        qapp.applicationDisplayName(),
        qapp.applicationVersion(),
    )

    try:
        main_ui._configure_application_identity(qapp)

        assert qapp.applicationName() == "Seeker"
        assert qapp.applicationDisplayName() == "Seeker"
        assert qapp.applicationVersion() == version("seeker")
    finally:
        qapp.setApplicationName(previous[0])
        qapp.setApplicationDisplayName(previous[1])
        qapp.setApplicationVersion(previous[2])


@pytest.fixture
def isolated_entry_point(tmp_path, monkeypatch):
    """Point the log directory into tmp_path, keep the working
    directory's `.env` out of reach, and put back every process-wide
    hook and logger setting main() changes."""
    log_dir = tmp_path / "logs"
    monkeypatch.setattr(
        platformdirs, "user_log_dir",
        lambda *args, **kwargs: str(log_dir),
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEEKER_DEBUG_POLL", raising=False)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)

    seeker_logger = logging.getLogger("seeker")
    handlers, level = list(seeker_logger.handlers), seeker_logger.level
    poll_level = poller.logger.level
    yield log_dir
    for handler in seeker_logger.handlers:
        if handler not in handlers:
            handler.close()
    seeker_logger.handlers[:] = handlers
    seeker_logger.setLevel(level)
    poller.logger.setLevel(poll_level)


def test_configure_logging_writes_the_seeker_tree_to_the_log_file(
        isolated_entry_point,
):
    main_ui._configure_logging()
    logging.getLogger("seeker.library.service").info("Scanned 3 files.")
    logging.getLogger("seeker.library.service").debug("not at INFO")
    for handler in logging.getLogger("seeker").handlers:
        handler.flush()

    lines = (isolated_entry_point / "seeker.log").read_text().splitlines()

    assert len(lines) == 1
    assert lines[0].endswith(" INFO seeker.library.service: Scanned 3 files.")


# --- main() over fakes ------------------------------------------------
#
# A test process already has its one QApplication (pytest-qt's), so
# main() gets a stand-in; MainWindow and the wizard are stand-ins too,
# recording what main() asked of them.


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class FakeQApplication:
    instances: ClassVar[list["FakeQApplication"]] = []

    def __init__(self, argv):
        self.quit_on_last_window_closed = True
        self.aboutToQuit = _Signal()
        self.identity: dict[str, str] = {}
        FakeQApplication.instances.append(self)

    def setApplicationName(self, name):
        self.identity["name"] = name

    def setApplicationDisplayName(self, name):
        self.identity["display_name"] = name

    def setApplicationVersion(self, value):
        self.identity["version"] = value

    def setQuitOnLastWindowClosed(self, value):
        self.quit_on_last_window_closed = value

    def exec(self):
        return 0


class FakeMainWindow:
    instances: ClassVar[list["FakeMainWindow"]] = []
    tray_available = True

    def __init__(self, application):
        self.application = application
        self.calls: list[str] = []
        FakeMainWindow.instances.append(self)

    def cleanup_before_quit(self):
        self.calls.append("cleanup_before_quit")

    def start_hidden_to_tray(self):
        self.calls.append("start_hidden_to_tray")
        return FakeMainWindow.tray_available

    def show_restored(self):
        self.calls.append("show_restored")

    def show(self):
        self.calls.append("show")


class FakeWizard:
    instances: ClassVar[list["FakeWizard"]] = []

    def __init__(self, application, on_complete):
        self.on_complete = on_complete
        self.shown = False
        FakeWizard.instances.append(self)

    def show(self):
        self.shown = True


@dataclass
class FakeSettings:
    start_hidden_at_login: bool = False


class FakeApplication:
    def __init__(self, onboarding_complete=True, start_hidden=False):
        self.onboarding_complete = onboarding_complete
        self.theme_mode = "dark"
        self.settings = FakeSettings(start_hidden_at_login=start_hidden)


def _run_main(monkeypatch, application, *, tray_available=True):
    for fake in (FakeQApplication, FakeMainWindow, FakeWizard):
        fake.instances = []
    FakeMainWindow.tray_available = tray_available
    themes: list[str] = []

    monkeypatch.setattr(main_ui, "Application", lambda: application)
    monkeypatch.setattr(main_ui, "QApplication", FakeQApplication)
    monkeypatch.setattr(main_ui, "MainWindow", FakeMainWindow)
    monkeypatch.setattr(main_ui, "OnboardingWizard", FakeWizard)
    monkeypatch.setattr(
        main_ui, "apply_theme", lambda app, mode: themes.append(mode),
    )
    installed_qt_handlers: list[bool] = []
    monkeypatch.setattr(
        main_ui, "install_qt_message_handler",
        lambda: installed_qt_handlers.append(True),
    )

    with pytest.raises(SystemExit) as exit_info:
        main_ui.main()

    (qt_app,) = FakeQApplication.instances
    return SimpleNamespace(
        exit_code=exit_info.value.code,
        qt_app=qt_app,
        themes=themes,
        installed_qt_handlers=installed_qt_handlers,
    )


def test_main_installs_the_crash_hooks_and_logs_to_the_file(
        isolated_entry_point, monkeypatch,
):
    excepthook_before = sys.excepthook
    threading_excepthook_before = threading.excepthook

    run = _run_main(monkeypatch, FakeApplication())

    assert sys.excepthook is not excepthook_before
    assert threading.excepthook is not threading_excepthook_before
    assert run.installed_qt_handlers == [True]
    assert any(
        isinstance(handler, RotatingFileHandler)
        for handler in logging.getLogger("seeker").handlers
    )


def test_main_opens_the_dashboard_once_onboarding_is_complete(
        isolated_entry_point, monkeypatch,
):
    application = FakeApplication()

    run = _run_main(monkeypatch, application)

    (window,) = FakeMainWindow.instances
    assert run.exit_code == 0
    assert window.application is application
    assert window.calls == ["show_restored"]
    assert run.qt_app.quit_on_last_window_closed is False
    assert run.qt_app.aboutToQuit.slots == [window.cleanup_before_quit]
    assert run.qt_app.identity["name"] == "Seeker"
    assert run.themes == ["dark"]
    assert FakeWizard.instances == []


def test_main_starts_hidden_to_the_tray_when_asked(
        isolated_entry_point, monkeypatch,
):
    _run_main(monkeypatch, FakeApplication(start_hidden=True))

    (window,) = FakeMainWindow.instances
    assert window.calls == ["start_hidden_to_tray"]


def test_main_shows_the_window_when_start_hidden_finds_no_tray(
        isolated_entry_point, monkeypatch,
):
    _run_main(
        monkeypatch, FakeApplication(start_hidden=True),
        tray_available=False,
    )

    (window,) = FakeMainWindow.instances
    assert window.calls == ["start_hidden_to_tray", "show_restored"]


def test_first_launch_shows_the_wizard_then_opens_the_dashboard(
        isolated_entry_point, monkeypatch,
):
    run = _run_main(monkeypatch, FakeApplication(onboarding_complete=False))

    (wizard,) = FakeWizard.instances
    assert wizard.shown is True
    assert FakeMainWindow.instances == []
    # Closing the wizard before finishing must still quit the app.
    assert run.qt_app.quit_on_last_window_closed is True

    wizard.on_complete()

    (dashboard,) = FakeMainWindow.instances
    assert dashboard.calls == ["show"]
    assert run.qt_app.quit_on_last_window_closed is False
    assert run.qt_app.aboutToQuit.slots == [dashboard.cleanup_before_quit]


def test_seeker_debug_poll_turns_on_the_gui_poll_trace(
        isolated_entry_point, monkeypatch,
):
    monkeypatch.setenv("SEEKER_DEBUG_POLL", "1")

    _run_main(monkeypatch, FakeApplication())

    assert poller.logger.level == logging.DEBUG

import logging
import sys
import threading

import pytest
from PySide6.QtCore import QMessageLogContext, QObject, QtMsgType, Signal

from seeker.ui import error_hooks


@pytest.fixture
def restored_hooks(monkeypatch):
    # install_exception_hooks() replaces process-wide hooks; setattr
    # through monkeypatch so each is put back after the test.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)


class _Emitter(QObject):
    fired = Signal()


def _critical_records(caplog):
    return [
        record for record in caplog.records
        if record.levelno == logging.CRITICAL
    ]


# pytest-qt otherwise swaps in its own sys.excepthook around each test
# (to fail it on a slot exception), which would stand in for the hook
# under test.
@pytest.mark.qt_no_exception_capture
def test_a_raising_slot_reaches_the_log(qtbot, caplog, restored_hooks):
    error_hooks.install_exception_hooks()
    emitter = _Emitter()

    def slot() -> None:
        raise RuntimeError("slot blew up")

    emitter.fired.connect(slot)

    with caplog.at_level(logging.CRITICAL, logger="seeker"):
        emitter.fired.emit()

    [record] = _critical_records(caplog)
    assert record.exc_info is not None
    assert "slot blew up" in caplog.text


# The hook hands the exception on to the one it replaced, here pytest's,
# which reports it as this warning: expected, not a leak.
@pytest.mark.filterwarnings(
    "ignore::pytest.PytestUnhandledThreadExceptionWarning",
)
def test_an_uncaught_thread_exception_reaches_the_log(caplog, restored_hooks):
    error_hooks.install_exception_hooks()

    def target() -> None:
        raise ValueError("thread blew up")

    with caplog.at_level(logging.CRITICAL, logger="seeker"):
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()

    [record] = _critical_records(caplog)
    assert record.exc_info is not None
    assert "thread blew up" in caplog.text


def test_keyboard_interrupt_is_not_logged_as_a_crash(caplog, restored_hooks):
    calls = []
    sys.excepthook = lambda *args: calls.append(args)
    error_hooks.install_exception_hooks()

    with caplog.at_level(logging.CRITICAL, logger="seeker"):
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert _critical_records(caplog) == []
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("message_type", "level"),
    [
        (QtMsgType.QtDebugMsg, logging.DEBUG),
        (QtMsgType.QtInfoMsg, logging.INFO),
        (QtMsgType.QtWarningMsg, logging.WARNING),
        (QtMsgType.QtCriticalMsg, logging.ERROR),
    ],
)
def test_qt_messages_are_logged_at_the_matching_level(
        caplog, message_type, level,
):
    with caplog.at_level(logging.DEBUG, logger="seeker"):
        error_hooks.log_qt_message(
            message_type, QMessageLogContext(), "QFont: something odd",
        )

    [record] = caplog.records
    assert record.levelno == level
    assert record.name == "seeker.qt"
    assert "QFont: something odd" in record.getMessage()


def test_the_offscreen_size_hints_warning_is_dropped(caplog):
    with caplog.at_level(logging.DEBUG, logger="seeker"):
        error_hooks.log_qt_message(
            QtMsgType.QtWarningMsg,
            QMessageLogContext(),
            "This plugin does not support propagateSizeHints()",
        )

    assert caplog.records == []

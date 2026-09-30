"""Routes every exception nothing caught, and every Qt diagnostic, into
the `seeker` logger tree, so `seeker.log` sees them.

A Finder-launched `.app` has no terminal: without these hooks an
exception raised in a Qt slot goes to stderr, which launchd discards.
Worker-thread failures are logged by `ui/workers.py` itself; this
covers the rest (slots, timers, event handlers, stray threads).
"""

import logging
import sys
import threading
from types import TracebackType

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler

logger = logging.getLogger(__name__)
qt_logger = logging.getLogger("seeker.qt")

_QT_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}

# Messages known to say nothing about Seeker, each with its evidence.
_BENIGN_QT_MESSAGES = (
    # The offscreen QPA plugin (tests, CI) lacks this window feature and
    # says so whenever a top-level widget's size hints change; observed
    # on a plain QWidget.setMinimumSize() under QT_QPA_PLATFORM=offscreen.
    # The Cocoa plugin a real launch uses supports it.
    "This plugin does not support propagateSizeHints()",
)


def install_exception_hooks() -> None:
    """Logs uncaught exceptions at CRITICAL, from the main thread
    (including a Qt slot, which PySide6 reports through
    `sys.excepthook`; observed live) and from any `threading.Thread`,
    then hands each to the hook it replaced so a terminal launch still
    prints the traceback."""
    previous_excepthook = sys.excepthook
    previous_threading_excepthook = threading.excepthook

    def excepthook(
            exc_type: type[BaseException],
            exc_value: BaseException,
            exc_traceback: TracebackType | None,
    ) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            logger.critical(
                "Uncaught exception",
                exc_info=(exc_type, exc_value, exc_traceback),
            )

        previous_excepthook(exc_type, exc_value, exc_traceback)

    def threading_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            thread_name = args.thread.name if args.thread else "unknown"
            logger.critical(
                "Uncaught exception in thread %s",
                thread_name,
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        previous_threading_excepthook(args)

    sys.excepthook = excepthook
    threading.excepthook = threading_excepthook


def install_qt_message_handler() -> None:
    qInstallMessageHandler(log_qt_message)


def log_qt_message(
        message_type: QtMsgType,
        context: QMessageLogContext,
        message: str,
) -> None:
    if message in _BENIGN_QT_MESSAGES:
        return

    level = _QT_LEVELS.get(message_type, logging.WARNING)

    if context.file:
        qt_logger.log(level, "%s (%s:%d)", message, context.file, context.line)
    else:
        qt_logger.log(level, "%s", message)

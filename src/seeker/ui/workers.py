from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QAbstractButton, QLabel


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    """Runs a bound, zero-argument callable off the main thread via
    QThreadPool, then emits finished(result) or error(message) back on
    the main thread. Every long-running action in this app (sync, scan,
    match, download, the dashboard's status poll) goes through this —
    no per-screen bespoke threading.
    """

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as error:
            self.signals.error.emit(str(error))
        else:
            self.signals.finished.emit(result)


# QRunnable isn't a QObject, so it can't be kept alive via Qt's own
# parent-child ownership the way a QObject could — QThreadPool.start()
# schedules it on a real OS thread and returns immediately, well before
# run() actually executes there. Without a strong Python reference held
# somewhere until it finishes, the local `worker` variable in
# run_worker() below is the only reference, and it goes out of scope
# the instant the function returns — long before the background thread
# is done using it. Confirmed for real, not theoretical: without this
# registry, a worker's result never arrived (silently GC'd before
# run() executed) or, under different timing, the process segfaulted
# outright (a cross-thread signal emit racing a half-finalized object).
# This registry is the fix — every in-flight worker is kept alive here
# until its own finished/error signal fires.
_active_workers: set[Worker] = set()


def run_worker(
        pool: QThreadPool,
        fn: Callable[[], Any],
        button: QAbstractButton | None = None,
        status_label: QLabel | None = None,
        on_finished: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
) -> Worker:
    """Submit fn to run in the background. The triggering button (if
    any) disables for the duration and re-enables on completion either
    way; an error clears to the status line rather than a modal dialog.
    `on_error` is for callers that need to react to a failure beyond the
    status line (e.g. clearing an in-progress flag) — optional, and
    additive to the status-label behavior, not a replacement for it.
    """
    if button is not None:
        button.setEnabled(False)

    if status_label is not None:
        status_label.setText("")

    worker = Worker(fn)
    _active_workers.add(worker)

    def handle_finished(result: Any) -> None:
        _active_workers.discard(worker)

        if button is not None:
            button.setEnabled(True)

        if on_finished is not None:
            on_finished(result)

    def handle_error(message: str) -> None:
        _active_workers.discard(worker)

        if button is not None:
            button.setEnabled(True)

        if status_label is not None:
            status_label.setText(message)

        if on_error is not None:
            on_error(message)

    worker.signals.finished.connect(handle_finished)
    worker.signals.error.connect(handle_error)

    pool.start(worker)

    return worker

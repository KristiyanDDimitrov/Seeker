from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
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


# Real, confirmed-live leak fix (broad end-to-end stress test, see
# CLAUDE.md): handle_finished/handle_error both close over `worker`
# itself (to call _active_workers.discard(worker)), and are connected
# to worker.signals.finished/.error — a genuine reference cycle
# (worker -> worker.signals -> [Qt connection] -> handle_finished/
# handle_error -> worker). Discarding worker from _active_workers only
# drops OUR set's reference; it does nothing about the connection
# itself, which independently keeps the whole cycle alive. A live
# repro (repeatedly opening and closing SettingsWindow, 40 real
# cycles, explicit gc.collect() between each) showed every single
# Worker/WorkerSignals object ever created was STILL live afterward —
# the Qt/shiboken side of a signal connection isn't visible to
# Python's own cycle tracer, so this leak is real and permanent
# without breaking the connection, not just slow to collect.
#
# Qt.ConnectionType.SingleShotConnection (connect() below) is what
# actually breaks it — NOT a manual worker.signals.X.disconnect()
# call from inside the very handler that signal's own emission just
# invoked. A first attempt tried exactly that manual disconnect and
# caused a real, reproducible segfault (confirmed live: full test
# suite crashed deep in Qt's own event processing, consistently,
# every run) — mutating a signal's connection list while that same
# signal is mid-emission is undefined behavior in Qt's C++ layer, not
# something Python-level try/except can protect against.
# SingleShotConnection instead tells Qt itself to disconnect its own
# connection safely, internally, immediately after that one emission
# finishes — the same real repro confirms this has zero leak (every
# Worker/WorkerSignals object released) with the full test suite
# passing clean, not just the isolated case.
#
# One asymmetry SingleShotConnection alone doesn't cover: a Worker
# only ever emits ONE of finished/error, never both — so whichever
# signal DIDN'T fire still has its original connection sitting there
# forever (its SingleShotConnection never got a chance to trigger).
# handle_finished/handle_error each explicitly disconnect the OTHER
# (non-firing) signal — safe to do, since that signal was never
# mid-emission in the first place.
def _disconnect_the_signal_that_never_fired(
        signal: object, connected_slot: Callable[..., object],
) -> None:
    signal.disconnect(connected_slot)  # type: ignore[attr-defined]


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
        _disconnect_the_signal_that_never_fired(worker.signals.error, handle_error)

        if button is not None:
            button.setEnabled(True)

        if on_finished is not None:
            # A bug in the caller's own render/completion logic (a
            # malformed-data assumption violated, an index error, ...)
            # must not be left to whatever PySide6's own default
            # exception hook happens to do with it. Confirmed live,
            # not assumed: on this version an unhandled exception here
            # neither crashes the app nor stops the QTimer that
            # triggered this poll from firing again — but it also
            # leaves the failure completely invisible to an actual GUI
            # user (only a raw traceback on stderr, which a
            # non-terminal launch never shows), forever, every tick,
            # with the table/panel just silently never updating again.
            # Same "one bad item can't silently vanish" principle as
            # every batch loop in this codebase (see CLAUDE.md item
            # 15) — surfaced to status_label too, when the caller
            # provided one, so a render bug is exactly as visible as
            # any other error already is for that action.
            try:
                on_finished(result)
            except Exception as error:
                print(f"Error handling worker result: {error}")

                if status_label is not None:
                    status_label.setText(f"Error: {error}")

    def handle_error(message: str) -> None:
        _active_workers.discard(worker)
        _disconnect_the_signal_that_never_fired(
            worker.signals.finished, handle_finished
        )

        if button is not None:
            button.setEnabled(True)

        if status_label is not None:
            status_label.setText(message)

        if on_error is not None:
            try:
                on_error(message)
            except Exception as error:
                print(f"Error handling worker error callback: {error}")

    worker.signals.finished.connect(
        handle_finished, Qt.ConnectionType.SingleShotConnection
    )
    worker.signals.error.connect(
        handle_error, Qt.ConnectionType.SingleShotConnection
    )

    pool.start(worker)

    return worker

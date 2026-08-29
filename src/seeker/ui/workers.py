from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QAbstractButton, QLabel


class Worker(QRunnable):
    """Runs a bound, zero-argument callable off the main thread via
    QThreadPool, then reports finished(result)/error(message) back on
    the main thread through the shared _Dispatcher below (never a
    per-worker signal — see that class's own docstring for why). Every
    long-running action in this app (sync, scan, match, download, the
    dashboard's status poll) goes through this — no per-screen bespoke
    threading.
    """

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        # QThreadPool's C++ side auto-deletes a QRunnable the instant
        # run() returns UNLESS told not to (confirmed live: a fresh
        # QRunnable subclass's autoDelete() defaults to True). The
        # dispatcher below passes `self` through a cross-thread queued
        # signal as the LAST statement of run() — a real, reproducible
        # segfault (caught by the full test suite, not the isolated
        # repro — see docs/HISTORY.md item 39) traced to exactly this:
        # QThreadPool deletes the underlying C++ object the moment
        # run() returns, which can race ahead of the queued event
        # actually being delivered/processed on the main thread, so
        # `worker` in _handle_task_finished/_handle_task_error can
        # already be a dangling reference to a deleted C++ object by
        # the time it's used. The original per-task WorkerSignals
        # design never hit this because it never passed the worker
        # itself through any signal — only the plain result value.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as error:
            _dispatcher.task_error.emit(self, str(error))
        else:
            _dispatcher.task_finished.emit(self, result)


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
# until its own completion is dispatched.
_active_workers: set[Worker] = set()


class _Dispatcher(QObject):
    """A single, permanent QObject whose two signals are connected
    EXACTLY ONCE, at import time, for the whole life of the process —
    never reconnected or disconnected again. Every Worker reports
    through this same shared dispatcher instead of a fresh per-task
    QObject+connect()/disconnect() cycle.

    This replaces an earlier per-task design (one `WorkerSignals`
    QObject created fresh per `run_worker()` call, connected then
    disconnected every time) after that design was confirmed live to
    cause a real, reproducible deadlock — not a rare theoretical race.
    Root cause, confirmed via `sample`-profiling a genuinely stuck
    process (see CLAUDE.md/docs/HISTORY.md item 39): Qt's own signal/
    slot connection bookkeeping is guarded by a striped pool of mutexes
    keyed by object address (`QObjectPrivate::signalSlotLock`, backed
    by `QMutexPool` — confirmed against Qt's own internals, not
    assumed). A cross-thread `.emit()` needs the GIL (to safely copy
    the Python result into a queued event) WHILE holding one of those
    mutex-pool slots; a `.connect()`/`.disconnect()` call on the main
    thread needs the GIL's own thread to be free to run AND needs a
    mutex-pool slot too (two slots, in fact — sender and receiver).
    With a fresh `WorkerSignals()` object (a new heap address) on every
    single task, and `connect()`/`disconnect()` happening on every
    single task too, the address space of "objects whose pool slot
    might collide with whatever the main thread is touching right now"
    grows continuously — live-verified (a standalone repro script, not
    just reasoning) to collide often enough to hang a real process
    within seconds under realistic concurrent load.

    A first attempt at fixing this — a single `threading.RLock` around
    every cross-thread connect/disconnect/emit call — was verified live
    to REDUCE but NOT ELIMINATE the hang: it correctly serializes our
    own connect/disconnect/emit calls against each other (confirmed:
    zero hangs across repeated trials with no other Qt widget
    construction happening concurrently), but the OTHER side of a real
    collision can be a completely unrelated `QObject::connect()` call
    Qt itself makes internally while constructing an ordinary widget
    (a `QToolBar`, a `QPushButton`, ...) — code we don't own and can't
    wrap in a Python-level lock. With real, concurrent widget
    construction in the mix (the actual real-world condition — this
    app builds fresh buttons in table rows on every 2s poll tick), the
    RLock version still hung in roughly half of repeated trials.

    This dispatcher design removes the other half of the problem
    instead: by connecting exactly once and never disconnecting, the
    ONLY Qt connection-list operation happening on a hot path is
    `.emit()` itself, always on the SAME fixed-address `_dispatcher`
    object — not a constantly-growing population of distinct
    addresses. `.emit()` calls from different worker threads still
    serialize against each other via Qt's own per-object connection
    lock (safe, and no different from before); what's gone is the
    steady stream of `connect()`/`disconnect()` calls that used to
    compound the collision surface. Live-verified (the same repro
    script, unaltered) to fully eliminate the hang, including under the
    exact concurrent-widget-construction conditions that broke the
    RLock attempt, and including at a stress level higher than what
    reliably broke the original design within its first attempt.
    """

    task_finished = Signal(object, object)
    task_error = Signal(object, str)


_dispatcher = _Dispatcher()

# Keyed by id(worker), not the worker object itself — sidesteps any
# question of whether a QRunnable subclass is safely hashable across
# the shiboken binding. Safe from id() reuse: an entry is only ever
# removed by that exact worker's own completion, in the same handler
# that also drops it from _active_workers — so nothing else can free
# (and Python can't recycle the address of) a worker whose entry is
# still here.
_CallbackEntry = tuple[
    QAbstractButton | None,
    QLabel | None,
    Callable[[Any], None] | None,
    Callable[[str], None] | None,
]
_callbacks: dict[int, _CallbackEntry] = {}


def _handle_task_finished(worker: object, result: Any) -> None:
    entry = _callbacks.pop(id(worker), None)
    _active_workers.discard(worker)

    if entry is None:
        return

    button, status_label, on_finished, _on_error = entry

    if button is not None:
        button.setEnabled(True)

    if on_finished is not None:
        # A bug in the caller's own render/completion logic (a
        # malformed-data assumption violated, an index error, ...)
        # must not be left to whatever PySide6's own default exception
        # hook happens to do with it — see run_worker()'s own docstring
        # for the full reasoning (unchanged from before this redesign).
        try:
            on_finished(result)
        except Exception as error:
            print(f"Error handling worker result: {error}")

            if status_label is not None:
                status_label.setText(f"Error: {error}")


def _handle_task_error(worker: object, message: str) -> None:
    entry = _callbacks.pop(id(worker), None)
    _active_workers.discard(worker)

    if entry is None:
        return

    button, status_label, _on_finished, on_error = entry

    if button is not None:
        button.setEnabled(True)

    if status_label is not None:
        status_label.setText(message)

    if on_error is not None:
        try:
            on_error(message)
        except Exception as error:
            print(f"Error handling worker error callback: {error}")


# The one and only connect() for these two signals, for the life of
# the process — see _Dispatcher's own docstring for why this is the
# real fix rather than a per-task connect/disconnect cycle.
_dispatcher.task_finished.connect(_handle_task_finished)
_dispatcher.task_error.connect(_handle_task_error)


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
    _callbacks[id(worker)] = (button, status_label, on_finished, on_error)

    pool.start(worker)

    return worker

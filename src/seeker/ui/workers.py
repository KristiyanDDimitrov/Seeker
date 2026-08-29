import itertools
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QAbstractButton, QLabel

# Plain, non-Qt correlation ids for in-flight tasks. The dispatcher
# signal carries this, never the Worker/QRunnable instance itself — see
# Worker's own docstring for the two things this avoids.
_next_task_id = itertools.count()


class Worker(QRunnable):
    """Runs a bound, zero-argument callable off the main thread via
    QThreadPool, then reports finished(result)/error(message) back on
    the main thread through the shared _Dispatcher below (never a
    per-worker signal — see that class's own docstring for why). Every
    long-running action in this app (sync, scan, match, download, the
    dashboard's status poll) goes through this — no per-screen bespoke
    threading.

    Two real, independently-confirmed hazards shaped this design
    (docs/HISTORY.md item 39) — both live-verified with a reproducible
    subprocess repro, not reasoned about in the abstract:

    1. `setAutoDelete(False)` is required, full stop, regardless of
       what crosses the dispatcher signal. Confirmed live via bisection:
       a task_id-only signal (no Worker reference anywhere in it) with
       `autoDelete` left at its default (`True`) STILL segfaults
       reproducibly (5/5) in a real pytest-qt teardown sequence, and
       switching only `setAutoDelete(False)` back on — nothing else
       changed — made the exact same repro pass cleanly. The mechanism:
       `Worker` is a Python subclass carrying real Python state
       (`self.fn`, a bound closure, often itself holding references
       back into a QWidget). `QThreadPool`'s own auto-delete tears that
       down on the WORKER thread the instant `run()` returns — safe for
       a plain C++ QRunnable, but requires touching the Python
       interpreter (decref'ing `self.fn` and friends) to tear down a
       Python subclass instance, and doing that from a background
       thread immediately after `run()` returns has been confirmed,
       live, to race unsafely against ordinary main-thread Qt/Python
       activity (e.g. a window closing while its own background poll
       is still in flight — see docs/HISTORY.md item 39's regression
       test and its own `test_backend_poll_runs_poll_downloads_off_
       the_main_thread` fix for the closely related test-timing gap
       this crash class also depends on).
    2. Passing `self` through the signal (an earlier, briefly-tried
       design) is independently wrong even with `setAutoDelete(False)`
       correctly set: a QRunnable's lifetime is Qt's own to manage once
       submitted, and marshaling that specific object across a queued
       cross-thread connection adds a second, separate hazard on top of
       (1) for no benefit — a plain `task_id` int carries everything
       the dispatcher actually needs (a dict lookup keyed by it), with
       none of a QRunnable's own cross-thread marshaling baggage.

    The earlier native-memory-leak finding this task started from (an
    unfreed native `Worker` per completed task, confirmed via
    `shiboken6.Shiboken.getAllValidWrappers()`) is real given (1). Fixed
    below, but NOT by a synchronous `shiboken6.Shiboken.delete()` call
    inside the dispatcher's own signal handler — that was tried first
    and confirmed live to reintroduce the exact same class of crash as
    (1), even with the worker reference obtained via a plain dict
    lookup keyed by `task_id` rather than the signal payload: deleting
    the native QRunnable while still inside the call stack of the
    queued signal that just reported it done is itself unsafe in this
    environment. `QTimer.singleShot(0, ...)` defers the delete to the
    NEXT event-loop iteration instead — confirmed live, this fully
    avoids the crash while still freeing the native object with no
    unbounded accumulation (see `_delete_native_worker`'s docstring).
    """

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.task_id = next(_next_task_id)
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as error:
            _dispatcher.task_error.emit(self.task_id, str(error))
        else:
            _dispatcher.task_finished.emit(self.task_id, result)


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

    task_finished = Signal(int, object)
    task_error = Signal(int, str)


_dispatcher = _Dispatcher()

# Keyed by Worker.task_id (a plain int assigned before submission), not
# by the worker itself — the dispatcher signal never carries the
# QRunnable (see Worker's own docstring for why), so there's no
# id()-reuse hazard to sidestep either: each task_id is unique for the
# life of the process (itertools.count() never repeats), and an entry
# is only ever removed by that exact task's own completion. The
# `Worker` reference kept here (not passed through the signal) is what
# lets the handlers below explicitly free the native object once
# they're done with it, avoiding the leak `setAutoDelete(False)`
# otherwise causes.
_CallbackEntry = tuple[
    Worker,
    QAbstractButton | None,
    QLabel | None,
    Callable[[Any], None] | None,
    Callable[[str], None] | None,
]
_callbacks: dict[int, _CallbackEntry] = {}


def _delete_native_worker(worker: Worker) -> None:
    """Frees the underlying C++ `QRunnable` once its own completion has
    been fully handled. Always called via `QTimer.singleShot(0, ...)`
    from the handlers below, never synchronously from within the
    dispatcher signal handler itself — see Worker's own docstring for
    why a synchronous call at that exact point was confirmed live to
    reintroduce a crash. `isValid()` guards against ever double-
    deleting the same native object.
    """
    if shiboken6.Shiboken.isValid(worker):
        shiboken6.Shiboken.delete(worker)


def _handle_task_finished(task_id: int, result: Any) -> None:
    entry = _callbacks.pop(task_id, None)

    if entry is None:
        return

    worker, button, status_label, on_finished, _on_error = entry

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

    QTimer.singleShot(0, lambda: _delete_native_worker(worker))


def _handle_task_error(task_id: int, message: str) -> None:
    entry = _callbacks.pop(task_id, None)

    if entry is None:
        return

    worker, button, status_label, _on_finished, on_error = entry

    if button is not None:
        button.setEnabled(True)

    if status_label is not None:
        status_label.setText(message)

    if on_error is not None:
        try:
            on_error(message)
        except Exception as error:
            print(f"Error handling worker error callback: {error}")

    QTimer.singleShot(0, lambda: _delete_native_worker(worker))


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

    The returned `Worker` (and the one stored in `_callbacks`) is the
    same reference kept alive by this dict entry until its own
    completion is handled and its native object explicitly freed — see
    `_delete_native_worker`'s and Worker's own docstrings for why
    `setAutoDelete(False)` plus an explicit delete, rather than letting
    `QThreadPool` auto-delete it, is the confirmed-safe combination.
    """
    if button is not None:
        button.setEnabled(False)

    if status_label is not None:
        status_label.setText("")

    worker = Worker(fn)
    _callbacks[worker.task_id] = (worker, button, status_label, on_finished, on_error)

    pool.start(worker)

    return worker

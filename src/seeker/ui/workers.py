import itertools
import time
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, SignalInstance, Slot
from PySide6.QtWidgets import QAbstractButton, QLabel

# Plain, non-Qt correlation ids for in-flight tasks. The dispatcher
# signal carries this, never the Worker/QRunnable instance itself — see
# Worker's own docstring for the two things this avoids.
_next_task_id = itertools.count()

# Roadmap item 65 (Phase 2.3) — progress-reporting throttle, applied
# INSIDE the worker thread, before anything ever reaches the dispatcher.
# This is a safety requirement, not polish: item 39's own deadlock was
# triggered by rapid, repeated cross-thread Qt activity, and a naive
# per-item progress emit across thousands of items (e.g. one per file
# during fingerprinting) is exactly that pattern. Both untuned — pick
# whichever threshold is hit first.
PROGRESS_EMIT_MIN_INTERVAL_S = 0.25
PROGRESS_EMIT_EVERY_N = 25


def _emit_or_drop(bound_signal: SignalInstance, *args: Any) -> None:
    """Emits into the shared dispatcher from a worker thread, silently
    dropping the result if `_dispatcher`'s native QObject is gone by the
    time this runs (interpreter shutdown, or a window closing while this
    worker was still mid-flight — CLAUDE.md item 41).

    **Why not a preceding `Shiboken.isValid(_dispatcher)` check instead
    (item 41's original fix)?** That's check-then-act, and there is a
    real, non-zero gap between confirming validity and actually calling
    `.emit()` where teardown can land — proven live, not assumed
    (`tests/_workers_teardown_race_repro.py`, which deterministically
    forces deletion to land in exactly that gap): the check-then-act
    version raised the same uncaught `RuntimeError` in every single
    forced trial, because the check happening to pass tells you nothing
    about the very next line. That test is the same "prove it, don't
    reason about it" discipline item 39's own aborted `RLock` attempt
    should have gotten the first time — CLAUDE.md item 42.

    **The boundary that's actually safe, confirmed live rather than
    assumed:** calling `.emit()` on a signal whose source QObject was
    ALREADY deleted — including a deletion landing synchronously
    immediately beforehand, the tightest possible version of this race —
    always raises a clean, catchable `RuntimeError: Signal source has
    been deleted`, never a segfault or a partial emit (confirmed via a
    direct interactive check: delete, then emit, repeatedly — always the
    same clean exception, never corruption). Wrapping the emit call
    itself, rather than gating it behind a separate check, is what
    actually closes the gap: there's no window left for teardown to land
    in between "wrapped" and "called," because they're the same
    statement.
    """
    try:
        bound_signal.emit(*args)
    except RuntimeError:
        pass


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
    unbounded accumulation (see `_schedule_native_delete`'s docstring).

    3. A third hazard, closed after this docstring's other two (CLAUDE.md
       item 42): `run()` reporting completion via the dispatcher can
       still race a real teardown of `_dispatcher` itself (see item 41).
       The fix isn't a validity check before the emit — that's
       check-then-act with a real gap in between — it's wrapping the
       emit call itself (`_emit_or_drop`, below); see that function's
       own docstring for why this is the actual, verified-safe boundary.
    """

    def __init__(
            self,
            fn: Callable[[], Any] | Callable[[Callable[[str, int, int], None]], Any],
            wants_progress: bool = False,
    ):
        super().__init__()
        self.fn = fn
        self.task_id = next(_next_task_id)
        self.setAutoDelete(False)
        # roadmap item 65 (Phase 2.3) — set only when run_worker() was
        # given an on_progress callback; changes nothing about fn's own
        # calling convention otherwise (every pre-existing call site's
        # zero-argument fn is completely unaffected).
        self._wants_progress = wants_progress
        # -inf, not 0.0: guarantees the FIRST _report_progress call always
        # emits regardless of what time.monotonic()'s own reference point
        # happens to be (0.0 "looks recent enough to throttle" only by
        # accident of real monotonic time always being a large positive
        # number — a real gap this task's own test caught: a monkeypatched
        # clock starting at 0.0 would otherwise throttle the very first
        # report). Immediate first-report feedback is the desired
        # behavior, not an accident — a caller starting a long operation
        # should see something before waiting out a full throttle window.
        self._progress_last_emit = float("-inf")
        self._progress_count = 0

    def _report_progress(self, stage: str, current: int, total: int) -> None:
        # Throttled at the source (roadmap item 65 Phase 2.3) — runs on
        # THIS worker thread, before _emit_or_drop is ever reached, so an
        # unthrottled caller looping over thousands of items can never
        # produce thousands of cross-thread emits regardless of how often
        # it calls this.
        self._progress_count += 1
        now = time.monotonic()
        elapsed = now - self._progress_last_emit

        if (
                elapsed < PROGRESS_EMIT_MIN_INTERVAL_S
                and self._progress_count % PROGRESS_EMIT_EVERY_N != 0
        ):
            return

        self._progress_last_emit = now
        _emit_or_drop(
            _dispatcher.task_progress, self.task_id, stage, current, total,
        )

    @Slot()
    def run(self) -> None:
        try:
            result = (
                self.fn(self._report_progress)  # type: ignore[call-arg]
                if self._wants_progress else self.fn()  # type: ignore[call-arg]
            )
        except Exception as error:
            # A straggling worker — fn() was still genuinely running when
            # the app started tearing down (window close, interpreter
            # shutdown) — can reach this point after _dispatcher's own
            # native QObject is already gone (first surfaced by
            # tests/test_stress_e2e.py once the Duplicates tab gave it
            # real background traffic to race against a slow real slskd
            # retry, CLAUDE.md item 41). Nobody is listening once the
            # dispatcher is gone regardless of why — `_emit_or_drop`
            # (see its own docstring) is what makes dropping the result
            # here actually safe, including against the tighter race a
            # plain pre-check can't close.
            _emit_or_drop(_dispatcher.task_error, self.task_id, str(error))
        else:
            _emit_or_drop(_dispatcher.task_finished, self.task_id, result)


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
    # Roadmap item 65 (Phase 2.3) — a THIRD signal on this same, already-
    # permanently-connected object, following the identical "primitives
    # only, connected once, emit-or-drop" pattern task_finished/task_error
    # already use. No new QObject, no new connect()/disconnect() —
    # exactly the property that made this dispatcher design safe in the
    # first place (see this class's own docstring above).
    task_progress = Signal(int, str, int, int)


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

# Roadmap item 65 (Phase 2.3) — a separate dict, not folded into
# _CallbackEntry above: a progress callback is optional and orthogonal
# to finished/error handling, and this one is deliberately NOT popped
# by _handle_task_progress itself (a task can report progress many
# times) — only ever removed by the SAME finished/error paths that
# already clean up _callbacks, so a late/dropped progress emit after
# completion can never look up a stale callback.
_progress_callbacks: dict[int, Callable[[str, int, int], None]] = {}


def _delete_native_worker(worker: Worker) -> None:
    """Frees the underlying C++ `QRunnable` once its own completion has
    been fully handled. Always called via `_schedule_native_delete`
    below, never synchronously and never left to plain `QThreadPool`
    autoDelete — see that function's own docstring for why. `isValid()`
    guards against ever double-deleting the same native object — a
    second, independent line of defense on top of
    `_schedule_native_delete` never scheduling a given worker's delete
    more than once in the first place (see its own docstring).
    """
    if shiboken6.Shiboken.isValid(worker):
        shiboken6.Shiboken.delete(worker)


def _schedule_native_delete(worker: Worker) -> None:
    """The only call site for `_delete_native_worker` — deferred one
    event-loop tick via `QTimer.singleShot(0, ...)`. Do not "simplify"
    this back to either of the two alternatives already tried and
    confirmed live (docs/HISTORY.md item 39) to reintroduce the same
    native-QObject-teardown-races-a-live-thread crash class:

    - Plain `QThreadPool` autoDelete (the default `setAutoDelete(True)`)
      tears the Python-subclassed `Worker` down ON THE WORKER THREAD the
      instant `run()` returns — real Python state (`self.fn`, often a
      closure holding references back into a QWidget) getting decref'd
      from a background thread the moment control leaves it, racing
      unsafely against ordinary main-thread Qt/Python activity. This is
      why `Worker.__init__` calls `setAutoDelete(False)` — see Worker's
      own docstring, point 1.
    - A SYNCHRONOUS `shiboken6.Shiboken.delete()` call made directly
      from inside the dispatcher's own signal handler (i.e., right here,
      with no `QTimer.singleShot`) — tried first, and confirmed live to
      crash just the same, even with the worker obtained via this dict
      lookup rather than the signal payload: deleting the native
      QRunnable while still on the call stack of the very queued signal
      that just reported it done is itself unsafe in this environment.

    Deferring to the next event-loop tick sidesteps both: by the time
    this callback actually runs, the dispatcher signal that triggered it
    is no longer on the call stack, and the delete happens on the main
    thread with no other thread touching this `worker` at that point.

    **Can this ever get scheduled twice for the same worker?** No —
    structurally, not just by luck. `_handle_task_finished`/
    `_handle_task_error` both `_callbacks.pop(task_id, None)` *before*
    reaching this call, and `Worker.run()`'s own try/except/else emits
    at most one of the two dispatcher signals per task — so at most one
    handler invocation ever sees a non-`None` entry for a given
    `task_id` to begin with; a hypothetical second invocation (there
    isn't a real path to one, but even if there were) would find
    `entry is None` and return before ever reaching this line.
    """
    QTimer.singleShot(0, lambda: _delete_native_worker(worker))


def _handle_task_progress(
        task_id: int,
        stage: str,
        current: int,
        total: int,
) -> None:
    # Deliberately does NOT pop _progress_callbacks — a task can report
    # progress many times before it finishes; only _handle_task_finished/
    # _handle_task_error (below) ever remove the entry, once, when the
    # task is actually done.
    callback = _progress_callbacks.get(task_id)

    if callback is None:
        return

    try:
        callback(stage, current, total)
    except Exception as error:
        print(f"Error handling worker progress: {error}")


def _handle_task_finished(task_id: int, result: Any) -> None:
    entry = _callbacks.pop(task_id, None)
    _progress_callbacks.pop(task_id, None)

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

    _schedule_native_delete(worker)


def _handle_task_error(task_id: int, message: str) -> None:
    entry = _callbacks.pop(task_id, None)
    _progress_callbacks.pop(task_id, None)

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

    _schedule_native_delete(worker)


# The one and only connect() for these three signals, for the life of
# the process — see _Dispatcher's own docstring for why this is the
# real fix rather than a per-task connect/disconnect cycle.
_dispatcher.task_finished.connect(_handle_task_finished)
_dispatcher.task_error.connect(_handle_task_error)
_dispatcher.task_progress.connect(_handle_task_progress)


def run_worker(
        pool: QThreadPool,
        fn: Callable[[], Any] | Callable[[Callable[[str, int, int], None]], Any],
        button: QAbstractButton | None = None,
        status_label: QLabel | None = None,
        on_finished: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_progress: Callable[[str, int, int], None] | None = None,
) -> Worker:
    """Submit fn to run in the background. The triggering button (if
    any) disables for the duration and re-enables on completion either
    way; an error clears to the status line rather than a modal dialog.
    `on_error` is for callers that need to react to a failure beyond the
    status line (e.g. clearing an in-progress flag) — optional, and
    additive to the status-label behavior, not a replacement for it.

    `on_progress` (roadmap item 65, Phase 2.3) is optional and defaults
    to today's behavior for every existing call site — when omitted, `fn`
    is called exactly as before, with zero arguments. When given, `fn`
    is instead called with ONE argument: a `report(stage, current,
    total)` callable it can call as often as it likes — throttling
    happens inside `Worker._report_progress` itself (see
    PROGRESS_EMIT_MIN_INTERVAL_S/PROGRESS_EMIT_EVERY_N above), so `fn`
    never needs to rate-limit its own calls. `on_progress` itself is
    invoked on the MAIN thread, same as `on_finished`/`on_error`.

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

    worker = Worker(fn, wants_progress=on_progress is not None)
    _callbacks[worker.task_id] = (
            worker,
            button,
            status_label,
            on_finished,
            on_error,
    )

    if on_progress is not None:
        _progress_callbacks[worker.task_id] = on_progress

    pool.start(worker)

    return worker

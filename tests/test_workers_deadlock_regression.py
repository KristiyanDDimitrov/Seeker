"""Regression test for a real, reproducible deadlock in
ui/workers.py's cross-thread signal handling (roadmap item 39 — see
CLAUDE.md's Known Issues entry, now fixed, and docs/HISTORY.md item
39 for the full investigation).

Root cause, confirmed via `sample`-profiling a genuinely stuck process:
Qt's own connect()/disconnect()/emit() bookkeeping is guarded by a
striped pool of mutexes keyed by object address
(`QObjectPrivate::signalSlotLock`, backed by `QMutexPool`). The
original per-task design created a fresh `WorkerSignals` QObject and
called connect()/disconnect() on it for every single background task —
under enough concurrent load (many QMainWindow/widget constructions
interleaved with many `run_worker()` calls, no explicit event-loop
processing in between — the real condition this project's own UI test
suite exercises), a worker thread mid-`.emit()` (holding a mutex-pool
slot, waiting on the GIL to safely marshal the result into a queued
event) could deadlock against the main thread mid-`connect()`/
`disconnect()` (holding the GIL, waiting for that same mutex-pool
slot). Fixed by routing every worker through one shared, permanently-
connected dispatcher instead (see workers.py's own `_Dispatcher`
docstring for the full story, including why a `threading.RLock`
around the same calls was tried first and confirmed NOT to fully close
the hazard).

The failure mode is a literal, unrecoverable process freeze — not an
exception, not a slow test — so this file NEVER runs the repro
in-process. Each trial is a real, separate subprocess with a hard
wall-clock timeout; a regression here times out that one subprocess
rather than hanging the whole test suite.

Confirmed live, before this test existed (docs/HISTORY.md item 39):
at this exact stress level, the pre-fix design hung 43/50 trials
(86%); the fixed design passed 50/50, and 20/20 at nearly 4x the
stress level. A single failure here means the deadlock (or a crash)
is back — treat it as a P0 regression, not a flaky test to retry.
"""
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
DEADLOCK_REPRO = TESTS_DIR / "_workers_deadlock_repro.py"
CORRECTNESS_REPRO = TESTS_DIR / "_workers_correctness_repro.py"
TEARDOWN_RACE_REPRO = TESTS_DIR / "_workers_teardown_race_repro.py"

# Matches the exact stress level confirmed live to hang the pre-fix
# design 43/50 times (see module docstring) -- not tuned down for
# speed, since a weaker stress level would be a weaker regression
# guard.
DEADLOCK_TRIALS = 50
DEADLOCK_ITERATIONS_PER_TRIAL = 400
DEADLOCK_TRIAL_TIMEOUT_SECONDS = 8.0


def _run_deadlock_trial() -> str:
    try:
        result = subprocess.run(
            [sys.executable, str(DEADLOCK_REPRO), str(DEADLOCK_ITERATIONS_PER_TRIAL)],
            capture_output=True,
            text=True,
            timeout=DEADLOCK_TRIAL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "timeout"

    if result.returncode != 0:
        return f"crash(code={result.returncode}, stderr={result.stderr[-500:]!r})"

    if "DONE" not in result.stdout:
        return f"incomplete(stdout={result.stdout[-500:]!r})"

    return "ok"


def test_run_worker_does_not_deadlock_under_concurrent_construction():
    outcomes = [_run_deadlock_trial() for _ in range(DEADLOCK_TRIALS)]
    failures = [outcome for outcome in outcomes if outcome != "ok"]

    assert not failures, (
        f"{len(failures)}/{DEADLOCK_TRIALS} trials failed: {failures}\n"
        "This is the ui/workers.py Qt-mutex/GIL deadlock (or a related "
        "crash) regressing -- see CLAUDE.md/docs/HISTORY.md item 39. "
        "Do not retry/skip this; find what reintroduced per-task "
        "connect()/disconnect() (or an equivalent hazard) instead."
    )


def test_run_worker_delivers_correct_results_under_concurrency():
    # A separate concern from the deadlock above: the shared-dispatcher
    # redesign must still route each task's own result/error to its
    # own callback, not just avoid hanging. Also subprocess-isolated,
    # for the same "the failure mode could itself hang" reasoning.
    result = subprocess.run(
        [sys.executable, str(CORRECTNESS_REPRO), "800"],
        capture_output=True,
        text=True,
        timeout=20.0,
    )

    assert result.returncode == 0, (
        f"correctness repro failed: stdout={result.stdout!r} "
        f"stderr={result.stderr[-2000:]!r}"
    )
    assert "OK:" in result.stdout


def test_worker_run_survives_dispatcher_torn_down_around_the_emit():
    # CLAUDE.md item 42: closes a loose end in item 41's own fix -- a
    # `Shiboken.isValid(_dispatcher)` check before the dispatcher emit
    # is check-then-act, not atomic, and there's a real gap between the
    # check and the `.emit()` call itself where teardown can land.
    # Measured live before the real fix (`_emit_or_drop` in
    # workers.py): forcing deletion into that exact gap escaped an
    # uncaught RuntimeError in 50/50 trials against the pre-fix code --
    # not a rare theoretical race. See _workers_teardown_race_repro.py's
    # own docstring for the full mechanism and why this is deterministic
    # rather than relying on incidental thread-scheduling luck.
    result = subprocess.run(
        [sys.executable, str(TEARDOWN_RACE_REPRO), str(DEADLOCK_TRIALS)],
        capture_output=True,
        text=True,
        timeout=30.0,
    )

    assert result.returncode == 0, (
        f"teardown-race repro failed: stdout={result.stdout!r} "
        f"stderr={result.stderr[-2000:]!r}\n"
        "This is the ui/workers.py check-then-act dispatcher-teardown "
        "race regressing -- see CLAUDE.md item 42. Do not retry/skip "
        "this; find whatever reintroduced a validity check ahead of "
        "the dispatcher emit (rather than wrapping the emit itself)."
    )
    assert "RESULT already_dead_escapes=0/" in result.stdout, result.stdout
    assert "check_then_act_escapes=0/" in result.stdout, result.stdout

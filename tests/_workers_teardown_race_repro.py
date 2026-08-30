"""Standalone, deterministic repro closing a loose end in item 41's own
fix (CLAUDE.md item 42) -- run only as a subprocess by
test_workers_deadlock_regression.py, for the same reason every other
script in this directory is: the failure mode this hunts for is a
background thread raising into whatever Qt/CPython is doing mid-
shutdown, which this project's own history (docs/HISTORY.md items 39
and 41) has already seen turn into a segfault once, not just a clean
traceback -- a subprocess-per-run() means a regression here fails loud
rather than taking the whole test runner down with it.

Item 41 fixed a real bug (an uncaught `RuntimeError: Signal source has
been deleted` escaping `Worker.run()` when `_dispatcher`'s native
QObject was already gone) with a `Shiboken.isValid(_dispatcher)` check
before the emit. That's check-then-act, not atomic -- there is a real
gap between the check returning True and the following `.emit()` call
where teardown can land. Deterministic, not incidental: rather than
relying on real thread scheduling to occasionally land teardown in
that gap (the same mistake item 39's own aborted `threading.RLock`
attempt made -- "reduces the failure rate" isn't "fixed" until it's
forced under real adversarial timing, repeatedly), this FORCES it,
every trial:

Measured live before writing the real fix (`_emit_or_drop` in
workers.py, CLAUDE.md item 42): forcing a real `shiboken6.Shiboken.
delete(_dispatcher)` to land in that exact gap (via a monkeypatched
`Shiboken.isValid` that deletes the dispatcher the moment it confirms
validity, then returns True) escaped an uncaught `RuntimeError` in
50/50 trials against the pre-fix, check-then-act code -- not a rare
theoretical race.

Two scenarios, run TRIALS times each against whatever `Worker.run()`
currently does:

1. `already_dead` -- `_dispatcher`'s native QObject is torn down for
   the ENTIRE duration of `Worker.run()`. This is the shape the CURRENT
   `_emit_or_drop`-based fix is actually exposed to (it makes no
   separate validity check for teardown to land "after" -- see
   `_emit_or_drop`'s own docstring) and the shape a real straggling
   worker hits in production (window close, interpreter shutdown).
2. `check_then_act` -- if `Worker.run()`'s code path ever calls
   `shiboken6.Shiboken.isValid(_dispatcher)` again (it doesn't today,
   but a future "simplification" could reintroduce exactly this
   pattern), this forces teardown into the exact gap between that call
   returning True and the following statement. `hook_fires` is reported
   separately so a run where nothing calls `isValid` anymore (true
   today) reads honestly as "not applicable," not a false pass.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from seeker.ui import workers  # noqa: E402

TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def _fresh_dispatcher() -> "workers._Dispatcher":
    disp = workers._Dispatcher()
    workers._dispatcher = disp
    return disp


def _run_already_dead_trial() -> Exception | None:
    disp = _fresh_dispatcher()
    shiboken6.Shiboken.delete(disp)

    worker = workers.Worker(lambda: "ok")
    try:
        worker.run()
    except Exception as exc:
        return exc
    return None


def _run_check_then_act_trial() -> tuple[Exception | None, bool]:
    disp = _fresh_dispatcher()
    real_is_valid = shiboken6.Shiboken.isValid
    hook_fired = False

    def forced_is_valid(obj: object) -> bool:
        nonlocal hook_fired
        if obj is disp:
            hook_fired = True
            if real_is_valid(disp):
                shiboken6.Shiboken.delete(disp)
            return True
        return bool(real_is_valid(obj))

    shiboken6.Shiboken.isValid = forced_is_valid  # type: ignore[assignment]
    try:
        worker = workers.Worker(lambda: "ok")
        try:
            worker.run()
        except Exception as exc:
            return exc, hook_fired
        return None, hook_fired
    finally:
        shiboken6.Shiboken.isValid = real_is_valid


def main() -> None:
    QApplication.instance() or QApplication([])

    already_dead_escapes = 0
    for _ in range(TRIALS):
        exc = _run_already_dead_trial()
        if exc is not None:
            already_dead_escapes += 1
            print(f"ALREADY-DEAD ESCAPE: {type(exc).__name__}: {exc}", file=sys.stderr)

    check_then_act_escapes = 0
    check_then_act_hook_fires = 0
    for _ in range(TRIALS):
        exc, fired = _run_check_then_act_trial()
        if fired:
            check_then_act_hook_fires += 1
        if exc is not None:
            check_then_act_escapes += 1
            print(f"CHECK-THEN-ACT ESCAPE: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(
        f"RESULT already_dead_escapes={already_dead_escapes}/{TRIALS} "
        f"check_then_act_escapes={check_then_act_escapes}/{TRIALS} "
        f"check_then_act_hook_fires={check_then_act_hook_fires}/{TRIALS}",
        flush=True,
    )
    sys.exit(0 if already_dead_escapes == 0 and check_then_act_escapes == 0 else 1)


if __name__ == "__main__":
    main()

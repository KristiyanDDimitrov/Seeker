"""Standalone script confirming run_worker() delivers each task's own
result to its own callback correctly under real concurrency — not just
"doesn't deadlock" but functionally correct. Run only as a subprocess
by test_workers_deadlock_regression.py (see that file and
_workers_deadlock_repro.py's own docstring for why a subprocess).
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from seeker.ui.workers import run_worker

N = int(sys.argv[1]) if len(sys.argv) > 1 else 500
# Every 97th task deliberately raises, to confirm on_error() is routed
# just as correctly as on_finished() under the same concurrent load.
ERROR_EVERY = 97


def main() -> None:
    app = QApplication.instance() or QApplication([])
    pool = QThreadPool()
    pool.setMaxThreadCount(16)

    received: list[int] = []
    errors: list[str] = []

    def make_task(i: int):
        if i % ERROR_EVERY == 0:
            def task() -> int:
                raise ValueError(f"deliberate-error-{i}")
            return task

        def task() -> int:
            return i

        return task

    def make_on_finished(i: int):
        def on_finished(result: object) -> None:
            assert result == i, f"expected {i}, got {result}"
            received.append(i)
        return on_finished

    def make_on_error(i: int):
        def on_error(message: str) -> None:
            assert message == f"deliberate-error-{i}", (i, message)
            errors.append(message)
        return on_error

    for i in range(N):
        run_worker(
            pool, make_task(i),
            on_finished=make_on_finished(i), on_error=make_on_error(i),
        )

    pool.waitForDone(15_000)

    # waitForDone() only waits for run() to return (i.e. emit() to have
    # been called) -- it does not pump the main thread's event loop,
    # which is what actually delivers the queued cross-thread signal.
    deadline = time.time() + 15
    while len(received) + len(errors) < N and time.time() < deadline:
        app.processEvents()

    expected_ok = [i for i in range(N) if i % ERROR_EVERY != 0]
    expected_err = [i for i in range(N) if i % ERROR_EVERY == 0]

    assert sorted(received) == expected_ok, (
        f"missing={set(expected_ok) - set(received)} "
        f"extra={set(received) - set(expected_ok)}"
    )
    assert len(errors) == len(expected_err), (len(errors), len(expected_err))

    print(
        f"OK: {len(received)} correct results, {len(errors)} correct "
        f"errors",
        flush=True,
    )


if __name__ == "__main__":
    main()

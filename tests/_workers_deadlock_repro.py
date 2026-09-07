"""Standalone repro script for the real ui/workers.py Qt-mutex/GIL
deadlock (roadmap item 39, see CLAUDE.md/docs/HISTORY.md). Not a test
module itself (leading underscore — pytest's default `test_*.py`
collection pattern skips it); run only as a subprocess by
test_workers_deadlock_regression.py, which needs a hard wall-clock
timeout around each real, separate process since the actual failure
mode is a literal, unrecoverable freeze.

Confirmed live (see docs/HISTORY.md item 39) that just this — many
`QMainWindow`+widget constructions interleaved with real `run_worker()`
calls, with no explicit event-loop processing in between — is
sufficient to reproduce the real deadlock reliably against the
pre-fix design (a fresh per-task QObject connected/disconnected on
every call): 43/50 trials hung at this exact stress level. No
Application/DB layer is needed; the hazard lives entirely in Qt/
widget-construction + ui/workers.py.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QToolBar,
)

from seeker.ui.workers import run_worker

ITERATIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 400


def _fast_task() -> int:
    return 1


def _build_window_with_worker(pool: QThreadPool) -> QMainWindow:
    win = QMainWindow()
    toolbar = QToolBar("Actions")
    win.addToolBar(toolbar)

    for i in range(4):
        button = QPushButton(f"button{i}")
        button.clicked.connect(lambda: None)
        toolbar.addWidget(button)

    run_worker(pool, _fast_task)
    run_worker(pool, _fast_task)

    return win


def main() -> None:
    app = QApplication.instance() or QApplication([])
    pool = QThreadPool()
    pool.setMaxThreadCount(16)

    windows = [_build_window_with_worker(pool) for _ in range(ITERATIONS)]

    pool.waitForDone(10_000)
    print(f"DONE ({len(windows)} windows)", flush=True)


if __name__ == "__main__":
    main()

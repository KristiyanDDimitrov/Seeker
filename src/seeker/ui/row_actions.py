"""Per-row actions whose row a rebuild can delete while they run.

A table that rebuilds on a poll or a new search deletes the buttons a
running action was started from. `run_worker`'s `button=` would
re-enable only the deleted one and leave the rebuilt row's new button
enabled, so a second click starts the same action again: a second
download request, a second file move (HISTORY §227). `RunningRows`
keeps the running state by row key instead, apart from any widget: a
row built while its key runs gets its buttons disabled, and every
button bound to the key, old or rebuilt, is re-enabled when it ends.
"""

from collections.abc import Callable, Hashable
from typing import Any

import shiboken6
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QAbstractButton, QLabel

from seeker.ui.workers import run_worker


class RunningRows[K: Hashable]:
    """The row keys of one table whose per-row action is running, and
    the buttons bound to each."""

    def __init__(self) -> None:
        self._buttons: dict[K, list[QAbstractButton]] = {}

    def __contains__(self, key: K) -> bool:
        return key in self._buttons

    def bind(self, key: K, *buttons: QAbstractButton) -> None:
        """For a row being built: disables its buttons while `key`
        runs, and re-enables them when it ends."""
        if key not in self._buttons:
            return

        for button in buttons:
            button.setEnabled(False)
        self._buttons[key].extend(buttons)

    def start(self, key: K, *buttons: QAbstractButton) -> None:
        """Marks `key` running and disables its row's buttons."""
        self._buttons.setdefault(key, [])
        self.bind(key, *buttons)

    def settle(self, key: K) -> None:
        """Marks `key` ended and re-enables every button bound to it
        that no rebuild has deleted."""
        for button in self._buttons.pop(key, []):
            if shiboken6.Shiboken.isValid(button):
                button.setEnabled(True)

    def run(
            self,
            pool: QThreadPool,
            key: K,
            buttons: tuple[QAbstractButton, ...],
            fn: Callable[[], Any],
            *,
            status_label: QLabel | None = None,
            on_finished: Callable[[Any], None] | None = None,
            on_error: Callable[[str], None] | None = None,
    ) -> None:
        """`run_worker` for a row's action: `start`, then `settle`
        before the caller's own handler, on either outcome."""
        self.start(key, *buttons)

        def finished(result: Any) -> None:
            self.settle(key)
            if on_finished is not None:
                on_finished(result)

        def failed(message: str) -> None:
            self.settle(key)
            if on_error is not None:
                on_error(message)

        run_worker(
            pool, fn, status_label=status_label,
            on_finished=finished, on_error=failed,
        )

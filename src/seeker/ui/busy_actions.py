from PySide6.QtWidgets import QAbstractButton


class BusyActionRegistry:
    """Tracks which named, long-running actions are currently in flight,
    so a poll-driven UI refresh (which recomputes button state from
    static facts on a timer, with no idea a run_worker() action might
    currently be mid-flight) can skip a button whose own action is still
    running instead of fighting its busy state.

    The Dashboard's next-step render runs on every 2s poll_timer tick
    and sets the action-row buttons' enabled state; without checking
    is_running() first it would re-enable (or, for Download, hide) a
    button mid-action within 2 seconds of a click, regardless of whether
    the real background work was still running.

    Deliberately kept entirely outside ui/workers.py and its shared
    cross-thread dispatcher — this class holds no signals, does no
    cross-thread work, and is only ever touched from the main thread
    (begin()/end() are both called from ordinary Qt click handlers and
    run_worker() on_finished/on_error callbacks, all main-thread code).
    workers.py's own docstrings document three separate, hard-won
    crash/deadlock fixes around its actual cross-thread machinery — this
    registry doesn't need any of that machinery, so it doesn't touch that
    file at all.
    """

    def __init__(self) -> None:
        self._running: dict[str, tuple[QAbstractButton | None, str]] = {}

    def begin(
            self,
            key: str,
            button: QAbstractButton | None,
            busy_text: str | None = None,
    ) -> None:
        if key in self._running:
            # Already running -- never clobber the stored original text
            # with what's currently showing (which may already be the
            # busy text from this very call).
            return

        if button is None:
            # A background action with no button (the daily sweep):
            # registered only for the activity strip and its own
            # overlap check.
            self._running[key] = (None, "")
            return

        self._running[key] = (button, button.text())
        button.setEnabled(False)

        if busy_text is not None:
            button.setText(busy_text)

    def end(self, key: str) -> None:
        entry = self._running.pop(key, None)

        if entry is None:
            return

        button, original_text = entry

        if button is None:
            return

        button.setText(original_text)
        button.setEnabled(True)

    def is_running(self, key: str) -> bool:
        return key in self._running

    def running_keys(self) -> frozenset[str]:
        return frozenset(self._running)

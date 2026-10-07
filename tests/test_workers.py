"""`ui/workers.py`: `Worker`'s signals and `run_worker`'s button,
status-label, error and progress handling.
"""

from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
)

from seeker.ui import workers as workers_module
from seeker.ui.workers import Worker, run_worker


def test_worker_emits_finished_with_result():
    # Worker no longer owns a per-instance `.signals` object — every
    # worker reports through the one shared, permanently-connected
    # `_dispatcher` (see workers.py's own docstring for why: a fresh
    # per-task QObject+connect()/disconnect() cycle was confirmed live
    # to cause a real, reproducible deadlock). Connect directly to the
    # dispatcher and filter by task_id, the same way _handle_task_finished
    # itself does — the signal carries a plain int, never the Worker
    # instance itself (see Worker's own docstring for why).
    worker = Worker(lambda: 42)
    results = []

    def on_finished(task_id: int, result: object) -> None:
        if task_id == worker.task_id:
            results.append(result)

    # Disconnected in finally — this connects to the one PERMANENT,
    # shared dispatcher, so a test-local connection left dangling would
    # linger for the rest of the process, not just this test.
    workers_module._dispatcher.task_finished.connect(on_finished)
    try:
        worker.run()
    finally:
        workers_module._dispatcher.task_finished.disconnect(on_finished)

    assert results == [42]


def test_worker_emits_error_on_exception():
    def boom():
        raise RuntimeError("simulated failure")

    worker = Worker(boom)
    errors = []

    def on_error(task_id: int, message: str) -> None:
        if task_id == worker.task_id:
            errors.append(message)

    workers_module._dispatcher.task_error.connect(on_error)
    try:
        worker.run()
    finally:
        workers_module._dispatcher.task_error.disconnect(on_error)

    assert errors == ["simulated failure"]


def test_worker_run_logs_the_traceback_on_exception(caplog):
    # §1.3 (round 10, Defect B) — task_error only ever carries
    # str(error); before this fix nothing logged the traceback anywhere,
    # so every failed background task left no trace in seeker.log.
    def boom():
        raise RuntimeError("simulated failure")

    worker = Worker(boom)

    with caplog.at_level("WARNING", logger="seeker.ui.workers"):
        worker.run()

    assert "simulated failure" in caplog.text
    assert "Traceback" in caplog.text


def test_run_worker_disables_button_while_running_and_reenables(qtbot):
    button = QPushButton("Go")
    qtbot.addWidget(button)

    button_state_during_run = []

    class SynchronousPool:
        def start(self, worker):
            button_state_during_run.append(button.isEnabled())
            worker.run()

    run_worker(SynchronousPool(), lambda: "done", button=button)

    assert button_state_during_run == [False]
    assert button.isEnabled() is True


def test_run_worker_error_sets_status_label_and_reenables_button(qtbot):

    button = QPushButton("Go")
    label = QLabel("")
    qtbot.addWidget(button)
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise RuntimeError("real failure text")

    run_worker(SynchronousPool(), boom, button=button, status_label=label)

    assert label.text() == "real failure text"
    assert button.isEnabled() is True


def test_run_worker_error_shows_readable_text_for_a_connection_error(qtbot):
    # A transport error's own text is `[Errno 61] Connection refused`;
    # the label must say which service and what to do instead.
    import httpx

    label = QLabel("")
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise httpx.ConnectError(
            "[Errno 61] Connection refused",
            request=httpx.Request("GET", "http://127.0.0.1:5030/api/v0/x"),
        )

    run_worker(SynchronousPool(), boom, status_label=label)

    assert "Errno" not in label.text()
    assert "slskd" in label.text()


def test_run_worker_error_names_a_bare_assertion_error(qtbot):
    # str(AssertionError()) is "" — the label must not go blank.

    label = QLabel("")
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise AssertionError

    run_worker(SynchronousPool(), boom, status_label=label)

    assert "AssertionError" in label.text()
    assert "Open log folder" in label.text()


def test_run_worker_registry_releases_worker_on_both_success_and_error():
    # _callbacks (see workers.py's own comment) holds each in-flight
    # task's callback entry, keyed by task_id, until that task's own
    # completion pops it — if cleanup only fired on the success path, a
    # worker that raises would stay referenced forever, a real leak on
    # every failed sync/scan/match/download. Asserted directly against
    # the registry itself, not just inferred from button/label side
    # effects.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    run_worker(SynchronousPool(), lambda: "ok")
    assert len(workers_module._callbacks) == baseline

    def boom():
        raise RuntimeError("simulated failure")

    run_worker(SynchronousPool(), boom)
    assert len(workers_module._callbacks) == baseline


def test_run_worker_on_finished_exception_does_not_propagate(qtbot):
    # A bug in a render/completion callback (not the fetch itself) must
    # not escape run_worker uncontrolled — confirmed live this doesn't
    # crash the app or stop the triggering QTimer either way, but
    # nothing in this codebase's own code caught it before this fix;
    # only PySide6's own default exception hook did, an implicit safety
    # net rather than an intentional one.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    # Must not raise out of this call.
    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)


def test_run_worker_on_finished_exception_surfaces_to_status_label(qtbot):

    label = QLabel("")
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(
        SynchronousPool(),
        lambda: "ok",
        status_label=label,
        on_finished=render_that_raises,
    )

    # The render bug's own text is for the log, not the user.
    assert "malformed render data" not in label.text()
    assert label.text().startswith("Couldn't display the result")


def test_run_worker_on_finished_exception_without_status_label_still_safe(
        qtbot
):
    # The periodic-poll shape (e.g. the Downloads/Review tabs' 2s
    # refresh) — no status_label wired at all, by design, so a fetch
    # error doesn't flash a noisy message every tick. A render bug must
    # still not propagate even here.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)


def test_run_worker_on_error_exception_does_not_propagate(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise RuntimeError("fetch failed")

    def on_error_that_raises(message):
        raise ValueError("bug in on_error handling")

    # Must not raise out of this call either.
    run_worker(SynchronousPool(), boom, on_error=on_error_that_raises)


def test_run_worker_on_finished_exception_still_releases_worker_registry(
        qtbot
):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)

    assert len(workers_module._callbacks) == baseline


# --- Progress channel (roadmap item 65, Phase 2.3) --------------------

def test_run_worker_without_on_progress_calls_fn_with_zero_arguments(qtbot):
    # Backward-compat guarantee: every pre-existing call site's fn stays
    # exactly zero-argument when on_progress isn't passed.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    calls = []
    run_worker(SynchronousPool(), lambda: calls.append("called") or "ok")

    assert calls == ["called"]


def test_run_worker_with_on_progress_passes_fn_a_reporter(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    reported = []

    def do_work(report):
        report("stage one", 1, 10)
        return "ok"

    def on_progress(stage, current, total):
        reported.append((stage, current, total))

    run_worker(SynchronousPool(), do_work, on_progress=on_progress)

    assert reported == [("stage one", 1, 10)]


def test_progress_reports_are_throttled_by_count(qtbot):
    # PROGRESS_EMIT_EVERY_N = 25 — 100 calls should emit at multiples of
    # 25 (the count-based branch fires regardless of elapsed time, since
    # these calls all happen well under PROGRESS_EMIT_MIN_INTERVAL_S),
    # PLUS the very first call (i=1), which always emits regardless of
    # count/elapsed — see Worker.__init__'s own comment on why.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    reported = []

    def do_work(report):
        for i in range(1, 101):
            report("stage", i, 100)
        return "ok"

    run_worker(
        SynchronousPool(), do_work,
        on_progress=lambda stage, current, total: reported.append(current),
    )

    assert reported == [1, 25, 50, 75, 100]


def test_progress_reports_are_throttled_by_time(qtbot, monkeypatch):
    from seeker.ui import workers as workers_mod

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    fake_time = [0.0]
    monkeypatch.setattr(workers_mod.time, "monotonic", lambda: fake_time[0])

    reported = []

    def do_work(report):
        report("a", 1, 10)   # always emits (first report)
        fake_time[0] += 0.1  # under PROGRESS_EMIT_MIN_INTERVAL_S -> dropped
        report("b", 2, 10)
        fake_time[0] += 0.3  # over the interval -> emits
        report("c", 3, 10)
        return "ok"

    run_worker(
        SynchronousPool(), do_work,
        on_progress=lambda stage, current, total: reported.append(stage),
    )

    assert reported == ["a", "c"]


def test_progress_callback_is_cleared_on_finish(qtbot):
    from seeker.ui import workers as workers_mod

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    worker = run_worker(
        SynchronousPool(), lambda report: "ok",
        on_progress=lambda stage, current, total: None,
    )

    assert worker.task_id not in workers_mod._progress_callbacks


def test_progress_callback_is_cleared_on_error(qtbot):
    from seeker.ui import workers as workers_mod

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom(report):
        raise RuntimeError("simulated failure")

    worker = run_worker(
        SynchronousPool(), boom,
        on_progress=lambda stage, current, total: None,
    )

    assert worker.task_id not in workers_mod._progress_callbacks

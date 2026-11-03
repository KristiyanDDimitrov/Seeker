"""Source sweeps over the tests' own waits: an idiom that cannot tell
its flow's workers from anyone else's, and a bound sized on a faster
machine than the one that runs it. See HISTORY §265.
"""
import ast
from pathlib import Path

import pytest

from fakes import WAIT_MS

_TESTS_DIR = Path(__file__).parent


def _wait_until_calls() -> list[tuple[str, ast.Call]]:
    """Every `<anything>.waitUntil(<condition>, ...)` in the tests."""
    calls = []

    for path in sorted(_TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        label = str(path.relative_to(_TESTS_DIR))

        for node in ast.walk(tree):
            if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "waitUntil"
                    and node.args
            ):
                calls.append((label, node))

    return calls


def test_the_sweep_sees_the_suites_waits():
    # A rename of `waitUntil`, or a moved tests folder, would leave the
    # sweep below passing over nothing.
    assert len(_wait_until_calls()) > 100


def test_no_wait_reads_the_global_worker_registry():
    # `workers._callbacks` holds every in-flight task of the process, so
    # a wait on its size compares a count that unrelated workers move
    # (and that a handler's own follow-up worker moves too) with one
    # taken before the flow began: `test_quit_stops_the_wait_for_a_new_
    # share` timed out on the Intel runner this way. A flow's end is its
    # window's own pool going idle (`fakes.settle_workers`) or the
    # outcome the flow produces on a widget.
    #
    # Only `waitUntil` is inspected. `test_stress_e2e.py` drains the
    # registry through its own `_pump` to an absolute 0 for the whole
    # process, which is neither baseline-relative nor part of the
    # default run (`requires_stress_opt_in`), so it cannot hide this
    # bug; a wait spelled any other way is not what failed.
    offenders = []

    for label, call in _wait_until_calls():
        mentioned = {
            *(n.attr for n in ast.walk(call.args[0])
              if isinstance(n, ast.Attribute)),
            *(n.id for n in ast.walk(call.args[0])
              if isinstance(n, ast.Name)),
        }

        if "_callbacks" in mentioned:
            offenders.append(f"{label}:{call.lineno}")

    assert not offenders, (
        "wait on the flow's own outcome or `fakes.settle_workers`, "
        f"never the global worker count: {offenders}"
    )


# Every wait that returns as soon as its condition holds, so that its
# bound is only a ceiling: pytest-qt's (`timeout=`, keyword-only) and
# `QThreadPool.waitForDone` (the first argument). Not here: fixed
# delays (`qtbot.wait`), which a longer bound would make every run pay,
# and `assertNotEmitted`, which passes only by waiting out its `wait`.
_CEILING_WAITS = {
    "waitUntil", "waitSignal", "waitSignals", "waitCallback",
    "waitExposed", "waitActive", "waitForDone",
    # pytest-qt's PEP 8 aliases, which `QtBot.__init__` sets (4.5.0).
    "wait_until", "wait_signal", "wait_signals", "wait_callback",
    "wait_exposed", "wait_active",
    # Deprecated, and takes no bound (Qt's own 5 s), so it always
    # fails: `waitExposed(widget, timeout=WAIT_MS)` replaces it.
    "waitForWindowShown", "wait_for_window_shown",
}

# Subprocess scripts run as `python <script>`, outside pytest's import
# path, so they cannot import `fakes`. Their literal bounds are held to
# at least `WAIT_MS` instead, which cannot hide a short one.
_STANDALONE_DIR = "repro"


def _bound_of(call: ast.Call) -> ast.expr | None:
    if call.func.attr == "waitForDone":
        return call.args[0] if call.args else None

    return next(
        (k.value for k in call.keywords if k.arg == "timeout"), None,
    )


def _wait_ms_bindings(tree: ast.Module) -> list[ast.AST]:
    """Every node in `tree` that binds the name `WAIT_MS`: an
    assignment or loop target, a parameter, an import, an `except …
    as`, a `match` capture, a `def` or a `class`."""
    found = []

    for node in ast.walk(tree):
        match node:
            case ast.Name(ctx=ast.Store()):
                name = node.id
            case ast.arg():
                name = node.arg
            case ast.alias():
                name = node.asname or node.name.partition(".")[0]
            case (
                    ast.ExceptHandler() | ast.MatchAs() | ast.MatchStar()
                    | ast.FunctionDef() | ast.AsyncFunctionDef()
                    | ast.ClassDef()
            ):
                name = node.name
            case ast.MatchMapping():
                name = node.rest
            case _:
                continue

        if name == "WAIT_MS":
            found.append(node)

    return found


def _wait_ms_comes_from_fakes(tree: ast.Module) -> bool:
    """Its one binding is a module-level `from fakes import WAIT_MS`."""
    bindings = _wait_ms_bindings(tree)
    from_fakes = [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "fakes" and node.level == 0
        for alias in node.names
    ]

    return len(bindings) == 1 and any(bindings[0] is a for a in from_fakes)


def _wait_ms_is_defined_once(tree: ast.Module) -> bool:
    """`fakes.py`'s own: one binding, a module-level assignment."""
    bindings = _wait_ms_bindings(tree)

    return len(bindings) == 1 and any(
        isinstance(node, ast.Assign)
        and any(target is bindings[0] for target in node.targets)
        for node in tree.body
    )


def _is_wait_by_name(node: ast.AST) -> bool:
    """`getattr(<anything>, "<a ceiling wait>")`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in _CEILING_WAITS
    )


def _ceiling_waits() -> list[tuple[Path, ast.Module, ast.Call]]:
    found = []

    for path in sorted(_TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))

        for node in ast.walk(tree):
            if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _CEILING_WAITS
            ):
                found.append((path, tree, node))

    return found


def test_the_bound_sweep_sees_every_kind_of_wait():
    # A rename, or a moved tests folder, would leave the sweep below
    # passing over nothing.
    kinds = {call.func.attr for _, _, call in _ceiling_waits()}

    assert {"waitUntil", "waitSignal", "waitExposed", "waitForDone"} <= kinds


def _kind_of(path: Path) -> str:
    """"fakes" (where `WAIT_MS` is defined), "standalone" (a subprocess
    script) or "test"."""
    if path.parent.name == _STANDALONE_DIR:
        return "standalone"

    return "fakes" if path.name == "fakes.py" else "test"


def _bound_offenders(tree: ast.Module, kind: str) -> list[str]:
    """The line of each ceiling wait in `tree` bounded by anything but
    `WAIT_MS` from `fakes`, with why when it is not plain.

    A wait is checked where it is called, so one reached any other way
    (an alias, `functools.partial`, `getattr`) fails: its bound is out of
    sight. Assigning one (`pool.waitForDone = fake`) is not a wait."""
    offenders = []
    called = {
        id(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)
    }

    for node in ast.walk(tree):
        if _is_wait_by_name(node) or (
                isinstance(node, ast.Attribute)
                and node.attr in _CEILING_WAITS
                and isinstance(node.ctx, ast.Load)
                and id(node) not in called
        ):
            offenders.append(f"{node.lineno} (not called directly)")
            continue

        if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _CEILING_WAITS
        ):
            continue

        bound = _bound_of(node)

        if kind == "standalone":
            if not (
                    isinstance(bound, ast.Constant)
                    and isinstance(bound.value, int)
                    and bound.value >= WAIT_MS
            ):
                offenders.append(f"{node.lineno} (below WAIT_MS)")
        elif not (isinstance(bound, ast.Name) and bound.id == "WAIT_MS"):
            offenders.append(f"{node.lineno}")
        elif kind == "test" and not _wait_ms_comes_from_fakes(tree):
            offenders.append(f"{node.lineno} (WAIT_MS not from fakes)")
        elif kind == "fakes" and not _wait_ms_is_defined_once(tree):
            offenders.append(f"{node.lineno} (WAIT_MS bound again)")

    return offenders


def test_every_wait_is_bounded_by_the_named_bound():
    # The Intel runner is 5 to 10 times slower than the Apple silicon
    # Mac on UI work, so a bound picked locally (2000 ms, or pytest-qt's
    # 5000 ms default) times out there on a wait that is merely slow.
    # One named bound, `fakes.WAIT_MS`, sized from measurements, is the
    # only ceiling a wait may have. See HISTORY §265.
    offenders = []

    for path in sorted(_TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        label = path.relative_to(_TESTS_DIR)
        offenders += [
            f"{label}:{offender}"
            for offender in _bound_offenders(tree, _kind_of(path))
        ]

    assert not offenders, (
        "bound every wait by `fakes.WAIT_MS` (`timeout=WAIT_MS`, "
        f"`waitForDone(WAIT_MS)`): {offenders}"
    )


_FROM_FAKES = "from fakes import WAIT_MS\n"


def test_the_bound_sweep_passes_the_named_bound():
    source = _FROM_FAKES + (
        "qtbot.waitUntil(cond, timeout=WAIT_MS)\n"
        "qtbot.wait_until(cond, timeout=WAIT_MS)\n"
        "with qtbot.waitSignal(signal, timeout=WAIT_MS):\n"
        "    pass\n"
        "assert pool.waitForDone(WAIT_MS)\n"
    )

    assert _bound_offenders(ast.parse(source), "test") == []


@pytest.mark.parametrize("evasion", [
    # pytest-qt's PEP 8 aliases, set in `QtBot.__init__`.
    "qtbot.wait_until(cond, timeout=200)",
    "qtbot.wait_signal(signal)",
    "qtbot.wait_signals([signal], timeout=200)",
    "qtbot.wait_exposed(widget)",
    "qtbot.wait_active(widget)",
    "qtbot.wait_callback(timeout=200)",
    # Deprecated, and takes no bound: Qt's own 5 s.
    "qtbot.waitForWindowShown(widget)",
    "qtbot.wait_for_window_shown(widget)",
    # A wait reached other than as the called attribute.
    "wait = qtbot.waitUntil\nwait(cond, timeout=200)",
    "functools.partial(qtbot.waitUntil, timeout=200)(cond)",
    "getattr(qtbot, 'waitUntil')(cond, timeout=200)",
    # `WAIT_MS` bound again, so the name no longer means fakes'.
    "WAIT_MS = 200\nqtbot.waitUntil(cond, timeout=WAIT_MS)",
    "def wait(qtbot, WAIT_MS=200):\n"
    "    qtbot.waitUntil(cond, timeout=WAIT_MS)",
    "wait = lambda WAIT_MS=200: qtbot.waitUntil(cond, timeout=WAIT_MS)",
    "from timing import SHORT as WAIT_MS\n"
    "qtbot.waitUntil(cond, timeout=WAIT_MS)",
    "try:\n    pass\nexcept Exception as WAIT_MS:\n"
    "    qtbot.waitUntil(cond, timeout=WAIT_MS)",
    "for WAIT_MS in (200,):\n    qtbot.waitUntil(cond, timeout=WAIT_MS)",
])
def test_the_bound_sweep_fails_each_way_round_it(evasion):
    tree = ast.parse(_FROM_FAKES + evasion)

    assert _bound_offenders(tree, "test")


def test_the_bound_sweep_fails_a_wait_ms_not_taken_from_fakes():
    tree = ast.parse("qtbot.waitUntil(cond, timeout=WAIT_MS)\n")

    assert _bound_offenders(tree, "test")


def test_the_bound_sweep_fails_fakes_binding_wait_ms_twice():
    defined = "WAIT_MS = 10_000\npool.waitForDone(WAIT_MS)\n"

    assert _bound_offenders(ast.parse(defined), "fakes") == []
    assert _bound_offenders(
        ast.parse(defined + "def wait(WAIT_MS=200):\n    pass\n"), "fakes",
    )

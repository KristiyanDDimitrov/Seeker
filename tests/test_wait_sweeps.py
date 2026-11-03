"""Source sweeps over the tests' own waits: an idiom that cannot tell
its flow's workers from anyone else's. See HISTORY §265.
"""
import ast
from pathlib import Path

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

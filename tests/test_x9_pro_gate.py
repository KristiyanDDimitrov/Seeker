"""`x9_pro_gate.skip_reason`: the X9 Pro tests run only when a run
opts in and the drive is mounted, and without the opt-in nothing asks
about the drive."""
import pytest

from x9_pro_gate import OPT_IN_VARIABLE, skip_reason


def _never_asked():
    raise AssertionError("asked about the drive without the opt-in")


@pytest.mark.parametrize("value", [None, "", "0", "yes"])
def test_without_the_opt_in_the_tests_skip_and_nothing_asks(value):
    environ = {} if value is None else {OPT_IN_VARIABLE: value}

    reason = skip_reason(environ=environ, is_mounted=_never_asked)

    assert reason is not None
    assert f"{OPT_IN_VARIABLE}=1" in reason


def test_with_the_opt_in_an_unmounted_drive_skips():
    assert skip_reason(
        environ={OPT_IN_VARIABLE: "1"}, is_mounted=lambda: False,
    ) == "x9-pro drive not mounted"


def test_with_the_opt_in_a_mounted_drive_runs():
    assert skip_reason(
        environ={OPT_IN_VARIABLE: "1"}, is_mounted=lambda: True,
    ) is None

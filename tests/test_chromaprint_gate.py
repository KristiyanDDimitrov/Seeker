"""The gate for tests that need a real libchromaprint.

A skip on "no library loads" cannot tell a machine without the library
from an Intel lookup bug, so CI sets SEEKER_REQUIRE_CHROMAPRINT=1 and
the same condition then lets the test run and fail.
"""

from chromaprint_gate import REQUIRE_VARIABLE, skip_reason


def test_a_loadable_library_never_skips():
    assert skip_reason(loads=True, environ={}) is None
    assert skip_reason(loads=True, environ={REQUIRE_VARIABLE: "1"}) is None


def test_an_unloadable_library_skips_by_default():
    reason = skip_reason(loads=False, environ={})
    assert reason is not None
    assert "libchromaprint" in reason


def test_a_required_library_that_does_not_load_is_never_skipped():
    assert skip_reason(loads=False, environ={REQUIRE_VARIABLE: "1"}) is None


def test_only_the_value_1_requires_it():
    assert skip_reason(loads=False, environ={REQUIRE_VARIABLE: "0"}) is not None
    assert skip_reason(loads=False, environ={REQUIRE_VARIABLE: ""}) is not None

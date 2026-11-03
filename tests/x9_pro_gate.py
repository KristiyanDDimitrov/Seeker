"""One skip condition for every test that reads the X9 Pro, the
removable drive holding Kris's scanned library.

macOS guards a removable volume as it guards Documents, so a process
reading one may raise a permission prompt (UNVERIFIED for this drive:
the terminals that ran these tests already had access). A bare run
never looks at it, not even to see whether it is mounted; a run that
should read it sets `SEEKER_RUN_X9_PRO_TESTS=1`, and the tests then run
when the drive is mounted.
"""

import os
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

X9_PRO_ROOT = Path("/Volumes/X9 Pro")
OPT_IN_VARIABLE = "SEEKER_RUN_X9_PRO_TESTS"


def skip_reason(
        *, environ: Mapping[str, str], is_mounted: Callable[[], bool],
) -> str | None:
    """Why an X9 Pro test is skipped, or None to run it. Asks whether
    the drive is mounted only once the run has opted in."""
    if environ.get(OPT_IN_VARIABLE) != "1":
        return (
            "reads the X9 Pro, a removable volume; set "
            f"{OPT_IN_VARIABLE}=1 to run"
        )
    if not is_mounted():
        return "x9-pro drive not mounted"
    return None


_reason = skip_reason(environ=os.environ, is_mounted=X9_PRO_ROOT.is_dir)

requires_x9_pro = pytest.mark.skipif(_reason is not None, reason=_reason or "")

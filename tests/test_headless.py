"""The suite never reaches the desktop it runs on: its Qt platform is
offscreen unless the caller names another, and conftest refuses the
programs that open things on the desktop."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
PROBE = TESTS / "repro" / "_headless_probe.py"


@pytest.mark.parametrize(
    ("callers_platform", "expected"),
    [(None, "offscreen"), ("minimal", "minimal")],
)
def test_the_suite_is_offscreen_unless_its_caller_names_a_platform(
        tmp_path, callers_platform, expected,
):
    """A bare `pytest` builds its `qapp` offscreen, and a process a
    test starts inherits that; a platform the caller sets (Kris's
    `cocoa`) wins. `minimal` stands in for `cocoa`, which would put
    windows on this desktop. If the default regresses, Qt's
    QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM keeps the probe's
    Cocoa app out of the Dock: observed 2026-11-03, `lsappinfo list`
    showed it as type BackgroundOnly, not Foreground."""
    env = {
        name: value for name, value in os.environ.items()
        if name != "QT_QPA_PLATFORM"
    }
    if callers_platform is not None:
        env["QT_QPA_PLATFORM"] = callers_platform
    env["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] = "1"
    report = tmp_path / "report.json"
    env["SEEKER_HEADLESS_PROBE_REPORT"] = str(report)

    result = subprocess.run(  # noqa: S603 — this interpreter, a fixed probe
        [
            sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
            str(PROBE),
        ],
        cwd=TESTS.parent, env=env, capture_output=True, text=True,
        timeout=120, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "qapp": expected, "child": expected,
    }

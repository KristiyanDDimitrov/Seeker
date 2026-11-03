"""A one-test pytest run that `tests/test_headless.py` starts in a
process of its own, with an environment it chose: reports the platform
the suite's `qapp` was built on, and the `QT_QPA_PLATFORM` a process
the test starts inherits. Not a `test_*.py` file, so the suite itself
never collects it."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_report_the_platform(qapp):
    child = subprocess.run(
        [
            sys.executable, "-c",
            "import os; print(os.environ.get('QT_QPA_PLATFORM', ''))",
        ],
        capture_output=True, text=True, check=True,
    )
    Path(os.environ["SEEKER_HEADLESS_PROBE_REPORT"]).write_text(
        json.dumps({
            "qapp": qapp.platformName(),
            "child": child.stdout.strip(),
        }),
        encoding="utf-8",
    )

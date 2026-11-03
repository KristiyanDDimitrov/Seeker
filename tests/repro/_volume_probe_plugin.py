"""A pytest plugin `tests/test_headless.py` loads into a `--collect-only`
run of the suite in a process of its own: records every path under
`/Volumes` that collecting the suite asks `Path` about, and answers
"absent" without touching the volume. Loaded with `-p` before any test
module is imported, so a module-level skip condition is seen too."""
import json
import os
import pathlib

_VOLUMES = "/Volumes/"
_seen: list[str] = []


def _guard(name):
    real = getattr(pathlib.Path, name)

    def check(self, *args, **kwargs):
        if str(self).startswith(_VOLUMES):
            _seen.append(str(self))
            return False
        return real(self, *args, **kwargs)

    return check


for _name in ("exists", "is_dir", "is_file"):
    setattr(pathlib.Path, _name, _guard(_name))


def pytest_sessionfinish(session):
    pathlib.Path(os.environ["SEEKER_VOLUME_PROBE_REPORT"]).write_text(
        json.dumps(sorted(set(_seen))), encoding="utf-8",
    )

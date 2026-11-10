"""The suite never resolves this machine's own Seeker folders on
Windows. There a moved `HOME` moves none of them: platformdirs builds
Seeker's data, log and cache folders from `CSIDL_LOCAL_APPDATA`, so
conftest points `WIN_PD_OVERRIDE_LOCAL_APPDATA`, which platformdirs
reads first, at a temporary folder for the whole session (HISTORY
§268). Elsewhere a test patches platformdirs or moves `HOME` itself.
"""
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import platformdirs
import pytest
from platformdirs.windows import Windows

OVERRIDE = "WIN_PD_OVERRIDE_LOCAL_APPDATA"

# Seeker's folders, each `platformdirs.<name>("Seeker", appauthor=False)`:
# the database, config, token and slskd's data; the logs; the album art.
_SEEKERS_FOLDERS = ("user_data_dir", "user_log_dir", "user_cache_dir")

_windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="platformdirs reads the override on Windows alone",
)

# A child that prints where platformdirs puts Seeker's data. It imports
# nothing of Seeker's, and platformdirs creates no folder unless asked,
# so it reads and writes nothing.
_PROBE = [
    sys.executable, "-c",
    "import platformdirs; "
    "print(platformdirs.user_data_dir('Seeker', appauthor=False))",
]


def _probe(env):
    return subprocess.run(  # noqa: S603 — this interpreter, a fixed probe
        _PROBE, env=env, capture_output=True, text=True, check=True,
        timeout=30,
    ).stdout.strip()


def test_the_suite_points_local_appdata_at_a_temporary_folder(
        tmp_path_factory,
):
    # On every platform, so the jobs that block a merge see it in place.
    assert Path(os.environ[OVERRIDE]).is_relative_to(
        tmp_path_factory.getbasetemp(),
    )


def test_platformdirs_builds_seekers_windows_folders_on_the_override(
        monkeypatch,
):
    """platformdirs' Windows resolver, which runs here too, puts each of
    Seeker's folders under the override, so the jobs that block a merge
    fail if an upgrade renames it or stops reading it for one of them. A
    drive path: one that is not fully qualified is ignored (platformdirs
    4.14.0)."""
    monkeypatch.setenv(OVERRIDE, r"C:\suite")
    folders = Windows(appname="Seeker", appauthor=False)

    for name in _SEEKERS_FOLDERS:
        folder = PureWindowsPath(getattr(folders, name))
        assert folder.is_relative_to(r"C:\suite"), (name, folder)


@_windows_only
def test_on_windows_seekers_folders_resolve_to_the_temporary_one(
        tmp_path_factory,
):
    basetemp = tmp_path_factory.getbasetemp()

    for name in _SEEKERS_FOLDERS:
        folder = Path(getattr(platformdirs, name)("Seeker", appauthor=False))
        assert folder.is_relative_to(basetemp), (name, folder)


@_windows_only
def test_on_windows_a_child_with_home_moved_resolves_the_temporary_one(
        tmp_path, tmp_path_factory,
):
    """A child started as test_lazy_spotify_config starts its own: the
    suite's environment, with `HOME` moved."""
    folder = Path(_probe({**os.environ, "HOME": str(tmp_path)}))

    assert folder.is_relative_to(tmp_path_factory.getbasetemp())


@_windows_only
def test_on_windows_moving_home_alone_leaves_the_machines_own_folder(
        tmp_path,
):
    """Shows the probe above can tell: without the override, a child
    with `HOME` moved names this machine's own folder, the one the
    suite must never open. It only prints the path."""
    env = {**os.environ, "HOME": str(tmp_path)}
    env.pop(OVERRIDE, None)

    assert Path(_probe(env)) == Path(os.environ["LOCALAPPDATA"]) / "Seeker"

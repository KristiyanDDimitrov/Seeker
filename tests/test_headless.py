"""The suite never reaches the desktop it runs on: its Qt platform is
offscreen unless the caller names another, conftest refuses the
programs that open things on the desktop, and no removable volume is
read unless the run opts in."""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from x9_pro_gate import OPT_IN_VARIABLE

TESTS = Path(__file__).resolve().parent
PROBE = TESTS / "repro" / "_headless_probe.py"
VOLUME_PROBE = TESTS / "repro" / "_volume_probe_plugin.py"
SRC = TESTS.parent / "src" / "seeker"

# Programs src/ spawns that open nothing on the desktop, and what each
# does. conftest refuses every other program src/ spawns.
OPENS_NOTHING = {
    "ffmpeg": "decodes a track to a pipe for its fingerprint",
    "path_helper": "prints the login shell's PATH, to find docker",
}

_SUBPROCESS_SPAWNS = {"run", "Popen", "call", "check_call", "check_output"}
# Spawns whose program the sweep cannot read from a list literal.
_OTHER_SPAWNS = {
    "system", "popen", "startfile", "posix_spawn", "posix_spawnp",
    "execv", "execve", "execvp", "execvpe", "spawnv", "spawnvp",
}


def _commands_src_spawns(
        root: Path,
) -> tuple[list[tuple[str, ...]], list[str]]:
    """Every `subprocess` spawn in the modules under `root`, as the
    literal words its argument list starts with (`("docker",
    "inspect")` for `["docker", "inspect", name, ...]`), and where they
    spawn in a way this sweep cannot read."""
    commands: set[tuple[str, ...]] = set()
    unreadable: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            where = f"{path.relative_to(root)}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Name) and node.id == "QProcess":
                unreadable.append(where)
            if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
            ):
                continue
            module, function = node.func.value.id, node.func.attr
            if module == "os" and function in _OTHER_SPAWNS:
                unreadable.append(where)
            if module != "subprocess" or function not in _SUBPROCESS_SPAWNS:
                continue
            if not (node.args and isinstance(node.args[0], ast.List)):
                unreadable.append(where)
                continue
            words: list[str] = []
            for element in node.args[0].elts:
                if not (
                        isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                ):
                    break
                words.append(element.value)
            if not words:
                unreadable.append(where)
                continue
            commands.add(tuple(words))
    return sorted(commands), unreadable


_SPAWNED, _UNREADABLE = _commands_src_spawns(SRC)
_REFUSED = [
    command for command in _SPAWNED
    if Path(command[0]).name not in OPENS_NOTHING
]


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


def test_collecting_the_suite_looks_at_no_removable_volume(tmp_path):
    """The real-file tests read the X9 Pro, a removable volume, which
    macOS guards as it guards Documents (UNVERIFIED for this drive: the
    terminals that ran them already had access). Without their opt-in,
    collecting the suite asks about no path under /Volumes, not even
    whether the drive is mounted. The probe answers "absent" to any
    such question, so a regression reads nothing either."""
    env = {
        name: value for name, value in os.environ.items()
        if name != OPT_IN_VARIABLE
    }
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(VOLUME_PROBE.parent), env.get("PYTHONPATH")]),
    )
    report = tmp_path / "report.json"
    env["SEEKER_VOLUME_PROBE_REPORT"] = str(report)

    result = subprocess.run(  # noqa: S603 — this interpreter, the suite
        [
            sys.executable, "-m", "pytest", "--collect-only", "-q",
            "-p", "no:cacheprovider", "-p", VOLUME_PROBE.stem, str(TESTS),
        ],
        cwd=TESTS.parent, env=env, capture_output=True, text=True,
        timeout=300, check=False,
    )

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr
    assert json.loads(report.read_text(encoding="utf-8")) == []


def test_the_sweep_reads_every_spawn_in_src():
    """The sweep below sees a program only in a `subprocess` call whose
    argument list starts with literal words; any other spawn would pass
    it unseen. It also finds what src/ is known to spawn, and every
    harmless program it names is still spawned."""
    assert _UNREADABLE == []
    programs = {Path(command[0]).name for command in _SPAWNED}
    assert {"docker", "open", *OPENS_NOTHING} <= programs


def _stand_in(tmp_path, name):
    """An executable `name` that only leaves a mark, so a guard that
    lets it through runs nothing of the desktop's."""
    ran = tmp_path / "ran"
    program = tmp_path / name
    program.write_text(f'#!/bin/sh\n: > "{ran}"\n', encoding="utf-8")
    program.chmod(0o755)
    return program, ran


@pytest.mark.parametrize("command", _REFUSED, ids=" ".join)
def test_the_suite_refuses_every_other_program_src_spawns(
        tmp_path, monkeypatch, command, _docker_attempts, _desktop_attempts,
):
    """Each spawn as src/ makes it, a bare name on PATH, where the only
    program of that name is a stand-in."""
    name = Path(command[0]).name
    _, ran = _stand_in(tmp_path, name)
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(FileNotFoundError):
        subprocess.run(  # noqa: S603 — a stand-in, alone on PATH
            [name, *command[1:]], check=False,
        )

    assert not ran.exists()
    record = _docker_attempts if name == "docker" else _desktop_attempts
    assert record == [" ".join([name, *command[1:]])]
    # Recorded and refused; cleared so this test alone passes.
    record.clear()


def test_the_suite_refuses_the_osascript_webbrowser_opens_through(
        tmp_path, _desktop_attempts,
):
    """On macOS `webbrowser.open` pipes its script to
    `os.popen("/usr/bin/osascript", "w")`, which is `subprocess.Popen`
    with `shell=True` (CPython 3.13.15's webbrowser.py and os.py, read
    2026-11-03). The wizard, Support and the Spotify login call it."""
    program, ran = _stand_in(tmp_path, "osascript")

    with pytest.raises(FileNotFoundError):
        os.popen(str(program), "w")  # noqa: S605 — webbrowser's call, a stand-in

    assert not ran.exists()
    assert _desktop_attempts == [str(program)]
    # Recorded and refused; cleared so this test alone passes.
    _desktop_attempts.clear()

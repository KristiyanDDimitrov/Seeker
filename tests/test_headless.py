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
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

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

# What starts a program, by the module it is reached through. The sweep
# reads the program of a `subprocess` spawn whose argument list starts
# with literal words; every other use of these names is unreadable.
_MODULE_SPAWNS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output"},
    "os": {
        "system", "popen", "startfile", "posix_spawn", "posix_spawnp",
        "execl", "execle", "execlp", "execlpe",
        "execv", "execve", "execvp", "execvpe",
        "spawnl", "spawnle", "spawnlp", "spawnlpe",
        "spawnv", "spawnve", "spawnvp", "spawnvpe",
    },
}
# Names that start a program whatever they are reached through.
_ANY_SPAWNS = {
    "QProcess", "create_subprocess_exec", "create_subprocess_shell",
    "subprocess_exec", "subprocess_shell",
}


def _literal_program(call: ast.Call) -> tuple[str, ...]:
    """The literal words `subprocess.<spawn>([...])`'s argument list
    starts with, up to its first computed element; empty for any other
    call, and for a list that starts computed."""
    function = call.func
    if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "subprocess"
            and function.attr in _MODULE_SPAWNS["subprocess"]
            and call.args
            and isinstance(call.args[0], ast.List)
    ):
        return ()
    words: list[str] = []
    for element in call.args[0].elts:
        if not (
                isinstance(element, ast.Constant)
                and isinstance(element.value, str)
        ):
            break
        words.append(element.value)
    return tuple(words)


def _binds_a_spawn(node: ast.Import | ast.ImportFrom) -> bool:
    """Whether an import puts a spawn, or a module of them, under a
    name the sweep does not follow: `import subprocess as sp`, `from
    subprocess import Popen`, `from os import *`, `from asyncio import
    create_subprocess_exec`. `import subprocess`, `from os import path`
    and `from subprocess import PIPE` bind nothing that starts a
    program."""
    if isinstance(node, ast.Import):
        return any(
            alias.name in _MODULE_SPAWNS
            and alias.asname not in (None, alias.name)
            for alias in node.names
        )
    spawns = _MODULE_SPAWNS.get(node.module or "", set())
    return any(
        alias.name in spawns | _ANY_SPAWNS | _MODULE_SPAWNS.keys()
        or (alias.name == "*" and bool(spawns))
        for alias in node.names
    )


def _commands_src_spawns(
        root: Path,
) -> tuple[list[tuple[str, ...]], list[str]]:
    """Every `subprocess` spawn in the modules under `root`, as the
    literal words its argument list starts with (`("docker",
    "inspect")` for `["docker", "inspect", name, ...]`), and where they
    reach a spawn the sweep cannot read: a computed command, `os`'s
    spawns, an alias, a `from` import, the module or function handed
    on as a value, `asyncio`'s and Qt's. It reads source, so a module
    imported by a string (`importlib.import_module("subprocess")`)
    passes it; a library's own spawn (webbrowser's `osascript`) is
    conftest's guard's, at run time."""
    commands: set[tuple[str, ...]] = set()
    unreadable: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # `ast.walk` yields a node before its children, so a read call
        # marks its function, and an attribute its module's name,
        # before the walk reaches either.
        read: set[int] = set()
        qualifying: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (words := _literal_program(node)):
                commands.add(words)
                read.add(id(node.func))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                qualifying.add(id(node.value))
            if _reaches_a_spawn(node, read, qualifying):
                lineno = getattr(node, "lineno", "?")
                unreadable.append(f"{path.relative_to(root)}:{lineno}")
    return sorted(commands), unreadable


def _reaches_a_spawn(node: ast.AST, read: set[int], qualifying: set[int]) -> bool:
    """Whether `node` reaches a spawn some other way than a call whose
    program was read (`read`, by its function's id): `os.system`,
    `subprocess.run(command)`, `run = subprocess.run`, `QProcess`,
    `loop.subprocess_exec`, an import that renames one, or the module
    handed on as a value (`getattr(subprocess, "run")`): a module name
    that is not the left of an attribute (`qualifying`, by its id)."""
    if isinstance(node, ast.Attribute):
        module = node.value.id if isinstance(node.value, ast.Name) else ""
        return (
            node.attr in _MODULE_SPAWNS.get(module, set()) | _ANY_SPAWNS
            and id(node) not in read
        )
    if isinstance(node, ast.Name):
        return node.id in _ANY_SPAWNS or (
            node.id in _MODULE_SPAWNS and id(node) not in qualifying
        )
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _binds_a_spawn(node)
    return False


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


def test_the_sweep_reads_a_subprocess_call_by_its_module(tmp_path):
    """What src/ writes: `subprocess.<spawn>([...])` is read, and names
    from `subprocess` and `os` that start nothing are not flagged."""
    (tmp_path / "opener.py").write_text(
        "import os.path\n"
        "import subprocess\n"
        "from os import path\n"
        "from subprocess import PIPE, CalledProcessError\n"
        "subprocess.run(['open', '-R', os.path.join('/', 'x')], stdout=PIPE)\n"
        "subprocess.TimeoutExpired\n",
        encoding="utf-8",
    )

    assert _commands_src_spawns(tmp_path) == ([("open", "-R")], [])


# Spawns the sweep would otherwise neither read nor flag, by what each
# goes through.
_HIDDEN_SPAWNS = {
    "from-import": "from subprocess import Popen\nPopen(['open', '/'])\n",
    "module-alias": "import subprocess as sp\nsp.run(['open', '/'])\n",
    "function-alias": (
        "import subprocess\nrun = subprocess.run\nrun(['open', '/'])\n"
    ),
    "getattr": (
        "import subprocess\ngetattr(subprocess, 'run')(['open', '/'])\n"
    ),
    "os-from-import": "from os import system\nsystem('open /')\n",
    "os-alias": "import os as o\no.system('open /')\n",
    "asyncio": (
        "import asyncio\nasyncio.create_subprocess_exec('open', '/')\n"
    ),
    "asyncio-from-import": (
        "from asyncio import create_subprocess_exec\n"
        "create_subprocess_exec('open', '/')\n"
    ),
    "qprocess": (
        "from PySide6.QtCore import QProcess\n"
        "QProcess.startDetached('open', ['/'])\n"
    ),
    "qprocess-attribute": (
        "from PySide6 import QtCore\n"
        "QtCore.QProcess.startDetached('open', ['/'])\n"
    ),
}


@pytest.mark.parametrize(
    "source", _HIDDEN_SPAWNS.values(), ids=list(_HIDDEN_SPAWNS),
)
def test_the_sweep_flags_a_spawn_it_cannot_read(tmp_path, source):
    """A spawn the sweep flags fails the test above until someone reads
    it; one it neither reads nor flags passes every test here unseen.
    `from subprocess import Popen` in a module the tests import binds
    the real class before conftest's guard replaces it, so the guard
    would not see that spawn either."""
    (tmp_path / "opener.py").write_text(source, encoding="utf-8")

    spawned, unreadable = _commands_src_spawns(tmp_path)

    assert spawned == []
    assert unreadable != []


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


@pytest.mark.parametrize(
    "link",
    ["https://example.com/", "http://example.com/", "mailto:x@example.com", None],
    ids=["https", "http", "mailto", "file"],
)
def test_the_suite_refuses_a_link_qt_would_open_on_the_desktop(
        qapp, tmp_path, link, _desktop_attempts,
):
    """A label with `setOpenExternalLinks(True)` (Support's and About's
    author and bug-report links) hands a click to
    `QDesktopServices.openUrl`, which opens it in the browser, the mail
    app or Finder without `subprocess`. `None` is a local folder."""
    url = QUrl(link) if link is not None else QUrl.fromLocalFile(str(tmp_path))

    QDesktopServices.openUrl(url)

    assert _desktop_attempts == [url.toString()]
    # Recorded and refused; cleared so this test alone passes.
    _desktop_attempts.clear()

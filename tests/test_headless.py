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

from ast_annotations import annotation_names
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

# The helper src/ starts every program through, as the one import the
# sweep follows binds it (`from seeker import processes`), and its path
# under src/seeker.
_HELPER_MODULE = "seeker.processes"
_HELPER = Path("processes.py")

# What starts a program, by the module it is reached through. The sweep
# reads the program of a `subprocess` or helper spawn whose argument
# list starts with literal words; every other use of these names is
# unreadable.
_OS_SPAWNS = {
    "system", "popen", "startfile", "posix_spawn", "posix_spawnp",
    "execl", "execle", "execlp", "execlpe",
    "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "_execvpe", "_spawnvef",
}
_MODULE_SPAWNS = {
    "subprocess": {
        "run", "Popen", "call", "check_call", "check_output",
        "getoutput", "getstatusoutput", "_fork_exec",
    },
    "processes": {"run", "popen"},
    _HELPER_MODULE: {"run", "popen"},
    # `posix` and `nt` are the modules `os` re-exports them from.
    "os": _OS_SPAWNS, "posix": _OS_SPAWNS, "nt": _OS_SPAWNS,
    # `pty.spawn` forks and runs `os.execlp` in the child.
    "pty": {"spawn"},
}
# Modules any import of which is unreadable: the C cores `subprocess`
# and `multiprocessing` start processes through, and `multiprocessing`
# (with `ProcessPoolExecutor`, below), whose child on macOS is a fresh
# interpreter started through `_posixsubprocess.fork_exec`, never
# `Popen`, running src/ code without conftest (CPython 3.13.15's
# multiprocessing/context.py and util.py, read 2026-11-03).
_UNGUARDED_MODULES = {"multiprocessing", "_posixsubprocess", "_winapi"}
# Names that start a program, or open something on the desktop,
# whatever they are reached through: Qt's, asyncio's and Cocoa's.
_ANY_SPAWNS = {
    "QProcess", "create_subprocess_exec", "create_subprocess_shell",
    "subprocess_exec", "subprocess_shell", "ProcessPoolExecutor",
    "NSWorkspace", "NSTask", "NSAppleScript",
}


def _literal_program(call: ast.Call) -> tuple[str, ...]:
    """The literal words `subprocess.<spawn>([...])`'s or
    `processes.<spawn>([...])`'s argument list starts with, up to its
    first computed element; empty for any other call, and for a list
    that starts computed."""
    function = call.func
    if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in {"subprocess", "processes"}
            and function.attr in _MODULE_SPAWNS[function.value.id]
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
    name the sweep does not follow (`import subprocess as sp`, `from
    subprocess import Popen`, `from os import *`, `from asyncio import
    create_subprocess_exec`), or imports an unguarded module (`import
    multiprocessing`, `from multiprocessing.pool import Pool`), or
    binds the helper any way but `from seeker import processes`.
    `import subprocess`, `from os import path` and `from subprocess
    import PIPE` bind nothing that starts a program."""
    if isinstance(node, ast.Import):
        return any(
            alias.name.partition(".")[0] in _UNGUARDED_MODULES
            or alias.name == _HELPER_MODULE
            or (
                alias.name in _MODULE_SPAWNS
                and alias.asname not in (None, alias.name)
            )
            for alias in node.names
        )
    module = node.module or ""
    spawns = _MODULE_SPAWNS.get(module, set())
    return module.partition(".")[0] in _UNGUARDED_MODULES or any(
        (
            alias.name in spawns | _ANY_SPAWNS | _MODULE_SPAWNS.keys()
            and not _imports_the_helper(node, alias)
        )
        or (alias.name == "*" and bool(spawns))
        for alias in node.names
    )


def _imports_the_helper(node: ast.ImportFrom, alias: ast.alias) -> bool:
    """`from seeker import processes`, the one import of the helper the
    sweep follows: it reads `processes.run([...])` as it reads
    `subprocess.run([...])`. Another module of that name, or the helper
    under another name, would be read as the helper or not at all."""
    return (
        node.level == 0
        and node.module == _HELPER_MODULE.partition(".")[0]
        and alias.name == _HELPER_MODULE.partition(".")[2]
        and alias.asname is None
    )


def _forwarding_call(function: ast.stmt) -> ast.Call | None:
    """`function`'s spawn, when `function` is the helper's `run` or
    `popen` and hands its caller's argument list on untouched: past its
    docstring, its body is the one statement `return
    subprocess.<spawn>(args, ...)`, with `args` its first parameter,
    named there and nowhere else in the body. That spawn starts what
    the caller names, and the sweep reads each caller where it calls
    `processes.run([...])`, so passing it hides no program. Any other
    shape (the list rebuilt, rebound, sliced or changed in place; a
    second statement), and the same shape in any other module, stays
    unreadable."""
    if not (
            isinstance(function, ast.FunctionDef)
            and function.name in _MODULE_SPAWNS["processes"]
            and function.args.args
    ):
        return None
    body = function.body
    if ast.get_docstring(function) is not None:
        body = body[1:]
    if not (len(body) == 1 and isinstance(body[0], ast.Return)):
        return None
    call = body[0].value
    parameter = function.args.args[0].arg
    named = [
        node for node in ast.walk(body[0])
        if isinstance(node, ast.Name) and node.id == parameter
    ]
    if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "subprocess"
            and call.func.attr in _MODULE_SPAWNS["subprocess"]
            and len(call.args) == 1
            and len(named) == 1
            and named[0] is call.args[0]
    ):
        return None
    return call


def _commands_src_spawns(
        root: Path,
) -> tuple[list[tuple[str, ...]], list[str]]:
    """Every `subprocess` or helper spawn in the modules under `root`,
    as the literal words its argument list starts with (`("docker",
    "inspect")` for `["docker", "inspect", name, ...]`), and where they
    reach a spawn the sweep cannot read: a computed command; `os`'s,
    `pty`'s, `asyncio`'s, Qt's or Cocoa's spawns; an alias, a `from`
    import, the module or function handed on as a value; an unguarded
    module.

    What it passes opens nothing unseen: `os.fork`, `os.forkpty` and
    `pty.fork` start no program, and their child keeps conftest's
    guard and needs a spawn above to start one; a library's own spawn
    (webbrowser's `osascript`) reaches `Popen` at run time, where the
    guard refuses it. What it cannot see, since it reads names in
    source: a module imported by a string
    (`importlib.import_module("subprocess")`), and a C function called
    through ctypes (libc's `system`); src/ calls libc's
    `sysctlbyname` and libchromaprint that way, nothing that opens
    anything."""
    commands: set[tuple[str, ...]] = set()
    unreadable: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # `ast.walk` yields a node before its children, so a read call
        # marks its function, and an attribute its module's name,
        # before the walk reaches either.
        read: set[int] = set()
        if path.relative_to(root) == _HELPER:
            read |= {
                id(call.func) for function in tree.body
                if (call := _forwarding_call(function)) is not None
            }
        qualifying: set[int] = set()
        typed = annotation_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (words := _literal_program(node)):
                commands.add(words)
                read.add(id(node.func))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                qualifying.add(id(node.value))
            if id(node) not in typed and _reaches_a_spawn(node, read, qualifying):
                lineno = getattr(node, "lineno", "?")
                unreadable.append(f"{path.relative_to(root)}:{lineno}")
    return sorted(commands), unreadable


def _reaches_a_spawn(node: ast.AST, read: set[int], qualifying: set[int]) -> bool:
    """Whether `node` reaches a spawn some other way than a call whose
    program was read (`read`, by its function's id): `os.system`,
    `subprocess.run(command)`, `run = subprocess.run`, `QProcess`,
    `loop.subprocess_exec`, an import that renames one, the module
    handed on as a value (`getattr(subprocess, "run")`): a module name
    that is not the left of an attribute (`qualifying`, by its id), or
    the helper reached through its package (`seeker.processes`)."""
    if isinstance(node, ast.Attribute):
        module = node.value.id if isinstance(node.value, ast.Name) else ""
        return (
            node.attr in _MODULE_SPAWNS.get(module, set()) | _ANY_SPAWNS
            and id(node) not in read
        ) or f"{module}.{node.attr}" == _HELPER_MODULE
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
    [(None, "offscreen"), ("", "offscreen"), ("minimal", "minimal")],
    ids=["unset", "empty", "named"],
)
def test_the_suite_is_offscreen_unless_its_caller_names_a_platform(
        tmp_path, callers_platform, expected,
):
    """A bare `pytest` builds its `qapp` offscreen, and a process a
    test starts inherits that; a platform the caller sets (Kris's
    `cocoa`) wins. An empty `QT_QPA_PLATFORM=` names none: Qt takes it
    as unset and picks Cocoa. `minimal` stands in for `cocoa`, which
    would put windows on this desktop. If the default regresses, Qt's
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
    from `subprocess` and `os` that start nothing, annotations among
    them, are not flagged."""
    (tmp_path / "opener.py").write_text(
        "import os.path\n"
        "import subprocess\n"
        "from os import path\n"
        "from subprocess import PIPE, CalledProcessError\n"
        "subprocess.run(['open', '-R', os.path.join('/', 'x')], stdout=PIPE)\n"
        "subprocess.TimeoutExpired\n"
        "started: list[subprocess.Popen[bytes]] = []\n"
        "def wait(process: subprocess.Popen[str]) -> subprocess.Popen | None: ...\n",
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
    "annotation-call": (
        "import subprocess\ndef wait() -> subprocess.Popen(command): ...\n"
    ),
    "forwarding-outside-the-helper": (
        "import subprocess\ndef run(args):\n    return subprocess.run(args)\n"
    ),
    "helper-computed": (
        "from seeker import processes\nprocesses.run(command, check=False)\n"
    ),
    "helper-function-alias": (
        "from seeker import processes\n"
        "run = processes.run\n"
        "run(['open', '/'], check=False)\n"
    ),
    "helper-getattr": (
        "from seeker import processes\n"
        "getattr(processes, 'run')(['open', '/'], check=False)\n"
    ),
    "helper-through-its-package": (
        "import seeker\nseeker.processes.run(['open', '/'], check=False)\n"
    ),
    "getoutput": "import subprocess\nsubprocess.getoutput('qlmanage -p x')\n",
    "getstatusoutput": (
        "from subprocess import getstatusoutput\ngetstatusoutput('open /')\n"
    ),
    "pty": "import pty\npty.spawn(['open', '/'])\n",
    "posix": "import posix\nposix.system('open /')\n",
    "private": "import os\nos._execvpe('open', ['open', '/'])\n",
    "fork-exec": (
        "from _posixsubprocess import fork_exec\nfork_exec(['open', '/'])\n"
    ),
    "multiprocessing": (
        "import multiprocessing\n"
        "import webbrowser\n"
        "multiprocessing.Process(\n"
        "    target=webbrowser.open, args=['https://example.com/'],\n"
        ").start()\n"
    ),
    "multiprocessing-from-import": (
        "from multiprocessing.pool import Pool\n"
        "import webbrowser\n"
        "Pool().map(webbrowser.open, ['https://example.com/'])\n"
    ),
    "process-pool": (
        "import concurrent.futures\n"
        "import webbrowser\n"
        "concurrent.futures.ProcessPoolExecutor().submit(\n"
        "    webbrowser.open, 'https://example.com/',\n"
        ")\n"
    ),
    "nsworkspace": (
        "from AppKit import NSURL, NSWorkspace\n"
        "NSWorkspace.sharedWorkspace().openURL_(NSURL.fileURLWithPath_('/'))\n"
    ),
    "nstask": (
        "import Foundation\n"
        "Foundation.NSTask.launchedTaskWithLaunchPath_arguments_(\n"
        "    '/usr/bin/open', ['/'],\n"
        ")\n"
    ),
    "nsapplescript": (
        "from Foundation import NSAppleScript\n"
        "NSAppleScript.alloc().initWithSource_(\n"
        "    'open location \"https://example.com/\"',\n"
        ").executeAndReturnError_(None)\n"
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


@pytest.mark.parametrize(
    "line",
    [
        "from seeker import processes as p",
        "from seeker.processes import run",
        "from seeker.processes import *",
        "import seeker.processes",
        "import seeker.processes as processes",
        "from . import processes",
        "from .processes import popen",
        "from other import processes",
    ],
)
def test_the_sweep_follows_the_helper_through_one_import_alone(tmp_path, line):
    """`processes.run([...])` is read as the helper's spawn under `from
    seeker import processes` alone: any other import of the helper puts
    it under a name the sweep does not follow, and another module of
    that name would be read as the helper."""
    (tmp_path / "opener.py").write_text(f"{line}\n", encoding="utf-8")

    assert _commands_src_spawns(tmp_path) == ([], ["opener.py:1"])


def test_the_sweep_reads_a_program_started_through_the_helper(tmp_path):
    """The real helper's own two spawns pass, and a caller's
    `processes.run([...])` and `processes.popen([...])` are read as
    `subprocess`'s are."""
    (tmp_path / _HELPER).write_text(
        (SRC / _HELPER).read_text(encoding="utf-8"), encoding="utf-8",
    )
    (tmp_path / "opener.py").write_text(
        "from seeker import processes\n"
        "processes.run(['open', '-R', path], check=False)\n"
        "processes.popen(['ffmpeg', '-i', path])\n",
        encoding="utf-8",
    )

    assert _commands_src_spawns(tmp_path) == (
        [("ffmpeg", "-i"), ("open", "-R")], [],
    )


# Helper spawns that may start what no caller's list names, by how.
_CHANGED_FORWARDS = {
    "rebound": (
        "def run(args):\n"
        "    args = ['open', *args]\n"
        "    return subprocess.run(args)\n"
    ),
    "changed-in-place": (
        "def run(args):\n"
        "    args.insert(0, 'open')\n"
        "    return subprocess.run(args)\n"
    ),
    "changed-in-the-call": (
        "def run(args):\n"
        "    return subprocess.run(args, check=args.insert(0, 'open'))\n"
    ),
    "sliced": "def run(args):\n    return subprocess.run(args[1:])\n",
    "not-its-first-parameter": (
        "def run(flags, args):\n    return subprocess.run(args)\n"
    ),
    "not-run-or-popen": "def start(args):\n    return subprocess.run(args)\n",
    "nested": (
        "def run(args):\n"
        "    def start():\n"
        "        return subprocess.run(args)\n"
        "    return start()\n"
    ),
}


@pytest.mark.parametrize(
    "function", _CHANGED_FORWARDS.values(), ids=list(_CHANGED_FORWARDS),
)
def test_the_helper_passes_only_a_spawn_of_what_its_caller_named(
        tmp_path, function,
):
    """The sweep passes the helper's `run` and `popen` only as one
    statement handing their first parameter on untouched, since it reads
    the program at their callers; any other spawn there is unreadable."""
    (tmp_path / _HELPER).write_text(
        f"import subprocess\n{function}", encoding="utf-8",
    )

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


# Programs the guard refuses, spelled as they start all the same: with
# the extension a Windows path names (`shutil.which` there finds
# `docker.exe`, PF-34), or in another case, which a file system that
# ignores case finds (this Mac's APFS ran `/USR/BIN/TRUE`, observed
# 2026-11-10; NTFS's lookup is Microsoft's documentation, UNVERIFIED).
_SPELLINGS = {
    "docker.exe": ["ps"],
    "DOCKER": ["ps"],
    "Docker.EXE": ["compose", "up", "-d"],
    "OPEN.EXE": ["-R", "/"],
    "Explorer.exe": ["/"],
    "cmd.exe": ["/c", "start", "", "Docker Desktop"],
    "CMD": ["/C", "START", "", "Docker Desktop"],
}


@pytest.mark.parametrize("name", _SPELLINGS)
def test_the_suite_refuses_a_program_by_its_stem_in_any_case(
        tmp_path, name, _docker_attempts, _desktop_attempts,
):
    """Each by its full path, as `shutil.which` hands it back."""
    program, ran = _stand_in(tmp_path, name)
    command = [str(program), *_SPELLINGS[name]]

    with pytest.raises(FileNotFoundError):
        subprocess.run(command, check=False)  # noqa: S603 — a stand-in

    assert not ran.exists()
    docker = Path(name).stem.casefold() == "docker"
    record = _docker_attempts if docker else _desktop_attempts
    assert record == [" ".join(command)]
    # Recorded and refused; cleared so this test alone passes.
    record.clear()


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "webbrowser runs osascript on macOS only (os.startfile on "
        "Windows), and shlex.split strips a Windows path's backslashes"
    ),
)
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
    app or Finder without `subprocess`. `None` is a local folder.

    No stand-in can take the link's place: with the handler gone, this
    test would open the real thing. Offscreen opens nothing whatever
    (it warns that it cannot; observed 2026-11-03), and the handler is
    the same on every platform, so a run on any other is skipped."""
    if qapp.platformName() != "offscreen":
        pytest.skip(
            "the handler does not depend on the platform, so every "
            "offscreen run checks it; on this one a broken handler "
            "would open these links on the desktop",
        )
    url = QUrl(link) if link is not None else QUrl.fromLocalFile(str(tmp_path))

    QDesktopServices.openUrl(url)

    assert _desktop_attempts == [url.toString()]
    # Recorded and refused; cleared so this test alone passes.
    _desktop_attempts.clear()

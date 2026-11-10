"""Every program src/ starts goes through `seeker/processes.py`: no
other module names a spawn of `subprocess`'s, `os.system` or
`os.popen`, so each program starts with `processes.run()` or
`processes.popen()`, which on Windows open no console window and read
text as UTF-8.

This sweep reads where a spawn is named. `tests/test_headless.py` reads
what each one starts and flags every other way to start a program
(`os.posix_spawn`, asyncio's, `QProcess`, Cocoa's), so a spawn missing
from `_SPAWNS` fails that sweep instead. Both read names in source: a
module imported by a string (`importlib.import_module("subprocess")`)
passes them both.
"""
import ast
from pathlib import Path

import pytest

from ast_annotations import annotation_names

SEEKER_ROOT = Path(__file__).resolve().parent.parent / "src" / "seeker"

# The one module that may start a program, by its path under the root.
HELPER = Path("processes.py")

# What starts a program, by the module it is named on. `posix` and `nt`
# are the modules `os` takes `system` from.
_OS_SPAWNS = frozenset({"system", "popen"})
_SPAWNS = {
    "subprocess": frozenset({
        "run", "Popen", "call", "check_call", "check_output",
        "getoutput", "getstatusoutput",
    }),
    "os": _OS_SPAWNS,
    "posix": _OS_SPAWNS,
    "nt": _OS_SPAWNS,
}


class _Modules:
    """The names that stand for a module of `_SPAWNS` in one module's
    tree."""

    def __init__(self, tree: ast.AST) -> None:
        # Each module's own name, and any alias an import gives it
        # (`import subprocess as sp`, `from seeker.processes import
        # subprocess as sp`), with its module.
        self._aliases = {module: module for module in _SPAWNS}
        # Every name an import binds (`import seeker.processes` binds
        # `seeker`).
        self._imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.asname is not None and alias.name in _SPAWNS:
                        self._aliases[alias.asname] = alias.name
                    self._imported.add(
                        alias.asname or alias.name.partition(".")[0],
                    )

    def named_by(self, node: ast.AST) -> str | None:
        """The module `node` stands for: a name of it, or an attribute
        of its name on a module this one imports (`processes.subprocess`,
        `seeker.processes.subprocess`, `shutil.os`), never on any other
        object (`device.os`)."""
        if isinstance(node, ast.Name):
            return self._aliases.get(node.id)
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if (
                isinstance(node, ast.Attribute)
                and node.attr in _SPAWNS
                and isinstance(root, ast.Name)
                and root.id in self._imported
        ):
            return node.attr
        return None


def _spawns_in(tree: ast.AST) -> list[tuple[int, str]]:
    """Where `tree` names a spawn, by line, and what it names: an
    attribute (`subprocess.run`, `sp.run`, `processes.subprocess.run`),
    a `from` import of one (`from os import system`, `from subprocess
    import *`), or its module handed on as a value
    (`getattr(subprocess, "run")`)."""
    modules = _Modules(tree)
    typed = annotation_names(tree)
    qualifying = {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        # An annotation (`-> subprocess.Popen[bytes]`) names a type and
        # starts nothing, since a spawn needs a call, and
        # `annotation_names` never follows one into a call: `->
        # subprocess.Popen(command)` is read as it is anywhere else.
        if id(node) in typed:
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module in _SPAWNS:
                found.extend(
                    (node.lineno, f"{node.module}.{alias.name}")
                    for alias in node.names
                    if alias.name in _SPAWNS[node.module] | {"*"}
                )
        elif isinstance(node, ast.Attribute) and (
                (module := modules.named_by(node.value))
                and node.attr in _SPAWNS[module]
        ):
            found.append((node.lineno, f"{module}.{node.attr}"))
        elif (
                isinstance(node, (ast.Attribute, ast.Name))
                and id(node) not in qualifying
                and (module := modules.named_by(node))
        ):
            found.append((node.lineno, f"{module}, as a value"))
    return found


def _spawns_under(root: Path) -> list[str]:
    """Every spawn named in the modules under `root` but the helper, as
    `path:line: what it names`."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        # The helper alone may name a spawn; the test of it below pins
        # the two it names, so passing it here hides no third.
        if relative == HELPER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found += [
            f"{relative.as_posix()}:{lineno}: {named}"
            for lineno, named in sorted(_spawns_in(tree))
        ]
    return found


def test_no_module_but_the_helper_starts_a_program():
    # Guards against a moved src/ sweeping nothing.
    for relative in (HELPER, Path("soulseek/docker_setup.py")):
        assert (SEEKER_ROOT / relative).is_file(), relative

    assert _spawns_under(SEEKER_ROOT) == []


def test_the_helper_names_one_spawn_in_each_of_its_functions():
    """`processes.py` names `subprocess.run` in `run` and
    `subprocess.Popen` in `popen`, and nothing else the sweep flags: a
    spawn added there is a decision this test makes someone read."""
    tree = ast.parse((SEEKER_ROOT / HELPER).read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]

    def owner(lineno: int) -> str:
        return next(
            (
                function.name for function in functions
                if function.lineno <= lineno <= (function.end_lineno or 0)
            ),
            "<module>",
        )

    assert sorted(
        (owner(lineno), named) for lineno, named in _spawns_in(tree)
    ) == [("popen", "subprocess.Popen"), ("run", "subprocess.run")]


def test_only_the_helper_at_the_root_is_passed(tmp_path):
    spawn = "import subprocess\nsubprocess.run(['open', '/'], check=False)\n"
    (tmp_path / HELPER).write_text(spawn, encoding="utf-8")
    (tmp_path / "soulseek").mkdir()
    (tmp_path / "soulseek" / HELPER).write_text(spawn, encoding="utf-8")

    assert _spawns_under(tmp_path) == ["soulseek/processes.py:2: subprocess.run"]


# A spawn named outside the helper, by how, with the line it is on and
# what the sweep reports it names.
_PLANTED = {
    "run": (
        "import subprocess\nsubprocess.run(['docker', 'ps'], check=True)\n",
        "2: subprocess.run",
    ),
    "popen": (
        "import subprocess\nsubprocess.Popen(['ffmpeg', '-i', path])\n",
        "2: subprocess.Popen",
    ),
    "call": (
        "import subprocess\nsubprocess.call(['open', '/'])\n",
        "2: subprocess.call",
    ),
    "check-call": (
        "import subprocess\nsubprocess.check_call(['open', '/'])\n",
        "2: subprocess.check_call",
    ),
    "check-output": (
        "import subprocess\nsubprocess.check_output(['docker', 'ps'])\n",
        "2: subprocess.check_output",
    ),
    "getoutput": (
        "import subprocess\nsubprocess.getoutput('docker ps')\n",
        "2: subprocess.getoutput",
    ),
    "os-system": ("import os\nos.system('open /')\n", "2: os.system"),
    "os-popen": (
        "import os\nos.popen('/usr/bin/osascript', 'w')\n", "2: os.popen",
    ),
    "posix-system": ("import posix\nposix.system('open /')\n", "2: posix.system"),
    "in-a-function": (
        "def reveal(path):\n"
        "    import subprocess\n"
        "    subprocess.run(['open', path], check=False)\n",
        "3: subprocess.run",
    ),
    "module-alias": (
        "import subprocess as sp\nsp.run(['open', '/'], check=False)\n",
        "2: subprocess.run",
    ),
    "from-import": (
        "from subprocess import run\nrun(['open', '/'], check=False)\n",
        "1: subprocess.run",
    ),
    "from-import-alias": (
        "from os import system as shell\nshell('open /')\n", "1: os.system",
    ),
    "star-import": (
        "from subprocess import *\nrun(['open', '/'], check=False)\n",
        "1: subprocess.*",
    ),
    "through-the-helper": (
        "from seeker import processes\n"
        "processes.subprocess.run(['open', '/'], check=False)\n",
        "2: subprocess.run",
    ),
    "through-another-module": (
        "import shutil\nshutil.os.system('open /')\n", "2: os.system",
    ),
    "through-the-helpers-package": (
        "import seeker.processes\n"
        "seeker.processes.subprocess.check_output(['docker', 'ps'])\n",
        "2: subprocess.check_output",
    ),
    "imported-from-the-helper": (
        "from seeker.processes import subprocess as sp\n"
        "sp.Popen(['open', '/'])\n",
        "2: subprocess.Popen",
    ),
    "spawn-as-a-value": (
        "import subprocess\nstart = subprocess.Popen\n", "2: subprocess.Popen",
    ),
    "module-as-a-value": (
        "import subprocess\ngetattr(subprocess, 'run')(['open', '/'])\n",
        "2: subprocess, as a value",
    ),
    "helper-module-as-a-value": (
        "from seeker import processes\n"
        "getattr(processes.subprocess, 'run')(['open', '/'])\n",
        "2: subprocess, as a value",
    ),
    "generic-call": (
        "import subprocess\nsubprocess.Popen[bytes](['open', '/'])\n",
        "2: subprocess.Popen",
    ),
    "annotation-call": (
        "import subprocess\n"
        "def wait() -> subprocess.Popen(['open', '/']): ...\n",
        "2: subprocess.Popen",
    ),
}


@pytest.mark.parametrize(
    ("source", "reported"), _PLANTED.values(), ids=list(_PLANTED),
)
def test_the_sweep_flags_a_planted_spawn(tmp_path, source, reported):
    (tmp_path / "opener.py").write_text(source, encoding="utf-8")

    assert _spawns_under(tmp_path) == [f"opener.py:{reported}"]


# What src/ writes that starts nothing, or starts through the helper.
_HARMLESS = {
    "the-helper": (
        "from seeker import processes\n"
        "processes.run(['docker', 'ps'], check=True)\n"
        "processes.popen(['ffmpeg', '-i', path])\n"
    ),
    "exceptions-and-constants": (
        "import subprocess\n"
        "from subprocess import PIPE, CalledProcessError\n"
        "try:\n"
        "    pass\n"
        "except (subprocess.TimeoutExpired, subprocess.SubprocessError):\n"
        "    pass\n"
    ),
    "os-without-a-spawn": (
        "import os\n"
        "import os.path\n"
        "from os import path\n"
        "os.environ.get('PATH', os.pathsep)\n"
        "os.fdopen(os.open('x', os.O_RDONLY))\n"
    ),
    "annotations": (
        "import subprocess\n"
        "started: list[subprocess.Popen[bytes]] = []\n"
        "def wait(\n"
        "        process: subprocess.Popen[str] | None,\n"
        ") -> subprocess.CompletedProcess[str]: ...\n"
    ),
    "a-mention": (
        '"""Starts nothing: subprocess.run is a word here."""\n'
        "# os.system('open /')\n"
    ),
    "methods-of-those-names": (
        "def start(runner, task):\n"
        "    runner.run()\n"
        "    task.call()\n"
        "    return runner.popen\n"
    ),
    "an-objects-attribute-of-a-modules-name": (
        "def describe(device):\n    return device.os, device.nt.system\n"
    ),
}


@pytest.mark.parametrize("source", _HARMLESS.values(), ids=list(_HARMLESS))
def test_the_sweep_passes_what_starts_nothing(tmp_path, source):
    (tmp_path / "opener.py").write_text(source, encoding="utf-8")

    assert _spawns_under(tmp_path) == []

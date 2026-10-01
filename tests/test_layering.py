"""CLAUDE.md's layering rules, swept over every module in `src/seeker/`.

An import anywhere in a module counts, including one inside a function
or a `TYPE_CHECKING` block: each couples the layers just the same.
"""
import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

SEEKER_ROOT = Path(__file__).resolve().parent.parent / "src" / "seeker"

ENTRY_POINTS = ("main.py", "main_ui.py")


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _imported_modules(path: Path, root: Path) -> Iterator[tuple[str, int]]:
    """Every module `path` imports, as an absolute dotted name.

    `from seeker import database` yields `seeker.database` as well as
    `seeker`, so naming a subpackage as an imported name cannot slip
    past a rule; a relative import is resolved against the module's own
    package for the same reason.
    """
    package = ["seeker", *path.parent.relative_to(root).parts]

    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - (node.level - 1)]
                module = ".".join(
                    [*base, node.module] if node.module else base,
                )
            else:
                assert node.module is not None
                module = node.module

            yield module, node.lineno
            for alias in node.names:
                yield f"{module}.{alias.name}", node.lineno


def _broken_rule(relative: str, module: str) -> str | None:
    in_ui = relative.startswith("ui/")
    presentation = in_ui or relative == "cli.py" or relative in ENTRY_POINTS

    if presentation and _within(module, "seeker.database"):
        return "presentation code goes through Application, never the database"
    if relative == "cli.py" and _within(module, "seeker.ui"):
        return "the CLI never imports the GUI"
    if (
            (_within(module, "PySide6") or _within(module, "shiboken6"))
            and not (in_ui or relative == "main_ui.py")
    ):
        return "only ui/ and main_ui.py import Qt"
    if (
            relative.startswith("models/")
            and _within(module, "seeker")
            and module != "seeker"
            and not _within(module, "seeker.models")
    ):
        return "models/ imports nothing from seeker but models"
    return None


def _violations(root: Path) -> list[str]:
    # One entry per import statement: `from a.b import c` is checked as
    # both `a.b` and `a.b.c`, and should read as one violation.
    found: dict[tuple[str, int], str] = {}

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        for module, lineno in _imported_modules(path, root):
            rule = _broken_rule(relative, module)
            if rule is not None:
                found.setdefault(
                    (relative, lineno),
                    f"{relative}:{lineno}: {module} — {rule}",
                )

    return list(found.values())


def test_src_keeps_every_layering_rule():
    # Guards against a moved src/ silently sweeping nothing.
    for relative in ("cli.py", *ENTRY_POINTS, "ui/main_window.py",
                     "models/track.py", "database/connection.py"):
        assert (SEEKER_ROOT / relative).is_file(), relative

    assert _violations(SEEKER_ROOT) == []


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        (
            "ui/pages/some_page.py",
            "from seeker.database.repositories.track_repository import (\n"
            "    TrackRepository,\n"
            ")\n",
        ),
        ("ui/pages/some_page.py", "from ...database import connection\n"),
        ("cli.py", "def f():\n    import seeker.database.connection\n"),
        ("main.py", "from seeker import database\n"),
        ("main_ui.py", "from seeker.database.connection import Database\n"),
        ("cli.py", "from seeker.ui.theme import apply_theme\n"),
        ("library/service.py", "from PySide6.QtCore import QObject\n"),
        ("main.py", "import shiboken6\n"),
        (
            "models/track.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from seeker.application import Application\n",
        ),
        ("models/track.py", "from .. import errors\n"),
    ],
)
def test_each_rule_catches_a_planted_import(tmp_path, relative, source):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)

    assert len(_violations(tmp_path)) == 1


@pytest.mark.parametrize(
    ("relative", "source"),
    [
        (
            "ui/pages/some_page.py",
            "from PySide6.QtCore import Qt\n"
            "from seeker.application import Application\n",
        ),
        ("main_ui.py", "from PySide6.QtWidgets import QApplication\n"),
        ("cli.py", "from seeker.formatting import format_file_size\n"),
        ("models/track.py", "from seeker.models.playlist import Playlist\n"),
        ("models/track.py", "from dataclasses import dataclass\n"),
        ("library/service.py", "from seeker.database import connection\n"),
    ],
)
def test_an_allowed_import_is_not_flagged(tmp_path, relative, source):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)

    assert _violations(tmp_path) == []

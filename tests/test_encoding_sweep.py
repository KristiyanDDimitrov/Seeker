"""No text the project's Python opens is read or written in the
locale's encoding, which on Windows is its ANSI code page (cp1252 on a
Western install): every call that opens text names its encoding. ruff's
PLW1514 sees such a call only on a receiver it can tell is a `Path`,
and never `os.fdopen`; this sweep reads each call by the name it is
made through, whatever the receiver.

Python picks the locale's encoding for text opened with none in one
place, `io.text_encoding()` (PEP 597): the builtin `open` (also
`io.open`, `codecs.open`) and `io.TextIOWrapper` reach it in C; in
CPython 3.13.15's Lib (read 2026-11-12) `os.fdopen`, `Path.open`,
`read_text` and `write_text` (zipfile's `Path` too), tempfile's three
functions, logging's file handlers and `basicConfig`, socket's
`makefile`, `bz2`, `gzip` and `lzma`'s `open`, `subprocess`,
`configparser`, `fileinput` and `logging.config` call it. So a call
through one of `_OPENS`' names is read: it passes when it names
`encoding="..."` as a string, or opens in a binary mode written as a
string. `configparser`, `fileinput` and `logging.config` are refused at
their import, and another module's `open` (`gzip.open`) at its call.
Anything the sweep cannot read is refused too: a computed mode or
encoding, an encoding passed by position, `*` or `**` arguments, and
any use of these names but a call (as a value, rebound, imported under
another name), except where a type is named (an annotation,
`isinstance`). So no text open in the project's Python passes unread.
What it cannot see: a name built from a string (`getattr(path,
"read_text")`), and a library's own text I/O.

A spawn's text mode is not read here: src/ starts every program
through `seeker/processes.py`, which decodes UTF-8
(`tests/test_subprocess_sweep.py`); a test's child writes in its own
stream's encoding, which the test reads it in.
"""
import ast
from pathlib import Path

import pytest

from ast_annotations import annotation_names

PROJECT = Path(__file__).resolve().parent.parent

# The project's Python, by folder, with a module each holds, so a moved
# folder fails here instead of sweeping nothing.
SWEPT = {
    "src": "seeker/files/atomic.py",
    "tests": "conftest.py",
    "tools": "screenshots.py",
}

# How a call opens text, by the name it is made through: where its mode
# is among the positional arguments (None: text, whatever the arguments
# say) and the mode it opens in when given none.
_OPENS: dict[str, tuple[int | None, str]] = {
    # The builtin, or a module's that is the builtin's (`_BUILTIN_OPENS`).
    "open": (1, "r"),
    "fdopen": (1, "r"),
    "read_text": (None, "r"),
    "write_text": (None, "w"),
    "TextIOWrapper": (None, "r"),
    "FileHandler": (None, "a"),
    "RotatingFileHandler": (None, "a"),
    "TimedRotatingFileHandler": (None, "a"),
    "WatchedFileHandler": (None, "a"),
    "TemporaryFile": (0, "w+b"),
    "NamedTemporaryFile": (0, "w+b"),
    "SpooledTemporaryFile": (1, "w+b"),
    "makefile": (0, "r"),
}
# An object's `open` (a Path's, a zipfile.Path's) takes its mode first.
_METHOD_OPEN = (0, "r")
_BUILTIN_OPENS = {"builtins", "io", "codecs"}
# Modules whose `open` opens no text: a file descriptor, a URL, a WAV
# file (binary whatever its mode).
_OPENS_NO_TEXT = {"os", "webbrowser", "wave"}
# Modules that read text through `io.text_encoding()` in calls the sweep
# does not read.
_REFUSED_MODULES = {"configparser", "fileinput", "logging.config"}


def _type_names(tree: ast.AST) -> set[int]:
    """The ids of the names that only name a type: in an annotation,
    or the class an `isinstance` or `issubclass` checks against."""
    named = annotation_names(tree)
    for node in ast.walk(tree):
        if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"isinstance", "issubclass"}
                and len(node.args) == 2
        ):
            classes = node.args[1]
            elements = classes.elts if isinstance(classes, ast.Tuple) else [classes]
            named |= {
                id(element) for element in elements
                if isinstance(element, (ast.Name, ast.Attribute))
            }
    return named


def _why_locale_text(
        call: ast.Call, mode_at: int | None, default_mode: str,
) -> str | None:
    """Why `call` may open text in the locale's encoding, or None when
    it names an encoding or opens in a binary mode."""
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if "encoding" in keywords:
        encoding = keywords["encoding"]
        if (
                isinstance(encoding, ast.Constant)
                and isinstance(encoding.value, str)
                and encoding.value.lower() != "locale"
        ):
            return None
        return "an encoding that may be the locale's"
    if None in keywords or any(isinstance(arg, ast.Starred) for arg in call.args):
        return "arguments unpacked"
    if mode_at is None:
        return "no encoding"
    mode = keywords.get(
        "mode", call.args[mode_at] if len(call.args) > mode_at else None,
    )
    if mode is None:
        mode_text = default_mode
    elif isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        mode_text = mode.value
    else:
        return "a mode the sweep cannot read"
    return None if "b" in mode_text else "no encoding"


def _locale_text_in(tree: ast.AST) -> list[tuple[int, str]]:
    """Where `tree` may open text in the locale's encoding, by line, and
    why."""
    # Each name an `import` binds to a module, with the module.
    modules = {
        alias.asname or alias.name.partition(".")[0]:
            alias.name if alias.asname else alias.name.partition(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    calls = {
        id(node.func): node for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    types = _type_names(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found += [(node.lineno, why) for why in _why_import(node)]
            continue
        if isinstance(node, ast.Name):
            name, receiver = node.id, None
        elif isinstance(node, ast.Attribute):
            name, receiver = node.attr, node.value
        else:
            continue
        if name not in _OPENS and name != "basicConfig":
            continue
        module = (
            modules.get(receiver.id) if isinstance(receiver, ast.Name) else None
        )
        if name == "open" and module in _OPENS_NO_TEXT:
            continue
        if id(node) in types:
            continue
        call = calls.get(id(node))
        if call is None:
            # A name kept or handed on opens text unread wherever it is
            # called.
            if name != "basicConfig":
                found.append((node.lineno, f"{name}, as a value"))
            continue
        if name == "basicConfig":
            keywords = {keyword.arg for keyword in call.keywords}
            why = (
                _why_locale_text(call, None, "a")
                if keywords & {"filename", None} else None
            )
        elif name == "open" and receiver is not None and module not in _BUILTIN_OPENS:
            why = (
                f"on {module}, which the sweep does not read" if module
                else _why_locale_text(call, *_METHOD_OPEN)
            )
        else:
            why = _why_locale_text(call, *_OPENS[name])
        if why is not None:
            found.append((node.lineno, f"{name}, {why}"))
    return found


def _why_import(node: ast.Import | ast.ImportFrom) -> list[str]:
    """What an import binds that the sweep cannot read: a module of
    `_REFUSED_MODULES` or a name from one, or one of `_OPENS`' names
    under another name (`from io import open as io_open`)."""
    found: list[str] = []
    for alias in node.names:
        if isinstance(node, ast.Import):
            imported = alias.name
        else:
            imported = f"{node.module or ''}.{alias.name}"
        if (
                imported in _REFUSED_MODULES
                or imported.rpartition(".")[0] in _REFUSED_MODULES
        ):
            found.append(f"{imported}, which opens text the sweep does not read")
        elif (
                isinstance(node, ast.ImportFrom)
                and alias.name in {*_OPENS, "basicConfig"}
                and alias.asname not in (None, alias.name)
        ):
            found.append(f"{alias.name}, as {alias.asname}")
    return found


def _locale_text_under(root: Path) -> list[str]:
    """Every call in the modules under `root` that may open text in the
    locale's encoding, as `path:line: name, why`."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found += [
            f"{path.relative_to(root).as_posix()}:{lineno}: {why}"
            for lineno, why in sorted(_locale_text_in(tree))
        ]
    return found


def test_no_text_is_opened_in_the_locales_encoding():
    for folder, module in SWEPT.items():
        assert (PROJECT / folder / module).is_file(), (folder, module)

    assert [
        f"{folder}/{line}" for folder in SWEPT
        for line in _locale_text_under(PROJECT / folder)
    ] == []


# Text opened in the locale's encoding, by how, with the line it is on
# and what the sweep reports.
_PLANTED = {
    "read-text": ("text = path.read_text()\n", "1: read_text, no encoding"),
    "write-text": ("path.write_text(text)\n", "1: write_text, no encoding"),
    "a-path-built-in-the-call": (
        "def read(root):\n    return (root / 'slskd.yml').read_text()\n",
        "2: read_text, no encoding",
    ),
    "the-builtin-open": ("open(path)\n", "1: open, no encoding"),
    "the-builtin-open-for-writing": (
        "open(path, 'w')\n", "1: open, no encoding",
    ),
    "a-paths-open": ("path.open()\n", "1: open, no encoding"),
    "a-paths-open-by-keyword": (
        "path.open(mode='a')\n", "1: open, no encoding",
    ),
    "fdopen": ("import os\nos.fdopen(fd, 'w')\n", "2: fdopen, no encoding"),
    "io-open": ("import io\nio.open(path)\n", "2: open, no encoding"),
    "codecs-open": (
        "import codecs\ncodecs.open(path, 'w')\n", "2: open, no encoding",
    ),
    "text-io-wrapper": (
        "import io\nio.TextIOWrapper(buffer)\n", "2: TextIOWrapper, no encoding",
    ),
    "a-file-handler": (
        "import logging\nlogging.FileHandler(path)\n",
        "2: FileHandler, no encoding",
    ),
    "a-rotating-file-handler": (
        "from logging.handlers import RotatingFileHandler\n"
        "RotatingFileHandler(path, maxBytes=1_000_000)\n",
        "2: RotatingFileHandler, no encoding",
    ),
    "a-temporary-file-in-text": (
        "import tempfile\ntempfile.TemporaryFile('w+')\n",
        "2: TemporaryFile, no encoding",
    ),
    "a-named-temporary-file-in-text": (
        "import tempfile\ntempfile.NamedTemporaryFile(mode='w')\n",
        "2: NamedTemporaryFile, no encoding",
    ),
    "logging-to-a-file": (
        "import logging\nlogging.basicConfig(filename=path)\n",
        "2: basicConfig, no encoding",
    ),
    "the-locales-encoding-by-name": (
        "path.read_text(encoding='locale')\n",
        "1: read_text, an encoding that may be the locale's",
    ),
    "no-encoding-by-name": (
        "path.read_text(encoding=None)\n",
        "1: read_text, an encoding that may be the locale's",
    ),
    "a-computed-encoding": (
        "path.read_text(encoding=encoding)\n",
        "1: read_text, an encoding that may be the locale's",
    ),
    "an-encoding-by-position": (
        "path.write_text(text, 'utf-8')\n", "1: write_text, no encoding",
    ),
    "a-computed-mode": (
        "open(path, mode)\n", "1: open, a mode the sweep cannot read",
    ),
    "options-unpacked": (
        "open(path, 'rb', **options)\n", "1: open, arguments unpacked",
    ),
    "arguments-unpacked": ("open(*arguments)\n", "1: open, arguments unpacked"),
    "a-method-as-a-value": (
        "from pathlib import Path\nread = Path.read_text\n",
        "2: read_text, as a value",
    ),
    "the-builtin-as-a-value": (
        "import functools\nfunctools.partial(open, mode='w')\n",
        "2: open, as a value",
    ),
    "the-builtin-rebound": ("open = opener\n", "1: open, as a value"),
    "imported-under-another-name": (
        "from io import open as io_open\nio_open(path)\n", "1: open, as io_open",
    ),
    "another-modules-open": (
        "import gzip\ngzip.open(path, 'rt')\n",
        "2: open, on gzip, which the sweep does not read",
    ),
    "configparser": (
        "import configparser\n",
        "1: configparser, which opens text the sweep does not read",
    ),
    "fileinput": (
        "from fileinput import input as lines\n",
        "1: fileinput.input, which opens text the sweep does not read",
    ),
    "logging-config": (
        "from logging import config\n",
        "1: logging.config, which opens text the sweep does not read",
    ),
}


@pytest.mark.parametrize(
    ("source", "reported"), _PLANTED.values(), ids=list(_PLANTED),
)
def test_the_sweep_flags_text_opened_in_the_locales_encoding(
        tmp_path, source, reported,
):
    (tmp_path / "reader.py").write_text(source, encoding="utf-8")

    assert _locale_text_under(tmp_path) == [f"reader.py:{reported}"]


# What the project writes that names its encoding or opens no text.
_HARMLESS = {
    "encodings-named": (
        "import io, os\n"
        "from logging.handlers import RotatingFileHandler\n"
        "path.read_text(encoding='utf-8')\n"
        "path.write_text(text, encoding='utf-8')\n"
        "open(path, 'w', encoding='utf-8')\n"
        "path.open(encoding='utf-8')\n"
        "os.fdopen(fd, 'w', encoding='utf-8')\n"
        "io.TextIOWrapper(buffer, encoding='ascii')\n"
        "RotatingFileHandler(path, encoding='utf-8', maxBytes=1)\n"
        "open(path, encoding='utf-8', **options)\n"
    ),
    "binary-modes": (
        "import os, tempfile\n"
        "open(path, 'rb')\n"
        "path.open('rb')\n"
        "path.open(mode='rb+')\n"
        "os.fdopen(fd, 'wb')\n"
        "tempfile.TemporaryFile()\n"
        "tempfile.NamedTemporaryFile(suffix='.wav', delete=False)\n"
        "path.read_bytes()\n"
        "path.write_bytes(data)\n"
    ),
    "modules-whose-open-opens-no-text": (
        "import os, wave, webbrowser\n"
        "os.open(path, os.O_RDONLY)\n"
        "webbrowser.open(url)\n"
        "wave.open(str(path), 'wb')\n"
        "real_open = os.open\n"
    ),
    "a-type-named": (
        "import logging\n"
        "from logging.handlers import RotatingFileHandler\n"
        "isinstance(handler, RotatingFileHandler)\n"
        "issubclass(kind, (logging.FileHandler, str))\n"
        "def attach(handler: logging.FileHandler) -> None: ...\n"
    ),
    "logging-to-a-stream": (
        "import logging\nlogging.basicConfig(level=logging.INFO)\n"
    ),
    "a-mention": (
        '"""Opens nothing: path.read_text() is a word here."""\n'
        "# open(path)\n"
    ),
}


@pytest.mark.parametrize("source", _HARMLESS.values(), ids=list(_HARMLESS))
def test_the_sweep_passes_what_names_its_encoding_or_opens_no_text(
        tmp_path, source,
):
    (tmp_path / "reader.py").write_text(source, encoding="utf-8")

    assert _locale_text_under(tmp_path) == []

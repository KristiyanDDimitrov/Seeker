"""Text from outside Seeker renders literally in the UI.

A peer's filename or username, a playlist name, slskd's log text: left
at Qt's `AutoText`, a label, tooltip or message box renders any of them
as HTML once something tag-like appears before the first line break.
The sweeps below are structural (`ast`), so a label, message box or
tooltip added anywhere in `ui/` or `main_ui.py` later is covered
without a test of its own.

What they cannot see: the message-box sweep accepts a function that
calls `setTextFormat` anywhere in it, even in one branch, and nothing
follows a label's text set after construction (`setText`). Both were
clean by hand at the last audit.
"""

import ast
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QMessageBox

import seeker.ui as ui_package
from seeker.ui import plain_text
from seeker.ui.plain_text import PlainLabel, RichLabel, plain_tooltip

PEER_FILENAME = '<a href="https://evil.example">Update Seeker</a>.mp3'

_UI_DIR = Path(ui_package.__file__).parent
_SEEKER_DIR = _UI_DIR.parent
# The one module allowed to build these directly: it is where the
# explicit format is set.
_HELPER = _UI_DIR / "plain_text.py"


def _swept_files() -> list[Path]:
    # main_ui.py is the one module outside ui/ that may import Qt
    # (test_layering), so it is the one other place a widget is built.
    paths = [*sorted(_UI_DIR.rglob("*.py")), _SEEKER_DIR / "main_ui.py"]
    return [path for path in paths if path != _HELPER]


def _ui_calls() -> list[tuple[Path, ast.Call]]:
    calls = []
    for path in _swept_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        calls.extend(
            (path, node) for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        )
    return calls


def _where(path: Path, node: ast.AST) -> str:
    return f"{path.relative_to(_SEEKER_DIR)}:{node.lineno}"


def test_no_label_in_ui_is_left_to_guess_its_text_format():
    violations = [
        _where(path, call) for path, call in _ui_calls()
        if isinstance(call.func, ast.Name) and call.func.id == "QLabel"
    ]

    assert violations == [], (
        "bare QLabel(...) defaults to AutoText; use PlainLabel, or "
        "RichLabel for Seeker's own markup:\n" + "\n".join(violations)
    )


def test_no_message_box_in_ui_is_left_to_guess_its_text_format():
    static_helpers = {"question", "information", "warning", "critical"}
    violations = [
        _where(path, call) for path, call in _ui_calls()
        if isinstance(call.func, ast.Attribute)
        and call.func.attr in static_helpers
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "QMessageBox"
    ]

    assert violations == [], (
        "QMessageBox's static helpers use AutoText; use plain_text."
        "question/information/warning:\n" + "\n".join(violations)
    )


def test_every_hand_built_message_box_sets_its_text_format():
    # Scoped per function: the box is built and filled in one place,
    # so a function that constructs one and never calls setTextFormat
    # left it at AutoText.
    violations = []
    for path in _swept_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            calls = [
                node for node in ast.walk(function)
                if isinstance(node, ast.Call)
            ]
            builds_box = any(
                isinstance(call.func, ast.Name)
                and call.func.id == "QMessageBox"
                for call in calls
            )
            sets_format = any(
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "setTextFormat"
                for call in calls
            )
            if builds_box and not sets_format:
                violations.append(_where(path, function))

    assert violations == [], (
        "QMessageBox(...) defaults to AutoText; call setTextFormat:\n"
        + "\n".join(violations)
    )


def _is_fixed_text(node: ast.expr) -> bool:
    # A string literal, or a module-level UPPER_CASE constant
    # (help_text.X or a bare X): Seeker's own text, never data.
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Attribute):
        return node.attr.isupper()
    if isinstance(node, ast.Name):
        return node.id.isupper()
    return False


def _is_plain_tooltip_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "plain_tooltip"
    )


# Where each tooltip-setting call takes its text.
_TOOLTIP_TEXT_ARGUMENT = {"setToolTip": 0, "showText": 1}


def test_every_dynamic_tooltip_goes_through_plain_tooltip():
    violations = []
    for path, call in _ui_calls():
        if not isinstance(call.func, ast.Attribute):
            continue
        position = _TOOLTIP_TEXT_ARGUMENT.get(call.func.attr)
        if position is None or len(call.args) <= position:
            continue
        text = call.args[position]
        if not _is_fixed_text(text) and not _is_plain_tooltip_call(text):
            violations.append(f"{_where(path, call)}: {ast.unparse(text)}")

    assert violations == [], (
        "a tooltip auto-detects rich text; wrap dynamic text in "
        "plain_tooltip():\n" + "\n".join(violations)
    )


def _is_escaped_markup(node: ast.expr) -> bool:
    # Seeker's own text, html.escape(...) of anything, or a `+` or
    # f-string built only from those.
    if _is_fixed_text(node):
        return True
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "escape"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "html"
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_escaped_markup(node.left) and _is_escaped_markup(node.right)
    if isinstance(node, ast.JoinedStr):
        return all(
            isinstance(part, ast.Constant)
            or (
                isinstance(part, ast.FormattedValue)
                and _is_escaped_markup(part.value)
            )
            for part in node.values
        )
    return False


def _values_assigned_to(function: ast.AST, name: str) -> list[ast.expr]:
    values: list[ast.expr] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            values.append(node.value)
    return values


def _unescaped_rich_label_arguments(tree: ast.AST) -> list[ast.Call]:
    """`RichLabel(x)` calls whose text may carry unescaped data.

    The argument passes if it is escaped markup itself, or a local name
    every assignment of which, in the enclosing function, is. A name
    with no assignment there (a parameter, a global) fails: its origin
    is out of sight.
    """
    violations = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(function):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "RichLabel"
                and call.args
            ):
                continue
            text = call.args[0]
            if isinstance(text, ast.Name) and not text.id.isupper():
                values = _values_assigned_to(function, text.id)
                safe = bool(values) and all(map(_is_escaped_markup, values))
            else:
                safe = _is_escaped_markup(text)
            if not safe:
                violations.append(call)
    return violations


def test_the_rich_label_sweep_tells_escaped_markup_from_raw_data():
    unsafe = """
def peer(name):
    RichLabel(name)

def built(name):
    body = "<p>Hello</p>"
    body += f"<p>{name}</p>"
    RichLabel(body)

def inline(name):
    RichLabel("<b>" + name + "</b>")
"""
    safe = """
def about(version):
    body = help_text.ABOUT_BODY
    body += f"<p>Version {html.escape(version)}</p>"
    RichLabel(body)

def fixed():
    RichLabel(help_text.HELP_BODY)
    RichLabel("<b>" + html.escape(x) + "</b>")
"""

    flagged = [
        call.lineno for call in _unescaped_rich_label_arguments(ast.parse(unsafe))
    ]

    assert flagged == [3, 8, 11]
    assert _unescaped_rich_label_arguments(ast.parse(safe)) == []


def test_every_rich_label_escapes_the_data_in_its_markup():
    violations = []
    for path in _swept_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        violations.extend(
            f"{_where(path, call)}: {ast.unparse(call.args[0])}"
            for call in _unescaped_rich_label_arguments(tree)
        )

    assert violations == [], (
        "RichLabel renders its text as HTML; html.escape the data in "
        "it, or use PlainLabel:\n" + "\n".join(violations)
    )


def test_plain_tooltip_renders_markup_and_entities_literally():
    text = f"Failed: {PEER_FILENAME} & more\nsecond line"

    document = QTextDocument()
    document.setHtml(plain_tooltip(text))

    assert document.toPlainText() == text


def test_plain_label_shows_a_peer_filename_literally(qtbot):
    label = PlainLabel(PEER_FILENAME)
    qtbot.addWidget(label)

    assert label.text() == PEER_FILENAME
    assert label.textFormat() == Qt.TextFormat.PlainText


def test_rich_label_keeps_seekers_own_markup(qtbot):
    label = RichLabel("<h2>Connect Spotify</h2>")
    qtbot.addWidget(label)

    assert label.textFormat() == Qt.TextFormat.RichText


def test_plain_tooltip_of_nothing_is_no_tooltip():
    assert plain_tooltip("") == ""


def test_message_boxes_show_their_text_literally(qtbot, monkeypatch):
    shown: list[QMessageBox] = []

    def fake_exec(self):
        shown.append(self)
        return QMessageBox.StandardButton.Yes.value

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    answer = plain_text.question(None, "Delete?", PEER_FILENAME)
    plain_text.information(None, "Done", PEER_FILENAME)
    plain_text.warning(None, "Failed", PEER_FILENAME)

    assert answer == QMessageBox.StandardButton.Yes
    assert [box.text() for box in shown] == [PEER_FILENAME] * 3
    assert all(
        box.textFormat() == Qt.TextFormat.PlainText for box in shown
    )

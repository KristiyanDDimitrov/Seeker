"""Text from outside Seeker renders literally in the UI.

A peer's filename or username, a playlist name, slskd's log text: left
at Qt's `AutoText`, a label, tooltip or message box renders any of them
as HTML once something tag-like appears before the first line break.
The sweeps below are structural (`ast`), so a label, message box or
tooltip added anywhere in `ui/` later is covered without a test of its
own.
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
# The one module allowed to build these directly: it is where the
# explicit format is set.
_HELPER = _UI_DIR / "plain_text.py"


def _ui_calls() -> list[tuple[Path, ast.Call]]:
    calls = []
    for path in sorted(_UI_DIR.rglob("*.py")):
        if path == _HELPER:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        calls.extend(
            (path, node) for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        )
    return calls


def _where(path: Path, node: ast.AST) -> str:
    return f"{path.relative_to(_UI_DIR)}:{node.lineno}"


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


def test_every_dynamic_tooltip_goes_through_plain_tooltip():
    violations = [
        f"{_where(path, call)}: {ast.unparse(call.args[0])}"
        for path, call in _ui_calls()
        if isinstance(call.func, ast.Attribute)
        and call.func.attr == "setToolTip"
        and call.args
        and not _is_fixed_text(call.args[0])
        and not _is_plain_tooltip_call(call.args[0])
    ]

    assert violations == [], (
        "a tooltip auto-detects rich text; wrap dynamic text in "
        "plain_tooltip():\n" + "\n".join(violations)
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

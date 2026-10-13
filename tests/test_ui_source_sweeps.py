"""Source sweeps over `src/seeker/ui/`: conventions an `ast` or text
scan can enforce for every widget at once.
"""
import ast
from pathlib import Path


def test_no_selector_less_setstylesheet_call_anywhere_in_ui():
    # Roadmap item E3.6 (round 7) — the actual mechanism behind E3, not
    # just that one symptom: Qt parses a `setStyleSheet()` string with
    # no selector as a universal `* {...}` rule, applying it to the
    # target widget AND EVERY DESCENDANT — this is what silently
    # stripped a QProgressBar's border inside make_card() (E3) and was
    # present in two more places (`cell_widget()`'s container,
    # `ThemeToggleButton`) that happened not to cause visible harm yet.
    # A real rule always contains a `{` (selector, then a brace, then
    # properties); a bare declaration list like "border: none;" never
    # does — checked structurally via `ast`, not by re-reading these
    # three call sites by eye, so a future one added anywhere in ui/ is
    # covered automatically.
    import ast

    import seeker.ui as ui_package

    def rendered_text(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            # Interpolated values (ACCENT, PROGRESS_BAR_RADIUS, etc.)
            # are never selector/brace syntax themselves — a placeholder
            # preserves the surrounding literal text's structure.
            return "".join(
                str(part.value) if isinstance(part, ast.Constant) else "X"
                for part in node.values
            )
        return None

    ui_dir = Path(ui_package.__file__).parent
    violations = []
    for path in sorted(ui_dir.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setStyleSheet"
                and len(node.args) == 1
            ):
                continue
            text = rendered_text(node.args[0])
            # "" clears a widget's own sheet: no declarations, so
            # nothing that could cascade. Any non-blank text is checked.
            if text is not None and text.strip() and "{" not in text:
                violations.append(f"{path.name}:{node.lineno}: {text!r}")

    assert violations == [], (
        "selector-less setStyleSheet() call(s) found (Qt parses these "
        "as a universal `* {...}` rule that cascades onto every "
        "descendant widget):\n" + "\n".join(violations)
    )


def test_no_private_application_attribute_access_in_ui():
    # Round 8 §7.1.3 — CLAUDE.md's layering rule ("every Qt widget goes
    # through Application, never past it") held in letter (no repository
    # imports in ui/) but not in spirit: sixteen read sites and one WRITE
    # reached straight into self.application._config_store/
    # _slskd_base_url/_slskd_api_key, bypassing update_settings()'s
    # persistence/cache-invalidation entirely (§7.1.1/§7.1.2 added the
    # public settings/update_settings/slskd_base_url/slskd_api_key
    # surface and replaced every one of those sixteen). Checked
    # structurally via ast, not by re-reading call sites by eye, so a
    # future one added anywhere in ui/ (including ui/pages/* once Phase
    # 6 lands) is caught automatically.
    import ast

    import seeker.ui as ui_package

    ui_dir = Path(ui_package.__file__).parent
    violations = []
    for path in sorted(ui_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "application"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
            ):
                continue
            violations.append(f"{path.name}:{node.lineno}: {node.attr}")

    assert violations == [], (
        "private Application attribute access found (presentation-layer "
        "code must go through a public Application property/method, "
        "never self.application._*):\n" + "\n".join(violations)
    )


def test_no_stray_ampersand_mnemonic_in_button_or_label_text():
    # Roadmap item 79 (P12) — a bare "&" in a QPushButton/QLabel string
    # literal is a real Qt keyboard-mnemonic marker (consumed, renders
    # as an underline under the next character — "Rescan & match
    # library" rendered as "Rescan _match library"), not a literal
    # ampersand. "&Help" on the real menu bar is the one intentional
    # mnemonic in this file; "&&" escapes to a literal "&" and is not
    # flagged. A source-level scan, not a widget-by-widget assertion,
    # so a future string added anywhere in this file is covered
    # automatically.
    import re

    import seeker.ui.main_window as main_window_module

    source = Path(main_window_module.__file__).read_text()
    literals = re.findall(
        r'(?:QPushButton|PlainLabel|RichLabel)\(\s*"([^"]*)"', source,
    )
    stray = [
        text for text in literals
        if "&" in text and "&&" not in text and text != "&Help"
    ]
    assert stray == []


# Every call that hands a task a button to disable and give back, by
# the callee's name: the button's keyword and its positional index.
# `start_slskd` is the slskd_status helper, called by bare name (the
# Application method of that name takes no button).
_BUTTON_TAKERS = {
    "run_worker": ("button", 2),
    "run_busy_worker": ("button", 1),
    "_run_busy_worker": ("button", 1),
    "pick_and_add_library_location": ("button", 4),
    "start_slskd": ("button", 1),
}
# The two helpers above forward their own caller's `button` parameter;
# this sweep checks each of their callers in turn, so a per-row button
# cannot reach a task through them either.
_FORWARDED_BUTTONS = {
    ("library_location_picker.py", "button"),
    ("slskd_status.py", "button"),
}


def _is_self_attribute(node):
    while isinstance(node, ast.Attribute):
        node = node.value
    return isinstance(node, ast.Name) and node.id == "self"


def test_a_task_button_is_a_page_attribute_or_none():
    # A per-row button is deleted by the next rebuild while its task
    # runs, and a rebuilt row's new button never learns the task is
    # running, so it offers the action again (HISTORY §227). A row's
    # running state goes in ui/row_actions.RunningRows; a task's button
    # is a widget that outlives every render: a `self.` attribute.
    import seeker.ui as ui_package

    ui_dir = Path(ui_package.__file__).parent
    checked = 0
    violations = []
    for path in sorted(ui_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute) and func.attr != "start_slskd":
                name = func.attr
            else:
                continue
            if name not in _BUTTON_TAKERS:
                continue
            keyword, index = _BUTTON_TAKERS[name]
            given = [k.value for k in node.keywords if k.arg == keyword]
            if len(node.args) > index:
                given.append(node.args[index])
            for button in given:
                checked += 1
                if (
                    (isinstance(button, ast.Constant) and button.value is None)
                    or _is_self_attribute(button)
                    or (
                        isinstance(button, ast.Name)
                        and (path.name, button.id) in _FORWARDED_BUTTONS
                    )
                ):
                    continue
                violations.append(
                    f"{path.name}:{node.lineno}: {name}(… {ast.unparse(button)})"
                )

    # The sweep found the calls it exists for (a renamed helper would
    # otherwise pass it vacuously).
    assert checked > 30
    assert violations == [], (
        "a task's button that a rebuild can delete; keep the row's "
        "running state in RunningRows instead:\n" + "\n".join(violations)
    )

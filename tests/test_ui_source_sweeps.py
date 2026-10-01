"""Source sweeps over `src/seeker/ui/`: conventions an `ast` or text
scan can enforce for every widget at once.
"""
from pathlib import Path


def test_no_selector_less_setstylesheet_call_anywhere_in_ui():
    # Roadmap item E3.6 (round 7) — the actual mechanism behind E3, not
    # just that one symptom: Qt parses a `setStyleSheet()` string with
    # no selector as a universal `* {...}` rule, applying it to the
    # target widget AND EVERY DESCENDANT — this is what silently
    # stripped a QProgressBar's border inside make_card() (E3) and was
    # present in two more places (`cell_widget()`'s container,
    # `_ThemeToggleButton`) that happened not to cause visible harm yet.
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
            if text is not None and "{" not in text:
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

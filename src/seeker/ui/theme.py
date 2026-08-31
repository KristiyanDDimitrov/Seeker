"""Seeker's dark design system: color tokens, spacing/radius tokens,
and the one global stylesheet applied to every window.

Layout conventions (read once, apply everywhere — nothing here is
enforced by code, so a future page must follow this by hand):

- Every page: `setContentsMargins(24, 20, 24, 20)`, `setSpacing(12)`.
  Nothing touches a window edge.
- Every action row: `QHBoxLayout`, primary action first (left),
  secondaries after, `addStretch()` at the end. Never centred.
  Destructive actions go after the stretch, right-aligned.

Accent discipline: ACCENT is for the active nav item, exactly one
primary button per screen, focus rings, progress fill, table
selection, links, and the "In library" badge. Nothing else — two
violet buttons on one screen means one of them is wrong.

Dark only for now (light is a real possible future addition — token
names are theme-neutral so adding a light palette later is cheap, not
a rewrite).
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# --- Color tokens ----------------------------------------------------------

BG_APP = "#121016"
BG_SIDEBAR = "#17141F"
BG_SURFACE = "#1C1926"
BG_SURFACE_2 = "#232030"

BORDER = "#302C3E"
BORDER_STRONG = "#423C55"

TEXT = "#ECEAF3"
TEXT_MUTED = "#9E98B3"
TEXT_FAINT = "#6F6987"

ACCENT = "#7C5CFF"
ACCENT_HOVER = "#8E72FF"
ACCENT_PRESSED = "#6446E0"
ACCENT_SUBTLE = "#241E3D"

SUCCESS = "#3FBF7F"
WARNING = "#E0A33E"
DANGER = "#E5484D"

# --- Spacing / radius tokens -------------------------------------------------

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24

RADIUS_CONTROL = 6
RADIUS_CARD = 10


def set_variant(widget: QWidget, variant: str | None) -> None:
    """Set a widget's `variant` dynamic property (used by the
    stylesheet's `[variant="..."]` selectors, e.g. QPushButton
    `primary`/`danger`) and force Qt to re-poll the stylesheet for it.
    Qt caches style-sheet-selector results per widget — a plain
    `setProperty()` call alone doesn't repaint with the new rule
    applied, so every call site needing a runtime variant change (not
    just one set once at construction) must go through this rather
    than calling `setProperty()` directly.
    """
    widget.setProperty("variant", variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def apply_theme(app: QApplication) -> None:
    """Call once, before any window is constructed. Sets Fusion (so the
    stylesheet below renders identically on macOS and Windows — real
    concern here, since Windows packaging is still unverified per
    CLAUDE.md item 36), a matching QPalette (so anything Qt draws
    natively — native dialogs, menus opened via the system menu bar —
    still matches instead of falling back to the OS's own light theme),
    and the one global stylesheet.
    """
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_APP))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_SURFACE_2))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_SURFACE_2))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_SURFACE_2))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_FAINT))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(TEXT_FAINT),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(TEXT_FAINT),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(TEXT_FAINT),
    )
    app.setPalette(palette)

    app.setStyleSheet(STYLESHEET)


STYLESHEET = f"""
QWidget {{
    background-color: {BG_APP};
    color: {TEXT};
}}

QMainWindow, QDialog {{
    background-color: {BG_APP};
}}

QLabel {{
    background: transparent;
}}

QLabel[badge="ok"] {{
    color: {SUCCESS};
}}

QLabel[badge="warn"] {{
    color: {WARNING};
}}

QLabel[badge="muted"] {{
    color: {TEXT_MUTED};
}}

QPushButton {{
    background-color: {BG_SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 14px;
    color: {TEXT};
}}

QPushButton:hover {{
    border-color: {BORDER_STRONG};
}}

QPushButton:pressed {{
    background-color: {BG_SURFACE};
}}

QPushButton:disabled {{
    color: {TEXT_FAINT};
    border-color: {BORDER};
}}

QPushButton[variant="primary"] {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: {TEXT};
    font-weight: 600;
}}

QPushButton[variant="primary"]:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}

QPushButton[variant="primary"]:pressed {{
    background-color: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}

QPushButton[variant="danger"] {{
    background-color: {BG_SURFACE_2};
    border: 1px solid {DANGER};
    color: {DANGER};
}}

QPushButton[variant="danger"]:hover {{
    background-color: {DANGER};
    color: {TEXT};
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 4px 8px;
    selection-background-color: {ACCENT_SUBTLE};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}

QComboBox::drop-down {{
    border: none;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_SUBTLE};
    selection-color: {TEXT};
}}

QTableWidget, QListWidget {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
    gridline-color: {BORDER};
    selection-background-color: {ACCENT_SUBTLE};
    selection-color: {TEXT};
    alternate-background-color: {BG_SURFACE_2};
}}

QListWidget::item {{
    padding: 4px;
}}

/* Deliberately no `QTableWidget::item {{ padding: ... }}` rule — a
real, reproducible Qt/Fusion rendering bug (found live while
screenshotting the Dashboard for Phase 3): styling QTableWidget::item
padding corrupts the paint of any QPushButton living inside a cell
WIDGET (QTableWidget.setCellWidget — used throughout this app's
Actions/Progress columns), producing garbled, ghosted button text.
Confirmed via a bisected minimal repro; the identical rule on
QListWidget::item is safe since nothing in this app puts a widget
inside a QListWidget item. Table cell padding, if wanted later, must
come from row height instead. */

QHeaderView::section {{
    background-color: {BG_SURFACE};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
}}

QProgressBar {{
    background-color: {BG_SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    text-align: center;
    color: {TEXT_MUTED};
    max-height: 14px;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: {RADIUS_CONTROL}px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER_STRONG};
    background-color: {BG_SURFACE};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 7px;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {TEXT_FAINT};
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QToolTip {{
    background-color: {BG_SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 4px 6px;
}}

QMenuBar {{
    background-color: {BG_SIDEBAR};
    color: {TEXT};
}}

QMenuBar::item:selected {{
    background-color: {ACCENT_SUBTLE};
}}

QMenu {{
    background-color: {BG_SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}

QMenu::item:selected {{
    background-color: {ACCENT_SUBTLE};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 6px 14px;
}}

QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}
"""

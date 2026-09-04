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

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QHeaderView, QProgressBar,
    QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

# --- Color tokens ----------------------------------------------------------

BG_APP = "#100E15"
BG_SIDEBAR = "#15121D"
BG_SURFACE = "#1D1929"
BG_SURFACE_2 = "#29243A"

BORDER = "#3A344E"
BORDER_STRONG = "#4E4768"

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


def style_determinate_progress_bar(bar: QProgressBar) -> None:
    """Apply the accent chunk fill to a genuinely DETERMINATE
    QProgressBar (a real range + value already set) — never to an
    indeterminate one (`setRange(0, 0)`). See the stylesheet's own
    `QProgressBar::chunk` comment for why this can't just be a global
    QSS rule: any `::chunk` rule at all, regardless of its properties,
    replaces Qt's native animated "busy" indicator with a static block
    for every QProgressBar it matches, indeterminate ones included. A
    per-instance stylesheet, applied only here, keeps that global rule
    from ever existing in the first place.
    """
    bar.setStyleSheet(
        f"QProgressBar::chunk {{"
        f"  background-color: {ACCENT};"
        f"  border-radius: {RADIUS_CONTROL}px;"
        f"}}"
    )


def make_card(inner: QWidget) -> QFrame:
    """Roadmap item 80 (P10.1) — Qt's `border-radius` on a widget does
    NOT clip that widget's own children. Any child reaching a
    QTableWidget's/QListWidget's own edge (a full-width `setCellWidget`
    button, most commonly — see the Sharing table's "Add to my
    SoulSeek share" column) paints straight over that same widget's
    own rounded corner; no stylesheet rule can fix this, since the
    problem is paint ORDER/clipping, not color. The fix is structural:
    this QFrame owns the real rounded border/background (`QFrame#card`
    in STYLESHEET below); `inner` sits inside it with its OWN
    border/radius turned off and a small uniform content margin
    between them. That margin is the load-bearing part — it keeps any
    of `inner`'s own edge-reaching children (or `inner`'s own now-flat
    corners) physically away from the frame's rounded arc, so nothing
    can ever paint over it regardless of what `inner` contains.
    """
    frame = QFrame()
    frame.setObjectName("card")
    # Item 47's own standing gotcha (2): a QSS background/border on a
    # QWidget-derived class isn't painted by default unless this
    # attribute is set — QFrame is no exception in practice.
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    # Untuned, deliberately small and uniform — just enough that no
    # child of `inner` can reach into the frame's own rounded corner
    # arc (RADIUS_CARD's curve extends a few px inward from each
    # corner), not a visible "gap" of its own.
    margin = SPACING_XS
    layout.setContentsMargins(margin, margin, margin, margin)
    inner.setStyleSheet("border: none; border-radius: 0px;")
    layout.addWidget(inner)
    return frame


def cell_widget(*widgets: QWidget) -> QWidget:
    """Roadmap item 80 (P10.2) — the one place a `setCellWidget`
    container is built, replacing every hand-rolled `QWidget()` +
    `QHBoxLayout` + `setContentsMargins(0, 0, 0, 0)` at a call site
    across the app (they had all drifted into the identical pattern
    independently — the same kind of duplication this project's
    `matching.py`/`download_dedup.py` precedent exists to prevent).
    Real, visible margins/spacing instead of zero (jammed-together
    buttons, and buttons touching the table's own gridlines, were both
    part of the reported bug) — and a trailing stretch, so leftover
    cell width goes to blank space, not to stretching the last widget
    to fill the whole cell (P10.3 — a button reads as a button, not a
    filled cell).
    """
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(
        SPACING_SM, SPACING_XS, SPACING_SM, SPACING_XS,
    )
    layout.setSpacing(SPACING_SM)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    return container


def apply_table_defaults(table: QTableWidget) -> None:
    """Roadmap item R5 (5a.1 + 5b.2) — the shared baseline every real
    QTableWidget in this app should be constructed with.

    5a.1: hides the vertical (row-number) header. No table in this app
    has ever used it for anything (Duplicates has its own real Group
    column) — confirmed by grep before this fix existed, nothing in
    this file ever styled QHeaderView/QTableCornerButton, so the area
    of the vertical header below the last row painted the default
    palette color (a stray black column down the left edge), and the
    unstyled top-left corner button cut a black square into the card's
    own rounded corner (item 80 fixed the card's OWN border but not
    this).

    5b.2: floors row height at a real `cell_widget()`'s own
    `sizeHint().height()` — Qt's default row height is shorter than
    that container (button + item 80's own real margins), which is
    what sliced "Replace"/"Decline" off at the bottom before this.
    Applied via the vertical header's `setMinimumSectionSize` (a real
    floor `resizeRowsToContents()` can't shrink below), not
    `setDefaultSectionSize` (only affects brand-new rows, not a floor).
    """
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setMinimumSectionSize(40)

    representative_row_height = cell_widget(
        QPushButton("Sample")
    ).sizeHint().height()
    table.verticalHeader().setMinimumSectionSize(representative_row_height)


def size_action_column(
        table: QTableWidget, column: int, action_widgets: list[QWidget],
) -> None:
    """Roadmap item R5 (5b.1) — the shared form of the fix items 73/82
    each wrote once for themselves (`_size_duplicates_columns`/
    `_size_search_columns`), extracted so every table with a real
    Actions column gets it instead of a tenth hand-rolled copy. Widens
    the column to the WIDEST real Actions widget built this render
    (never a magic number) — the actual fix for "Confirm" reading as
    "onfirm": nothing in the other 8 tables named in this item ever
    set a derived width for this column before, so Qt's own
    stretch-last-section leftover-space math could squeeze it to a
    sliver. Caller must have already called
    `header.setStretchLastSection(False)` — stretch-last overrides any
    resize mode set on the last section, Fixed included, if this
    column happens to be the last one.
    """
    header = table.horizontalHeader()
    action_width = max(
        (widget.sizeHint().width() for widget in action_widgets),
        default=header.minimumSectionSize(),
    )
    header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
    header.resizeSection(column, action_width)

    # Roadmap item R5 (5b.2) — apply_table_defaults()'s
    # setMinimumSectionSize() floor already raises every row to a safe
    # height with no explicit call needed (confirmed empirically: a
    # bare setRowCount() after it already reports the floored height).
    # This call is what lets a row grow TALLER than that floor for
    # real content that needs it (e.g. a future wrapped multi-line
    # cell), on every table that has real per-row Actions widgets to
    # measure content against.
    table.resizeRowsToContents()


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

/* Sidebar nav items — transparent by default (deliberately NOT the
ordinary QPushButton surface/border look above; a flat text-only
button reads better in a list of nav items than a row of boxed
buttons), ACCENT_SUBTLE fill + a 3px ACCENT left border when the
active page's own nav button is checked. */
QPushButton[navItem="true"] {{
    background-color: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0px;
    text-align: left;
    padding: 8px {SPACING_MD}px;
    color: {TEXT_MUTED};
}}

QPushButton[navItem="true"]:hover {{
    background-color: {BG_SURFACE_2};
    color: {TEXT};
}}

QPushButton[navItem="true"]:checked {{
    background-color: {ACCENT_SUBTLE};
    border-left: 3px solid {ACCENT};
    color: {TEXT};
    font-weight: 600;
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

/* Roadmap item 80 (P10.1) — the real rounded border for a table/list
routed through make_card(); the inner QTableWidget/QListWidget itself
gets border:none/border-radius:0 per-instance (see make_card's own
docstring) so this is the ONLY rounded edge actually painted. */
QFrame#card {{
    background-color: {BG_SURFACE};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CARD}px;
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
    /* Roadmap item 97 (B2.1) — a real regression from item 47: once
    ANY QHeaderView::section rule exists, Qt paints the header entirely
    from this box model, so `border: none` above removed the native
    left/right section divider with no fallback underneath — "I can
    drag the column to resize it but I can't see where it is" is
    exactly that missing edge. */
    border-right: 1px solid {BORDER};
    padding: 6px;
}}

/* Suppresses the divider on the trailing section — nothing to
separate it FROM on that side. Qt's support for `:last`/`:horizontal:
last-child` on QHeaderView::section is version-dependent; if this
doesn't take on some platform, a divider surviving on the last column
is a cosmetic nit, not a reason to drop the fix above. */
QHeaderView::section:last {{
    border-right: none;
}}

QHeaderView::section:horizontal:last-child {{
    border-right: none;
}}

/* Roadmap item R5 (5a.2) — belt and braces alongside
apply_table_defaults() hiding the vertical header outright: a future
table that genuinely wants row numbers back would otherwise repaint
the exact same black-column/black-corner defects this item fixes,
since QHeaderView::section above only styles the section painting, not
the header/corner-button WIDGETS themselves (the area below the last
row, and the top-left corner button between the two headers, have no
section to match that rule at all). */
QHeaderView {{
    background-color: {BG_SURFACE};
    border: none;
}}

QTableCornerButton::section {{
    background-color: {BG_SURFACE};
    border: none;
}}

QProgressBar {{
    background-color: {BG_SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    text-align: center;
    color: {TEXT_MUTED};
    max-height: 14px;
}}

/* Deliberately no global `QProgressBar::chunk` rule here — found live
while re-rendering the Downloads tab: a genuinely indeterminate bar
(setRange(0, 0), Qt's own native "busy" mode) renders as an animated,
moving diagonal-striped pattern by default — but the INSTANT any
`::chunk` rule matches a QProgressBar, Qt switches that sub-control to
the QSS box-model painter for ALL its states, indeterminate included,
which has no concept of the native busy animation and just paints a
static solid rect instead. Confirmed by bisection: a bare
`QProgressBar {{ ... }}` container rule alone preserves the native
animated stripe; adding ANY `::chunk` rule back (even one with no
background-color at all) replaces it with a static block that reads as
"stuck at 100%," not "in progress." There is no `:indeterminate`
pseudo-state in Qt's QSS to scope a `::chunk` rule around, so the
accent fill for a genuinely DETERMINATE bar is applied locally, per
instance, via `style_determinate_progress_bar()` below — never here,
never globally. */

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

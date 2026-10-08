"""Seeker's design system: color tokens (dark + light), spacing/radius
tokens, and the one global stylesheet applied to every window.

Layout conventions (read once, apply everywhere — nothing here is
enforced by code, so a future page must follow this by hand):

- Every page: `setContentsMargins(24, 20, 24, 20)`, `setSpacing(12)`.
  Nothing touches a window edge.
- Every action row: `QHBoxLayout`, primary action first (left),
  secondaries after, `addStretch()` at the end. Never centred.
  Destructive actions go after the stretch, right-aligned.
  `action_row()` builds one; a button never sits alone in a vertical
  or form layout, where it would stretch to the full width.

Accent discipline: ACCENT is for the active nav item, exactly one
primary button per screen, focus rings, progress fill, table
selection, links, and the "In library" badge. Nothing else — two
violet buttons on one screen means one of them is wrong.

Architecture, read before touching a color (HISTORY §107): `Palette` is
the source of truth (`DARK`/`LIGHT` below), and `active_palette()` is
the one that `apply_theme()` last applied. Code that paints or renders
reads `active_palette()` at that moment, never caches a token, so it
follows a theme switch. Prefer routing a label/panel's color through an
`objectName` + a rule in `build_stylesheet()` over reading a token at
all: `QApplication.setStyleSheet()` re-polishes every widget matching a
rule on re-apply, so it needs no theme-change handler code. Anything
that bakes a token into a widget at build time (a table item's
foreground) must be rebuilt when the theme changes;
`MainWindow.on_theme_changed()` is where that rebuilding happens.
"""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QProgressBar,
    QProxyStyle,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleFactory,
    QStyleHintReturn,
    QStyleOption,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.ui.elided_text import elide_table_cells, set_path_columns
from seeker.ui.plain_text import PlainLabel

logger = logging.getLogger(__name__)

# --- Palettes ----------------------------------------------------------

ThemeMode = str  # "system" | "light" | "dark" — see resolve_palette()


@dataclass(frozen=True)
class Palette:
    """Every color token this app uses. A frozen dataclass (not a
    dict) so a typo in a future field name is a real `AttributeError`
    at the call site, not a silent `None`."""

    BG_APP: str
    BG_SIDEBAR: str
    BG_SURFACE: str
    BG_SURFACE_2: str
    BORDER: str
    BORDER_STRONG: str
    TEXT: str
    TEXT_MUTED: str
    TEXT_FAINT: str
    ACCENT: str
    ACCENT_HOVER: str
    ACCENT_PRESSED: str
    ACCENT_SUBTLE: str
    SELECTION: str
    SUCCESS: str
    WARNING: str
    CUE: str
    DANGER: str
    ON_ACCENT: str


# "Booth" with a violet accent (docs/design/visual-direction.md):
# neutral graphite surfaces, so the accent marks only selection, focus
# and the primary action, and the status colours read like a CDJ's
# lamps: SUCCESS is play (in library), CUE is cue (working, or waiting
# on you), DANGER is not found. WARNING is the cue's text-grade amber
# (4.5:1); CUE fills the lamps and meters, which need only 3:1.
# test_theme.py asserts every contrast pair this module relies on.
DARK = Palette(
    BG_APP="#17191C",
    BG_SIDEBAR="#101113",
    BG_SURFACE="#1E2125",
    BG_SURFACE_2="#282C31",
    BORDER="#353A40",
    BORDER_STRONG="#4C535B",
    TEXT="#E8EAEC",
    TEXT_MUTED="#A0A7AE",
    TEXT_FAINT="#737B83",
    # A lit violet: white on it would be 3.1:1, so it carries dark
    # text, like a backlit pad.
    ACCENT="#9A7DFF",
    ACCENT_HOVER="#AA91FF",
    ACCENT_PRESSED="#8A6BF5",
    ACCENT_SUBTLE="#262236",
    # Selected text and rows: TEXT on a mid violet, which stands off
    # the field (ACCENT_SUBTLE barely does) and keeps every status lamp
    # at 3:1. The one selection pair, palette and stylesheet alike.
    SELECTION="#4A3799",
    SUCCESS="#35D07F",
    WARNING="#FFB020",
    CUE="#FFB020",
    DANGER="#FF6363",
    # Text on a saturated ACCENT/DANGER fill. Its own token because it
    # is not TEXT in either theme: dark ink on dark mode's lit accent,
    # white on light mode's deep one.
    ON_ACCENT="#120E1F",
)

# Elevation is preserved, lightness is not: in dark, higher elevation
# gets LIGHTER; here it gets WHITER, over a grey page ground, so a card
# (BG_SURFACE) reads as coming forward. The sidebar stays the recessed
# chrome in both. ACCENT is a deep violet under white text.
LIGHT = Palette(
    BG_APP="#E8EAEC",
    BG_SIDEBAR="#DDE0E3",
    BG_SURFACE="#F9FAFA",
    BG_SURFACE_2="#F0F2F3",
    BORDER="#CBD0D5",
    BORDER_STRONG="#9BA3AB",
    TEXT="#15181B",
    TEXT_MUTED="#4D555D",
    TEXT_FAINT="#757D85",
    ACCENT="#6440E6",
    ACCENT_HOVER="#5734D6",
    ACCENT_PRESSED="#4A2BBD",
    ACCENT_SUBTLE="#E9E4FB",
    SELECTION="#E4DDFB",
    SUCCESS="#11804A",
    WARNING="#9E5C00",
    # The lightest golden amber still 3:1 on a card, the page ground
    # and a selected row; text-grade WARNING reads brown as a fill.
    CUE="#AD7400",
    DANGER="#C22B2B",
    ON_ACCENT="#FFFFFF",
)


def _relative_luminance(hex_color: str) -> float:
    """Real WCAG 2.x relative luminance, so contrast is a test, not a
    claim. No third-party dependency; the formula is short enough to own
    directly and verify against known reference values in tests (pure
    black/white)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (
        int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4)
    )

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio between two colors, always >= 1.0
    regardless of argument order (lighter over darker)."""
    l_a = _relative_luminance(hex_a)
    l_b = _relative_luminance(hex_b)
    lighter, darker = max(l_a, l_b), min(l_a, l_b)
    return (lighter + 0.05) / (darker + 0.05)


def resolve_palette(mode: ThemeMode) -> Palette:
    """`"light"`/`"dark"` resolve directly; `"system"` (and anything
    else unrecognized — same guarded-default discipline as
    `config_store.load_config`) asks the real OS via
    `QGuiApplication.styleHints().colorScheme()`.
    `Qt.ColorScheme.Unknown` (a platform that can't report one) falls
    back to `DARK` — today's standing behavior, preserved on purpose.
    """
    if mode == "light":
        return LIGHT
    if mode == "dark":
        return DARK

    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return LIGHT
    return DARK


@dataclass
class _ActivePalette:
    palette: Palette


_active = _ActivePalette(DARK)


def active_palette() -> Palette:
    """The palette `apply_theme` last applied; `DARK` before the first
    call. Read it when painting or rendering, never keep it: a theme
    switch replaces it."""
    return _active.palette


# --- Spacing / radius tokens (theme-independent) ----------------------------

SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 12
SPACING_LG = 16
SPACING_XL = 24

# Tight, like hardware: a control is a key cap, a card a panel.
RADIUS_CONTROL = 4
RADIUS_CARD = 6

# Track and fill are the SAME pill shape at 0%, mid-download and 100%.
# The radius is derived from the height (never a literal), so the two
# can never drift apart.
PROGRESS_BAR_HEIGHT = 14
PROGRESS_BAR_RADIUS = PROGRESS_BAR_HEIGHT // 2

# A meter: determinate progress drawn as a hardware level meter, lit
# segments on a squarer track. Its width fits the Progress header.
METER_WIDTH = 72
METER_RADIUS = 2
METER_SEGMENT_WIDTH = 5
METER_SEGMENT_GAP = 1

# A status chip is a pill, its radius derived the same way.
CHIP_HEIGHT = 26
CHIP_RADIUS = CHIP_HEIGHT // 2

# --- Type (theme-independent) ----------------------------------------------

# Panel lettering, as on a mixer's faceplate: the wordmark, page titles
# and section headers. Everything else stays on the system UI font.
DISPLAY_FAMILY = "Barlow Semi Condensed"
TYPE_TITLE_PX = 26
TYPE_SECTION_PX = 16
# The two weights bundled. QSS takes the number.
WEIGHT_MEDIUM = 500
WEIGHT_SEMIBOLD = 600

# A sidebar item's icon, on Lucide's 24-unit grid scaled to sit beside
# body text.
NAV_ICON_PX = 18

# A splitter handle's grab area. Odd, so its 1px line has a centre
# pixel (see the QSplitter rules in _misc_qss).
SPLITTER_GRAB_WIDTH = 7


def bundled_dir(name: str) -> Path:
    """`packaging/<name>/` in a source tree; the `<name>/` directory
    `seeker.spec` bundles in a frozen build."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[3] / "packaging" / name
    return Path(sys._MEIPASS) / name  # type: ignore[attr-defined]  # noqa: SLF001


def load_fonts(directory: Path) -> None:
    """Registers every `.ttf` in `directory` with Qt. A file Qt cannot
    read is logged and skipped: its role falls back to the system
    font rather than stopping the app."""
    for path in sorted(directory.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) == -1:
            logger.warning("Could not load the bundled font %s", path)


def register_display_font() -> None:
    """Makes `DISPLAY_FAMILY` available, once per process (a second
    `addApplicationFont` of the same file would register it again)."""
    if DISPLAY_FAMILY not in QFontDatabase.families():
        load_fonts(bundled_dir("fonts"))


def _palette_icon(stem: str, palette: Palette) -> Path:
    """A QSS `image:` takes a file, not a color, so each palette has
    its own bundled SVG; `test_theme.py` fails if one drifts from its
    token."""
    name = "light" if palette == LIGHT else "dark"
    return bundled_dir("icons") / f"{stem}_{name}.svg"


def combo_chevron_path(palette: Palette) -> Path:
    """The drop-down chevron, drawn in `palette.TEXT_MUTED`."""
    return _palette_icon("combo_chevron", palette)


def spin_up_arrow_path(palette: Palette) -> Path:
    """A spin box's up chevron, drawn in `palette.TEXT_MUTED`."""
    return _palette_icon("spin_up", palette)


def spin_down_arrow_path(palette: Palette) -> Path:
    """A spin box's down chevron, drawn in `palette.TEXT_MUTED`."""
    return _palette_icon("spin_down", palette)


def check_tick_path(palette: Palette) -> Path:
    """A checked checkbox's tick, drawn in `palette.ON_ACCENT` over the
    ACCENT fill, so the state does not rest on colour alone."""
    return _palette_icon("check_tick", palette)


def set_dynamic_property(widget: QWidget, name: str, value: str | None) -> None:
    """Set a dynamic property used by a `[name="value"]` stylesheet
    selector (e.g. QPushButton's `variant`, QLabel's `badge`) and force
    Qt to re-poll the stylesheet for it. Qt caches style-sheet-selector
    results per widget — a plain `setProperty()` call alone doesn't
    repaint with the new rule applied, so every call site needing a
    runtime property change (not just one set once at construction)
    must go through this rather than calling `setProperty()` directly.
    """
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_variant(widget: QWidget, variant: str | None) -> None:
    set_dynamic_property(widget, "variant", variant)


def style_meter(bar: QProgressBar) -> None:
    """Determinate progress as a meter: cue-amber segments (work in
    progress, the same amber as a working lamp) and no label; the
    percentage, where one shows, is text beside it. A per-instance
    sheet, never a global `::chunk` rule (see the stylesheet's
    `QProgressBar` comment), so call it again after a theme switch."""
    bar.setTextVisible(False)
    bar.setFormat("")
    bar.setStyleSheet(
        f"QProgressBar {{ border-radius: {METER_RADIUS}px; }}"
        f"QProgressBar::chunk {{"
        f"  background-color: {active_palette().CUE};"
        f"  width: {METER_SEGMENT_WIDTH}px;"
        f"  margin: {METER_SEGMENT_GAP}px;"
        f"  border-radius: 1px;"
        f"}}"
    )


def set_indeterminate(bar: QProgressBar) -> None:
    """Qt's animated busy bar, with any determinate fill a bar was
    given removed first: a `::chunk` rule left behind paints a static
    block instead of the animation."""
    bar.setStyleSheet("")
    bar.setRange(0, 0)


def set_busy_meter(bar: QProgressBar) -> None:
    """A meter whose amount is not known yet: Qt's busy animation in
    the cue amber of a working lamp, not the accent. The colour is set
    on the bar's palette, so call it again after a theme switch."""
    set_indeterminate(bar)
    palette = bar.palette()
    palette.setColor(
        QPalette.ColorRole.Highlight, QColor(active_palette().CUE),
    )
    bar.setPalette(palette)


def wrap_progress_bar(bar: QProgressBar, label_text: str | None) -> QWidget:
    """The one place a progress bar gets put into a cell-ready
    container. A bare bar returned directly from a `setCellWidget` call
    gets resized to the full cell rect by Qt, and the global
    stylesheet's `QProgressBar { max-height: 14px; }` then clamps it to
    the TOP of that tall cell instead of centering it. `label_text=None`
    omits the label entirely (an indeterminate "busy" bar has nothing
    determinate to show an ETA for). Shared by the Downloads page's own
    progress cells and the Dashboard's track_table. See HISTORY §96.

    A fixed-width bar (a meter) sits at the cell's left edge with or
    without a label, so a column of them lines up."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(bar, 1)
    if label_text is not None:
        layout.addWidget(PlainLabel(label_text))
    layout.addStretch()
    return container


def scrollable(content: QWidget) -> QScrollArea:
    """`content` in a frameless scroll area, so a page or tab taller
    than the window scrolls instead of squeezing its rows below their
    size."""
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll_area.setWidget(content)
    return scroll_area


# Prose wraps at a reading measure, not the window's width.
READING_MEASURE_CHARS = 80


def _reading_width(widget: QWidget) -> int:
    return widget.fontMetrics().averageCharWidth() * READING_MEASURE_CHARS


def set_reading_measure(label: QLabel) -> None:
    """Caps a wrapping `label` at about `READING_MEASURE_CHARS` of its
    own font. Only where `label` is a scroll area's whole content: in a
    layout row wider than the cap, the row measures the label's height
    at the row's width and clips the wrapped lines (seen on Help)."""
    label.setWordWrap(True)
    label.setMaximumWidth(_reading_width(label))


def reading_column(column: QWidget) -> QWidget:
    """`column` capped at the reading measure, left-aligned, with the
    rest of the width a stretch. A horizontal layout gives each item
    its real width before asking its height, so wrapped labels inside
    `column` are measured at the width they get."""
    column.setMaximumWidth(_reading_width(column))
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    # The column's stretch factor, not the spacer's: the column grows
    # to its cap first and the spacer takes only what is left.
    layout.addWidget(column, 1)
    layout.addStretch()
    return row


def make_card(inner: QWidget) -> QFrame:
    """Qt's `border-radius` on a widget does NOT clip that widget's own
    children. Any child reaching a QTableWidget's/QListWidget's own edge
    (a full-width `setCellWidget` button, most commonly — see the
    Sharing table's "Add to my SoulSeek share" column) paints straight
    over that same widget's own rounded corner; no stylesheet rule can
    fix this, since the problem is paint ORDER/clipping, not color. The
    fix is structural: this QFrame owns the real rounded
    border/background (`QFrame#card` in STYLESHEET below); `inner` sits
    inside it with its OWN border/radius turned off and a small uniform
    content margin between them. That margin is the load-bearing part —
    it keeps any of `inner`'s own edge-reaching children (or `inner`'s
    own now-flat corners) physically away from the frame's rounded arc,
    so nothing can ever paint over it regardless of what `inner`
    contains. See HISTORY §80.
    """
    frame = QFrame()
    frame.setObjectName("card")
    # A QSS background/border on a QWidget-derived class isn't painted
    # by default unless this attribute is set — QFrame is no exception
    # in practice (HISTORY §47).
    frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    layout = QVBoxLayout(frame)
    # Untuned, deliberately small and uniform — just enough that no
    # child of `inner` can reach into the frame's own rounded corner
    # arc (RADIUS_CARD's curve extends a few px inward from each
    # corner), not a visible "gap" of its own.
    margin = SPACING_XS
    layout.setContentsMargins(margin, margin, margin, margin)
    # Never a per-widget `inner.setStyleSheet(...)`: Qt parses a
    # selector-less declaration list as a universal `* {...}` rule,
    # which strips border/radius off EVERY descendant widget BOX (a
    # QProgressBar's track, the most visible case), not just `inner`
    # itself. Scoped via objectName instead — `#cardInner` in
    # build_stylesheet's `QFrame#card` block. No make_card() caller
    # gives `inner` an objectName of its own. See HISTORY §114.
    inner.setObjectName("cardInner")
    layout.addWidget(inner)
    return frame


def section_card(
        title: str, explanation: str, *rows: QWidget | QLayout,
) -> QFrame:
    """One job's card: its title in the panel lettering, one sentence
    saying what its controls do, then the controls. The title is also
    the card's accessible name."""
    inner = QWidget()
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
    layout.setSpacing(SPACING_SM)

    heading = PlainLabel(title)
    heading.setObjectName("sectionHeaderLabel")
    layout.addWidget(heading)

    label = PlainLabel(explanation)
    label.setWordWrap(True)
    label.setProperty("badge", "muted")
    layout.addWidget(label)

    for row in rows:
        if isinstance(row, QLayout):
            layout.addLayout(row)
        else:
            layout.addWidget(row)

    card = make_card(inner)
    card.setAccessibleName(title)
    return card


def action_row(*widgets: QWidget) -> QHBoxLayout:
    """A row of buttons at their size hint, left-aligned: `widgets`
    in order, then a stretch that takes the leftover width. A button
    added straight to a vertical or form layout stretches to the full
    width instead. A layout that wants a full-width primary sets the
    button's `fullWidth` property, which the button-sizing sweep
    honours."""
    row = QHBoxLayout()
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch()
    return row


def cell_widget(*widgets: QWidget, row_label: str | None = None) -> QWidget:
    """The one place a `setCellWidget` container is built — no call
    site hand-rolls a `QWidget()` + `QHBoxLayout` of its own. Real,
    visible margins/spacing instead of zero (so buttons neither jam
    together nor touch the table's gridlines), and a trailing stretch,
    so leftover cell width goes to blank space, not to stretching the
    last widget to fill the whole cell — a button reads as a button,
    not a filled cell. See HISTORY §80.

    `row_label` names each button for its row ("Confirm Nova Reyes -
    Voltage Drop"): a screen reader announces a cell's button on its
    own, without the row around it. Every row with a button passes
    one.
    """
    container = QWidget()
    # Transparent via `#cellWidgetContainer` in build_stylesheet, never
    # a selector-less per-widget `setStyleSheet()`, which Qt parses as a
    # universal `* {...}` rule over every descendant.
    container.setObjectName("cellWidgetContainer")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(
        SPACING_SM, SPACING_XS, SPACING_SM, SPACING_XS,
    )
    layout.setSpacing(SPACING_SM)
    for widget in widgets:
        # A click gives a StrongFocus button real keyboard focus;
        # disabling it later (run_worker's pattern) then makes Qt
        # synthesize a Tab press on its behalf via focusNextChild(),
        # walking the table's current cell one column to the right per
        # click. NoFocus stops the button from ever taking focus in the
        # first place. Nothing is lost for keyboard users —
        # tabKeyNavigation (on by default) already moves between cells
        # without ever entering a cell widget. See HISTORY §126.
        if isinstance(widget, QAbstractButton):
            widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if row_label is not None:
                widget.setAccessibleName(f"{widget.text()} {row_label}")
        layout.addWidget(widget)
    layout.addStretch()
    return container


def header_label_floor(table: QTableWidget, column: int) -> int:
    """The minimum pixel width a header SECTION needs so its own label
    never clips, independent of whatever real per-row content that
    column happens to hold this render (which may be nothing at all — an
    empty table, where a generic 40px floor reads "Actions" as ".ction";
    HISTORY §104). `QFontMetrics.horizontalAdvance` measures the
    header's own real rendered text; the two `6`s mirror the QSS
    `padding: 6px` on both sides of `QHeaderView::section` (this file's
    own STYLESHEET) and the `+ 1` leaves room for the header's column
    divider itself, so the label's last character never touches it.
    """
    header = table.horizontalHeader()
    item = table.horizontalHeaderItem(column)
    text = item.text() if item is not None else ""
    metrics = QFontMetrics(header.font())
    return metrics.horizontalAdvance(text) + 6 + 6 + 1


def apply_table_defaults(table: QTableWidget) -> None:
    """The shared baseline every real QTableWidget in this app should be
    constructed with (HISTORY §87).

    Hides the vertical (row-number) header. No table uses it
    (Duplicates has its own real Group column), and left visible, the
    area below the last row paints a stray black column down the left
    edge and the top-left corner button cuts a black square into the
    card's own rounded corner.

    Floors row height at a real `cell_widget()`'s own
    `sizeHint().height()` — Qt's default row height is shorter than
    that container (button plus its margins), which slices
    "Replace"/"Decline" off at the bottom.
    Applied via the vertical header's `setMinimumSectionSize` (a real
    floor `resizeRowsToContents()` can't shrink below), not
    `setDefaultSectionSize` (only affects brand-new rows, not a floor).

    Also enables click-to-sort. Every table populated by a `with
    preserving_sort_order(table):` rebuild (ui/table_sort.py) is safe
    under this; the one table that is NOT — Duplicates, whose rows are
    grouped via `setSpan()` and would visually corrupt under an
    arbitrary per-row sort — turns it back off right after this call
    (see duplicates_page.py's own comment at construction).
    """
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setMinimumSectionSize(40)
    # Cells are left-aligned text, and a cell widget's contents start
    # at its left edge (`cell_widget`'s trailing stretch); a centred
    # header floats over neither.
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )
    elide_table_cells(table)
    table.setSortingEnabled(True)
    # QHeaderView defaults sortIndicatorSection to 0 (not "no column"),
    # so setSortingEnabled(True) alone silently auto-sorts every table
    # by its first column ascending the moment it's first populated —
    # confirmed live: it reordered Search results away from
    # rank_candidates()'s own best-first order, and Sharing's locations
    # away from the service's own order, on first render, before any
    # real user click. -1 is a genuine "no column" state Qt accepts
    # here; preserving_sort_order (ui/table_sort.py) already checks for
    # it, so this defers the first real sort to the user's own click.
    table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    representative_row_height = cell_widget(
        QPushButton("Sample")
    ).sizeHint().height()
    table.verticalHeader().setMinimumSectionSize(representative_row_height)

    # No header-label floor here: this runs before the caller assigns
    # its per-column resize modes, so every column still reads as
    # `Interactive` — `resizeSection()` would pin a width onto columns
    # about to become `Stretch`/`ResizeToContents`, and that width
    # sticks (changing a section's resize mode does not make Qt
    # recompute its size), leaving a dead band where a `Stretch` column
    # should have reclaimed the leftover width. Callers invoke
    # `apply_column_floors` AFTER setting their resize modes instead.
    # See HISTORY §110.


def apply_column_floors(table: QTableWidget) -> None:
    """The header-label floor, applied only to columns still in
    `Interactive`/`Fixed` resize mode. `Stretch` and `ResizeToContents`
    size themselves; pinning an explicit width onto one of them leaves a
    dead band (HISTORY §110), so those modes are skipped outright rather
    than floored. A column covered by `setStretchLastSection(True)` is
    skipped the same way, for the same reason, even though
    `sectionResizeMode()` still reports it as `Interactive`.

    Call this AFTER assigning every column's real resize mode — at the
    end of a table's own `_size_*_columns` render method for a table
    that has one, or directly after setting modes at construction for
    a table that never changes them again. A table that skips this call
    clips its header label (".ction") for whichever column stays at
    Qt's plain default width.
    """
    header = table.horizontalHeader()
    last_column = table.columnCount() - 1
    for column in range(table.columnCount()):
        if header.stretchLastSection() and column == last_column:
            continue
        mode = header.sectionResizeMode(column)
        if mode not in (
            QHeaderView.ResizeMode.Interactive,
            QHeaderView.ResizeMode.Fixed,
        ):
            continue
        floor = header_label_floor(table, column)
        if header.sectionSize(column) < floor:
            header.resizeSection(column, floor)


def size_action_column(
        table: QTableWidget, column: int, action_widgets: list[QWidget],
) -> None:
    """Widens an Actions column to the WIDEST real Actions widget built
    this render (never a magic number); without a derived width, Qt's
    stretch-last-section leftover-space math squeezes it to a sliver
    ("Confirm" reads as "onfirm"). Caller must have already called
    `header.setStretchLastSection(False)` — stretch-last overrides any
    resize mode set on the last section, Fixed included, if this column
    happens to be the last one.

    The width is derived from BOTH the widest real action widget AND the
    header label's own rendered width (`header_label_floor`). An EMPTY
    table has no action widgets at all, so `header_label_floor` is
    always in the candidate set: an empty table still shows its header
    in full, and a populated table with narrow buttons but a wide header
    (or vice versa) always fits both.
    """
    header = table.horizontalHeader()
    action_width = max(
        [widget.sizeHint().width() for widget in action_widgets]
        + [header_label_floor(table, column)]
    )
    header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
    header.resizeSection(column, action_width)


# The width a stretch column keeps before the fit-content columns get
# all theirs: enough for an "Artist - Title" to read at the Dashboard's
# narrowest, beside Status, Progress and Actions at 960 wide.
STRETCH_COLUMN_FLOOR = 180
# The most of a table's width its stretch columns hold back for their
# content before the fit-content columns are sized.
_STRETCH_SHARE = 0.4


@dataclass(frozen=True)
class ColumnLayout:
    """A table's column layout, declared once: which columns stretch
    (the primary text a row is about, such as Track or Filename),
    which fit their content, and which (if any) is the Actions column.
    `configure_columns`/`size_columns` below apply it. See HISTORY §118.

    A fit-content column gets its content's width while the stretch
    columns keep theirs (at least `stretch_floor`, at most 40 % of the
    table); when the table is too narrow for both, the widest
    fit-content text columns give way first, down to their header
    label (`fit_widths`).
    """
    stretch: tuple[int, ...]
    fit_content: tuple[int, ...]
    actions: int | None = None
    minimum_section: int = 40
    stretch_floor: int = STRETCH_COLUMN_FLOOR
    # Columns of file paths, which elide in the middle.
    paths: tuple[int, ...] = ()


def fit_widths(
        wants: dict[int, int], floors: dict[int, int], budget: int,
) -> dict[int, int]:
    """Each column's width when `wants` (content widths) must share
    `budget` pixels: every column wider than a common cap is cut to
    it, never below its floor, and the cap is the largest one that
    fits. Narrow columns keep their content; wide ones share the
    shortfall. When even the floors overrun the budget, the floors."""
    def total(cap: int) -> int:
        return sum(
            max(floors[column], min(want, cap))
            for column, want in wants.items()
        )

    low, high = 0, max(wants.values(), default=0)
    while low < high:
        cap = (low + high + 1) // 2
        if total(cap) <= budget:
            low = cap
        else:
            high = cap - 1
    return {
        column: max(floors[column], min(want, low))
        for column, want in wants.items()
    }


def _fit_content_columns(table: QTableWidget, layout: ColumnLayout) -> None:
    """Sets every fit-content column's width from this render's
    content and the viewport's current width (`fit_widths`). The
    stretch columns take what is left, which `Stretch` mode does."""
    if not layout.fit_content:
        return
    header = table.horizontalHeader()
    floors = {
        column: header_label_floor(table, column)
        for column in layout.fit_content
    }
    wants = {
        column: max(table.sizeHintForColumn(column), floors[column])
        for column in layout.fit_content
    }
    # Text elides; a cell widget (a progress bar, a radio) clips
    # instead, so a column holding one keeps its content's width.
    for column in layout.fit_content:
        if any(
            table.cellWidget(row, column) is not None
            for row in range(table.rowCount())
        ):
            floors[column] = wants[column]
    actions_width = (
        header.sectionSize(layout.actions)
        if layout.actions is not None else 0
    )
    viewport_width = table.viewport().width()
    # A stretch column holds back room for its own content, up to its
    # share of `_STRETCH_SHARE`, so a long secondary column (a failure
    # reason) never takes the width the row's primary text needs.
    share = int(viewport_width * _STRETCH_SHARE) // max(len(layout.stretch), 1)
    reserved = sum(
        max(layout.stretch_floor, min(table.sizeHintForColumn(column), share))
        for column in layout.stretch
    )
    budget = viewport_width - actions_width - reserved
    for column, width in fit_widths(wants, floors, budget).items():
        header.resizeSection(column, width)


class _ColumnFitter(QObject):
    """Re-fits a table's columns whenever its viewport changes width,
    so the policy holds while the window is resized, not only at the
    render that last called `size_columns`. A child of the table, so
    it lives exactly as long as the table does."""

    def __init__(self, table: QTableWidget, layout: ColumnLayout):
        super().__init__(table)
        self.table = table
        self.column_layout = layout
        self._width = -1
        table.viewport().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            width = self.table.viewport().width()
            if width != self._width:
                self._width = width
                _fit_content_columns(self.table, self.column_layout)
        return False


def _column_fitter(table: QTableWidget, layout: ColumnLayout) -> None:
    fitter = table.findChild(_ColumnFitter)
    if fitter is None:
        _ColumnFitter(table, layout)
    else:
        fitter.column_layout = layout


_ACTIONS_SORT_VETO_WIRED = "_seeker_actions_sort_veto_wired"


def _veto_actions_column_sort(table: QTableWidget, actions_column: int) -> None:
    """An Actions column holds buttons, not data; sorting by it is
    meaningless, so a click on its header must neither sort nor keep the
    sort indicator it would otherwise pick up. Every table with a
    `ColumnLayout.actions` gets this from `configure_columns` itself,
    not as a per-page special case (HISTORY §122).

    `configure_columns` is re-run on every populated render, so this
    wiring is guarded to happen exactly once per table via a dynamic Qt
    property — connecting again on every render would both leak
    connections and fire the revert multiple times per click.
    """
    header = table.horizontalHeader()
    if header.property(_ACTIONS_SORT_VETO_WIRED):
        return
    header.setProperty(_ACTIONS_SORT_VETO_WIRED, True)

    # The last real (non-actions) sort state, seeded from whatever
    # apply_table_defaults already set (-1/Ascending on a fresh
    # table). A plain closure, not a Qt property — no QVariant
    # round-trip needed for values only this closure reads.
    last_good_section = header.sortIndicatorSection()
    last_good_order = header.sortIndicatorOrder()

    def _track_real_sort(section: int, order: Qt.SortOrder) -> None:
        nonlocal last_good_section, last_good_order
        if section != actions_column:
            last_good_section = section
            last_good_order = order

    def _veto_click(section: int) -> None:
        # Qt has already flipped the indicator (and the connected
        # QTableView has already re-sorted) by the time sectionClicked
        # reaches us; restoring the prior indicator here re-sorts back
        # to it within the same call, so nothing paints in between.
        if section == actions_column:
            header.setSortIndicator(last_good_section, last_good_order)

    header.sortIndicatorChanged.connect(_track_real_sort)
    header.sectionClicked.connect(_veto_click)


def configure_columns(table: QTableWidget, layout: ColumnLayout) -> None:
    """The construction-time half of a table's column layout — see
    `size_columns` below for the render-time half. This must be safe to
    call on a still-empty table, and `size_columns` calls it again,
    harmlessly, at the top of every populated render.
    """
    header = table.horizontalHeader()
    header.setMinimumSectionSize(layout.minimum_section)
    header.setStretchLastSection(False)
    for column in layout.fit_content:
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
    for column in layout.stretch:
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
    if layout.actions is not None:
        size_action_column(table, layout.actions, [])
        _veto_actions_column_sort(table, layout.actions)
    _fit_content_columns(table, layout)
    _column_fitter(table, layout)
    set_path_columns(table, layout.paths)
    apply_column_floors(table)


def size_columns(
        table: QTableWidget,
        layout: ColumnLayout,
        action_widgets: list[QWidget],
) -> None:
    """The render-time half — re-runs `configure_columns`, then
    re-derives the Actions column width from this render's own real
    widgets rather than the empty placeholder list.
    """
    configure_columns(table, layout)
    if layout.actions is not None:
        size_action_column(table, layout.actions, action_widgets)
    _fit_content_columns(table, layout)
    apply_column_floors(table)
    # After the columns, whose widths decide how tall a cell's content
    # is. apply_table_defaults()'s vertical-header floor already keeps
    # every row tall enough for a cell widget; this lets a row grow
    # taller than that floor for content that needs it (a two-line
    # progress cell).
    table.resizeRowsToContents()


def build_qpalette(palette: Palette) -> QPalette:
    """The native `QPalette` counterpart to `build_stylesheet` — so
    anything Qt draws natively (native dialogs, menus opened via the
    system menu bar) still matches the active palette instead of
    falling back to the OS's own theme."""
    qpalette = QPalette()
    qpalette.setColor(QPalette.ColorRole.Window, QColor(palette.BG_APP))
    qpalette.setColor(QPalette.ColorRole.WindowText, QColor(palette.TEXT))
    qpalette.setColor(QPalette.ColorRole.Base, QColor(palette.BG_SURFACE))
    qpalette.setColor(
        QPalette.ColorRole.AlternateBase, QColor(palette.BG_SURFACE_2),
    )
    qpalette.setColor(QPalette.ColorRole.Text, QColor(palette.TEXT))
    qpalette.setColor(QPalette.ColorRole.Button, QColor(palette.BG_SURFACE_2))
    qpalette.setColor(QPalette.ColorRole.ButtonText, QColor(palette.TEXT))
    qpalette.setColor(
        QPalette.ColorRole.ToolTipBase, QColor(palette.BG_SURFACE_2),
    )
    qpalette.setColor(QPalette.ColorRole.ToolTipText, QColor(palette.TEXT))
    qpalette.setColor(QPalette.ColorRole.Highlight, QColor(palette.SELECTION))
    qpalette.setColor(
        QPalette.ColorRole.HighlightedText, QColor(palette.TEXT),
    )
    qpalette.setColor(
        QPalette.ColorRole.PlaceholderText, QColor(palette.TEXT_FAINT),
    )
    # A rich-text anchor paints in these; left unset they are the
    # platform's, which offscreen is #0000FF (2:1 on dark's page) and
    # on Cocoa a visited magenta (2.6:1 on light's).
    for link_role in (
            QPalette.ColorRole.Link, QPalette.ColorRole.LinkVisited,
    ):
        qpalette.setColor(link_role, QColor(palette.ACCENT))
    qpalette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(palette.TEXT_FAINT),
    )
    qpalette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(palette.TEXT_FAINT),
    )
    qpalette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(palette.TEXT_FAINT),
    )
    return qpalette


class _SeekerStyle(QProxyStyle):
    """Fusion, except that a click never gives a button keyboard focus
    (`SH_Button_FocusPolicy` is `TabFocus`, Fusion's is `StrongFocus`),
    so the `:focus` ring appears only for focus that came from the
    keyboard. macOS's native style makes the same choice; with the
    system's keyboard navigation off, Tab then skips buttons there,
    as it does in native apps."""

    def styleHint(
            self,
            hint: QStyle.StyleHint,
            option: QStyleOption | None = None,
            widget: QWidget | None = None,
            returnData: QStyleHintReturn | None = None,
    ) -> int:
        if hint == QStyle.StyleHint.SH_Button_FocusPolicy:
            return Qt.FocusPolicy.TabFocus.value
        return super().styleHint(hint, option, widget, returnData)


def apply_theme(app: QApplication, mode: ThemeMode = "system") -> Palette:
    """Resolves `mode` to a real `Palette` (`resolve_palette`), sets
    Fusion through `_SeekerStyle` (so the stylesheet renders
    identically on macOS and Windows — a real concern, since Windows
    packaging is still unverified), the matching `QPalette`, and the
    one global stylesheet, after registering the bundled display face.
    Safe to call again later, not just once before the first window —
    `MainWindow.on_theme_changed()` is the runtime re-apply entry point
    for exactly that.

    The macOS gotcha, UNVERIFIED (never checked on a real Mac): changing
    the stylesheet alone is believed to NOT change the native window
    chrome (title bar, native dialogs) — a light-mode app would
    otherwise keep a dark title bar.
    `QGuiApplication.styleHints().setColorScheme()` (real Qt 6.8+ API,
    this project runs PySide6 6.11) is believed to be what makes the
    title bar follow. An explicit `"light"`/`"dark"` choice sets it
    directly; `"system"` resets it to `Unknown` so the OS's own current
    appearance keeps driving native chrome without this app fighting it.
    Verify by screenshotting the real title bar in all three modes
    before trusting this description further.
    """
    app.setStyle(_SeekerStyle(QStyleFactory.create("Fusion")))

    register_display_font()

    # Before resolving: `"system"` reads `colorScheme()`, which reports
    # the last explicit choice until `Unknown` clears it (observed on
    # Cocoa, HISTORY §194).
    style_hints = QGuiApplication.styleHints()
    if mode == "light":
        style_hints.setColorScheme(Qt.ColorScheme.Light)
    elif mode == "dark":
        style_hints.setColorScheme(Qt.ColorScheme.Dark)
    else:
        style_hints.setColorScheme(Qt.ColorScheme.Unknown)

    palette = resolve_palette(mode)
    _active.palette = palette

    app.setPalette(build_qpalette(palette))
    app.setStyleSheet(build_stylesheet(palette))

    return palette


def _base_qss(palette: Palette) -> str:
    """Base/typography — generic widget backgrounds, dialogs, and
    every QLabel variant (badges, page/section headers, wordmark),
    plus the sidebar panel and activity strip chrome.
    """
    return f"""
/* Only a real surface paints a background: the window and dialogs
here, a card or a table in their own rules. A generic QWidget, a
checkbox or a radio paints none, so a cell container or a form row
shows the surface it sits on instead of a BG_APP band. A top-level
widget still fills with the palette's Window role, which is BG_APP
(observed on Cocoa and offscreen). */
QWidget {{
    color: {palette.TEXT};
}}

QMainWindow, QDialog {{
    background-color: {palette.BG_APP};
}}

QLabel, QCheckBox, QRadioButton {{
    background: transparent;
}}

QLabel[badge="ok"] {{
    color: {palette.SUCCESS};
}}

QLabel[badge="warn"] {{
    color: {palette.WARNING};
}}

QLabel[badge="muted"] {{
    color: {palette.TEXT_MUTED};
}}

/* Each of these selectors stands in for a per-widget setStyleSheet()
call, which would bake a token into a fixed string at construction time
(dead on a runtime theme switch — see the module docstring). Routing
through the global stylesheet + a real selector means these five widget
classes need NO code in MainWindow.on_theme_changed() at all;
QApplication.setStyleSheet() re-polishes them automatically. */
QLabel[badge="faint"] {{
    color: {palette.TEXT_FAINT};
}}

QLabel#pageTitleLabel {{
    font-family: "{DISPLAY_FAMILY}";
    font-size: {TYPE_TITLE_PX}px;
    font-weight: {WEIGHT_SEMIBOLD};
    color: {palette.TEXT};
}}

QLabel#sectionHeaderLabel {{
    font-family: "{DISPLAY_FAMILY}";
    font-size: {TYPE_SECTION_PX}px;
    font-weight: {WEIGHT_MEDIUM};
    color: {palette.TEXT};
}}

/* A plain QLabel re-themes for free on QApplication.setStyleSheet()
and reserves its own font's ascent/descent internally, so it is never
clipped at the bottom the way a custom-painted wordmark was. */
QLabel#wordmark {{
    font-family: "{DISPLAY_FAMILY}";
    font-size: {TYPE_TITLE_PX}px;
    font-weight: {WEIGHT_SEMIBOLD};
    color: {palette.TEXT};
}}

#sidebarPanel {{
    background-color: {palette.BG_SIDEBAR};
    border-right: 1px solid {palette.BORDER};
}}

#activityStrip {{
    background-color: {palette.BG_SURFACE_2};
    border-bottom: 1px solid {palette.BORDER};
}}

"""


def _notice_qss(palette: Palette) -> str:
    """InlineNotice and its four variants' lit edges."""
    return f"""\
/* A notice is a raised panel with its left edge lit in its variant's
colour, like a lamp; the rest of the frame stays the ordinary hairline,
so a stack of notices never reads as a row of alarms. Info's edge is
muted, not ACCENT, which marks only selection, focus and the primary
action. The variant is InlineNotice's `[variant]` dynamic property
(theme.set_variant()), so a theme switch restyles it. */
InlineNotice {{
    background-color: {palette.BG_SURFACE_2};
    border: 1px solid {palette.BORDER};
    border-left: 3px solid {palette.TEXT_MUTED};
    border-radius: {RADIUS_CONTROL}px;
}}

InlineNotice[variant="success"] {{
    border-left-color: {palette.SUCCESS};
}}

InlineNotice[variant="warning"] {{
    border-left-color: {palette.CUE};
}}

InlineNotice[variant="error"] {{
    border-left-color: {palette.DANGER};
}}

"""


def _button_qss(palette: Palette) -> str:
    """QPushButton — default, primary, danger, and sidebar nav-item variants."""
    return f"""\
QPushButton {{
    background-color: {palette.BG_SURFACE_2};
    border: 1px solid {palette.BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 14px;
    color: {palette.TEXT};
}}

QPushButton:hover {{
    border-color: {palette.BORDER_STRONG};
}}

QPushButton:pressed {{
    background-color: {palette.BG_SURFACE};
}}

QPushButton:disabled {{
    color: {palette.TEXT_FAINT};
    border-color: {palette.BORDER};
}}

QPushButton[variant="primary"] {{
    background-color: {palette.ACCENT};
    border: 1px solid {palette.ACCENT};
    color: {palette.ON_ACCENT};
    font-weight: 600;
}}

QPushButton[variant="primary"]:hover {{
    background-color: {palette.ACCENT_HOVER};
    border-color: {palette.ACCENT_HOVER};
}}

QPushButton[variant="primary"]:pressed {{
    background-color: {palette.ACCENT_PRESSED};
    border-color: {palette.ACCENT_PRESSED};
}}

QPushButton[variant="danger"] {{
    background-color: {palette.BG_SURFACE_2};
    border: 1px solid {palette.DANGER};
    color: {palette.DANGER};
}}

QPushButton[variant="danger"]:hover {{
    background-color: {palette.DANGER};
    color: {palette.ON_ACCENT};
}}

/* A horizontal segmented filter row (Dashboard's track-status filter):
plain default QPushButton look unchecked, an ACCENT fill once checked —
a pill-row variant of [variant="primary"] rather than the sidebar's own
[navItem="true"] left-border treatment, which assumes a vertical list. */
QPushButton[variant="segment"]:checked {{
    background-color: {palette.ACCENT};
    border: 1px solid {palette.ACCENT};
    color: {palette.ON_ACCENT};
    font-weight: 600;
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
    color: {palette.TEXT_MUTED};
}}

QPushButton[navItem="true"]:hover {{
    background-color: {palette.BG_SURFACE_2};
    color: {palette.TEXT};
}}

QPushButton[navItem="true"]:checked {{
    background-color: {palette.ACCENT_SUBTLE};
    border-left: 3px solid {palette.ACCENT};
    color: {palette.TEXT};
    font-weight: 600;
}}

/* Keyboard focus: a 2px ring, with the padding giving back the extra
pixel so the label never moves. ACCENT on the plain surfaces; TEXT on
an ACCENT fill, where an ACCENT ring would vanish into the button.
After the variant rules, which set border colours at equal
specificity. */
QPushButton:focus {{
    border: 2px solid {palette.ACCENT};
    padding: 5px 13px;
}}

QPushButton[variant="primary"]:focus,
QPushButton[variant="segment"]:checked:focus {{
    border: 2px solid {palette.TEXT};
    padding: 5px 13px;
}}

/* A Disclosure's toggle (ui/disclosure.py): a quiet line of text with
its chevron, not a button box. */
QToolButton#disclosureToggle {{
    background: transparent;
    border: 2px solid transparent;
    border-radius: {RADIUS_CONTROL}px;
    padding: 2px 4px 2px 0;
    color: {palette.TEXT_MUTED};
}}

QToolButton#disclosureToggle:hover,
QToolButton#disclosureToggle:checked {{
    color: {palette.TEXT};
}}

QToolButton#disclosureToggle:focus {{
    border: 2px solid {palette.ACCENT};
}}

QPushButton[navItem="true"]:focus {{
    border: 2px solid {palette.ACCENT};
    border-left: 3px solid {palette.ACCENT};
    padding: 6px {SPACING_MD - 2}px 6px {SPACING_MD}px;
}}

"""


def _input_qss(palette: Palette) -> str:
    """Text/combo/spin inputs, including their focus and dropdown states."""
    return f"""\
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background-color: {palette.BG_SURFACE};
    border: 1px solid {palette.BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 4px 8px;
    selection-background-color: {palette.SELECTION};
    selection-color: {palette.TEXT};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus {{
    border: 1px solid {palette.ACCENT};
}}

QComboBox {{
    padding-right: 24px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border: none;
}}

QComboBox::down-arrow {{
    image: url("{combo_chevron_path(palette).as_posix()}");
    width: 10px;
    height: 6px;
}}

/* Fusion's own spin arrows are a 2 px speck on Cocoa (HISTORY §194):
the buttons get the combo's chevron, a pair stacked in the right-hand
padding. */
QSpinBox, QDoubleSpinBox {{
    padding-right: 24px;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: padding;
    width: 20px;
    border: none;
    background-color: transparent;
}}

QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: {RADIUS_CONTROL - 1}px;
}}

QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: {RADIUS_CONTROL - 1}px;
}}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {palette.BG_SURFACE_2};
}}

QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background-color: {palette.BORDER};
}}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{spin_up_arrow_path(palette).as_posix()}");
    width: 10px;
    height: 6px;
}}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{spin_down_arrow_path(palette).as_posix()}");
    width: 10px;
    height: 6px;
}}

QComboBox QAbstractItemView {{
    background-color: {palette.BG_SURFACE};
    border: 1px solid {palette.BORDER_STRONG};
    selection-background-color: {palette.SELECTION};
    selection-color: {palette.TEXT};
}}

"""


def _table_qss(palette: Palette) -> str:
    """The QTableWidget/QListWidget container itself."""
    return f"""\
QTableWidget, QListWidget {{
    background-color: {palette.BG_SURFACE};
    border: 1px solid {palette.BORDER};
    border-radius: {RADIUS_CARD}px;
    gridline-color: {palette.BORDER};
    selection-background-color: {palette.SELECTION};
    selection-color: {palette.TEXT};
    alternate-background-color: {palette.BG_SURFACE_2};
}}

"""


def _card_qss(palette: Palette) -> str:
    """QFrame#card and the selector-scoped rules for its inner
    widgets (cardInner, cellWidgetContainer, themeToggleButton).
    """
    return f"""\
/* The real rounded border for a table/list routed through make_card();
the inner QTableWidget/QListWidget itself gets
border:none/border-radius:0 per-instance (see make_card's own docstring)
so this is the ONLY rounded edge actually painted. */
QFrame#card {{
    background-color: {palette.BG_SURFACE};
    border: 1px solid {palette.BORDER};
    border-radius: {RADIUS_CARD}px;
}}

/* Scoped by objectName, never a selector-less per-widget
setStyleSheet() on make_card()'s `inner`: Qt parses a selector-less
declaration list as `* {{ ... }}`, applying it to `inner` AND EVERY ONE
OF ITS DESCENDANTS. A rule with no pseudo-element only ever matches a
widget's BOX, never a pseudo-element/sub-control — so this silently
stripped border/radius off every plain widget box nested inside a card
(a QProgressBar's track, line edits, combo boxes, buttons in cells...)
while leaving `QHeaderView::section`/`QProgressBar::chunk` alone, since
those are pseudo-elements `*` can't match. Confirmed live: with a
per-widget sheet in place, a determinate QProgressBar's own top edge
samples as BG_SURFACE_2 (no border at all); with it removed, the same
pixel samples as BORDER. See HISTORY §114. */
#cardInner {{
    border: none;
    border-radius: 0px;
}}

/* `cell_widget()`'s container and `ThemeToggleButton` are scoped the
same way, so a source-level sweep can assert no selector-less
per-widget stylesheet exists anywhere in ui/. */
#cellWidgetContainer {{
    background: transparent;
}}

#themeToggleButton {{
    border: none;
    background: transparent;
}}

#themeToggleButton:focus {{
    border: 2px solid {palette.ACCENT};
    border-radius: {RADIUS_CONTROL}px;
}}

#closeButton {{
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    background: transparent;
    padding: 0;
}}

#closeButton:hover {{
    background: {palette.BG_SURFACE_2};
}}

#closeButton:focus {{
    border: 2px solid {palette.ACCENT};
}}

"""


def _table_header_qss(palette: Palette) -> str:
    """QListWidget::item plus every QHeaderView/QTableCornerButton
    rule — split from `_table_qss` above only because `_card_qss`'s
    rules sit between them in the original file; both are still
    "tables" in concern.
    """
    return f"""\
QListWidget::item {{
    padding: 4px;
}}

/* Deliberately no `QTableWidget::item {{ padding: ... }}` rule — a
real, reproducible Qt/Fusion rendering bug (found live while
screenshotting the Dashboard): styling QTableWidget::item
padding corrupts the paint of any QPushButton living inside a cell
WIDGET (QTableWidget.setCellWidget — used throughout this app's
Actions/Progress columns), producing garbled, ghosted button text.
Confirmed via a bisected minimal repro; the identical rule on
QListWidget::item is safe since nothing in this app puts a widget
inside a QListWidget item. Table cell padding, if wanted later, must
come from row height instead. */

QHeaderView::section {{
    background-color: {palette.BG_SURFACE};
    color: {palette.TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {palette.BORDER};
    /* Once ANY QHeaderView::section rule exists, Qt paints the header
    entirely from this box model, so `border: none` above removes the
    native section divider with no fallback underneath; this
    border-right is the only divider a user sees to drag.

    Never add `QHeaderView::section:horizontal:last-child`: it is CSS
    syntax, not valid Qt QSS (Qt's pseudo-state set has no
    `last-child`), and its mere PRESENCE poisons this entire
    `::section` rule — a window.grab() pixel scan found zero
    divider-colored pixels at any column boundary with it present.
    `:last` alone (below) is valid. BORDER_STRONG rather than BORDER:
    measured contrast against BG_SURFACE is 1.98:1 vs. 1.46:1, and the
    header is one flat block with no alternating-row-color help for
    the eye, unlike the body gridlines below (which stay BORDER). See
    HISTORY §103. */
    border-right: 1px solid {palette.BORDER_STRONG};
    padding: 6px;
}}

/* Suppresses the divider on the trailing section — nothing to
separate it FROM on that side. `:last` is real, valid Qt QSS (see the
comment above for the invalid selector never to use alongside it). */
QHeaderView::section:last {{
    border-right: none;
}}

/* Belt and braces alongside apply_table_defaults() hiding the vertical
header outright: a future table that genuinely wants row numbers back
would otherwise repaint the black-column/black-corner defects, since
QHeaderView::section above only styles the section painting, not the
header/corner-button WIDGETS themselves (the area below the last row,
and the top-left corner button between the two headers, have no section
to match that rule at all). */
QHeaderView {{
    background-color: {palette.BG_SURFACE};
    border: none;
}}

QTableCornerButton::section {{
    background-color: {palette.BG_SURFACE};
    border: none;
}}

"""


def _progress_qss(palette: Palette) -> str:
    """QProgressBar's container box (deliberately no ::chunk rule —
    see the comment below).
    """
    return f"""\
QProgressBar {{
    background-color: {palette.BG_SURFACE_2};
    border: 1px solid {palette.BORDER};
    border-radius: {PROGRESS_BAR_RADIUS}px;
    text-align: center;
    color: {palette.TEXT};
    max-height: {PROGRESS_BAR_HEIGHT}px;
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
pseudo-state in Qt's QSS to scope a `::chunk` rule around, so a
genuinely DETERMINATE bar's fill is applied locally, per instance, via
`style_meter()` — never here, never globally. */

"""


def _form_control_qss(palette: Palette) -> str:
    """QCheckBox/QRadioButton indicators."""
    return f"""\
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {palette.BORDER_STRONG};
    background-color: {palette.BG_SURFACE};
}}

QCheckBox::indicator {{
    border-radius: 3px;
}}

QRadioButton::indicator {{
    border-radius: 7px;
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {palette.ACCENT};
    border-color: {palette.ACCENT};
}}

QCheckBox::indicator:checked {{
    image: url("{check_tick_path(palette).as_posix()}");
}}

/* Keyboard focus thickens the indicator's border to 2px inside the
same 16px box; TEXT once checked, where the fill is already ACCENT. */
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
    width: 12px;
    height: 12px;
    border: 2px solid {palette.ACCENT};
}}

QCheckBox::indicator:checked:focus, QRadioButton::indicator:checked:focus {{
    border-color: {palette.TEXT};
}}

"""


def _centred_line(color: str, direction: str) -> str:
    """A `qlineargradient` that paints one pixel of `color` across the
    middle of a SPLITTER_GRAB_WIDTH band and leaves the rest clear;
    `direction` is the gradient's end point, across the band."""
    start = (SPLITTER_GRAB_WIDTH // 2) / SPLITTER_GRAB_WIDTH
    end = (SPLITTER_GRAB_WIDTH // 2 + 1) / SPLITTER_GRAB_WIDTH
    return (
        f"qlineargradient(x1: 0, y1: 0, {direction}, "
        f"stop: 0 transparent, stop: {start:.4f} transparent, "
        f"stop: {start + 0.0001:.4f} {color}, stop: {end - 0.0001:.4f} {color}, "
        f"stop: {end:.4f} transparent, stop: 1 transparent)"
    )


def _misc_qss(palette: Palette) -> str:
    """QScrollBar and QToolTip."""
    return f"""\
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {palette.BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {palette.TEXT_FAINT};
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {palette.BORDER_STRONG};
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QToolTip {{
    background-color: {palette.BG_SURFACE_2};
    color: {palette.TEXT};
    border: 1px solid {palette.BORDER_STRONG};
    padding: 4px 6px;
}}

/* Splitter handles (the Review page's sections): a 1px line centred
in a SPLITTER_GRAB_WIDTH band that is otherwise transparent, so the
band can be wide enough to grab without reading as a bar. The line is
two hard gradient stops: with an odd band, the line's pixel sits
exactly between them, so it renders crisp at 1x and 2x. ACCENT on
hover shows what the cursor will move. */
QSplitter::handle:vertical {{
    background: {_centred_line(palette.BORDER_STRONG, "x2: 0, y2: 1")};
}}

QSplitter::handle:horizontal {{
    background: {_centred_line(palette.BORDER_STRONG, "x2: 1, y2: 0")};
}}

QSplitter::handle:vertical:hover {{
    background: {_centred_line(palette.ACCENT, "x2: 0, y2: 1")};
}}

QSplitter::handle:horizontal:hover {{
    background: {_centred_line(palette.ACCENT, "x2: 1, y2: 0")};
}}

"""


def _status_qss(palette: Palette) -> str:
    """StepIndicator: its labels' weight per step and the hairline
    between steps; a numbered instruction's number; StatusChip."""
    return f"""\
QLabel[stepState="current"] {{
    color: {palette.TEXT};
    font-weight: {WEIGHT_SEMIBOLD};
}}

QLabel[stepState="done"] {{
    color: {palette.TEXT};
}}

QLabel[stepState="upcoming"], QLabel[stepState="skipped"] {{
    color: {palette.TEXT_MUTED};
}}

/* A numbered instruction's number, in the panel lettering. */
QLabel#stepNumber {{
    font-family: "{DISPLAY_FAMILY}";
    font-size: {TYPE_SECTION_PX}px;
    font-weight: {WEIGHT_SEMIBOLD};
    color: {palette.TEXT_MUTED};
}}

QFrame#statusChip {{
    background-color: {palette.BG_SURFACE_2};
    border: 1px solid {palette.BORDER};
    border-radius: {CHIP_RADIUS}px;
}}

QFrame#stepConnector {{
    background-color: {palette.BORDER_STRONG};
}}

"""


def _menu_tab_qss(palette: Palette) -> str:
    """QMenuBar/QMenu and QTabWidget/QTabBar."""
    return f"""\
QMenuBar {{
    background-color: {palette.BG_SIDEBAR};
    color: {palette.TEXT};
}}

QMenuBar::item:selected {{
    background-color: {palette.ACCENT_SUBTLE};
}}

QMenu {{
    background-color: {palette.BG_SURFACE_2};
    color: {palette.TEXT};
    border: 1px solid {palette.BORDER_STRONG};
}}

QMenu::item:selected {{
    background-color: {palette.ACCENT_SUBTLE};
}}

QTabWidget::pane {{
    border: 1px solid {palette.BORDER};
    border-radius: {RADIUS_CARD}px;
}}

QTabBar::tab {{
    background: transparent;
    color: {palette.TEXT_MUTED};
    padding: 6px 14px;
}}

QTabBar::tab:selected {{
    color: {palette.TEXT};
    border-bottom: 2px solid {palette.ACCENT};
}}

/* Only the current tab takes focus. The ring keeps the selected
tab's 8px below the label (2px border + 6px padding). */
QTabBar::tab:focus {{
    border: 2px solid {palette.ACCENT};
    border-radius: {RADIUS_CONTROL}px;
    padding: 4px 12px 6px 12px;
}}
"""


def build_stylesheet(palette: Palette) -> str:
    """The global QSS stylesheet, parameterized by palette, so it can
    be re-evaluated for a different palette at runtime. Called by
    `apply_theme()`/`on_theme_changed()` on every theme
    (re-)application. Assembled from the per-concern functions above.
    """
    return (
        _base_qss(palette)
        + _notice_qss(palette)
        + _button_qss(palette)
        + _input_qss(palette)
        + _table_qss(palette)
        + _card_qss(palette)
        + _table_header_qss(palette)
        + _progress_qss(palette)
        + _form_control_qss(palette)
        + _misc_qss(palette)
        + _status_qss(palette)
        + _menu_tab_qss(palette)
    )

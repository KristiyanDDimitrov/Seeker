# seeker — `ui/` rules

Standing facts for work under `src/seeker/ui/`, kept here so the root
`CLAUDE.md` stays short; Claude Code documents loading it when a
session reads files here (UNVERIFIED in this repo). The root file's Conventions (pages, feedback
channels, plain text), its quit seam and thread pool facts, and its
Testing section apply here too. Same rules as the root: present
tense, each fact linked to the HISTORY entry holding its
investigation.

## Threads and the window

- PySide6 reports an exception raised in a slot through
  `sys.excepthook` (observed live). pytest-qt swaps in its own hook
  per test, so a test of Seeker's hook needs
  `@pytest.mark.qt_no_exception_capture`.
  [HISTORY §150](../../../docs/history/121-150.md#150)
- `ui/workers.py`'s `Worker`: one shared, permanently-connected
  dispatcher QObject, never a fresh one per task —
  connect/disconnect cycling through Qt's mutex pool per call caused a
  real deadlock under heavy concurrent use. `setAutoDelete(False)` plus
  a `task_id`-only signal (never `self`) plus a deferred native delete
  are all independently required. [HISTORY §39](../../../docs/history/032-046.md#39)
- A `Worker` must be kept alive via a strong reference
  (`_active_workers: set[Worker]`) until its own finished/error signal
  fires — `QThreadPool.start()` returning early lets GC collect it
  mid-flight. [HISTORY §22](../../../docs/history/001-024.md#22)
- `Qt.ConnectionType.SingleShotConnection` is required on
  `run_worker`'s cross-thread connections — the reference cycle
  otherwise formed is invisible to Python's GC (the Qt/shiboken side
  isn't visible to the tracer), and a manual `disconnect()` from inside
  its own handler mid-emission segfaults. [HISTORY §32](../../../docs/history/032-046.md#32)
- **The window lifecycle is `WindowLifecycleController`'s alone**
  (`ui/window_lifecycle.py`): geometry, `_hidden_to_tray`,
  `_hide_request_id`, `_reopen_filled`, the Dock-icon calls, the quit
  confirmation and `cleanup_before_quit`. `MainWindow` keeps only what
  a QObject must own (`closeEvent`, `showEvent`, the QApplication
  `eventFilter`, the `applicationStateChanged` slot) and delegates;
  the tray reopens through `MainWindow.reopen()`. A test patching the
  Dock icon patches `window_lifecycle._set_dock_icon_visible`.
  [HISTORY §163](../../../docs/history/151-180.md#163)
- `WA_DeleteOnClose` on a top-level window must be cleared the moment a
  real tray icon exists, or the first close after that deletes the
  window's C++ object and "reopen from tray" breaks permanently.
  [HISTORY §114](../../../docs/history/108-120.md#114)
- `WA_DeleteOnClose`'s value is decided in exactly one place —
  `TrayController._build_tray_icon()` (`ui/tray.py`), both branches
  explicitly (`True` when no tray is available, `False` the moment one
  is built). `MainWindow.__init__` does not set it at all. A future
  change to this invariant belongs in that one method, not split
  between it and `__init__` again. [HISTORY §125](../../../docs/history/121-150.md#125)

## Widgets and rendering

- **One navigation model: the sidebar.** Every registered page has a
  sidebar button, and no page gets its own "← Back" (Settings' was
  removed). Settings' tabs are `SETTINGS_TAB_*` (General, Library,
  Connections, Matching); select one by constant, never by index.
  [HISTORY §179](../../../docs/history/151-180.md#179)
- **Never synchronously rebuild a widget from a handler that can run
  inside that widget's own selection/data-changed emission** —
  directly or via a shared signal like `PlaylistSelection.changed`.
  Reproduced as a real SIGSEGV (Dashboard's `track_table` cleared
  from inside its own `itemSelectionChanged`); defer with
  `QTimer.singleShot(0, ...)`, as `_on_shared_selection_changed`
  does. [HISTORY §134](../../../docs/history/121-150.md#134)
- **The Dashboard's track table rebuilds only when what its rows were
  built from changes** (`_RenderedRows`: the visible statuses plus the
  active palette, which the lamps bake in); a progress-only change updates
  bars, percentages and sort keys in place. Anything new a row bakes in at
  build time (a color, a setting) must join that key, or a change to it
  never reaches the table. `QTableWidget.setItem` measured ~2.4 ms a call
  at 500 rows — mutate an existing item on a hot path.
  [HISTORY §166](../../../docs/history/151-180.md#166)
- **A polled table with buttons rebuilds only when its rows change.**
  A shown tooltip dies with its widget, so a rebuild under the pointer
  kills a button's tooltip; an item's tooltip survives its item being
  replaced (both observed on Cocoa). Review keeps each table's last
  rows (`_rendered_candidates`, …) and skips an equal tick; Sharing's
  20 s rebuild still replaces its per-row button.
  [HISTORY §195](../../../docs/history/181-210.md#195)
- **A button whose enabled state a render decides is never
  `run_worker`'s `button=`.** Its finish handler re-enables the button
  before `on_finished`, over any render that already ran; disable it
  on click and let the render set it (Downloads' Clear finished,
  reproduced deterministically). [HISTORY §145](../../../docs/history/121-150.md#145)
- A page inside `MainWindow`'s `QStackedWidget` has no real geometry
  until first navigated to — restore saved splitter/size state from
  its first real `showEvent`, never its constructor
  (`ReviewPage._restore_splitter_state`).
  [HISTORY §132](../../../docs/history/121-150.md#132)

## Theme, tables and layout

- `QHeaderView::section:horizontal:last-child` is invalid Qt QSS (valid
  CSS, not Qt's dialect) and silently poisons the **entire**
  `::section` rule — use `:last` alone.
  [HISTORY §103](../../../docs/history/072-107.md#103)
- **A colour is read from `theme.active_palette()` at paint or render
  time, never cached** — the palette `apply_theme` last applied. There
  are no module-level colour names (`theme.ACCENT` is gone); prefer a
  QSS rule over reading a token at all.
  [HISTORY §181](../../../docs/history/181-210.md#181)
- **One selection pair: `TEXT` on `SELECTION`**, the palette's
  `Highlight`/`HighlightedText` and every QSS `selection-*` alike. A
  rule that sets a selection ground sets `selection-color` too: left
  out, it falls back to the palette's (dark mode's field selection
  drew near-black). **A mark is `CUE`, amber text is `WARNING`:**
  lamps, meters, the busy bar and the warning notice's edge take
  `CUE` (3:1); `WARNING` only where amber is text (4.5:1).
  [HISTORY §193](../../../docs/history/181-210.md#193)
- **A bundled line icon is a `QIcon` over `ui/icons.py`'s
  `TokenIconEngine`**, which swaps `currentColor` for a palette token
  on every draw (per mode and state, `IconColours`). The vendored
  Lucide files in `packaging/icons/lucide/` are never edited; a QSS
  `image:` still needs one file per palette (`_palette_icon`: the
  combo chevron, the spin arrows, the tick). Fusion's own spin arrows
  are a 2 px speck on Cocoa, so the spin buttons are styled in QSS.
  [HISTORY §182](../../../docs/history/181-210.md#182),
  [HISTORY §194](../../../docs/history/181-210.md#194)
- **`styleHints().colorScheme()` reports the app's own
  `setColorScheme()` override until `Unknown` clears it** (observed on
  Cocoa; offscreen never moves it), so `apply_theme` sets or clears the
  override before it resolves `"system"`. A test of that ordering
  stubs the hints (`_CocoaStyleHints` in `test_theme.py`).
  [HISTORY §194](../../../docs/history/181-210.md#194)
- **Only a real surface paints a background.** The generic `QWidget`
  rule sets text colour only; `QMainWindow`/`QDialog` paint `BG_APP`,
  cards and tables their own; `QLabel`/`QCheckBox`/`QRadioButton` are
  transparent. A new surface gets its own selector, never a
  background on a generic type, which bands every nested widget.
  Review a UI change in `tools/screenshots.py`'s images.
  [HISTORY §173](../../../docs/history/151-180.md#173)
- **A button takes its size hint.** It goes in `theme.action_row()`
  (or a row ending in `addStretch()`), never alone in a vertical or
  form layout, where it stretches to the full width; a tall form
  scrolls rather than squeezing rows (Settings' tabs).
  `tests/shell/test_button_sizing.py` walks every harness screen and
  fails the build. [HISTORY §174](../../../docs/history/151-180.md#174)
- **Focus is visible, and only keyboard focus.** `apply_theme` sets
  Fusion through `_SeekerStyle` (buttons are `TabFocus`: a click never
  focuses one), and every focusable control has a `:focus` rule. Test
  a focused look by painting through `style().drawControl()` with
  `State_HasFocus` on the option, never by real focus. A per-row
  button gets `cell_widget(..., row_label=)` and an icon-only control
  `setAccessibleName`; `tests/shell/test_keyboard_access.py` fails
  the build.
  [HISTORY §175](../../../docs/history/151-180.md#175)
- **Every table declares a `theme.ColumnLayout`** whose stretch
  column is the one its rows are about (Track, Filename, Path).
  `fit_widths` keeps that column's content width (180 px floor, 40 %
  cap) and shrinks the widest other text columns first, never below
  a header; a viewport filter refits on resize. Cells are one line:
  `ElidedTextDelegate` shows the full text on hover only when elided,
  and `ColumnLayout.paths` columns elide in the middle. A list of
  names uses `elide_list_items`. `tests/shell/test_table_columns.py`
  walks every harness screen at 960×640.
  [HISTORY §176](../../../docs/history/151-180.md#176)
- **An empty table shows `ui/empty_state.EmptyState`** (a glyph, one
  sentence, an optional action) inside its viewport, shown by the row
  count itself; never a spanned placeholder row or a status-label
  message. A page only changes its sentence (`set_text`) as the reason
  changes. A short marker on a row ("Upgrade") is a `BADGE_ROLE`
  pill on the primary cell, not a column of its own; quieter detail
  beside a cell's text (a candidate's quality and peer) is
  `SECONDARY_ROLE`, not a second line. Rows that come in groups band
  every other group with `BAND_ROLE` (the palette's AlternateBase,
  read at paint time) and span the group's own cells, never a
  group-number column. A state in a cell is its
  `status_lamp` lamp as the item's icon beside the label, never link
  styling; where the label must read in full, the view sets
  `set_secondary_min_share(view, 0.0)`. Determinate progress is
  `theme.style_meter` (amber segments, no label: the percentage is
  cell text); an in-table bar with no amount yet is
  `theme.set_busy_meter` (the same amber), and a bar goes back to busy
  only through `theme.set_indeterminate`, which drops the `::chunk`
  sheet. [HISTORY §177](../../../docs/history/151-180.md#177),
  [HISTORY §178](../../../docs/history/151-180.md#178), [HISTORY §184](../../../docs/history/181-210.md#184)
- **A titled section is `theme.section_card`** (its title in the
  panel lettering, one muted sentence, then the controls), never a
  `QGroupBox`, whose title draws in the system font; none is left in
  `src/`. [HISTORY §189](../../../docs/history/181-210.md#189)
- **Background reading goes behind a `ui/disclosure.Disclosure`,
  after the page's working content** (Sharing's "How sharing works"),
  closed by default, its state a `SeekerConfig` field written on the
  user's click only. Open, its body scrolls inside a share of the
  height rather than squeezing the tables.
  [HISTORY §187](../../../docs/history/181-210.md#187)
- **Prose wraps at 80 characters through `theme.reading_column`**
  (Help, Support), which caps the whole column. Never cap one wrapped
  label inside a wider layout row: the row asks its height at the
  row's width and clips its last lines (`set_reading_measure` is only
  for a label that is a scroll area's whole content). A link takes
  `QPalette.Link`, which `build_qpalette` sets to `ACCENT`.
  [HISTORY §188](../../../docs/history/181-210.md#188)
- Any `setStyleSheet()` call must carry a selector — a selector-less
  rule parses as a universal `*` rule and silently strips styling off
  every descendant widget's box model.
  [HISTORY §114](../../../docs/history/108-120.md#114)
- `setSpan()` must be called **before** `setCellWidget()` on the
  span-owning cell, and no widget of any kind belongs on the cells it
  covers — a "blank placeholder" widget resolves to the same geometry
  as the real span-owning widget and paints over it.
  [HISTORY §77](../../../docs/history/072-107.md#77)
- A bare `QProgressBar`/`QPushButton` handed straight to
  `setCellWidget` renders top-clamped or stretched to fill the whole
  cell — always wrap it in a centering container widget. A structural
  test walks every table for this.
  [HISTORY §104](../../../docs/history/072-107.md#104)
- `QTableWidget::item { padding }` corrupts a `QPushButton` living
  inside a cell widget (safe on `QListWidget`). A plain `QWidget`
  subclass needs `WA_StyledBackground` to paint its own stylesheet
  background/border at all. [HISTORY §47](../../../docs/history/047-071.md#47)
- A `setCellWidget`-only column (no `QTableWidgetItem`) sorts as a
  silent no-op under click-to-sort — give it a `SortKeyItem`
  (`ui/table_sort.py`) if it has real data to order by (see
  Progress's fraction-complete key), never a bare display string.
  `theme.configure_columns` already vetoes sorting entirely on
  whichever column `ColumnLayout.actions` names, for every table, so
  a new Actions column needs no per-page handling at all.
  [HISTORY §122](../../../docs/history/121-150.md#122)

# Brief for Claude Code — round 7

Base commit `6b0c19c`, working tree clean, `dist/Seeker.app` rebuilt
2026-09-05 16:44 — i.e. the user tested a **current round-6 build**, not
a stale one. (Checked deliberately, because three of these four are
round-6 items reported fixed. Both brows render in the user's sidebar
crop, which is D1.4's fix; the binary is current. The reports are real.)

Four user-reported defects. Every one was diagnosed against the real
source **and** against real pixels sampled out of the four screenshots —
exact RGB values and column positions are quoted inline, so the
diagnosis is measurement, not inference. Where I could not settle
something without a running Qt (PySide6 still will not install in the
diagnosing environment — no wheel reachable from it), I say so and hand
you the experiment instead of a conclusion.

---

## Standing note: a test that skips its own case

D3 shipped green last round. Here is the test that was supposed to hold
it (`tests/test_ui_smoke.py:6900`):

```python
for table in window.findChildren(QTableWidget):
    if not table.isVisible() or not has_a_stretch_column(table):
        continue
```

`has_a_stretch_column()` returns False for a table whose resize modes
have never been assigned. An **empty** Search or Duplicates table has no
stretch column — because nothing has ever set one — so the test
`continue`s past the exact table that is broken, on the exact screen the
user photographed, and passes.

That is a new failure mode, distinct from round 5's ("asserted a
property instead of looking") and round 6's ("wrote an assumption as a
comment"). This one is: **the test's own guard excludes the failing
case.** A skip condition derived from the same state the bug corrupts
cannot be a guard — it is a blindfold.

> **Convention, add it to CLAUDE.md:** any `continue`/`skip` inside a
> sweep test must be justified in a comment that names what it excludes
> and why that exclusion cannot hide the bug the test exists for. If it
> can, the skip is the bug.

And my own share of it: round 6's D3 brief diagnosed only the populated
render path and never asked what an empty table's columns look like.
Same scoping error as B4→C3 (the Downloads progress bar fixed, the
Dashboard's own copy missed). I keep writing briefs that describe the
path the user's screenshot came from rather than every path that reaches
the same widget.

---

## Ordering

1. **E1** — fullscreen close. It strands the app in an unclosable empty
   window; it is the only defect here that costs the user their session.
2. **E2** — empty tables never get a column layout. Two pages look
   broken the moment they are opened, and five more share the defect.
3. **E3** — the progress bar's square groove. Small visually, but the
   cause is a stylesheet cascade that is silently stripping borders and
   radii off **every** control inside a card.
4. **E4** — the wordmark. Mostly deletion.

---

## E1 — Closing from fullscreen leaves an empty, unclosable window

### What the screenshot actually shows

Not a black macOS Space. Sampled from the user's image: the body is a
uniform **#292929** and the title bar **#383838**, with live traffic
lights and the title "Seeker". Those are AppKit's own dark-mode
`NSWindow` colours. No Seeker palette token is anywhere near them —
`BG_APP` is `#100E15`. So the native window is alive and ordered in,
and **nothing Qt owns is being painted inside it**: a window frame whose
content widget is marked hidden.

That single fact explains both halves of the report:

- **The window is empty** because Qt believes it is hidden
  (`WA_WState_Hidden` set on the widget and its children), while AppKit
  has the `NSWindow` back on screen.
- **The red button does nothing** because `closeEvent` →
  `event.ignore()` → not fullscreen any more → `_hide_to_tray()` →
  `self.hide()` on a window Qt already considers hidden is a **no-op**.
  Every subsequent click runs the same no-op. The only way out is the
  menu bar's "Open Seeker", which calls `showNormal()` and re-syncs the
  two views of reality — exactly what the user found.

### Why D4's fix produced this

`closeEvent` (`main_window.py:6364`) leaves fullscreen and defers the
hide to `changeEvent` (`:6396`), which fires on the first
`WindowStateChange` where `isFullScreen()` is false, then
`QTimer.singleShot(0, self._hide_to_tray)`.

The commit's own comment says this was "confirmed live, in this
offscreen test session". **Offscreen QPA has no fullscreen Space and no
transition animation at all** — `showNormal()` there flips a state flag
synchronously. On real macOS the exit is an animated, multi-hundred-
millisecond AppKit transition, and Qt reports `WindowStateChange` when
the *state* changes, at the start of it. So `singleShot(0)` fires in the
middle of the animation, `hide()` calls `[NSWindow orderOut:]` mid-
transition, AppKit re-orders the window in when the animation completes,
and Qt's hidden flag stays set. The verification was structurally
incapable of exercising the thing that breaks — the same gap D1.5 hit
with `devicePixelRatio` and the same one HISTORY §107 records.

- [ ] **E1.1 — reproduce and instrument first, on the real Mac.** Print,
  with timestamps: every `changeEvent` of type `WindowStateChange` with
  `self.windowState()`, `isFullScreen()`, `isVisible()`, and
  `self.windowHandle().visibility()`; then the same four values inside
  `_hide_to_tray`, and again 1s later on a timer. Go fullscreen, click
  the red button, and paste the real sequence. The expected shape is two
  or more state changes with the hide landing between them. **If the
  sequence contradicts that, stop and report — do not apply E1.2 on top
  of a wrong model.** This cannot be run offscreen; it is a real-desktop
  step or it is not done.

- [ ] **E1.2 — the fix, and it is a deletion: stop intercepting the
  close while fullscreen.** On macOS, do not call `event.ignore()` when
  `self.isFullScreen()`. Capture `normalGeometry()` into
  `_pre_fullscreen_geometry`, set `_hidden_to_tray = True`, show the
  tray notice if it is still owed, and then let the close proceed
  normally. AppKit's own "close a fullscreen window" path tears down the
  Space correctly — it is the one code path guaranteed to get this
  right, because it is the platform's own. `setQuitOnLastWindowClosed
  (False)` is already set (`main_ui.py:35`, `:40`), so the app survives
  the close and stays in the menu bar; "Open Seeker" already calls
  `showNormal()` + `setGeometry(...)` and will restore the same window.
  Delete `_pending_hide_after_fullscreen_exit` and the `changeEvent`
  branch that serves it.

- [ ] **E1.3 — fallback, only if E1.1 shows E1.2 does not hold.** Keep
  exit-then-hide, but drive it off the *second* `WindowStateChange`
  (AppKit's `windowDidExitFullScreen:`, which Qt forwards) rather than
  the first, and add a real settle delay whose value comes from the
  duration you measured in E1.1, commented as an observation with the
  macOS and PySide6 versions — never a guessed constant.

- [ ] **E1.4 — make the failure impossible to be silent.** Whatever
  `_hide_to_tray` does, it must verify: after hiding, check
  `self.isVisible()`. If the window is still visible, the hide did not
  take — restore `_hidden_to_tray = False` and retry once on a short
  timer, and log it. The user's window was blank precisely because
  `_hidden_to_tray` stayed True (the poll/render guards at `:1873`,
  `:4920`, `:5097`, `:5237`, `:5371`, `:5465`, `:5640` all early-return
  on it) while the window stayed on screen. That flag must never be able
  to disagree with reality.

- [ ] **E1.5 — all four exit routes, from fullscreen, on the real
  desktop.** Red button, ⌘W, ⌘Q, and the tray menu's Quit. They reach
  different code and only one has ever been tried. For each: no empty
  window left behind, no black Space, app genuinely in the menu bar (or
  genuinely gone, for Quit), and reopening restores the pre-fullscreen
  geometry.

- [ ] **E1.6** Report E1.5 as a real-desktop checklist with the outcome
  of each of the four. A passing unit test is not evidence for any of
  them; say "not verified" rather than "done" for anything you could not
  actually click.

---

## E2 — Empty tables sit at Qt's default 100px columns, so the grid stops mid-air

### Measured, not inferred

Header divider positions sampled from the user's own two screenshots:

- Search: dividers at x = **328, 428, 528, 628, 728, 828, 928**
- Duplicates: dividers at x = **125, 225, 325, 425, 525, 625, 725**

Exactly 100px apart in both — Qt's `defaultSectionSize`. Not one resize
mode has been applied. Eight columns occupy 800px inside a card whose
inner width is ~1660px (Search) and ~950px (Duplicates).

The header's *background* does run the full width (sampled: `#29243A`
continues to x=1894 on Search), but the header's **bottom border stops
at the last section**, at x=1028. That underline ending in mid-air, with
the last section having no right divider, is precisely what the user is
calling "the Action section is cut off on the right side". The label
itself is not clipped — the column has no right-hand edge and the table
visibly stops short of its own card.

### Cause

Seven tables assign their resize modes **only inside a render method**
that never runs while the table is empty:

| table | modes set in | called from |
|---|---|---|
| `search_results_table` | `_size_search_columns` (`:2427`) | `_render_search_results` |
| `duplicates_table` | `_size_duplicates_columns` (`:4463`) | duplicates render |
| `track_table` | `_size_track_columns` (`:5034`) | `_render_track_statuses` |
| `review_needs_table` | `_size_review_needs_columns` (`:5395`) | review render |
| `review_upgrades_table` | `_size_review_upgrades_columns` (`:5496`) | review render |
| `review_local_table` | `_size_review_local_columns` (`:5666`) | review render |
| `sharing_locations_table` | `_size_sharing_locations_columns` (`:2838`) | sharing render |

Their `_build_*` methods call `theme.apply_table_defaults(...)` and
nothing else. Until the first non-empty render, every column is 100px,
there is no `Stretch` column, and `apply_column_floors` is never
reached — so `header_label_floor` never runs either.

Downloads (`:2532`), History (`:2590`), Sharing's uploads table
(`:2700`) and Settings' locations table (`settings_window.py:179-185`)
all configure at construction and are fine. **The correct pattern
already exists in this codebase** — Settings does exactly the right
thing four lines apart. Seven tables just don't do it.

- [ ] **E2.1 — measure before changing anything.** For all seven tables,
  freshly constructed with zero rows: print every `sectionSize(i)`,
  `sectionResizeMode(i)`, `sum(sectionSize)` and `viewport().width()`.
  Confirm the 100px figure above from the live app rather than from my
  reading of a screenshot, and report the real numbers.

- [ ] **E2.2 — split configuration from sizing.** For each of the seven,
  extract a `_configure_*_columns()` that takes no arguments and does
  everything not derived from real row content: `setStretchLastSection`,
  every `setSectionResizeMode`, then `theme.size_action_column(table,
  col, [])` for a table with an Actions column (an empty widget list
  already falls through to `header_label_floor`, which is C2's fix and
  is correct), then `theme.apply_column_floors(table)`. Call it at the
  end of the table's `_build_*`, and call it first from the existing
  `_size_*_columns(action_widgets)`, which then only widens Actions to
  the real widgets and re-applies the floors. One definition of a
  table's column layout, reachable from both states.

- [ ] **E2.3 — fix the test's blindfold (see the standing note).** Drop
  the `has_a_stretch_column(table)` guard from
  `_assert_no_dead_band_at_stretch_columns`. Assert the invariant for
  **every** visible table: `sum(sectionSize) >= viewport().width() - 2`.
  If a table legitimately cannot fill its viewport, that is a defect in
  the table, not a case to skip. Keep the zero-rows and populated runs
  and both window sizes; the zero-rows run is the one that matters here
  and is the one that was being skipped.

- [ ] **E2.4 — a second, structural test.** Every `QTableWidget` in both
  windows must have at least one column in `Stretch` mode, or
  `stretchLastSection()`, **immediately after construction** — before
  any render. That is the invariant whose absence caused this, and it is
  cheap to assert directly instead of inferring it from widths.

- [ ] **E2.5** Screenshot Search, Duplicates, Review (all three tables)
  and Sharing **empty**, before and after — those are the screens a new
  user meets first. Then populated, to prove nothing regressed. Attach
  the crops.

---

## E3 — The progress bar's track is a hard rectangle while its fill is a pill

### Measured

From the user's Dashboard crop, sampled pixel by pixel:

- Track: `#29243A` = `BG_SURFACE_2`, spanning y = 82–95 → **14px tall**,
  matching `QProgressBar { max-height: 14px }`.
- Corners: **perfectly square**, no antialiased arc on any of the four,
  at x = 94 and x = 188.
- **No border at all** — row 82 is already full `BG_SURFACE_2`, with no
  `#3A344E` line above or below it.

So the app stylesheet's `QProgressBar { border: 1px solid {BORDER};
border-radius: {RADIUS_CONTROL}px; }` (`theme.py:868-885`) is **not
reaching this widget's box**, while `background-color`, `color` and
`max-height` from the very same rule plainly are. Meanwhile
`style_determinate_progress_bar` (`theme.py:258`) sets
`QProgressBar::chunk { border-radius: 6px }` on the bar itself, and the
chunk keeps its rounding. Square track, rounded fill — exactly the
inconsistency reported, and the reason it only appears "once it starts
downloading" is that at 0% there is no chunk to see.

### Cause — `make_card`'s selector-less stylesheet

`theme.py:308`:

```python
inner.setStyleSheet("border: none; border-radius: 0px;")
```

Qt cannot parse a bare declaration list, so it **wraps it as
`* { border: none; border-radius: 0px; }`** and applies it to `inner`
and every descendant. A widget-level sheet outranks the application
sheet, so for every widget box inside a card, `border` and
`border-radius` are forced off.

The reason this strips the progress bar's track but leaves the header
dividers alone is the piece that makes the diagnosis fit every pixel:
**a rule with no pseudo-element only applies to widget boxes, never to
sub-controls.** `QHeaderView::section` is a pseudo-element, so `*` does
not match it — and sure enough, the header divider in the same crop
samples as `#4E4768` = `BORDER_STRONG`, C1.4's colour, straight from the
app stylesheet. `QProgressBar::chunk` is likewise a pseudo-element and
keeps its 6px radius. The `QProgressBar` **box** — the track — is a
widget box, and loses everything.

This is round 5's C1.3 hypothesis, which was investigated, found not to
be the header-divider cause, and then left in place. It was real; it was
just breaking something else.

- [ ] **E3.1 — confirm the mechanism in one step.** Comment out
  `theme.py:308`, `window.grab()` a Dashboard row with a determinate
  bar, and sample the track's corners and border. Rounded + bordered
  confirms it. Report the sampled RGBs either way; if it does not
  change, this diagnosis is wrong and the next suspect is the QSS
  `max-height` interacting with the box painter — say so and stop.

- [ ] **E3.2 — kill the `*` cascade.** Give `inner` an objectName
  (`cardInner`) and move the rule into `build_stylesheet` as
  `#cardInner { border: none; border-radius: 0px; }`. No widget-level
  sheet, no universal selector, no cascade into children. First check
  all **17** `make_card(...)` call sites (15 in `main_window.py`, 2 in
  `settings_window.py`) for an inner widget that already has an
  objectName — confirm the count yourself and state it; if one exists,
  use a dynamic property + `[cardInner="true"]` selector instead of
  clobbering it.

- [ ] **E3.3 — then make it a pill, deliberately and derived.** Add
  `PROGRESS_BAR_HEIGHT = 14` next to the spacing tokens and use it for
  the QSS `max-height`; set both the `QProgressBar` box and the
  `::chunk` radius to `PROGRESS_BAR_HEIGHT // 2` (7px), so track and
  fill are the same pill at 0%, mid-download and 100%. Never a literal
  `7`. Comment that the pill is the user's explicit request and that the
  radius is tied to the height so the two can never drift.

- [ ] **E3.4 — the indeterminate bar must survive.** The whole reason
  there is no global `::chunk` rule is that any such rule kills Qt's
  native busy animation (`theme.py:887-897`, confirmed by bisection).
  Keep `style_determinate_progress_bar` per-instance. But note that the
  track's own rounding now actually paints for indeterminate bars too,
  where it previously did not — so grab a queued/indeterminate row and
  confirm the animation still runs and the track is a pill.

- [ ] **E3.5 — sweep for the rest of the class.** Removing the `*`
  cascade restores borders and radii to **every** widget box inside a
  card, not just progress bars: line edits, combo boxes, spin boxes,
  buttons in cells, checkboxes, the tables' own frames. Some of that is
  the intended styling finally arriving; some may be a border you did
  not expect. Enumerate what changes, page by page, and screenshot every
  page in both themes before and after. If a specific inner widget
  genuinely needs its frame off, turn it off with a real selector for
  that widget, not with a universal rule.

- [ ] **E3.6 — a test for the mechanism, not the symptom.** Assert that
  no `setStyleSheet` call anywhere in `ui/` passes a string without a
  selector (i.e. one whose first non-whitespace run reaches a `:` before
  a `{`). There are others — `cell_widget`'s `"background: transparent;"`
  (`theme.py:325`) and `_ThemeToggleButton`'s `"border: none;
  background: transparent;"` (`:633`) are both the same shape. Neither
  looks harmful today (transparent backgrounds on leaf widgets), but
  both are the same loaded gun; scope them the same way and let the test
  keep the pattern from coming back.

---

## E4 — Wordmark: plain text, no brows

Two requests in one: the text is still clipped at the bottom, and the
brows go away.

### The clipping, measured — and it contradicts the source

From the user's full-window screenshot, at 1× (the sidebar is exactly
200px wide, matching `SIDEBAR_WIDTH`):

- Sidebar top margin `SPACING_LG` = 16, so the wordmark row starts at
  y = 16.
- The theme toggle's 20px glyph spans y = 20–39, centred at 29.5 → the
  28px toggle occupies y = 16–43.
- The selected nav button spans y = 84–115 (32px tall, left edge x = 12
  = `SPACING_MD`), pitch 36 → the Dashboard button is y = 48–79 → with
  `SPACING_XS` = 4 spacing, **the wordmark row ends at y = 44 and is
  28px tall**.
- "Seeker" ink runs y = 30–43 and stops dead at 43 with no antialiased
  falloff row. The baseline is at 44 — **the row's exact bottom edge**.
  The 1px baseline overshoot of the round letters is what is being cut.

So the widget is 28px tall and paints its baseline at its own bottom.
28 = `top_reserve + ascent` (≈9 + 19 for this font), i.e. the widget's
height equals `baseline_y` precisely, with `descent()` and
`_BOTTOM_PADDING` (12) contributing nothing.

**That contradicts the committed `sizeHint()`** (`:512`), which returns
`top + ascent + descent + 12` ≈ 44 and whose D1.3 test asserts exactly
that and passes. I could not settle the contradiction without a running
Qt. Both brows render, so the binary does contain D1.4 and therefore
D1.1 — this is not a stale build. Something at runtime is giving the
widget 28px anyway. Do not skip past this:

- [ ] **E4.1 — print the numbers on the real Mac, before changing
  anything.** After `window.show()`: `self._wordmark.sizeHint()`,
  `.height()`, `.minimumSizeHint()`, `.sizePolicy().verticalPolicy()`,
  the row's `geometry()`, and the four components (`_brow_reserve_
  height`, `ascent()`, `descent()`, `_BOTTOM_PADDING`) from
  `QFontMetrics(self._font)` **and** from `self.fontMetrics()`. If those
  two metric sources disagree, that is the answer and it should be
  written down — `QFontMetrics(font)` with no paint device is not
  guaranteed to match what the widget actually paints with. Report the
  numbers whatever they say; this is the one chance to learn what
  happened before the code that caused it is deleted.

### The fix: delete the widget

- [ ] **E4.2** Replace `_Wordmark` with a plain `QLabel("Seeker")`,
  `objectName("wordmark")`, styled entirely in `build_stylesheet`:
  `QLabel#wordmark { font-size: 20px; font-weight: 700; color:
  {palette.TEXT}; }`. A QLabel reserves its own ascent and descent and
  cannot exhibit this class of bug, and it re-themes for free on
  `setStyleSheet` — which also deletes `retint()` and its call site
  (`:2098-2101`). Keep the size at 20px; the user did not ask for a
  different one.

- [ ] **E4.3** Delete `_Wordmark` (`:418-599`),
  `_resolve_wordmark_brows_path` (`:404`), the `QSvgRenderer` import if
  it becomes unused, and the four wordmark/brow tests in
  `test_ui_smoke.py` (`:7136`, `:7152`, `:7171`, `:7183`, `:7213`,
  `:7241` — confirm the exact set). **Decision: keep**
  `packaging/icons/seeker_brows.svg` in the repo, unreferenced. It was
  measured off the real icon and is cheap to keep; `packaging/icons/`
  ships wholesale so the spec needs no change. One line in HISTORY
  saying it is dormant and why, so the next round does not treat it as
  a missing-asset bug.

- [ ] **E4.4** Confirm the row still looks right: the label's sizeHint
  height (~24) is now under the toggle's fixed 28, so the row stays 28
  and the label centres in it. Screenshot the sidebar in both themes and
  check there is real space below the "S" — the bottoms of the round
  letters must show their full curve, not a flat cut. Sample the pixel
  row below the last ink row and confirm it is background, in the
  screenshot, not in an assertion.

- [ ] **E4.5** One test worth keeping, rewritten for the label: render
  the sidebar, grab it, and assert the bottom row of the label's rect
  contains no text-coloured pixel — i.e. nothing is touching the edge.
  That is the invariant the user actually cares about, and it is the one
  the D1.3 test never expressed.

---

## Commits, and reporting

One commit per E-item, each verified before the next. `mypy --strict`
clean, real test numbers named inline, pre-existing failure count
treated as a regression if it moves.

The screenshot gate stands and applies to E2, E3 and E4. **E1 cannot be
verified offscreen at all** — E1.1 and E1.5 are real-desktop steps or
they are not done, and the round-6 commit message's "confirmed live, in
this offscreen test session" for a fullscreen-transition claim is
exactly the kind of sentence that produced this round's worst defect.
List anything you could not actually run as outstanding; the user can
click through E1.5 in under a minute.

Roadmap item 70 (the stress-test hang) — round 6 was asked whether it is
now believed to be the same defect as the queued-`QMessageBox` hang or
still separate, and the answer needs to land somewhere findable. Seven
rounds of carrying it forward without that answer is its own problem.

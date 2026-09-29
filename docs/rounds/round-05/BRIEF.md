# Brief for Claude Code — round 5

Base commit `2021e22`. Three of these are **regressions of items already
reported fixed in round 4** — read the standing note before touching
them. The rest is one visual feature and one large refactor.

Diagnosis below was done against the real repo and, for the palette
work, with real measured contrast ratios. PySide6 still cannot be
installed in the diagnosing environment, so Qt-runtime claims carry an
experiment rather than an assertion.

Standing project rules apply in full. One is elevated to a hard gate
this round — see immediately below.

---

## Standing note: C1–C3 were all "fixed" last round

B2 (header dividers), B6.3 (Actions column width) and B4 (progress bar
centring) were all committed, all tested, all reported green, and the
user opened the app and saw all three still broken. The common thread is
not carelessness — it is that **every one of them was verified by
asserting a property rather than by looking at the result.** Round 4
shipped no `window.grab()` at all.

So for this round:

> **A visual item is not done until a real screenshot of it has been
> looked at.** `window.grab()` under the offscreen QPA needs no Screen
> Recording permission and is what items 77 and R5 both used. Attach
> the before/after crop in HISTORY for C1, C2, C3 and C5. An item whose
> screenshot was not taken is reported as **not done**, not as done.

This is the fourth round in which the 09-02 brief's standing rule 2 — "a
test that asserts an object exists is not a test that a user can see it"
— has been the actual root cause. Please state that plainly in HISTORY
rather than writing a fourth entry that reads like the first three.

---

## Ordering

1. **C1** — header dividers. First, because its bisect settles whether
   per-widget stylesheets override the global one, which C5 depends on.
2. **C2**, **C3** — small, fully diagnosed, independent.
3. **C4** — the wordmark (asset already committed).
4. **C5** — light/dark. The large one, on a clean base.
5. **C6** — record the SoundCloud decision. No code.

---

## C1 — Header column dividers: third attempt, so bisect before editing

The CSS from B2.1 is present and reads correctly (`theme.py:432-459`):
`border: none` followed by `border-bottom` and `border-right: 1px solid
{BORDER}`. The user still sees no divider between header cells on any
tab. Body gridlines **are** visible (confirmed in the user's Dashboard
screenshot — real vertical lines between Status / Progress / Actions),
so this is specific to the header.

**Do not edit the stylesheet again before running the bisect.** Two
rounds have now changed this rule and asserted the changed string. Three
hypotheses, cheapest discriminator first — one screenshot each:

- [ ] **C1.1 — is it painting at all?** Temporarily set
  `border-right: 2px solid #FF0000` on `QHeaderView::section`,
  `window.grab()` a populated table, and look.
  - Red dividers appear → the rule works and this is a **contrast**
    problem. Go to C1.4.
  - Nothing appears → the rule is being overridden. Go to C1.2.
- [ ] **C1.2 — the `:last` rules.** `QHeaderView::section:horizontal:
  last-child` is not valid Qt QSS — Qt's pseudo-state set for header
  sections is `:first`, `:last`, `:middle`, `:only-one`, `:selected`,
  `:next-selected`, `:previous-selected`, `:checked`, `:horizontal`,
  `:vertical`. `last-child` is CSS, not Qt. Delete both `:last` rules
  and re-run C1.1. If the dividers appear, the invalid selector was
  poisoning the rule; reinstate only `::section:last` and verify it
  suppresses exactly the trailing divider and nothing else.
- [ ] **C1.3 — `make_card`'s per-widget stylesheet.** `make_card()` calls
  `inner.setStyleSheet("border: none; border-radius: 0px;")`
  (`theme.py:128`). A widget-level sheet outranks the application sheet,
  and a widget's stylesheet applies to its children — the `QHeaderView`
  **is** a child of the `QTableWidget`. Comment that line out and re-run
  C1.1. If the dividers appear, this is the cause, and the fix is to
  scope that per-widget rule to the widget itself
  (`"QTableWidget { border: none; border-radius: 0px; }"` with a real
  selector, not a bare declaration list) so it cannot cascade into the
  header. **Report this result explicitly either way — C5 needs the
  answer.**
- [ ] **C1.4 — the likely real fix, and it is measured, not preferred.**
  `BORDER` (#3A344E) against `BG_SURFACE` (#1D1929) is a contrast ratio
  of **1.46:1**. In the body that is enough because alternating row
  colours help the eye find the line; the header is one flat block with
  no such help. `BORDER_STRONG` (#4E4768) gives **1.98:1** — still
  subtle, but ~35% more separation. Use `BORDER_STRONG` for header
  dividers specifically, keep `BORDER` for body gridlines, and say in
  the comment that the two differ deliberately and why.
- [ ] **C1.5** Confirm the body gridlines really are on everywhere (the
  user asked for this globally). Sample the pixel column between two
  body cells on Downloads, Duplicates and Settings → Library Locations
  and report the real RGB. If any table lacks them, move
  `gridline-color` into `make_card`'s own per-widget rule so it cannot
  be lost.
- [ ] **C1.6** Screenshot every affected page, before and after, and put
  the crops in HISTORY. Regression test: assert the header divider
  property is present **and** that its colour token is `BORDER_STRONG`.

---

## C2 — "Action" renders as ".ction" — the column collapses when the table is empty

**CONFIRMED, with the exact line.** `theme.size_action_column`
(`theme.py:208-214`):

```python
action_width = max(
    (widget.sizeHint().width() for widget in action_widgets),
    default=header.minimumSectionSize(),      # <- 40px
)
```

The user's Review screenshot shows all three tables **empty**. No rows
means no action widgets, so `max()` falls through to its `default` —
`minimumSectionSize()`, which `apply_table_defaults` leaves at Qt's
floor — and the column is set to 40px, clipping the "Action" header to
".ction". The contrast proves it: in the same session's Dashboard
screenshot the populated table shows "Actions" in full.

The narrower bug is real too: even with rows, the width is derived
**only** from the action widgets. A table with a narrow button ("Tag")
and a wide header ("Actions") clips whenever the text is wider than the
button.

- [ ] **C2.1** Derive the width from **both**: the widest action widget
  *and* the header label's own rendered width. Measure the label with
  `QFontMetrics(header.font()).horizontalAdvance(text)`, and add the
  real chrome — the `padding: 6px` from the QSS on both sides, the
  divider from C1, and `header.style().pixelMetric(...)` for the sort
  indicator if the header is sortable. Derived, never a magic number,
  same discipline `size_action_column` already applies to widgets.
- [ ] **C2.2** Make the empty-table case explicit rather than a `max()`
  default: with no rows the column should still be at least the header
  text width. An empty table is the **first** thing a new user sees on
  Review, Search and Duplicates, so it is the case that matters most.
- [ ] **C2.3 — this is not Actions-specific.** Add a shared invariant:
  no column's width may be less than its own header label needs. Apply
  it in `apply_table_defaults` for every column, then let
  `size_action_column` widen the Actions column further where the
  widgets need it.
- [ ] **C2.4** Regression test over **every** table in both windows: for
  every column, `sectionSize(i) >= horizontalAdvance(headerText) +
  padding`, asserted with **zero rows** and again with real rows, at the
  app's 960×640 minimum and at default size.
- [ ] **C2.5** Screenshot the Review page empty — that is the exact
  screenshot the user sent.

---

## C3 — The progress bar is a second site, and B4 only fixed the first

**CONFIRMED.** The user's screenshot is the **Dashboard track table**,
not the Downloads table — the columns are Status / Progress / Actions
with "In library" / "Downloading" and per-row "Tag" buttons. B4 fixed
`_build_progress_widget`, which serves the Downloads page. The Dashboard
builds its own, at `main_window.py:4512-4523`:

```python
progress = QProgressBar()
progress.setMaximum(status.total_bytes)
progress.setValue(status.bytes_transferred)
theme.style_determinate_progress_bar(progress)
self.track_table.setCellWidget(row, 2, progress)     # bare widget
```

A bare `QProgressBar` handed to `setCellWidget` is resized to the whole
cell and then clamped by the stylesheet's `QProgressBar { max-height:
14px; }`, which pins it to the top — the identical mechanism B4
diagnosed, in a function B4 never touched. My round-4 brief scoped B4 to
"the Downloads tab" and that is why this was missed; the fault is in the
brief, not in the implementation.

- [ ] **C3.1** Wrap it in the same container helper B4 introduced, so
  the Dashboard bar centres exactly as the Downloads one does. Keep the
  Dashboard's existing difference — no ETA label — deliberate and
  commented; only the container is shared.
- [ ] **C3.2 — one builder, not two.** Both pages should reach a single
  progress-cell function. Two independent implementations of the same
  cell is what produced this bug and it will produce the next one.
- [ ] **C3.3 — sweep the remaining sites.** There are exactly 15
  `setCellWidget(` calls across `main_window.py` and
  `settings_window.py`. Fourteen pass a real container; the two bare
  ones are `:4521` (this bug) and `:4523` (a `QWidget()` placeholder,
  harmless). Confirm that count yourself and state it. Then add a test
  that fails if a bare `QProgressBar` or `QPushButton` is ever handed
  to `setCellWidget` — walk the rendered tables and assert every cell
  widget has a layout.
- [ ] **C3.4** Verify with pixels: force a real downloading row on the
  Dashboard, `window.grab()`, and compare the bar's centre-y against the
  row's centre-y for both pages. Attach the crop.

---

## C4 — Wordmark: the logo's brows over the "ee" of "Seeker"

**Decided with the user after seeing real mocks.** The original idea —
the two eyes replacing the two `e`s — was mocked in four treatments and
does not work: each eye is roughly 3:1 where a lowercase `e` is 1:1, so
at x-height the pair is triple-width and the word reads as "S…ker", the
eye skipping the cluster as a symbol rather than reading it as letters.
What does work is the brows alone, sitting above the real "ee".

**The asset is already committed**, untracked, as
`packaging/icons/seeker_brows.svg` — two strokes traced from the real
`seeker_icon.icns`, geometry measured rather than eyeballed (thickness
22.5, slope ±0.738, mirrored), with 12 units of viewBox padding so the
butt caps are not clipped (verified: painted bbox 5,4 → 503,146 in a
507×150 canvas).

- [ ] **C4.1** Replace the sidebar's `QLabel("Seeker")`
  (`main_window.py:1580`) with a small custom widget whose `paintEvent`
  draws the text and then composites the brows above the "ee" span.
  Compute the span from the font itself —
  `horizontalAdvance("S")` gives the left edge and
  `horizontalAdvance("See") - horizontalAdvance("S")` the width — never
  hardcoded offsets, so it survives a font or size change.
- [ ] **C4.2 — size.** Raise the wordmark from 16px to **20px**. At 16px
  the brows are ~2px tall and read as a smudge; at 20px they read
  cleanly. The sidebar is 200px wide (`SIDEBAR_WIDTH`) with `SPACING_MD`
  margins, so "Seeker" at 20px bold leaves ample room — confirm the
  toggle from C5.6 still fits on the same row.
- [ ] **C4.3 — tint, don't recolour the file.** `QSvgRenderer` has no
  `currentColor` support. Render the SVG to a `QPixmap` at the needed
  device-pixel-ratio, then tint with `QPainter`
  `CompositionMode_SourceIn` — the same template treatment the menu bar
  icon already uses. One asset then serves both themes, which C5 needs.
  Accent (`ACCENT`) is the intended colour.
- [ ] **C4.4** Add the SVG to `seeker.spec`'s `datas` — `packaging/
  icons/` already ships wholesale, so confirm rather than assume, and
  resolve its path through the same `sys.frozen`/`_MEIPASS` branch
  `_resolve_tray_icon_path` uses. A packaged build with a missing
  wordmark asset must fall back to plain text, never to a blank label.
- [ ] **C4.5** Screenshot the sidebar in both themes at real size and
  attach. Test: the widget's `sizeHint()` accommodates the full word,
  and it degrades to plain text when the asset is absent.

> If the user comes back preferring one of the eye-replacement
> treatments after all, "D" (eyes squeezed into the "ee" slot) is the
> best of them and this becomes a one-function change. Don't
> pre-implement it.

---

## C5 — Light and dark themes, with system-follow

The large item. `theme.py` currently bakes its colours into a
module-level `STYLESHEET` f-string evaluated at **import** time, and
there are **56** `theme.<TOKEN>` references plus **12** `setStyleSheet`
calls outside `theme.py`, all resolved at widget-construction time.
Nothing about that survives a runtime theme switch, so this is a real
refactor, not a second palette.

### 5a — Architecture

- [ ] **C5.1** A frozen `Palette` dataclass holding every colour token.
  `DARK` carries today's exact values unchanged — this refactor must be
  a **visual no-op** in dark mode, and that is the first thing to prove:
  screenshot every page before and after the refactor and diff them.
- [ ] **C5.2** Move the `STYLESHEET` f-string into
  `build_stylesheet(palette) -> str` and the QPalette construction into
  `build_qpalette(palette) -> QPalette`. `apply_theme(app, mode)`
  resolves mode → palette and applies both.
- [ ] **C5.3 — the 56 references are the actual work.** Each is a colour
  read at construction time. Convert them, preferring in this order:
  1. Give the widget an `objectName` and move the colour into the global
     stylesheet, so Qt re-styles it on `setStyleSheet` automatically.
     This is the right answer for most of the 12 `setStyleSheet` calls
     (`main_window.py:290, 697, 2044, 4394` are plain colour-only labels).
  2. Where a per-widget sheet must stay, rebuild it in the theme-change
     handler.
  3. `QColor(theme.ACCENT)` on table items (e.g. `:4508`) is set during
     a render, and the 2s poll re-renders those tables anyway — so they
     self-heal. **Confirm that rather than assuming it**, and handle any
     table that does not re-render on a timer.
  Note the C1.3 finding here: if per-widget stylesheets are cascading
  into children, that affects this conversion directly.
- [ ] **C5.4 — runtime switch.** `app.setStyleSheet(...)` re-polishes
  QSS-driven colours by itself; QPalette-driven and hardcoded ones do
  not. Add a single `on_theme_changed()` on `MainWindow` (and
  `SettingsWindow`) that re-applies the palette and re-runs the render
  paths, and route every switch through it. No page may require a
  restart to look right.
- [ ] **C5.5 — the macOS gotcha, do not skip it.** Changing the
  stylesheet does not change the **native** window chrome: a light-mode
  app keeps a dark title bar and dark native dialogs. PySide6 6.11.2 is
  Qt 6.11, so `QGuiApplication.styleHints().setColorScheme(...)` (Qt
  6.8+) is available and is what makes the title bar follow. Set it
  alongside the stylesheet, and **screenshot the title bar** to prove it
  — this is precisely the kind of thing that looks fine in a widget
  screenshot and wrong on the real desktop.

### 5b — System-follow

- [ ] **C5.6** Three modes: `system` (default), `light`, `dark`.
  `system` resolves via `QGuiApplication.styleHints().colorScheme()`
  and subscribes to `colorSchemeChanged`, so the app follows the Mac
  flipping at sunset without a restart. Handle
  `Qt.ColorScheme.Unknown` by falling back to dark (today's behaviour) —
  and disconnect the signal when the mode is not `system`, so an
  explicit choice is never overridden.
- [ ] **C5.7** Persist as `theme_mode: str = "system"` in
  `config_store.py`, read through `data.get("theme_mode", "system")`
  with an unknown value falling back to `"system"` rather than raising —
  same guarded-default discipline as every other field. A test with a
  config file containing garbage in that key.

### 5c — The light palette

Proposed below, with real measured WCAG contrast ratios against
`BG_SURFACE`. The design rule is **elevation is preserved, lightness is
not** — in dark, higher elevation gets lighter; in light, higher
elevation gets whiter, with the page ground slightly tinted so white
cards come forward. The sidebar stays the recessed chrome in both. That
mapping is a deliberate judgement call, not a mechanical inversion —
flag it as untuned in the comment.

| token | dark (today) | ratio | light (proposed) | ratio |
|---|---|---|---|---|
| `BG_APP` | `#100E15` | — | `#F1EEF8` | — |
| `BG_SIDEBAR` | `#15121D` | — | `#E9E4F3` | — |
| `BG_SURFACE` | `#1D1929` | — | `#FFFFFF` | — |
| `BG_SURFACE_2` | `#29243A` | — | `#F7F5FC` | — |
| `BORDER` | `#3A344E` | 1.46 | `#DCD6EC` | 1.41 |
| `BORDER_STRONG` | `#4E4768` | 1.98 | `#BFB5DA` | 1.94 |
| `TEXT` | `#ECEAF3` | 14.41 | `#1B1726` | 17.54 |
| `TEXT_MUTED` | `#9E98B3` | 6.21 | `#5C5474` | 7.06 |
| `TEXT_FAINT` | `#6F6987` | 3.31 | `#8A82A3` | 3.62 |
| `ACCENT` | `#7C5CFF` | 3.95 | `#6A46F0` | 5.60 |
| `ACCENT_HOVER` | `#8E72FF` | — | `#5B36E4` | — |
| `ACCENT_PRESSED` | `#6446E0` | — | `#4B2ACB` | — |
| `ACCENT_SUBTLE` | `#241E3D` | — | `#EDE7FF` | — |
| `SUCCESS` | `#3FBF7F` | 7.33 | `#18854F` | 4.66 |
| `WARNING` | `#E0A33E` | 7.75 | `#9A6410` | 4.99 |
| `DANGER` | `#E5484D` | 4.39 | `#C2303A` | 5.56 |

The accent is deliberately darker in light mode (`#6A46F0` vs
`#7C5CFF`) — the dark value scores only 2.9:1 on white, which is below
the floor for a control colour. White text on the light accent is
5.6:1, so accent-filled buttons work in both directions.

- [ ] **C5.8 — make the contrast a test, not a claim.** Add a real WCAG
  relative-luminance checker and assert, for **both** palettes: body
  text ≥ 4.5:1 on its own background, `TEXT_FAINT` and borders ≥ 3:1
  where they carry meaning (note `TEXT_FAINT` is 3.31/3.62 — right at
  the edge, deliberately, since it is decorative), and white-on-accent
  ≥ 4.5:1. A palette that regresses then fails CI instead of shipping.
  This is the one part of the design that can be objectively verified,
  so verify it.
- [ ] **C5.9** The menu bar icon needs no change — it is a template
  image (`setIsMask(True)`) and macOS already recolours it per
  appearance. Confirm that in the real menu bar in both appearances
  rather than assuming.

### 5d — The toggle

The user asked for a quick toggle in the left nav, opposite "Seeker",
and hoped it could be logo-derived.

**I tried the logo-derived version and it does not work.** A single eye
from the mark, rendered solid (dark) / outlined (light) / half-filled
(auto), reads as an abstract parallelogram at 18px — the eye shape is a
flat sliver whose outline carries no eye identity, and the half-fill
reads as a broken shape rather than a state. Evidence: three rendered
variants inspected at real size on both grounds. The logo works as a
*pair*; it does not carry state on its own.

- [ ] **C5.10** Use a conventional glyph set instead — sun (light),
  moon (dark), split circle (auto) — drawn with `QPainter` rather than
  shipped as assets, so it is resolution-independent and tints with the
  palette for free. The user explicitly authorised this fallback. The
  logo still appears right beside it in C4's wordmark, which is where it
  belongs.
- [ ] **C5.11** Place it right-aligned on the wordmark's row. Cycles
  system → light → dark; the icon shows the **current mode** and the
  tooltip names it in words, because a three-state control with no label
  is otherwise a guess.
- [ ] **C5.12** Settings gets the authoritative three-way control
  (radio buttons: Follow system / Light / Dark), and the two stay in
  sync in both directions.

### 5e — Verification

- [ ] **C5.13** Screenshot **every** page in both themes at 960×640 and
  at default size. This is the item where a property assertion is least
  adequate — a theme is only correct if it looks correct. Attach a
  contact sheet.
- [ ] **C5.14** Explicitly check the places most likely to be missed:
  the InlineNotice variants (`notice.py` builds its own per-widget
  sheet), the activity strip, disabled buttons, the nav item's
  `:checked` accent bar, table selection colours, and the empty-state
  labels.

---

## C6 — SoundCloud: deferred, and here is what the research found

**The user's decision, after seeing the findings: defer entirely.** Do
not start it. Record it so the research is not repeated:

1. **Registering a SoundCloud API app requires a paid Artist Pro
   subscription.** No Artist Pro, no client credentials, so nothing can
   be verified against real behaviour — which this project treats as
   disqualifying rather than as a detail.
2. **SoundCloud requires a `client_secret` even for native apps.** Their
   guide states PKCE is required *and* that "all clients are currently
   treated as confidential rather than public, meaning a secret is
   required to obtain a token." That is fundamentally different from
   Spotify, where Seeker deliberately uses PKCE with no secret. A
   distributed `.dmg` cannot hold a secret — it is extractable by
   anyone with the file — and the usual workaround, a proxy server,
   violates the project's own "prefer solutions that run locally"
   principle.
3. **If it is ever picked up, the architecture is bring-your-own-
   credentials**: the user registers their own app and pastes
   `client_id` + `client_secret` into Settings, stored only in their own
   config store, exactly as they already do for the Spotify client ID.
   That is the only shape consistent with this project's principles.
4. The agreed UI, kept for whenever it happens: a source toggle at the
   top-right of the Dashboard, Spotify green vs SoundCloud orange.

- [ ] **C6.1** Add this to `CLAUDE.md`'s roadmap as a named, deferred
  item with the two blockers stated, so the next round does not
  rediscover them. No code, no schema, no stubs.

---

## Commits, and reporting

One commit per C-item, each individually verified before the next.
`mypy --strict src/` clean, real test numbers named inline per RR3, and
the pre-existing-failure count treated as a regression if it moves.

The screenshot gate at the top of this brief applies to C1, C2, C3, C4
and C5. Roadmap item 70 (the stress-test hang) remains open and
untouched — five rounds now.

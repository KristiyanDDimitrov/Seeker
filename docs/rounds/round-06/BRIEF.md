# Brief for Claude Code — round 6

Base commit `ca685c3`. Five user-reported defects from a real manual
session on the round-5 build. All five were diagnosed by reading the
real source; each names the exact line.

**Three of these five were introduced by round 5's own fixes** (D1 by
C4, D2 by C5, D3 by C2), and **two are assumptions written as comments
that were never tested** (D4, D5). Those are two different failure
modes and both are addressed below.

---

## Standing note: comments that assert platform behaviour

C1 last round was caused by a QSS selector that had been written
confidently and never verified. D5 in this brief is caused by this
comment, at `main_window.py:6098`:

```python
# macOS routes a left-click on a QSystemTrayIcon straight to its
# context menu already (Trigger never fires there the way it
# does on Windows/Linux) ...
```

That is stated as fact, the code is built on it, and the user's report
proves it false on this machine. Same shape as `last-child`.

> **New convention, add it to CLAUDE.md:** a comment asserting platform
> or framework behaviour must either cite a real observation ("confirmed
> live, PySide6 6.11.2 on macOS 26") or be explicitly marked unverified.
> An unmarked confident claim about a framework this project has already
> been wrong about twice is a liability, not documentation.

Then sweep for others: `grep` the UI layer for comments claiming what Qt
or macOS "always"/"never" does, and mark every one that has no recorded
observation behind it. Do not go fixing them — just stop them reading as
established fact.

---

## Ordering

1. **D2** — the light/dark toggle does nothing at all. The headline
   feature of round 5 is dead.
2. **D3** — a visible regression on two pages, caused by C2.
3. **D1** — the wordmark, two separate bugs in one widget.
4. **D5** — small, and its fix is a one-line platform guard.
5. **D4** — the fullscreen black Space; most involved of the small ones.

---

## D1 — The wordmark is clipped at the bottom and shows only the left brow

Two independent bugs in `_Wordmark` (`main_window.py:416-542`).

### 1a — Clipped bottom: `sizeHint()` and `paintEvent()` disagree

`sizeHint()` (`:492`) measures with the **ink** rect:

```python
text_size = metrics.boundingRect(self._TEXT).size()
return QSize(text_size.width(), text_size.height() + top + self._BOTTOM_PADDING)
```

`paintEvent()` (`:522`) positions with the **font metric**:

```python
baseline_y = top_reserve + metrics.ascent()
```

`boundingRect("Seeker").height()` is the ink height — roughly cap height,
since "Seeker" has no descenders — around 15px at this 20px bold font.
But the baseline sits at `ascent()`, around 19-20px, and `descent()` is
never reserved at all. So the widget asks for ~10px less height than it
draws into, and Qt clips the bottom of the text. Exactly the report.

- [ ] **D1.1** Reserve real font metrics, not ink:
  `top_reserve + metrics.ascent() + metrics.descent() + _BOTTOM_PADDING`.
- [ ] **D1.2** Same class of error on the width: `boundingRect().width()`
  omits the right side bearing. Use
  `metrics.horizontalAdvance(self._TEXT)`, and take the max of that and
  `ee_left + ee_width` so a brow that overhangs the text can never be
  clipped either.
- [ ] **D1.3** Assert the invariant in a test rather than trusting it:
  `sizeHint().height() >= top_reserve + ascent + descent`, and the same
  for width. This is a mismatch between two functions in the same class,
  which is precisely what a test can hold.

### 1b — Only the left brow: a device-pixel-ratio bug in the source rect

`_load_tinted_brows` (`:462`) builds the pixmap at device resolution and
tags it:

```python
pixmap = QPixmap(round(size.width() * dpr), round(size.height() * dpr))
pixmap.setDevicePixelRatio(dpr)
```

then `paintEvent` (`:539`) draws it with an explicit source rect in
**device** pixels:

```python
painter.drawPixmap(target, self._brows_pixmap, QRectF(
    0, 0, self._brows_pixmap.width(), self._brows_pixmap.height(),
))
```

`QPixmap.width()` returns device pixels (507 × 2 = 1014), but
`drawPixmap`'s source rect is interpreted in the pixmap's
**device-independent** coordinates once a devicePixelRatio is set. So
the source rect is twice the image in both axes: only the top-left
quadrant of it contains anything, and the two brows — which span the
full width — collapse into a fraction of the target. The left brow
survives as a visible stroke; the right one falls outside entirely.

This is the same DPR trap HISTORY §107 already records hitting once this
round ("`window.grab()` returns in DEVICE pixels"), in a second place.

- [ ] **D1.4** Use the device-independent size for the source rect:
  `QRectF(QPointF(0, 0), self._brows_pixmap.deviceIndependentSize())`.
- [ ] **D1.5 — verify before and after with a number, not an eye.**
  Print `dpr`, `pixmap.width()`, `pixmap.deviceIndependentSize()` and
  the target rect, then `window.grab()` the sidebar. Both brows must be
  present and symmetric about the "ee".
- [ ] **D1.6** `dpr = self.devicePixelRatioF() if self.window() else 2.0`
  (`:470`) hardcodes 2.0 whenever the widget has no window yet — which
  is the case at construction, always. On a 1× display that renders the
  brows at double resolution and scales them down; on a 3× display it
  under-renders. Re-render the pixmap when the widget's screen or DPR
  actually changes (`QEvent.Type.DevicePixelRatioChange`), and make the
  fallback 1.0 with a comment saying why.
- [ ] **D1.7** Screenshot the sidebar in both themes, at 1× and 2× if a
  second display is available, and attach the crops.

---

## D2 — The theme toggle changes the icon and nothing else

**The wiring is correct and the palette resolution is correct.** I
checked both: `resolve_palette` (`theme.py:174`) returns `LIGHT`
directly for `"light"`, and `apply_theme` (`:498`) calls
`_set_module_tokens`, `setPalette` and `setStyleSheet` in the right
order. So the outer call really does apply the light stylesheet — and
then something applies the dark one back over it before the user sees
anything. The icon updating while the palette does not is the tell:
`_theme_mode` and the toggle are set **after** `apply_theme` returns, so
they survive; the stylesheet does not.

**Leading hypothesis — re-entrancy through `colorSchemeChanged`.** In
`_apply_theme_mode` (`main_window.py:1942`) the order is:

```python
theme.apply_theme(app, mode)          # 1
self._theme_mode = mode               # 2
...
self._sync_system_scheme_subscription()   # 4  <- too late
self._theme_toggle.set_mode(mode)         # 5
```

While the app is in `"system"` mode, `_on_system_color_scheme_changed`
is connected to `styleHints().colorSchemeChanged`. Step 1's own last act
is `style_hints.setColorScheme(Qt.ColorScheme.Light)` — **after** it has
already called `setStyleSheet(build_stylesheet(LIGHT))`. That emits
`colorSchemeChanged`, the still-connected handler fires, and it calls
`_apply_theme_mode("system", persist=False)`, which re-resolves the
system palette (dark, on a dark Mac) and re-applies the **dark**
stylesheet. Control returns to the outer frame, which then sets the mode
and the icon to "light" over a dark stylesheet.

That produces the exact reported symptom, and it explains why *no* mode
appears to work: system → light and system → dark both re-enter, and
dark → light re-enters again once the subscription is restored.

- [ ] **D2.1 — confirm it first, cheaply.** Add a temporary print in
  `_on_system_color_scheme_changed` recording the current
  `self._theme_mode` and a stack depth, then click the toggle once and
  report what actually fires and in what order. If the handler does not
  fire, this hypothesis is wrong — stop and report, do not "fix" it
  anyway. In that case the next suspects are, in order: whether
  `setStyleSheet` on the `QApplication` is reaching an already-polished
  widget tree (try an explicit `style().unpolish()`/`polish()` sweep),
  and whether `setColorScheme` on macOS is overriding the Fusion
  palette after the fact.
- [ ] **D2.2 — fix the ordering.** Sync the subscription **before**
  applying the theme, so an explicit light/dark choice has already
  disconnected the system handler by the time `setColorScheme` fires.
  That means `_sync_system_scheme_subscription()` needs the target mode,
  so set `self._theme_mode = mode` first and re-order to: set mode →
  sync subscription → apply theme → persist → update toggle/settings →
  `on_theme_changed()`.
- [ ] **D2.3 — make re-entrancy impossible, not merely unlikely.**
  Ordering alone still leaves the `"system"` path able to re-enter
  itself (`setColorScheme(Unknown)` while subscribed). Add a plain
  re-entrancy guard — an `_applying_theme` flag that
  `_on_system_color_scheme_changed` checks and returns early on. Belt
  and braces, and it costs three lines.
- [ ] **D2.4 — the handler is also too blunt.** It re-applies
  unconditionally; it should return immediately when
  `self._theme_mode != "system"`, regardless of subscription state. A
  handler that can only ever be correct if its signal is connected at
  exactly the right moments is a handler waiting to be re-broken.
- [ ] **D2.5 — test it as behaviour, not as wiring.** Offscreen: start
  in `"system"`, click the toggle, and assert
  `theme.BG_SURFACE == LIGHT.BG_SURFACE` **and** that the string
  returned by the application's current stylesheet contains
  `LIGHT.BG_SURFACE`. Then cycle all three modes and assert the module
  tokens match the expected palette at each step. The existing tests
  presumably assert the mode string and the icon — which is exactly
  what stayed correct while the feature was broken.
- [ ] **D2.6** Then verify for real: screenshot the same page in all
  three modes on the actual desktop, plus the title bar (C5.5's
  `setColorScheme` claim has still never been checked on a real Mac).

---

## D3 — Search and Duplicates leave dead space to the right of "Actions"

**A regression introduced by C2**, and confirmed by the screenshots:
in both tables every column is roughly the same modest width, including
Filename and Path — the two columns that are supposed to be
`ResizeMode.Stretch` (`main_window.py:2342` and `:4386`). They are not
stretching. That is why the columns stop short of the viewport.

The cause is C2.3's blanket floor loop in `apply_table_defaults`
(`theme.py:399-403`):

```python
for column in range(table.columnCount()):
    floor = header_label_floor(table, column)
    if header.sectionSize(column) < floor:
        header.resizeSection(column, floor)
```

`resizeSection()` is applied to **every** column, including the one the
caller will designate as `Stretch` and the ones set to
`ResizeToContents`. Pinning a section to an explicit width fights the
mode that is supposed to own it, and the stretch column ends up sitting
at its header-label floor — "Filename" or "Path", a handful of
characters wide — instead of absorbing the remaining viewport. The sum
of all sections then falls well short of the viewport width, and the
shortfall is the empty band the user sees.

C2 itself was right; applying its floor indiscriminately was not.

- [ ] **D3.1 — measure before changing anything.** For the Search and
  Duplicates tables, print each `sectionSize(i)`, each column's
  `sectionResizeMode(i)`, `sum(sectionSize)` and `viewport().width()`,
  with zero rows and with real rows. Report the real numbers. The
  shortfall should equal the gap; if it does not, this diagnosis is
  incomplete — say so.
- [ ] **D3.2** Apply the header-label floor **only** to `Interactive`
  and `Fixed` columns. `Stretch` and `ResizeToContents` size themselves
  and must not be pinned. Note in the comment that this is the whole
  bug: the floor was correct, its scope was not.
- [ ] **D3.3 — ordering matters too.** `apply_table_defaults` runs at
  construction, before the caller assigns resize modes, so at that
  moment every column still reads as the default mode. Split the
  responsibilities: keep `apply_table_defaults` for header/row chrome,
  and add a `theme.apply_column_floors(table)` that the caller invokes
  **after** setting its resize modes. Audit every table for the new
  call; a table that misses it regains the ".ction" bug, so make that
  failure visible (see D3.5).
- [ ] **D3.4** `size_action_column` runs on every render and calls
  `resizeSection` on the Actions column. Confirm the stretch column
  reclaims space when the Actions column *shrinks* between renders —
  Qt only recomputes stretch sections on a `resizeSections()` pass, so
  it may need an explicit nudge (re-assert the stretch column's mode
  after resizing the fixed one). Verify with the same measurement as
  D3.1, before and after a render that narrows Actions.
- [ ] **D3.5 — the regression test that would have caught this.** For
  every table that has a `Stretch` column: assert
  `sum(sectionSize(i)) >= viewport().width() - 2` (no dead band), with
  zero rows and with rows, at 960×640 and at the default size. Pair it
  with C2's existing "no header label is clipped" assertion, because
  the two pull in opposite directions and both must hold at once.
- [ ] **D3.6** Screenshot Search and Duplicates, empty and populated,
  before and after.

---

## D4 — Closing a fullscreen window leaves a black Space

On macOS a fullscreen window owns its own Space. `closeEvent`
(`main_window.py:6204`) does:

```python
event.ignore()
self.hide()
self._hidden_to_tray = True
```

Hiding a window that is currently fullscreen leaves that Space in place
with nothing in it — the black screen the user landed on. The Space is
only torn down when the window leaves fullscreen, which never happens.
The window then reappears correctly from the menu bar because
`_on_tray_open_seeker` calls `showNormal()`, which does leave
fullscreen — which is why the second close behaved.

- [ ] **D4.1** In `closeEvent`, when `self.isFullScreen()`, leave
  fullscreen **before** hiding. The transition is animated and
  asynchronous, so hiding in the same call will race it: exit
  fullscreen, then hide once the state change has actually landed —
  either from `changeEvent`/`QEvent.Type.WindowStateChange`, or via a
  short single-shot timer with a comment saying the delay is a real
  observed animation duration rather than a guess.
- [ ] **D4.2** Restore the window to its pre-fullscreen geometry, so
  reopening from the menu bar gives back the window the user had rather
  than an arbitrary default.
- [ ] **D4.3** Check ⌘W and ⌘Q from fullscreen too, and the tray menu's
  own Quit — all four paths reach different code and only one has been
  tested.
- [ ] **D4.4** Verify on the real desktop: fullscreen → red button →
  confirm no black Space is left behind and the app is genuinely in the
  menu bar → reopen → confirm geometry. This one cannot be verified
  offscreen at all; say so plainly rather than reporting it as done from
  a unit test.

---

## D5 — Clicking the menu bar icon opens the window

`_on_tray_icon_activated` (`main_window.py:6097`) connects
`ActivationReason.Trigger` to `_on_tray_open_seeker()`, guarded only by
the comment quoted at the top of this brief — which claims Trigger never
fires on macOS. The user's report is direct evidence that it does: a
single left-click on the menu bar icon both opens the menu and restores
the window, which is not what a menu bar extra should do.

- [ ] **D5.1** Do not connect the `Trigger` branch on macOS
  (`sys.platform == "darwin"`), or return early from it there. Keep the
  Windows/Linux behaviour, where a left-click genuinely does nothing
  otherwise.
- [ ] **D5.2** Replace the comment with what was actually observed on
  this machine, including the Qt and macOS versions, per the standing
  note above. If a double-click should still open the window on macOS,
  wire `DoubleClick` explicitly and say so.
- [ ] **D5.3** Verify by clicking the real menu bar icon: the menu opens
  and the window stays hidden. Then confirm "Open Seeker" in that menu
  still works.

---

## Commits, and reporting

One commit per D-item, each verified before the next. `mypy --strict`
clean, real test numbers named inline.

The screenshot gate from round 5 stands and applies to D1, D2 and D3.
D4 and D5 cannot be verified offscreen at all — they are real-desktop
checks or they are not done, and "the unit test passes" is not a
substitute. If you cannot run them, list them as outstanding rather than
as complete; the user can run both in under a minute.

Roadmap item 70 (the stress-test hang) — note that round 5 root-caused a
*different* intermittent hang (the queued `QMessageBox`). State whether
item 70 is now believed to be the same defect or still separate, since
five rounds of carrying it forward without that answer is its own
problem.

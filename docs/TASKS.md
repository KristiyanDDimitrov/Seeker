# Task ledger — work block: docs/BRIEF-2026-09-05.md (round 5)

Working ledger for this block only (not a permanent doc). One line per
brief item, ticked when done and verified. Commit order follows the
brief's own stated ordering: C1 → C2 → C3 → C4 → C5 → C6.

## C1 — Header column dividers, third attempt

- [x] Real bisect (not a third guess) found the actual cause:
  `QHeaderView::section:horizontal:last-child` is invalid Qt QSS and
  its mere presence poisoned the whole `::section` rule, dropping
  `border-right` everywhere. Deleted it (kept `:last`, which alone
  already works); switched header dividers to `BORDER_STRONG` (1.98:1
  vs. `BORDER`'s 1.46:1). Bigger finding: `theme.apply_theme()` was
  never called anywhere in the test suite before this — every prior
  "pixel-verified" claim was rendered under Qt's default style, not
  the real one. Fixed with a new session-scoped `conftest.py` fixture.
  Also found and fixed a latent `devicePixelRatio` bug in two
  `window.grab()` pixel tests. 1056 passed, 1 skipped.
  [HISTORY §103](HISTORY.md#103)

## C2 — "Action" reads as ".ction" on an empty table

- [x] `theme.size_action_column`'s fallback for zero action widgets was
  a generic 40px floor; new `theme.header_label_floor()` derives a
  real minimum from the header's own text via `QFontMetrics`, applied
  both as the fallback AND as a floor on every column via
  `apply_table_defaults`. Screenshot-confirmed: Review's three empty
  tables all show "Actions" in full. Also recorded (not fixed): a
  real, intermittent full-suite stall caught live via `lldb` — later
  root-caused in C3. 1058 passed, 1 skipped.
  [HISTORY §104](HISTORY.md#104)

## C3 — Dashboard progress bar, a second untouched site

- [x] `_render_track_statuses` built its own bare `QProgressBar` —
  B4/item 96 only fixed the Downloads page's builder. Wrapped through
  the same `_wrap_progress_bar` container. Swept all 13 real
  `setCellWidget(` call sites; only this one and a harmless empty
  `QWidget()` were bare. Root-caused C2's "open finding" for real: not
  intermittent — three tests waited only for a service call to
  register, not for the worker's own `QMessageBox.information()` to
  fire, leaving it queued to pop a real blocking modal during a later
  test. Fixed by mocking it in all three. Full suite: 1060 passed, 1
  skipped, in 70.71s (no stall — was inflated by real stall minutes
  before this fix). [HISTORY §105](HISTORY.md#105)

## C4 — Wordmark: brows over the real "ee"

- [x] New `_Wordmark(QWidget)` replaces the plain `QLabel("Seeker")`,
  drawing text at 20px bold then compositing `packaging/icons/
  seeker_brows.svg` above the "ee" (span derived from one
  `QFontMetrics` call). SVG rendered to a `QPixmap` once and tinted via
  `CompositionMode_SourceIn` (`ACCENT`) — one asset serves any future
  palette. Degrades to plain text if the asset is missing (tested).
  Screenshot-confirmed at real size, in context. 1063 passed, 1
  skipped. [HISTORY §106](HISTORY.md#106)

## C5 — Light and dark themes, with system-follow

- [x] The large item. `theme.py`: frozen `Palette` dataclass (`DARK`/
  `LIGHT`), `build_stylesheet(palette)`/`build_qpalette(palette)`,
  `apply_theme(app, mode)`. All 10 real per-widget `setStyleSheet()`
  calls converted to objectName/property + global-stylesheet rules;
  `InlineNotice` now uses `theme.set_variant()`.
  `MainWindow._apply_theme_mode()` is the one entry point every switch
  routes through (sidebar toggle, Settings' new "Appearance" radios,
  `colorSchemeChanged` while `mode=="system"`). Persisted via new
  `SeekerConfig.theme_mode`. Toggle is a hand-drawn sun/moon/split-
  circle (`QPainter`, no assets) — the logo-derived idea was tried and
  rejected. **Two real contrast bugs found via actual screenshots, not
  the brief's own scope:** the progress-bar percentage text was nearly
  invisible in light mode (1.26:1, fixed by switching `TEXT_MUTED` →
  `TEXT`), and the primary button put near-black text on a purple fill
  in light mode (fixed with a new `ON_ACCENT` token). Also corrected
  the brief's own claimed DARK-accent-on-white contrast number (2.9:1
  claimed, 4.35:1 real). Verified with real `window.grab()` screenshots
  across every real page in both themes, all four `InlineNotice`
  variants, the About dialog, and the app's 960×640 minimum. 1086
  passed, 1 skipped. [HISTORY §107](HISTORY.md#107)

## C6 — SoundCloud: deferred, research recorded

- [x] No code, per the brief's own instruction. Recorded as CLAUDE.md
  roadmap item 108: two disqualifying blockers (Artist Pro required to
  register an app; SoundCloud requires a `client_secret` even for
  native apps) and the bring-your-own-credentials architecture if ever
  picked up.

---

## Brief closed

All six items (C1–C6) addressed: five real code fixes/features
committed (C1, C2, C3, C4, C5) plus C6's documentation-only deferral.
Every visual item was screenshot-verified per this round's own gate —
a real `window.grab()` was inspected, not just measured, for every
item C1–C5. Two real bugs found beyond the brief's own named scope:
the full-suite stall (root-caused in C3, not just recorded) and the
two contrast regressions found while producing C5's own screenshot
sweep (fixed in the same commit).

**Left for the user, blocked by this sandboxed session's own real
permission/environment gaps (not attempted-and-failed):**
- C5.9/C4 — the real macOS menu bar icon and title-bar color-scheme
  follow, both in real light/dark appearance (no Screen Recording
  permission in this session; same gap as items 84/89/90/99).

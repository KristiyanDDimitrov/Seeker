# Task ledger — work block: docs/BRIEF-2026-09-03.md (round 2)

Working ledger for this block only (not a permanent doc). Every item from
the brief, one line each, ticked only when done *and* verified, with a
one-line result + commit sha. Items not done as briefed are marked
`NOT DONE — <reason>`, never silently dropped.

Commit order per the brief: P7 → P8 → P12 → P11 → P9 → P10 →
0.1/0.2/0.3 → P13.

## P7 — Duplicates "Actions" column, 5th report

- [x] 7.1 Ran the brief's exact standalone PySide6 repro
  (`QT_QPA_PLATFORM=offscreen`). **Hypothesis CONFIRMED**: blank
  widget's geometry == real widget's geometry (both `(100, 0, 99,
  59)`), child order `[REAL, BLANK]` (blank added later, paints on
  top), `childAt(center)` returned the blank widget, not the real one
  — despite `real.visibleRegion()` being the FULL non-empty rect. This
  is exactly why item 73's own geometry/visibleRegion test passed
  anyway: occlusion is a paint-order property, not a geometry one.
- [x] 7.2 Fixed in `_render_duplicate_groups`: `setSpan()` now called
  BEFORE `setCellWidget()` for the group's first row (so the real
  widget's geometry is computed against the final span rect), and the
  `for other_row … setCellWidget(..., QWidget())` loop deleted
  entirely — covered rows get no cell widget at all; the span itself
  is what makes them read as blank.
- [x] 7.3 Audited every `setSpan` call site (`grep -n setSpan`): only
  one other exists, the Sharing-uploads empty-state span
  (`main_window.py:1814`), which uses `setItem` not `setCellWidget` —
  no widget-occlusion risk there. No other instance found.
- [x] 7.4 N/A — 7.1 confirmed the hypothesis, no pixel-diff needed.
- [x] 7.5 New occlusion-aware regression test,
  `test_duplicates_actions_widget_is_not_occluded_by_a_covered_row_widget`
  — asserts `viewport().childAt(visualRect(...).center())` resolves to
  the real widget (or a descendant of it), not merely that the widget
  exists or has nonzero `visibleRegion()`. **Verified it actually
  catches the regression**: reverted the source fix only, reran this
  one test in isolation — fails with the exact predicted
  `hit is not real_widget` assertion; passes again with the fix
  restored. Updated one pre-existing test
  (`test_render_duplicate_groups_actions_only_on_group_first_row`) to
  assert `cellWidget(1, ACTIONS) is None` instead of "a blank widget
  with no buttons" — the corrected behavior per 7.2.

`mypy --strict src/` clean (82 files). Full suite: 908 passed, 1
skipped (0 failures) — 1 net new test, 0 regressions (the one
`test_history_refresh_button_refetches` failure is the pre-existing
documented flake, reconfirmed passing in isolation).

**Commit boundary — pending.**

## P8 — Duplicates "0 files in scope" + P9 — location combo disabled

Combined into one commit (deviating from the brief's listed order,
noted explicitly): P9's "keep the combo enabled" change has no real
value until P8's most-specific-wins fix lands to make the combo a
genuine tiebreak, and both touch `resolve_folder_scopes`' exact same
signature.

- [x] 8.1 Ran the real query against THIS session's own real
  production DB (same machine/account this session has filesystem
  access to — the brief's "other account" is a different macOS user
  this session cannot reach, noted as a limitation). Real result:
  `x9-pro` (3264 files, 3161 fingerprinted), `Test` (8 files, 4
  fingerprinted, nested at `/Volumes/X9 Pro/Music/Test`), `Music` (0
  files, 0 fingerprinted, registered at `/Volumes/X9 Pro/Music` — the
  PARENT of `Test`). This is 8b's exact scenario, live and
  reproducible right here — simulated `resolve_folder_scopes`'s old
  alphabetical-first logic against these real rows: a folder equal to
  `Test`'s own path matches `Music` first (alphabetically "Music" <
  "Test"), which has 0 scanned files — confirming 8b as a real,
  demonstrated defect in real data, not merely a theoretical one.
- [x] 8.2 `resolve_folder_scopes` now scores every candidate location a
  folder resolves inside by resolved-path length and keeps the
  LONGEST (most specific); a genuine tie (only possible via
  Path.resolve() collapsing two different registered paths to the
  same real directory, e.g. a symlink — `library_locations.path` is
  UNIQUE at the DB level so two locations can never share a literal
  path string) breaks via a new optional `preferred_location_id`
  param, else falls back to the existing stable alphabetical order.
  Two new tests: nested-location most-specific-wins (reproduces the
  real 8.1 shape structurally), and a real symlink-based tie test.
- [x] 8.3 New `DuplicateService.summarize_scopes()` → `ScopeSummary`
  (file_count, resolved_location_names, empty_locations).
  `format_duplicates_scope_count()` now names the resolved location(s):
  "216 files in scope (Music)."
- [x] 8.4 Same `ScopeSummary.empty_locations` — when non-empty, the
  message says plainly which location has no scanned files yet and to
  run Rescan and match library first, instead of a bare "0 files in
  scope."
- [x] 9.1 `duplicates_location_combo` stays enabled always; wired as
  `resolve_folder_scopes`' `preferred_location_id` at every UI call
  site (`_refresh_duplicates_folder_scope_count`,
  `_compute_fingerprints_for_folders`, `_on_find_duplicates_clicked`),
  captured on the MAIN thread before entering a background worker
  closure (reading Qt widget state off-thread is unsafe) and passed
  in as a plain int parameter. A `currentIndexChanged` handler
  refreshes the scope count live when the preference changes.
- [x] 9.2 Both tooltips reworded to describe the real tiebreak
  behavior; the stale "disables the combo" comment removed.

`mypy --strict src/` clean (82 files). Full suite: 913 passed, 1
skipped (0 failures) — 5 net new tests, 0 regressions (the
`test_history_refresh_button_refetches` flake did not reproduce this
run either).

**Commit boundary — pending.**

## P12 — Qt mnemonic in "Rescan & match library" + P11 — tagging controls spacing

Combined into one commit (both small, independent, no shared code —
grouped per the brief's own "small, independent, quick wins" framing
for this trio; P9 was already folded into the P8 commit above).

- [x] 12.1 `"Rescan & match library"` → `"Rescan and match library"`.
  `"&Help"` (the real menu-bar mnemonic) left untouched.
- [x] 12.2 Audited every `QPushButton`/`QLabel` string literal in
  `main_window.py` via `grep`/a real regex — no other stray `&` found.
  New source-level regression test scans the file for any
  `QPushButton("...")`/`QLabel("...")` literal containing a bare `&`
  (a doubled `&&` or the real `"&Help"` mnemonic don't count) — covers
  any future string added to this file automatically, not just the
  one fixed here.
- [x] 11.1 `FlowLayout(h_spacing=theme.SPACING_SM,
  v_spacing=theme.SPACING_SM)` — bare `FlowLayout()` left both at -1,
  falling through to a style-derived spacing that's effectively zero
  under this app's Fusion styling. **Verified it actually fixes a
  real, measured overlap**: reverted the fix in isolation and reran
  the new spacing test — real adjacent items measured -2px apart
  (touching/overlapping), not merely "less than ideal."
- [x] 11.2 Confirmed structurally, not just by inspection: FlowLayout's
  own `_do_layout` always calls `item.setGeometry(..., item.sizeHint())`
  — every VISIBLE item always gets its own full sizeHint() width, so
  no truncation was ever possible once 11.1's spacing is in place. New
  test asserts both checkbox labels render at their full sizeHint()
  width.
- [x] 11.3 New test asserts a real non-zero (>= `SPACING_SM`) gap
  between every pair of adjacent VISIBLE items' geometries, checked at
  both a wide (single-row) and a narrow (multi-row wrap) width.
  (`bpm_min_edit`/`bpm_max_edit` start `.hide()`'n — `QWidgetItem.
  setGeometry()` is a real Qt no-op for a hidden widget, so they're
  excluded from the gap check, not silently miscounted.)

Two pre-existing tests asserting the literal old button text updated
to match the real intentional rename (12.1), not silently xfailed.

`mypy --strict src/` clean (82 files). Full suite: 916 passed, 1
skipped (0 failures) — 5 net new tests, 0 regressions.

**Commit boundary — pending.**

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

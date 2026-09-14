# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `f9aa687`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1186
  passed, 2 failed, 29 skipped`** — the 2 failures are the documented
  fullscreen-close pair, order-dependent (pass in isolation, fail only
  under the full suite). Confirmed pre-existing this session via `git
  stash -u`: identical 2 failures on unmodified HEAD, same area. On a
  second full-suite run with this session's changes present, the exact
  same 2 tests failed again (`test_reopening_after_a_fullscreen_close_
  restores_prior_geometry`, `test_fullscreen_close_policy_check_
  ignores_a_stale_request`) — one earlier run in between also surfaced
  a third test in the same area
  (`test_fullscreen_close_schedules_a_policy_only_check`), consistent
  with CLAUDE.md's already-tracked "two different tests in the same
  fullscreen-close area, only under the full suite" flake.
- **`mypy --strict src/`: clean, 103 files. `ruff check src tests`: 0
  findings.**
- **CI on `f9aa687` (this session's push): run `34857398720`, `2
  failed`.** ruff/mypy both clean; new `src/seeker/ui/pages/
  review_page.py` code shows 98% coverage. The 2 failures are the
  OTHER already-tracked CI-only flake pair
  (`test_history_refresh_button_refetches`,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_
  delete_flag`) — the same pair that failed on S7's own CI run
  (`34840265764`), not new, not this session's diff (the replace-
  button test lives in `tests/pages/test_review_page.py` and exercises
  the same page this session touched, but it's the specific,
  multiply-recurring flake CLAUDE.md's Open issues already tracks by
  name — see that section for the recurrence history).

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1-S8.**
- **Next: S9** — Library page, lift the selection seam (§7.1, pure
  refactor, no visible change). Hard stop named in the session map: no
  visible change in this row.

## S8 report — §6, Review page resizable panes

**What landed:**
- `src/seeker/ui/pages/review_page.py` — the three Review sections
  (needs-review, downloaded upgrades, local matches) moved from a
  plain `QVBoxLayout` stack into a `QSplitter(Qt.Orientation.Vertical)`
  (`review_splitter`). Each section's header row and card are wrapped
  in one `QWidget` so the whole section moves as a unit (the upgrades
  header row, including "Replace all," travels with its table).
  `setChildrenCollapsible(False)` plus a real `minimumHeight`
  (`_REVIEW_SECTION_MIN_HEIGHT = 140`) per section keeps every pane
  recoverable. First-run proportions are `setStretchFactor` 3:2:2
  (needs-review favored — the section acted on most), not equal
  thirds.
- Persistence mirrors `window_geometry`'s existing pattern exactly:
  `config_store.SeekerConfig.review_splitter_state: str | None` (base64
  of `QSplitter.saveState()`), written by a new
  `ReviewPage._persist_splitter_state()` called from
  `MainWindow.cleanup_before_quit` — **unconditionally**, unlike the
  `_hidden_to_tray`-gated window-geometry backstop next to it, since a
  hidden-to-tray splitter still reports its real current sizes (only
  the top-level window's own `saveGeometry()` has that visibility
  quirk).
- Restore (`ReviewPage._restore_splitter_state`) is called from a new
  `ReviewPage.showEvent()`, guarded to fire once, on the page's first
  real show — the same §3.1 failure mode (restoring before the
  splitter has real, laid-out geometry distributes the saved sizes
  against the wrong total; this page sits hidden inside MainWindow's
  `QStackedWidget` until first navigated to). Verified live with a
  scratch two-`MainWindow` script: a dragged split round-tripped
  through persist/restore byte-for-byte once both windows shared real
  geometry (script deleted after use).
- `theme.py`'s `_misc_qss` gains `QSplitter::handle` rules —
  `BORDER_STRONG` (same reasoning as the table-header divider),
  `ACCENT` on hover, 6px thickness matching `setHandleWidth()`.
  Confirmed visible in both themes via a real offscreen `window.grab()`
  screenshot (scratch check, not committed).
- No new dedicated test file — `tests/pages/test_review_page.py` and
  `tests/test_ui_smoke.py` already construct/interact with the three
  tables by attribute name, which the restructuring preserved, so
  existing tests cover section rendering unchanged. **A real gap**: no
  automated test asserts the splitter's persist/restore round-trip, or
  that `_persist_splitter_state` is called from `cleanup_before_quit`
  — only verified via a scratch script this session. Worth adding if a
  future session touches this page again.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

See `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris" section —
unchanged by this session. Carried from round 8, still open: click
through the Review page's new splitter on a real display (drag each
handle, quit, reopen, confirm the drag survived) — this session only
verified the persist/restore round-trip mechanically, never on a real
Mac.

## Open questions

- **No automated test covers the splitter persist/restore round-trip**
  (see S8 report above) — only manually/mechanically verified this
  session via a scratch script, not committed.
- Item 125 (the §2.3 quit hang), the two S4 flakes (fullscreen-close
  pair), and the CI-only flake pair (history-refresh/replace-button)
  are all unchanged — this session's own local and CI runs reproduced
  them again, nothing newly fired. Tracked in CLAUDE.md's Open issues;
  not re-litigated here.
- `docs/HISTORY.md` is now ~890 KB — still never read whole. No
  HISTORY entry written yet for §3.2 (carried from S7) or §6 (this
  session) — worth a combined two-tier docs pass if a future session
  has budget (Working agreement #1).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.

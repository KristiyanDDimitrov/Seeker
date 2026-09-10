# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `32713ce`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine):** `1147 passed, 29
  skipped in 88.69s` — clean, no flakes fired locally this session.
- **Real CI (`gh run view 34452439345`, the push of this session's
  final commit `32713ce`): ruff/mypy clean, pytest fully green.** The
  prior push in this session (`34452031576`, commit `d1701bf`) DID
  fail pytest — one real failure,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`,
  already a tracked round-8 flake in CLAUDE.md's Open issues. Passed
  5/5 re-run locally immediately after; this session's own diff
  doesn't touch that test's code path. Recorded as a second real
  recurrence in CLAUDE.md rather than silently re-pushing past it —
  see that file's Open issues section.
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings** (both local and on CI).

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1, S2** (see prior handoffs / HISTORY §115-§121).
- **Done: S3** — Table sorting correctness (§5.1, §5.2, §5.3), five
  commits: `39f54f5` (§5.1), `9157a93` (§5.2), `d1701bf` (§5.3),
  `10650b6` (CI flake recorded), `32713ce` (session-plan tick).
- **Next: S4** — Quit semantics + confirmation dialog (§2.1, §2.2).

## S3 report

**§5.1.** Dashboard's and Downloads' Progress columns were
`setCellWidget`-only, no `QTableWidgetItem` — click-to-sort compared
nothing and was a silent no-op. Added a `SortKeyItem` (already
existed in `ui/table_sort.py`) alongside each progress widget, keyed
on fraction complete (not raw bytes) so same-percentage rows sort
together regardless of file size. `-1.0` sentinel for "nothing real
to show" rows (never `None`).

**§5.2 — the round's real seam work.** Same root cause hit every
Actions column app-wide. Fixed once in `theme.configure_columns`,
keyed off `ColumnLayout.actions` (already existed, no new field
needed — the brief's own bet paid off). Mechanism:
`sortIndicatorChanged` continuously tracks the last real (non-Actions)
sort state; `sectionClicked` on the Actions column restores it. Two
signals are required, not one — by the time `sectionClicked` fires,
Qt's own mouse handling has already flipped the indicator and
re-sorted, so reading `sortIndicatorSection()` inside that handler
would read the wrong (new) value. Verified with a **real**
`qtbot.mouseClick` on header coordinates (`tests/test_theme.py`) — a
manually emitted `sectionClicked` signal would skip the exact Qt code
path the fix depends on and pass for the wrong reason.

**§5.3.** Audited all 13 real `.setCellWidget(` call sites (7 files —
the brief's own count of "ten" was an undercount, corrected in
HISTORY). Full table in HISTORY §122. Duplicates' two sites remain
correctly excluded (`setSortingEnabled(False)`, grouped via
`setSpan()`). Every other site now either has a real sort key or is
covered by §5.2's generic veto.

**A real CI-only flake fired** on this session's own push (see
above) — not a regression, already tracked, recorded with the new
evidence rather than ignored.

**Skills used:** `improve-codebase-architecture` was the row's
assigned bundle — the actual available skill list this session (see
`docs/round9/SESSION-PLAN.md`'s own resolve-at-start step) had no
exact match by that name; proceeded directly per the brief's own very
explicit mechanism instructions, same divergence pattern S1/S2 already
noted.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

Unchanged from `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris"
section — see that file, not here, for the current list (approval
gates on §4.2b/§3.2/§1.2-fallback/§8.1-§8.5, and the real-desktop
checks Code cannot do). Nothing in S3 added a new one.

## Open questions

- **`test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`
  fired a second time, on real CI, this session** (`gh run
  34452031576`) — see CLAUDE.md's Open issues, updated with this
  recurrence's detail. Two real CI failures with zero local repro
  either time is stronger evidence of a genuine race than the
  single round-8 occurrence was. Worth a dedicated diagnosis session
  if it recurs a third time; not diagnosed this session (out of S3's
  scope, and the brief's own row didn't point at it).
- **`test_history_refresh_button_refetches` is still an open flake**
  (carried from S2) — instrumentation in place (HISTORY §121), no
  real natural-recurrence snapshot captured yet.
- Carried, unconfirmed: the fullscreen-close pattern and
  `test_callback_server.py` trio in CLAUDE.md's Open issues — neither
  fired this session (2 full-suite runs total), not evidence they're
  gone.
- `docs/HISTORY.md` is now ~850 KB — still never read whole.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.

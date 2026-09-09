# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `7dadb17` — "S15 §12.2: sortable tables". Working tree
  clean except this handoff rewrite + the session-plan tick, about to
  be committed.
- **`origin/main`: at `ccafc61`, 2 commits behind local HEAD** (the two
  S15 commits below). **Ask before pushing.**
- **pytest:** `2 failed, 1160 passed, 1 skipped in 99.27s` — both
  failures are the same already-tracked fullscreen-close flakes
  (`test_fullscreen_close_policy_check_ignores_a_stale_request`,
  `test_reopening_after_a_fullscreen_close_restores_prior_geometry`),
  confirmed passing individually again this session. 1 skipped is the
  real-hardware number.
- **`mypy --strict src/`: clean, 100 files. `ruff check src tests`: 0
  findings.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done: Phase 0-7 (through S13), S14, and now S15 (a subset).**
- **Next: nothing scheduled.** Kris approved §12.1/§12.2/§12.3/§12.5 of
  S15's Group A this session; **§12.4 (accessible names) was
  explicitly NOT selected** — open, no further yes given. Group B
  (§12.6-§12.10) remains a product decision, not scheduled.

## S15 report (two commits: `9856bc3`, `7dadb17`)

**§12.1:** `SeekerConfig.window_geometry`/`last_open_page`
(config_store.py), round-tripped via `saveGeometry()`/
`restoreGeometry()` base64-encoded at real quit
(`cleanup_before_quit` -> `_persist_window_geometry`) and on
construction (`_restore_window_geometry`). Closing while on Settings
persists the page underneath it, not the transient "settings" key. A
corrupt/foreign stored value is tolerated silently.

**§12.3/§12.5:** new View menu (⌘1-⌘7 nav pages, ⌘R refresh, ⌘F focus
search, ⌘, Settings, Toggle Theme) and Window menu (Minimize/Zoom).
Menu bar previously held only Help.

**§12.2 (sortable tables) — pulled in real correctness work beyond the
brief's one-line description, caught by the test suite itself, not
just reasoned about:**
- `QHeaderView` defaults `sortIndicatorSection` to `0`, not "no
  column" — `setSortingEnabled(True)` alone silently auto-sorted every
  table by column 0 ascending on first populate. Caught two real
  existing tests failing on exactly this (Search's "best quality
  first" ranking, Sharing's reconciliation order, both alphabetized).
  Fixed via `setSortIndicator(-1, ...)` in `apply_table_defaults`.
- Every table rebuilds via `setRowCount()` + `setItem()` addressed by
  loop index; live sorting mid-loop desyncs those indices. Every
  rebuild now runs inside `with preserving_sort_order(table):` (new
  `ui/table_sort.py`).
- Three call sites (Dashboard's double-click/context-menu/bulk-select,
  Review's dashboard-double-click focus-and-select) resolved a row via
  a parallel Python list's insertion-order index — wrong the moment a
  user sorts. Fixed by anchoring each row's real id via
  `Qt.ItemDataRole.UserRole`. `_focus_pending_review_row`'s signature
  simplified (dropped the now-unused list params) accordingly.
- History's "When", Search's Bitrate/Size/Score, Review's Score,
  Sharing's file count display formatted text that sorts wrong against
  its real meaning (date by month name; "128"/"320"/"96" kbps as
  text). `SortKeyItem` (`ui/table_sort.py`) carries the real sort key
  separately from the displayed text.
- Duplicates' table stays explicitly NOT sortable — rows are grouped
  per cluster via `setSpan()`, which sorting would visually corrupt.
- 14 new regression tests: 11 for §12.1/§12.3/§12.5, 3 targeting the
  sort-safety bugs above (sorted-then-double-click, chronological
  History sort, sorted-then-focus in Review).

**Verification note (CLAUDE.md's platform-claim rule):** verified via
`qtbot`/offscreen Qt, not a live human on a real Mac window (no display
here). One gap found directly: `saveGeometry()`/`restoreGeometry()`'s
SIZE round-trips exactly under offscreen; X/Y POSITION does not —
plausibly an offscreen-only artifact (standard Qt idiom otherwise), but
genuinely UNVERIFIED on real hardware.

## Read discipline — this is why sessions were costing 300-700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief for a phase you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Click the Dock icon after a normal close and after a fullscreen
      close; confirm the window returns. Reopen via Spotlight too.
- [ ] From a second device, confirm `http://<mac-lan-ip>:5030` no
      longer answers.
- [ ] Push the 2 unpushed S15 commits to `origin/main` (or say go
      ahead) — `origin/main` is currently at `ccafc61`, 2 behind local
      HEAD.
- [ ] **New this session:** quit the real app after resizing/moving the
      window, relaunch, confirm it reopens at the same size AND
      position — position is unverified under offscreen testing (S15
      report above).
- [ ] Decide §12.4 (accessible names) and/or Group B (§12.6-§12.10) —
      approve or skip; nothing scheduled without a yes.

## Open questions

- **Is the GitHub repo private?** `github.com/KristiyanDDimitrov/
  Seeker/actions` 404s anonymously — if so, `update_check.py`'s 404-
  means-"no releases" assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
- **Round-8 flakes (five total, in CLAUDE.md's Open Issues)** —
  diagnose any recurrence directly, never `pytest-rerunfailures`. The
  two fullscreen-close ones fired together again this session (S15
  never touched that code — not a regression); two same-area tests
  failing together only under the full suite is stronger evidence of a
  real bug than either alone, worth a dedicated session if it recurs
  again.
- **`docs/HISTORY.md` is ~14,100+ lines** — still never read whole, per
  the standing rule.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

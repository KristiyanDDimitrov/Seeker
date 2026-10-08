# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S3 close-out (HISTORY §195). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2044 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S1, S2 and S37/S38 (S9 owns it).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** `0032235`'s run `37831789311` green: `2018 passed, 29
  skipped`, coverage 94.54 % (floor 92 %).

## 2. Where we are

**Round 12 S3 is done.** **Next: S4**, status columns sort by
progress, closest to done first (BRIEF §4; `tdd`). Its sort keys must
survive S3's render-on-change. On Review nothing sorts by status, but
the Dashboard updates sort keys in place on a progress-only change
(`_update_progress_in_place`), and Downloads still rebuilds every
tick.

## 3. Session report (S3)

- `e9604d0`, §3.1–§3.2: each Review table keeps the rows it was last
  built from and skips an equal tick. Three new tests; the checkbox
  test now forces a real rebuild.
- The close-out: HISTORY §195, one fact in `src/seeker/ui/CLAUDE.md`,
  the plan tick, this file.
- CI: run `37831789311`, green.

## 4. Key context

- **A shown tooltip dies with its widget, but survives its item being
  replaced** (observed on Cocoa with real `QHelpEvent`s, HISTORY
  §195). Only a rebuilt widget that carries a tooltip loses it.
  Downloads' 2 s rebuild is therefore harmless to its tooltips.
- **Waiting on a render that changes nothing:** S3's tests change
  another table in the same tick and wait on that, since an equal
  render leaves nothing to observe.
- **Sharing's locations table** rebuilds its per-row "Add to my
  SoulSeek share" button (with a tooltip) on every 20 s backend poll
  after the first visit. Same bug class, not fixed: it is outside
  S3's "2-second pollers" scope. **For S15**, or a row of its own.
- **For S16: `uv build --wheel` packages whatever is in
  `src/seeker/`,** including a gitignored `_build_info_generated.py`
  left by a local DMG build. `wheel-exclude` already drops
  `CLAUDE.md`.
- **S9 owns:** the two radon-D functions and the two undiagnosed
  tests (the CI flake
  `test_search_download_best_passes_the_already_fetched_results`,
  `37599402903`; the Cocoa-only theme failure, whose first untried
  check is a rerun with only the built-in display).
- **Planning found, for later rows:** the Dashboard's Status column
  sorts by label text (S4). The "daily" retry never existed (S10).
  `urllib3 2.7.0` has three advisories, fixed in 2.8.0, and CI has no
  dependency audit (S7).
- **Carried:** set `set -o pipefail` before `pytest … | tail && git
  commit`. Never touch slskd or real data. The full suite takes
  ~4.5 min, so run it in the background, and never stash `src/` while
  it runs. `git stash push -- <paths>` to test HEAD's `src/` with the
  new tests.

## 5. Decisions made

- **Review's key is the rows alone, without the palette** the brief's
  suggested shape included. Nothing in a Review row bakes in a colour
  (QSS buttons, `SECONDARY_ROLE` read at paint time). If a row ever
  gains a lamp, the palette joins the key (the ui/CLAUDE.md rule).
- **The key is the full row data, not only the ids:** a changed score
  or filename for the same track must show.
- **Skills:** `tdd` was used. `focused-fix` was not loaded: the brief
  had already pinned the cause to one method in one module, and the
  probe settled the audit. The seams were named by the brief
  (`poll_review_items`, the row's button), so no question was asked.

## 6. Blockers

None.

## 7. Files in progress

None: S3 is committed whole.

## 8. Waiting on Kris

**A live check (S3):** on Review, hover Confirm or Replace and keep
the pointer still for 5 s or more; the tooltip should stay.

**From S1/S2, still a cheap veto:** the new colours (images in
HISTORY §193), the spin arrows and `90.0` (HISTORY §194). A live
check: in Dark, choose Light, then Follow system; the app should turn
dark at once.

**Open gates:** reading `AUDIT.md` after S6, the S5 wording veto, the
first live Cancel (S12) and cleanup (S13), and the S18 publishing
commands. Also the wordmark's brows over "ee" (`9ff777b`).

**Live checks:** round 12 BRIEF §17, plus the carried list in
`git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
three nested locations.

## 9. Open questions

- Should Sharing's 20 s rebuild get the same fix in S15, or a row of
  its own? (§4 above.)
- Unchanged from S36: see `git show 1b415a4:docs/HANDOFF.md` §9 (the
  Downloads first-poll header, Settings' Reachable lamp, Duplicates'
  Quality at 960, and the carried items).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

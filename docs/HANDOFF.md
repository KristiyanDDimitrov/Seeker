# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S4 close-out (HISTORY §196). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2051 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S1–S3 and S37/S38 (S9 owns it).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** the close-out's run, recorded in the follow-up handoff commit.

## 2. Where we are

**Round 12 S4 is done.** **Next: S5**, the Support page: the new
contact email and "Support the artists" (BRIEF §5; `frontend-design`).
Kris may veto the wording after seeing it on screen, so the HISTORY
entry needs the before and after screenshots.

## 3. Session report (S4)

- `b5cabe2`, §4.1–§4.2: the Dashboard's Status sorts by
  `track_status.PROGRESS_RANK`. Two new tests (the order; a
  progress-only poll keeps it).
- `b5bc773`, §4.3: Downloads by `download_request.PROGRESS_RANK`;
  a test that every `DownloadStatus` has a rank.
- `e59f95a`, §4.4: the sweep's three more columns (Sharing's State
  and Shared, Library's Tags; Cover art made explicit).
- The close-out: HISTORY §196, one fact in `src/seeker/ui/CLAUDE.md`,
  the plan tick, this file.

## 4. Key context

- **A status column sorts closest to done first** through a named
  rank, never its label (the new ui/CLAUDE.md fact). A new state
  needs a rank, or the lookup raises `KeyError` (Dashboard,
  Downloads); `test_every_status_has_a_progress_rank` catches a new
  `DownloadStatus`.
- **The Dashboard's in-place progress path leaves status keys alone,**
  correctly: it runs only when every row's state is unchanged.
- **Sharing's locations table** still rebuilds its per-row "Add to my
  SoulSeek share" button (with a tooltip) on every 20 s backend poll.
  Not fixed (S3's scope was 2 s pollers). **For S15**, or a row of
  its own.
- **For S16: `uv build --wheel` packages whatever is in
  `src/seeker/`,** including a gitignored `_build_info_generated.py`
  left by a local DMG build. `wheel-exclude` already drops
  `CLAUDE.md`.
- **S9 owns:** the two radon-D functions and the two undiagnosed
  tests (the CI flake
  `test_search_download_best_passes_the_already_fetched_results`,
  `37599402903`; the Cocoa-only theme failure, whose first untried
  check is a rerun with only the built-in display).
- **Planning found, for later rows:** the "daily" retry never existed
  (S10). `urllib3 2.7.0` has three advisories, fixed in 2.8.0, and CI
  has no dependency audit (S7).
- **Carried:** set `set -o pipefail` before `pytest … | tail && git
  commit`. Never touch slskd or real data. The full suite takes
  ~4.5 min, so run it in the background, and never stash `src/` while
  it runs. `git stash push -- <paths>` to test HEAD's `src/` with the
  new tests.

## 5. Decisions made

- **Downloads: locked above shortlisted.** The brief grouped them as
  "Retrying (locked, shortlisted)"; distinct ranks keep the two labels
  ("Retrying", "Queued as backup") from interleaving. Superseded is
  ranked last so that every member has one.
- **The sweep went past the brief's two columns** to Sharing's State
  and Shared and Library's Tags/Cover art: the brief said "any other
  status column … treat each one the same way". Page-derived labels
  carry their rank with them (no model enum to sit beside).
- **Ties keep no explicit second key:** within a rank, rows are equal
  and Qt's sort keeps them as they come.
- **No screenshots:** nothing is sorted until a header is clicked.
- **Skills:** `tdd` was used (each change failed first for the stated
  reason). No skill contradicted the brief.

## 6. Blockers

None.

## 7. Files in progress

None: S4 is committed whole.

## 8. Waiting on Kris

**A live check (S4):** on the Dashboard and on Downloads, click the
Status header; the finished rows should come first.

**From S1–S3, still open:** the new colours (HISTORY §193), the spin
arrows and `90.0` (§194), "Follow system" applying at once, and a
Review tooltip staying up for 5 s under a still pointer (§195).

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

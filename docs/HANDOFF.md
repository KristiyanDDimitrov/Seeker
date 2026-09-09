# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `80fb0e3` — "Round 8 §12.10: show the needs-review
  runner-up inline". Working tree clean except this handoff rewrite +
  the session-plan tick, about to be committed.
- **`origin/main`**: was in sync with local HEAD at S15 close-out
  (`6f1ea0b`); this session's 5 commits (`d5cc2f0`..`80fb0e3`) are
  **unpushed. Ask before pushing.**
- **pytest:** `1174 passed, 1 skipped in 94.37s` — the two long-
  standing fullscreen-close flakes (`test_fullscreen_close_policy_
  check_ignores_a_stale_request`, `test_reopening_after_a_fullscreen_
  close_restores_prior_geometry`) each fired at least once across this
  session's several full-suite runs, always in different combinations,
  always passing individually — same pre-existing pattern CLAUDE.md's
  Open issues already tracks, not a new regression.
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done: Phase 0-7 (through S13), S14, S15 (Group A subset), and now
  S16 (Group B, all five items).**
- **Next: nothing scheduled.** §9.4 (long functions beyond
  `MainWindow`'s own decomposition) is the only item left in the brief,
  explicitly optional — fold into a session that finishes early, or
  skip and say so. Round 8 is otherwise complete.

## S16 report (five commits, one per item: `d5cc2f0`, `2ecb748`,
`1c16441`, `ceaf482`, `80fb0e3`)

Kris approved all of §12.6–§12.10 in one go ("execute all of these"),
a deliberate exception to the one-item-per-session pacing this file
normally enforces — five commits, each independently verified.

**§12.6:** TaggingPanel (already its own widget class) moved from being
a Dashboard sub-widget to its own top-level **Library** page (new
`ui/pages/library_page.py`, `LibraryHost`). Dashboard's `DashboardHost`
gained three callables (`on_tag_track_clicked`/`on_retag_track_
clicked`/`on_tag_playlist_clicked`) reaching Library's TaggingPanel for
the track table's own row actions. 8th nav entry — History's shortcut
is now Ctrl+8, not Ctrl+7.

**§12.7:** the old scrolling `tagging_results` QPlainTextEdit replaced
with `TagResultPanel` (new `ui/tag_result_panel.py`) — one-line summary
("Tagged 3 of 4 — 1 failed") + a details list collapsed by default.
Failed tag_tracks items get a real "Retry" button (re-runs
`tag_tracks([track_id])`, same call the row-level Re-tag context menu
makes); fix-art/rename results have no single-track retry endpoint, so
their rows stay read-only.

**§12.8:** segmented All/Missing/Needs review/Untagged filter on the
Dashboard track table (new `[variant="segment"]:checked` QSS,
`_apply_track_filter_and_render` split out of `_render_track_
statuses`). A filter with zero matches gets its own empty state,
distinct from "tracks haven't loaded yet."

**§12.9:** wrote the five-channel rule into CLAUDE.md's Conventions
(activity strip/next_step_notice/InlineNotice/status_label/tray, each
with exactly one job — full investigation in HISTORY §120). Audited
every page against it and found one real bug:
`sharing_page.py`'s add-to-share confirmation was written to
`sharing_status_label`, then immediately wiped by the same handler's
own `_refresh_sharing()` call (`run_worker` clears its target
`status_label` unconditionally at the start of every call) — the
confirmation was never actually readable. Fixed with a new
`sharing_notice` (InlineNotice), same pattern Dashboard/Library
already use.

**§12.10:** the Review page showed a candidate's score but not what it
beat. `quality.py`'s `find_best_needs_review_candidate` now returns
`(file, score, runner_up)` instead of `(file, score)` — runner_up is
the second-best-scoring candidate in the same band, or `None`. New
`runner_up_username`/`runner_up_filename`/`runner_up_score` columns on
`soulseek_review_candidates` (migration via the existing
`_add_column_if_missing` pattern). Review's needs-review table gained
a sortable "Runner-up" column.

**Screenshots:** dashboard-dark/light, library-dark, review all
regenerated and eyeballed in both themes — Library page, the segmented
filter, the results panel with a real failed retry row, and the
Runner-up column all render correctly. `docs/screenshots/generate.py`
updated to produce all of these plus a populated (not just empty-
state) Library screenshot.

## Read discipline — this is why sessions were costing 300-700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief for a phase you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Push this session's 5 unpushed commits to `origin/main` (or say
      go ahead) — local HEAD `80fb0e3`, `origin/main` last confirmed at
      `6f1ea0b`.
- [ ] Click through the new Library page and the Dashboard's status
      filter on a real Mac window — verified via offscreen Qt this
      session, not a live human on a real display.
- [ ] The pre-S16 "waiting on Kris" items (Dock icon reopen, LAN port
      check, window geometry position round-trip) are still open if
      not yet done — see prior handoff history for detail if needed.

## Open questions

- **Is the GitHub repo private?** `github.com/KristiyanDDimitrov/
  Seeker/actions` 404s anonymously — if so, `update_check.py`'s 404-
  means-"no releases" assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
- **Round-8 flakes (five total, in CLAUDE.md's Open Issues)** —
  diagnose any recurrence directly, never `pytest-rerunfailures`. The
  two fullscreen-close ones fired again this session, in different
  combinations across different full-suite runs (S16 never touched
  that code) — consistent with the existing pattern, not a new lead.
- **`docs/HISTORY.md` is ~14,180+ lines** — still never read whole, per
  the standing rule.
- **CLAUDE.md is ~32 KB**, up from S14's ~29 KB target — S16 added one
  real Conventions entry (the five-channel rule). Still well under the
  pre-S1 148 KB, not urgent, but a future session could fold this
  handoff's own "S16 report" section into HISTORY once it's no longer
  the most recent work, per the two-tier docs rule.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

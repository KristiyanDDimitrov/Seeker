# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `b907cfb` — "S11.2: repoint Search/Sharing tests at their
  page widgets, drop delegating properties" (S11.2's own two-commit
  mechanism landed; this session's own tick/handoff commit goes on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1149 passed, 1 skipped on a clean run — identical to
  S10/S11/S11.1's own numbers. One of the two already-tracked
  fullscreen-close flakes failed on 2 of 4 full runs this session
  (different one each time), always passing in isolation immediately
  after — not a regression, see "Known flakes" below.
- **mypy --strict src/:** clean, 99 source files (unchanged count —
  this session only touched tests + main_window.py)
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map:
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the brief is 115 KB, you only need your own session's slice.

- **Done:** Phase 0–4, S1–S10, S11, S11.1 (dialogs + History +
  Help/Support), **S11.2** (Search + Sharing, mirroring S6's own
  extraction order).
- **Next session: S11.3** (Downloads + Tagging panel, mirrors S7). Same
  mechanism, same two-commit split — see "What S11.2 found" below,
  which is now the third confirmation of the same pattern S11.1
  established; S11.3–S11.7 should keep applying it.

## S11.2 — what landed (§9.3.4 test-split: Search, Sharing)

Two commits (`da30f59`, `b907cfb`). 11 tests moved out of
test_ui_smoke.py into `tests/pages/test_search_page.py` (6, plus the
Search-only `_search_column` helper) and `tests/pages/
test_sharing_page.py` (5).

**Nothing new discovered vs. S11.1's own findings (still read those
before S11.3) — this session just re-confirmed all four hold:**

1. Repointed tests address `window._search_page.<attr>` /
   `window._sharing_page.<attr>` directly, not a standalone page
   construction.
2. **Six** structural sweep tests (not five — one more than S11.1's own
   two) referenced Search/Sharing attributes by name and needed
   repointing after the delegating properties were deleted:
   `test_every_table_and_list_widget_is_routed_through_make_card`,
   `test_every_actions_column_table_has_a_derived_floor_for_row_height_
   and_width`, `test_no_table_column_clips_its_own_header_label_when_
   populated`, `test_stretch_columns_reach_the_viewport_edge_with_no_
   dead_band`, `test_every_table_has_a_stretch_column_immediately_
   after_construction`, `test_no_table_ever_hands_a_bare_progress_bar_
   or_button_to_setcellwidget`. **Grep every deleted attribute/method
   name across the WHOLE file before deleting — this keeps costing
   more than it looks like it will.**
3. `_search_column` (Search-only) moved in full with its tests, same as
   any page-only helper. `_make_location`/`_confirm_yes` (shared with
   the sweep tests and Duplicates' own tests) stayed in
   test_ui_smoke.py and were imported into the new file — same
   precedent as `_make_history_event`.
4. Deleting the delegating properties left three now-unused imports in
   main_window.py (`SoulseekFile`, `LocationShareState`, `UploadStatus`)
   — `ruff check` catches these immediately; check for it every time a
   delegate block is deleted, don't rely on remembering.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. This session, one or the other failed on 2 of 4 full runs
(never both at once), always green in isolation run immediately after.
More frequent than S11.1's own "not seen this session" report — worth
someone eventually instrumenting rather than continuing to note as
background noise, but still not a S11.3 blocker.

## Read discipline — this is why sessions were costing 300–700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
in full — `grep -n` the symbol/section, read that range. `uv run
pytest -q`: report only the summary line plus named failures. `git
diff --stat` by default, full diff only for the file under review.
Don't re-read a file you just edited. Don't read a brief for a phase
you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Physically click the Dock icon (both after a normal close and
      after a fullscreen close) and confirm the window returns.
- [ ] Reopen via Spotlight.
- [ ] From a **second device on the same network**, confirm
      `http://<mac-lan-ip>:5030` no longer answers.
- [ ] Push the unpushed commits to `origin/main` (or say go ahead and a
      future session will) — count not re-verified this session, check
      `git status` / `git log origin/main..HEAD` fresh.

## Open questions

- **Is the GitHub repo private?** Anonymous requests to
  `github.com/KristiyanDDimitrov/Seeker/actions` return 404 — if so,
  `update_check.py`'s `/releases/latest` 404-means-"no releases"
  assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
- **Three round-8 flakes already in CLAUDE.md's Open Issues, plus the
  fullscreen-close pair above (now firing more often — see "Known
  flakes")** — diagnose any recurrence directly, never
  `pytest-rerunfailures`.
- **S9's recorded pytest skip count (29) doesn't match S10/S11's
  clean-tree baseline (1)** — unresolved since S10, no regression to
  chase.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `a105372` — "S11.3: repoint Downloads/Tagging-panel tests
  at their page widgets, drop delegating properties" (S11.3's own two-
  commit mechanism landed; this session's own tick/handoff commit goes
  on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1149 passed, 1 skipped on a clean run — identical to
  S10/S11/S11.1/S11.2's own numbers. The tracked fullscreen-close flake
  pair fired once (of three full runs) this session, always passing in
  isolation immediately after — not a regression, see "Known flakes"
  below.
- **mypy --strict src/:** clean, 99 source files (unchanged count —
  this session only touched tests + main_window.py)
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map:
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the brief is 115 KB, you only need your own session's slice.

- **Done:** Phase 0–4, S1–S10, S11, S11.1 (dialogs + History +
  Help/Support), S11.2 (Search + Sharing), **S11.3** (Downloads +
  Tagging panel, mirroring S7's own extraction order).
- **Next session: S11.4** (Dashboard, mirrors S8). Read "What S11.3
  found" below first — it changes what S11.4 walks into.

## S11.3 — what landed (§9.3.4 test-split: Downloads, Tagging panel)

Two commits (`473fb19`, `a105372`). 24 tests moved out of
test_ui_smoke.py: 20 into `tests/pages/test_downloads_page.py` (the
whole contiguous ETA/progress-bar/row-rendering block plus the paged-
render-while-hidden test) and only 4 into `tests/pages/
test_tagging_panel.py` (the FlowLayout/checkbox-width tests).

**New pattern, not seen at S11.1/S11.2, that S11.4+ will hit again:**
TaggingPanel is a sub-widget of Dashboard, not a standalone page — most
of its own candidate tests also drive Dashboard's not-yet-extracted
`track_table`/`playlist_list`/`dashboard_notice`/`_render_track_
statuses`/`_on_retag_track_clicked`/`_render_tag_result` to set up a
selection or assert a notice. Moving those would have broken S11.1/
S11.2's own precedent (a moved page's tests reference ONLY that page's
own attributes — confirmed by grep, zero foreign-page references in
`test_search_page.py`/`test_sharing_page.py`). So ~18 Tagging-adjacent
tests (`test_tag_selected_*`, `test_tag_playlist_*`, `test_force_
retag_*`, `test_bpm_range_*`, `test_fix_missing_art_*`, `test_fill_
missing_art_urls_*`, `test_rename_files_*`, `test_rename_result_
notice_*`, `test_results_panel_*`, `test_retag_context_menu_*`)
**stayed** in test_ui_smoke.py as cross-cutting, repointed only for
their TaggingPanel-attribute reads — the Dashboard half
(`window.track_table` etc.) is untouched. **S11.4 will need to decide
where these ~18 tests ultimately belong** once it deletes Dashboard's
own delegates — its job is not a clean mirror of S5–S10's mechanism.

Other findings, consistent with S11.1/S11.2's own: (1) deleted ALL TEN
TaggingPanel delegating properties, not just the four the moved tests
used — repointing the ~18 cross-cutting tests first left zero bare
`window.<attr>` references to any of them; (2) `_active_downloads_
count` wasn't just a test artifact — MainWindow's own real PageContext
wiring (tray/nav-badge count) also read it, repointed alongside the
deletion — grep for real callers, not just test_ui_smoke.py; (3) three
structural sweep tests plus the nav-badge and tray-status tests touched
deleted Downloads attributes by name, same "grep the whole file first"
lesson, third confirmation; (4) now-unused `ActiveDownload`/
`DownloadEtaTracker`/`QLineEdit`/`QPlainTextEdit`/`FlowLayout` imports
dropped via unrestricted `ruff check --fix` (not narrowed `--select`).

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. This session, one fired on 1 of 3 full runs, always green in
isolation run immediately after. Same background-noise rate as before
S11.2's own higher-frequency report; still not an S11.4 blocker, but
still worth someone eventually instrumenting.

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
  fullscreen-close pair above** — diagnose any recurrence directly,
  never `pytest-rerunfailures`.
- **S9's recorded pytest skip count (29) doesn't match S10/S11's
  clean-tree baseline (1)** — unresolved since S10, no regression to
  chase.
- **S11.4 (Dashboard) scope** — see "S11.3 — what landed" above.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

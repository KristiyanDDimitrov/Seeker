# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `270e9ea` — "9.3.1: Phase 6 — extract Search and Sharing
  pages" (S6 close-out, pending this commit's own tick/handoff commit
  on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** was 15 commits ahead as of S4's handoff, not
  re-checked this session — ask before pushing regardless.
- **pytest:** 1147 passed, 1 skipped, 0 real failures this run (the two
  tracked fullscreen-close flakes fired in the full run, passed 2/2 in
  isolation right after — see "Known flakes")
- **mypy --strict:** clean, 93 source files
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map:
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the brief is 115 KB, you only need your own session's slice.

- **Done:** Phase 0 (baseline), Phase 1 (toolchain, ruff config, CI),
  Phase 3 (security §6.1–§6.6), Phase 3B (§14 Dock icon), S1 (CLAUDE.md
  shrunk), S2 (§7.1), S3 (§7.2 — logging), S4 (§8.1, §8.2 —
  deduplication), S5 (§9.2, §9.3.1 — Phase 6 prep + dialogs +
  History/Help/Support pages), **S6** (§9.3.1 — Search + Sharing
  pages).
- **Next session: S7 — Downloads + Tagging panel** (§9.3.1). Read
  `docs/round8/SESSION-PLAN.md`'s own "Phase 6 — the part that needs the
  most care" section before starting, not just your row — and read the
  "Phase 6 mechanics, refined by S5/S6" section below.
  **Tagging panel is currently inside the Dashboard page's own
  `_build_dashboard_page`/tagging methods (17 methods, per §9.1's
  table) — it hasn't been extracted as a separate page yet, so this is
  the first row that has to pull a group of methods OUT of a page
  that's still otherwise on Dashboard**, not out of MainWindow
  directly. Confirm the method boundary with a grep before assuming
  it's a clean lift.

## S6 — what landed (§9.3.1: Search, Sharing pages)

One commit (`270e9ea`), full detail in the commit message:

- `ui/pages/search_page.py` (`SearchPage`, 9 methods) and
  `ui/pages/sharing_page.py` (`SharingPage`, 10 methods) — moved
  verbatim, same shape as S5's HistoryPage.
- **SharingPage owns its own page-visited/poll-in-progress/ETA-tracker
  state now** — these were plain `MainWindow` instance fields
  (`_sharing_page_visited`, `_sharing_poll_in_progress`,
  `_upload_eta_tracker`) that only ever existed to support the Sharing
  page; moved onto the page itself rather than kept on the shell.
  `MainWindow.backend_poll_timer` now connects directly to
  `self._sharing_page._trigger_sharing_poll`, and `_on_page_changed`
  sets `self._sharing_page._sharing_page_visited` / calls
  `self._sharing_page._refresh_sharing()` — same "reach the private
  method on the page object directly" pattern History's
  `_refresh_history()` call already established.
- Delegating properties for every widget attribute tests touch by name
  (`search_artist_edit`, `search_results_table`,
  `download_best_button`, `sharing_summary_label`,
  `sharing_locations_table`, `sharing_uploads_table`, etc.) **plus
  delegating methods** for private methods called directly on a fresh
  `MainWindow` instance: `_on_search_clicked`, `_render_search_results`,
  `_render_sharing_locations_table`, `_render_sharing_uploads_table`.
  Found these by grepping the test file for `window._` inside each
  page's test block — see the gap S5 already flagged below.
- Visually verified: an offscreen-QPA script (real theme stack, the
  test file's own `FakeApplication`) grabbed both pages in both themes
  and matched the Phase 0.3 baselines structurally. Not committed.

## Phase 6 mechanics, refined by S5/S6 — read before S7

Two real gaps in SESSION-PLAN.md's 5-step mechanism found so far:

1. **`PageContext` needed a fifth field the brief's own sketch didn't
   have: `run_busy_worker`**, bound from `MainWindow._run_busy_worker`.
   `notify` stays OUT — still no real implementation to bind it to.
2. **"Zero test edits" only covers `window.<attr>`-style widget access
   — not a page's private module-level helper patched by dotted path,
   and not a MainWindow method (builder or otherwise) called directly
   on a fresh instance.** Before assuming a page is a clean zero-edit
   move, grep the page's test block for
   `monkeypatch.setattr(main_window_module,` and `window._<method>(`
   calls — S5 found this with `_build_help_page()`/`webbrowser.open`;
   S6 found it again with `_on_search_clicked`, `_render_search_results`,
   `_render_sharing_locations_table`, `_render_sharing_uploads_table` —
   all four needed a delegating **method**, not just a property. Do the
   grep per-page; don't assume the delegating-properties-only shape from
   History generalizes.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. Fired in the full suite again this session (S6), passed 2/2
in isolation immediately after, same as S5. Same pytest-qt teardown /
Qt deferred-deletion cause already documented. Not diagnosed further —
worth real instrumentation if a session has spare budget (see
CLAUDE.md's "history_refresh_button" flake entry for the kind of probe
that would help).

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

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

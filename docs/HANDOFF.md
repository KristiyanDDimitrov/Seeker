# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `67dff93` — "9.3.1: Phase 6 — extract Tagging panel" (S7
  close-out, pending this commit's own tick/handoff commit on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1147 passed, 1 skipped, 0 real failures this run (the two
  tracked fullscreen-close flakes fired in the full run, passed 2/2 in
  isolation right after — see "Known flakes")
- **mypy --strict:** clean, 95 source files
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
  History/Help/Support pages), S6 (§9.3.1 — Search + Sharing pages),
  **S7** (§9.3.1 — Downloads + Tagging panel).
- **Next session: S8 — Dashboard page** (§9.3.1, ~22 methods per §9.1's
  table — the biggest single page moved so far). Read
  `docs/round8/SESSION-PLAN.md`'s own "Phase 6 — the part that needs the
  most care" section before starting, not just your row — and read
  "Phase 6 mechanics, refined by S5/S6/S7" below.
  **The Tagging panel already lives inside Dashboard as a sub-widget**
  (`self._tagging_panel = TaggingPanel(page_context, TaggingPanelHost(...))`,
  built in `_build_dashboard_page` and added to `right`) — that
  construction call, and the `TaggingPanelHost` it binds, moves along
  with Dashboard verbatim; nothing about TaggingPanel itself changes.

## S7 — what landed (§9.3.1: Downloads page, Tagging panel)

Two commits (`916a00f`, `67dff93`), full detail in each commit message.
`ui/pages/downloads_page.py` (`DownloadsPage`) and
`ui/pages/tagging_panel.py` (`TaggingPanel`, a Dashboard *sub-widget*,
not a registered page) moved verbatim, both with temporary delegating
properties/methods on MainWindow for everything test_ui_smoke.py
touches. Full suite green, zero test edits. Visually verified
(offscreen QPA, both themes) — not committed.

## Phase 6 mechanics, refined by S5/S6/S7 — read before S8

1. **`PageContext` grows fields one at a time, as a page moved turns
   out to need one**: `run_busy_worker` (S5), `update_nav_badge`/
   `is_hidden_to_tray` (S7/Downloads), `render_activity_strip`
   (S7/Tagging — a call site that begins a busy action by hand).
   Always bound to the real MainWindow method, never reimplemented.
2. **A sub-widget of a not-yet-migrated page needs a SECOND, narrower
   seam** beyond PageContext — S7 added `TaggingPanelHost` for Tagging
   (inside Dashboard). Expect the same shape for any other sub-widget
   pulled out ahead of its host page.
3. **"Zero test edits" covers three gotchas, not one** — check all
   per page: `window.<attr>` widget access; a MainWindow method/
   module-level helper called or dotted-path-patched on a fresh
   instance (S5/S6); and **a class the test file imports FROM
   main_window.py's own namespace** rather than its real module (S7:
   `RenamePreviewDialog`, kept re-exported with `noqa: F401`) — grep
   the test file's own import block for the name, not just its usage.
4. **A helper shared by the page moving AND a page that hasn't moved
   yet** needs a home both can import without a circular dependency —
   S7 used `theme.py` for `wrap_progress_bar`; judge the right home
   per case, don't default to either `theme.py` or `context.py`.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. Fired in the full suite again this session (S7), passed 2/2
in isolation immediately after, same as every prior session. Same
pytest-qt teardown / Qt deferred-deletion cause already documented. Not
diagnosed further — worth real instrumentation if a session has spare
budget (see CLAUDE.md's "history_refresh_button" flake entry for the
kind of probe that would help).

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

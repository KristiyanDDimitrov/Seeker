# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `8e3665e` — "9.3.1: Phase 6 — extract Dashboard page" (S8
  close-out, pending this commit's own tick/handoff commit on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1120 passed, 29 skipped, 0 real failures this run (one
  tracked fullscreen-close flake fired in the full run, passed 2/2 in
  isolation right after — see "Known flakes")
- **mypy --strict:** clean, 96 source files
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
  S7 (§9.3.1 — Downloads + Tagging panel), **S8** (§9.3.1 — Dashboard
  page, the biggest single page so far).
- **Next session: S9 — Review page** (§9.3.1, ~25 methods per §9.1's
  table — the hardest page per the plan's own ordering rationale).
  Read `docs/round8/SESSION-PLAN.md`'s own "Phase 6 — the part that
  needs the most care" section before starting, not just your row —
  and read "Phase 6 mechanics, refined by S5–S8" below.
  **`_pending_review_focus_track_id` and `_focus_pending_review_row`
  are Review-owned state/logic that already exist on MainWindow
  (unmoved)** — set by Dashboard's `DashboardHost.navigate_to_review`
  seam (a lambda closing over `self._show_page("review",
  focus_track_id=...)`), consumed by `_focus_pending_review_row` once
  Review's own data loads. Both move to `review_page.py` as part of
  this session; the `navigate_to_review` seam on DashboardHost does
  NOT change (it stays bound to `self._show_page`, a real shell
  method, not to anything Review-specific).

## S8 — what landed (§9.3.1: Dashboard page)

One commit (`8e3665e`), full detail in the commit message.
`ui/pages/dashboard_page.py` (`DashboardPage`) moved verbatim,
including the module-level `_NextStepFacts`/`_NextStep`/
`_decide_next_step` (pure "next step" CTA logic) and `_STATE_LABELS`/
`_TRACK_COLUMNS`. TaggingPanel — already its own module since S7 — is
now constructed inside DashboardPage instead of MainWindow; nothing
about TaggingPanel itself changed.

**A new, second seam was needed beyond PageContext: `DashboardHost`**
(dashboard_page.py's own docstring has the full rationale) — for
Sync/Scan/Match/"Load tracks" (shared plumbing, stay on MainWindow) and
for two actions PageContext's one-`str`-argument `navigate` can't carry
(`open_settings(tab)`, `navigate_to_review(track_id)`). Same shape as
S7's `TaggingPanelHost`, just at the MainWindow level instead of
Dashboard-hosting-a-sub-widget.

**A test file other than test_ui_smoke.py imports a private symbol
from main_window's own namespace** — `tests/test_next_step.py` imports
`_decide_next_step`/`_NextStepFacts` directly. Same re-export treatment
as `RenamePreviewDialog` (S7): both kept as `from
seeker.ui.pages.dashboard_page import ... _decide_next_step  # noqa:
F401`. **Checked for S9**: grepped every test file for `from
seeker.ui.main_window import` — only `test_ui_smoke.py` and
`test_next_step.py` import anything beyond bare `MainWindow` (the
`_stress_*`/`test_stress_e2e.py` files only import `MainWindow`
itself, unaffected by any page move).

`selected_playlist` needed a real property **with a setter**, not just
a getter — it's a plain mutable attribute (not a widget), and
test_ui_smoke.py assigns it directly on a fresh MainWindow instance.

Full suite green, zero test edits. Visually verified (offscreen QPA,
both themes) — not committed.

## Phase 6 mechanics, refined by S5–S8 — read before S9

1. **`PageContext` grows fields one at a time, as a page moved turns
   out to need one**: `run_busy_worker` (S5), `update_nav_badge`/
   `is_hidden_to_tray` (S7/Downloads), `render_activity_strip`
   (S7/Tagging). Always bound to the real MainWindow method, never
   reimplemented.
2. **A page that hosts a sub-widget, or that several not-yet-migrated
   MainWindow methods still reach into, needs a SECOND, narrower
   seam** beyond PageContext — S7 added `TaggingPanelHost`, S8 added
   `DashboardHost`. Judge the shape per case: callables for live
   reads/actions, plain widget references only for things that never
   get reassigned.
3. **"Zero test edits" covers at least four gotchas** — check all per
   page: `window.<attr>` widget access; a MainWindow method/module-
   level helper called or dotted-path-patched on a fresh instance;
   a class/function the test file imports FROM main_window.py's own
   namespace rather than its real module (grep the test file's own
   import block for the name, not just its usage) — **and check EVERY
   test file that imports from main_window, not just
   test_ui_smoke.py** (S8: test_next_step.py); and a plain mutable
   attribute (not a widget) that a test assigns directly — needs a
   property **setter**, not just a getter (S8: `selected_playlist`).
4. **A helper shared by the page moving AND a page that hasn't moved
   yet** needs a home both can import without a circular dependency —
   judge the right home per case (S7 used `theme.py` for
   `wrap_progress_bar`).
5. **Not every moved method needs a MainWindow delegating stub** — only
   ones a test calls directly by name on a fresh instance. For the
   rest, redirect their MainWindow call sites straight to
   `self._<page>_page._method()` (S7's `_poll_active_downloads`, S8's
   `_load_playlists`/`_poll_next_step`/`_render_no_playlist_selected`).
   Grep every call site of a moved method before deciding — a method
   called from many still-unmoved shared-plumbing methods (S8's
   `_poll_next_step`, ~5 call sites) is easy to undercount.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. The latter fired in the full suite again this session (S8),
passed 2/2 in isolation immediately after, same as every prior session.
Same pytest-qt teardown / Qt deferred-deletion cause already
documented. Not diagnosed further — worth real instrumentation if a
session has spare budget (see CLAUDE.md's "history_refresh_button"
flake entry for the kind of probe that would help).

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

# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `dfa1437` — "9.3.1: Phase 6 — extract Review page" (S9,
  pending this commit's own tick/handoff commit on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1121 passed, 29 skipped, 0 real failures this run
- **mypy --strict:** clean, 97 source files
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
  S7 (§9.3.1 — Downloads + Tagging panel), S8 (§9.3.1 — Dashboard
  page), **S9** (§9.3.1 — Review page, ~25 methods, the hardest page
  per the plan's own ordering rationale).
- **Next session: S10 — Duplicates page** (§9.3.1, ~21 methods — the
  last of the nine pages). Read `docs/round8/SESSION-PLAN.md`'s own
  "Phase 6 — the part that needs the most care" section before
  starting, not just your row — and read "Phase 6 mechanics, refined
  by S5–S9" below. Duplicates' content-builder is
  `_build_duplicates_content` (grep for it); its methods sit
  contiguously right after where Review's used to be. No known
  Duplicates-specific stranded state has been spotted yet the way
  Review's `_pending_review_focus_track_id` was — but grep for
  `self.duplicates_status_label`/`_duplicates_keep_selection` and every
  method touching them before assuming a clean lift, same as every
  prior page.

## S9 — what landed (§9.3.1: Review page)

One commit (`dfa1437`). `ui/pages/review_page.py` (`ReviewPage`) moved
verbatim — three sections (SoulSeek needs-review candidates, Phase 2
upgrade replacements, local-file needs-review matches) sharing one
poll cycle. Second seam `ReviewHost` covers `status_label` (shared
Dashboard-owned widget, same as TaggingPanelHost), `refresh_track_table`
(`self._dashboard_page._poll_selected_playlist`), and
`check_for_needs_decision_notification` (real MainWindow/tray R7.5
logic, bound through the Host since it also reads
`_tray_icon`/`application.settings`).

`_pending_review_focus_track_id`/`_focus_pending_review_row` moved
here as flagged in the prior handoff — `_show_page` sets/calls them on
`self._review_page` now. `_needs_review_count`/`_pending_upgrades_count`
moved onto the page too, read by the shell via delegating properties
of the same private names (same shape as `_active_downloads_count`).

`_poll_review_items` got **no** MainWindow stub (no test calls it by
name) — every internal call site redirects to
`self._review_page._poll_review_items()` directly, same as S7's
`_poll_active_downloads`. The four `_render_*`/
`_on_bulk_replace_upgrades_finished` methods DO have stubs —
test_ui_smoke.py calls each by name.

Full suite green, zero test edits. Visually verified (offscreen QPA,
both themes) — not committed.

## Phase 6 mechanics, refined by S5–S9 — read before S10

1. **`PageContext` grows fields one at a time, as a page moved turns
   out to need one**: `run_busy_worker` (S5), `update_nav_badge`/
   `is_hidden_to_tray` (S7), `render_activity_strip` (S7).
2. **A page hosting a sub-widget, or reached by several
   not-yet-migrated methods, needs a SECOND, narrower seam** beyond
   PageContext — `TaggingPanelHost` (S7), `DashboardHost` (S8),
   `ReviewHost` (S9). Callables for live reads/shell-owned logic the
   page must trigger but not own; plain widget refs for things never
   reassigned.
3. **"Zero test edits" gotchas to check per page**: `window.<attr>`
   widget access; a method/helper called or dotted-path-patched on a
   fresh instance; a class/function/**type alias** the test file
   imports FROM main_window.py's own namespace rather than its real
   module (S9: `NeedsReviewCandidates`/`PendingUpgrades` re-imported
   back into main_window.py for stub annotations, same shape as
   `_NextStepFacts`); a plain mutable attribute a test assigns
   directly — needs a property setter, not just a getter.
4. **A helper shared by the page moving AND a page that hasn't moved
   yet** needs a home both can import without a circular dependency.
5. **Not every moved method needs a MainWindow delegating stub** — only
   ones a test calls directly by name. For the rest, redirect internal
   call sites straight to `self._<page>_page._method()`. Grep every
   call site before deciding — S9's `_poll_review_items` had 5, all
   redirected, none kept as a stub.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. Neither fired this session (S9); same pytest-qt teardown /
Qt deferred-deletion cause already documented when they do. Not
diagnosed further — worth real instrumentation if a session has spare
budget.

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

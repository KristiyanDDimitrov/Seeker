# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `af9be85` — "9.3.1: Phase 6 — extract Duplicates page" (S10,
  pending this commit's own tick/handoff commit on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1149 passed, 1 skipped, 0 real failures this run — note
  this differs from S9's recorded "1121 passed, 29 skipped"; confirmed
  via `git stash -u` that the CLEAN pre-S10 tree (`45e7ad7`) also
  produces 1149/1 in THIS environment, so the S9 number was
  environment-dependent (unclear which environment), not a regression
  introduced here. Numbers otherwise identical before/after this
  session's change.
- **mypy --strict:** clean, 98 source files
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
  History/Help/Support pages), S6 (Search + Sharing), S7 (Downloads +
  Tagging panel), S8 (Dashboard page), S9 (Review page), **S10**
  (§9.3.1 — Duplicates page, ~23 methods — the last of the nine pages).
- **Next session: S11 — Tray extraction + `MainWindow` close-out**
  (§9.3.2, §9.3.3, §9.3.4). Read `docs/round8/SESSION-PLAN.md`'s own
  "Phase 6 — the part that needs the most care" section before
  starting, and "Phase 6 mechanics, refined by S5–S10" below. §9.3.2
  extracts the ~20 tray/notification methods into `ui/tray.py` —
  **except** `closeEvent`/hide-to-tray verification, which stays on
  `MainWindow` per the brief. §9.3.3 shrinks `__init__` to shell state
  only. §9.3.4 splits `test_ui_smoke.py` to match the new `ui/pages/*`
  layout — this is also where EVERY page's delegating stub/property
  block (S5 through S10, all still marked "deleted at S11, not before")
  finally gets removed, alongside repointing each test file at its page
  widget directly. Expect this to be the largest single session in the
  plan; the brief's own hard-stop condition (§9.3.5) applies in full —
  stop and report if any page can't go green without editing a test.

## S10 — what landed (§9.3.1: Duplicates page)

One commit (`af9be85`). `ui/pages/duplicates_page.py`
(`DuplicatesPage`) moved verbatim — folder/location scoping, fingerprint
computation, group render, single-group delete, and bulk "Resolve all
groups". No Host seam needed (unlike Review/Tagging/Dashboard):
Duplicates owns its own `duplicates_status_label` rather than sharing
the Dashboard's, so every method reaches only `PageContext`
(`application`/`thread_pool`/`run_busy_worker`) plus its own widgets.

The module-level `_DuplicatesColumn`/`_DUPLICATES_COLUMN_HEADERS`/
`_DUPLICATES_COLUMNS`/`KEEP_ALL_DUPLICATES_ID` constants moved with it
(no test imports them from `main_window`, confirmed by grep — unlike
`BulkResolveDuplicatesDialog`, which tests still import from
`seeker.ui.main_window`'s own namespace, so it stays re-exported there
with `# noqa: F401`, same shape as `BulkReplaceUpgradesDialog`/
`RenamePreviewDialog`).

`_on_page_changed` stays on `MainWindow` (shared shell dispatch across
Duplicates/Sharing/History) — its two Duplicates-branch calls now read
`self._duplicates_page._refresh_duplicates_locations()`/
`._refresh_duplicates_milestone()`. One other stray internal call site
found by grep and redirected the same way:
`_invalidate_after_leaving_settings`'s own Settings-exit refresh.

8 methods got MainWindow delegating stubs (called directly by name in
test_ui_smoke.py): `_render_duplicates_milestone`,
`_render_duplicates_locations`, `_selected_duplicates_location`,
`_on_find_duplicates_clicked`, `_on_compute_fingerprints_clicked`,
`_render_duplicate_groups`, `_on_delete_duplicates_clicked`,
`_on_remove_duplicates_folder_clicked` — the last two (compute-
fingerprints and remove-folder) aren't obvious from their names alone;
found only by grepping every `window._on_*`/`window._render_*` call in
the test file, not by pattern-matching on "duplicate" in the name
(`_on_compute_fingerprints_clicked` doesn't contain that substring —
worth remembering for any future page with a similarly-named side
action). Two attributes needed setter properties, not just getters:
`_duplicates_folder_paths` and `_current_duplicates_location_name` (both
directly assigned by tests, not just read).

Full suite green, zero test edits. Visually verified via a throwaway
offscreen-QPA script (both themes) — layout matches the Phase 0
baseline's structure (milestone label, location combo, folder-scope
checkbox, two buttons, status row, 8-column table); not a pixel-exact
diff against the baseline PNGs (different synthetic fixture data), and
not committed.

## Phase 6 mechanics, refined by S5–S10 — read before S11

1. **`PageContext` grows fields one at a time, as a page moved turns
   out to need one**: `run_busy_worker` (S5), `update_nav_badge`/
   `is_hidden_to_tray` (S7), `render_activity_strip` (S7). No new field
   needed for Duplicates (S10) — it's the first page confirmed to need
   nothing beyond the original four-plus-`run_busy_worker` set.
2. **A page hosting a sub-widget, or reached by several
   not-yet-migrated methods, needs a SECOND, narrower seam** beyond
   PageContext — `TaggingPanelHost` (S7), `DashboardHost` (S8),
   `ReviewHost` (S9). Duplicates (S10) needed none — confirm this by
   checking whether the page owns all its own widgets/state before
   assuming a Host is required.
3. **"Zero test edits" gotchas to check per page**: `window.<attr>`
   widget access; a method/helper called or dotted-path-patched on a
   fresh instance; a class/function/type alias the test file imports
   FROM main_window.py's own namespace rather than its real module; a
   plain mutable attribute a test assigns directly — needs a property
   setter, not just a getter (S10: `_duplicates_folder_paths`,
   `_current_duplicates_location_name`). **New for S10:** a shell
   method that stays on MainWindow (`_on_page_changed`) can still call
   INTO the moved page's now-private methods — don't just stub the
   methods tests call directly; grep the whole file for every other
   internal call site too (`_invalidate_after_leaving_settings` was
   found this way, not from the test grep).
4. **A helper shared by the page moving AND a page that hasn't moved
   yet** needs a home both can import without a circular dependency.
5. **Not every moved method needs a MainWindow delegating stub** — only
   ones a test calls directly by name. For the rest, redirect internal
   call sites straight to `self._<page>_page._method()`. Grep every
   call site before deciding, and don't pattern-match the method name
   against the page's own name (see S10's `_on_compute_fingerprints_
   clicked` note above) — grep the exact identifier list a test file
   actually calls on `window`.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. Neither fired this session (S10); same pytest-qt teardown /
Qt deferred-deletion cause already documented when they do.

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
- **S9's recorded pytest skip count (29) doesn't match this session's
  clean-tree baseline (1)** — see "Current state" above. Not
  investigated further this session (no regression to chase, since
  both before/after THIS session's diff agree); worth a real look if a
  future session has spare budget, since it means at least one of the
  two numbers was measured in a materially different environment.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

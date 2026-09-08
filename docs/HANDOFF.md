# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `36ee402` — "S11.5: repoint Review tests at the page
  widget, drop delegating properties" (S11.5's two-commit mechanism
  landed; this session's tick/handoff commit goes on top)
- **Working tree:** clean except this rewrite. `origin/main`: not
  re-checked this session — ask before pushing regardless.
- **pytest:** a clean run is 1149 passed, 1 skipped — identical to
  S10–S11.4's own numbers. The tracked fullscreen-close flake pair
  fired on most runs this session too (same elevated rate S11.2–S11.4
  reported), always green in isolation — see "Known flakes" below.
- **mypy --strict src/:** clean, 99 files. **ruff check src tests: 0
  findings — this must stay at 0.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done:** Phase 0–4, S1–S10, S11, S11.1–S11.4 (test-split, dialogs
  through Dashboard), **S11.5** (Review, mirrors S9).
- **Next: S11.6** (Duplicates, mirrors S10). Read "S11.5 — what
  landed" below first — same mechanism, one new wrinkle to expect.

## S11.5 — what landed (§9.3.4 test-split: Review)

Two commits (`697c06b`, `36ee402`). 17 tests moved verbatim into
`tests/pages/test_review_page.py`. 7 tests stayed cross-cutting in
test_ui_smoke.py (the Dashboard-double-click-navigates-to-Review test,
asserting on `stacked_widget`; the Downloads/Review nav-badge and
tray-menu-counts tests, shell; four structural sweep tests checking
every page's tables/buttons at once) — repointed to
`window._review_page.<attr>` in place, unmoved.

**No non-test internal callers needed repointing beyond the tray
controller's two lambdas** (`needs_review_count`/
`pending_upgrades_count` in `_build_tray_controller()`) — Review was
already fully wired to `self._review_page`/`self._dashboard_page`
everywhere else (construction, `ReviewHost`, poll-timer wiring). A
much smaller blast radius than S11.4's Dashboard session, likely
because Review's own click handlers already lived on `ReviewPage`
itself (no "Shared plumbing" leftovers on MainWindow, unlike
Dashboard's still-there sync/scan/match/download handlers).

**One new wrinkle, worth expecting at S11.6 too:**
`test_every_table_and_list_widget_is_routed_through_make_card` keeps
its own separate `table_and_list_attrs` (`getattr(window, attr)`) list
for pages that still have delegating properties, alongside a
`page_owned_tables` list (`(name, window._page.attr)` tuples) for pages
that don't. Deleting a page's delegating table properties without
moving its entries from the first list to the second is a real gap
this test's own `getattr` silently produces an `AttributeError` for —
caught only by the full suite run, not by grep. Duplicates has entries
in that same `table_and_list_attrs` list (`duplicates_folders_list`,
`duplicates_table` — the latter is Duplicates' own, check before S11.6
assumes the whole list is Review's).

`BulkReplaceUpgradesDialog`'s re-export from `main_window.py` (kept
since S11.1) is now dropped — the same-shaped
`BulkResolveDuplicatesDialog` re-export is what S11.6 will drop.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2, always green in isolation. Fired on most full runs again this
session (consistent with S11.2–S11.4's already-elevated reports).
Someone should instrument this rather than re-reporting it.

## Read discipline — this is why sessions were costing 300–700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't re-read a file you just edited. Don't read a brief for a
phase you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Click the Dock icon after a normal close and after a fullscreen
      close; confirm the window returns. Reopen via Spotlight too.
- [ ] From a second device, confirm `http://<mac-lan-ip>:5030` no
      longer answers.
- [ ] Push the unpushed commits to `origin/main` (or say go ahead) —
      check `git log origin/main..HEAD` fresh, not re-verified now.

## Open questions

- **Is the GitHub repo private?** `github.com/KristiyanDDimitrov/
  Seeker/actions` 404s anonymously — if so, `update_check.py`'s 404-
  means-"no releases" assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
  S9's skip-count mismatch (29 vs. everyone else's 1) — same status.
- **Three round-8 flakes in CLAUDE.md's Open Issues, plus the
  fullscreen-close pair above (firing noticeably more often across
  S11.2–S11.5)** — diagnose any recurrence directly, never
  `pytest-rerunfailures`.
- **S11.6 (Duplicates) scope** — check whether Duplicates' own click
  handlers/bulk-resolve logic are fully inside `duplicates_page.py` or
  partly still on MainWindow before assuming every attribute test
  moves cleanly (same check S11.5's own handoff asked of Review, which
  turned out clean).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

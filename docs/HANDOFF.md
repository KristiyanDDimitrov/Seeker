# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `f286760` — "S11.4: repoint Dashboard tests at the page
  widget, drop delegating properties" (S11.4's two-commit mechanism
  landed; this session's tick/handoff commit goes on top)
- **Working tree:** clean except this rewrite. `origin/main`: not
  re-checked this session — ask before pushing regardless.
- **pytest:** 1149 passed, 1 skipped on a clean run — identical to
  S10–S11.3's own numbers. The tracked fullscreen-close flake pair
  fired on 5 of 7 full runs, always green in isolation — see "Known
  flakes" below.
- **mypy --strict src/:** clean, 99 files. **ruff check src tests: 0
  findings — this must stay at 0.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done:** Phase 0–4, S1–S10, S11, S11.1–S11.3 (test-split, dialogs
  through Downloads/Tagging), **S11.4** (Dashboard, mirrors S8).
- **Next: S11.5** (Review, mirrors S9). Read "S11.4 — what landed"
  below first — two real traps it hit that S11.5 will likely hit too.

## S11.4 — what landed (§9.3.4 test-split: Dashboard)

Two commits (`a08653b`, `f286760`). 52 tests moved verbatim into
`tests/pages/test_dashboard_page.py` (including the ~18 Tagging-
adjacent tests S11.3 left cross-cutting — Dashboard is their real home
since TaggingPanel is its sub-widget), 3 more into `tests/pages/
test_tagging_panel.py` (zero-Dashboard-state tests, including two
RenamePreviewDialog tests leftover from S11.1's own dialogs split).

**27 tests stayed in test_ui_smoke.py as genuinely cross-cutting — NOT
a clean mirror of S5–S10, read before assuming a Dashboard-attribute
test belongs in the page file:** activity-strip/tooltip tests (shell);
the sync/scan/match/download-button click tests (exercise MainWindow's
own **not-yet-extracted** `_on_*_clicked`/`_open_destination_dialog`
orchestration — never moved to `dashboard_page.py` at S8, confirmed by
grep: no delegating stub, real implementation still on MainWindow,
using Dashboard's buttons only as a trigger); backend-poll/Review-tab
tests asserting on `status_label`/`selected_playlist` as a side effect;
double-click-navigates-to-Review tests (assert on `stacked_widget`);
five structural sweep tests. All 27 got their attribute references
repointed to `window._dashboard_page` in place, unmoved.

**Two real traps, confirmed live, worth knowing before S11.5:**

1. **A blanket `self.<attr>` → `self._dashboard_page.<attr>` regex
   broke ~270 tests** (`AttributeError: no attribute '_dashboard_page'`)
   — `_build_tray_controller()` runs **before** `_dashboard_page`
   exists (built later in `_build_ui()`), the same ordering constraint
   a comment right there already documented for its sibling lambdas.
   Fixed by wrapping that one call site in a lambda too — check each
   call site's construction-order position, a full-suite run is what
   actually catches this.
2. **Real (non-test) internal callers of a deleted delegating stub are
   easy to miss** — `_poll_selected_playlist` had 8 beyond its own
   stub; the still-MainWindow-owned click handlers + `_open_
   destination_dialog` read Dashboard's widgets directly at 20 more
   sites. Same lesson S11.3's close-out flagged — grep `self\.<attr>\b`
   across the WHOLE file, not just tests, before deleting a property.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2, always green in isolation. 5 of 7 full runs this session had
one fail — meaningfully higher than S11.2/S11.3's already-elevated
rate. Someone should instrument this rather than re-reporting it.

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
  fullscreen-close pair above (now firing noticeably more often)** —
  diagnose any recurrence directly, never `pytest-rerunfailures`.
- **S11.5 (Review) scope** — check whether Review's own click handlers
  are fully inside `review_page.py` or partly still on MainWindow
  (Shared plumbing, S11.4's own pattern) before assuming every
  attribute test moves cleanly.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `b2ef2fa` — "S11.1: repoint History/Help/Support tests at
  their page widgets, drop delegating properties" (S11.1's own two-
  commit mechanism landed; this session's own tick/handoff commit goes
  on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1149 passed, 1 skipped, 0 real failures — identical to
  S10/S11's own numbers. Confirmed stable across two repeated full runs
  this session.
- **mypy --strict src/:** clean, 99 source files (unchanged count —
  this session only touched tests + main_window.py)
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map:
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the brief is 115 KB, you only need your own session's slice.

- **Done:** Phase 0–4, S1–S10, S11, **S11.1** (§9.3.4 test-split for
  dialogs + History + Help/Support, mirroring S5's own extraction
  order).
- **Next session: S11.2** (Search + Sharing, mirrors S6). Same
  mechanism, same two-commit split — see "What S11.1 found" below
  before starting; it changes what "step 4" actually means in
  practice, which S11.2–S11.7 all still need to apply.

## S11.1 — what landed (§9.3.4 test-split: dialogs, History, Help/Support)

Two commits (`fd228f0`, `b2ef2fa`) — the first time §9.3's own step-4
"repoint + delete delegating members" has actually been exercised (S5–
S11 all stopped after step 3). 24 tests moved out of test_ui_smoke.py
into `tests/pages/test_dialogs.py` (8 — About/Destination only;
RenamePreviewDialog/BulkReplaceUpgradesDialog/
BulkResolveDuplicatesDialog are each constructed by one specific
already-extracted page, not MainWindow, so their tests wait for that
page's own session — S11.3/S11.5/S11.6), `test_history_page.py` (5),
and `test_static_pages.py` (11, Help+Support).

**What "step 4" actually means in practice, found live this session —
read before S11.2–S11.7:**

1. **"Address the page widget directly" = `window._history_page.
   <attr>`, not constructing the page standalone.** Pages are exercised
   through real `MainWindow` navigation (`window._show_page(...)`), and
   some tests assert MainWindow-owned call counts (e.g. the silent
   `_seed_notification_cutoff` fetch) — building `HistoryPage(context)`
   in isolation would lose that. One precedent already existed
   (`window._help_page`) — followed it everywhere.
2. **Cross-page structural sweep tests can silently depend on a
   property you're about to delete.** Two tests that check every page's
   tables at once (not owned by any one page's file) still referenced
   `window.history_table` by name and broke when it was deleted. **Grep
   the attribute name across the WHOLE test file before deleting a
   MainWindow property** — a moved test isn't the only consumer.
3. **No shared fixtures module exists yet.** `FakeApplication` lives in
   test_ui_smoke.py; new page test files import it with a plain
   cross-file `from test_ui_smoke import FakeApplication` — reliable
   because `tests/conftest.py` puts `tests/` on `sys.path` before any
   test file imports, regardless of collection order. Fine at 3 files;
   revisit if it gets unwieldy.
4. Dialogs split into "shell-owned" (About/Destination — test imports
   repointed `main_window` → `seeker.ui.dialogs`, their real module) vs.
   "page-owned" (the other three — left alone, deferred).

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2, not seen this session's two runs but don't assume fixed.

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

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `a95d0f4` — "S11.6: repoint Duplicates tests at the page
  widget, drop delegating properties" (S11.6's two-commit mechanism
  landed; this session's tick/handoff commit goes on top)
- **Working tree:** clean except this rewrite. `origin/main`: not
  re-checked this session — ask before pushing regardless.
- **pytest:** a clean run is 1149 passed, 1 skipped — identical to
  S10–S11.5's own numbers. The tracked fullscreen-close flake pair
  fired on most runs this session too (same elevated rate S11.2–S11.5
  reported, one or the other test failing on a given run), always
  green in isolation — see "Known flakes" below.
- **mypy --strict src/:** clean, 99 files. **ruff check src tests: 0
  findings — this must stay at 0.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done:** Phase 0–4, S1–S10, S11, S11.1–S11.5 (test-split, dialogs
  through Review), **S11.6** (Duplicates, mirrors S10).
- **Next: S11.7** (Tray, mirrors S11's own tray extraction). Read
  "S11.6 — what landed" below first — same mechanism, two known
  gotchas already flagged in SESSION-PLAN.md's own S11-split note.

## S11.6 — what landed (§9.3.4 test-split: Duplicates)

Two commits (`2e399c9`, `a95d0f4`). 44 tests moved verbatim into
`tests/pages/test_duplicates_page.py`. Four tests stayed cross-cutting
in test_ui_smoke.py (the activity-strip progress test, the every-
table/make_card sweep, and two structural sweeps that render a
duplicate group alongside every page's own state) — all four
repointed to `window._duplicates_page.<attr>` in place.

**Real gap, worth expecting at S11.7 too:** building the move list by
grepping test *names* containing "duplicat" missed three cross-cutting
tests that call `window._render_duplicate_groups(...)`/
`compute_fingerprints_button` without "duplicat" in their own name.
Commit 1 (pure move, delegating properties still live) passed clean
regardless — the gap only surfaced when commit 2 deleted the
delegating properties and the full suite broke with `AttributeError`.
**Grep the whole file for the page's own delegating attribute/method
names, not just tests whose name mentions the page**, before treating
the move list as complete.

No non-test internal callers needed repointing (unlike Review's
tray-controller lambdas at S11.5) — `_on_page_changed` already called
`self._duplicates_page`'s own methods directly.
`BulkResolveDuplicatesDialog`'s re-export from `main_window.py` is now
dropped — Tray has no equivalent re-export to worry about at S11.7.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2, always green in isolation. Fired on most full runs again this
session (consistent with S11.2–S11.5's already-elevated reports).
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
  S11.2–S11.6)** — diagnose any recurrence directly, never
  `pytest-rerunfailures`.
- **S11.7 (Tray) scope** — the two gotchas already documented in
  `docs/round8/SESSION-PLAN.md`'s S11-split note (a signal connected
  to a non-`QObject` controller loses Qt's auto-disconnect; a test
  monkeypatching a module-qualified name only intercepts a bare-name
  call resolved in that module's own globals) are real and specific to
  Tray — read them before starting. Also grep the **whole** file for
  Tray's delegating names before declaring the move list complete
  (see S11.6's own gap above).

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

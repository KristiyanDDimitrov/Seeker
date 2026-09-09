# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `c564d13` — "S14 close-out: tick session-plan box". Working
  tree clean.
- **`origin/main`: at `711f87c` ("S14: README §11.3.4 — title case
  fix") — 3 commits behind local HEAD.** A push happened mid-session up
  through `711f87c` (confirmed via `gh run list` — a real triggered CI
  run exists for it); the two commits after it (README reorder +
  screenshots) were never pushed. **Ask before pushing** — don't assume
  the earlier push means blanket permission for the rest.
- **pytest:** `2 failed, 1119 passed, 29 skipped in 86.11s` — both
  failures are already-tracked flakes
  (`test_fullscreen_close_policy_check_ignores_a_stale_request` and,
  new this session, `test_reopening_after_a_fullscreen_close_restores_
  prior_geometry` — see CLAUDE.md Open issues), both pass individually.
  29 skipped is now a fully-explained number, not a mystery — see
  below.
- **`mypy --strict src/`: clean, 99 files. `ruff check src tests`: 0
  findings.**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map: `docs/round8/
SESSION-PLAN.md` — **read that, not the full 115 KB brief.**

- **Done: Phase 0-7 (through S13), and now S14** (CLAUDE.md 8b +
  README — §11.2.4, §11.2.5, §11.3).
- **Next: S15 — UX Group A, only if Kris approves** (§12.1-§12.5).
  Nothing is scheduled without that explicit yes; if it hasn't been
  given, there is no round-8 row left to run and the round is
  effectively done pending that product decision.

## S14 report

**§11.2.4/§11.2.2 (CLAUDE.md):** layout tree regenerated against the
real `src/seeker` tree (`ui/pages/*` folded in, `main_window.py`
6,882 -> 1,842 lines, two new repositories/models, `destination_
resolution.py`). Four conventions §11.2.4 named were missing and are
now in: the comment shelf-life test, logging-over-print in services,
the AST sweep barring `ui/` from `Application`'s private attributes,
page widgets taking a `PageContext`. §11.2.5 (items 63/70 in Open
issues) was already done in S1 — confirmed, nothing to redo.
CLAUDE.md: 25,260 -> 29,448 chars (growth is the conventions this
session was explicitly deferred to add).

**Real finding, not in the plan: CI is running for real, not billing-
blocked.** `gh run list`/`gh run view` show real completed runs;
ruff/mypy clean every time, pytest failing only on the pre-existing
`test_callback_server.py` trio (real evidence now, not just a local
hypothesis — see CLAUDE.md Open issues). This also fully explains the
long-standing "29 vs. 1 skipped" mismatch: 28 `@requires_x9_pro` tests
(no such drive on a GitHub runner) + 1 `@requires_stress_opt_in` test
= 29, exact arithmetic match; real hardware with the drive mounted
sees only 1. Both written into CLAUDE.md's Open issues.

**§11.3 (README):** title fixed (`# seeker` -> `# Seeker`); reordered
to name+description -> badges -> Screenshots -> What it does ->
Architecture (tree regenerated same as CLAUDE.md's) -> Tech stack ->
Quality -> everything else unchanged. Badges are **static** (shields.io
tests/mypy/ruff/python/license badges), not a live GitHub Actions
badge — deliberate: CI is real but currently red on the documented
`test_callback_server.py` timeouts, and a live red badge on the
portfolio front door would misrepresent code quality with an
environment quirk. Screenshots (§11.3.1, the brief's own "highest-
value single change"): `docs/screenshots/generate.py` builds a real
`MainWindow` against `FakeApplication` (same test double `tests/
test_ui_smoke.py` uses) with invented playlists/tracks/a duplicate
group/a review candidate, drives it under `QT_QPA_PLATFORM=offscreen`,
and grabs real widget pixels in both themes — no real playlist names,
paths or usernames, and reproducible by anyone. Committed: `dashboard-
dark.png`, `dashboard-light.png`, `review.png`, `duplicates.png`, plus
the generator script.

**Process note:** a background `fork` first tasked with this screenshot
capture ran ~14 min/246K tokens, produced nothing (`docs/screenshots/`
didn't exist afterward), and returned a confusing final message. It
wasn't spawned with `isolation: "worktree"`. Re-attempted directly and
finished in a handful of iterations by hand. Try `isolation:
"worktree"` first if delegating offscreen-Qt work to a subagent again.

## Read discipline — this is why sessions were costing 300-700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief for a phase you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Click the Dock icon after a normal close and after a fullscreen
      close; confirm the window returns. Reopen via Spotlight too.
- [ ] From a second device, confirm `http://<mac-lan-ip>:5030` no
      longer answers.
- [ ] Push the 2 unpushed commits to `origin/main` (or say go ahead) —
      `origin/main` is currently at `711f87c`, 3 behind local HEAD.
- [ ] Decide S15 (UX Group A, brief §12.1-§12.5) — approve or skip.

## Open questions

- **Is the GitHub repo private?** `github.com/KristiyanDDimitrov/
  Seeker/actions` 404s anonymously — if so, `update_check.py`'s 404-
  means-"no releases" assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
  S9's skip-count mismatch is now RESOLVED (see above) — this one
  remains open.
- **Round-8 flakes now in CLAUDE.md's Open Issues (five total)** —
  diagnose any recurrence directly, never `pytest-rerunfailures`. The
  two fullscreen-close ones fired together again this session (comment/
  docs-only — not a regression from this session's own work); two
  same-area tests failing together only under the full suite is
  stronger evidence of a real ordering/state-leak bug than either
  alone, worth a dedicated diagnosis session if it recurs a third time.
- **`docs/HISTORY.md` is ~14,100+ lines** — still never read whole, per
  the standing rule.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

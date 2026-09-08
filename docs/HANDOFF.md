# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** commit this session ends on (see `git log -1` — S1 close-out)
- **Working tree:** clean
- **`origin/main`:** pushed and up to date as of this session
- **pytest:** 1147 passed, 1 skipped
  (the skip is `tests/test_stress_e2e.py`, opt-in via
  `SEEKER_RUN_STRESS_TEST=1` — real infra, never runs normally)
- **mypy --strict:** clean, 86 source files
- **ruff check src tests:** **0 findings — this must stay at 0**
- **CI:** completed real runs for the first time this session (the
  earlier billing block cleared mid-session). First run: 17 failures.
  Fixed the 14 caused by a missing `chromaprint` system library
  (`brew install chromaprint` added to `ci.yml`) and **confirmed by a
  second real run** — down to exactly 3 failures now, all
  `test_callback_server.py`, `httpx.ConnectTimeout` on the runner only
  (passes locally). Root cause still open — see below.
  [HISTORY §117](HISTORY.md#117)

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. The full plan is
`docs/BRIEF-2026-09-08-refactor.md`; the session-by-session map is
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the full brief is 115 KB and you only need your own session's
slice of it.

- **Done:** Phase 0 (baseline), Phase 1 (toolchain, ruff config, CI),
  Phase 3 (security §6.1–§6.6), Phase 3B (§14 Dock icon), **S1**
  (all of S1.1–S1.6 — CI push/billing-block found, Settings inert-
  credential fix, fresh-install confirmation, §6.1 severity
  re-assessment, CLAUDE.md shrunk 147,842 → 25,260 chars).
- **Next session:** **S2 — Layering: private access (§7.1)**. See
  `docs/round8/SESSION-PLAN.md`.
- **`docs/HANDOFF.md` and `docs/round8/`** were untracked in git for the
  whole of S1 (created but never `git add`ed by an earlier session) —
  fixed this session; both are now committed. If a future session finds
  either untracked again, that's a repeat of the same slip — commit them.

## Read discipline — this is why sessions were costing 300–700 K tokens

Reading whole files is what blows the budget. Measured:

| File | Size | ≈ tokens to read once |
|---|---|---|
| `docs/HISTORY.md` | ~830 KB | **~220 K** |
| `tests/test_ui_smoke.py` | 8,688 lines | **~95 K** |
| `src/seeker/ui/main_window.py` | 6,882 lines | **~78 K** |
| `CLAUDE.md` | ~25 KB | **~7 K** (was ~40 K before S1) |

Rules, in force for every session:

1. **Never read `docs/HISTORY.md` in full.** Ever. `grep -n` it for the
   section you need, then read that line range. One full read exceeds
   an entire session budget.
2. **Never read `main_window.py` or `test_ui_smoke.py` in full.**
   `grep -n` for the symbol, then read a range around it. Together they
   are ~173 K tokens — over budget before a single edit.
3. **`uv run pytest -q`**, and report only the summary line plus any
   named failure. Full verbose output is thousands of wasted tokens per
   run.
4. **`git diff --stat`** by default. Full `git diff` only for the one
   file actually under review.
5. **Do not re-read a file you just edited to confirm the edit.** The
   edit tool errors if it failed.
6. **Do not read a brief for a phase you are not doing.**

## Waiting on Kris — real-world actions Code cannot do

- [ ] Physically click the Dock icon (both after a normal close and
      after a fullscreen close) and confirm the window returns.
- [ ] Reopen via Spotlight.
- [ ] From a **second device on the same network**, confirm
      `http://<mac-lan-ip>:5030` no longer answers.
- [ ] Confirm the fullscreen-close Dock-icon disappearance timing looks
      right (automation cannot reach the close button while fullscreen).

## Open questions

- **Is the GitHub repo private?** Anonymous requests to
  `github.com/KristiyanDDimitrov/Seeker/actions` return 404. If it is
  private, `update_check.py`'s `/releases/latest` call returns 404 for
  every user regardless of releases — and that module's comment reasons
  a 404 safely means "no releases yet" *because the repo constant is
  known-good*, an assumption that only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once): a scripted
  launch left the window behind the terminal until explicitly
  activated. Probably macOS focus-stealing prevention applying to
  scripted launches only, which real Dock clicks are not subject to —
  but unconfirmed, and deliberately not "fixed" speculatively.
- **`test_close_event_falls_back_to_real_close_when_no_tray`** flaked
  once in Phase 1, did not reproduce since, recorded in CLAUDE.md's open
  issues. If it fires again, diagnose it — never reach for
  `pytest-rerunfailures`.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `1d1b934`, not yet pushed. Tree clean (aside from an
  untracked `Claude outputs/` directory that predates this session —
  not part of the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1195
  passed, 29 skipped, 2 failed`.** The 2 failures are the already-
  tracked order-dependent pair
  (`test_reopening_after_a_fullscreen_close_restores_prior_geometry`,
  `test_fullscreen_close_policy_check_ignores_a_stale_request`) — pass
  individually, fail together under the full suite. Scheduled for S5/S6
  this round, not touched here. **29 skipped, not S1's 1** — this
  machine has no X9 Pro drive mounted right now
  (`/Volumes/X9 Pro` doesn't exist); CLAUDE.md's Open issues already
  explains this exact 29-vs-1 split (28 `@requires_x9_pro` tests + 1
  `@requires_stress_opt_in`). Not a regression, just this machine's
  state at the moment.
- **`mypy --strict src/`: clean, 104 files** (scoped to `src/`, not
  `tests/`, per CLAUDE.md's own Commands section).
  **`ruff check src tests`: 0 findings.**
- **Not pushed this session — no CI run to report.**

## Where we are in the plan

**Round 10, S1 and S3 done. S2 is blocked, not skipped — see below.**
Brief: `docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`. **Next: S2, but only once Kris answers
the §1.4 question below — until then, S4 is the next row with no
dependency on it.**

## Why S2 didn't run this session

S2's own brief section says "Only after §1.4" — its branch (missing
size / peer offline / slskd unreachable) is picked by whichever cause
§1.4 found, and that was **not settled** by S1. This session re-checked
fresh, in case anything had changed since S1's own check: `docker ps`
— still zero containers, slskd not running on this machine. `select
count(*) from soulseek_review_candidates` — still 0. `seeker.log` —
still 442 bytes, last entry 2026-09-10, unchanged. Nothing new. Rather
than guess a branch, this session moved to S3, the next row with no
dependency on the answer. **S2 is still fully blocked on Kris
reproducing live** (see Waiting on Kris below) — don't start it on a
guess.

## S3 report — §3.1-§3.2, the stress test's stale widget handles

Full investigation: [HISTORY §127](docs/HISTORY.md#127). Summary:
round 8's page extraction moved every widget the opt-in stress test
touches (`playlist_list`, `sync_button`/`scan_button`/`match_button`,
`status_label`, `download_button`, the duplicates widgets,
`sharing_summary_label`) off `MainWindow` onto
`DashboardPage`/`DuplicatesPage`/`SharingPage` — confirmed live via a
real `AttributeError`, not just trusted from the brief. Fixed with one
`_StressHandles`/`_resolve_handles(main_window)` seam (`tests/
test_stress_e2e.py`) the whole test body now reads through, plus a
new **non-opt-in** guard test,
`test_stress_handles_resolve_against_current_main_window`, that runs
on every push. `_current_duplicate_groups` is a `@property` on
`_StressHandles`, not a captured value — `DuplicatesPage` reassigns it
wholesale on every compute/delete, so capturing it once at resolve
time would have gone stale after the first delete.

**Not run: the real stress test.** This machine has no X9 Pro drive
mounted, no slskd running, and no live Spotify session — left for
Kris, exact command below.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

- **Still open from S1, blocks S2:** click Confirm once on a real
  SoulSeek needs-review candidate (slskd running) and paste back what
  Review's notice says plus the matching `seeker.log` entry — this
  settles §1.4 and unblocks S2's branch.
- **New this session:** run the real stress test,
  `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
  with the X9 Pro mounted and Spotify and slskd up, and paste the
  resource table. This is still the round-9 §1.5b check, and S3's own
  fix means the widget lookups it now uses are real for the first time
  since round 8.
- Carried, unaddressed: click through the Review page's splitter (S8)
  on a real display; the Library context header/picker (round 9 S10)
  on a real display, both themes. No automated screenshot exists for
  either.

## Open questions

- Item 125 (the §2.3 quit hang), the fullscreen-close pair (S4/S5's own
  area), and the CI-only flake pair (history-refresh/replace-button —
  the replace-button half of this pair should be re-examined after
  §1.2, since it now waits on the notice instead of the old vacuous
  assertion) are all unchanged — tracked in CLAUDE.md's Open issues.
- `docs/HISTORY.md` is still growing (now through §127), never read
  whole. No HISTORY entry yet for round 9 §3.2 (S7), §6 (S8), §7.1
  (S9), or §7.2 (S10) — round 10's own S7 row is scheduled to backfill
  these.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round10/SESSION-PLAN.md`.
4. Append your own HISTORY entry before your close-out commit (round
   10 §0.6 — every row this round writes one).
5. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
6. If you pushed: record the CI run id and result here too.

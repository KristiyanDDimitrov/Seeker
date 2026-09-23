# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `ddc1f6e`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1197
  passed, 29 skipped, 0 failed`**, confirmed across 3 consecutive
  full-suite runs this session (no failures, no hangs, ~70s each). The
  round-10 S1 handoff's 2 tracked failures
  (`test_reopening_after_a_fullscreen_close_restores_prior_geometry`,
  `test_fullscreen_close_policy_check_ignores_a_stale_request`) did not
  recur — consistent with that pair being order-dependent, not
  deterministic (still open, S5/S6's own area, untouched here). 29
  skipped is this machine's usual split (no X9 Pro drive mounted; see
  CLAUDE.md's Open issues for the 28+1 explanation).
- **`mypy --strict src/`: clean, 104 files.** **`ruff check src
  tests`: 0 findings.**
- **CI on `ddc1f6e` (this session's push): run `35892529042`,
  `success`.** Clean — CI green is §4's own stated acceptance criterion
  and it's met.

## Where we are in the plan

**Round 10: S1, S3, S4 done. S2 is blocked, not skipped.** Brief:
`docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`. **Next: S5 (fullscreen-close reopen
behavior), no dependency on S2's block.** S2 remains blocked on Kris
per S1/S3's own notes — not re-checked this session, nothing new to
report there.

## S4 report — §4.1-§4.3, the review/history CI race, closed

Full investigation: [HISTORY §128](docs/HISTORY.md#128). Both
`test_review_tab_replace_button_calls_apply_upgrade_decision_with_
delete_flag` (already fixed by S1's §1.2) and
`test_history_refresh_button_refetches` shared one mechanism: a fake
service's call counter increments on the worker thread before
`run_worker`'s triggering button is re-enabled on the main thread — a
test that waits only on the counter and clicks can land on a still-
disabled button (a real Qt no-op, not a product bug).

Confirmed with a deterministic repro (`threading.Event`-based blocking
on `FakeHistoryService.get_recent_events`) rather than trusting the
brief's framing. **Found a real hang while building it**, not in the
brief: blocking by call *number* (following the R7.5 comment's "call #1
is the seed, call #2 is the page fetch") assumes an ordering the
`QThreadPool` doesn't guarantee between the two independent tasks —
when the seed call lands second instead, it's the one that blocks, the
test's assertion fails before ever releasing it, and the leaked
`Event.wait()` hangs the whole process at teardown
(`MainWindow.thread_pool` blocks its own destructor on any in-flight
runnable, HISTORY §125). Fixed by keying the block on the call's
**`limit` value** instead (the seed call and the page's real fetch use
different literal limits, so this is correct regardless of scheduling
order) plus a `try/finally` as a second, independent safety net.

Audited all ~156 `waitUntil` sites in `tests/pages/` and
`test_ui_smoke.py` for the same shape — no other instance found (one
near-miss, `test_force_retag_checkbox_passed_through_all_three_
triggers`, is safe: its two clicked buttons use different
`busy_actions` keys). No `wait_for_workers_idle` conftest helper added
— nothing else needed it.

CLAUDE.md: closed both flakes' Open issues entries (condensed note +
link to HISTORY §128, per the doc rules — "three unconfirmed round-8
test flakes" now, not five).

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

- **Still open from S1, blocks S2:** click Confirm once on a real
  SoulSeek needs-review candidate (slskd running) and paste back what
  Review's notice says plus the matching `seeker.log` entry — this
  settles §1.4 and unblocks S2's branch. Not re-checked this session.
- **Still open from S3:** run the real stress test,
  `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
  with the X9 Pro mounted and Spotify and slskd up, and paste the
  resource table.
- Carried, unaddressed: click through the Review page's splitter (S8)
  on a real display; the Library context header/picker (round 9 S10)
  on a real display, both themes. No automated screenshot exists for
  either.
- **New, from S5's own brief section:** once S5 lands, three real-Mac
  checks (fullscreen close → Dock reopen; resize → close → Dock reopen;
  fullscreen close → quit from menu bar → relaunch) — not reached yet
  this session.

## Open questions

- Item 125 (the §2.3 quit hang) and the fullscreen-close pair (S5/S6's
  own area) are unchanged — tracked in CLAUDE.md's Open issues.
- `docs/HISTORY.md` is still growing (now through §128), never read
  whole. No HISTORY entry yet for round 9 §3.2 (S7), §6 (S8), §7.1
  (S9), or §7.2 (S10) — round 10's own S7 row is scheduled to backfill
  these.
- **From the S3 handoff, not re-checked this session:** a one-occurrence
  CI-only `SETUP ERROR` on
  `test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_
  dialog` (same symptom class as the now-closed history-refresh flake,
  different victim test). Did not recur in this session's own CI run's
  named failures (none — see Current state); watch for a second
  occurrence before adding it to CLAUDE.md's Open issues.

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

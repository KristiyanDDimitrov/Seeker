# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `a820372`, pushed (this handoff's own commit follows it).
  Tree clean aside from the untracked `Claude outputs/` directory that
  predates round 10 — not part of the repo, left alone.
- **Local pytest (offscreen Qt, Darwin 25.6.0): `1204 passed, 29
  skipped, 0 failed` on 10 of 10 consecutive full-suite runs** (1202 +
  S6's two new repro tests). 29 skipped is this machine's usual split
  (no X9 Pro drive; see CLAUDE.md's Open issues).
- **`mypy --strict src/`: clean, 104 files.** **`ruff check src
  tests`: 0 findings.**
- **CI on `a820372`: run `35903072236`, `success`.**

## Where we are in the plan

**Round 10: S1, S3, S4, S5, S6 done. S2 is blocked, not skipped.**
Brief: `docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`. **Next: S7 (HISTORY backfill, round 9
S7–S10 — docs only).** S2 remains blocked on Kris per S1/S3's notes.

## S6 report — §6, the fullscreen-close test pair, closed

Full investigation: [HISTORY §130](docs/HISTORY.md#130). A temporary
trace in both `_set_dock_icon_visible(True)` callers (plus
`MainWindow.__init__`) caught the pair firing twice in 5 full-suite
runs. Both times: **candidate 1, on the test's OWN window** (matching
`init`/`policy` ids) — offscreen Qt delivered a real
`applicationStateChanged(ApplicationActive)` inside `qtbot.wait`
while the window was closed, so the reopen handler ran. Not
`cleanup_before_quit`, not a leftover window.

Fix is tests-only: conftest's autouse
`_ignore_organic_application_state_changes` drops signal-delivered
calls (`sender()` is the QApplication); direct test calls still reach
the handler, so the reopen contract stays tested. Two repro tests
(`test_organic_application_active_cannot_fire_the_dock_policy`,
`..._cannot_reopen_a_closed_window`) emit the real signal during the
wait — both failed on `HEAD` (`[True] == []`; `isHidden()` False),
both pass now; the second one covers S5's geometry sibling. PySide6
gotcha found on the way: a monkeypatched slot needs `functools.wraps`
or `sender()` reads `None`. CLAUDE.md's Open issues entry updated in
place (closed).

**Skills divergence:** the session plan points S6 at
`engineering-advanced-skills`; not loaded — the brief's own trace-then-
repro recipe was specific enough, and it found the caller in 5 runs.

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
- **Still open from S3:** run the real stress test,
  `SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
  with the X9 Pro mounted and Spotify and slskd up, and paste the
  resource table.
- **Still open from S5 (§5's own acceptance test):** script the three real
  paths with System Events (`AXFullScreen` on `window 1` of process
  "Seeker") and `open -a Seeker`: fullscreen close → Dock reopen
  (fills the screen, windowed); windowed resize → close → Dock reopen
  (same size); fullscreen close → quit from the menu bar → relaunch
  (fills the screen, windowed). Paste the raw `size of window 1`
  numbers plus one screenshot each; HISTORY has prior `AXFullScreen`
  recipes (`grep -n "AXFullScreen" docs/HISTORY.md`).
- Carried, unaddressed: click through the Review page's splitter (S8)
  on a real display; the Library context header/picker (round 9 S10)
  on a real display, both themes. No automated screenshot exists for
  either.

## Open questions

- Item 125 (the §2.3 quit hang) is tracked in CLAUDE.md's Open
  issues.
- `docs/HISTORY.md` is still growing (now through §130), never read
  whole. No HISTORY entry yet for round 9 §3.2 (S7), §6 (S8), §7.1
  (S9), or §7.2 (S10) — round 10's own S7 row is scheduled to backfill
  these.
- **From the S3 handoff:** a one-occurrence
  CI-only `SETUP ERROR` on
  `test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_
  dialog` (same symptom class as the now-closed history-refresh flake,
  different victim test). Not seen since: CI green on S5's and S6's
  runs, and 0 local occurrences across S6's 15 full-suite runs. Watch
  for a second occurrence before adding it to CLAUDE.md's Open issues.

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

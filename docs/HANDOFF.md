# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `05f798b`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1202
  passed, 29 skipped, 0 failed`** on 4 of 5 full-suite runs this
  session. The 5th run failed `test_reopening_after_a_fullscreen_
  close_restores_maximized_not_fullscreen` together with `test_
  fullscreen_close_policy_check_ignores_a_stale_request`, both passing
  immediately when re-run alone — this is the SAME pre-existing,
  already-tracked order-dependent pair CLAUDE.md's Open issues
  describes (its 4th recorded recurrence now), not a new defect this
  session introduced. Diagnosing it is S6's own scope, not S5's — see
  that row's split point in the session plan. 29 skipped is this
  machine's usual split (no X9 Pro drive; see CLAUDE.md's Open issues).
- **`mypy --strict src/`: clean, 104 files.** **`ruff check src
  tests`: 0 findings.**
- **CI on `05f798b` (this session's push): run `35897033958`,
  `success`.**

## Where we are in the plan

**Round 10: S1, S3, S4, S5 done. S2 is blocked, not skipped.** Brief:
`docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`. **Next: S6 (the fullscreen-close test
pair — find the real caller, isolate).** S2 remains blocked on Kris
per S1/S3's own notes — not re-checked this session.

## S5 report — §5, reopen after fullscreen/zoomed close, closed

Full investigation: [HISTORY §129](docs/HISTORY.md#129). Implemented
Kris's decision (2026-09-23): a window closed fullscreen or maximized/
zoomed comes back **filling the screen as a normal window**, never
re-entering macOS fullscreen (that transition is round 7's own E1).

`_pre_fullscreen_geometry` replaced by `_reopen_filled: bool`, set in
`closeEvent` (both branches) from `isFullScreen() or isMaximized()`,
captured before state changes. New `MainWindow.show_restored()` owns
"show the window the way it was closed"; `_on_tray_open_seeker` and
`main_ui.py`'s first `window.show()` both call it now. Persisted for
relaunch via `SeekerConfig.window_reopen_filled` (default `False`).
`_restore_window_geometry` strips Qt's own `WindowFullScreen` state
bit whenever it survives `restoreGeometry()` (the fullscreen-close
branch unavoidably still saves a blob carrying it), at both call sites
(`__init__`, `showEvent`'s post-layout re-apply); `showEvent` then
re-asserts `showMaximized()` last so its own re-apply can never
un-maximize a window `show_restored()` just filled. Same expression
fixes Window → Zoom reopening un-zoomed for free.

Offscreen Qt asserts window STATE only, never pixels (round 9 §3.1
follow-up 3). Rewrote the geometry-restore test to the new
`isMaximized()`/`not isFullScreen()` contract; added windowed/zoomed
reopen cases and a real-saved-blob fullscreen-flag test. Every
new/changed test confirmed failing on unmodified `HEAD` first.

**Not done — real-Mac verification is the brief's own stated
acceptance test**, not offscreen Qt. See "Waiting on Kris" below.

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
- **New, from S5 (§5's own acceptance test):** script the three real
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

- Item 125 (the §2.3 quit hang) and the fullscreen-close pair (S6's
  own area — 4th recurrence now, see CLAUDE.md's Open issues and
  [HISTORY §129](docs/HISTORY.md#129)'s own verification section) are
  tracked in CLAUDE.md's Open issues.
- `docs/HISTORY.md` is still growing (now through §129), never read
  whole. No HISTORY entry yet for round 9 §3.2 (S7), §6 (S8), §7.1
  (S9), or §7.2 (S10) — round 10's own S7 row is scheduled to backfill
  these.
- **From the S3 handoff, not re-checked this session:** a one-occurrence
  CI-only `SETUP ERROR` on
  `test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_
  dialog` (same symptom class as the now-closed history-refresh flake,
  different victim test). Did not recur in this session's own CI run's
  named failures (none — CI was green, see Current state); watch for a
  second occurrence before adding it to CLAUDE.md's Open issues.

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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `2e1cd45`, pushed (this handoff's own commit follows it).
  Tree clean aside from the untracked `Claude outputs/` directory that
  predates round 10 — not part of the repo, left alone.
- **Local pytest (offscreen Qt, Darwin 25.6.0): `1204 passed, 29
  skipped, 0 failed`** (one full run; S7 is docs only). 29 skipped is
  this machine's usual split (no X9 Pro drive; see CLAUDE.md's Open
  issues).
- **`mypy --strict src/`: clean, 104 files.** **`ruff check src
  tests`: 0 findings.**
- **CI on `2e1cd45`: run `35906181145`, `success`.**

## Where we are in the plan

**Round 10: S1, S3, S4, S5, S6, S7 done. S2 is blocked, not skipped.**
Brief: `docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`. **Every unblocked row is done.** The
next row is S2, and it only starts after Kris answers the S1 item
below. Without that, the next work is a new round, which Kris
scopes (round 9's §4.2b and §8.1–§8.5 are still [ASK KRIS]).

## S7 report — §7, round 9's HISTORY debt

Docs only. HISTORY §131 (§3.2 login item / `SMAppService`), §132 (§6
Review splitter), §133 (§7.1 `PlaylistSelection` seam), §134 (§7.2
Library header and picker, **with the re-entrant SIGSEGV and its
`QTimer.singleShot(0)` fix**), plus §135 for this row itself. Each
entry came from its feature commit plus the close-out handoff
(`git show <sha>:docs/HANDOFF.md`). Every load-bearing claim was
re-grepped against the current tree and still holds.

CLAUDE.md cross-links added: the re-entrant-rebuild rule (§134) and
restore-on-first-real-show (§132) under Qt; `PlaylistSelection` as the
cross-page selection seam (§133) on the page-widgets convention, whose
`PageContext` field list was also stale (named a `notify` field that
does not exist); the login item's frozen-only gate and live status
(§131) under Packaging.

**Found, not fixed (docs-only row):** no test covers the Review
splitter's persist/restore round-trip or its `cleanup_before_quit`
call (`grep -rn review_splitter tests/` is empty). A small candidate
for the next round.

**Skills:** the session plan names no skill for S7; none used.

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
- Carried from round 9: on a real display, both themes, click through
  the Review splitter (§132) and the Library header and picker (§134);
  on a packaged `.app`, confirm "Start Seeker at login" really
  registers and "start hidden" skips the window (§131). None of these
  has an automated check.

## Open questions

- Item 125 (the §2.3 quit hang) is tracked in CLAUDE.md's Open
  issues.
- `docs/HISTORY.md` now runs through §135, never read whole. Round 9's
  HISTORY debt is closed.
- **From the S3 handoff:** a one-occurrence CI-only `SETUP ERROR` on
  `test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_
  dialog`. Not seen since (CI green on S5 and S6). Watch for a second
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

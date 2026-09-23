# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `fccf411`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1222
  passed, 1 skipped, 2 failed`.** The 2 failures are the already-tracked
  order-dependent pair
  (`test_reopening_after_a_fullscreen_close_restores_prior_geometry`,
  `test_fullscreen_close_policy_check_ignores_a_stale_request`) — pass
  individually, fail together under the full suite. Scheduled for S5/S6
  this round, not touched here.
- **`mypy --strict src/`: clean, 104 files. `ruff check src tests`: 0
  findings.**
- **CI on `fccf411` (this session's push): run `35870225354`,
  `failure`.** ruff/mypy clean on the run log. The one failure is the
  OTHER already-tracked CI-only flake
  (`test_history_refresh_button_refetches`, `pytestqt.exceptions.
  TimeoutError`) — not new, not this session's diff (this session never
  touched `history_page.py`). Scheduled for S4 this round.

## Where we are in the plan

**Round 10, S1 done — start S2 next.** Brief:
`docs/BRIEF-2026-09-23-round10.md`. Session map:
`docs/round10/SESSION-PLAN.md`.

## S1 report — §1.1-§1.4, Review's Confirm button

Full investigation: [HISTORY §126](docs/HISTORY.md#126). Summary:
three independent defects produced one observed symptom (Confirm
"does nothing," cell highlight creeps sideways).

- **§1.1 (fixed):** the moving highlight was real Qt focus traversal —
  a disabled, previously-focused button makes Qt synthesize a Tab
  press. `theme.cell_widget` now sets `NoFocus` on every button it
  wraps (all 15 call sites, not just Review).
- **§1.2 (fixed):** every Review `run_worker` call wrote errors to the
  *Dashboard's* `status_label` — invisible from Review, wiped by
  Dashboard's own 2s poll. Review now has its own `self.notice`
  (`InlineNotice`), same as Library/TaggingPanel. `status_label`
  removed from `ReviewHost` entirely.
- **§1.3 (fixed):** `Worker.run` never logged a traceback on failure —
  confirmed live via `seeker.log` (442 bytes, last entry 2026-09-10,
  unchanged as of this session). Now logs one `logger.warning(...,
  exc_info=True)` per failure, in its own commit (workers.py has the
  deadlock history — kept independently revertable).
- **§1.4 (read-only, NOT settled):** the real `soulseek_review_
  candidates` table is currently **empty** (`select count(*)` → 0) —
  whatever row Kris hit is gone, most likely worked around via Reject.
  `docker ps` also shows slskd is not running on this machine right
  now. Neither read-only check settles which of the three hypotheses
  (missing size / peer offline / slskd unreachable) caused the
  original report. **Asking Kris (see below) to reproduce live now
  that §1.2/§1.3 make a real failure visible and logged** — this was
  the brief's own named fallback for exactly this case.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

- **New this session:** click Confirm once on a real SoulSeek
  needs-review candidate (slskd running) and paste back what Review's
  notice says plus the matching `seeker.log` entry — this settles §1.4
  and unblocks S2's own branch (brief §2 is built on the answer).
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
- `docs/HISTORY.md` is still growing (now through §126), never read
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

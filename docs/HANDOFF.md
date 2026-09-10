# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `664a9a9`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine):** `1183 passed, 1
  skipped` clean once (see below), but the full suite also produced
  `2 failed, 1183 passed, 1 skipped in 102.16s` on a separate run —
  see "Discovered this session" below, not a regression from this
  session's own diff (confirmed via `git stash -u`).
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings.**
- **CI on this session's push (`664a9a9`): run `34461031345`, `2
  failed, 1155 passed, 29 skipped in 201.51s`. ruff/mypy both clean.
  The 2 failures are the SAME two already-tracked S4 flakes**
  (`test_history_refresh_button_refetches`,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`)
  — not new, not caused by this session's diff (S5 touched
  `main_window.py`/`tray.py`/tests only, none of which are in either
  flake's own path). Both are already fully documented in CLAUDE.md's
  Open issues as past their "dedicated diagnosis session" bar; not
  re-litigated here.

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1-S5.**
- **Next: S6** — Window geometry + wizard support page + update-check
  honesty (§3.1, §4.1, §4.2a). Split point: after §3.1.
- Two of round 9's own approval gates are still waiting on Kris
  (unchanged — see `docs/round9/SESSION-PLAN.md`'s "Waiting on Kris"):
  §4.2b (cut a real release / auto-update opt-in) and §3.2
  (`SMAppService` for start-at-login). §4.2a in S6 does NOT need
  either gate — check the brief's own text for what's actually scoped
  there before assuming it's blocked.

## S5 report — §2.3, the quit hang

**Reproduction: not achieved live, and said so rather than closing
this as a one-off**, per the brief's own explicit instruction for this
exact outcome. Judged a full real-GUI repro (real background job, a
real tray-menu click via System Events, watching for an actual hang)
out of this session's budget against three candidate mechanisms the
brief itself ranks by likelihood.

**Instead, mechanically confirmed candidate mechanism 1** (`QThreadPool`
blocking at exit) in isolation: a throwaway probe submitted one 4s
`QRunnable` to a per-instance `QThreadPool` (the same shape
`MainWindow.thread_pool` is) and timed teardown — `quit()` always
returns instantly, but the enclosing scope took +4.011s to actually
finish vs. +0.012s with no task running. This is real, live evidence
of the reported shape (event loop gone, process still alive, blocked
in native code) — not yet confirmed as Kris's specific cause.

**Landed regardless, per the brief's own fallback:**
1. **§2.3.3's latent bug, fixed.** `WA_DeleteOnClose` is now decided in
   exactly one place (`TrayController._build_tray_icon()`, both
   branches explicit) instead of split between it and
   `MainWindow.__init__`.
2. **Instrumentation.** `cleanup_before_quit` now logs the real
   per-window thread pool's active/max count at entry and elapsed time
   at exit — designed so a real recurrence is diagnosable from
   `seeker.log` alone next time, without needing a deliberate repro.
3. Two new tests (`testAttribute` on both tray branches) plus one
   logging test (`caplog`, shape-only assertion — see HISTORY §125 for
   why an exact `active=0` count was tried first and had to be
   loosened: a freshly-built window can have its own real worker still
   running).

**Deliberately not done:** no `waitForDone()` (bare or timed) added
anywhere — the brief warns a bare one is the same hang with a
different stack, and a timed one needs a confirmed live repro to pick
a real value for. Full method/reasoning: HISTORY §125; condensed
facts: CLAUDE.md Standing facts (Qt/threading) and Open issues
(Item 125, still genuinely open).

## Discovered this session, out of S5's own scope

**The fullscreen-close test pair now has its third recurrence** —
`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` failed
together under the full suite (`uv run pytest -q`), confirmed
pre-existing via `git stash -u` (both fail identically on unmodified
`HEAD`, both pass individually / under a narrower `-k` selection every
time — not caused by this session's `WA_DeleteOnClose`/
`cleanup_before_quit` diff). CLAUDE.md's own prior note named "a third
time" as the bar for a dedicated diagnosis session — that bar is now
cleared. Not diagnosed this session (S5 was scoped to §2.3 only); a
good candidate for a future session, though not itself a scheduled row
in `docs/round9/SESSION-PLAN.md` yet.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

Unchanged from `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris"
section — see that file, not here (approval gates on
§4.2b/§3.2/§1.2-fallback/§8.1-§8.5, and the real-desktop checks Code
cannot do). S5 adds one real-desktop item to that list, already
present there: **if the §2.3 hang recurs before a dedicated diagnosis
session, capture it live** — `sample Seeker 10 -f
/tmp/seeker-hang.txt` while it's stuck, plus `seeker.log` around the
same timestamp (now carries the two new `cleanup_before_quit` lines).
That one real capture is worth more than another session of guessing.

## Open questions

- **Item 125 (the §2.3 quit hang) is still open** — mechanism
  confirmed mechanically, Kris's specific case not reproduced. See
  CLAUDE.md Open issues and HISTORY §125 for what a live attempt
  should watch for.
- **The two history-refresh/review-tab-replace flakes from S4 are
  unchanged** — still ready for a dedicated diagnosis session, see
  CLAUDE.md's Open issues. Neither fired this session (this session's
  only CI run was still in progress at handoff time).
- **The fullscreen-close pair now has a real third recurrence** (see
  above) — also ready for a dedicated diagnosis session.
- Carried, unconfirmed: `test_callback_server.py`'s trio and the
  focus-search CI-only flake in CLAUDE.md's Open issues — neither
  fired this session.
- `docs/HISTORY.md` is now ~890 KB — still never read whole.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.

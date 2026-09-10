# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `e7c8d57`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine):** `1146 passed, 29
  skipped in 59.36s` — clean, no flakes fired this run.
- **Real CI (`gh run view 34450316595`, the push of this session's
  three commits): ruff/mypy clean, pytest `1146 passed, 29 skipped,
  158.49s`.** Fully green — the one remaining failure from the prior
  push (`test_view_menu_focus_search_navigates_and_focuses_the_search_field`,
  S1's handoff) is now fixed and confirmed on real CI.
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings** (both local and on CI).

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1** (§1.1, §1.2 — see prior HISTORY/handoff, superseded by
  this file). **Done: S2** (§1.3 the focus-search flake, §1.4 the
  history-refresh flake instrumentation, §1.5a the skip-count doc
  entry), three commits: `706f00c` (§1.3), `9ff840b` (§1.5a),
  `e7c8d57` (§1.4).
- **Next: S3** — Table sorting correctness (§5.1, §5.2, §5.3).

## S2 report

**§1.3.** `hasFocus()` requires the window to be the active window,
which never happens under the offscreen QPA platform CI runs under —
that's why this test failed on CI twice while passing locally every
time. Changed the one live assertion
(`tests/test_ui_smoke.py`) to `window.focusWidget() is
<field>` instead. Grepped for the same pattern elsewhere: one other
hit, a comment in `test_wizard.py` explaining why an assertion was
deliberately omitted there (not a live `hasFocus()` call) — left as
is, still accurate.

**§1.5a.** Added a "Why one test always skips" entry to CLAUDE.md's
Standing facts → Testing (new subsection), citing HISTORY §32 (the
real item that documents `test_stress_e2e.py`'s opt-in gate, not §116
as the brief's own text suggested — verified by grepping HISTORY for
the actual heading before citing it). No behavior change.

**§1.4 — time-boxed, and the interesting part of this session.**
Added `ui/workers.py::debug_snapshot()` plus a `_task_started_at`
tracking dict, wired into `test_history_refresh_button_refetches`'s
own timeout handler. Ran a 12-run full-suite loop (~60s/run); run 7
caught a real recurrence — but the instrumentation itself had a bug:
`except TimeoutError` never fired because `pytestqt.exceptions.
TimeoutError` does not inherit from the builtin one (confirmed via its
MRO). Fixed to catch pytestqt's own type by name, then **verified the
fix works** via a deliberately forced timeout (temporarily changed the
awaited call count to an unreachable value, ran with `-s`, confirmed
the snapshot printed, confirmed it also survives pytest's normal
capture-and-report path without `-s`, then reverted the temporary
change). Did not chase a second natural recurrence within the
time-box — full account in HISTORY §121. CLAUDE.md's existing Open
issues bullet for this flake is updated to point at the new
instrumentation and HISTORY §121, not removed (still open: no *real*
diagnostic snapshot exists yet, only a verified-working probe).

**Skills used:** `engineering-advanced-skills` was the row's assigned
bundle; no single skill in that bundle names "flake diagnosis"
directly (checked the full list) — followed the brief's own
instrumentation instructions directly, same divergence pattern S1
already noted for pre-diagnosed items.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

Unchanged from `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris"
section — see that file, not here, for the current list (approval
gates on §4.2b/§3.2/§1.2-fallback/§8.1-§8.5, and the real-desktop
checks Code cannot do). Nothing in S2 added a new one.

## Open questions

- **`test_history_refresh_button_refetches` is still an open flake** —
  the instrumentation added this session is verified working but has
  not yet captured a *real* natural recurrence's snapshot (the one
  real recurrence this session hit predated the instrumentation fix).
  Next session that sees it fire should read the printed snapshot and
  diagnose from there — see HISTORY §121.
- **CLAUDE.md's Open issues still lists the `test_callback_server.py`
  trio as open** (carried from S1's handoff, still not actioned —
  low priority, not urgent enough to justify its own session).
- **`docs/HISTORY.md` is now ~844 KB** (grew this session) — still
  never read whole, per the standing rule.
- Carried, unconfirmed: the remaining round-8 test flakes in
  CLAUDE.md's Open issues (fullscreen-close pattern) — none fired in
  this session's ~13 total full-suite runs (12-run loop + 1 final
  check), consistent with their known low/unpredictable rate, not
  evidence they're gone.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.

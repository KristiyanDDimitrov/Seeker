# Seeker — session handoff

**This file is the entry point for every new Claude Code session on this
project. Read it first. Overwrite it last.**

Keep it under ~120 lines. It is a baton, not a log — `docs/HISTORY.md`
is the log.

---

## Current state

- **HEAD:** `9e29e82` — "9.3.2/9.3.3: Phase 6 — extract tray/
  notifications into ui/tray.py" (S11, pending this commit's own
  tick/handoff commit on top)
- **Working tree:** clean except this rewrite
- **`origin/main`:** not re-checked this session — ask before pushing
  regardless.
- **pytest:** 1149 passed, 1 skipped, 0 real failures this run —
  identical to S10's own numbers. Confirmed stable across four
  repeated full runs this session (needed — see "Two real bugs"
  below); the only non-deterministic failures seen were the two
  already-documented flakes below, never anything new.
- **mypy --strict src/:** clean, 99 source files (was 98 — `ui/tray.py`
  is new)
- **ruff check src tests:** **0 findings — this must stay at 0**

## Where we are in the plan

Round 8 is a nine-phase refactor/security/docs pass. Full plan:
`docs/BRIEF-2026-09-08-refactor.md`. Session map:
`docs/round8/SESSION-PLAN.md`. **Read the session plan, not the full
brief** — the brief is 115 KB, you only need your own session's slice.

- **Done:** Phase 0–4, S1–S10, **S11** (§9.3.2 tray extraction to
  `ui/tray.py`, §9.3.3 `__init__` shrink via a new
  `_build_tray_controller()` builder).
- **S11's own §9.3.4 (test-file split) did NOT land this session** —
  found mid-session to be comparable in size to the entire S5–S10 arc
  (307 tests, ~121 delegating properties/stubs still on `MainWindow`:
  73 properties + 48 stub methods). SESSION-PLAN.md now splits it into
  **S11.1–S11.7**, one per already-extracted page/group, same order
  S5–S10 used (dialogs+History+Help/Support, Search+Sharing,
  Downloads+Tagging, Dashboard, Review, Duplicates, Tray). **Next
  session: S11.1.** Read SESSION-PLAN.md's own new "S11 split" note
  first — it names two real, confirmed-live gotchas any future page's
  stub removal could hit again (see below), plus the concrete first
  step (grep the page's own delegating identifiers in
  `test_ui_smoke.py`, apply §9.3's step-4 mechanism: move verbatim,
  confirm green, THEN a separate commit repointing + deleting stubs —
  step 4 has never actually been exercised yet; S5–S11 all stopped
  after step 3).

## S11 — what landed (§9.3.2 tray extraction, §9.3.3 init shrink)

One commit (`9e29e82`). `ui/tray.py`'s `TrayController` (+ `TrayHost`
seam, same Host-dataclass shape as `DashboardHost`/`ReviewHost`/
`TaggingPanelHost`) now owns the ~20-method tray/notification group.
`closeEvent` and the hide-to-tray verification (`_confirm_hidden_to_
tray`/`_is_exposed_at_platform_level`/`_check_hidden_to_tray`/
`_hide_request_id`, plus the dock-icon-policy-after-fullscreen-close
pair) stayed on `MainWindow` per §9.3.2's own exception — round 7's
E1, genuinely subtle, about the window rather than the tray.
`__init__`'s tray state (`_tray_icon`, `_last_notified_*`) moved to
`TrayController`; the verbose `TrayHost` construction moved into a new
`_build_tray_controller()` builder, matching `_build_ui()`'s own shape.

**Two real bugs found and fixed, both confirmed live — relevant to
EVERY future page's stub removal, not just Tray's:**

1. A signal (`applicationStateChanged`) connected directly to a bound
   method of `TrayController` (a plain Python object, not a
   `QObject`) loses Qt's automatic disconnect-on-receiver-destruction
   — a real, reproduced `RuntimeError: libshiboken: ... already
   deleted` on later delivery, non-deterministic, order-dependent.
   Fix: connect through a `QObject` (page/MainWindow) method instead.
2. `test_reopen_restores_the_dock_icon_before_showing` monkeypatches
   `main_window_module._set_dock_icon_visible` — only intercepts a
   bare-name call resolved in THAT module's own globals. Moving the
   call site to `tray.py` broke it deterministically. Fix: a
   `TrayHost.set_dock_icon_visible` callable bound to a `MainWindow`
   method, so the bare-name call still executes in `main_window.py`'s
   namespace.

Zero test edits this session — S11.1–S11.7 are where they're
authorized (step 4). The `_resolve_tray_icon_path` re-export (same
shape as `BulkReplaceUpgradesDialog` before it) stays until S11.7.

## Known flakes — not regressions, reproduce on a clean tree

`test_reopening_after_a_fullscreen_close_restores_prior_geometry` and
`test_fullscreen_close_policy_check_ignores_a_stale_request` — tracked
since S2. Both fired at least once across this session's repeated
runs; same pytest-qt teardown / Qt deferred-deletion cause already
documented.

## Read discipline — this is why sessions were costing 300–700 K tokens

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
in full — `grep -n` the symbol/section, read that range. `uv run
pytest -q`: report only the summary line plus named failures. `git
diff --stat` by default, full diff only for the file under review.
Don't re-read a file you just edited. Don't read a brief for a phase
you aren't doing.

## Waiting on Kris — real-world actions Code cannot do

- [ ] Physically click the Dock icon (both after a normal close and
      after a fullscreen close) and confirm the window returns.
- [ ] Reopen via Spotlight.
- [ ] From a **second device on the same network**, confirm
      `http://<mac-lan-ip>:5030` no longer answers.
- [ ] Push the unpushed commits to `origin/main` (or say go ahead and a
      future session will) — count not re-verified this session, check
      `git status` / `git log origin/main..HEAD` fresh.

## Open questions

- **Is the GitHub repo private?** Anonymous requests to
  `github.com/KristiyanDDimitrov/Seeker/actions` return 404 — if so,
  `update_check.py`'s `/releases/latest` 404-means-"no releases"
  assumption only holds once the repo is public.
- **`open -a Seeker` focus artifact** (§14, observed once, unconfirmed).
- **Three round-8 flakes already in CLAUDE.md's Open Issues, plus the
  fullscreen-close pair above** — diagnose any recurrence directly,
  never `pytest-rerunfailures`.
- **S9's recorded pytest skip count (29) doesn't match S10/S11's
  clean-tree baseline (1)** — unresolved since S10, no regression to
  chase.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round8/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.

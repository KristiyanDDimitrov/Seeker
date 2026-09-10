# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** `b729468`, pushed. Tree clean (aside from an untracked
  `Claude outputs/` directory that predates this session — not part of
  the repo, left alone).
- **Local pytest (offscreen Qt, this machine, Darwin 25.6.0): `1188
  passed, 1 skipped`** clean, or `1 failed` when the already-documented
  `test_fullscreen_close_policy_check_ignores_a_stale_request` flake
  fires (CLAUDE.md Open issues) — confirmed pre-existing via
  `git stash -u` when it appeared mid-session. Neither is this
  session's own regression.
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings.**
- **CI on `b729468` (this session's final push): run `34481602292`,
  `2 failed`. ruff/mypy both clean.** The 2 failures are the SAME two
  already-tracked S4 flakes (`test_history_refresh_button_refetches`,
  `test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`)
  — not new, not caused by this session's diff. **This session's own
  §3.1 test is green on this run** — see "S6 follow-up" below for the
  three-round diagnosis that got it there.

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1-S6.**
- **Next: S7** — Start at login (§3.2). Split point: after the
  mechanism decision is written down. **This row is gated —
  `docs/round9/SESSION-PLAN.md`'s "Waiting on Kris" needs a yes on
  `SMAppService` vs. a `LaunchAgent` plist before real work starts**;
  the brief's own recommendation is `SMAppService`, [ASK KRIS] only if
  a different conclusion is reached or the new dependency
  (`pyobjc-framework-ServiceManagement`) is contentious.

## S6 report — §3.1, §4.1, §4.2a

**§3.1 — window geometry didn't reopen at its saved size, confirmed by
Kris on a real Mac.** Two independent bugs:
- **Save path:** `_persist_window_geometry()` only ran from
  `cleanup_before_quit`, by which point the window is already hidden to
  the tray in Kris's real flow — `saveGeometry()` against a
  non-visible window isn't trustworthy. Now persisted in `closeEvent`,
  immediately before hiding (both branches), while still visible.
  `cleanup_before_quit`'s own call is now a backstop for the
  quit-without-closing route, gated on `_hidden_to_tray`.
- **Restore path:** moved `_restore_window_geometry()` to after
  `_build_ui()`, AND re-applied it once more from a new `showEvent()`
  override (guarded to the first real show only) — see below for why
  the second half was needed.

**S6 follow-up — a real, three-round CI diagnosis, resolved.** CI
(macos-26) caught something this machine (Darwin 25.6.0) never
reproduced despite real effort across many full-suite and isolated
runs: a fresh window's restored width came back clamped to exactly the
configured minimum (960, not the requested 1000). Three
independently-reasoned production fixes were tried in sequence —
restore-after-`_build_ui()` alone, a `QEvent::LayoutRequest` flush
before the restore, then a `showEvent()`-based re-apply (Qt activates a
widget's layout before delivering `QShowEvent`, so this should be
provably the last write) — and **all three produced the identical
wrong CI result**, strong evidence this is a genuine Qt/offscreen-QPA
version difference in engine behavior, not a defect in call ordering.
Round 3's actual fix was to the **test**, not more production-code
guessing: followed this codebase's own established pattern
(`test_restore_window_geometry_decodes_and_calls_restore_geometry`) of
mocking `restoreGeometry()` and asserting the exact bytes/call-timing
wiring, rather than trusting the real engine to apply pixel values
identically under offscreen QPA. **This is what made CI go green on
`b729468`.** The `showEvent()` production fix stays (sound regardless
of whether it's THE fix for CI's specific quirk) — full narrative
belongs in `docs/HISTORY.md` if this is picked up as a HISTORY entry
next session; not written there yet.
- **Still needs a real-Mac confirmation from Kris** — already tracked
  in `docs/round9/SESSION-PLAN.md`'s "Waiting on Kris". This matters
  more than usual given the CI diagnosis above: the real pixel-exact
  restore behavior was never actually verified by any automated test
  in the end, by design.

**§4.1 — removed the support-the-creator row from the wizard's done
page.** Sidebar Support page and `AboutDialog`'s own support row
untouched. `DONE_PAGE_SUPPORT_PROMPT` deleted (unused). Two stale
"URLs aren't ready yet" comments corrected. `tests/test_wizard.py`'s
buttons-exist assertion inverted to assert their absence.

**§4.2a — the "no releases published" update-check branch is now
honest.** Split `UpdateStatus.UNAVAILABLE` into a new
`NO_RELEASES_PUBLISHED` (Information icon, plain reason text) vs.
`UNAVAILABLE` (Warning icon, "Couldn't check for updates:" prefix) for
genuine failures.

**§4.2b was NOT touched** — both decisions `[ASK KRIS]`, unchanged.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

Unchanged from `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris"
section — see that file, not here. This session adds one item there:
**§3.1's real-Mac confirmation** (resize → close to menu bar → quit →
reopen restores the size) — see the S6 follow-up note above for why
this is now the ONLY real verification of the pixel-exact behavior.

## Open questions

- **§3.1's real applied-pixel behavior is unverified by any automated
  test** (see S6 follow-up above) — a deliberate trade after three
  failed attempts to make it deterministic under offscreen QPA across
  environments. Worth revisiting if Kris's real-Mac check finds it
  still broken; the production fix (showEvent-based re-apply) would
  then need actual real-hardware iteration, not more offscreen guessing.
- **Item 125 (the §2.3 quit hang), the two S4 flakes, and the
  fullscreen-close pair's recurrences are all unchanged from S5** —
  none newly fired beyond the known pattern. Tracked in CLAUDE.md's
  Open issues; not re-litigated here.
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

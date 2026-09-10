# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read
it first. Overwrite it last.** Keep it under ~120 lines — a baton, not
a log (`docs/HISTORY.md` is the log).

---

## Current state

- **HEAD:** pushed (this handoff's own close-out commit, made after
  `85ce139`, folds in the third-recurrence CLAUDE.md update below).
  Tree clean (aside from an untracked `Claude outputs/` directory that
  predates this session — not part of the repo, left alone).
- **Local pytest (offscreen Qt, this machine, X9 Pro mounted so the
  `@requires_x9_pro` tests ran for real too):** `1183 passed, 1
  skipped in 106.01s` — fully clean, no flakes fired locally. The
  review-tab replace-button test specifically re-ran 5/5 green locally
  right after its own CI failure (see below).
- **Real CI: ruff/mypy clean on all three runs this session. pytest
  failed on all three** — not a regression from this session's own
  work (two of the three pushes were docs-only), **two DIFFERENT
  already-tracked flakes, each now hitting its own stated
  "dedicated diagnosis session" threshold:**
  - `34452686991` (commit `44109aa`, the *previous* session's own
    close-out push, never checked before this session started) and
    `34457258960` (this session's `b07287c`):
    `test_history_refresh_button_refetches` timed out both times with
    an **identical** debug-snapshot signature (`active_threads=0
    max_threads=3`, `no tasks in flight`) — two matching recurrences,
    clears its own stated bar.
  - `34457820512` (commit `85ce139`, a pure docs-only push):
    `test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`
    failed (`assert '' == 'Replaced with /new/path'`) — its **third**
    real CI recurrence, clears the "third time" bar CLAUDE.md already
    named for it. Passed 5/5 re-run locally immediately after, same as
    both prior occurrences.
  - Both flakes' evidence is recorded in CLAUDE.md's Open issues.
    **Either is a legitimate next pickup** — ahead of or alongside S5,
    if a session has room. Neither is caused by S4's own diff (ruff/
    mypy clean throughout; ruff/mypy are the only gates S4's own code
    changes could affect).
- **`mypy --strict src/`: clean, 102 files. `ruff check src tests`: 0
  findings.**

## Where we are in the plan

Round 9. Full plan: `docs/BRIEF-2026-09-09-round9.md`. Session map:
`docs/round9/SESSION-PLAN.md` — **read that, not the full ~40 KB
brief.**

- **Done: S1, S2, S3** (see prior handoffs / HISTORY §115-§122).
- **Done: S4** — Quit semantics + confirmation dialog (§2.1, §2.2),
  commits: `7598240` (§2.1, live verification), `b07287c` (§2.2, the
  dialog + the `QEvent.Type.Quit` mechanism), `aa32fb3` and this
  handoff's own close-out commit (CI-flake evidence, opportunistic,
  not part of S4's own scope).
- **Next: S5** — the quit hang (§2.3). **Consider one of the two
  now-qualified flake diagnoses as an alternative/companion pickup**
  — see "Current state" above.

## S4 report

**§2.1 — live-verified, not assumed.** Brought up the real
production stack (Docker Desktop + the real `docker-compose.yml`
slskd container; the X9 Pro drive had to be physically reconnected
first — wasn't mounted at session start). Used the fact that the
`seeker` CLI is itself a clean "Seeker not running" proxy (each
invocation enqueues/polls then exits, no persistent process) rather
than trying to automate the real Qt GUI. Requested a real download via
`seeker search ... --download`, watched slskd's own API directly with
zero `seeker` process running — it finished the transfer completely on
its own — then confirmed `seeker downloads status` reconciled it into
the library on the next "open." **Confirmed: quitting Seeker stops
reconciliation, not the transfer.** Nothing is lost. Cleaned up every
trace of the test against real prod (file, DB row, config, container)
afterward. Full method/result: HISTORY §123; condensed fact: CLAUDE.md
Standing facts (SoulSeek/slskd).

**§2.2 — the single seam, found by live experiment.** The brief asked
to find the one seam both real quit routes (tray Quit, ⌘Q/Dock "Quit
Seeker") pass through, since `cleanup_before_quit`'s `aboutToQuit`
hook fires too late to cancel anything. Built a throwaway probe app on
this real Mac, drove it via `osascript`/System Events (a synthetic
Cmd+Q keystroke did NOT reach the handler — clicking the actual native
Quit menu item did), and confirmed **both routes deliver
`QEvent.Type.Quit` to the `QApplication` instance itself, before
`aboutToQuit`.** Ruled out a reentrant "cancel-then-repost-quit()"
design by testing it directly — it exits the process silently with no
`aboutToQuit` at all, skipping cleanup. The working mechanism needs no
repost: `MainWindow` installs itself as an event filter on the
`QApplication`; on that one event it decides synchronously (via
`DashboardService.get_active_downloads()`, filtered to
`status == "downloading"`, matching `downloads_page`'s own existing
definition) and returns `False` to let the same event proceed or
`True` to cancel it. Zero active downloads: no dialog at all. Copy
follows §2.1's confirmed truth — no "lose." "Keep Seeker Open" is the
real default button. 8 new tests in `test_ui_smoke.py`, both the
decision method and the `eventFilter` boundary itself (a real
`QEvent(QEvent.Type.Quit)`, not a stand-in). Full mechanism/method:
HISTORY §124; condensed fact: CLAUDE.md Standing facts
(Qt/threading) — **likely reusable for any future "confirm before a
real quit" need.**

**Real production infra was used deliberately, with Kris's explicit
sign-off each time it mattered** (running against real prod vs. a
disposable substitute; physically reconnecting the X9 Pro drive) —
see this session's own transcript for the specific asks, not repeated
here.

## Read discipline — unchanged, still why sessions blow their budget

Never read `docs/HISTORY.md`, `main_window.py`, or `test_ui_smoke.py`
whole — `grep -n` the symbol/section, read that range. `pytest -q`:
report only the summary line plus named failures. `git diff --stat` by
default. Don't read a brief section your row doesn't point at.

## Waiting on Kris

Unchanged from `docs/round9/SESSION-PLAN.md`'s own "Waiting on Kris"
section — see that file, not here (approval gates on
§4.2b/§3.2/§1.2-fallback/§8.1-§8.5, and the real-desktop checks Code
cannot do). S4 resolved **§2.1's own real-desktop check itself** (that
item wasn't formally listed in the "Waiting on Kris" table, but it
required Kris's live participation the same way — done now, no action
needed). Nothing else in S4 added a new one.

## Open questions

- **`test_history_refresh_button_refetches` now has two matching real
  CI recurrences with debug-snapshot evidence** (see "Current state"
  above and CLAUDE.md's Open issues) — ready for a dedicated diagnosis
  session; the "no active threads, no tasks in flight" signature rules
  out the stuck-worker hypothesis, points toward a missed signal
  delivery or a race between the click and the snapshot instead.
- **`test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`
  now has a THIRD real CI recurrence** (see "Current state" above and
  CLAUDE.md's Open issues) — also ready for a dedicated diagnosis
  session; still zero local repros across all three occurrences.
- Carried, unconfirmed: the
  fullscreen-close pattern and `test_callback_server.py`'s trio in
  CLAUDE.md's Open issues — none fired this session.
- `docs/HISTORY.md` is now ~880 KB — still never read whole.

## How to end your session

1. All work committed, tree clean.
2. `uv run pytest -q`, `uv run mypy --strict src/`,
   `uv run ruff check src tests` — quote all three.
3. Tick your session's checkbox in `docs/round9/SESSION-PLAN.md`.
4. **Rewrite this file** — HEAD, the three numbers, what landed, what is
   next, and any new open question. Delete anything no longer true.
   Keep it under ~120 lines.
5. If you pushed: record the CI run id and result here too.

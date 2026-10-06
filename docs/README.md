# Seeker documentation

Every document in the repository, then where to start.

## Living documents

- [`../README.md`](../README.md) — what Seeker does, install, every CLI
  command and GUI screen.
- [`../CLAUDE.md`](../CLAUDE.md) — architecture, conventions, standing
  facts and gotchas, open issues. Present tense only.
- [`HANDOFF.md`](HANDOFF.md) — the baton between Claude Code sessions:
  state, next row, blockers. Overwritten every session.
- [`history/`](history/README.md) — the full investigation log,
  numbered `§N`, split by range; its README indexes every entry.
  `grep -n` for the section, never read a whole file.
  `HISTORY.md` is a stub pointing there.
- [`screenshots/`](screenshots/) — the README's images, written by
  `uv run python tools/screenshots.py --readme`.
- [`../tools/screenshots.py`](../tools/screenshots.py) — renders every
  screen and wizard step, both themes, at 1280×820 and 960×640, over
  one invented dataset: `uv run python tools/screenshots.py` (into the
  gitignored `tools/.screens/`; `--page NAME` and `--theme` narrow it).
  Review a UI change against these before committing it.

## Round archive (`rounds/`)

Each round's brief is the task text a session executed; a session plan
is its budgeted row-by-row map.

- [`round-01`](rounds/round-01/BRIEF.md) — six user-reported bugs, four
  of them previously closed unfixed.
- [`round-02`](rounds/round-02/BRIEF.md) — what manual testing found
  after round 1; corrects a misdiagnosed root cause.
- [`round-03`](rounds/round-03/BRIEF.md) — AIFF support, bulk actions,
  table chrome, background tray mode.
- [`round-04`](rounds/round-04/BRIEF.md) — eleven items diagnosed
  against the real library.
- [`round-05`](rounds/round-05/BRIEF.md) — round-4 regressions, a
  palette feature, a refactor;
  [`TASKS.md`](rounds/round-05/TASKS.md) is its working ledger.
- [`round-06`](rounds/round-06/BRIEF.md) — five defects, three from round 5.
- [`round-07`](rounds/round-07/BRIEF.md) — four defects on a current build.
- [`round-08`](rounds/round-08/BRIEF.md) — the codebase-wide refactor
  and `MainWindow` decomposition;
  [security brief](rounds/round-08/SECURITY-BRIEF.md),
  [session plan](rounds/round-08/SESSION-PLAN.md).
- [`round-09`](rounds/round-09/BRIEF.md) — CI, quit safety, window
  lifecycle; [session plan](rounds/round-09/SESSION-PLAN.md).
- [`round-10`](rounds/round-10/BRIEF.md) — Review Confirm, fullscreen
  reopen, stress test, CI races;
  [session plan](rounds/round-10/SESSION-PLAN.md).
- [`round-11`](rounds/round-11/BRIEF.md) — the final polish round and
  v0.1.0 release; [audit](rounds/round-11/AUDIT.md) (findings `A-NN`),
  [session plan](rounds/round-11/SESSION-PLAN.md).

## Reading orders

- **A Claude Code session:** `HANDOFF.md` → your row in the current
  round's `SESSION-PLAN.md` → that brief's §0 plus your row's § →
  `../CLAUDE.md`. Nothing else until the task needs it.
- **A new contributor:** `../README.md` → `../CLAUDE.md` (Architecture,
  Conventions) → the current round's `AUDIT.md` for known weak spots →
  `history/` entries as `CLAUDE.md` links them.
- **A portfolio reviewer:** `../README.md` → `../CLAUDE.md` → the
  round-11 `AUDIT.md` (an honest whole-repo audit) → any one round's
  brief next to its `history/` entries, to see diagnosis turn into
  a fix.

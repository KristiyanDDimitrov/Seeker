# Phase 01 — from first build to v0.1.0

**Rounds 01–12, closed 2026-10-14 with the v0.1.0 release** (HISTORY
§245). Phase 01 built Seeker for one platform, macOS 15 or later on
Apple silicon: sync, scan, match, search and download through slskd,
tagging, duplicates, the GUI, the security audits and the release
process. What it left open is in `../../CLAUDE.md` → Open issues and
in `../HANDOFF.md` → Waiting on Kris. Phase 02 (`../phase-02/`) takes
the same app to Intel Macs and Windows.

Each round's brief is the task text a session executed; a session plan
is its budgeted row-by-row map. These documents are archived: they
keep the paths that were true when they were written, including
`docs/rounds/…`, which `../rounds/README.md` resolves.

- [`round-01`](round-01/BRIEF.md) — six user-reported bugs, four of
  them previously closed unfixed.
- [`round-02`](round-02/BRIEF.md) — what manual testing found after
  round 1; corrects a misdiagnosed root cause.
- [`round-03`](round-03/BRIEF.md) — AIFF support, bulk actions, table
  chrome, background tray mode.
- [`round-04`](round-04/BRIEF.md) — eleven items diagnosed against the
  real library.
- [`round-05`](round-05/BRIEF.md) — round-4 regressions, a palette
  feature, a refactor; [`TASKS.md`](round-05/TASKS.md) is its working
  ledger.
- [`round-06`](round-06/BRIEF.md) — five defects, three from round 5.
- [`round-07`](round-07/BRIEF.md) — four defects on a current build.
- [`round-08`](round-08/BRIEF.md) — the codebase-wide refactor and
  `MainWindow` decomposition;
  [security brief](round-08/SECURITY-BRIEF.md),
  [session plan](round-08/SESSION-PLAN.md).
- [`round-09`](round-09/BRIEF.md) — CI, quit safety, window lifecycle;
  [session plan](round-09/SESSION-PLAN.md).
- [`round-10`](round-10/BRIEF.md) — Review Confirm, fullscreen reopen,
  stress test, CI races; [session plan](round-10/SESSION-PLAN.md).
- [`round-11`](round-11/BRIEF.md) — the final polish round and v0.1.0
  release; [audit](round-11/AUDIT.md) (findings `A-NN`),
  [session plan](round-11/SESSION-PLAN.md), whose "Session protocol"
  and "The handoff contract" every later round still follows. Stopped
  after S38; its release rows carried to round 12, which closed it.
- [`round-12`](round-12/BRIEF.md) — Kris's pre-release walkthrough, a
  security re-audit, the daily sweep, Retry/Cancel and leftover
  cleanup, then the v0.1.0 release (published 2026-10-14);
  [session plan](round-12/SESSION-PLAN.md),
  [security audit](round-12/AUDIT.md) (findings `S-NN`),
  [acceptance checklist](round-12/ACCEPTANCE.md).

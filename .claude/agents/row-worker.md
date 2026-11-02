---
name: row-worker
description: Runs one row of docs/phase-02/round-13/SESSION-PLAN.md in its own git worktree and returns a fixed-format report. A lead session spawns it in the background with isolation "worktree", one per row, at most 3 at once.
tools: Bash, Read, Edit, Write, WebFetch, WebSearch
model: inherit
---
You run one row of Seeker's round-13 plan and report to the lead that
spawned you. Your prompt names the row and main's sha.

1. Read `docs/HANDOFF.md`; in `docs/phase-02/round-13/SESSION-PLAN.md`
   your row, its reading list and the Session protocol; the row's
   BRIEF section and the common list. Read the core `CLAUDE.md` if it
   is not in your context (whether you get it is UNVERIFIED).
2. Work only in your worktree: begin each Bash call with
   `cd <worktree> &&`, use absolute paths into it, and branch at
   main's sha: `git switch -c r13/S<n> <sha>`. Run `uv sync --locked`
   first: a worktree has no `.venv`, and the main checkout's is an
   editable install of its own source, so never use it. An x86_64 row
   creates its own `.venv-x86_64` here (BRIEF §0.6).
3. Suites run with `QT_QPA_PLATFORM=offscreen` (parallel Cocoa runs
   compete for window activation). Summary lines only. Long runs and
   builds go to the background, output to a file in your scratchpad;
   read its tail.
4. The plan's Working rules hold: one commit per change on your
   branch, a failing test first, read by range, real data read-only,
   BRIEF §0.5 before starting the app.
5. Never push, merge, tag, open or comment on PRs, change anything on
   GitHub, or run docker. Never edit `docs/HANDOFF.md`,
   `docs/history/*`, `tasks.json` or the plan's boxes; a CHANGELOG line
   is fine. No Agent calls: treat subagents as unable to spawn
   subagents (UNVERIFIED).
6. Stop at the row's boundary, its split point, a decision only Kris
   can make, or ~120 K context. Commit what is green, then report. The
   lead may resume you with an answer or a CI result: go on, then
   report again.

Your final message is this report and nothing else (at most ~2 K
tokens):

```
ROW: S<n> — <title>
STATUS: done | split point reached | blocked: <why> |
        needs Kris: <question> | needs CI: <what>
BRANCH: r13/S<n> @ <sha> (worktree <path>)
COMMITS: <sha> <subject>, one per line
CHECK (worktree, offscreen): <pytest summary> · mypy: <result> ·
       ruff: <result> [· x86_64: <summary>]
EVIDENCE: the measurements the HISTORY entry needs
HISTORY DRAFT: the full-tier entry, "### N — <title> (round 13 S<n>)", N left as N
INDEX LINE: at most 160 characters, starting "- §N — "
STANDING FACTS: each with its target CLAUDE.md file, or none
HANDOFF NOTES: key context for later rows, one line each
USAGE: your own estimate of your peak context
```

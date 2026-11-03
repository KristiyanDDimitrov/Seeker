# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 2 K tokens: a baton, not
a log. The log is `docs/history/` (short tier: `docs/history/README.md`,
grep it, never read it whole). **The plan is
`docs/phase-02/autodev/SESSION-PLAN.md`** (an `autonomous-development`
run), with status in `tasks.json` beside it, changed only through
`autodev.py`. Every document: `docs/README.md`.

---

## 1. Current state

- **Released: v0.1.1** (2026-10-26, §247).
- **HEAD is the autodev plan commit on `d3403de`.** Tree clean. Kris's
  libchromaprint is built (`.chromaprint/lib`, 1.6.2). `origin` still has
  `r13/S7`, `r13/S7c` (row GH-1 deletes them).
- **The three numbers (Cocoa, before H1):** pytest `2574 passed, 1
  skipped`; mypy `--strict src/` clean, 149 files; ruff 0. H1 records the
  offscreen baseline that replaces it.
- **CI:** `41607225022` on `e397410` green (`check`, `check-intel`,
  `audit`). The 6th/7th Intel runs: §265; read the latest by full SHA.

## 2. Where we are

Phase 02's rest is one autodev plan (2026-11-03): round 13's release
(re-cut: tag first, both images built from the tag, then Kris's
checklist; the old `826608b` candidate in `dist/` is superseded), round
14 whole (S13 skipped, S10 option a), round 15's re-plan, plus H1
(headless tests) and H2 (one wait bound). Kris's decisions: the plan's
first section.

## 3. Next steps

1. Kris starts the lead in a fresh terminal at the repo root:
   `~/.claude/skills/autonomous-development/scripts/launch.sh docs/phase-02/autodev/tasks.json`
2. The lead's first wave: GH-1 (lead), workers H1, R13-S10a, R14-S1.

## 4. Key context

- A fresh worker on an existing branch: `git checkout -B r13/S<n> main`.
  Workers' suites run offscreen; the lead's Cocoa check runs alone.
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.
  zsh does not word-split an unquoted `$var` (a pytest file list failed so).
- S10: un-gate the README (`From 0.2.0`, `Download (from 0.2.0)`,
  `Until 0.2.0 is published…`), resolve nothing else pending
  (`grep -rn S7-PENDING docs` is empty).

## 5. Decisions made

- Kris (2026-11-02): the Intel bundle ships libchromaprint (`f19ad82`);
  arm64 stays on Homebrew's.
- The lead, for Kris's review: libchromaprint is built from a pinned source
  (`build_chromaprint.sh`, one revert undoes it); `SEEKER_CHROMAPRINT_DIR`
  and `.chromaprint/`; the ffmpeg-free Intel runner skips 2 more tests (§262).
- The lead (S4c): the 355 short `waitUntil`s (346 at 2000 ms) were not
  audited or raised, and `--durations` was added instead (§265).

- Kris (2026-11-03): the autodev plan's eight decisions (H2's wait bound,
  R14-S10 option a, offscreen always, "LGPL-2.1-or-later", S13 skipped).

## 6. Blockers

None.

## 7. Files in progress

None. `dist/` and `.chromaprint/` hold gitignored build outputs.

## 8. Waiting on Kris

The plan's "Waiting on Kris": the §9 checklist after R13-S9b, the
publish approval, the post-release checks, round 15's machine.
- FYI: six Settings tests POSTed a login to the real slskd on
  127.0.0.1:5030 until S4b (§264); fixed, effect on slskd unknown.

## 9. Open questions

- Without ffmpeg a non-audio file reads `error`, with it
  `decode_unsupported` (pinned as documented, §262): which is right?
- PyInstaller's Intel-only libomp SDK warning (§262); where numba's cache
  lives; Module map lacks `ui/row_actions.py`, `soulseek/sweep.py`,
  `soulseek/leftovers.py` (older than round 13).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

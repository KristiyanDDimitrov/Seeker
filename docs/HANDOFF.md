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

- **Released: v0.1.1** (2026-10-26, §247). **Main says 0.2.0**
  (R13-S10a, §266): version, lock, CHANGELOG `[0.2.0] - 2026-11-03`,
  README → License "LGPL-2.1-or-later". Not tagged.
- **HEAD is R13-S10a's close-out.** Kris's libchromaprint is built
  (`.chromaprint/lib`, 1.6.2); an x86_64 one is also in `/usr/local/lib`
  (dated 2026-11-03 10:41), so a Rosetta run here runs the 25
  real-chromaprint tests (root `CLAUDE.md` → Platforms).
- **The three numbers on main (offscreen, before H1):** pytest `2575
  passed, 1 skipped` (x86_64 the same); mypy `--strict src/` clean, 149
  files; ruff 0. H1 changes the baseline (Kris: `2568 passed, 29
  skipped`, the X9 Pro tests opt-in).
- **CI:** read the latest run by full SHA (`gh run list --commit`).

## 2. Where we are

Phase 02's rest is one autodev plan (2026-11-03): round 13's release
(tag first, both images built from the tag, then Kris's checklist; the
old `826608b` candidate in `dist/` is superseded), round 14 whole (S13
skipped, S10 option a), round 15's re-plan, plus H1 (headless tests)
and H2 (one wait bound). Done: GH-1, R13-S10a. In flight: H1, R14-S1
(`python3 ~/.claude/skills/autonomous-development/scripts/autodev.py
status`).

## 3. Next steps

1. Integrate H1 and R14-S1 when reviewed; then H2 (after H1).
2. R13-S9 tags v0.2.0 once R13-S10a and H2 are in and CI is green.
   **Re-date CHANGELOG's `[0.2.0] - 2026-11-03` first if the tag lands
   on a later day** (RELEASING: "today's date").
3. R13-S9b builds both images from the tag and replaces the release
   notes' placeholders `SHA256_ARM64_PLACEHOLDER` and
   `SHA256_INTEL_PLACEHOLDER` with the `shasum -a 256` lines.

## 4. Key context

- **Release notes draft:** `.git/autodev/release/v0.2.0/notes.md`,
  outside the tree; never commit it. R13-S10 publishes from it.
- R13-S10b: README → Install needs a note that an M4A or AAC file needs
  ffmpeg for Duplicates in either app (libsndfile 1.2.2 opens neither;
  `packaging/CLAUDE.md`, §266); and un-gate the README's three 0.2.0
  gates (`From 0.2.0`, `Download (from 0.2.0)`, `Until 0.2.0 is
  published…`).
- `packaging/seeker.iss` still says MyAppVersion "0.1.0": PF-36, owned
  by R14-S11.
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.

## 5. Decisions made

- Kris (2026-11-03): the autodev plan's eight decisions (H2's wait bound,
  R14-S10 option a, offscreen always, "LGPL-2.1-or-later", S13 skipped);
  Dependabot #5/#7/#8 wait for DEP-1 after v0.2.0; H1 keeps the X9 Pro
  tests opt-in behind `SEEKER_RUN_X9_PRO_TESTS=1`.
- The lead: root `CLAUDE.md` → Platforms qualified: the real-chromaprint
  tests skip under Rosetta only without an x86_64 libchromaprint (§266).
- "LGPL-2.1-or-later" was read in the pinned 1.6.2 tarball itself
  (FFmpeg's resample2.c is compiled in; KissFFT is not; §266).

## 6. Blockers

None.

## 7. Files in progress

H1 and R14-S1 in their worktrees under `.claude/worktrees/`. `dist/` and
`.chromaprint/` hold gitignored build outputs.

## 8. Waiting on Kris

The plan's "Waiting on Kris": the §9 checklist after R13-S9b, the
publish approval, the post-release checks, round 15's machine.
- FYI: six Settings tests POSTed a login to the real slskd on
  127.0.0.1:5030 until S4b (§264); fixed, effect on slskd unknown.

## 9. Open questions

- Without ffmpeg a non-audio file reads `error`, with it
  `decode_unsupported` (pinned as documented, §262): which is right?
- A Rosetta run on this Mac no longer covers a missing libchromaprint
  (`SEEKER_REQUIRE_CHROMAPRINT=1` covers only the reverse): does any
  run still need to?
- PyInstaller's Intel-only libomp SDK warning (§262); where numba's cache
  lives; Module map lacks `ui/row_actions.py`, `soulseek/sweep.py`,
  `soulseek/leftovers.py` (older than round 13).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

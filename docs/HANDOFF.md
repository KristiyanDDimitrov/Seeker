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
  README → License "LGPL-2.1-or-later". Not tagged. CHANGELOG's
  `[Unreleased]` now holds R14-S1's two CI bullets; they are not 0.2.0's.
- **HEAD is R14-S1's close-out (§268):** CI gains a non-blocking
  `check-windows` (`windows-2025`, offscreen, `continue-on-error: true`)
  and, in `check`, `mypy --strict --platform win32 src/` (gating). The
  first full Windows run (41647752561): "41 failed, 2470 passed, 57
  skipped, 1 error"; its 42 failures are numbered by cause in §268, and
  every later round-14 row cites the numbers it closes. Before it, H1
  (§267): tests offscreen by default, desktop openers refused.
- **The three numbers on main (a bare run, offscreen, X9 Pro opt-in
  unset):** pytest `2602 passed, 29 skipped`; mypy `--strict src/` and `--strict
  --platform win32 src/` clean, 149 files; ruff 0. Before R14-S1:
  `2596 passed, 29 skipped`. No `src/` change, so no x86_64 run.
- **CI:** read the latest run by full SHA (`gh run list --commit`).

## 2. Where we are

Phase 02's rest is one autodev plan (2026-11-03): round 13's release,
round 14 whole (S13 skipped, S10 option a), round 15's re-plan, plus
H1 and H2. Done: GH-1, R13-S10a, H1, R14-S1. In flight: H2 (reviewing,
on `p02/H2`). Status: `python3
~/.claude/skills/autonomous-development/scripts/autodev.py status`.

## 3. Next steps

1. Integrate H2 when its review passes (based on fb27807; rebase onto
   R14-S1's close-out).
2. R13-S9 tags v0.2.0 once H2 is in and CI is green. **Re-date
   CHANGELOG's `[0.2.0] - 2026-11-03` first if the tag lands on a later
   day** (RELEASING: "today's date"). R14-S1's bullets stay in
   `[Unreleased]`.
3. R13-S9b builds both images from the tag and replaces the release
   notes' placeholders `SHA256_ARM64_PLACEHOLDER` and
   `SHA256_INTEL_PLACEHOLDER` with the `shasum -a 256` lines.
4. R14-S2 after R13-S10: it now also owns isolating platformdirs in
   tests (round-14 BRIEF §2 step 5; plan → Round 14 rows; its
   `lead_note`).

## 4. Key context

- **Platformdirs on Windows (guards real data):** a test's `HOME` moves
  neither `expanduser()` nor, from platformdirs' source, Seeker's
  data/log/cache folders (`WIN_PD_OVERRIDE_LOCAL_APPDATA`, else the
  known-folder API). Until R14-S2's conftest fixture lands,
  `test_lazy_spotify_config`'s `Application()` subprocesses would open a
  Windows machine's real `%LOCALAPPDATA%\Seeker`; round 15's BRIEF
  §0.3 runs no suite there before it is on main (R15-S0 checks).
- R14-S1's list, for its rows: PATH split on `:` (entries 5–8, S4);
  no drive hint off `/Volumes` (11–12, S9); a case-only rename read as
  `already_correct` (13, `library/metadata_service.py:1065`, not in
  AUDIT.md: S9, else S12); PySide6's Windows
  `LicenseRef-Qt-Commercial.txt` (38–42, `bundle_info.py:179`, S11);
  entry 28 (`os.geteuid`) hides 14 tests, and the row that fixes it
  reports what they do on Windows. A pipe's code page: S3 settles it in
  CI under PF-11. Typing `tests/` for `win32` is a proposal only.
- Round 14's BRIEF grew 8 lines in §2; the plan's ranges are updated.
- **Release notes draft:** `.git/autodev/release/v0.2.0/notes.md`,
  outside the tree; never commit it.
- R13-S10b: README → Install needs the M4A/AAC-needs-ffmpeg note and
  the three 0.2.0 gates un-gated (§266). `packaging/seeker.iss` still
  says "0.1.0": PF-36, R14-S11.
- H1's notes: R14-S2's stem compare should cover conftest's
  `_opens_on_the_desktop` (cmd.exe, OPEN.EXE); a new link scheme joins
  `_URL_SCHEMES`.
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.

## 5. Decisions made

- Kris (2026-11-03): the autodev plan's eight decisions; Dependabot
  #5/#7/#8 wait for DEP-1 after v0.2.0; X9 Pro tests opt-in
  (`SEEKER_RUN_X9_PRO_TESTS=1`).
- The integrator: R14-S1's CHANGELOG bullets went to a fresh
  `[Unreleased]` above `[0.2.0]` (0.2.0 is untagged and R14 is not in
  it).

## 6. Blockers

None.

## 7. Files in progress

H2 in its worktree under `.claude/worktrees/`. Merged branches and
worktrees left for Kris to remove: `p02/H1`
(`agent-a12ba60fe9f01f418`), `p02/R14-S1`
(`agent-a2f629926c967ad19`); origin's `p02/R14-S1` holds the
pre-rebase commits the two CI runs built. `dist/` and `.chromaprint/`
hold gitignored build outputs.

## 8. Waiting on Kris

- The X9 Pro opt-in path has not been run since H1 gated it (§267).
- The plan's "Waiting on Kris": the §9 checklist after R13-S9b, the
  publish approval, the post-release checks, round 15's machine.
- FYI: six Settings tests POSTed a login to the real slskd on
  127.0.0.1:5030 until S4b (§264); fixed, effect on slskd unknown.

## 9. Open questions

- Without ffmpeg a non-audio file reads `error`, with it
  `decode_unsupported` (§262): which is right?
- H1 review nit (§267): with `BROWSER` set to an unregistered program,
  webbrowser spawns it unrefused; fix in conftest or narrow
  `tests/test_headless.py:131-133`'s docstring.
- R14-S1 left open (§268): the causes of entries 31–33 (Qt and fonts)
  and test_connection's 16 s on Windows.
- A Rosetta run here finds the x86_64 libchromaprint in
  `/usr/local/lib`, so it no longer covers a missing one: does any run
  still need to?
- PyInstaller's Intel-only libomp SDK warning (§262); Module map lacks
  `ui/row_actions.py`, `soulseek/sweep.py`, `soulseek/leftovers.py`.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

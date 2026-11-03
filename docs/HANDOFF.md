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
  (R13-S10a, §266): version, lock, CHANGELOG `[0.2.0] - 2026-11-04`,
  README → License "LGPL-2.1-or-later". Not tagged. CHANGELOG's
  `[Unreleased]` holds R14-S1's two CI bullets; they are not 0.2.0's.
  H2 added none (test-only).
- **HEAD is H2's close-out (§269):** every ceiling wait in `tests/`
  (pytest-qt's waits, `waitForDone`, an asserted `Event.wait`) is
  bounded by `fakes.WAIT_MS` (10 s); `tests/test_wait_sweeps.py` fails
  any other bound; a fake the code under test releases records that it
  was. Before it, R14-S1 (§268): non-blocking `check-windows`, mypy
  `--platform win32`; its failures are numbered in §268 (42, plus entry
  43 from the second run, `41700942081`, in §268's addendum: recorded,
  not a baseline).
- **The three numbers on main (a bare run, offscreen, X9 Pro opt-in
  unset):** pytest `2632 passed, 29 skipped`; mypy `--strict src/` and `--strict
  --platform win32 src/` clean, 149 files; ruff 0. Before H2: `2602
  passed, 29 skipped`. No `src/` change, so no x86_64 run.
- **CI:** read the latest run by full SHA (`gh run list --commit`).
  **H2's real evidence is the first `check-intel` run on its merge:**
  whether 10 s ends the Intel flakes is UNVERIFIED until it runs.

## 2. Where we are

Phase 02's rest is one autodev plan (2026-11-03): round 13's release,
round 14 whole (S13 skipped, S10 option a), round 15's re-plan, plus
H1 and H2. Done: GH-1, R13-S10a, H1, R14-S1, H2. In flight: none.
Status: `python3
~/.claude/skills/autonomous-development/scripts/autodev.py status`.

## 3. Next steps

1. **R13-S9 (lead) tags v0.2.0** once `check`, `check-intel` and
   `audit` are green on main's HEAD and `build.yml` is
   green on a commit with HEAD's `pyproject.toml`, `uv.lock` and
   `packaging/`. CHANGELOG's `[0.2.0]` is re-dated 2026-11-04 (RELEASING:
   "today's date"); **if the tag lands later, re-date it again
   first**. R14-S1's bullets stay in `[Unreleased]`. Tag local only;
   record its sha here.
2. R13-S9b builds both images from the tag and replaces the release
   notes' placeholders `SHA256_ARM64_PLACEHOLDER` and
   `SHA256_INTEL_PLACEHOLDER` with the `shasum -a 256` lines.
3. R14-S2 after R13-S10: it also owns isolating platformdirs in tests
   (round-14 BRIEF §2 step 5; plan → Round 14 rows; its `lead_note`).

## 4. Key context

- **Platformdirs on Windows (guards real data):** a test's `HOME` moves
  neither `expanduser()` nor, from platformdirs' source, Seeker's
  data/log/cache folders. Until R14-S2's conftest fixture lands,
  `test_lazy_spotify_config`'s `Application()` subprocesses would open a
  Windows machine's real `%LOCALAPPDATA%\Seeker`; round 15's BRIEF
  §0.3 runs no suite there before it is on main (R15-S0 checks).
- R14-S1's list, for its rows: PATH split on `:` (entries 5–8, S4);
  no drive hint off `/Volumes` (11–12, S9); a case-only rename read as
  `already_correct` (13, `library/metadata_service.py:1065`, not in
  AUDIT.md: S9, else S12); PySide6's Windows
  `LicenseRef-Qt-Commercial.txt` (38–42, `bundle_info.py:179`, S11);
  entry 28 (`os.geteuid`) hides 14 tests and causes entry 43
  (test_headless's collect-only test); the row that fixes 28 closes 43
  and reports what the 14 do on Windows. A pipe's code page: S3 in CI
  under PF-11. Typing `tests/` for `win32` is a proposal only.
- **H2's rules for new tests** (tests/CLAUDE.md): a test file that
  waits takes `from fakes import WAIT_MS` at module level, never
  rebound, or the sweep fails the build. A wait that must time out
  (inside `pytest.raises`) does not exist yet; it would need a named
  exclusion in `test_wait_sweeps.py`, its reason stated (agreement 5).
  `test_soulseek_client.py` is the first non-UI test to import `fakes`
  (review: keep it).
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
  `[Unreleased]` above `[0.2.0]`; H2 gets no CHANGELOG entry (test-only
  changes have none, H1 neither).

## 6. Blockers

None.

## 7. Files in progress

None. Merged branches and worktrees left for Kris to remove: `p02/H1`
(`agent-a12ba60fe9f01f418`), `p02/R14-S1`
(`agent-a2f629926c967ad19`), `p02/H2` (`agent-ae7b7d5bd10ba6576`);
origin's `p02/R14-S1` holds the pre-rebase commits the two CI runs
built. `dist/` and `.chromaprint/` hold gitignored build outputs.

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
- H2 review round-2 nits, comment-only, open (§269):
  (1) `tests/test_wait_sweeps.py`'s exclusion comment claims too much:
  the rule sees only `assert e.wait(...)` (`ok = e.wait(2); assert ok`
  passes it), and the `Thread.join`/`Queue.get` sites are unswept with
  no reason given (non-UI, 5 to 30 s); (3) its header does not say that
  a `QSignalSpy`/`QThread` `.wait(ms)` would be steered to `WAIT_MS /
  1000` (10 ms) or a negative `waitSignal(raising=False)` forced up to
  `WAIT_MS`. If `check-intel` flakes on a join/get or an unasserted
  wait, those are next.
- A Rosetta run here finds the x86_64 libchromaprint in
  `/usr/local/lib`, so it no longer covers a missing one: does any run
  still need to?
- PyInstaller's Intel-only libomp SDK warning (§262); Module map lacks
  `ui/row_actions.py`, `soulseek/sweep.py`, `soulseek/leftovers.py`.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

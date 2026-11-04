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

- **Released: v0.2.0** (2026-11-04T09:43:50Z, R13-S10): tag `v0.2.0`
  (object `3ff929d7`) on `5d3c5e3`, four assets, `releases/latest`;
  GitHub's digests match notes.md. Its record and README's un-gating
  are R13-S10b's, in review now. CHANGELOG's `[Unreleased]` holds
  R14-S1's two CI bullets; DEP-1 added none (no security bump).
- **HEAD is DEP-1's close-out (§271, the first entry of the new
  `docs/history/271-300.md`):** mypy 2.4.1, ruff 0.17.3 (one new rule,
  RUF071, no finding), platformdirs 4.14.0 (same folders on macOS and
  Windows; an override that is not fully qualified is now ignored).
  Before it: R13-S9b (§270), H2 (§269), R14-S1 (§268).
- **The three numbers on main (a bare run, offscreen, X9 Pro opt-in
  unset):** pytest `2632 passed, 29 skipped`, unchanged; mypy `--strict src/` and `--strict
  --platform win32 src/` clean, 149 files; ruff 0. The branch's x86_64
  suite: `2632 passed, 29 skipped`.
- **CI:** read the latest run by full SHA (`gh run list --commit`).
  DEP-1's branch head `8223c25` (run 41812144334): `check`,
  `check-intel`, `audit` green, Build 41812144395 green;
  `check-windows` "42 failed, 2547 passed, 58 skipped, 1 error", its 43
  names equal to main's run 41755383483 (diffed).

## 2. Where we are

Phase 02's rest is one autodev plan (2026-11-03): round 13's release,
round 14 whole (S13 skipped, S10 option a), round 15's re-plan, plus
H1, H2 and DEP-1. Done: GH-1, R13-S10a, H1, R14-S1, H2, R13-S9,
R13-S9b, R13-S10, DEP-1. In flight: R13-S10b (review fixes), R14-S2.
Status: `python3
~/.claude/skills/autonomous-development/scripts/autodev.py status`.

## 3. Next steps

1. **R13-S10b** (in review fixes): its branch links
   `history/271-300.md#271` in status.md and packaging.md (twice) for
   its own entry. DEP-1 took §271, so its integrator renumbers to
   §272, appends to the existing `271-300.md`, and merges its
   README file-table and section lines with DEP-1's.
2. **R14-S2** (in flight): it also owns isolating platformdirs in tests
   (round-14 BRIEF §2 step 5; its `lead_note`). It edits
   `tests/CLAUDE.md`'s Windows `HOME` fact, which DEP-1 changed to cite
   "platformdirs 4.14.0's source": a one-line overlap at rebase.
   Under 4.14.0 an override must be fully qualified (`C:\…` or
   `\\server\share`); a pytest tmp path qualifies. Its new code must
   pass ruff 0.17.
3. Dependabot #5, #7 and #8 close themselves now that main carries
   their versions; nobody touches them. platformdirs 4.14.4 is
   upstream, unread: a new PR and a new read (§271).
4. Then R14-S3 onward, per `autodev.py status`.

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
- **Release notes:** `.git/autodev/release/v0.2.0/notes.md`, filled,
  outside the tree; never commit it, never touch that folder or the tag.
- **Building on this Mac (§270, packaging/CLAUDE.md):** PyInstaller's
  ctypes scan bundles `/usr/local/lib`'s x86_64 libchromaprint (§266)
  into the arm64 app, which fails `bundle_check`. Build under
  `sandbox-exec` denying reads of `^/usr/local/lib/libchromaprint`.
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
  `[Unreleased]` above `[0.2.0]`; H2 and R13-S9b get no CHANGELOG
  entry (test-only, and docs and release process). DEP-1 gets no
  CHANGELOG line (only security bumps are recorded, as with `579cd0e`
  and `08e24f5`) and takes §271, as §248 did for the last batch.
- Kris (2026-11-04): ACCEPTANCE.md's checklist passed on the Intel
  image (the cross-image BPM/key comparison skipped, accepted by the
  lead); R13-S10's publish approved and done.

## 6. Blockers

None.

## 7. Files in progress

None. Merged branches and worktrees left for Kris to remove: `p02/H1`
(`agent-a12ba60fe9f01f418`), `p02/R14-S1`
(`agent-a2f629926c967ad19`), `p02/H2` (`agent-ae7b7d5bd10ba6576`),
`p02/R13-S9b` (`agent-a6b56d8b69bdca68f`; its `dist/` holds both
images and the smoke reports), `p02/DEP-1`
(`agent-ad89972bf2bc73aa7`, also on origin);
origin's `p02/R14-S1` holds the pre-rebase commits the two CI runs
built. `dist/` and `.chromaprint/` hold gitignored build outputs.

## 8. Waiting on Kris

- The X9 Pro opt-in path has not been run since H1 gated it (§267).
- **After R13-S10b:** the browser download and first launch of each
  image, Help -> Check for updates in both apps, the website's
  Download buttons. Later: round 15's machine.
- **Proposed rows, awaiting Kris (not in tasks.json):** (A)
  `seeker.spec` filters any libchromaprint the ctypes scan picks up
  that `bundle_info` did not stage (a symlink twin on CI's Intel job, a
  foreign-arch copy on this Mac), or RELEASING §2 hides that copy for
  both builds; (B) `build.yml`'s `uv sync` takes the runner's
  python.org 3.13.17 while the release uses python-build-standalone
  3.13.15, so CI's build smoke test runs another runtime (§270).
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
  `/usr/local/lib`, so it no longer covers a missing one (and it breaks
  an unsandboxed arm64 build, §270): does any run still need it?
- PyInstaller's Intel-only libomp SDK warning (§262); Module map lacks
  `ui/row_actions.py`, `soulseek/sweep.py`, `soulseek/leftovers.py`.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

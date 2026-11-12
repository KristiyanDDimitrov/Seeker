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

- **Released: v0.2.0** (2026-11-04, tag `v0.2.0` on `5d3c5e3`, four
  assets, `releases/latest`). CHANGELOG's `[Unreleased]` holds R14-S1's
  two CI bullets and R14-S2's (no console window, UTF-8 output).
- **main = origin/main = R14-S2's close-out (§273)**, 2026-11-12: every
  program `src/` starts goes through `seeker/processes.py`. `tasks.json`
  (run state) and this file are committed with it.
- **The three numbers on main**, re-run 2026-11-12 on R14-S2's head
  (`abb6112`; a bare run, offscreen, X9 Pro opt-in unset): pytest `2710
  passed, 35 skipped` (6 of the skips Windows-only); mypy `--strict
  src/` and `--platform win32` clean, 150 files; ruff 0.
- **CI on main:** R14-S2's push, run in the integrator's report (the
  lead watches it). Before it, 9ab238a (run 42830514266): check,
  check-intel, audit green, run conclusion success; check-windows failed
  as on the baseline (its names not compared). check-windows' baseline:
  run 41814614530 on main, `42 failed, 2547 passed, 58 skipped, 1
  error`, 43 names; on R14-S2's branch (run 43270539077) the same 43 names at
  `42 failed, 2630 passed, 59 skipped, 1 error`, the new baseline line.

## 2. Where we are

The autodev plan (2026-11-03). Done: GH-1, R13-S10a, H1, R14-S1, H2,
R13-S9, R13-S9b, R13-S10, DEP-1, R13-S10b, **R14-S2** (§273: the
subprocess helper and its sweep, the docker guard by stem, platformdirs
isolated in tests). Round 13 is closed; its post-release checks are
Kris's (§8). Next: **R14-S3** (UTF-8 for every text file), which
R14-S4, S5, S6 and S10 wait on.

## 3. Next steps

1. **A fresh lead:** `/autonomous-development run` (registers the
   hooks) or `launch.sh docs/phase-02/autodev/tasks.json`; then
   `autodev.py next`.
2. **R14-S3**, with R14-S2's carried items:
   - the eight bare `read_text()` reads in the source sweeps:
     `test_errors.py:21`, `test_formatting.py:81`, `test_layering.py:31`,
     `test_wait_sweeps.py:20, 200, 299`, `test_quit_stop_sweep.py:37,
     67`. Make them UTF-8 under S3's guard, then drop `tests/CLAUDE.md`'s
     cp1252 fact. Until then a byte cp1252 leaves undefined (0x81, 0x8D,
     0x8F, 0x90, 0x9D; U+201D and U+6771 each hold one) anywhere in
     `src/` or `tests/` breaks five sweeps on Windows.
   - Review round 2's nit: test_headless's and test_subprocess_sweep's
     readers ignore decorators and a later rebinding of `run`/`popen`.
3. **Rows that start a program (S3, S4, S5, S10):** through
   `seeker.processes`. A new program joins `OPENS_NOTHING` or
   `_DESKTOP_PROGRAMS`; a new keyword on the helper's own spawn joins
   test_headless's `_FORWARDED_KEYWORDS`, once shown not to change the
   program (`executable`, `shell` never).
4. **Open follow-up (§273):** a CI-only `DETACHED_PROCESS` console
   control that skips unless `GITHUB_ACTIONS` is set; the Headless rule
   guards Kris's screen, not a CI runner. needs-ci; no row owns it yet.
5. **Ask Kris** once for §8's post-release checks.

## 4. Key context

- **`gh run watch --exit-status` exits 1 whenever the non-blocking
  check-windows fails**, so read each job's conclusion, never the exit
  code. `gh run list --commit` needs the full SHA.
- **A worktree-isolated subagent works only in its own worktree**
  (observed 2026-11-10): the harness refuses its git commands elsewhere
  and its writes outside its own, `.git/autodev/reports/` included. A
  respawned worker fast-forwards its harness branch onto the row's
  branch, builds there and reports to the lead's scratchpad; the lead
  files the report and fast-forwards the row branch. Tell it up front.
- An ended session's subagents cannot be resumed: respawn, naming the
  branch and the report.
- **Windows tests:** conftest's `_no_real_seeker_folders` points
  `WIN_PD_OVERRIDE_LOCAL_APPDATA` at a pytest folder (observed on
  check-windows); round 15 BRIEF §0.3's precondition holds now.
  conftest's guard reads `args` only, never `executable=`; the helper
  has no such keyword and the sweep refuses one.
- R14-S1's failure list, by row: PATH on `:` (5–8, S4); drive hint
  (11–12, S9); case-only rename (13, S9 else S12); PySide6 licence file
  (38–42, S11); entry 28 (`os.geteuid`) hides 14 tests and causes 43.
  R14-S2: entry 30 could use a `docker.cmd` stand-in now the guard reads
  stems (UNVERIFIED; S12); entry 33's empty-home check cannot see a
  write under the override, so its fix points the child's override
  into `home`.
- H2's rule: a test file that waits takes `from fakes import WAIT_MS` at
  module level, never rebound.
- Release notes: `.git/autodev/release/v0.2.0/notes.md`; never commit or
  touch that folder or the tag. Building on this Mac: `sandbox-exec`
  denying `/usr/local/lib/libchromaprint` (§270).
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.

## 5. Decisions made

- Kris (2026-11-03): the plan's eight decisions; X9 Pro tests opt-in.
  Kris (2026-11-04): ACCEPTANCE.md passed on the Intel image; R13-S10's
  publish approved. Kris (2026-11-10): Dependabot #8 closed by the lead
  ("Already on main: 8223c25"); "Not yet" to R13-S10b's after-release
  checks.
- Integrator: R14-S1's and R14-S2's CHANGELOG bullets in
  `[Unreleased]`; H2, R13-S9b, DEP-1 and R13-S10b get none. R14-S2's
  standing facts: CLAUDE.md → Conventions (the helper), tests/CLAUDE.md
  (guard by stem, `_FORWARDED_KEYWORDS`, cp1252 bytes, 35 skips).
- Lead (2026-11-10): R14-S2 took one CI run rather than splitting its
  platformdirs commit.

## 6. Blockers

None.

## 7. Files in progress

- None in flight. R14-S2's worktree and local branch are removed;
  `origin/p02/R14-S2` remains.
- Locked worktrees, left for Kris: `agent-a412b1ac17ba70460`
  (`worktree-agent-a412b1ac17ba70460` @ `4714674`) and
  `agent-a622aacbbafc0ca45` (@ `e038df3`), R14-S2's two harness
  branches, both superseded by main.
- Superseded or merged, left for Kris to remove: `agent-afb1763b72e9a7acb`
  (`p02/R13-S10b` @ `1911e49`), `p02/H1`, `p02/R14-S1`, `p02/H2`,
  `p02/R13-S9b` (its `dist/` holds both images), `p02/R13-S10a`,
  `p02/DEP-1`.

## 8. Waiting on Kris

- **After R13-S10b** (asked 2026-11-10: "Not yet"): the browser
  download and first launch of each image, Help → Check for updates in
  both apps, the website's Download buttons; recommended, the BPM/key
  comparison he offered (whether its skip stands is open, §272). Then
  round 13's five unticked Intel boxes in `round-13/ACCEPTANCE.md`.
- platformdirs 4.14.4 is upstream, unread (no PR open).
- The X9 Pro opt-in path has not run since H1 gated it (§267).
- Proposed rows, not in tasks.json (§270): (A) `seeker.spec` filters a
  stray libchromaprint; (B) build.yml's runtime differs from the
  release's.

## 9. Open questions

- §262: without ffmpeg a non-audio file reads `error`, with it
  `decode_unsupported`; which is right? PyInstaller's libomp warning.
- §267: `BROWSER` set to an unregistered program spawns unrefused.
- §268: entries 31–33's causes; test_connection's 16 s on Windows.
- §269: H2's round-2 comment nits on `test_wait_sweeps.py`.
- §273: whether `CREATE_NO_WINDOW` hides a window is unobserved (the
  console control skips on CI); round 15 §0.7 settles it on hardware.
- Does any run still need Rosetta without `/usr/local/lib`'s chromaprint?
- Module map lacks `ui/row_actions.py`, `soulseek/sweep.py`,
  `soulseek/leftovers.py`.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

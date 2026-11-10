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
  two CI bullets.
- **main = origin/main = R13-S10b's close-out (§272)**, 2026-11-10:
  README un-gated, round 13 closed. `tasks.json` (run state) and this
  file are committed with it.
- **The three numbers on main**, re-run 2026-11-10 on R13-S10b's head
  (a bare run, offscreen, X9 Pro opt-in unset): pytest `2632 passed,
  29 skipped`; mypy `--strict src/` and `--platform win32` clean, 149
  files; ruff 0.
- **CI on main:** R13-S10b's push, run in the integrator's report (the
  lead watches it); before it, 42653099166 green. check-windows' baseline on main is run 41814614530: `42 failed, 2547
  passed, 58 skipped, 1 error`, 43 names.

## 2. Where we are

The autodev plan (2026-11-03). Done: GH-1, R13-S10a, H1, R14-S1, H2,
R13-S9, R13-S9b, R13-S10, DEP-1, **R13-S10b** (§272: v0.2.0 verified,
README un-gated, round 13 closed; round 13's `tasks.json` S9 and S10
done). **Round 13 is closed**; its post-release checks are Kris's (§8).
**R14-S2: review round 1 `fix`** (2026-11-10), a fresh worker
continuing. Everything else waits on R14-S2 (R14-S3 first).

## 3. Next steps

1. **A fresh lead:** `/autonomous-development run` (registers the
   hooks) or `launch.sh docs/phase-02/autodev/tasks.json`; then
   `autodev.py next`.
2. **Ask Kris** once for §8's post-release checks and Dependabot #8.
3. **R14-S2, review round 1 `fix`** (2026-11-10). Its findings:
   `processes.py`'s docstring and `test_processes.py:195-204` overclaim
   what check-windows showed, since the control skipped there;
   `test_headless.py`'s `_forwarding_call` should reject `executable`/
   `shell`; the HISTORY draft should note U+FFFD on undecodable docker
   output. The earlier worker's session ended, so a fresh worker
   (agent `a622aacbbafc0ca45`, attempt 2) continues `p02/R14-S2` from
   its own worktree; then re-review. Before the fix: `p02/R14-S2` @
   `4714674`, pushed. Report `.git/autodev/reports/R14-S2.md`, current
   report on top. Run
   42812791705 on `ccd8355`: check, check-intel, audit, Build green;
   check-windows had 9 new cp1252 decode failures, fixed in `ee02521`.
   Run 42817632165 on `4714674`: check, check-intel, audit green;
   check-windows `42 failed, 2626 passed, 59 skipped, 1 error`, its 43
   names equal to main's. Build is path-filtered (pyproject, uv.lock,
   packaging, build.yml) and did not run; it was green on `ccd8355`.
4. **R14-S3** owns the eight bare `read_text()` reads in the source
   sweeps (R14-S2's report lists them). Until they read UTF-8, a byte
   cp1252 leaves undefined (0x81, 0x8D, 0x8F, 0x90, 0x9D: `"` U+201D
   holds one) anywhere in `src/` or `tests/` breaks five sweeps on
   Windows. Write such text in escapes.

## 4. Key context

- **A worktree-isolated subagent works only in its own worktree**
  (observed 2026-11-10). The harness refuses its git commands in any
  other worktree, and its writes outside its own, `.git/autodev/reports/`
  included. So a respawned worker fast-forwards its harness branch onto
  the row's branch and builds there, and writes its report to the lead's
  scratchpad. The lead then files the report and fast-forwards the row
  branch. Tell a respawned worker this up front.
- An ended session's subagents cannot be resumed (SendMessage: "No
  transcript found"): respawn, naming the branch and the report.
- `gh run list --commit` needs the full SHA.
- **Platformdirs on Windows:** R14-S2's session fixture
  `_no_real_seeker_folders` points `WIN_PD_OVERRIDE_LOCAL_APPDATA` at a
  pytest tmp path; run 42812791705 observed the probe and control green.
  Until it is on main, no suite runs on a real Windows machine (round 15
  BRIEF §0.3).
- R14-S1's failure list, by row: PATH on `:` (5–8, S4); drive hint (11–12,
  S9); case-only rename (13, S9 else S12); PySide6 licence file (38–42,
  S11); entry 28 (`os.geteuid`) hides 14 tests and causes 43. R14-S2's
  notes: entry 30 could use a `docker.cmd` stand-in (S12); entry 33's
  fix points the child's override into `home`.
- H2's rule: a test file that waits takes `from fakes import WAIT_MS` at
  module level, never rebound.
- Release notes: `.git/autodev/release/v0.2.0/notes.md`; never commit or
  touch that folder or the tag. Building on this Mac: `sandbox-exec`
  denying `/usr/local/lib/libchromaprint` (§270).
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.

## 5. Decisions made

- Kris (2026-11-03): the plan's eight decisions; X9 Pro tests opt-in.
  Kris (2026-11-04): ACCEPTANCE.md passed on the Intel image; R13-S10's
  publish approved.
- Integrator: R14-S1's CHANGELOG bullets in `[Unreleased]`; H2, R13-S9b,
  DEP-1 and R13-S10b get no CHANGELOG line. R13-S10b's standing fact
  (what CI checks of audio analysis) is in `tests/CLAUDE.md`. R14-S2 proposes one ("programs open
  no console window, output reads as UTF-8"): the integrator's call.
- Lead (2026-11-10): R14-S2 takes one CI run rather than splitting
  `bd9660d`. The control child shows HOME moving nothing.

## 6. Blockers

None.

## 7. Files in progress

- In flight: R14-S2's fresh worker in its own worktree;
  `agent-a135fd3b734e4bead` (`p02/R14-S2`) and `agent-a412b1ac17ba70460`
  (its harness branch), both kept until R14-S2 integrates.
- Stash `ac6d6dc0` ("R14-S2 first worker's uncommitted copies…"):
  superseded by `ccd8355`; drop it after R14-S2 integrates.
- Superseded or merged, left for Kris to remove: `agent-afb1763b72e9a7acb`
  (`p02/R13-S10b` @ `1911e49`), `p02/H1`, `p02/R14-S1`, `p02/H2`,
  `p02/R13-S9b` (its `dist/` holds both images), `p02/R13-S10a`,
  `p02/DEP-1`.

## 8. Waiting on Kris

- **Dependabot #8 is still open** (§272). Dependabot cannot update it (uv
  version), so it stays open until someone closes it: Kris's call, e.g.
  "Already on main: 8223c25". platformdirs 4.14.4 is upstream, unread.
- **After R13-S10b (now):** the browser download and first launch of
  each image, Help → Check for updates in both apps, the website's
  Download buttons; recommended, the BPM/key comparison he offered
  (whether its skip stands is open, §272). Then round 13's five
  unticked Intel boxes in `round-13/ACCEPTANCE.md`.
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
- Does any run still need Rosetta without `/usr/local/lib`'s chromaprint?
- Module map lacks `ui/row_actions.py`, `soulseek/sweep.py`,
  `soulseek/leftovers.py`.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

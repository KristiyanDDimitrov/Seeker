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
  two CI bullets, R14-S2's (no console window, UTF-8 output) and
  R14-S3's Fixed bullet (UTF-8 files and CLI output on Windows).
- **main = origin/main = R14-S3's close-out (§274)**, 2026-11-13: every
  text read or write names `encoding="utf-8"`, under PLW1514 and
  `tests/test_encoding_sweep.py`; the CLI's stdout/stderr are UTF-8;
  settings, Compose or `slskd.yml` that are not UTF-8 raise
  `TextFileNotUtf8Error` and are left as they are. `tasks.json` and this
  file are committed with it.
- **The three numbers on main**, re-run 2026-11-13 on R14-S3's head
  (`bafb481` plus the docs-only close-out; a bare run, offscreen, X9
  Pro opt-in unset): pytest `2768 passed, 36 skipped` (7 of the skips
  Windows-only); mypy `--strict src/` and `--platform win32` clean, 150
  files; ruff 0.
- **CI on main:** R14-S3's push, run in the integrator's report (the
  lead watches it). On the branch head (run 43334141779): check,
  check-intel, audit green. **check-windows' baseline is now that
  run's: `41 failed, 2690 passed, 59 skipped, 1 error`, 42 names**:
  run 41814614530's 43 minus entry 29 (closed by `7c41507`).

## 2. Where we are

The autodev plan (2026-11-03). Done: GH-1, R13-S10a, H1, R14-S1, H2,
R13-S9, R13-S9b, R13-S10, DEP-1, R13-S10b, R14-S2, **R14-S3** (§274:
UTF-8 for every text file, the sweep, the CLI's output, vendored
licences `-text`). Round 13 is closed; its post-release checks are
Kris's (§8). S1's list (§268): 42 entries remain (41 failed, 1 error).

## 3. Next steps

1. **A fresh lead:** `/autonomous-development run` (registers the
   hooks) or `launch.sh docs/phase-02/autodev/tasks.json`; then
   `autodev.py next`.
2. **R14-S4, R14-S5, R14-S6, R14-S10**, which depend only on R14-S3.
   R14-S3's carried items:
   - New text I/O names `encoding="utf-8"`. The sweep refuses
     configparser, fileinput, logging.config and another module's
     `.open` until `_BUILTIN_OPENS` or `_OPENS_NO_TEXT` gains it, and
     its allow-lists grow only with a reason. A Qt object's
     `.open(flags)` would be read as a Path's and refused.
   - **R14-S4:** on Windows, a test that runs a bare program name after
     `test_application.py` meets the PATH entries 5–8 mangle; `3b7bedb`
     works around it for git only. The fix should leave PATH whole.
   - **R14-S5:** `write_text_atomic` writes CRLF on Windows (text mode);
     it may want LF for the Compose YAML.
   - The CLI's stdin is not reconfigured; its prompts read only y/n.
3. **Rows that start a program (S4, S5, S10):** through
   `seeker.processes`. A new program joins `OPENS_NOTHING` or
   `_DESKTOP_PROGRAMS`; a new keyword on the helper's own spawn joins
   test_headless's `_FORWARDED_KEYWORDS`, once shown not to change the
   program (`executable`, `shell` never).
4. **Open follow-up (§273):** a CI-only `DETACHED_PROCESS` console
   control that skips unless `GITHUB_ACTIONS` is set. needs-ci; no row
   owns it yet.
5. **Ask Kris** once for §8's post-release checks and the candidate row.

## 4. Key context

- **`gh run watch --exit-status` exits 1 whenever the non-blocking
  check-windows fails**, so read each job's conclusion, never the exit
  code. `gh run list --commit` needs the full SHA.
- **A macos-26 job (CI's check, Build's arm64) cancelled with no steps
  after about 15 minutes queued is the runner queue, not a failure**
  (seen twice 2026-11-12): rerun that job once the run completes
  (`gh run rerun <run> --job <id>`).
- **A worktree-isolated subagent works only in its own worktree**
  (observed 2026-11-10): the harness refuses its git commands elsewhere
  and its writes outside its own, `.git/autodev/reports/` included. A
  respawned worker fast-forwards its harness branch onto the row's
  branch, builds there and reports to the lead's scratchpad; the lead
  files the report and fast-forwards the row branch. Tell it up front.
- An ended session's subagents cannot be resumed: respawn, naming the
  branch and the report.
- **Windows tests:** conftest's `_no_real_seeker_folders` points
  `WIN_PD_OVERRIDE_LOCAL_APPDATA` at a pytest folder. conftest's guard
  reads `args` only, never `executable=`.
- R14-S1's failure list, by row: PATH on `:` (5–8, S4); drive hint
  (11–12, S9); case-only rename (13, S9 else S12); PySide6 licence file
  (38–42, S11); entry 28 (`os.geteuid`) hides 14 tests and causes 43;
  entry 29 closed (R14-S3). Entry 30 could use a `docker.cmd` stand-in
  (UNVERIFIED; S12); entry 33's fix points the child's override into
  `home`.
- H2's rule: a test file that waits takes `from fakes import WAIT_MS` at
  module level, never rebound.
- Release notes: `.git/autodev/release/v0.2.0/notes.md`; never commit or
  touch that folder or the tag. Building on this Mac: `sandbox-exec`
  denying `/usr/local/lib/libchromaprint` (§270).
- Never `cmd | tail && git commit`: a pipe hides the gate's exit code.

## 5. Decisions made

- Kris (2026-11-03): the plan's eight decisions; X9 Pro tests opt-in.
  Kris (2026-11-04): ACCEPTANCE.md passed on the Intel image; R13-S10's
  publish approved. Kris (2026-11-10): "Not yet" to R13-S10b's
  after-release checks.
- Lead (R14-S3 review round 1): settings that are not UTF-8 raise
  `TextFileNotUtf8Error` and are left untouched, never defaults; the
  token reads as none.
- Integrator: CHANGELOG bullets for R14-S1, S2, S3 in `[Unreleased]`.
  R14-S3's standing facts: CLAUDE.md → Conventions ("Text is UTF-8,
  never the locale's"); tests/CLAUDE.md (encoding fact, 36 skips).

## 6. Blockers

None.

## 7. Files in progress

- None in flight. R14-S3's worktree and local branch are removed;
  `origin/p02/R14-S3` and `origin/p02/R14-S2` remain.
- Locked worktrees, left for Kris: `agent-a412b1ac17ba70460`
  (`worktree-agent-a412b1ac17ba70460` @ `4714674`) and
  `agent-a622aacbbafc0ca45` (@ `e038df3`), R14-S2's two harness
  branches, both superseded by main.
- Superseded or merged, left for Kris to remove: `agent-afb1763b72e9a7acb`
  (`p02/R13-S10b` @ `1911e49`), `p02/H1`, `p02/R14-S1`, `p02/H2`,
  `p02/R13-S9b` (its `dist/` holds both images), `p02/R13-S10a`,
  `p02/DEP-1`.

## 8. Waiting on Kris

- **A decision the lead will ask him (§274, `docs/status.md` → Open
  issues):** a candidate row. A `config.json` that is not valid JSON,
  a UTF-8 file with a BOM included, loads as defaults, and the next
  save writes them over his Spotify and Soulseek credentials. The GUI's
  startup dialog for `TextFileNotUtf8Error` (today it only logs at
  CRITICAL and quits) is a follow-up there too.
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

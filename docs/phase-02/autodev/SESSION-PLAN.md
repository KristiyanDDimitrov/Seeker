# Phase 02, the rest — autonomous-development plan

**Planned 2026-11-03** (base `d3403de`). This plan finishes what is
left of phase 02 ([`../README.md`](../README.md)) as one
`autonomous-development` run: a lead session schedules, workers build
each row in their own worktree, a reviewer attacks every branch, one
integrator at a time merges. Status lives in [`tasks.json`](tasks.json),
changed only through `autodev.py`. The task text stays in the round
briefs and [`../AUDIT.md`](../AUDIT.md); nothing here repeats it.

It replaces, for execution, round 13's open rows (S9, S10, re-cut
below) and round 14's session plan (its rows unchanged in substance).
Round 15 needs a real Windows PC, which no worker on this Mac has: the
run ends by re-planning it (`R15-S0`) as a second autodev plan for that
machine.

Start the run: `~/.claude/skills/autonomous-development/scripts/launch.sh docs/phase-02/autodev/tasks.json`

---

## Kris's decisions (2026-11-03)

Sessions do not ask again.

1. **Scope:** round 13's release, all of round 14, round 15's re-plan.
2. **Order:** round 14's rows that change `src/`, `packaging/`,
   `pyproject.toml` or `uv.lock` wait until v0.2.0 is published.
   R14-S1 (CI only) and the tests-only rows (H1, H2) run at once.
3. **Wait bound:** yes, one named bound for the suite's short
   `waitUntil`s (row H2).
4. **R14-S10:** option (a), a CI-built `chromaprint.dll`.
5. **Headless:** every automated run is offscreen; a native Cocoa run
   happens only when Kris types `QT_QPA_PLATFORM=cocoa uv run pytest`.
6. **Licence wording:** libchromaprint is "LGPL-2.1-or-later" in the
   README, once checked against the pinned source's headers.
7. **R14-S13** (the Windows VM pass) is skipped.
8. libchromaprint for the Intel build is built (`.chromaprint/lib`,
   1.6.2, observed 2026-11-03).

Standing decisions from 2026-10-17 (`../README.md` → "Kris's
decisions") still hold: no code signing, Docker Desktop on Windows,
one DMG per architecture.

---

## Headless: nothing reaches Kris's screen

Kris works on this Mac while the run goes. **No command a row runs may
open a window, take focus, put an icon in the Dock, post a
notification or raise a permission prompt.**

- Until H1 merges, every suite is run with `QT_QPA_PLATFORM=offscreen`
  spelled out (the commands below do). H1 makes it the default.
- `seeker-ui --smoke-test` already builds its `QApplication` offscreen
  (`ui/smoke_test.py`); `tools/screenshots.py` sets offscreen itself.
- Nobody starts `seeker-ui` or the built app without `--smoke-test`,
  runs `open`, `osascript` or Docker, or reads a TCC-protected folder
  (Music, Documents, Desktop, removable volumes). A step that needs any
  of these is Kris's: `needs-physical`, with the exact steps.
- The skill's own desktop notifications (the run needs Kris) are
  intended; they are the only popups.

---

## Roles

| Role | Model | Effort |
|---|---|---|
| Lead (launch.sh) | opus | xhigh |
| Worker | opus | the row's `effort` below |
| Reviewer | opus | xhigh |
| Integrator | opus | high |
| `suite-runner`, `ci-watcher` (`.claude/agents/`) | their file's model | — |

Workers use the skill's `agents/worker.md` (general-purpose agent,
`isolation: "worktree"`), not the round-13 `row-worker` agent.

## Rows

`deps` must be `done` before a row starts; parallelism comes only from
them. **Kris** is what the run waits on: *before* blocks the start,
*after* is a gate that blocks the row's dependents.

| Row | Title | Type · risk | Effort | Deps | Est. work | Split point | Kris |
|---|---|---|---|---|---|---|---|
| GH-1 | Close Dependabot PRs #1, #5, #7, #8; delete origin's `r13/S7`, `r13/S7c` (lead) | release | high | — | ~4 K | — | — |
| H1 | Tests headless by default; nothing a test runs reaches the desktop | behaviour | xhigh | — | ~45 K | After the default and its test | — |
| H2 | One named bound for the suite's short waits, with a sweep | refactor | high | H1 | ~60 K | After the constant and half the files | — |
| R13-S10a | v0.2.0 prepared: version, lock, CHANGELOG, licence wording, notes draft | release | high | — | ~30 K | After the version commit | — |
| R13-S9 | Tag v0.2.0 locally, once CI is green on it (lead) | release | high | R13-S10a, H2 | ~5 K | — | — |
| R13-S9b | Both v0.2.0 images built from the tag, RELEASING §3, ACCEPTANCE.md | release | xhigh | R13-S9 | ~45 K | After the arm64 image | after: BRIEF §9 checklist |
| R13-S10 | Publish v0.2.0 (lead) | release | high | R13-S9b | ~5 K | — | before: the exact commands and notes |
| R13-S10b | v0.2.0 verified; README un-gated; round 13 closed | release | high | R13-S10 | ~35 K | After the release checks | after: update check, website |
| R14-S1 | Windows CI job (non-blocking); the failure list; `mypy --platform win32` | investigation | max | — | ~45 K | After the failure list | — |
| R14-S2 | One way to run a subprocess; docker guard by stem | behaviour · security | max | R14-S1, R13-S10 | ~55 K | After docker_setup and sharing move | — |
| R14-S3 | UTF-8 for every text file, with a guard; the CLI's output | behaviour · user-data | max | R14-S2 | ~35 K | After the file sites | — |
| R14-S4 | Windows' PATH left whole; "Launch Docker Desktop" | behaviour | xhigh | R14-S3 | ~35 K | After the PATH fix | — |
| R14-S5 | Sharing's Compose line valid YAML; one path-comparison key | behaviour · user-data | max | R14-S3 | ~55 K | After the YAML line | — |
| R14-S6 | Tray and window icons, menus, platform words | feature | xhigh | R14-S3 | ~55 K | After the icons | — |
| R14-S7 | One Seeker at a time (`QLocalServer`, "show") | feature · concurrency, security | max | R14-S6 | ~55 K | After a second instance exits | — |
| R14-S8 | Start at login on Windows, over a registry seam | feature · security | max | R14-S6 | ~45 K | After the backend, before Settings | — |
| R14-S9 | Windows file-system rules; PF-22 accepted | behaviour · user-data | max | R14-S5 | ~65 K | After drive-safe joins and reserved names | — |
| R14-S10 | `chromaprint.dll` built in CI and bundled (option a) | feature · security | max | R14-S3 | ~55 K | After the DLL builds in CI | — |
| R14-S11 | The Windows build in CI: identity, per-user installer, smoke test | feature · user-data | max | R14-S7, R14-S10 | ~65 K | After the one-folder build's smoke test | — |
| R14-S12 | The Windows suite green; the job blocking | behaviour | xhigh | R14-S4, R14-S5, R14-S8, R14-S9, R14-S11 | ~65 K | At a group boundary of S1's list | — |
| R15-S0 | Round 15 re-planned as an autodev plan for the Windows PC | docs | high | R14-S12 | ~45 K | After the brief's rows | after: machine, owner, accounts, dates |

**Critical path:** R14-S1 ∥ (H1 → H2, R13-S10a) → R13-S9 → R13-S9b →
Kris's checklist → R13-S10 → R14-S2 → R14-S3 → R14-S6 → R14-S7 →
R14-S11 → R14-S12 → R15-S0 (12 of 22 rows). The checklist is the one
long wait on Kris; everything not behind it runs first.

**Why these edges.** Rows that edit the same files are sequential:
R14-S3 is a sweep over every text file, so the Windows rows fan out
only after it; S6 → S7 (both `main_ui.py`/`main_window.py`); S5 → S9
(the path key S9's joins use); S2 before S3/S4/S5/S10 (the subprocess
helper); S7 and S10 before S11 (what the installer bundles and how it
finds a running Seeker); S12 last (S1's list shrinks with each fix).
H2 follows H1 (both edit `tests/`). The tag waits for H2 so the
release commit carries the Intel wait fix.

---

## Row notes and reading lists

Common reading for every row (~5 K): `docs/HANDOFF.md`; this file's
row, its notes and the Session protocol; the round brief's §0
(`round-13/BRIEF.md:28-91`; round 14 adds `round-14/BRIEF.md:24-66`).
A range like `AUDIT.md:234-252` is one finding; `grep -n` a large file
before reading it.

### GH-1 — round 13's GitHub leftovers (lead)

Kris's yes, 2026-11-03. Each PR's change is already on main: close it
with `gh pr close <n> --comment "<the commit on main that carries it>"`
(find it with `git log --oneline --grep`, or by the file it bumps).
Then `git push origin --delete r13/S7 r13/S7c`, after `git branch -r
--contains` shows both merged into `origin/main`.

### H1 — tests headless by default

Make `QT_QPA_PLATFORM=offscreen` the suite's default
(`os.environ.setdefault` in `tests/conftest.py` before any
`QApplication` exists), so a bare `uv run pytest` and every subprocess
a test starts inherit it, and an explicit value (`cocoa`) still wins.
Test first: a test that the `qapp`'s `platformName()` is `offscreen`
when the variable was unset fails on HEAD (`cocoa`). Then audit what
else a test can show: grep `tests/` and the code it drives for
`QDesktopServices`, `open`/`osascript` spawns, `NSApplication`/`AppKit`,
`setActivationPolicy`, `QSystemTrayIcon.showMessage`, native file
dialogs, notifications, and paths under TCC-protected folders. Each
reaches the desktop only through a fake, and `conftest.py` refuses an
`open` or `osascript` spawn for the session as it refuses `docker`
(PF-34's guard; a sweep test pins both). Evidence that nothing
registers with the window server while the suite runs: poll
`lsappinfo list` for a Python process of type Foreground during a full
run (method UNVERIFIED; record what it shows). Docs: `tests/CLAUDE.md`
("Local runs use Cocoa" becomes the opt-in), `CLAUDE.md` → Commands and
agreement 3 (the tracked count is the offscreen count), and
`.claude/agents/suite-runner.md` (offscreen is the default; Cocoa only
when asked). Record the new baseline.
Reading (~6 K): `tests/conftest.py` (grep, ~2 K) · `tests/CLAUDE.md:15-45`
· `.claude/agents/suite-runner.md` · `CLAUDE.md` → Commands.

### H2 — one named bound for short waits

HISTORY §265: the Intel runner is 5–10× slower on UI tests, and 355
`waitUntil` calls use short literal bounds (346 at 2000 ms). Replace
the upper bounds of `waitUntil`/`waitSignal`/`waitCallback` with one
named constant in `tests/fakes.py`, its value justified from §265's
`--durations` numbers. Never lengthen a fixed delay (`qtbot.wait(ms)`)
or a wait that asserts something does *not* happen: a green run must
not get slower (measure the suite's wall clock before and after). A
sweep test fails on any literal bound left; each exclusion names why
it cannot hide a short bound (agreement 5). Test first: the sweep
fails on HEAD.
Reading (~4 K): `grep -n "<a name=\"265\">" docs/history/241-270.md`
then that entry · `tests/fakes.py` (grep `def settle_workers`, waits) ·
`tests/CLAUDE.md` (UI-test waits).

### R13-S10a — v0.2.0 prepared

RELEASING §1 steps 2–3: `version = "0.2.0"`, `uv lock`, CHANGELOG's
`[0.2.0] - <date>` with its compare link. README → License: the Intel
app's libchromaprint is "LGPL-2.1-or-later", after reading the pinned
1.6.2 source's licence headers (the tarball `build_chromaprint.sh`
verifies, or the upstream tag); say which in the report. The release
notes per RELEASING §4, with the SHA-256s as placeholders, written to
`<git common dir>/autodev/release/v0.2.0/notes.md` (outside the tree).
The README's three "0.2.0" gates stay until R13-S10b.
Reading (~3 K): `RELEASING.md:14-54`, `:164-186` · `README.md:80-100`,
`:225-240` · `CHANGELOG.md:1-30`.

### R13-S9 — tag (lead)

Before tagging, through `ci-watcher`: `check`, `check-intel` and
`audit` green on main's HEAD, and `build.yml` green on a commit with
HEAD's `pyproject.toml`, `uv.lock` and `packaging/` (R13-S10a's push
starts it). Then `git tag -a v0.2.0 -m "Seeker 0.2.0"` on that HEAD,
local only, and record the sha in the handoff. Main may move on after;
the tag pins the release.

### R13-S9b — both images from the tag

Branch at the tag (`git switch -c <branch> v0.2.0`; the worktree must
stay clean for `git describe`). `uv sync --locked`; the x86_64
environment per `CLAUDE.md` → Commands. RELEASING §2 then §3 for each
image, the arm64 one checked before the Intel build replaces
`dist/Seeker.app`; the Intel build with
`SEEKER_CHROMAPRINT_DIR=<main checkout>/.chromaprint/lib`. `shasum -a
256` each image into its `.sha256`. Copy the four files to
`<git common dir>/autodev/release/v0.2.0/` (worktrees are deleted;
that folder survives) and fill the notes' SHA-256s. Write
`docs/phase-02/round-13/ACCEPTANCE.md` (format: round 12's): both
SHA-256s, the §3 results, then Kris's checklist (BRIEF §9), including
how he gets a quarantined copy of the Intel image. A failed §3 check:
report `blocked`; the lead deletes the local tag (RELEASING: fix and
restart from §1). No slskd bring-up anywhere.
Reading (~3 K): `round-13/BRIEF.md:519-546` · `RELEASING.md:55-160` ·
`docs/phase-01/round-12/ACCEPTANCE.md` (headings).

### R13-S10 — publish (lead)

Show Kris, verbatim: `python3 <autodev.py> push-check`, `git push
origin v0.2.0`, and `gh release create v0.2.0 <the four files in
.git/autodev/release/v0.2.0/> --title "Seeker 0.2.0" --notes-file
<notes.md> --verify-tag`, plus the notes. Run them only on his yes.

### R13-S10b — verified and closed

RELEASING §5 as far as a worker can: `gh release view v0.2.0` lists
the four assets; `gh release download` into the scratchpad and `shasum
-a 256 -c` each. Un-gate the README (`From 0.2.0`, `Download (from
0.2.0)`, `Until 0.2.0 is published…`; `grep -rn S7-PENDING docs` stays
empty). `docs/status.md` → Roadmap. Measure round 13's exit criteria
(`round-13/SESSION-PLAN.md` → Exit criteria) for the HISTORY draft.
Kris's gate after: the browser download and first launch, Help →
"Check for updates…" up to date in both apps, the website's Download
buttons.
Reading (~3 K): `RELEASING.md:187-203` · `round-13/SESSION-PLAN.md:388-410`
· `README.md:80-100` · `docs/status.md` (grep Roadmap).

### Round 14 rows

Each executes its `round-14/BRIEF.md` section; the brief's §0 holds
(Windows on a Mac: patched `sys.platform`, `PureWindowsPath`,
`winerror`; never `PYTHONUTF8`). **Every round-14 row** appends what it
could not verify to `round-15/BRIEF.md` → §0.7, reports
`mypy --strict --platform win32 src/`'s last line and the Windows job's
summary line from the latest run, and says which entries of S1's list
it closed. A row that needs a CI run stops with `needs-ci`; the lead
pushes its branch and resumes it with the result.

| Row | Brief | Audit (`AUDIT.md`) | Code (grep, then ranges) |
|---|---|---|---|
| R14-S1 | `:67-106` | PF-32 `:604-618`, PF-33 `:619-627` | `.github/workflows/ci.yml` (3 K) · `tests/conftest.py` · `pyproject.toml` `[tool.mypy]` |
| R14-S2 | `:107-151` | PF-10 `:253-274`, PF-11 `:275-304`, PF-34 `:628-637` | `soulseek/docker_setup.py` (17 KB) · `soulseek/sharing_service.py` (32 KB) · `audio/fingerprint.py` · `ui/workers.py` · `tests/conftest.py` (docker guard) |
| R14-S3 | `:152-183` | PF-11, PF-12 `:305-318` | `main.py` · `cli.py` (46 KB) · `files/atomic.py` · every `open(`/`read_text`/`write_text` |
| R14-S4 | `:184-214` | PF-09 `:234-252`, PF-15 `:360-373` | `soulseek/docker_setup.py:20-80` · `application.py:125-140` |
| R14-S5 | `:215-246` | PF-13 `:321-340`, PF-14 `:341-359` | `soulseek/sharing_service.py` · `ui/pages/sharing_page.py` |
| R14-S6 | `:247-286` | PF-24–PF-27 `:499-546`, PF-31 `:590-601` | `ui/tray.py` (26 KB) · `ui/main_window.py` (grep only) · `src/seeker/ui/CLAUDE.md` · `tools/screenshots.py` |
| R14-S7 | `:287-320` | PF-23 `:484-498` | `main_ui.py` · `ui/main_window.py` (grep) · `src/seeker/ui/CLAUDE.md` (quit seam) |
| R14-S8 | `:321-350` | PF-28 `:547-560` | `login_item.py` · the Settings page (grep `login`) |
| R14-S9 | `:351-386` | PF-18–PF-22 `:408-423`, `:426-481` | `files/atomic.py` · `files/sanitize.py` · `files/placement.py` · `soulseek/placement.py` |
| R14-S10 | `:387-414` | PF-29 `:561-576` | `packaging/seeker.spec` · `packaging/bundle_info.py` · `audio/fingerprint.py` (grep `_candidate_search_dirs`) · `packaging/build_chromaprint.sh` · `docs/packaging.md` |
| R14-S11 | `:415-457` | PF-35 `:638-647`, PF-36 `:648-664` | `.github/workflows/build.yml` · `packaging/build_windows_installer.py` · `packaging/seeker.iss` · `packaging/build_dmg.py` |
| R14-S12 | `:458-475` | PF-32, PF-22 | S1's failure list, numbered by cause (HISTORY §268) |

R14-S10 adds a native library to the bundle: its source is pinned and
checksummed like `build_chromaprint.sh`, its licence texts land in
`licenses/`, and `docs/packaging.md` → Native libraries gains its row.
R14-S11's uninstaller removes the install folder only, never the user's
data folders (the reason for `user-data`).
R14-S2 also owns isolating platformdirs in tests (its BRIEF step 5;
HISTORY §268, R14-S1's review): a `tests/conftest.py` fixture sets
`WIN_PD_OVERRIDE_LOCAL_APPDATA` to a tmp path, and the probe on
`check-windows` is its failing test. Until it is on main,
`test_lazy_spotify_config`'s `Application()` subprocesses would open a
Windows machine's real `%LOCALAPPDATA%\Seeker`; round 15 runs no suite
before it lands.

### R15-S0 — round 15 as an autodev plan

`round-15/BRIEF.md` → §S0 (`:119-125`): read round 14's HISTORY
entries and §0.7; rewrite the brief's rows S1–S6 to what is left; then
write round 15's plan in this file's shape (`round-15/SESSION-PLAN.md`
and a `round-15/tasks.json` that `autodev.py validate` accepts) for a
lead on the Windows PC. Documents only. Kris's gate after: the machine
(x64, Windows 11 version), its owner, the test accounts, the dates.

---

## Session protocol

Workers follow the skill's `agents/worker.md`; reviewers
`agents/reviewer.md`; integrators `agents/integrator.md`. This section
is what those files defer to.

**Environment.** A worktree shares no environment: `uv sync --locked`
in it; an x86_64 row creates its own `.venv-x86_64` there with
`CLAUDE.md` → Commands. Never use the main checkout's environments
from a worktree. Real data is read-only (`CLAUDE.md`; BRIEF §0.5 under
Rosetta).

**The check** (summary lines only; a pipe never hides a gate's exit
code, so redirect to a file and read its tail):

```
QT_QPA_PLATFORM=offscreen uv run pytest -q
uv run mypy --strict src/
uv run ruff check src tests tools
```

From R14-S1 on, also `uv run mypy --strict --platform win32 src/`
(gating from the row that makes it clean). A row that changes `src/`,
`pyproject.toml` or `uv.lock` adds the x86_64 suite:
`QT_QPA_PLATFORM=offscreen .venv-x86_64/bin/python -m pytest -q`
(slow under Rosetta; run it in the background). A full suite goes to
`suite-runner` where the caller can spawn one.

**The tracked number.** The baseline is the offscreen count H1
records (Cocoa's was `2574 passed, 1 skipped`). Quote pytest's summary
line and name every failing test, every time; a changed count is a
regression to diagnose, never a new baseline.

**Working.** `CLAUDE.md`'s rules first. A behaviour change starts with
a test that fails on unmodified main for the stated reason; one commit
per change; stage by explicit path, never `git add -A`/`.`. Read by
range. Never push, tag, touch GitHub, run Docker, or start a GUI
(Headless, above).

**Ending (the integrator).**

1. The HISTORY entry from the worker's draft, under the next free
   number (§266 on), in `docs/history/241-270.md` under
   `<a name="N"></a>` and `### N — <title> (<row id>)`; from §271, a
   new file `docs/history/271-300.md`, and its range in
   `docs/history/README.md`'s file list. Its one line (≤ 160
   characters) in `docs/history/README.md`.
2. Standing facts into `CLAUDE.md` or the topic file the report names,
   linked to the entry.
3. `tasks.json` through `autodev.py set` only, with `history`,
   `commits` and `actual_peak_k`.
4. `docs/HANDOFF.md` overwritten: nine fields, ≤ ~2 K tokens, pointing
   at this plan.
5. The check on main, as above; quote it in the close-out commit
   message ("<row> close-out (HISTORY §N)").

---

## Waiting on Kris

Asked up front and answered: Kris's decisions above.

- **After R13-S9b:** BRIEF §9's checklist with the Intel image, in the
  test account (`ACCEPTANCE.md` says how). The run's one long wait.
- **Before R13-S10:** the exact push and release commands, and the
  notes.
- **After R13-S10b:** the browser download and first launch, the
  update check in both apps, the website's Download buttons.
- **After R15-S0:** the Windows machine, its owner, the test accounts,
  the dates.
- Anything a worker reports as `needs-kris` or `needs-physical`.

## Exit criteria

This run's: every row `done`; CI green on the final head (`check`,
`check-intel`, `check-windows` blocking, `audit`); v0.2.0 published
with four assets; round 14's exit criteria
(`round-14/SESSION-PLAN.md` → Exit criteria); round 15's autodev plan
validated. The phase's (`../README.md` → Exit criteria) are measured at
round 15's close.

## Estimate notes

- **Baseline.** Top-level sessions: 51 K median (`tokens.py measure
  --last 8`, 2026-11-03), so the lead compacts at 180 K by the
  launcher. A worker's own baseline ~18 K (round 13 S1d's report), so
  a worker row of ≤ 65 K work peaks near 85 K.
- **Round 14's estimates** are its plan's peaks minus that plan's
  57 K baseline; nothing in them was re-measured.
- **Calibration:** round 13's top-level sessions ran a median ~104 K
  of work. Workers report USAGE; if three rows run > 25 % over, the
  lead re-estimates the rest and says so in the handoff.
- **Waiting is not tokens:** Rosetta suites and builds, and CI runs of
  20–45 minutes (`check-intel` ~20 min), cost wall-clock time.

# Round 13 — Intel Macs, released as v0.2.0

**Author:** phase-02 planning, 2026-10-17; re-planned into smaller
rows on 2026-11-02. **Executor:** Claude Code.
**Base commit:** `e470d1c` (v0.1.1, a security release, 2026-10-26;
the planning documents were committed with the re-plan). **Session
map:** `docs/phase-02/round-13/SESSION-PLAN.md`, status in
`tasks.json` beside it.
**Phase:** `docs/phase-02/README.md`. **Findings:**
`docs/phase-02/AUDIT.md` (`PF-NN`).

Seeker runs on Apple silicon only. This round makes it install, test,
build and release for Intel Macs as well, using the M4 Pro under
Rosetta 2 and GitHub's Intel runner, and publishes v0.2.0 with two
disk images: `Seeker.dmg` (Apple silicon, as before) and
`Seeker-Intel.dmg`.

Read your row in the session map, then **only** §0 and the section
your row points at, plus each `PF-NN` that section names
(`grep -n "PF-NN" docs/phase-02/AUDIT.md`, then read that finding).
Line numbers are hints from `2b7e8d9`: `grep -n` the named symbol
before trusting one. Each section separates what is **established**
(read, run or measured during planning, with the evidence) from what
is a **hypothesis** (yours to confirm or rule out first).

---

## §0 — Ground rules

**§0.1 Phase 01's rules apply unchanged.** R11 §0.1–§0.10: read
discipline, approval gates, one commit per numbered item, a failing
test first, the three numbers, a HISTORY entry for every row,
real-data safety, verification gates as hard stops, no history
archaeology in comments, scratch work outside the repository. Read
them once at the start of your row:
`sed -n 19,83p docs/phase-01/round-11/BRIEF.md`. R12 §0.13 too:
every visual change gets before and after screenshots from
`uv run python tools/screenshots.py`, named in the HISTORY entry.

**§0.2 Kris's answers (2026-10-17)** are in
`docs/phase-02/README.md` → "Kris's decisions". Intel ships first, as
v0.2.0; no signing; rounds number on from 13. Do not ask again.

**§0.3 HISTORY continues at §246**, appended to
`docs/history/241-270.md`, with its line in `docs/history/README.md`.

**§0.4 Platform rules, for all of phase 02.**
- **Apple silicon never regresses.** Every row ends with the three
  numbers from the native environment, exactly as in phase 01.
- **A platform branch tests `sys.platform`** (`"darwin"`, `"win32"`),
  never `os.name` or `platform.system()`: it is this codebase's idiom
  and the form mypy narrows on. An architecture is
  `platform.machine()` (`"arm64"`, `"x86_64"`; Windows says
  `"AMD64"`).
- **A test of another platform's branch patches that module's
  `sys.platform`** (precedent: `tests/pages/test_static_pages.py:74-83`)
  and fails on unmodified `HEAD` for the stated reason, as every fix
  test does.
- **A platform claim cites an observation or says UNVERIFIED**
  (working agreement 4). What Rosetta shows is an observation about
  Rosetta, not about an Intel Mac; say which one you saw.
- **A new module joins `docs/architecture.md` → Module map**, and
  `tests/test_layering.py`'s rules hold: Qt only in `ui/` and
  `main_ui.py`.

**§0.5 Real data under Rosetta.** The x86_64 environment (§3) reads
and writes the same per-user folders as the native one
(`~/Library/Application Support/Seeker`, `~/Library/Logs/Seeker`).
Never run `seeker`, `seeker-ui` or a built app from it against them.
The smoke test (§5) touches no data. Anything else that must start
the app sets `HOME` to a folder in your scratchpad first, and proves
it with a printed `platformdirs.user_data_dir("Seeker",
appauthor=False)` before going further (platformdirs builds macOS
paths from `~`, read in its source; confirm by that print).

**§0.6 The x86_64 environment** exists from S3 on, beside `.venv`:

```
.venv-x86_64/bin/python -c "import platform; print(platform.machine())"   # x86_64
QT_QPA_PLATFORM=offscreen .venv-x86_64/bin/python -m pytest -q
```

S3 records the exact commands that create it in `CLAUDE.md` →
Commands. ruff and mypy are architecture-independent and keep
running natively.

**§0.7 Release assets.** `Seeker.dmg` stays the Apple silicon image,
the name v0.1.0 used, so existing links keep working.
`Seeker-Intel.dmg` is the Intel image. Each has a `.sha256` beside it.

---

## §1 — Commit the phase-02 documents; Help → Build names the architecture (S1)

### §1.1 The documents (one commit)

**Established.** Planning left these uncommitted on `2b7e8d9`:
- `git mv docs/rounds/round-NN docs/phase-01/round-NN` for rounds
  01–12, already staged (22 renames);
- new: `docs/rounds/README.md` (a stub mapping the old paths),
  `docs/phase-01/README.md`, `docs/phase-02/README.md`,
  `docs/phase-02/AUDIT.md`, and `BRIEF.md` plus `SESSION-PLAN.md` in
  each of `docs/phase-02/round-13/`, `round-14/` and `round-15/`;
- edited: `docs/README.md`, `docs/HANDOFF.md`, `docs/packaging.md`
  (a path, and a pointer to phase 02), `CLAUDE.md` (two paths and
  the Roadmap).

HISTORY entries and the archived round documents keep the paths that
were true when written; the stub resolves them.

**Done at the re-plan (2026-11-02):** the steps below ran before the
planning commit. Row S1 executes §1.2 only.

**Do.**
1. Check every relative Markdown link in the live documents resolves:
   `README.md`, `CLAUDE.md`, `RELEASING.md`, `docs/*.md`,
   `docs/phase-0*/README.md`, `docs/phase-02/**/*.md`,
   `src/seeker/ui/CLAUDE.md`. A throwaway script in your scratchpad
   is enough; paste its count of links checked and broken (expect 0
   broken).
2. Change the one source comment that names an old path,
   `tests/test_stress_e2e.py:921` (`docs/rounds/round-10/BRIEF.md` →
   `docs/phase-01/round-10/BRIEF.md`). A comment only.
3. Commit all of it as the round's first commit.

### §1.2 Help → Build names the architecture (PF-05)

**Established.** `_build_info.py:19-37` holds the SHA, `git describe`
and the build time; `ui/dialogs.py:96-97` (About) and
`ui/pages/static_pages.py` (Help) show them. Nothing names the
architecture. `sysctl -n sysctl.proc_translated` printed `0` from a
native process on 2026-10-17; under Rosetta it is `1` (Apple's
documented key; UNVERIFIED here until this row runs it under
`arch -x86_64`).

**Do (a failing test first).** A Qt-free function returns what Help
and About show: "Apple silicon", "Intel", or "Intel build on Apple
silicon (Rosetta)" with one sentence pointing at the Apple silicon
download. Detect translation without a subprocess (`ctypes` and
`sysctlbyname`, or whatever the row finds simplest and testable),
defaulting to "not translated" on any failure. Windows and Linux get
`platform.machine()` as is, for now. Tests patch the function's
inputs; screenshots of Help → Build before and after (§0.1).

**Split point:** after the Qt-free function and its tests, before
Help and About show it.

---

## §1b — The Dependabot backlog (S1b) **[ASK] for each merge**

**Established (2026-10-17, `gh pr list`; refreshed 2026-11-02).**
Eight Dependabot PRs are open:

| PR | Bump | Checks then |
|---|---|---|
| #1 | `actions/checkout` 5.1.0 → 7.0.1 | one failure |
| #5 | mypy 2.3.1 → 2.4.0 | green |
| #6 | `uv_build` requirement → `>=0.12.23,<0.13.0` | one failure |
| #7 | ruff 0.16.9 → 0.16.10 | green |
| #8 | platformdirs 4.11.4 → 4.12.3 | green |
| #9 | python-dotenv 1.2.3 → 1.2.4 | green |
| #12 | `astral-sh/setup-uv` 7.6.0 → 10.3.2 (replaced #10 on 2026-10-28) | not yet read |
| #13 | slskd 0.26.0 → 0.26.2, Compose template (replaced #11) | not yet read |

#11's diff (#13 replaced it) changes the tag and the digest together, which settles the
open question in `.github/dependabot.yml`'s comment. S2 rewrites
`uv.lock`, and S4 and S7 copy `ci.yml`'s pinned actions, so this
backlog goes first: otherwise each PR conflicts with this round's
lock, and the new jobs copy pins that are about to change.

**Two rows.** **S1b** settles the Python packages (#5, #7, #8, #9)
and first records v0.1.1, which has no HISTORY entry: `e4ff751`
bumped certifi and setuptools for two advisories the weekly audit
caught (run `40326963931`), `e470d1c` released it, CI `40348515619`
green. Its entry and the Roadmap line go wherever S0 left the
Roadmap. platformdirs (#8) must not move the real data or log folder
(`user_data_dir`, `user_log_dir`): read its changelog for path
changes. **S1c** settles the actions, the build backend and slskd
(#1, #6, #12, #13) and step 4's comment.

**Do.**
1. For each PR, read its diff, its current checks and the upstream
   release notes for anything that changes Seeker's behaviour: the two
   major action bumps (checkout 5 → 7, setup-uv 7 → 10), and slskd
   0.26.1 against HISTORY §238's enqueue limit and §204's cancel
   semantics. Diagnose #1's and #6's failures.
2. Show Kris one line per PR (merge, merge after a fix, or close, and
   why). Merge only what he approves: a merge is an outward action.
3. A PR that needs a code change (a new mypy or ruff finding, say)
   gets it in its own commit, with the failing check as its failing
   test.
4. `.github/dependabot.yml`: the comment now records the observation
   (#11, then #13), not "UNVERIFIED". A template bump still reaches new installs
   only (HISTORY §140, §222).

**Done when:** each of the eight is merged or closed with a reason;
`main`'s CI is green after the last merge; `uv sync --locked` passes.

**Split points:** in the session map (S1b, S1c).

---

## §1d — Spotify Premium in the README and the wizard (S1d)

**Established.** Since early 2026 Spotify's developer pages have said
that Development Mode use requires a Spotify Premium account, and
allowed one Development Mode Client ID per developer (read 2026-10-30;
not re-read since). Every Seeker user creates
their own Spotify app (`README.md:68`), so the rule applies to every
user. Neither `README.md` → Install nor the wizard's Spotify step
(`ui/wizard.py:194`) says so. The README's `wizard.png` is that step
(`tools/screenshots.py:706`, `README_WIZARD`).

**Hypothesis.** The rule's exact wording and scope (the app's owner,
or every account the app admits). Read Spotify's own page first and
cite its URL and the date. If the rule changed, stop and report.

**Do (a failing test first).**
1. The wizard's Spotify step says, in one sentence beside the Client
   ID instructions, that a Premium account is needed;
   `tests/test_wizard.py` asserts it.
2. `README.md` → Install names it beside the Spotify app.
3. `CHANGELOG.md` → `[Unreleased]`.
4. Screenshots of the wizard's Spotify step before and after (§0.1);
   the README's `wizard.png` regenerated.

Not the website: that is Kris's.

**Split point:** after step 1.

---

## §2 — The Intel dependency set (S2, PF-01)

**Established (planning, 2026-10-17).**
- numba 0.62.1 and llvmlite 0.45.1 are the last releases with Intel
  macOS wheels; numba 0.62.1 needs `numpy>=1.22,<2.4` and
  `llvmlite>=0.45.0dev0,<0.46`.
- Seeker's `numpy>=2.5.2` floor has no reason beyond being current
  when it was declared (`b4dc1d2`).
- librosa 1.0.0, scipy 1.18.1, scikit-learn 1.9.1, soxr 1.1.0,
  soundfile 0.14.0 and pyloudnorm 0.2.0 all accept numpy 2.3.
- Every other locked binary package has an Intel macOS wheel.
- `uv` is 0.12.5 here.

**Hypotheses (check before building on them).**
- H1. Marker-scoped `constraint-dependencies` make uv's universal lock
  fork: numba, llvmlite and numpy each gain a second entry for
  `sys_platform == 'darwin' and platform_machine == 'x86_64'`, and
  every other environment keeps today's versions. uv's resolution
  docs say a universal lock may list one package at several versions
  for different platforms; they do not describe constraints with
  markers. Confirm with `uv lock` and the diff.
- H2. `required-environments` makes `uv lock` backtrack or fail when
  a listed environment has no wheel, per uv's docs ("often requires
  backtracking past the latest published versions"). Confirm by
  experiment: what does `uv lock` do with the Intel environment
  required and the numba constraint removed? Record the answer: it
  decides whether §2's test (step 4) is a second guard or the only
  one.

**Do.**
1. In `pyproject.toml`: lower numpy's floor to `>=2.3`; add
   `[tool.uv]` with `constraint-dependencies` (`numba<0.63`,
   `llvmlite<0.46`, `numpy<2.4`, each with the Intel marker) and
   `required-environments` naming `darwin`/`arm64`,
   `darwin`/`x86_64` and `win32`/`AMD64`. A comment says why, citing
   this row's HISTORY entry, and that the pins are permanent (numba
   publishes no Intel macOS wheels any more).
2. `uv lock`. Paste the `git diff --stat uv.lock` and show that no
   package's native version changed:
   `uv export --frozen --no-hashes --all-groups` filtered to the
   native environment, before and after, diffs empty (or an
   equivalent check you can paste).
3. `uv sync --locked`; the three numbers natively, unchanged.
   `uv run --no-project --python 3.13 tools/audit_dependencies.py`
   passes over the new pins (pip-audit must cover numba 0.62.1,
   llvmlite 0.45.1 and the numpy 2.3 release).
4. A test (`tests/test_lock_platforms.py`) reads `uv.lock` with
   `tomllib` and fails, naming the package and the platform, when a
   package that ships only wheels (or wheels plus an sdist that would
   need compiling) has no cp313 or abi3 wheel for one of the three
   environments. Pure-Python (`py3-none-any`) packages pass. Model
   the marker handling on the lock's `resolution-markers`.

**Done when:** `uv lock --check` passes; the native package set is
unchanged; the new test passes and fails when you delete an Intel
numba wheel from a scratch copy of the lock (paste both runs);
`tools/audit_dependencies.py` passes; CI green.

**Stop and report if** uv can't express marker-scoped pins (the lock
fails, or every platform moves to numba 0.62.1). Do not fall back to
a global downgrade; that is Kris's call (phase README → planning
decisions).

**Split point:** after step 3 (the lock), before the test.

---

## §3 — The x86_64 environment under Rosetta; the suite on Intel (S3)

**Established.** Rosetta 2 is installed on the M4 Pro: `arch -x86_64`
runs python.org's universal2 Python 3.13.5 as `x86_64` (observed
2026-10-17). Kris's Homebrew is the Apple silicon one
(`/opt/homebrew`); an x86_64 process cannot load its arm64
`libchromaprint`, though it can run its `ffmpeg` (a separate process).
`.gitignore` covers `.venv/` but not `.venv-x86_64/`.

**Hypotheses.**
- H1. `uv python install` accepts an x86_64 request on Apple silicon
  (`cpython-3.13-macos-x86_64-none`; the exact spelling is
  UNVERIFIED), and `UV_PROJECT_ENVIRONMENT=.venv-x86_64 uv sync
  --locked --python <that interpreter>` installs the x86_64 wheels
  from the universal lock.
- H2. numba's JIT runs under Rosetta. If LLVM picks a host feature
  Rosetta lacks (it translates AVX2 since macOS 15, not AVX-512, per
  secondary sources), a test dies with `SIGILL`. Then
  `NUMBA_CPU_NAME=generic` for the Rosetta run only, recorded; never
  in the app.

**Do.**
1. Create the environment; paste `platform.machine()`,
   `numba.__version__`, `numpy.__version__` from it.
2. Ignore `.venv-x86_64/` (one line in `.gitignore`).
3. Run the whole suite in it, offscreen (§0.6). Paste the summary
   line and the duration beside the native run's duration.
4. Triage every failure into: (a) an Intel bug (a failing test, then
   the fix, one commit each); (b) this machine's environment (arm64
   Homebrew's chromaprint, say), which a skip may cover only if its
   condition cannot hide an Intel bug (working agreement 5), and
   which the Intel runner (§4) then still exercises; (c) a test that
   assumes Apple silicon (fix the test). The list and each verdict go
   in the HISTORY entry.
5. Time `analyze_audio` on one sample twice in the x86_64
   environment (cold, then warm) and natively; record them as
   Rosetta's numbers, not Intel's.
6. Write the commands that create and use the environment into
   `CLAUDE.md` → Commands, and a standing fact (with this row's
   §) under a new "Platforms" heading: the Intel pins, the
   environment, and that it shares the real data folders (§0.5).

**Split point:** after step 3, with the failure list in the HISTORY
entry.

---

## §4 — CI on Intel (S4, PF-03)

**Established.** `ci.yml`'s `check` job runs on `macos-26` with a
30-minute timeout; actions are SHA-pinned with a version comment; the
runner label is pinned to a concrete image on purpose (its own
comment). `macos-15-intel` is GitHub's last Intel macOS image, retired
in fall 2027.

**Do.** A second job, `check-intel`, on `macos-15-intel`:
`brew install chromaprint` (Intel Homebrew, `/usr/local`),
`uv sync --locked --all-extras --dev`, and the suite offscreen. ruff
and mypy stay in `check` only (they don't depend on the
architecture). Coverage stays gated on `check` alone; the Intel job
runs `pytest -q`. Set its timeout from a measured run (start at 45
minutes). Add a comment saying when the image retires and what then
(Intel tested under Rosetta only). Make the job blocking from its
first green run.

**Done when:** one CI run shows `check`, `check-intel` and `audit`
green; its id and both durations are in the HISTORY entry.

**Stop and report if** the Intel job fails on something §3 did not
see under Rosetta: that is the most valuable thing this row can find.
Record it, fix it in its own commit with a failing test, or stop at
the split point if it is large.

**Split point:** none (one cohesive change).

---

## §5 — A smoke test for frozen builds (S5, PF-06)

**Established.** No test or tool runs a frozen build. `seeker.spec`'s
`hiddenimports` (`AppKit`, `Foundation`, `objc`, `ServiceManagement`)
and `datas` (the Compose template, `icons/`, `fonts/`, licences) are
kept by hand. A one-folder build keeps numba's cache in the bundle
(HISTORY §30).

**Do (a failing test first).**
1. `seeker-ui --smoke-test` runs a check and exits, before any
   logging, `Application`, database or real folder is touched:
   - imports every module of the `seeker` package (UNVERIFIED that
     `pkgutil.walk_packages` sees modules inside PyInstaller's
     archive; if not, the spec writes the module list into the
     bundle at build time and the check reads it);
   - creates a `QApplication` on the offscreen platform, applies the
     light and the dark theme, and checks the bundled fonts, icons and
     Compose template resolve;
   - writes a synthetic 120 BPM click track (about 10 s) to a
     temporary WAV, runs `analyze_audio` twice, checks the tempo is
     within 2 BPM, and reports both durations (cold and warm JIT);
   - reports whether libchromaprint loads (informational: it is
     optional);
   - prints one JSON report, and also writes it to the file named
     after the flag (`--smoke-test report.json`), because a windowed
     Windows build has no console (round 14 §11); then exits 0, or 1
     naming the failed check.
   The code lives in `ui/` (it needs Qt); `main_ui.main()` only
   dispatches to it.
2. A test runs the mode in-process (unfrozen) and asserts the report.
3. Build the Apple silicon app (`uv run python packaging/build_dmg.py`)
   and run `dist/Seeker.app/Contents/MacOS/Seeker --smoke-test`. Paste
   the report. The build deletes its generated identity module
   afterwards; `git status` stays clean.

**Done when:** the unfrozen test passes; the frozen arm64 app's report
says every check passed; both JIT timings are in the HISTORY entry.

**Stop and report if** the frozen app fails a check: that is a real
packaging bug in v0.1.0's build. Fix it in its own commit (a failing
check first) before going on.

**Split point:** after step 2 (the mode passes unfrozen).

---

## §6 — The Intel app (S6, PF-02, PF-04)

**Established.** `seeker.spec:142` `target_arch=None`.
`build_dmg.py:21-22` names `dist/Seeker.app` and `dist/Seeker.dmg` and
runs PyInstaller as `sys.executable -m PyInstaller`, so running it
from `.venv-x86_64` builds with the x86_64 interpreter.
PySide6's wheels are universal2; numpy, scipy, numba and llvmlite are
thin. `bundle_info.MINIMUM_SYSTEM_VERSION` is `"15.0"`, measured
for arm64 in HISTORY §214; PySide6's x86_64 slices say 15.0 too
(planning's `otool`).

**Hypotheses.**
- H1. With `target_arch` explicit, PyInstaller thins universal2
  binaries to that architecture, so the Apple silicon bundle shrinks
  (it carries PySide6's x86_64 halves today: UNVERIFIED). Measure
  `du -sh dist/Seeker.app` before and after.
- H2. The x86_64 bootloader comes out thin. A fat bootloader over
  x86_64-only libraries would start its arm64 half on Apple silicon
  and fail.

**Do, one commit each.**
1. `seeker.spec`: `target_arch` set from the building interpreter
   (`platform.machine()`), so each build is one architecture
   explicitly. Measure both bundles' sizes.
2. `build_dmg.py`: the image's name from the architecture
   (`Seeker.dmg` for arm64, `Seeker-Intel.dmg` for x86_64), and a
   post-build check that fails the build when any Mach-O in the
   bundle lacks the target architecture or the main executable is not
   thin (`lipo -archs`), or when any binary's `minos` exceeds
   `MINIMUM_SYSTEM_VERSION` (`otool -l`). That turns HISTORY §214's
   one-off measurement into a check every build runs.
3. Build the Intel app from `.venv-x86_64`; run the smoke test on it
   (`arch -x86_64 dist/Seeker.app/Contents/MacOS/Seeker
   --smoke-test`); record the cold and warm analysis times under
   Rosetta.
4. If `bundle_info.license_datas()` refuses an Intel-only version
   (a wheel with no licence text), vendor its text as §215 did.

**Done when:** both builds pass the post-build check and the smoke
test; the HISTORY entry has both sizes, both reports and the Rosetta
timings; `git status` is clean after each build.

**Split point:** after step 3 (the Intel app builds and passes the
smoke test), before any naming polish.

---

## §7 — CI builds both apps and smoke-tests them (S7)

**Why.** The Intel runner is the only real x86_64 hardware in reach.
A frozen app smoke-tested there is the closest thing to an Intel Mac
launching it, and it catches a dependency bump that breaks the frozen
app (a Dependabot PR, say) before a release does.

**Do.** A workflow, `build.yml`, with a matrix over `macos-26` and
`macos-15-intel`: `uv sync --locked`, `packaging/build_dmg.py`, the
smoke test on the built app, the DMG uploaded as an artifact (short
retention). It runs on `workflow_dispatch`, on tags, and on pushes
that change `pyproject.toml`, `uv.lock` or `packaging/**`. It never
publishes a release; `RELEASING.md` keeps building release assets
locally. Same pinning rules as `ci.yml`.

**Done when:** a dispatched run is green on both runners and both
smoke reports are in the HISTORY entry, with the Intel runner's cold
and warm analysis times: the first numbers from real Intel hardware.

**Split point:** none.

---

## §8 — Documents for two Macs (S8, PF-04, PF-07)

**Do.**
- `README.md` → Install: which image for which Mac (Apple menu →
  About This Mac → Chip or Processor); the floor, "macOS 15 or later",
  for both; Intel Macs that can't run macOS 15 can't run Seeker.
  S1d's Spotify Premium line stays.
- `docs/packaging.md`: the platform table's Intel row (what was
  verified, where, when), the x86_64 build, the post-build check, the
  smoke test, the Native libraries table for both dependency sets.
- `RELEASING.md`: build both (native, then Rosetta), check both,
  checksum both, upload four files, notes naming both images; the
  rule for Intel's end (phase README → "The clock").
- `packaging/Read Me First.txt`: unchanged unless the Intel image
  needs a different first launch (it shouldn't; check).
- `CHANGELOG.md` → `[Unreleased]`: the Intel build, the smoke test,
  Help → Build's architecture line.
- `CLAUDE.md`: Packaging facts for both architectures and the asset
  names; `docs/architecture.md` → Module map for any new module.

**Done when:** every link resolves (§1.1's script); a person with an
Intel Mac can pick the right image from the README alone.

---

## §9 — Release-candidate acceptance (S9) — Kris and Code

**Code's half.** Both candidates built untagged from the same commit
(§6's two builds); `RELEASING.md` step 3 for each (codesign, `spctl`
rejects, `Info.plist` version, clean tree); the smoke test for each;
checksums. Write `docs/phase-02/round-13/ACCEPTANCE.md`: the
candidates' SHA-256s, then Kris's checklist.

**Kris's half, in the test account on the M4 Pro**, with the Intel
image (it runs under Rosetta): download it in a browser, first launch
through Privacy & Security → Open Anyway, the wizard (a test Spotify
account), a scan of a test folder, BPM and key on a few files beside
the Apple silicon app's values, Duplicates (fingerprinting will say
chromaprint is missing: expected under Rosetta with an Apple silicon
Homebrew), the tray, quit with a task running, Help → Build saying
"Intel build on Apple silicon (Rosetta)".

**No slskd bring-up in the test account:** the container name
`slskd` is global to this Mac's Docker, so a bring-up there recreates
Kris's real container. slskd's REST and `docker` calls do not depend
on the app's architecture.

**On a real Intel Mac, if Kris finds one:** the same list, plus Intel
Homebrew's chromaprint and ffmpeg, and a slskd bring-up with a test
Soulseek account (one login per username: Kris's own would kick his
Mac's session off).

---

## §10 — Publish v0.2.0; close round 13 (S10)

`RELEASING.md` end to end, for both images; Kris approves each
outward step (the exact `git tag`, `git push`, `gh release create`
commands and the notes, shown first). Then: the four assets download
and pass `shasum -c`; Help → "Check for updates…" says up to date
in both apps. Measure the round's exit criteria
(`SESSION-PLAN.md`), record them in the HISTORY entry, and update
`CLAUDE.md`'s Roadmap.

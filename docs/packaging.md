# Building Seeker

`seeker-ui` packages into a self-contained desktop app with
[PyInstaller](https://pyinstaller.org/): no Python or `uv` needed on the
machine that runs it. Docker is **not** bundled, and is not meant to
be. slskd still runs in a separate Docker install, which the onboarding
wizard detects and starts.

| Platform | Status |
|---|---|
| macOS 15+, Apple silicon | Built and verified on real hardware: the `.app`, the `.dmg`, and the app launched after being copied to `/Applications`. The frozen app also passes its own `--smoke-test` (2026-11-02, [HISTORY §257](history/241-270.md#257)). Image: `Seeker.dmg`. |
| macOS 15+, Intel (x86_64) | **Built, bundle-checked and smoke-tested on GitHub's Intel runner and under Rosetta 2; launched by a person only under Rosetta 2, never on an Intel Mac (UNVERIFIED there).** On 2026-11-02 `build.yml` built the app on `macos-15-intel`; its bundle check passed, and `--smoke-test` passed there with libchromaprint loading from the bundle ([Build run 41537431447](https://github.com/KristiyanDDimitrov/Seeker/actions/runs/41537431447), [HISTORY §262](history/241-270.md#262)). The test suite passed on the same runner ([HISTORY §261](history/241-270.md#261)). Under Rosetta 2 on Apple silicon the app built from an x86_64 interpreter and passed the same two checks ([HISTORY §260](history/241-270.md#260)). v0.2.0's image was launched and used in a test account under Rosetta 2 on an M4 Pro (2026-11-04, [HISTORY §271](history/271-300.md#271)). Image: `Seeker-Intel.dmg`. |
| Windows | **Written, never verified on real hardware.** `seeker.spec` is cross-platform and `packaging/seeker.iss` is a complete Inno Setup script, but neither has run on a Windows machine. |
| Linux | **Written, never verified on real hardware.** The same `seeker.spec`; no installer format (AppImage, `.deb`) is scoped. |

Treat the Windows and Linux rows as unverified until someone runs the
build on those platforms, and the Intel row as open until someone
launches the app on an Intel Mac: GitHub's runner and Rosetta cover the
suite, the build, the headless smoke test and a person using the app
under Rosetta, not Gatekeeper's first-launch block on an Intel Mac or
Docker Desktop for Intel. Both macOS images
need macOS 15, the highest `minos` among their binaries (the Info.plist
bullet below). Phase 02 ([`phase-02/README.md`](phase-02/README.md))
adds the Intel build in round 13 and verifies Windows in rounds 14 and
15; this table changes as each lands.

## The app

```
uv sync --group dev                     # pulls in PyInstaller and dmgbuild
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
```

Output lands in `dist/`: a one-folder build (`dist/Seeker/`) on every
platform, plus `dist/Seeker.app` on macOS.

- **Bundled resources:** `docker-compose.yml` (the template the wizard
  copies before starting slskd), `packaging/icons/` and
  `packaging/fonts/` (Barlow Semi Condensed, with its OFL licence).
  A frozen build finds them through `sys._MEIPASS`; `sys.frozen` gates
  every such lookup, and nothing else about a frozen run differs from
  `uv run seeker-ui`.
- **Licence texts:** `licenses/<distribution>/` in the bundle holds
  each runtime distribution's own texts from its `.dist-info`, plus
  Seeker's `LICENSE` and Python's. PySide6, shiboken6 and pyobjc-core
  ship none, so `packaging/licenses/` vendors theirs (GNU's LGPL-3.0
  and GPL-3.0 unedited, PyObjC's MIT text); a test pins their digests.
  `bundle_info.license_datas()` fails the build, and a test, for a
  dependency with no text and for a vendored entry whose wheel now
  carries its own. [HISTORY §215](history/211-240.md#215)
- **One folder, not one file, on purpose.** librosa's numba JIT cache
  persists across runs only in a one-folder build: about 1 s warm
  against 18–21 s on every launch of a one-file build, which
  re-extracts to a fresh temporary directory each time.
  [HISTORY §30](history/025-031.md#30)
- **Runtime dependencies only.** A built app contains no pytest, mypy
  or ruff files (checked in the bundle, not assumed).
- **Build identity.** `packaging/build_dmg.py` writes the gitignored
  `src/seeker/_build_info_generated.py` (the git SHA, `git describe`
  and the build time), which About and Help show, and deletes it once
  the build ends, failed or not. The tracked `_build_info.py` imports
  it only when frozen, falling back to `"dev"`; never write the
  tracked file. The wheel excludes it too.
  [HISTORY §83](history/072-107.md#83)
- **Info.plist** comes from `packaging/bundle_info.py`: the version is
  `pyproject.toml`'s, the copyright `LICENSE`'s line, the category
  Music, and the minimum macOS 15.0, the highest `minos` among the
  bundled binaries (PySide6's own, on both architectures). Every build
  checks it (`bundle_check`, below), so an upgrade that raises a
  `minos` fails the build instead of waiting for a re-measure.
  [HISTORY §214](history/211-240.md#214),
  [§259](history/241-270.md#259)

## The macOS `.dmg`

```
uv run python packaging/build_dmg.py
```

This runs the PyInstaller build, checks the bundle, then
[`dmgbuild`](https://dmgbuild.readthedocs.io/) with
`packaging/dmg_settings.py`, producing `dist/Seeker.dmg` on Apple
silicon and `dist/Seeker-Intel.dmg` on Intel (`bundle_check.dmg_name`).
The spec builds the interpreter's architecture on purpose
(`bundle_info.target_architecture()` as PyInstaller's `target_arch`).
The check, `bundle_check.check_bundle`, runs `lipo` and `otool` over
every Mach-O in the app: each must carry that architecture, the main
executable must be thin, and no `minos` may exceed
`MINIMUM_SYSTEM_VERSION`; a failure stops the build before `dmgbuild`.
The two steps can also run on their own (the DMG name below is the
Apple silicon one):

```
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
uv run dmgbuild -s packaging/dmg_settings.py -Dapp=dist/Seeker.app Seeker dist/Seeker.dmg
```

The volume holds the app, an `/Applications` link and
`Read Me First.txt`, in a sized window with no toolbar, sidebar or
status bar. The custom icon (`packaging/icons/seeker_icon.icns`) is set
on both the `.app` (`seeker.spec`'s `BUNDLE()`) and the volume
(`dmg_settings.py`), and was confirmed to render on both.
[HISTORY §31](history/025-031.md#31), [§42](history/032-046.md#42)

### The Intel app

An Intel Mac needs its own app. Its dependency set differs (numba
0.62.1, llvmlite 0.45.1 and numpy 2.3.5, the last Intel wheels; the lock
forks them, [HISTORY §253](history/241-270.md#253)) and a PyInstaller
app is one architecture. The spec builds the architecture of the
interpreter that runs it, so the Intel app comes from an x86_64
interpreter: on an Intel Mac the ordinary `uv run`, on an Apple silicon
Mac an x86_64 environment under Rosetta 2, beside `.venv`:

```
uv python install cpython-3.13.15-macos-x86_64-none
UV_PROJECT_ENVIRONMENT=.venv-x86_64 uv sync --locked --python cpython-3.13.15-macos-x86_64-none
packaging/build_chromaprint.sh "$PWD/.chromaprint"
SEEKER_CHROMAPRINT_DIR="$PWD/.chromaprint/lib" \
    .venv-x86_64/bin/python packaging/build_dmg.py      # dist/Seeker-Intel.dmg
```

That environment shares the real data folders, so it only builds: never
start the app from it ([CLAUDE.md](../CLAUDE.md#platforms)). The two
`.chromaprint` lines are for a Mac with no `/usr/local/lib`; on an Intel
Mac, or CI's Intel runner, `packaging/build_chromaprint.sh` with no
argument installs into `/usr/local/lib`, which is where
`SEEKER_CHROMAPRINT_DIR` defaults, so the folder and the variable can be
left out. The variable is read when the spec runs, so set it on the
build command itself, and give an absolute path: a relative one
resolves against PyInstaller's working directory, the repository root.
Do not put the library under `build/`: `build_dmg.py` runs PyInstaller
with `--clean`, which empties `build/` before the spec runs.
`.chromaprint/` is in `.gitignore` for this, so `RELEASING.md`'s clean
tree holds.

- **libchromaprint ships in the Intel app, not the Apple silicon one,
  and Seeker builds it.** `packaging/build_chromaprint.sh [PREFIX]`
  takes the upstream source tarball for chromaprint 1.6.2 (its `VERSION`,
  with the `SHA256` it checks), and builds x86_64 only, for a deployment
  target of 15.0 (the bundle's floor), with the vDSP FFT and without
  FFmpeg. It cross-compiles with Xcode's tools, so an Apple silicon Mac
  with no Intel Homebrew builds it. The result links Accelerate, libc++
  and libSystem alone (`otool -L` in the CI build, [Build run
  41537431447](https://github.com/KristiyanDDimitrov/Seeker/actions/runs/41537431447));
  the script fails on a dependency outside macOS's own folders, since one
  loads on the machine that built it and not on a user's Mac. It
  installs to `PREFIX/lib` (PREFIX defaults to `/usr/local`), creating
  that folder first and using `sudo` only when it can neither create nor
  write it, so a prefix inside the repository needs none; it builds in a
  temporary directory under `TMPDIR`, removed on exit, so the library is
  in the repository and the build scratch is not. Homebrew is not the
  source: it treats Intel Macs as Tier 3 since September 2026 and builds
  no new Intel bottles ([Homebrew's support
  tiers](https://docs.brew.sh/Support-Tiers), read 2026-11-03; its API
  lists none for `chromaprint` 1.6.2, `ffmpeg` or `mpg123`), so `brew
  install chromaprint` there compiles ffmpeg and ten more formulae for a
  library that needs none of them.
  `bundle_info.chromaprint_binaries` copies `libchromaprint.1.dylib`
  from `bundle_info.chromaprint_library_dir()` (`SEEKER_CHROMAPRINT_DIR`
  when set and not empty, else `/usr/local/lib`) to the bundle's resource
  root, which `audio/fingerprint.py` searches before the Homebrew
  prefixes, and the spec adds its licence texts (`packaging/licenses/`)
  under `licenses/chromaprint/`. A missing library fails the build, with
  these steps in the message, so the app never silently loses
  fingerprinting. The Apple silicon app still finds the user's own
  Homebrew copy.
- **Both architectures write `dist/Seeker.app`.** Each build replaces
  the last; the images are named apart (`Seeker.dmg`,
  `Seeker-Intel.dmg`) and both stay. Check one app before building the
  other architecture (RELEASING.md step 3).
- **ffmpeg is not bundled in either app.** `audio/fingerprint.py`
  decodes with soundfile and falls back to a Homebrew `ffmpeg` for a
  file libsndfile rejects. On Intel that is a Homebrew install of
  Tier 3 standing, so treat the fallback as best effort there.

### The smoke test

```
Seeker.app/Contents/MacOS/Seeker --smoke-test /absolute/path/report.json
```

`seeker-ui --smoke-test [REPORT]` (`ui/smoke_test.py`) is how a build
proves it can run, without a person launching it. It checks that the
bundle carries its identity (not `"dev"`), imports every module and the
macOS frameworks the spec bundles by hand, finds Qt's native platform
plugin, applies both themes, loads the bundled fonts, icons and Compose
template, and times two analyses of a generated click track (cold, then
warm; it reads back 123.05 BPM). It prints one JSON report, also
written to `REPORT`, and exits 0, or 1 naming what failed. It touches no
settings, database or library, so it is safe on any Mac. On an Apple
silicon Mac, prefix an Intel app with `arch -x86_64` (a real Intel Mac
runs it as it is). Give the first cold analysis a generous timeout:
numba compiles it (37 s under Rosetta, 23 s on GitHub's Intel runner).
The report's `architecture` is the text of the Architecture line on
Help's page, under its Build line (which holds the version and date);
under Rosetta it begins "Intel build on Apple silicon (Rosetta)".

`chromaprint_available` says whether fingerprinting loads, not which
copy loaded. `audio/fingerprint.py` looks in the bundle, then
`/opt/homebrew/lib`, then `/usr/local/lib`, so `true` proves the bundled
library only where no other copy can load there:

- **Intel app, built on an Apple silicon Mac with no Intel Homebrew**
  (the library built into `.chromaprint/`): no other x86_64
  copy is on the search path, and Homebrew's arm64 copy cannot load into
  an x86_64 process (observed under Rosetta,
  [HISTORY §258](history/241-270.md#258)), so `true` proves the bundled
  copy.
- **Intel app, built where an x86_64 copy is installed** (an Intel Mac
  with Homebrew's, or `packaging/build_chromaprint.sh` run with its
  default prefix, as CI's Intel job does): that copy answers the smoke
  test too. Move it aside for the run and put it back after; CI deletes
  it. `find dist/Seeker.app -name 'libchromaprint*'` lists the file the
  Intel bundle holds, whichever copy answers.
- **Apple silicon app:** `true` needs Homebrew's chromaprint on that Mac
  and says nothing about the bundle, which holds none.

None of this shows that the library loads after Gatekeeper's first launch
of a downloaded image: the smoke test runs the app from `dist/`.
[HISTORY §256](history/241-270.md#256), [§257](history/241-270.md#257)

### CI builds

`.github/workflows/build.yml` builds both apps on GitHub's runners,
`macos-26` for Apple silicon and `macos-15-intel` for Intel, with
`packaging/build_dmg.py`, runs `--smoke-test` on each built app, checks
the report (`passed`, `frozen`, `chromaprint_available` and the
architecture the app was built for) and uploads each image and report as
an artifact kept for a week. It runs on `workflow_dispatch`, on tags,
and on pushes that change `pyproject.toml`, `uv.lock`, `packaging/**` or
the workflow itself, so a dependency bump that breaks the frozen app
fails there rather than at a release. It never publishes a release:
`RELEASING.md` builds the release's images locally.

The Intel job builds libchromaprint first (`packaging/build_chromaprint.sh`,
into `/usr/local/lib`) and, before the smoke test, deletes
`/usr/local/lib/libchromaprint*`. `audio/fingerprint.py` searches the
bundle, then `/opt/homebrew/lib`, then `/usr/local/lib`, so with the
build machine's copy gone, a report that finds libchromaprint found the
bundled one. `ci.yml`'s `check-intel` builds the same library for the
suite, and Homebrew's `chromaprint` formula had pulled ffmpeg onto that
runner as a dependency; the source build does not, so the three tests
marked `requires_ffmpeg` skip there (one already skipped, for want of
the X9 drive, so `check-intel` skips 31 against 29) and run on the arm64
`check` job only.
[HISTORY §262](history/241-270.md#262)

### What was verified

On 2026-08-29 the real `.app` was launched with `open dist/Seeker.app`
against a real configuration, then a throwaway frozen build with the
same `Analysis` was driven under `QT_QPA_PLATFORM=offscreen` (Qt's
headless platform, so no Screen Recording or Accessibility permission
was needed). The wizard opened at its Spotify step, Connect built a
real PKCE authorization URL, Sync, Scan and Match completed against the
real library, "Set up later" finished onboarding without Docker, and
Settings showed the real configuration.

The `.dmg` was then mounted and the app copied to `/Applications`,
a different path from the build directory, and launched from there:
17 of 17 checks passed, including the one a `.dmg` puts at risk, that
`docker_setup.compose_file_path()` finds the bundled
`docker-compose.yml` relative to wherever the running binary lives.
The copies were removed afterwards.
[HISTORY §30](history/025-031.md#30), [§31](history/025-031.md#31)

**The Apple silicon app's smoke test** passed on the frozen app on
2026-11-02: cold analysis 3.7 s, warm 0.035 s, with libchromaprint
found.
[HISTORY §257](history/241-270.md#257)

**The Intel app** was built on 2026-11-02 from an x86_64 environment
under Rosetta 2 on an M4 Pro, in about 100 s, and was not launched as an
app. `bundle_check` passed first time: every Mach-O is x86_64, no
`minos` above 15.0, the main executable thin. `Seeker.app` was 333,304
KB (the Apple silicon one, 317,844 KB) and `Seeker-Intel.dmg` 123.2 MB.
`license_datas()` needed no vendored text. `arch -x86_64 Seeker
--smoke-test` exited 0: nine checks, 147 modules, 123.05 BPM, cold
analysis 37.5 s on the first launch and 1.53 s in a second process
(numba's cache persists on disk), warm 0.05 s. That is Rosetta, not an
Intel Mac. libchromaprint was not loadable in that build (the venv's is
arm64-only); the bundling above came after it. PyInstaller warned about
sklearn's `libomp.dylib` SDK version, Windows-only ctypes names and
three hidden imports it could not find (`pycparser.lextab`,
`pycparser.yacctab`, `scipy.special._cdflib`); none affected the run.
[HISTORY §260](history/241-270.md#260)

**CI built and smoke-tested both apps** on 2026-11-02 ([Build run
41537431447](https://github.com/KristiyanDDimitrov/Seeker/actions/runs/41537431447),
a push of the round's branch at `14d533e`). Apple silicon, on `macos-26`:
161 s for the job, 98 s of it the build; the bundle check passed ("every
Mach-O is arm64, minos <= 15.0"), the smoke test passed, cold analysis
6.62 s, warm 0.059 s, architecture "Apple silicon". Intel, on
`macos-15-intel`: 591 s for the job (setup-uv 60 s, libchromaprint 88 s,
the build 378 s, the smoke test 31 s); the bundle check passed over the
whole bundle, the staged dylib included ("every Mach-O is x86_64, minos
<= 15.0"); the smoke test passed with `chromaprint_available` true after
the job had deleted the build machine's `/usr/local/lib/libchromaprint*`,
so the library came from the bundle (an inference: the log does not name
the path); cold analysis 23.32 s, warm 0.257 s, architecture "Intel".
Those are the first analysis times from an Intel Mac's hardware; under
Rosetta the cold analysis took 37.5 s. The library's `otool -L` lists
`@rpath/libchromaprint.1.dylib` (its own id), libSystem.B, Accelerate and
libc++.1. PyInstaller warned, on Intel only, that
`sklearn/.dylibs/libomp.dylib` has an invalid macOS SDK version (a
warning, not a failure). This verifies the build and the headless smoke
test on GitHub's Intel runner, not an app launched by a person on a
user's Mac. A branch push triggered that run. A `workflow_dispatch` run
on `main` (`41547216451`, 2026-11-02 23:40 UTC) was green too: Intel
6 m 44 s, cold analysis 14.30 s, warm 0.297 s; Apple silicon 4 m 00 s,
cold 9.51 s, warm 0.084 s. The Intel runner's cold analysis ranged from
10.9 s to 23.3 s over four runs: quote no single figure.
[HISTORY §262](history/241-270.md#262)

**The Intel suite on real Intel hardware** ran on 2026-11-02 on
`macos-15-intel` (run `41506032138`): 2500 passed, 29 skipped in 19 min
34 s, about twice the Apple silicon job, with the 25 real-chromaprint
tests passing rather than skipping. The first Intel run found one wrong
test expectation: a real Intel Mac has no `sysctl.proc_translated` key,
which reads as not translated.
[HISTORY §261](history/241-270.md#261)

**The Intel app, launched by a person** on 2026-11-04: Kris installed
v0.2.0's `Seeker-Intel.dmg` (from the release folder, whose copy has
the published image's SHA-256) in a test account on an M4 Pro, so
under Rosetta 2, and ran part of round 13's checklist
(`phase-02/round-13/ACCEPTANCE.md` has which): "Analyze audio
(BPM/Key)" succeeded, which needs the wizard, sync and scan, with no
failure. The comparison with the Apple silicon app's BPM and key was
skipped.
[HISTORY §271](history/271-300.md#271)

**Not yet verified for Intel:** the app on an Intel Mac, so
Gatekeeper's first-launch block there (it is assumed to read as `Read
Me First.txt` says: UNVERIFIED), Docker Desktop for Intel, and analysis
speed on a real, older Intel Mac; and, anywhere, that the Intel app's
key and confidence, or its BPM for a real file, match the Apple silicon
app's. CI checks only a generated click track's BPM, within 2 of
123.05, on both architectures, in the suite and in each frozen app;
both apps found 123.046875 in the tag's Build run (observed in its
logs, not asserted).

### Signing and Gatekeeper

The build is **ad-hoc signed, not notarized**, which is not the same
as unsigned. PyInstaller ad-hoc-signs the executable and the bundle by
default: `codesign -dvvv` shows `Signature=adhoc`, and
`codesign --verify --deep --strict` passes. Gatekeeper still rejects
it (`spctl --assess`), as it does every non-notarized build. On macOS
15 and later Control-click → Open no longer overrides it: the first
launch on any other Mac is blocked, then allowed from System Settings
→ Privacy & Security → Open Anyway, or the quarantine attribute is
removed (`xattr -dr com.apple.quarantine`). `Read Me First.txt` on the
volume gives both. UNVERIFIED on a quarantined download until S17's
acceptance tries it on macOS 26.
[HISTORY §36](history/032-046.md#36), [§214](history/211-240.md#214)

The Intel app is signed the same way: PyInstaller's bundle step signs
with no architecture test (read in the locked PyInstaller's
`building/osx.py`, 2026-11-03), and the first launch is macOS's, not
the architecture's. Nobody has yet run `codesign -dvvv` on an Intel
app or opened a quarantined Intel download; RELEASING.md step 3 and
round 13's acceptance do (UNVERIFIED until then).

Notarization needs a paid Apple Developer account. The hooks for it
are marked in `packaging/seeker.spec`: `codesign_identity=` and
`entitlements_file=` on `EXE(...)`, followed by `xcrun notarytool` and
`stapler` on the built `.app`.

### Native libraries

CI's audit job (`tools/audit_dependencies.py`) runs pip-audit over
`uv.lock`. pip-audit reads Python package metadata, so it cannot see
the native code bundled inside wheels or the interpreter. Those
versions are recorded here instead. At each release, re-read them,
compare, and check each one that changed or has a new advisory
against its upstream security notes.

| Library | Apple silicon (2026-10-09) | Intel (2026-11-03) | Arrives with | Reads peer files? |
|---|---|---|---|---|
| libsndfile | 1.2.2 | 1.2.2 | soundfile 0.14.0's wheel (one per architecture) | yes: BPM, key, loudness |
| Qt | 6.11.2 | 6.11.2 | PySide6 6.11.2 (one universal2 wheel) | no |
| OpenSSL | 3.5.7 | 3.5.9 | the build's own Python 3.13.15 | no |
| SQLite | 3.53.1 | 3.53.1 | the build's own Python 3.13.15 | no |
| ffmpeg | 9.0.1 | the user's | Homebrew, not bundled in either app | yes: fingerprints |
| libchromaprint | 1.6.1 | 1.6.2 | Intel app: built from the pinned source by `packaging/build_chromaprint.sh` and staged by the spec; Apple silicon app: the user's Homebrew copy, not bundled | decoded audio only |

The Intel column was read in `.venv-x86_64` under Rosetta on
2026-11-03 (the Apple silicon column, re-read the same day in `.venv`,
still matches), except libchromaprint, whose Intel version is the
script's own pin and whose Apple silicon version is the maintainer's
Homebrew copy (a user's may differ). OpenSSL and SQLite belong to the
interpreter that builds the app, a uv-managed Python 3.13.15 for each
architecture, so the two builds can differ there (they do for OpenSSL)
and a CI runner's may differ again; read both from the environment that
builds. Homebrew's current ffmpeg formula is 9.0.2 (formulae.brew.sh,
2026-11-03), ahead of the 9.0.1 installed here.

The bundled four, from the environment the build uses (run it with each
architecture's own interpreter):

```
uv run python -c "import ssl, sqlite3, soundfile; from PySide6 import QtCore; print(ssl.OPENSSL_VERSION, sqlite3.sqlite_version, soundfile.__libsndfile_version__, QtCore.qVersion())"
```

`ffmpeg -version` reads ffmpeg's version and `grep '^VERSION='
packaging/build_chromaprint.sh` the Intel app's libchromaprint (1.6.2).
Neither app bundles ffmpeg; the Intel app carries its own
libchromaprint, and the Apple silicon app finds the user's. A new
chromaprint release changes the script's `VERSION` and `SHA256` together,
and this table with them.

**Tracked, because they decode peer files unsandboxed (AUDIT S-03,
accepted):** open against libsndfile 1.2.2 (both architectures) on 2026-10-09 are
CVE-2026-37555 (IMA ADPCM), CVE-2025-56226 (an mpeg_l3 leak) and
CVE-2024-50612 (ogg_vorbis, encoder-side). At each release, take the
first soundfile wheel or ffmpeg that fixes one, and update this list. The bundled four match the security audit's reading of
the `dist/Seeker.app` built on 2026-10-08 (`docs/phase-01/round-12/
AUDIT.md` §9).
[HISTORY §199](history/181-210.md#199)

## The Windows installer

**Written, never verified on real hardware.**

`packaging/seeker.iss` is an [Inno Setup](https://jrsoftware.org/isinfo.php)
script wrapping the same one-folder build: a `Setup.exe` with Start
Menu and Desktop shortcuts, an uninstall entry, and the icon
`packaging/icons/seeker_icon.ico`. Inno Setup is a separate Windows
tool that `uv` cannot install; put its compiler, `ISCC.exe`, on `PATH`
(or pass `--iscc`).

```
uv run python packaging/build_windows_installer.py
```

or the two steps by hand:

```
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
ISCC.exe packaging\seeker.iss
```

Either produces `dist/SeekerSetup.exe`. The script's `AppId` is a
fixed GUID that lets Inno Setup recognise an upgrade as the same app;
never regenerate it. No code signing is configured, so SmartScreen will
likely warn about the installer.
[HISTORY §36](history/032-046.md#36)

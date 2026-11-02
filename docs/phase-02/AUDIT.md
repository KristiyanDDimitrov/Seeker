# Phase 02 — platform audit: Intel Macs and Windows

**Author:** Claude Code, phase-02 planning, 2026-10-17. **Base:**
`2b7e8d9` (the S18 handoff after v0.1.0). **Mode:** read-only on
`src/`, `tests/` and `packaging/`. Every finding cites what was read,
run or measured; anything reasoned rather than observed says
UNVERIFIED. Nothing was fixed. The fix rows are in rounds 13–15
(`round-13/`, `round-14/`, `round-15/`), named in each finding's last
line.

**Severity** is the effect on the target platform: **Blocker** (it
cannot install, start, or do the job at all), **High** (a core flow
breaks), **Medium** (a flow degrades or a risk is real), **Low**,
**Info**. **Confidence** is HIGH (read in code or measured), MED
(strong signal, to confirm) or LOW (reasoned; hardware decides).

---

## Summary

**Intel Macs are close.** Seeker's Python is portable, and the one
macOS-arm64 assumption in the code (Homebrew's prefix) is already
handled. What blocks Intel is the dependency set and the build: numba
and llvmlite stopped publishing Intel macOS wheels in 2025 (PF-01),
and the build makes an arm64-only app (PF-02). Both are fixable on the
M4 Pro under Rosetta 2, and GitHub's Intel runner tests the result.

**Windows needs real work, most of it doable from the Mac.** Six
findings break a core flow outright: the PATH merge corrupts Windows'
PATH at startup (PF-09), Sharing writes Windows paths into YAML double
quotes (PF-13), text I/O uses the locale code page (PF-11), every
`docker` call flashes a console window (PF-10), a second launch runs a
second Seeker (PF-23), and the tray icon is a macOS template image
(PF-24). The rest is desktop integration that macOS had and Windows
lacks (start at login, wording, menus, fingerprinting), packaging that
has never run (PF-35, PF-36), and Docker Desktop behaviour that only a
real Windows machine can answer (PF-14 to PF-18).

| ID | Platform | Sev. | Conf. | Finding | Fix row |
|---|---|---|---|---|---|
| PF-01 | Intel | Blocker | HIGH | numba/llvmlite have no Intel macOS wheels after 0.62.1/0.45.1; the lock holds 0.67.0/0.49.0 | R13 S2 |
| PF-02 | Intel | Blocker | HIGH | The build makes an arm64-only app; one DMG, one name | R13 S6 |
| PF-03 | Intel | High | HIGH | CI never runs x86_64 | R13 S4 |
| PF-04 | Intel | Info | HIGH | Intel's floor is macOS 15.0 (PySide6's own binaries) | R13 S8 (document) |
| PF-05 | Mac | Low | HIGH | Help → Build doesn't say Intel or Apple silicon, or Rosetta | R13 S1 |
| PF-06 | All | Medium | HIGH | No smoke test of a frozen build | R13 S5 |
| PF-07 | All | Medium | HIGH | Release docs and assets assume one DMG | R13 S8, R15 S7 |
| PF-08 | All | Info | MED | librosa → numba is the root of PF-01, the one-folder build and the cold JIT (direction) | parked **[ASK]** |
| PF-09 | Windows | Blocker | HIGH | The startup PATH merge splits on `:` and corrupts Windows' PATH | R14 S4 |
| PF-10 | Windows | High | HIGH | Every subprocess opens a console window from the windowed app | R14 S2 |
| PF-11 | Windows | High | HIGH | Text I/O and subprocess output use the locale code page, not UTF-8 | R14 S2, S3 |
| PF-12 | Windows | Low | MED | The CLI's output can raise on a non-ANSI track name when redirected | R14 S3 |
| PF-13 | Windows | Blocker | HIGH | Sharing writes `C:\…` into a YAML double-quoted scalar | R14 S5 |
| PF-14 | Windows | High | LOW | Host-path identity with `docker inspect` is unmeasured on Windows | R14 S5, R15 S2 |
| PF-15 | Windows | Medium | MED | "Launch Docker Desktop" relies on `cmd /c start "" "Docker Desktop"` | R14 S4 |
| PF-16 | Windows | High | LOW | Peer names NTFS can't hold may never be placed | R15 S2 |
| PF-17 | Windows | High | LOW | slskd's SQLite lives on a Windows bind mount | R15 S2 |
| PF-18 | Windows | Medium | MED | Paths over 260 characters | R14 S9, R15 S5 |
| PF-19 | Windows | Medium | HIGH | Drive letters: peer names that look like drives; no "drive missing" hint | R14 S9 |
| PF-20 | Windows | Low | MED | Reserved device names (`CON`, `NUL`, …) pass the sanitizer | R14 S9 |
| PF-21 | Windows | Medium | MED | `os.replace` fails on a file another process holds open | R14 S9 |
| PF-22 | Windows | Info | MED | 0600/0700 are no-ops; privacy rests on the profile's ACL | R14 S9 (accept) |
| PF-23 | Windows | High | HIGH | No single-instance guard | R14 S7 |
| PF-24 | Windows | High | MED | The tray icon is a macOS template image | R14 S6 |
| PF-25 | Windows | Low | MED | No window icon is set | R14 S6 |
| PF-26 | Windows | Low | HIGH | The menu bar becomes an in-window strip with macOS items | R14 S6 |
| PF-27 | Windows | Medium | HIGH | User-facing text names macOS features | R14 S6 |
| PF-28 | Windows | Medium | HIGH | Start at login is macOS-only | R14 S8 |
| PF-29 | Windows | Medium | MED | Fingerprinting needs a `chromaprint.dll` nobody ships | R14 S10 **[ASK]** |
| PF-30 | Windows | Medium | LOW | The quit seam is unmeasured for shutdown, sign-out and upgrades | R15 S4 |
| PF-31 | Windows | Low | LOW | Fractional DPI scaling and Windows fonts are unreviewed | R14 S6, S13; R15 S4 |
| PF-32 | Windows | High | HIGH | The suite has never run on Windows; no Windows CI | R14 S1, S12 |
| PF-33 | Windows | Medium | HIGH | mypy never type-checks a `win32` branch | R14 S1 |
| PF-34 | Windows | Low | HIGH | The tests' docker guard matches the name `docker` only | R14 S2 |
| PF-35 | Windows | High | HIGH | The Windows build has never run, and is not in CI | R14 S11 |
| PF-36 | Windows | Medium | HIGH | `seeker.iss`: a second version, an admin install, no identity | R14 S11 |
| PF-37 | Windows | Info | MED | Unsigned: SmartScreen warns; antivirus may flag the bootloader | R15 S5, S7 |
| PF-38 | Windows | Info | HIGH | Windows on ARM runs the x64 build emulated; no native build | R15 S7 (document) |

---

## Intel Macs

### PF-01 — numba/llvmlite have no Intel macOS wheels after 0.62.1/0.45.1 · Blocker · HIGH

- **Evidence.** `uv.lock`: numba 0.67.0 and llvmlite 0.49.0 list
  cp313 wheels for `macosx_12_0_arm64`, manylinux x86_64 and aarch64,
  and `win_amd64` only. PyPI's JSON (read 2026-10-17): the last numba
  with a `macosx_*_x86_64` wheel is **0.62.1** (2025-09-29), the last
  llvmlite **0.45.1** (2025-10-01); every later release, 0.68.0 and
  0.50.0 included, has none. numba 0.62.1 requires
  `llvmlite>=0.45.0dev0,<0.46` and **`numpy>=1.22,<2.4`**.
- `pyproject.toml` requires **`numpy>=2.5.2`**, which conflicts. That
  floor is only the version current when numpy was declared
  (`b4dc1d2`, "present at runtime only transitively"); no fix or
  feature depends on it.
- Compatible with the Intel pins, read from the installed metadata:
  librosa 1.0.0 (`numba>=0.61.0`, `numpy>=2.1.0`), scipy 1.18.1
  (`numpy>=2.0.0,<2.8`), scikit-learn 1.9.1 (`numpy>=1.24.1`), soxr,
  soundfile, pyloudnorm (unbounded or low floors).
- Every other locked binary distribution has an Intel macOS wheel
  (numpy, scipy, scikit-learn, soxr, soundfile, rapidfuzz, msgpack,
  cffi; PySide6, shiboken6 and pyobjc are universal2). Measured by
  reading every wheel tag in `uv.lock`.
- **Impact.** On an Intel Mac `uv sync` tries to build llvmlite from
  source (an LLVM toolchain), so nothing installs, and no Intel app
  can be built.
- **Fix sketch.** `[tool.uv]` constraints with a
  `sys_platform == 'darwin' and platform_machine == 'x86_64'` marker
  (`numba<0.63`, `llvmlite<0.46`, `numpy<2.4`), numpy's floor lowered
  to what Intel can take, and `required-environments` naming the
  three targets, so a future lock that loses a platform's wheels fails
  at `uv lock` rather than on a user's machine. Apple silicon and
  Windows keep today's versions. **Effort** M. **Risk** LOW: the lock
  gains a fork; the arm64 set must not change (checked by diff).
- **Fix row:** round 13 S2.

### PF-02 — The build makes an arm64-only app · Blocker · HIGH

- **Evidence.** `packaging/seeker.spec:142` `target_arch=None`:
  PyInstaller builds for the running interpreter, arm64 on Kris's Mac.
  `packaging/build_dmg.py:21-22` names one output (`dist/Seeker.app`,
  `dist/Seeker.dmg`). `RELEASING.md` steps 2–5 build, check, checksum
  and upload one DMG.
- Universal2 is not an option: the two architectures need different
  numba versions (PF-01), and PyInstaller's universal2 mode needs
  every bundled binary fat (numpy, scipy, numba and llvmlite publish
  thin wheels).
- **Impact.** No app for Intel. Also UNVERIFIED: whether today's
  arm64 bundle carries PySide6's universal2 binaries whole (their
  x86_64 halves are dead weight in an arm64 app); `target_arch` set
  explicitly may thin them.
- **Fix sketch.** Build each architecture with its own interpreter
  (x86_64 under Rosetta), `target_arch` explicit, outputs named per
  architecture, every Mach-O in each bundle checked with `lipo`, the
  bundle size compared. **Effort** M. **Risk** MED: a mis-thinned
  bootloader would start the wrong slice (the check covers it).
- **Fix row:** round 13 S6.

### PF-03 — CI never runs x86_64 · High · HIGH

- **Evidence.** `.github/workflows/ci.yml:29` `runs-on: macos-26`
  (arm64) for the only test job. GitHub's `macos-15-intel` is the last
  Intel macOS runner, retired in fall 2027.
- **Impact.** An Intel-only break (a wheel, a numba or numpy
  difference) ships unnoticed.
- **Fix sketch.** A second job on `macos-15-intel`: the whole suite
  offscreen, with Intel Homebrew's chromaprint. **Effort** S.
- **Fix row:** round 13 S4.

### PF-04 — Intel's floor is macOS 15.0 · Info · HIGH

- **Evidence.** `otool -arch x86_64 -l` on PySide6 6.11.2's
  `QtCore.abi3.so`, `QtWidgets.abi3.so` and shiboken6's
  `Shiboken.abi3.so`: `minos 15.0`, the same as their arm64 halves.
  The Qt frameworks themselves say 13.0, numpy 2.5.3's extension
  modules 14.0. `packaging/bundle_info.py:28`
  `MINIMUM_SYSTEM_VERSION = "15.0"`.
- **Impact.** Intel Macs older than macOS 15's support list can't run
  Seeker: per Apple's list as secondary sources report it, macOS 15
  runs on MacBook Air 2020, MacBook Pro 2018, iMac 2019, Mac mini
  2018, Mac Pro 2019 and later, and iMac Pro (UNVERIFIED with Apple).
- **Fix.** None planned (a second, older Qt on Intel only).
  Document the floor and the models in the README and the release
  notes. **Fix row:** round 13 S8.

### PF-05 — Help → Build doesn't say which architecture runs · Low · HIGH

- **Evidence.** `src/seeker/_build_info.py:19-37` carries the SHA,
  `git describe` and the build time; `ui/dialogs.py:96-97` and
  `ui/pages/static_pages.py` show those three. Nothing reports
  `platform.machine()`, or that an x86_64 process runs translated
  (`sysctl.proc_translated` is 1 under Rosetta; observed 0 natively
  on 2026-10-17).
- **Impact.** Once two DMGs exist, support can't tell which one a
  person installed, and someone who installs the Intel DMG on Apple
  silicon gets a slower app with no hint why.
- **Fix sketch.** Help → Build names the architecture, and says
  "Intel build on Apple silicon (Rosetta)" with a pointer to the
  Apple silicon download when translated. **Effort** S.
- **Fix row:** round 13 S1.

---

## Every platform

### PF-06 — No smoke test of a frozen build · Medium · HIGH

- **Evidence.** No test or tool runs a frozen build; the last frozen
  checks were by hand (HISTORY §30, §31, §222, §242). `seeker.spec`'s
  `hiddenimports` and `datas` are maintained by hand.
- **Impact.** A missing hidden import, data file or native library
  (or numba misbehaving inside a frozen x86_64 or Windows bundle) is
  found only when a person launches the app. Phase 02 makes three
  frozen builds out of one spec.
- **Fix sketch.** A `--smoke-test` mode in the real entry point: it
  imports every `seeker` module, applies the theme offscreen, loads
  the bundled fonts and icons, analyses a generated WAV (numba's JIT
  inside the bundle), reports chromaprint's availability, and exits
  0 or 1. No `Application`, no database, no real data. **Effort** M.
- **Fix row:** round 13 S5.

### PF-07 — Release docs and assets assume one DMG · Medium · HIGH

- **Evidence.** `RELEASING.md` (steps 2–5, one `Seeker.dmg`);
  `README.md:78` "macOS 15 or later on Apple silicon";
  `docs/packaging.md`'s platform table; `packaging/Read Me First.txt`.
  The update check links to the release's page, not to an asset
  (`update_check.py:93-97, 189`), so it needs no change for several
  assets.
- **Fix rows:** round 13 S8 (two DMGs), round 15 S7 (the installer).

### PF-08 — librosa → numba is the root of several costs · Info (direction) · MED

- **Evidence.** Seeker calls three librosa functions:
  `librosa.load` (`audio/analysis.py:60`), `librosa.beat.beat_track`
  for the tempo only (`:84`, beats discarded), and
  `librosa.feature.chroma_cqt` (`:93`). librosa 1.0.0 requires numba,
  which brings llvmlite (130 MB unpacked here) and the 18–21 s
  cold JIT that forces the one-folder build (HISTORY §30). numba is
  also why Intel needs pins (PF-01) and why no native Windows ARM64
  build exists (PF-38).
- **Option.** Tempo (onset strength, tempogram, a prior) and chroma
  for key estimation in numpy/scipy alone, measured against librosa
  on the X9 Pro sample set for agreement. It removes numba everywhere;
  it risks BPM/key accuracy, which DJs notice.
- **Fix row:** none. Parked as an **[ASK]** spike (round 15 →
  "Parked").

---

## Windows: process and text

### PF-09 — The startup PATH merge corrupts Windows' PATH · Blocker · HIGH

- **Evidence.** `soulseek/docker_setup.py:31-70`
  `ensure_full_path_environment()` runs macOS's `path_helper`, then
  `os.environ.get("PATH", "").split(":")` (`:61-62`) and appends
  `/opt/homebrew/bin` and `/usr/local/bin` (`:28`), rejoining with
  `os.pathsep`. `application.py:135` calls it unconditionally in
  `Application.__init__`.
- **Impact.** On Windows every entry `C:\…` splits at its drive colon
  (`C`, `\Windows\system32;C`, …) and the rejoin with `;` breaks every
  entry: from the first `Application()` on, `docker` and `ffmpeg` are
  not found, and the wizard reports Docker missing on a machine that
  has it. Reasoned from the code; the arithmetic is certain, the
  symptom UNVERIFIED on hardware.
- **Fix sketch.** The body is macOS-only; elsewhere the function
  returns; any split uses `os.pathsep`. A test with
  `sys.platform` patched and a Windows-shaped PATH. **Effort** S.
- **Fix row:** round 14 S4.

### PF-10 — Every subprocess opens a console window · High · HIGH

- **Evidence.** The windowed build (`seeker.spec`, `console=False`)
  starts console programs with no `creationflags`:
  `soulseek/docker_setup.py:42, 133, 145, 448`;
  `soulseek/sharing_service.py:317, 357, 650`;
  `audio/fingerprint.py:378` (`ffmpeg`, once per file in a
  fingerprint run); `ui/wizard.py:660-667` (`cmd /c start`);
  `ui/pages/static_pages.py:41-45` (`explorer`). `grep` finds no
  `CREATE_NO_WINDOW` or `STARTUPINFO` anywhere.
- **Impact.** On Windows a GUI process that starts a console program
  without `CREATE_NO_WINDOW` gets a console window flashed per call
  (documented Windows behaviour; UNVERIFIED in this app). Sharing's
  and the outage checks' `docker` calls repeat on polls, so windows
  flash while Seeker sits in the tray.
- **Fix sketch.** One module runs every subprocess: it adds
  `CREATE_NO_WINDOW` on Windows and decodes text as UTF-8 (PF-11). An
  AST sweep fails the build on a direct `subprocess` call anywhere
  else in `src/`. **Effort** M (eleven call sites, behaviour-neutral
  on macOS). **Risk** LOW.
- **Fix row:** round 14 S2.

### PF-11 — Text I/O uses the locale code page · High · HIGH

- **Evidence.** Python 3.13 is not in UTF-8 mode by default, so text
  without an `encoding=` uses the locale's ANSI code page on Windows
  (cp1252 on a Western install).
  - Subprocess output decoded with `text=True`:
    `docker_setup.py:45, 452`; `sharing_service.py:320, 365, 656`.
    `docker inspect` prints a non-ASCII mount path in UTF-8, so it
    decodes wrongly and never matches the location it names.
  - Files written: `files/atomic.py:73` `os.fdopen(fd, "w")` writes
    every `write_text_atomic`/`write_text_locked` file, including the
    per-user Compose file and `slskd.yml` that Sharing edits
    (`sharing_service.py:550, 553`). A share path outside cp1252
    (Cyrillic, CJK) raises `UnicodeEncodeError`; one inside it but
    non-ASCII (`é`) is written as bytes that are invalid UTF-8, which
    Compose and slskd then refuse (UNVERIFIED on hardware).
  - Files read: `config_store.py:142`, `spotify/token_store.py:33`,
    `album_art_cache.py:65, 86`, `sharing_service.py:539-540`.
  - Safe today: `config.json`, the token and the art metadata are
    written by `json.dumps` with its default `ensure_ascii=True`, so
    they are ASCII whatever the code page.
  - `ruff check --preview --select PLW1514` (run read-only) finds 2 of
    these sites (`config_store.py:142`, `sharing_service.py:540`); it
    cannot see `os.fdopen` or `text=True`.
- **Fix sketch.** `encoding="utf-8"` at every site (the subprocess
  module of PF-10 for output), PLW1514 selected by its exact code, and
  a guard for what ruff can't see. **Effort** S–M. **Risk** LOW: macOS
  already defaults to UTF-8.
- **Fix rows:** round 14 S2 (subprocess output), S3 (files).

### PF-12 — The CLI's output can raise on Windows · Low · MED

- **Evidence.** `main.py:16` logs to `sys.stdout`; `cli.py` prints
  through `printable()` (control characters only). Redirected to a
  file or pipe on Windows, stdout uses the ANSI code page.
- **Impact.** `print()` of a track or peer name outside it raises
  `UnicodeEncodeError`, ending the command (UNVERIFIED on hardware).
  An interactive console is unaffected (Python writes it as UTF-16).
- **Fix sketch.** `sys.stdout`/`sys.stderr.reconfigure(encoding=
  "utf-8", errors="replace")` at the CLI's start. **Effort** S.
- **Fix row:** round 14 S3.

---

## Windows: Docker and slskd

### PF-13 — Sharing writes `C:\…` into a YAML double-quoted scalar · Blocker · HIGH

- **Evidence.** `soulseek/sharing_service.py:386-397`
  `preview_add_location` builds
  `f'      - "{location.path}:{container_path}:ro"'`. In a YAML
  double-quoted scalar `\` starts an escape: `\U` expects eight hex
  digits and `\M`, `\K` … are invalid (YAML 1.2 §5.7).
- **Impact.** Adding `C:\Users\Kris\Music` to the share writes a
  Compose file that no longer parses; Sharing then rolls back
  (HISTORY §74's two-file write), so the feature fails every time on
  Windows. The same line breaks on macOS for a folder whose name
  holds `"` or `\`, both legal there (rare, same fix). The template's
  own variables (`docker-compose.yml:46-47`) are safe: Compose
  interpolates them after parsing.
- **Fix sketch.** Write the host path with forward slashes
  (`C:/Users/…`), or as a single-quoted scalar; a test parses the
  inserted line with a YAML reader for a Windows path with `\U` and a
  `'` in it. **Effort** S.
- **Fix row:** round 14 S5.

### PF-14 — Host-path identity with `docker inspect` is unmeasured · High · LOW

- **Evidence.** Sharing compares `location.path` with each mount's
  `Source` from `docker inspect` (`sharing_service.py:268-310,
  639-683`); a recreate passes the live `Source` back as the share
  (`:297-303`, HISTORY §140). `is_self_managed` compares Compose's
  `config_files` label as a resolved `Path` (`:343-384`).
- **UNVERIFIED on Windows:** whether Docker Desktop reports a bind
  mount's `Source` as given (`C:\Users\…`), with forward slashes, or
  as its VM's path (`/run/desktop/mnt/host/c/…`); and Windows paths
  compare case-insensitively, which a plain string `==` does not.
- **Impact.** If the forms differ, Sharing shows nothing shared, and
  a recreate may hand Compose a path it can't mount.
- **Fix sketch.** One function turns either side into a comparable
  key (case-folded, one separator, the VM prefix mapped back once its
  form is measured); every comparison goes through it. **Fix rows:**
  round 14 S5 (the function, with the known forms), round 15 S2 (the
  measured form).

### PF-15 — "Launch Docker Desktop" relies on `start "Docker Desktop"` · Medium · MED

- **Evidence.** `ui/wizard.py:657-680` runs
  `cmd /c start "" "Docker Desktop"` on Windows. That finds the
  program only through an App Paths registration (UNVERIFIED for
  Docker Desktop's installer), shows a console (PF-10), and returns
  before Docker starts, so failure is invisible.
- **Fix sketch.** Prefer Docker Desktop's own CLI,
  `docker desktop start` (Docker Desktop 4.37 and later; UNVERIFIED
  here on either platform), falling back to the installed
  `Docker Desktop.exe` through `os.startfile`; the existing "Check
  again" stays the truth. **Effort** S.
- **Fix row:** round 14 S4.

### PF-16 — Peer names NTFS can't hold may never be placed · High · LOW

- **Evidence.** slskd runs on Linux in its container and writes
  `<remote parent>/<basename>` with the peer's raw characters
  (HISTORY §138). `_locate_completed_file`
  (`soulseek/placement.py:55-131`) looks the file up by that raw name.
  A name with `: * ? " < > |`, or ending in a dot or space, is valid
  on Linux and invalid on NTFS. Colons are common in music file names.
- **UNVERIFIED:** what Docker Desktop's file sharing does with such a
  name on a Windows bind mount: refuse the write (slskd's download
  fails), or map the characters into Unicode's private-use area as
  WSL's own drive mounts do (the file lands under another name).
- **Impact.** Either way the lookup by raw name finds nothing and
  the track stays "downloading" until its timeout.
- **Fix sketch.** Measure with `docker exec` writes on the hardware,
  then teach the lookup the mapped form, or fail the row with a
  readable reason. **Fix row:** round 15 S2 (measure), S3 (fix).

### PF-17 — slskd's SQLite lives on a Windows bind mount · High · LOW

- **Evidence.** `docker-compose.yml:46` mounts the whole data folder
  as `/app`, which holds slskd's own SQLite databases as well as
  `slskd.yml` and `downloads/`. On macOS that mount has worked since
  phase 01.
- **UNVERIFIED:** SQLite's locking over Docker Desktop's Windows file
  sharing, a known weak spot for SQLite on network-style mounts.
- **Impact.** If it fails: "database is locked" errors in slskd, or
  a corrupt slskd state.
- **Fix sketch.** Measure: a bring-up, a day of use, `docker logs`.
  If it fails, a named volume for slskd's state with only
  `downloads/` and `slskd.yml` bind-mounted; that changes the
  template, Sharing's file edits and the leftover rules, so it is an
  **[ASK]**. **Fix row:** round 15 S2, S3.

### PF-18 — Paths over 260 characters · Medium · MED

- **Evidence.** slskd's downloads land under
  `%LOCALAPPDATA%\Seeker\slskd-data\downloads\<remote folder>\<file>`
  (`docker_setup.py:107-113`), and library folders can be deep. Win32
  path calls fail past 260 characters unless the machine enables
  long paths and the executable's manifest says `longPathAware`.
  `grep` finds no `\\?\` handling. PyInstaller's manifest:
  UNVERIFIED.
- **Fix sketch.** Measure the manifest and a long placement; at
  least a `describe_error` branch that says the path is too long;
  `\\?\` only if measured necessary. **Fix rows:** round 14 S9
  (the error text), round 15 S5 (the measurement).

---

## Windows: files

### PF-19 — Drive letters · Medium · HIGH

- **Evidence.** `soulseek/placement.py:95` joins a peer-chosen folder
  name under the download folder: on Windows,
  `PureWindowsPath("C:/dl") / "D:x"` is `D:x`, another drive. The
  scanner's "may not be connected" hint is `/Volumes`-only
  (`library/scanner.py:31-35`). An external drive's letter on Windows
  is not stable, unlike `/Volumes/<name>`.
- **Impact.** A crafted name points a lookup at another drive (read
  only: the lookup lists and stats); an unplugged library drive
  reads as a plain missing folder; a drive that comes back as `F:`
  leaves its location dead.
- **Fix sketch.** Joins with peer-chosen names keep only the name's
  last component without a drive; the hint fires when a location's
  drive root is missing. Re-pointing a location at a new path is a
  separate feature (**[ASK]**, round 15). **Effort** S.
- **Fix row:** round 14 S9.

### PF-20 — Reserved device names pass the sanitizer · Low · MED

- **Evidence.** `files/sanitize.py:21-51` replaces `<>:"/\|?*` and
  controls and strips trailing dots and spaces, both Windows rules,
  but not the reserved names `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`9`,
  `LPT1`–`9`, alone or before an extension (`CON.flac`).
  `files/naming.py:103-128` (`clean_peer_filename`) builds on it.
- **Impact.** Placing `nul.mp3` fails or misbehaves on Windows
  (Windows 11 relaxed some cases; UNVERIFIED which).
- **Fix sketch.** Suffix a reserved stem (`CON_`). **Effort** S.
- **Fix row:** round 14 S9.

### PF-21 — `os.replace` fails on a file another process holds open · Medium · MED

- **Evidence.** `files/atomic.py:84` (`temp_path.replace(path)`) and
  `:114` (`rewrite_via_copy`, every tag write on a music file);
  placement's moves (`placement.py:279`). On Windows a rename onto a
  file that another process (a DJ app, a preview handler, antivirus)
  has open fails with `PermissionError` (winerror 5 or 32); POSIX
  allows it.
- **Fix sketch.** A bounded retry on those two errors, then a readable
  failure through `describe_error`. **Effort** S.
- **Fix row:** round 14 S9; measured on hardware in round 15 S5.

### PF-22 — 0600/0700 are no-ops on Windows · Info (accept) · MED

- **Evidence.** `files/atomic.py:26-56`: `write_text_locked`'s 0600
  and `make_private_dir`'s 0700 set only the read-only flag on
  Windows, as their docstrings say. Seeker's files live under
  `%LOCALAPPDATA%\Seeker` (platformdirs with `appauthor=False`), whose
  inherited ACL grants the user, SYSTEM and Administrators (Windows'
  default for a profile; UNVERIFIED on the test machine).
- **Accept**, in the manner of round 12's S-10, with `icacls` output
  from the hardware as evidence. **Fix row:** round 14 S9 (the
  written acceptance), round 15 S5 (the `icacls` reading).

---

## Windows: the desktop

### PF-23 — No single-instance guard · High · HIGH

- **Evidence.** `grep` finds no `QLocalServer`, `QSharedMemory`,
  `QLockFile` or lock file; `main_ui.py:61-137` builds an
  `Application` and a window on every launch. On macOS, LaunchServices
  brings a running `.app` forward instead of starting it twice
  (standard behaviour; UNVERIFIED for this bundle).
- **Impact.** On Windows a second Start-menu click, or the login item
  plus a manual launch, runs two Seekers: two backend polls, two
  sweeps, two tray icons, two writers of one database.
- **Fix sketch.** A `QLocalServer` handshake in `ui/` (Qt stays in
  `ui/` and `main_ui.py`): the first instance listens; a second one
  asks it to show its window (or the wizard) and exits. **Effort** M.
- **Fix row:** round 14 S7.

### PF-24 — The tray icon is a macOS template image · High · MED

- **Evidence.** `ui/tray.py:123-147` loads
  `seeker_menubar_Template.png` (a black glyph with alpha,
  `:518-539`) and calls `setIsMask(True)`, macOS's template-image
  convention.
- **Impact.** Windows doesn't recolour masks (UNVERIFIED), so the
  glyph stays black: invisible on Windows 11's default dark taskbar.
- **Fix sketch.** Off macOS, the full-colour app icon (or a light and
  a dark glyph by taskbar theme). **Effort** S.
- **Fix row:** round 14 S6.

### PF-25 — No window icon is set · Low · MED

- **Evidence.** `grep` finds no `setWindowIcon`. A dev run on Windows
  shows Python's icon; a frozen `Seeker.exe` may show its embedded icon
  (UNVERIFIED).
- **Fix row:** round 14 S6 (set it off macOS).

### PF-26 — The menu bar becomes an in-window strip · Low · HIGH

- **Evidence.** `ui/main_window.py:912-990` builds View, Window and
  Help with `self.menuBar()`. On macOS that is the global menu bar; on
  Windows it is a strip inside the window, above the sidebar, never
  reviewed in either theme. "Window → Zoom" is macOS's word
  (Windows says Maximize), there is no Exit, and
  `QKeySequence.StandardKey.Preferences` has no binding on Windows
  (Qt's table), so Settings loses its shortcut.
- **Fix sketch.** Decide with screenshots: a styled, Windows-worded
  menu bar, or none (the sidebar plus window shortcuts). **Effort** S.
- **Fix row:** round 14 S6.

### PF-27 — User-facing text names macOS features · Medium · HIGH

- **Evidence.** "menu bar": `ui/tray.py:341`,
  `ui/settings_window.py:1582`, `ui/help_text.py:1618`. "macOS
  notification": `help_text.py:1516`. "this Mac": `help_text.py:1514`.
  "macOS user account": `help_text.py:166`. "with macOS":
  `help_text.py:1512`. System Settings → Login Items:
  `help_text.py:1614-1615`, `settings_window.py:1645`.
  `brew install chromaprint` and "the Chromaprint installer on
  Windows", which does not exist for the library:
  `audio/fingerprint.py:222-227`, `library/duplicate_service.py:283`.
- **Fix sketch.** One module (no Qt, since services word some of
  these) holds each platform's term; the text uses it; a test reads
  each string with `sys.platform` patched to both. **Effort** S–M.
- **Fix row:** round 14 S6.

### PF-28 — Start at login is macOS-only · Medium · HIGH

- **Evidence.** `login_item.py:43-44`
  `is_supported() = darwin and frozen`; Settings shows the option
  unavailable elsewhere (`settings_window.py:1582-1650`). The module's
  rule: its status is read live, never stored (`packaging/CLAUDE.md`).
- **Fix sketch.** A Windows backend over `winreg`: the
  `HKCU\…\CurrentVersion\Run` value names the installed
  `Seeker.exe`; the live status also reads Task Manager's
  enable/disable flag under `…\Explorer\StartupApproved\Run`
  (key layout UNVERIFIED until round 15). Frozen builds only, as on
  macOS. **Effort** M.
- **Fix row:** round 14 S8.

### PF-29 — Fingerprinting needs a `chromaprint.dll` nobody ships · Medium · MED

- **Evidence.** `audio/fingerprint.py:90-160` loads
  `chromaprint.dll`/`libchromaprint.dll` from `_MEIPASS` first, then
  by name. Chromaprint's releases publish `fpcalc` builds, not the
  library, for Windows (UNVERIFIED for the current release); the error
  text points at an installer that does not exist (`:222-227`). The
  ffmpeg fallback (`:378`) finds ffmpeg on PATH (winget's `Gyan.FFmpeg`
  puts it there).
- **Fix sketch.** Build `chromaprint.dll` in CI (vcpkg or MSYS2),
  bundle it on Windows only with its LGPL text, and name it in
  `docs/packaging.md` → Native libraries; or ship v0.3.0 without
  fingerprinting on Windows and say so. Adding a native library to the
  bundle is **[ASK]**. **Effort** M.
- **Fix row:** round 14 S10.

### PF-30 — The quit seam is unmeasured on Windows · Medium · LOW

- **Evidence.** `src/seeker/ui/CLAUDE.md`: every quit passes `QEvent.Type.Quit` to
  the `QApplication`, and an `eventFilter` may ask the person first
  (the quit confirmation) — observed on Cocoa only. Windows' shutdown
  and sign-out (`WM_QUERYENDSESSION`/`WM_ENDSESSION`), and an
  installer that closes the running app to upgrade it (Restart
  Manager), are UNVERIFIED.
- **Impact.** A modal question during shutdown holds Windows'
  "this app is preventing shutdown" screen; an upgrade may fail to
  close Seeker.
- **Fix row:** round 15 S4 (measure, then fix).

### PF-31 — Fractional DPI and Windows fonts are unreviewed · Low · LOW

- **Evidence.** Display type is in px (`ui/theme.py:1156-1174`),
  body text the system font (Segoe UI on Windows, UNVERIFIED size).
  125 % and 150 % scaling are common on Windows laptops; custom
  painting (lamps, meters, `TokenIconEngine`, the brows) has only ever
  rendered at integer ratios.
- **Fix rows:** round 14 S6 (screenshots from the Windows CI job)
  and S13 (a VM, if Kris sets one up), round 15 S4 (hardware).

---

## Windows: tests, CI and packaging

### PF-32 — The suite has never run on Windows · High · HIGH

- **Evidence.** `ci.yml` has a macOS test job and a Linux audit job.
  `tests/`: 116 test modules, about 2,418 tests. Known POSIX
  assumptions: permission asserts (`test_token_store.py:73`,
  `test_atomic_file.py:50, 65, 111, 167`, `test_metadata.py:724`;
  three modules already carry a `skip_on_windows`), symlinks, which
  Windows allows only with Developer Mode or elevation
  (`test_leftover_service.py:226`, `test_duplicate_service.py:1139`,
  `test_nested_locations.py:101`), and path strings (count unknown).
- **Fix sketch.** A `windows-2025` job, non-blocking until the list
  is worked off, every skip naming what it excludes (working
  agreement 5). **Effort** L. **Fix rows:** round 14 S1 (the job and
  the list), S12 (green and blocking), fixes in between.

### PF-33 — mypy never type-checks a `win32` branch · Medium · HIGH

- **Evidence.** `ci.yml:49` runs `mypy --strict src/` on macOS. mypy
  evaluates `sys.platform` checks statically, so every
  `if sys.platform == "win32":` body is unreachable to it on macOS and
  never checked. New Windows code (`winreg`) needs checking.
- **Fix sketch.** `mypy --strict --platform win32 src/` beside the
  existing run. **Effort** S. **Fix row:** round 14 S1.

### PF-34 — The tests' docker guard matches the name `docker` only · Low · HIGH

- **Evidence.** `tests/conftest.py:139`
  `Path(os.fsdecode(argv[0])).name == "docker"`. A Windows code path
  that resolves `docker.exe` (through `shutil.which`) would slip past
  it, and the guard exists because a test once recreated Kris's
  container (HISTORY §213).
- **Fix sketch.** Compare the stem, case-folded. **Effort** S.
- **Fix row:** round 14 S2.

### PF-35 — The Windows build has never run · High · HIGH

- **Evidence.** `docs/packaging.md`: "Written, never verified on real
  hardware." `packaging/build_windows_installer.py:20-22` says the
  same. No CI job builds it. `bundle_info.python_license()` names
  Windows' `LICENSE.txt` location UNVERIFIED.
- **Fix sketch.** Build the one-folder app and the installer on
  `windows-2025`, run the smoke test (PF-06) on the result, upload
  both as artifacts. **Effort** M. **Fix row:** round 14 S11.

### PF-36 — `seeker.iss` keeps a second version and installs for everyone · Medium · HIGH

- **Evidence.** `packaging/seeker.iss:27` `#define MyAppVersion
  "0.1.0"`, a second copy of the version that `RELEASING.md` says
  doesn't exist; `:35` `DefaultDirName={autopf}\…` with no
  `PrivilegesRequired`, so an elevated install into Program Files,
  where numba's in-bundle JIT cache can't be written (where it falls
  back to is UNVERIFIED); no `AppMutex` for the single instance
  (PF-23); `build_windows_installer.py` never writes
  `_build_info_generated.py`, so Help → Build says "dev".
- **Fix sketch.** The version passed from `pyproject.toml` (`/D`),
  `PrivilegesRequired=lowest`, the running app closed for an upgrade
  (an `AppMutex` needs a named Win32 mutex that Seeker creates, which
  PF-23's `QLocalServer` does not; or Inno Setup's Restart Manager
  close alone), the build identity written by a function both build
  scripts share. **Effort** S–M. **Fix row:** round 14 S11.

### PF-37 — Unsigned on Windows · Info · MED

- **Evidence.** Decision 3 (`README.md`). An unsigned installer gets
  SmartScreen's "Windows protected your PC" until it builds
  reputation; PyInstaller's bootloader is a known source of antivirus
  false positives (UNVERIFIED for this build).
- **Fix rows:** round 15 S5 (Defender on the hardware; a false
  positive is reported to Microsoft), S7 (the first-run steps in the
  README and release notes).

### PF-38 — Windows on ARM runs the x64 build emulated · Info · HIGH

- **Evidence.** `uv.lock`: soxr 1.1.0 has no `win_arm64` wheel;
  numba and llvmlite have one only from 0.68.0 and 0.50.0
  (2026-09), after the locked versions. Windows 11 runs x64 programs
  on ARM through emulation.
- **Decision:** no native ARM64 build in phase 02; the x64 build
  under emulation is untested unless the borrowed machine is ARM.
  Documented in `docs/packaging.md` (round 15 S7).

---

## Checked, no change needed

- **Intel Homebrew's prefix.** Fingerprinting searches
  `/usr/local/lib` beside `/opt/homebrew/lib`
  (`audio/fingerprint.py:116-117`), and the PATH fallback lists
  `/usr/local/bin` (`docker_setup.py:28`).
- **Remote paths parse the same on every OS:** `PurePosixPath` after
  `\` → `/` (`placement.py:69`, `leftovers.py:66`, `client.py:493`,
  `quality.py:23`, `formatting.py:77`).
- **Placed names are Windows-safe** apart from PF-20: the sanitizer
  already replaces Windows' reserved characters and strips trailing
  dots and spaces; the 255-byte UTF-8 budget is within NTFS's 255
  UTF-16 units.
- **Per-user data** goes through `platformdirs` with `appauthor=False`
  everywhere (`application.py:85, 95, 105`, `config_store.py:125`,
  `album_art_cache.py:17`, `docker_setup.py:112, 121`):
  `%LOCALAPPDATA%\Seeker` on Windows.
- **Existing platform branches** are already right off macOS: the
  Dock-icon switch returns (`ui/tray.py:566`), a left-click on the
  tray opens the window (`:221-225`), "Show in folder" has Windows
  and Linux branches (`static_pages.py:40-45`; PF-10 aside), the
  login item reports "not supported" (`login_item.py:43-44`), and the
  wizard's Docker step has a Windows branch (PF-15 aside).
- **The slskd URL** is `127.0.0.1`, which avoids IPv6-first resolution
  on Windows as on macOS (`docker_setup.py:73`).
- **The Compose template** names no machine path, and its two host
  paths are variables (`docker-compose.yml:46-47`), interpolated after
  YAML parsing (PF-13 is Sharing's inserted lines, not the template).

## Considered and rejected

- **A universal2 macOS app:** impossible with two numba versions, and
  fragile without them (PF-02).
- **One older dependency set for every platform:** holds Apple
  silicon and Windows back for Intel's sake (PF-01).
- **An x86_64-only Mac build for both architectures:** Rosetta only,
  slower, and Apple is winding Rosetta down.
- **An Intel macOS VM or container on Apple silicon:** no
  virtualization runs another architecture's macOS usefully; Rosetta
  plus the Intel runner cover it.
- **Python's UTF-8 mode as the PF-11 fix:** the frozen app could set
  it, but `uv run` and tests would still run in the locale code page,
  so the two would differ. Explicit encodings behave the same
  everywhere.
- **A Seeker-managed native slskd on Windows:** decision 2.

## Method

Read: `pyproject.toml`, `uv.lock` (every wheel tag, by script),
`.github/workflows/ci.yml`, `packaging/` (spec, both build scripts,
`seeker.iss`, `bundle_info.py`), `docker-compose.yml`, and every
`src/` site found by `grep` for `sys.platform`, `subprocess`,
`text=True`, `read_text`/`write_text`/`fdopen`, Homebrew and
`/Volumes` paths, AppKit and ServiceManagement, `setIsMask`,
`setWindowIcon`, `menuBar`, `QKeySequence`, and macOS words in string
literals. Measured: `otool -l` `minos` over 1,005 binaries in `.venv`,
both slices of PySide6's; `arch -x86_64` running python.org's
universal2 3.13.5; PyPI's JSON for numba and llvmlite (2026-10-17).
Read-only: `ruff check --preview --select PLW1514` (no `--fix`).
Not audited: Linux; the website; performance on any platform.

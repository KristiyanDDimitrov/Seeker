# Round 14 — Windows readiness, from the Mac and CI

**Author:** phase-02 planning, 2026-10-17. **Executor:** Claude Code,
on Kris's Mac. **Base commit:** whatever `HEAD` is when S1 starts
(round 13 may still be running beside it). **Session map:**
`docs/phase-02/round-14/SESSION-PLAN.md`. **Phase:**
`docs/phase-02/README.md`. **Findings:** `docs/phase-02/AUDIT.md`.

No Windows hardware is needed for this round. It does everything a
Mac and GitHub's `windows-2025` runner can: a Windows CI job, then
fixes for every Windows finding whose fix can be tested without
hardware, then a CI-built, smoke-tested, unsigned `SeekerSetup.exe`.
What only hardware can answer is listed for round 15, not guessed
at. Nothing is released in this round.

Read your row in the session map, then **only** §0 and the section
your row points at, plus each `PF-NN` that section names. Line
numbers are hints from `2b7e8d9`: `grep -n` the symbol first. Each
section separates what is **established** from what is a
**hypothesis**.

---

## §0 — Ground rules

**§0.1 Round 13's §0 applies in full**
(`sed -n '/^## §0/,/^## §1 /p' docs/phase-02/round-13/BRIEF.md`): phase 01's rules (R11
§0.1–§0.10, R12 §0.13), Kris's answers, HISTORY from §246 on, the
platform rules (§0.4), real data (§0.5).

**§0.2 Testing Windows behaviour on a Mac.**
- Patch `sys.platform` in the module under test (round 13 §0.4).
- Path logic: `pathlib.PureWindowsPath`. A concrete `Path` on macOS is
  a `PosixPath` whatever `sys.platform` says, so a function whose
  Windows behaviour matters takes or builds a `PurePath` of the right
  flavour, or the test drives a pure helper.
- Windows-only modules (`winreg`, `msvcrt`, `ctypes.windll`) are
  imported only inside `if sys.platform == "win32":`, so
  `mypy --strict src/` stays clean on macOS and
  `mypy --strict --platform win32 src/` (from S1) checks the branch.
  Tests reach them through a seam that a fake can replace.
- A Windows `OSError` carries `winerror`; on macOS build the error and
  set the attribute (`error.winerror = 32`); production code reads it
  with `getattr(error, "winerror", None)`.

**§0.3 The Windows CI job is the referee.** A Windows claim that the
job can show is shown there, with the run id. A claim only hardware
can settle stays UNVERIFIED in code and docs, and goes onto round 15's
list (§0.5).

**§0.4 Never set `PYTHONUTF8` or `PYTHONIOENCODING`** in CI, tests or
the app. They would hide PF-11 instead of fixing it; explicit
`encoding="utf-8"` is the fix (AUDIT → "Considered and rejected").

**§0.5 Feeding round 15.** Each row appends what it could not verify
to `docs/phase-02/round-15/BRIEF.md` → §0.7 "Carried from round 14"
(one line each: the claim, where it lives in code, how hardware
settles it). Round 15 is re-planned from that list.

**§0.6 New dependencies.** `pyyaml` may join the **dev** group (S5),
pre-approved: Sharing edits YAML as text, and tests should parse what
it writes. Any runtime dependency, or a native library in the bundle
(S10), is **[ASK]**.

---

## §1 — Windows CI, non-blocking; the first failure list; mypy for `win32` (S1, PF-32, PF-33)

**Established.** `ci.yml` has `check` (`macos-26`: ruff, mypy, pytest
with coverage) and `audit` (`ubuntu-24.04`). The suite is about 2,418
tests in 116 modules. Known POSIX assumptions: AUDIT PF-32. Every
locked binary package has a `win_amd64` cp313 wheel, and pyobjc is
excluded by its `sys_platform == 'darwin'` marker (planning's reading
of `uv.lock`).

**Hypotheses.**
- H1. `uv sync --locked --all-extras --dev` succeeds on
  `windows-2025` (the dev group's `dmgbuild` is pure Python).
- H2. `conftest.py`'s docker refusal works there (it subclasses
  `subprocess.Popen`).

**Do.**
1. A job `check-windows` on `windows-2025`: checkout and setup-uv
   (same pinned SHAs as `check`), `uv sync --locked --all-extras
   --dev`, `uv run pytest -q` with `QT_QPA_PLATFORM: offscreen`.
   `continue-on-error: true` until S12, with a comment saying so. No
   chromaprint (those tests skip). Timeout from the first run (start
   at 45 minutes).
2. In `check`: `uv run mypy --strict --platform win32 src/` after the
   existing mypy step. Fix what it reports, one commit per cause.
3. Record the Windows run's summary line, then **every failing test,
   grouped by cause** (paths and separators, permission bits,
   symlinks, encoding, subprocess or docker guard, Qt and fonts,
   timing, other), with a count per group, in the HISTORY entry. That
   list is round 14's tracked number (working agreement 3): every
   later row says which entries it fixed.

**Done when:** a CI run shows `check-windows` (failing is allowed)
and a green `check` with the `win32` mypy step; the grouped list is
in the HISTORY entry.

**Split point:** after step 3's list (step 2's fixes may follow in
the next session if they are many).

---

## §2 — One way to run a subprocess (S2, PF-10, PF-11, PF-34)

**Established.** Eleven call sites run programs with no
`creationflags` (PF-10 lists them). Five decode with `text=True` in
the locale code page (PF-11). Tests fake subprocesses by patching the
`subprocess` module's own attributes
(`monkeypatch.setattr(subprocess, "run", …)` in
`tests/test_docker_setup.py` and `tests/test_sharing_service.py`;
`"seeker.ui.wizard.subprocess.run"` is the same object). The tests'
docker guard matches `argv[0]`'s name `docker` exactly
(`conftest.py:139`).

**Do, one commit each, a failing test first.**
1. A Qt-free module (`src/seeker/processes.py`, or a better name the
   module map suggests) with `run(...)` and `popen(...)` covering the
   arguments the call sites use. On Windows it adds
   `subprocess.CREATE_NO_WINDOW` (0x08000000); text mode is always
   `encoding="utf-8", errors="replace"`. It calls
   `subprocess.run`/`subprocess.Popen` **through the module at call
   time** (never `from subprocess import run`), so every existing
   fake keeps working. The failing test: with `sys.platform` patched
   to `"win32"`, a fake `Popen` receives the flag.
2. Move every call site to it: a refactor commit, no behaviour change
   on macOS, the whole suite unchanged.
3. An AST sweep (`tests/test_subprocess_sweep.py`): no module in
   `src/seeker` but the helper names `subprocess.run`, `Popen`,
   `call`, `check_call`, `check_output`, `os.system` or `os.popen`.
   It fails the build, like the other sweeps.
4. The docker guard compares `Path(argv[0]).stem.casefold()`, so
   `docker.exe` and `DOCKER` are refused too, with a test (PF-34).
5. Tests isolate platformdirs on Windows (HISTORY §268): an autouse
   `tests/conftest.py` fixture sets `WIN_PD_OVERRIDE_LOCAL_APPDATA` to
   a tmp path, which covers Seeker's data, log and cache folders and
   reaches `test_lazy_spotify_config`'s subprocesses (platformdirs'
   source; UNVERIFIED on Windows). Its failing test is the probe, on
   `check-windows`: under the suite, `platformdirs.user_data_dir(
   "Seeker", appauthor=False)` names a tmp path, not the runner's
   `%LOCALAPPDATA%\Seeker`. Round 15 runs no suite until it is on main.

**Split point:** after step 2 for `docker_setup.py` and
`sharing_service.py` (fingerprint, wizard and "Show in folder"
follow).

---

## §3 — UTF-8 for every text file; the CLI's output (S3, PF-11, PF-12)

**Established.** PF-11's file sites: `files/atomic.py:73`
(`os.fdopen(fd, "w")`, which writes the Compose file and `slskd.yml`),
`config_store.py:142`, `spotify/token_store.py:33`,
`album_art_cache.py:65, 86`, `sharing_service.py:539-540`. Ruff's
`PLW1514` (a preview rule) sees two of them and not `os.fdopen`.
`pyproject.toml` selects preview rules by exact code only.

**Do, one commit each, a failing test first.**
1. `encoding="utf-8"` on every text read and write in `src/`. The
   failing test shows the default encoding in use on `HEAD`: for
   instance a subprocess running the write with
   `-X warn_default_encoding -W error::EncodingWarning`, the shape of
   `tests/repro/`'s subprocess scripts.
2. Select `PLW1514` by its exact code; `ruff check src tests tools`
   stays at 0.
3. A build-failing guard for what ruff misses (`os.fdopen` and
   `open` in text mode without `encoding=`): extend S2's AST sweep,
   or the `EncodingWarning` run over the modules that write files.
   Pick one, and say in the HISTORY entry why it can't miss a site.
4. `main.py`: `sys.stdout` and `sys.stderr` reconfigured to UTF-8
   with `errors="replace"` before anything prints (every platform; a
   no-op on macOS). The failing test prints a name outside cp1252
   through a cp1252 stream.

**Done when:** no text I/O in `src/` relies on the locale; the guard
fails on a planted site (paste it); the Windows job's encoding group
is gone.

---

## §4 — Windows' PATH stays whole; Docker Desktop starts (S4, PF-09, PF-15)

**Established.** PF-09 and PF-15. `wizard.py:619-640` already
branches on `darwin`/`win32` for the "Launch Docker Desktop" button.

**Hypothesis.** Docker Desktop 4.37 and later has
`docker desktop start` on macOS and Windows (Docker's docs;
UNVERIFIED here). Check its documentation and record the minimum
version; it changes nothing on macOS in this row.

**Do, one commit each, a failing test first.**
1. `ensure_full_path_environment()` does its work on macOS only:
   `path_helper` and the Homebrew fallbacks are macOS facts, and Linux
   already gets its session's PATH. The failing test: `sys.platform`
   patched to `"win32"`, PATH
   `C:\Windows\system32;C:\Program Files\Docker\Docker\resources\bin`,
   PATH unchanged after the call.
2. Windows' "Launch Docker Desktop": `docker desktop start` through
   S2's helper when it exists, else `os.startfile` on
   `%ProgramFiles%\Docker\Docker\Docker Desktop.exe` when that file
   exists, else today's "open it yourself" text. "Check again" stays
   the only judge of success. Tests over fakes, `sys.platform`
   patched.
3. No new `describe_error` branch for a Docker-on-Windows message
   until round 15 has observed one: Seeker never invents an error's
   wording.

**Split point:** after step 1.

---

## §5 — Sharing's Compose edits and path comparisons on Windows (S5, PF-13, PF-14)

**Established.** PF-13: the inserted volume line is a YAML
double-quoted scalar. The same line breaks on macOS too for a folder
whose name holds `"` or `\` (both legal there), and Compose's short
syntax splits on `:`, which a macOS folder name may also hold. PF-14:
Sharing compares paths as plain strings. No YAML parser is locked
(`uv.lock`).

**Do, one commit each, a failing test first.**
1. `pyyaml` in the dev group (§0.6); a test helper parses the Compose
   text Sharing produces.
2. The volume entry Sharing inserts is valid YAML for any path:
   single-quoted (`'` doubled), with Windows paths written with `/`
   (`PureWindowsPath.as_posix()`). The failing tests: a Windows path
   with `\U` and an apostrophe, and a macOS path with `"`, each
   parsed back to the intended source, target and `ro`.
   - If Compose's long syntax (`type: bind`, `source:`, `target:`,
     `read_only: true`) fits `_insert_compose_volume_line` and the
     duplicate check without a rewrite, prefer it: it has no `:`
     splitting at all. Record the choice and why.
3. One function turns a host path into a comparison key: on Windows
   case-folded with one separator and no trailing one; on macOS the
   path as today. Every comparison of a location with a mount
   `Source` goes through it. Docker Desktop's Windows `Source` form
   is UNVERIFIED (PF-14): leave one marked place for its mapping, and
   add the question to round 15's list (§0.5).

**Split point:** after step 2.

---

## §6 — The tray, the window icon, the menus and the words (S6, PF-24–PF-27, PF-31)

UI row: read `src/seeker/ui/CLAUDE.md` first. Screenshots before and
after (R12 §0.13); **the macOS screens must not change** except where
a step says so.

**Established.** PF-24 (`tray.py:123-147`), PF-25 (no
`setWindowIcon`), PF-26 (`main_window.py:912-990`), PF-27 (the string
list). The offscreen platform has no native menu bar, so the
harness's images may already show the in-window strip: look before
deciding anything.

**Do, one commit each, a failing test first where behaviour changes.**
1. Off macOS the tray uses the full-colour app icon
   (`seeker_icon.ico`), never `setIsMask`. macOS unchanged.
2. Off macOS the application gets a window icon from the bundled
   icons.
3. The menu bar off macOS: either a styled strip with Windows' words
   (Maximize for Zoom, an Exit, an explicit `Ctrl+,` for Settings,
   which `StandardKey.Preferences` doesn't bind on Windows), or no
   strip, with the shortcuts' actions added to the window so they
   still fire. Decide from screenshots of both themes; record why.
4. Platform words in one Qt-free module (services word some of
   them): the tray's place ("menu bar" / "system tray"), the
   notification's owner, the login-item settings (System Settings ›
   General › Login Items / Task Manager › Startup apps), the file
   manager, "this Mac" / "this PC", the user account, and the
   chromaprint hint (Windows' wording waits for S10's outcome: say
   only what is true at this commit). Every PF-27 site uses it. The
   test reads each string with `sys.platform` patched to `"darwin"`
   and to `"win32"`, and asserts each names its own platform's term
   and never the other's.
5. If budget is left: `tools/screenshots.py` on the Windows CI job,
   on `workflow_dispatch` only, uploaded as an artifact (PF-31's first
   look at Windows fonts and the menu strip).

**Split point:** after steps 1–2 (the icons).

---

## §7 — One Seeker at a time (S7, PF-23)

UI row: read `src/seeker/ui/CLAUDE.md` first.

**Established.** PF-23. `main_ui.main()` builds `Application`
(opening and migrating the database) before any window. The quit seam
and `cleanup_before_quit` are `src/seeker/ui/CLAUDE.md`'s.

**Do, one commit each, a failing test first.**
1. `ui/single_instance.py` over `QLocalServer`/`QLocalSocket`. The
   server's name is per user (Windows' pipe names are machine-wide;
   derive it from the per-user data folder), with
   `QLocalServer.SocketOption.UserAccessOption`. The protocol is one
   fixed message, "show". Anything else is ignored, and nothing
   received is ever opened, run or used as a path.
2. `main_ui.main()`, before `Application()`: if a server answers, send
   "show" and exit 0; otherwise remove a stale server (a crashed
   instance leaves its socket file on macOS) and listen. On "show",
   the running instance reopens its window through the window's
   public `reopen()`, or raises the wizard. The server closes in
   cleanup.
3. Tests: both ends in one process with `qtbot`; a stale name; a
   foreign message ignored; "show" reaching `reopen()`.

**Note for S11:** Inno Setup's `AppMutex` checks a named Win32 mutex,
which `QLocalServer` doesn't create. Either Seeker also creates one on
Windows (`ctypes`, `CreateMutexW`), or the installer relies on its
Restart Manager close. S11 decides; round 15 verifies.

**Split point:** after step 2's first half (a second instance exits),
before "show".

---

## §8 — Start at login on Windows (S8, PF-28)

**Established.** PF-28. `login_item.py`'s rule: status is read live,
never stored. `LoginItemStatus` has `NOT_SUPPORTED`, `DISABLED`,
`ENABLED`, `REQUIRES_APPROVAL`, `NOT_FOUND`.

**Hypothesis (UNVERIFIED until round 15).** Task Manager's switch
writes a binary value named after the Run entry under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run`,
whose first byte is even when enabled and odd when disabled. Code it
as a hypothesis, isolated in one function, and put it on round 15's
list.

**Do, one commit each, a failing test first.**
1. A Windows backend: supported when frozen on Windows. Enabled means
   a `Seeker` value under `HKCU\Software\Microsoft\Windows\
   CurrentVersion\Run` holding the quoted path of the running
   `Seeker.exe`. One pointing elsewhere (an older install) reads as
   off and is rewritten on enable. Task Manager's off switch reads as
   its own state, which Seeker reports and never overrides.
2. The registry is reached through a seam that tests replace with an
   in-memory fake; `winreg` is imported only on Windows (§0.2).
3. Settings → General shows the option on Windows, worded through
   S6's module.

**Done when:** both mypy runs are clean; the fake-registry tests cover
on, off, a stale path and Task Manager's switch.

---

## §9 — Windows' file-system rules (S9, PF-18–PF-22)

**Do, one commit each, a failing test first.**
1. **Peer names never carry a drive (PF-19).** Wherever a peer-chosen
   name is joined to a local folder (`placement.py:95`; `grep` for
   the others), a name with a drive or an anchor in Windows' terms is
   never joined; the lookup falls back to its tree search, which stays
   under the download folder. Test the guard as a pure function over
   `PureWindowsPath`.
2. **Reserved device names (PF-20).** `clean_path_component` suffixes
   `_` to a stem that equals `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`
   or `LPT1`–`LPT9` (any case), on every platform, since a library on
   an exFAT drive moves between machines. Tests for `con.flac`,
   `Nul`, `COM1.mp3`, and `CONSOLE.flac` (unchanged).
3. **A missing drive says so (PF-19).** `LibraryUnavailableError`'s
   hint also covers a Windows location whose drive root is missing
   ("Drive E: isn't connected"), worded with S6's terms where they
   apply.
4. **Renames retry over a held file (PF-21).** On Windows only, the
   renames in `files/atomic.py` (both) and placement's move retry a
   `PermissionError` whose `winerror` is 5 or 32 a bounded number of
   times (about 2 s in all), then fail with a sentence that
   `describe_error` words ("in use by another program"). macOS
   unchanged.
5. **Paths too long (PF-18).** A `describe_error` branch for
   `winerror` 206 and `errno.ENAMETOOLONG`, saying the path is too
   long for Windows and what to shorten. No `\\?\` handling until
   round 15 measures the need.
6. **PF-22's acceptance** written under the finding in `AUDIT.md`, in
   the manner of round 12's S-10, marked "icacls evidence pending
   round 15".

**Split point:** after steps 1–2.

---

## §10 — Fingerprinting on Windows (S10) **[ASK]**, PF-29

Ask Kris at the row's start, with this recommendation: **(a)**,
unless its build cannot be made reproducible within the row.

- **(a) Bundle `chromaprint.dll`.** Built in CI on `windows-2025`
  from a pinned Chromaprint source release (checked by SHA-256) with
  CMake, the bundled KissFFT backend (BSD) and no tools, so no ffmpeg
  or FFTW is dragged in (that build option is UNVERIFIED for the
  pinned release: read its `CMakeLists.txt`). `seeker.spec` adds it
  to `binaries` on Windows only; `_candidate_search_dirs()` already
  looks in `_MEIPASS` first. Its LGPL-2.1 and KissFFT's texts go into
  `licenses/` (`bundle_info.py`), and `docs/packaging.md` → Native
  libraries gains a row. Chromaprint reads decoded PCM only, so
  AUDIT S-03's surface does not grow.
- **(b) No fingerprinting on Windows in v0.3.0.** Duplicates says so
  in Windows' words, and everything else in Duplicates works.

Either way: ffmpeg stays the user's optional install on Windows
(`winget install Gyan.FFmpeg` puts it on PATH; UNVERIFIED wording,
check winget), and S6's module words the hint.

**Done when (a):** the smoke test on the Windows build reports
chromaprint available; a fingerprint test runs (not skips) on
`check-windows`.

---

## §11 — The Windows build in CI (S11, PF-35, PF-36)

**Established.** PF-35, PF-36. Round 13 S7's `build.yml` builds the
two Macs. `build_dmg.py` writes and deletes the build identity;
`build_windows_installer.py` doesn't.

**Hypotheses.**
- H1. Inno Setup installs on `windows-2025` from Chocolatey at a
  pinned version (or a pinned download checked by SHA-256).
- H2. `SeekerSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER`
  installs without a prompt on the runner, so CI can test the
  installer itself.

**Do, one commit each.**
1. The build identity's writer moves to one function both build
   scripts use (a refactor commit), and the Windows script writes and
   deletes it as the DMG script does.
2. `seeker.iss`: the version from `pyproject.toml`, passed as
   `/DMyAppVersion=…` (and `#error` when absent, so a second copy can
   never come back); `PrivilegesRequired=lowest` (per user, no UAC);
   the running-app handling decided with S7's note (`AppMutex` with a
   Seeker-created mutex, or Restart Manager alone). User data stays
   on uninstall; say so in `docs/packaging.md`.
3. `build.yml` gains `windows-2025`: sync, build, the smoke test on
   `dist\Seeker\Seeker.exe`, then the silent install, the installed
   app's smoke test twice (cold and warm JIT, so numba's cache in a
   per-user install is measured), the silent uninstall, and the
   installer uploaded as an artifact. A windowed build has no
   console, so the smoke test writes its report to the file named on
   its command line (round 13 §5).
4. Read the built `Seeker.exe`'s manifest for `longPathAware`, and
   whether `bundle_info.python_license()` found Python's licence
   (PF-35); fix the lookup if not. Both go in the HISTORY entry.

**Done when:** a dispatched `build.yml` run is green on all three
runners, with the Windows smoke reports (built, installed cold,
installed warm) in the HISTORY entry.

**Split point:** after the one-folder build passes the smoke test in
CI, before the installer.

---

## §12 — The Windows suite green and blocking (S12, PF-32)

**Do.** Work through what is left of S1's list, group by group. A
test bug: fix the test. A product bug: the Windows job's failure is
the failing test; fix it in its own commit. A skip: only for a
behaviour Windows doesn't have (permission bits, say, whose
substitute is PF-22's acceptance), naming what it excludes and why
that can't hide the bug the test exists for (working agreement 5).
Then remove `continue-on-error`. Record the list's count before and
after.

**Done when:** `check-windows` is green and blocking on two
consecutive runs.

**Split point:** at a group boundary of S1's list.

---

## §13 — A Windows VM pass (S13, optional; Kris)

Only if Kris sets up a Windows 11 on ARM virtual machine (phase
README → "Developing for hardware Kris doesn't have"). Kris installs
the CI-built `SeekerSetup.exe` in it; Code writes the checklist and
reads the results: SmartScreen's first-run screen, the wizard up to
Docker, both themes, display scaling at 100, 125 and 150 %, the tray
icon and menu, a notification, closing to the tray, a second launch
(S7), start at login (S8), Help → Build, "Show in folder", uninstall.
The app runs under x64 emulation there: a crash or a slow step may be
the emulator's, so anything odd goes onto round 15's list rather than
being fixed blind.

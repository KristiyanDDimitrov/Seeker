# Round 15 — Windows on real hardware, released as v0.3.0

**Status: provisional.** Written at phase-02 planning (2026-10-17),
before any Windows hardware was in hand and before round 14 ran. **S0
re-plans this round** against round 14's results and §0.7's list,
then Kris confirms the machine and the accounts. Until S0 has run,
treat every row below as a sketch.

**Executor:** Claude Code, running **on the Windows machine itself**
for S1–S6 and S8, and on Kris's Mac for S0, S7 and S9. **Phase:**
`docs/phase-02/README.md`. **Findings:** `docs/phase-02/AUDIT.md`.

Round 14 makes everything a Mac and CI can test Windows-ready and
leaves a CI-built `SeekerSetup.exe`. This round answers what only a
real Windows machine can: Docker Desktop's file sharing, the desktop
behaviour under a real session, drives, installs and upgrades. It
fixes what that shows, accepts the build and releases v0.3.0.

---

## §0 — Ground rules

**§0.1 Rounds 13's and 14's §0 apply** (phase 01's rules; the
platform rules; testing discipline; no `PYTHONUTF8`).

**§0.2 Working on the Windows machine.** Kris installs Git for
Windows, `uv`, Docker Desktop (with WSL 2) and Claude Code, clones the
repository, and signs `gh` in. A session there starts with
`git pull` and ends with a push, so `docs/HANDOFF.md` travels through
the repository as always. The three numbers for a Windows row come
from that machine, and CI covers macOS.

**§0.3 Whose data.** Everything Seeker touches on that machine is
test data in folders made for the test (`C:\SeekerTest\…`, say). If
the machine is borrowed: never scan, tag, move or read anything
outside those folders, and remove Seeker, its data
(`%LOCALAPPDATA%\Seeker`), the slskd container and Docker Desktop
(if installed for this) when the round ends, with the owner's say.

**Precondition:** no suite runs on this machine until R14-S2's
platformdirs isolation (HISTORY §268) is on main; R15-S0 checks it.

**§0.4 Accounts.** A **Spotify test account**: `src/seeker/spotify/CLAUDE.md` records that
two installs sharing a client ID can invalidate each other's rotating
refresh tokens (§92), so Kris's own account stays on his Mac. A
**Soulseek test username**: the network allows one session per
username, so Kris's would sign his Mac's slskd out.

**§0.5 Docker on the test machine.** Its slskd container is a test
instance made for this round. Code may start, stop and recreate it,
and only it (`docker ps` shows which), with Kris at the keyboard for
the first bring-up. This permission does not extend to Kris's Mac,
where `tests/CLAUDE.md`'s rule stands. The suite still never runs `docker`
(`conftest.py`).

**§0.6 Evidence replaces UNVERIFIED.** Every Windows behaviour
observed is written into the HISTORY entry with the command and its
output. The same commit removes the UNVERIFIED mark it settles, in
code comments, `CLAUDE.md`, `AUDIT.md` and `docs/packaging.md`.

**§0.7 Carried from round 14.** What a Mac and CI could not settle,
one line each: the claim, where it lives, how hardware settles it.
Planning seeded the list; each round-14 row appends to it.

- PF-13/PF-14: Compose accepts Sharing's new volume entry (quoting,
  `/` separators); the form of `Source` that `docker inspect` reports
  for a Windows bind mount; whether `is_self_managed`'s label
  comparison holds. *Settle:* bring-up, add a location to the share,
  `docker inspect`.
- PF-15: the wizard's Launch Docker Desktop
  (`docker_setup.launch_docker_desktop()`) runs `docker desktop start
  --detach` (Docker Desktop 4.37 on, Docker's docs), else opens
  `%ProgramFiles%\Docker\Docker\Docker Desktop.exe` with
  `os.startfile`. Unverified: the command starts Docker Desktop and
  returns at once; one older than 4.37 answers it with an error, not a
  hang; the executable's name; a per-user install
  (`%LOCALAPPDATA%\Programs\DockerDesktop`) without the command gets
  only the "open it yourself" text; what `docker info` prints while it
  starts. *Settle:* the wizard's button with Docker Desktop quit;
  `dir "%ProgramFiles%\Docker\Docker"`; Seeker's log for `docker
  desktop start exited`.
- PF-09: on Windows `ensure_full_path_environment()` leaves PATH as it
  is (`soulseek/docker_setup.py`), shown by unit tests on
  `check-windows`; that the installed app then finds `docker` and
  `ffmpeg` is UNVERIFIED. *Settle:* the wizard's Docker step with
  Docker Desktop running reads "Docker is running"; a duplicate check
  fingerprints.
- PF-16: what lands on NTFS when slskd writes a name with
  `: * ? " < > |` or a trailing dot or space. *Settle:* `docker exec
  slskd sh -c 'touch "/app/downloads/a:b?.flac"'` and friends, then
  `dir` on the host.
- PF-17: slskd's SQLite on the bind mount over a day of use.
  *Settle:* `docker logs slskd` for lock errors; slskd's own health.
- PF-18: `longPathAware` in `Seeker.exe`'s manifest (round 14 S11
  reads it); Windows' `LongPathsEnabled` on the machine; a placement
  past 260 characters. *Settle:* a crafted deep download folder.
- PF-21: a tag write while another program holds the file.
  *Settle:* open the file in a player, then tag it in Seeker.
- PF-22: the ACL on `%LOCALAPPDATA%\Seeker`. *Settle:* `icacls`.
- PF-23: a second launch brings the first forward (Start menu, a
  shortcut, the login item plus a click).
- PF-24/PF-25: the tray and window icons on a light and a dark
  taskbar.
- PF-28: Task Manager's switch for start at login, and the registry
  value it writes.
- PF-29: the bundled `chromaprint.dll` loads in the installed app
  (if round 14 S10 chose (a)).
- PF-30: shutdown and sign-out with a task running; an upgrade
  install with Seeker running.
- PF-31: scaling at 100, 125 and 150 %, and two monitors with
  different scaling.
- PF-37: SmartScreen's first-run screens; Microsoft Defender's verdict
  on the installer and the installed folder.
- numba's JIT cache in a per-user install: where it lands, cold and
  warm times on real hardware (round 14 S11 measured CI's).
- The tray on Windows 11: does a new icon land in the overflow, and
  which app name do notifications carry?
- Symlinks: every test that makes one passed on CI's `windows-2025`
  runner (run 41647752561, user `runneradmin`; whether it runs elevated
  or with Developer Mode is UNVERIFIED), so whether a standard account
  can make one is open (PF-32's three symlink tests; the app bundles
  that `test_bundle_check.py`, `test_bundle_info.py` and
  `test_smoke_test.py` build). *Settle:* those tests and modules as a
  standard user, Developer Mode off, then on.
- A console's code page: run 41647752561's log shows pytest's em dash
  as U+FFFD, so the runner's pipe is not UTF-8. Round 14 S3's control
  (`tests/test_main.py`, Windows only) has a child's piped stdout in
  `locale.getencoding()`, never UTF-8, on `check-windows`; what a
  console on a real machine reports is open. *Settle:* in a console,
  `chcp`, then `python -c "import locale, sys;
  print(locale.getencoding(), sys.stdout.encoding)"`.
- PF-12: the CLI writes UTF-8 to a console, a pipe and a file
  (`main.py` reconfigures both streams; PEP 528 says a console is
  UTF-8 already). `check-windows` shows a pipe only. *Settle:* a
  playlist named `Café 東京`, then `seeker playlists` in a console,
  and `seeker playlists > out.txt` opened as UTF-8.
- PF-11, the file half: Sharing writes the Compose file and
  `slskd.yml` as UTF-8 (`files/atomic.py`), and on Windows with CRLF
  line endings (text mode's, observed on `check-windows`, run
  43324253654); that Compose and slskd read both is UNVERIFIED.
  *Settle:* share `C:\SeekerTest\Café 東京`, then `docker compose
  config` shows the path whole and slskd lists the share, from the
  CRLF files that edit wrote.
- PF-10: no console window flashes from the windowed app.
  `processes.py` adds `CREATE_NO_WINDOW` to every program Seeker
  starts; `tests/test_processes.py` shows on `check-windows` only that
  a child has no console window (`GetConsoleWindow()` is 0, run
  42812791705). That does not show the flag at work: its control
  skipped there, since the runner's pytest has no console window to
  share, and a child without the flag that shares a console with no
  window would read 0 too (UNVERIFIED). *Settle:* the
  installed app in the tray with Sharing open (its `docker ps` and
  `docker inspect` polls), then a duplicate-detection run (one
  `ffmpeg` per file): no window appears.
- PF-10: the flag on a GUI program. Microsoft documents it as ignored
  for a program that is not a console one, so `explorer` still opens a
  folder, and Docker Desktop, which the wizard's `docker desktop start
  --detach` (a console program, started with the flag) starts in turn,
  still shows its window. *Settle:* Help → Open data folder; the
  wizard's Launch Docker with Docker Desktop quit.
- PF-11, the subprocess half: `docker` writes UTF-8 on Windows, which
  `processes.run(..., text=True)` reads, so a non-ASCII share path
  matches; read in the code page, its bytes never would. *Settle:*
  share `C:\SeekerTest\Café 東京`, then Sharing lists it as live.
- The suite's platformdirs isolation (§0.3's precondition):
  `tests/conftest.py`'s `_no_real_seeker_folders`, probed by
  `tests/test_platformdirs_isolation.py` on `check-windows` only
  (passed, run 42812791705). *Settle:* before the first suite run,
  list `%LOCALAPPDATA%\Seeker`
  with its times (if it exists), run that test file, then the suite,
  and list it again: nothing changed.

---

## §S0 — Re-plan this round (S0, on the Mac)

Read round 14's HISTORY entries and §0.7. Rewrite this brief's rows
S1–S6 to match what is actually left; move anything settled out of
§0.7. Update the session plan's estimates. Confirm with Kris: the
machine (x64, Windows 11 version), who owns it, the accounts (§0.4),
and the dates. The documents are the commit; there is no code change.

## §1 — Bring the machine up (S1)

On the Windows machine: `uv sync --locked`; the three numbers
natively (compare the suite with `check-windows`: any difference is
this machine's, and goes in the HISTORY entry); install the
CI-built `SeekerSetup.exe` from the latest green `build.yml` run;
record SmartScreen's screens and Defender's verdict (PF-37); first
launch, the wizard with the test Spotify account, a scan of a test
library folder, BPM and key on a few files beside the Mac's values,
Help → Build. No slskd yet.

## §2 — Docker Desktop and slskd, measured (S2)

No fixes in this row: measurements only, each with its command and
output. The wizard's Docker launch (PF-15); a bring-up with Windows
paths (data folder, share); `docker inspect`'s `Source` (PF-14);
Sharing's add-to-share end to end (PF-13); the file-name experiment
(PF-16); a long path (PF-18); then slskd left running a day for the
SQLite check (PF-17), read at S3's start. A search and a download
through the test Soulseek account, placed into the test library.

**Split point:** after the file-name experiment.

## §3 — Fix what S2 found (S3)

Provisional. Expected shapes: Sharing's comparison key learns the
measured `Source` form; the completed-file lookup learns the mapped
name form, or fails the request with a readable reason. If slskd's
SQLite fails on the bind mount, the template change (state in a named
volume, only `downloads/` and `slskd.yml` bind-mounted) is **[ASK]**:
it changes the Compose template, Sharing's edits and the leftover
rules, and every existing macOS install's per-user copy is never
re-seeded (HISTORY §222). One commit per fix, a failing test first.

## §4 — The desktop on real Windows (S4)

Scaling and fonts (PF-31), both themes, the tray (PF-24, overflow,
clicks, notifications), close, minimize and quit, a second launch
(PF-23), start at login with Task Manager's switch (PF-28), menus and
shortcuts (PF-26), shutdown and sign-out with a task running (PF-30),
`tools/screenshots.py` run natively. Small fixes in the row (one
commit each); the rest listed for S6.

## §5 — Files and the installer on real Windows (S5)

A test library on an external drive (exFAT or NTFS): a scan; the
drive unplugged during a scan; the drive back under another letter
(PF-19); "Show in folder"; long paths (PF-18); a tag write over a
held file (PF-21); `icacls` (PF-22). The installer: an upgrade with
Seeker running (PF-30's Restart Manager or `AppMutex`), an uninstall
(user data stays), numba's cache and timings in the installed app,
Defender on the installed folder (PF-37).

## §6 — Fix what S4 and S5 found (S6)

Provisional, like §3.

## §7 — Documents for Windows (S7, on the Mac)

`README.md`: Windows 11 x64, Docker Desktop with WSL 2 and
virtualization enabled, SmartScreen's "More info → Run anyway",
where data lives, how to uninstall. `docs/packaging.md`: the Windows
row with what was verified, on what machine, and when; the installer
build. `RELEASING.md`: the installer comes from `build.yml` on the
release tag (a clean machine, a recorded run), checked by its SHA-256
before it is attached; a Windows smoke test from the artifact.
`docs/cli.md`: running slskd natively on Windows as the manual option
(decision 2). `CHANGELOG.md`. `CLAUDE.md`: Windows standing facts,
each with its HISTORY §, replacing the UNVERIFIED ones.

## §8 — Release-candidate acceptance on Windows (S8) — Kris and Code

Code: the candidate from `build.yml` on an untagged commit, checksum,
smoke test, `docs/phase-02/round-15/ACCEPTANCE.md`. Kris, on the
machine: a fresh install from a browser download through SmartScreen,
the wizard end to end with the test accounts and a slskd bring-up, a
playlist download placed into the test library, tagging, Duplicates,
the tray, start at login, an upgrade over the previous candidate, an
uninstall. Waived boxes are recorded as waived, as in round 12.

## §9 — Publish v0.3.0; close round 15 and phase 02 (S9, on the Mac)

`RELEASING.md` for all three builds (Kris approves each outward
step). v0.3.0 carries `SeekerSetup.exe`, `Seeker.dmg`,
`Seeker-Intel.dmg` and their `.sha256` files: round 14 changed code
the Macs run too (the subprocess helper, encodings, the single
instance, Sharing's YAML), and every installed copy's update check
will see v0.3.0 as the latest release, so it must have a build for
each. The update check from all three builds. Measure the phase's exit criteria (phase README) and record
them. `docs/status.md`'s Roadmap and `docs/README.md` close phase 02.

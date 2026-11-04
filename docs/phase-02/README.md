# Phase 02 — Seeker on Intel Macs and Windows

**Planned 2026-10-17** (planning session, base commit `2b7e8d9`, the
S18 handoff after v0.1.0). Phase 01 (`../phase-01/`) shipped Seeker
for one platform: macOS 15 or later on Apple silicon. Phase 02 makes
the same app install, run, test and release on **Intel Macs** and on
**Windows laptops**, without a second code base and without
weakening anything Apple silicon has today.

The findings this plan rests on, each with its evidence, are in
[`AUDIT.md`](AUDIT.md) (`PF-01`…`PF-38`). The work is in three
rounds, each with a brief and a session plan, in the same handoff
structure phase 01 used.

---

## What "supported" means at the end of the phase

| Platform | Built by | Tested on every push | Accepted on real hardware | Released |
|---|---|---|---|---|
| macOS 15+, Apple silicon | Kris's Mac (unchanged) | CI `macos-26` (unchanged) | Kris's M4 Pro | v0.1.0 onwards |
| macOS 15+, Intel (x86_64) | Kris's Mac under Rosetta 2 | CI `macos-15-intel` (new) | Rosetta on the M4 Pro; a real Intel Mac if one is found | **v0.2.0** (round 13) |
| Windows 11, x64 | CI `windows-2025` (new) | CI `windows-2025` (new) | a borrowed x64 PC or laptop | **v0.3.0** (round 15) |

Windows 10 22H2 is best effort: Microsoft ended its support on
2025-10-14, and nothing in the plan tests it. Windows on ARM runs the
x64 build under emulation (PF-38) and is not tested unless the
borrowed machine happens to be one. Linux stays where phase 01 left
it: written, never verified (`../packaging.md`), out of scope.

---

## Kris's decisions (2026-10-17)

These are decisions. Sessions do not ask again.

1. **Intel first.** v0.2.0 adds the Intel Mac build as soon as it
   passes CI, Rosetta and (if one is found) a real Intel Mac. Windows
   ships later as its own release, after real-hardware acceptance.
2. **Windows runs slskd through Docker Desktop**, the same single
   bring-up as macOS. A natively run slskd stays a documented manual
   option: `slskd_download_dir` already points Seeker at any slskd's
   download folder (`../cli.md`). Revisit only if round 15's hardware
   tests fail (PF-16, PF-17).
3. **No code signing in phase 02.** macOS stays ad-hoc signed, not
   notarized, as in v0.1.0; the Windows installer is unsigned. Each
   platform's first-launch steps are documented. A signing row stays
   parked (round 15 → "Parked").
4. **Rounds continue the global numbering:** `round-13`, `round-14`,
   `round-15` under `docs/phase-02/`, so "round 12 S17" and every
   HISTORY title stay unambiguous.

## Planning decisions (Code's, with reasons; Kris can veto)

- **One DMG per architecture, not a universal2 app.** Intel needs
  numba 0.62.1 and Apple silicon runs 0.67.0 (PF-01); two versions of
  one library cannot be fused into one binary, and PyInstaller's
  universal2 mode needs every bundled binary fat. Shipping only an
  x86_64 build for both was rejected: it runs on Apple silicon only
  through Rosetta, which Apple is winding down.
- **Asset names keep today's links working.** `Seeker.dmg` stays the
  Apple silicon image (the name v0.1.0 used, and whatever links to
  `releases/latest/download/Seeker.dmg`); the Intel image is
  `Seeker-Intel.dmg`; Windows adds `SeekerSetup.exe`. Each has a
  `.sha256` beside it.
- **Intel gets its own pins; nothing else moves.** Marker-scoped
  constraints hold numba, llvmlite and numpy back on
  `darwin`/`x86_64` only (round 13 §2). Rejected: one older set for
  every platform (it holds Apple silicon and Windows back for Intel's
  sake), and replacing librosa (PF-08: the right long-term fix, but a
  rewrite of BPM and key detection; parked as a direction).
- **Intel's minimum is macOS 15.0**, measured: PySide6 6.11.2's
  binding modules declare `minos 15.0` in their x86_64 slice too
  (PF-04). Going lower would mean a second, older Qt on Intel only.
- **The Windows installer installs per user** (no UAC prompt; the
  install folder stays writable for numba's JIT cache, PF-36).
- **Windows fixes are built and tested on the Mac first** (round 14),
  so round 15's scarce hardware time goes to what only hardware can
  answer.

---

## Developing for hardware Kris doesn't have

Every rung is listed, with what it cannot see.

### Intel

1. **Rosetta 2 on the M4 Pro** (the primary environment). Observed
   2026-10-17: Rosetta is installed (`arch -x86_64` runs), and
   python.org's universal2 Python 3.13.5 runs as `x86_64`. Round 13
   S3 sets up a second, x86_64 virtual environment beside `.venv` and
   runs the whole suite in it; S6b builds the Intel app in it. Rosetta
   translates AVX and AVX2 but not AVX-512 (secondary sources,
   UNVERIFIED with Apple), which matters for numba's JIT.
2. **GitHub's `macos-15-intel` runner** (real x86_64, macOS 15): the
   suite on every push (round 13 S4) and the frozen app's smoke test
   (S7). GitHub retires it, its last Intel macOS image, in fall 2027
   ([GitHub changelog, 2025-09-19](https://github.blog/changelog/2025-09-19-github-actions-macos-13-runner-image-is-closing-down/)).
3. **A real Intel Mac**, if Kris finds one: round 13's acceptance
   checklist, especially Docker Desktop for Intel and the speed of
   analysis on older hardware.

No container or virtual machine runs Intel macOS on Apple silicon:
Apple's virtualization runs guests of the host's own architecture,
and Docker cannot run macOS at all. Rosetta is the emulator.

### Windows

1. **GitHub's `windows-2025` runner**: the suite (offscreen Qt), mypy,
   the PyInstaller build and the Inno Setup installer (round 14). It
   cannot run slskd: no Docker Desktop and no Linux containers.
2. **`mypy --strict --platform win32 src/`** on the Mac: type-checks
   every `sys.platform == "win32"` branch, which today's mypy run
   skips as unreachable (PF-33).
3. **A Windows 11 on ARM virtual machine on the M4 Pro** (optional;
   UTM and VMware Fusion are free, Parallels is paid): the installed
   app's look, tray, notifications and dialogs, with the x64 build
   running under Windows' x64 emulation. Docker Desktop inside it
   needs nested virtualization: UNVERIFIED, so don't count on it.
4. **A borrowed x64 Windows 11 machine with Claude Code installed on
   it** (round 15): Code runs the suite natively there, reads the
   logs, and drives Docker Desktop experiments, with Kris at the
   keyboard for anything outward-facing. It uses test accounts only
   (round 15 §0).

### What each rung covers

| Risk | Rosetta | Intel CI | Real Intel Mac |
|---|---|---|---|
| x86_64 wheels install and import | yes | yes | yes |
| The suite on x86_64 | yes | yes | yes |
| The frozen x86_64 app starts | yes | yes (smoke) | yes |
| Intel Homebrew in `/usr/local` (chromaprint, ffmpeg) | no | yes | yes |
| Docker Desktop for Intel with slskd | no | no | yes |
| Speed on older hardware (JIT cold start) | no | partly | yes |

| Risk | CI | `mypy --platform` | ARM VM | Real x64 PC |
|---|---|---|---|---|
| Dependencies install and import | yes | — | yes | yes |
| The suite | yes | — | yes | yes |
| Type errors in Windows branches | yes | yes | — | — |
| The frozen app and installer build | yes | — | runs them | runs them |
| Look, DPI scaling, tray, notifications | screenshots only | — | yes (emulated) | yes |
| Docker Desktop, slskd, bind mounts | no | — | UNVERIFIED | yes |
| External drives, drive letters | no | — | partly | yes |
| Shutdown, upgrade-in-place, SmartScreen | no | — | yes | yes |
| Speed (JIT, scan) | no | — | no | yes |

---

## Rounds

| Round | Goal | Ends with | Needs | Status |
|---|---|---|---|---|
| [13](round-13/SESSION-PLAN.md) | Intel Macs | **v0.2.0**: `Seeker.dmg` (Apple silicon) and `Seeker-Intel.dmg` | this Mac; a real Intel Mac optional | **done**: v0.2.0 released 2026-11-04 |
| [14](round-14/SESSION-PLAN.md) | Windows readiness, from the Mac and CI | a tested, CI-built `SeekerSetup.exe` artifact (not released) | nothing new; a VM optional | **next** |
| [15](round-15/SESSION-PLAN.md) | Windows on real hardware | **v0.3.0** with `SeekerSetup.exe` | an x64 Windows 11 machine | provisional: re-planned at its start against round 14's results |

**From 2026-11-03 the rest of the phase runs as one autodev plan:**
[`autodev/SESSION-PLAN.md`](autodev/SESSION-PLAN.md) (round 13's release,
round 14, round 15's re-plan). Round 14's rows that change code waited
for v0.2.0's release (Kris, 2026-11-03), published 2026-11-04. The
two share only `ci.yml`, `build.yml`, `pyproject.toml` with
`uv.lock`, `RELEASING.md` and `packaging/`; whichever lands second
builds on the other's change, never over it.

**Reading order for a session:** `../HANDOFF.md` → your row in your
round's `SESSION-PLAN.md` → that round's `BRIEF.md` §0 plus your
row's § → each `AUDIT.md` finding your § names (`grep -n "PF-NN"`) →
`../../CLAUDE.md` (and `src/seeker/ui/CLAUDE.md` for a UI row).

---

## The clock

- **numba** stopped publishing Intel macOS wheels after 0.62.1
  (2025-09-29), and llvmlite after 0.45.1. Intel's pins (round 13 §2)
  are permanent.
- **GitHub's Intel runners** end in fall 2027 (above). After that,
  Intel builds are made and tested only under Rosetta.
- **Rosetta's full support** continues through macOS 27; Apple
  plans to keep only a subset for older games from macOS 28
  ([Eclectic Light, 2026-03-14](https://eclecticlight.co/2026/03/14/how-to-survive-the-loss-of-rosetta/),
  a secondary source). **macOS 26 is the last release for Intel Macs**
  (Apple's compatibility list as reported by
  [Macworld](https://www.macworld.com/article/2808358/if-you-own-an-intel-mac-you-have-12-months-to-upgrade-to-a-new-model.html)).

So Intel support has a horizon of roughly 2027–28. Round 13's
close-out records the rule for ending it: the last release that
still builds and tests on Intel becomes Intel's final version, and the
README says so.

---

## Exit criteria for the phase

Each is a number or a yes/no, measured at round 15's close-out.

- CI is green on `macos-26`, `macos-15-intel` and `windows-2025` on
  the release commit; every job is blocking; branch coverage on
  `macos-26` is at or above the floor.
- `mypy --strict src/` and `mypy --strict --platform win32 src/` are
  clean; `ruff check src tests tools` reports 0.
- v0.2.0 is published with `Seeker.dmg` and `Seeker-Intel.dmg` and
  their SHA-256s; the Intel app passed the smoke test on the Intel
  runner and round 13's acceptance under Rosetta.
- v0.3.0 is published with `SeekerSetup.exe` and its SHA-256; round
  15's acceptance checklist passed on a real x64 Windows machine,
  with every waived box recorded.
- Every `AUDIT.md` finding is fixed, or accepted with a written
  reason.
- `README.md`, `docs/packaging.md` and `RELEASING.md` describe all
  three builds; each platform's row in `docs/packaging.md` says what
  was verified on real hardware, and when.

## Out of scope

- Linux support or packaging; its existing branches must not
  regress.
- A native Windows ARM64 build (PF-38).
- Code signing and notarization (decision 3).
- A Seeker-managed native slskd (decision 2).
- Replacing librosa (PF-08), unless Kris approves the parked row.
- Intel Macs below macOS 15 (PF-04).

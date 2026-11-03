# Round 14 — session plan

**Purpose: keep each Claude Code session inside a predictable token
budget.** This file is the index. The task text is in
`docs/phase-02/round-14/BRIEF.md`; the findings it fixes are in
`docs/phase-02/AUDIT.md`. Nothing here repeats them.

**Budget: 150 K ceiling, ~120 K target**, with phase 01's three rules:
one cohesive change per row; stop at the row's boundary even with
budget left; if a row overruns, stop at its named split point, commit,
and say exactly where you stopped.

The order: let Windows CI show the real failure list first (S1); then
the cheap fixes every other Windows path depends on (S2–S4); then
Sharing (S5) and the desktop (S6–S8); then the file system (S9) and
fingerprinting (S10); then the installer (S11) and a blocking job
(S12). No Windows hardware is needed. The round can pause after any
row without leaving the codebase worse than it found it.

---

> **Execution moved (2026-11-03):** this round's open rows run in
> [`../autodev/SESSION-PLAN.md`](../autodev/SESSION-PLAN.md), an
> `autonomous-development` plan; status lives in its `tasks.json`.

## Session map

`§` points into this round's `BRIEF.md`. **[ASK]** rows start only
after Kris's explicit yes.

| # | Session | Executes | Est. | Split point if overrunning |
|---|---|---|---|---|
| ☐ S1 | Windows CI job (non-blocking); the grouped failure list; `mypy --platform win32` (PF-32, PF-33) | §1 | ~100 K | After the failure list |
| ☐ S2 | One way to run a subprocess: no console windows, UTF-8 output, a sweep; the docker guard by stem (PF-10, PF-11, PF-34) | §2 | ~110 K | After docker_setup and sharing move |
| ☐ S3 | UTF-8 for every text file, with a build-failing guard; the CLI's output (PF-11, PF-12) | §3 | ~90 K | After the file sites |
| ☐ S4 | Windows' PATH left whole; "Launch Docker Desktop" on Windows (PF-09, PF-15) | §4 | ~90 K | After the PATH fix |
| ☐ S5 | Sharing's Compose line valid YAML for any path; one path-comparison key (PF-13, PF-14) | §5 | ~110 K | After the YAML line |
| ☐ S6 | Tray and window icons, menus and platform words off macOS (PF-24–PF-27, PF-31) | §6 | ~110 K | After the icons |
| ☐ S7 | One Seeker at a time: `QLocalServer`, "show" (PF-23) | §7 | ~110 K | After a second instance exits |
| ☐ S8 | Start at login on Windows, over a registry seam (PF-28) | §8 | ~100 K | After the backend, before Settings |
| ☐ S9 | Windows file-system rules: drive-safe joins, reserved names, rename retries, long-path wording; PF-22 accepted (PF-18–PF-22) | §9 | ~120 K | After drive-safe joins and reserved names |
| ☐ S10 | **[ASK]** Fingerprinting on Windows: a CI-built `chromaprint.dll`, or none in v0.3.0 (PF-29) | §10 | ~110 K | After the DLL builds in CI |
| ☐ S11 | The Windows build in CI: identity, per-user installer, smoke test built and installed (PF-35, PF-36) | §11 | ~120 K | After the one-folder build's smoke test |
| ☐ S12 | The Windows suite green; the job blocking (PF-32) | §12 | ~120 K | At a group boundary of S1's list |
| ☐ S13 | *Optional, Kris:* a Windows 11 on ARM VM pass over the CI-built installer | §13 | ~80 K | — |

### Why this order

- **S1 first:** the Windows job's failure list is evidence; planning's
  list is a reading of the code. Every later row reports against S1's
  list (the tracked number).
- **S2 before S3, S4, S5 and S10:** they all run programs, and the
  helper is where Windows' console flag and UTF-8 output live once.
- **S4's PATH fix is a blocker** (PF-09) but needs S2's helper for the
  Docker launch, so it comes after S2, not first.
- **S5 before S6:** both small, but S5 fixes a feature that fails
  outright on Windows; S6 is presentation.
- **S6 before S8:** Settings' login-item text uses S6's platform
  words.
- **S7 before S11:** the installer's handling of a running Seeker
  depends on how S7 identifies the running instance.
- **S10 before S11:** the installer bundles what S10 builds. If Kris
  answers (b), S11 goes straight on.
- **S12 last:** some failures in S1's list disappear with S2–S11's
  fixes; S12 finishes the rest and makes the job blocking.
- **S13 whenever an installer exists** (after S11), only if Kris
  wants it.
- **Round 13 may still be running.** Shared files are `ci.yml`,
  `build.yml` and `packaging/`; land on top of the other round's
  change, never over it.

---

## Skills: resolve these at the start of every session

List your available skills and resolve their real names first.

| Rows | Reach for |
|---|---|
| S1, S11, S12 | `ci-cd-pipeline-builder` or `senior-devops`; `senior-qa` for S12's triage |
| S2–S5, S7–S9 | `tdd` (a failing test first); `focused-fix` for S5 |
| S6 | `frontend-design` (screenshots, both themes); `tdd` |
| S7, S8, S10 | `security-review` (a local socket, the registry, a native library in the bundle) |
| S10 | `dependency-auditor` (the DLL's version and licence) |
| S13 | `senior-qa` (the checklist) |
| Any row, optional | `adversarial-reviewer` before close-out; `self-eval` |

If a skill contradicts the brief, follow the skill for **how** and the
brief for **what**, and record the divergence in the handoff.

---

## Session protocol

As round 13's (`docs/phase-02/round-13/SESSION-PLAN.md` → "Session
protocol"), plus:

- **Ending:** quote the three numbers natively, the `win32` mypy
  result, and the Windows job's summary line from its latest run;
  say which entries of S1's list your row closed.
- **Every row** appends what it could not verify to round 15's
  §0.7 list (BRIEF §0.5).

---

## Waiting on Kris

**Approval gates:**
- [ ] **S10:** (a) bundle a CI-built `chromaprint.dll`, or (b) no
      fingerprinting on Windows in v0.3.0. BRIEF §10 recommends (a).

**Optional:**
- [ ] **S13:** set up a Windows 11 on ARM VM (UTM and VMware Fusion are
      free; Parallels is paid) if you want an early look before the
      hardware round. Not needed for anything else in this round.

**For round 15, start looking now:** an x64 Windows 11 PC or laptop
you can install software on for a few sessions (Docker Desktop with
WSL2, Claude Code, Git, uv); a Spotify test account; a Soulseek test
username. Round 15's plan says why each one.

---

## Exit criteria

Measured in S12's close-out (or S13's, if it runs). Each one is a
number or a yes/no.

- `check-windows` is green and blocking; S1's list is at 0, with
  every skip named.
- `mypy --strict --platform win32 src/` is clean in `check`.
- No subprocess call outside the helper (the sweep); no text I/O
  without an encoding (the guard).
- Every finding assigned to round 14 in `AUDIT.md` is fixed, or
  accepted with a written reason; every claim left UNVERIFIED is on
  round 15's list.
- `build.yml` builds `SeekerSetup.exe` on `windows-2025`; it installs
  and uninstalls silently there, and the installed app passes the
  smoke test cold and warm.
- macOS is unchanged where no step said otherwise: the three numbers,
  and the screenshots.

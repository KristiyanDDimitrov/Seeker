# Round 15 — session plan (provisional)

**Provisional until S0 re-plans it** against round 14's results. The
task text is in `docs/phase-02/round-15/BRIEF.md`; nothing here
repeats it.

**Budget: 150 K ceiling, ~120 K target**, with phase 01's three rules:
one cohesive change per row; stop at the row's boundary; if a row
overruns, stop at its named split point, commit, and say where.

Hardware time is the scarce thing in this round. The order spends it
on measurement first (S1, S2), then on fixes that need the hardware
to verify (S3), then on the parts of Windows a person uses every day
(S4, S5), and keeps documents and the release on the Mac (S7, S9).

---

## Session map

| # | Session | Where | Executes | Est. | Split point |
|---|---|---|---|---|---|
| ☐ S0 | Re-plan this round from round 14's results; Kris confirms machine and accounts | Mac | §S0 | ~60 K | — |
| ☐ S1 | Bring the machine up: suite natively, CI installer, first launch, wizard, scan | Windows | §1 | ~100 K | After the suite and the install |
| ☐ S2 | Docker Desktop and slskd measured: launch, `Source`, Sharing, file names, long paths, SQLite (PF-13–PF-18) | Windows | §2 | ~110 K | After the file-name experiment |
| ☐ S3 | Fix what S2 found (a template change is **[ASK]**) | Windows | §3 | ~120 K | Per fix |
| ☐ S4 | The desktop: scaling, tray, quit, shutdown, single instance, login item, menus (PF-23–PF-31) | Windows | §4 | ~120 K | After scaling and the tray |
| ☐ S5 | Files and the installer: drives, long paths, held files, ACLs, upgrade, uninstall, JIT, Defender (PF-18–PF-22, PF-30, PF-37) | Windows | §5 | ~110 K | After the drive checks |
| ☐ S6 | Fix what S4 and S5 found | Windows | §6 | ~120 K | Per fix |
| ☐ S7 | Documents for Windows: README, packaging, RELEASING, cli.md, CHANGELOG, CLAUDE.md | Mac | §7 | ~90 K | After README and RELEASING |
| ☐ S8 | Release-candidate acceptance on Windows (**Kris and Code**) | Windows | §8 | ~80 K | — |
| ☐ S9 | Publish v0.3.0 (Kris approves the outward steps); close round 15 and phase 02 | Mac | §9 | ~60 K | — |

### Why this order

- **S0 first:** this plan was written before round 14 ran; its rows
  must match what is actually left.
- **S1 before S2:** a machine whose suite and installed app work is
  the baseline every later observation is compared with.
- **S2 measures, S3 fixes:** a measurement session that also fixes
  runs out of budget halfway through both. S2's split point keeps the
  file-name experiment, the riskiest unknown (PF-16), in the first
  half.
- **S4 and S5 before S6:** one fix session for the desktop and file
  findings, after both lists exist, so related fixes land together.
- **S7 on the Mac:** documents don't need the hardware, so the
  hardware time goes to S8.

---

## Parked (not scheduled; each **[ASK]**)

Raised during planning, deliberately left out of phase 02. Any of
them becomes a row only with Kris's yes.

- **P1 — Code signing.** Windows: a free open-source signing service
  (the SignPath Foundation signs CI builds for qualifying projects)
  or a paid certificate; macOS: notarization through the Apple
  Developer Program. Decision 3 (2026-10-17) parked it.
- **P2 — Re-point a library location.** A drive that comes back under
  another letter (PF-19), or a renamed macOS volume, leaves its
  location dead. Moving a location to a new root path, keeping its
  matches.
- **P3 — Replace librosa** (PF-08): tempo and key in numpy/scipy,
  measured against librosa on the X9 Pro samples first. Removes
  numba, the Intel pins, the cold JIT and the one-folder constraint.
- **P4 — A Seeker-managed native slskd on Windows**, only if Docker
  Desktop fails round 15's tests (decision 2).
- **P5 — A native Windows ARM64 build** (PF-38), once soxr publishes a
  `win_arm64` wheel and a tester has ARM hardware.
- **P6 — Start hidden only when launched at login, on Windows.** The
  Run entry can pass an argument; macOS can't tell a login launch
  apart (`main_ui.py`), so this is a parity choice.
- **P7 — Linux packaging** (AppImage or `.deb`), out of scope.

---

## Skills: resolve these at the start of every session

| Rows | Reach for |
|---|---|
| S1, S4, S5, S8 | `senior-qa` (checklists, evidence), `run` for driving the app |
| S2 | `performance-profiler` (a share scan over the bind mount), `research` for Docker Desktop's documented behaviour |
| S3, S6 | `tdd`, `focused-fix`; `security-review` for a template change |
| S7, S9 | `changelog-generator`, `runbook-generator`, `ship-gate` |
| Any row, optional | `adversarial-reviewer` before close-out; `self-eval` |

---

## Session protocol

As round 13's, plus BRIEF §0.2: **on the Windows machine, `git pull`
first and push last**, and the three numbers come from that machine.

---

## Waiting on Kris

**Before S0:**
- [ ] An x64 Windows 11 PC or laptop you can install software on for
      the round (an ARM laptop tests only the emulated path, PF-38),
      and whether it is borrowed (BRIEF §0.3).
- [ ] On it: Git for Windows, `uv`, Docker Desktop with WSL 2, Claude
      Code; the repository cloned; `gh` signed in.
- [ ] A Spotify test account and a Soulseek test username (BRIEF
      §0.4).

**Approval gates:**
- [ ] **S2:** the first slskd bring-up on the test machine, at the
      keyboard.
- [ ] **S3, if needed:** the Compose template change for slskd's state.
- [ ] **S9:** the exact tag, push and release commands, and the notes.

---

## Exit criteria

The phase's (`docs/phase-02/README.md` → "Exit criteria for the
phase"), measured in S9's close-out.

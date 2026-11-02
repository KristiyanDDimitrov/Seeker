# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 2 K tokens: a baton, not
a log. The log is `docs/history/` (short tier: `docs/history/README.md`,
grep it, never read it whole). **The plan is
`docs/phase-02/round-13/SESSION-PLAN.md`**, with status in `tasks.json`
beside it. Every document: `docs/README.md`.

---

## 1. Current state

- **Released: v0.1.1** (2026-10-26), tag `v0.1.1` on `e470d1c`: a
  security release. It has no HISTORY entry yet; S1b writes it.
- **HEAD:** S0's close-out on top of `8997f5f` (the split). Tree clean
  but for Kris's two untracked PDFs.
- **The three numbers (S0, X9 Pro not mounted):** pytest `2390 passed, 29 skipped`;
  mypy `--strict src/` clean, 146 files; ruff `check src tests tools` 0. With the drive: `2418 passed,
  1 skipped` (§245).
- **CI:** run `41435308234` green on `f3bd633` (S0's close-out): check and
  audit both passed.

## 2. Where we are

Round 13 (Intel Macs → v0.2.0), 18 rows. **S0 is done** (§246).
**Next: wave 1**, started with "Read docs/HANDOFF.md and lead wave 1"
(the plan's Execution section). Its lead first measures the new B
(`tokens.py measure --last 1`) into `tasks.json` and this file.

**Wave 1's first attempt (2026-11-02) stopped before any row:** the
process had started at 11:36, before S0 created `.claude/agents/`
(12:48) and turned the plugins off (13:05). `/clear` reloaded neither:
`row-worker` and `suite-runner` were "not found" and product-skills
was still listed. Kris restarts Claude Code, runs `/context`, then
relaunches wave 1. Measured then, B = 52 K (`tokens.py`, base of
that session); the relaunch measures again.

## 3. Session report (S0, 2026-11-02)

- `CLAUDE.md`: 37.1 KB → 15.4 KB core plus six topic files and
  `docs/status.md`, moved by script by line range (`8997f5f`); 363
  moved lines, each exactly once; link check 0 broken (two old false
  positives).
- Plugins off in `.claude/settings.local.json` (untracked).
- `/context` was not captured at the start: **Kris runs it at wave
  1's start**, and the split goes into wave 1's report.
- Peak 120 K (base 61 K, work 58 K against 45 K est.).

## 4. Key context for the next session


- **Intel's blocker is wheels, not code** (PF-01): numba 0.62.1 and
  llvmlite 0.45.1 are the last with Intel macOS wheels; numba 0.62.1
  needs numpy < 2.4. The lock still holds 0.67.0, 0.49.0 and 2.5.3
  (read 2026-11-02); uv is 0.12.5.
- **Intel's floor is macOS 15** (PF-04). **Rosetta runs here**
  (`arch -x86_64`, observed 2026-11-02).
- **The test account shares this Mac's Docker**: no slskd bring-up in
  round 13's Rosetta acceptance (BRIEF §9).
- **Dependabot:** #12 and #13 replaced #10 and #11 (setup-uv 10.3.2,
  slskd 0.26.2). Eight are open: #1, #5–#9, #12, #13.
- **The website's Download button** points at
  `releases/latest/download/Seeker.dmg` (read 2026-10-30), which the
  planned asset names keep working.
- **Spotify Premium:** neither the README nor the wizard mentions it
  (grep, 2026-11-02). S1d adds it.
- **Topic `CLAUDE.md` files load on a Read-tool read** in their folder
  (observed in S0 for `soulseek/`, §246); through Bash, UNVERIFIED.
  The core's index names each file; read one by hand when unsure.
  Accepted risks, Open issues and the Roadmap are in `docs/status.md`.
- **Plugins:** marketing-skills and product-skills are `false` in
  `.claude/settings.local.json` from S0 on; the next session's skill
  listing shows whether that took.
- **Subagents, UNVERIFIED until wave 1 records them:** custom agents
  load at session start; subagents get `CLAUDE.md`; none can spawn
  another; `isolation: "worktree"`'s branch, location and cleanup; a
  worker's baseline and transcript location. The plan → Execution.
- HISTORY continues at §247 in `docs/history/241-270.md`.

## 5. Decisions made

- **Kris (2026-10-17):** Intel first as v0.2.0, Windows later as its
  own release; Windows runs slskd through Docker Desktop; no code
  signing in phase 02; rounds continue at 13.
- **Kris (2026-11-02):** S0 splits `CLAUDE.md` into a core plus
  path-scoped topic files and turns marketing-skills and
  product-skills off for this folder (`.claude/settings.local.json`);
  Spotify Premium gets its own row (S1d).
- **Kris (2026-11-02):** rows run in parallel waves, a lead session
  plus row-worker subagents in git worktrees; token limits are not a
  concern, context rot and speed are.
- **Planning (Code's; reasons in the phase README; Kris can veto):**
  one DMG per architecture (`Seeker.dmg` stays Apple silicon, beside
  `Seeker-Intel.dmg`); Intel-only pins; macOS 15 on Intel; a per-user
  Windows installer; Windows fixes built on the Mac first.
- **Kris (2026-11-02, wave 1):** yes to S1b and S1c, the [ASK]
  rows; each merge still needs his approval.
- **Re-plan (Code's, 2026-11-02):** rows are capped at 65 K of work
  because B is 54–62 K; the brief's § numbers stay, and splits take a
  suffix (S1b–S1d, S2b, S3b, S5b, S6b).
- HISTORY entries and archived briefs keep their `docs/rounds/…`
  paths as written; `docs/rounds/README.md` resolves them.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Round 13:** Each wave: Kris starts the lead session; questions
arrive through it. Wave 1: `/context` at the start. S1b, S1c: each
merge. S9:
the Intel image in the test account (BRIEF §9); an Intel Mac if one
turns up. S10: each outward step. After S10: an Intel download on the
website.

**Later rounds:** R14 S10 **[ASK]**: fingerprinting on Windows, (a) a
bundled `chromaprint.dll` or (b) none in v0.3.0; an optional VM (S13).
R15: an x64 Windows 11 machine with Claude Code, Docker Desktop and
uv; a Spotify test account; a Soulseek test username.

**Carried from phase 01:** RELEASING.md step 5.2–5.3 for v0.1.0; the
waived boxes in `docs/phase-01/round-12/ACCEPTANCE.md`, as
post-release checks; item 125 is narrowed, not closed.

## 9. Open questions

Carried from phase 01, unanswered; detail in S18's handoff
(`git show 2b7e8d9:docs/HANDOFF.md`, field 9) and HISTORY §223,
§238–§241:
- Review: should a busy slskd end Confirm all (S17l)? Resolve all
  opens its dialog when every group is on "Keep all" (S17m).
- The dark-mode question icon on the quit confirmation (S17o).
- Downloads: record a busy pick for a later poll; "Queued as backup"
  in the header; cancel a superseded row's transfer; slskd's "remove
  finished transfers"; how long a settled file may queue; Cancel on a
  downloading row, "Retry all", marking an activated backup;
  Search's unscored "—".
- Setup: "Match tracks" during a scan; a CLI command that starts
  slskd; a share folder that's missing; the wizard's share checkbox
  default; does a fresh slskd share anything by default?
- Sweep: skip a needs-review candidate still waiting; a GUI and a
  cron sweep at once (UNVERIFIED how they interleave).
- Code: a socket timeout for the OAuth callback; `measure_signal()`
  has no caller (show it on Duplicates, or delete it with pyloudnorm).
- Should a template bump reach an existing install's Compose copy
  (never re-seeded, §222)? Dependabot #13 bumps slskd.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. **Ending:** the plan's "Session protocol".

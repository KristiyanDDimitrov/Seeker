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
  security release (`e4ff751` bumped certifi and setuptools for two
  advisories). It has no HISTORY entry yet; S1b writes it. v0.1.0:
  HISTORY §245.
- **HEAD:** the round-13 re-plan's commit on top of `e470d1c`. Tree
  clean.
- **The three numbers:** last quoted at S18 (`2b7e8d9`): pytest
  `2418 passed, 1 skipped` locally with the X9 Pro (CI skips 29);
  `mypy --strict src/` clean, 146 files; `ruff check src tests tools`
  0. S0's check quotes them again.
- **CI:** run `40348515619` green on `e470d1c`. The weekly scheduled
  run `40326963931` (2026-10-26) failed on the two advisories v0.1.1
  fixed.

## 2. Where we are

Phase 01 is closed. Phase 02 was planned on 2026-10-17; **round 13
(Intel Macs → v0.2.0) was re-planned on 2026-11-02** into 18 rows
with the session-plan method. **Next row: S0**, the baseline cut, a
solo session; Kris runs `/context` at its start. After S0 the rows run
in waves, a lead session each (the plan's Execution section), starting
with "Read docs/HANDOFF.md and lead wave 1".

## 3. Session report (round 13 re-plan, 2026-11-02)

- Measured B: median 57 K over 20 sessions, 59–63 K since 2026-10-17.
- `SESSION-PLAN.md` rewritten: 18 rows, each ≤ 65 K of work except S5
  (~80 K); new `tasks.json`. BRIEF: base `e470d1c`, §1.1 marked done,
  §1b's PR table refreshed and split into S1b and S1c, a new §1d
  (Spotify Premium).
- Committed the phase-02 planning documents with the re-plan, after a
  link check (19 files, 257 links, 0 broken). No code changed except
  one comment path in `tests/test_stress_e2e.py`.

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
- **S0:** whether Claude Code loads a subfolder's `CLAUDE.md` on demand
  is UNVERIFIED here. S0 records what it sees; S1 confirms it from a
  fresh session.
- **Subagents, UNVERIFIED until wave 1 records them:** custom agents
  load at session start; subagents get `CLAUDE.md`; none can spawn
  another; `isolation: "worktree"`'s branch, location and cleanup; a
  worker's baseline and transcript location. The plan → Execution.
- HISTORY continues at §246 in `docs/history/241-270.md`.

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
arrive through it. S0: `/context` at the start. S1b, S1c: each merge. S9:
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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/HISTORY.md`, split into `docs/history/` from S2.
The nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** `378646a` (round 10 S7 close-out), pushed. Tree clean apart
  from the untracked `Claude outputs/` and the four round-11 documents
  the audit chat wrote and did **not** commit:
  `docs/rounds/round-11/{AUDIT,BRIEF,SESSION-PLAN}.md` and this file.
  S1 commits them first.
- **Local pytest** (offscreen Qt, Darwin 25.6.0, 2026-09-29):
  `1204 passed, 29 skipped, 6 warnings in 74.33s`. Branch coverage
  90.3 %.
- **`mypy --strict src/`:** clean, 104 files. **`ruff check src
  tests`:** 0 findings.
- **CI on `378646a`:** run `35906721903`, `success`. That is 8
  consecutive green runs since round 10 S4's race fix (`ddc1f6e`).

## 2. Where we are

Round 10 is complete apart from S2, which is superseded (S1 records it;
BRIEF §1.5). **Round 11 is planned and ready: 43 rows plus 2 optional.
The next row is S1.** Brief: `docs/rounds/round-11/BRIEF.md`. Session
map: `docs/rounds/round-11/SESSION-PLAN.md`. Ranked findings:
`docs/rounds/round-11/AUDIT.md`.

## 3. Session report (audit chat, 2026-09-29)

No code changed. A whole-repository audit (method and tools in
`AUDIT.md`: ship-gate, tech-debt-tracker, deptry, pip-audit, radon,
vulture, a ruff survey, branch coverage, import timing, 48 offscreen
screenshots, and probes against throwaway databases) produced 60
findings and this round's three documents.

## 4. Key context

- **Three critical findings, in order: S3, then S5.**
  - Same-name upgrade with "Delete old file" leaves no file at all (A-01).
  - Downloads silently overwrite a different same-named library file
    (A-02).
  - The shipped Compose file mounts `/Volumes/X9 Pro/...` (A-03,
    confirmed inside `dist/Seeker.app`).
  Reproductions are in BRIEF Appendix A. Turn them into the failing
  tests.
- **A privacy bug, also in S5 (§5.5, A-54).** Settings → "Update
  SoulSeek credentials" would re-share the alphabetically first location,
  which is `~/Desktop` on this machine, with the Soulseek network.
- **Interim cautions for Kris** (also in SESSION-PLAN → "Waiting on
  Kris"): no Review **Replace + Delete old file** until S3; no
  **Update SoulSeek credentials** until S5.
- **Real-data facts** (read-only; BRIEF Appendix B):
  - 2 limbo matches (Denzel Curry) and 1 orphan manual track;
  - 0 SoulSeek review candidates, which is why round 10 S2 is
    superseded;
  - 4 locations nest into 6,921 rows for about 3,460 files, one of them
    the volume root `/Volumes/X9 Pro`.
- **New docs layout.** Round documents live in
  `docs/rounds/round-NN/`; round 11's are already there, and S1 moves
  rounds 1–10. S1 appends §136 to `docs/HISTORY.md`; S2 splits the file
  into `docs/history/` with working `#N` anchors, and its own entry is
  §137.
- **Stale build identity.** A leftover `src/seeker/_build_info_generated.py`
  from the last packaging build makes source runs claim build `d38d80f`.
  Do not trust the Help page's build id in dev until S39.
- **Never start, stop or recreate Kris's slskd container, and never
  write real data** (BRIEF §0.7). Migrations are rehearsed on a copy of
  the database.
- **The audit's screenshot harness is not in the repository.** S27.0
  builds `tools/screenshots.py` (the design is in BRIEF §27.0).

## 5. Decisions made

- **Kris, 2026-09-29:** schedule the v0.1.0 release, the opt-in daily
  update check, the HISTORY split and the nested-location guard; do a
  consistency pass plus a visual refresh (Kris picks the direction at
  S30); archive round documents under `docs/rounds/`; keep Windows and
  Linux packaging, labelled unverified, with no new CI.
- **Audit chat:** keep the BRIEF, SESSION-PLAN and HANDOFF format
  rather than tc-tracker's JSON records, adopting its key-context,
  decisions, blockers and files-in-progress fields. Row numbers follow
  the brief's § order (S35a/S35b split §35).

## 6. Blockers

None for S1.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** §1.6 `Claude outputs/` (default: leave it); S21
package regrouping; S30 visual direction; S39 bundle identifier; S42
publishing commands; X1 and X2, the optional features.

**Live checks:** consolidated into S41's checklist (details in
`SESSION-PLAN.md` → "Waiting on Kris"), including every open live check
carried from rounds 9 and 10.

## 9. Open questions

- CLAUDE.md open items 63 (retry storm), 70 (stress hang; S22 adds a new
  lead: the 2-second poll deserialises 32.6 MB of fingerprints) and 125
  (quit hang) remain open.
- The one-off CI `SETUP ERROR` from round 10 S3 has not recurred in 8
  runs. S38 decides whether it deserves an Open-issues entry.

---

**Read discipline (still why sessions blow their budget):** never read
`docs/HISTORY.md` (or a whole `docs/history/*.md`), `main_window.py` or
`test_ui_smoke.py` whole; `grep -n`, then read a range. Report only
pytest's summary line plus named failures. Read only BRIEF §0 plus your
row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

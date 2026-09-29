# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/HISTORY.md`, split into `docs/history/` from S2.
The nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** `d0af9d4` (round 11 S1 close-out) plus this handoff commit,
  pushed. Tree clean apart from the untracked `Claude outputs/` (§1.6,
  waiting on Kris).
- **Local pytest** (offscreen Qt, 2026-09-29):
  `1232 passed, 1 skipped, 6 warnings in 116.00s`. Same 1,233 tests as
  round 10's `1204 passed, 29 skipped`: the X9 Pro was mounted, so its
  28 `@requires_x9_pro` tests ran.
- **`mypy --strict src/`:** clean, 104 files. **`ruff check src
  tests`:** 0 findings.
- **CI on `d0af9d4`:** run `36567623511`, `success` (`1204 passed, 29 skipped`; callback server `.....`).

## 2. Where we are

S1 done. **Next row: S2** (split `HISTORY.md` into `docs/history/`
with anchors that work, BRIEF §2). Then Phase B: S3 (downloads never
overwrite), the first critical fix.

## 3. Session report (S1)

- `af73e7c` §1.1: the four round-11 documents committed as written.
- `a9f7e60` §1.2: `git mv` of every round document into
  `docs/rounds/round-NN/`; all references repointed. HISTORY §136.
- `4383420` §1.3: `docs/README.md`, the docs index (59 lines).
- `00e8d3f` §1.4: callback-server CI issue closed, roadmap points at
  round 11. Evidence: HISTORY §136, "The `test_callback_server.py` CI
  timeouts".
- `0e51256` §1.5: round 10's S2 struck through as superseded. Evidence:
  HISTORY §136, "Round 10's S2 row".
- `d0af9d4` close-out: HISTORY §136 numbers; S1 ticked.

## 4. Key context

- **For S2, the links to repoint** (`grep -rl "HISTORY\.md#"`, 2026-09-29):
  `CLAUDE.md` 66, `docs/rounds/round-05/TASKS.md` 5,
  `docs/rounds/round-11/BRIEF.md` 3, `docs/rounds/round-08/SESSION-PLAN.md`
  2, `pyproject.toml` 2, `docs/rounds/round-10/SESSION-PLAN.md` 1,
  `src/seeker/ui/main_window.py` 1, and 1 inside `HISTORY.md` itself.
  `docs/README.md` links `HISTORY.md` without an anchor. Archived docs
  sit two levels down, so their links are `../../HISTORY.md#N`.
- **HISTORY's last entry is §136** (this session). S2's entry is §137.
- **The callback-server CI failures were fixed by round 9's `231b512`,
  not by anything environmental.** 39 of 39 CI runs since it pass all
  five tests; the two runs before it show `FFF..`. Which of its two
  changes did it is unexplained. CLAUDE.md now carries it as a
  standing fact under Spotify / OAuth.
- **Pytest's skip count depends on the X9 Pro being mounted** (1 skip
  mounted, 29 unmounted, same total). Compare totals, not the split.
- **In zsh, an unquoted `$files` is not word-split.** A `perl -pi` over
  `$files` failed silently the first time; pass the paths inline.
- **Still true from the audit:** three critical findings (S3: A-01,
  A-02; S5: A-03) and a privacy bug (S5 §5.5, A-54); reproductions in
  BRIEF Appendix A. A stale `_build_info_generated.py` makes dev runs
  claim build `d38d80f` until S39. Never start, stop or recreate
  Kris's slskd container, never write real data (BRIEF §0.7).

## 5. Decisions made

- **Old paths inside archived prose stay only where they are verbatim
  quotes.** Round 8's brief quotes a `git status` line naming
  `docs/BRIEF-2026-09-07.md`; it records the tree as it was, so it was
  left alone. Every navigational reference was repointed.
- **The callback-server issue closes as fixed-with-unexplained-cause,
  not as a verified root cause.** The CI record is conclusive about
  *when* it stopped; the mechanism is marked unexplained in HISTORY
  §136 and CLAUDE.md, per working agreement 4.
- **Skill divergence:** `codebase-onboarding` was loaded for §1.3; its
  analyzer and onboarding template target full onboarding packets, so
  only its audience-tailoring guidance was used for the 59-line index.

## 6. Blockers

None for S2.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:**
- **§1.6** `Claude outputs/` (two stray copies of round 9 documents):
  delete it, gitignore it, or leave it. Left untouched (the default).
- S21 package regrouping; S30 visual direction; S39 bundle identifier;
  S42 publishing commands; X1 and X2, the optional features.

**Interim cautions until their fix lands:** no Review **Replace +
Delete old file** until S3; no Settings → **Update SoulSeek
credentials** until S5.

**Live checks:** consolidated into S41's checklist (details in
`SESSION-PLAN.md` → "Waiting on Kris").

## 9. Open questions

- CLAUDE.md open items 63 (retry storm), 70 (stress hang; S22 has a new
  lead: the 2-second poll deserialises 32.6 MB of fingerprints) and 125
  (quit hang) remain open.
- The one-off CI `SETUP ERROR` from round 10 S3 has not recurred. S38
  decides whether it deserves an Open-issues entry.

---

**Read discipline (still why sessions blow their budget):** never read
`docs/HISTORY.md` (or a whole `docs/history/*.md`), `main_window.py` or
`test_ui_smoke.py` whole; `grep -n`, then read a range. Report only
pytest's summary line plus named failures. Read only BRIEF §0 plus your
row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

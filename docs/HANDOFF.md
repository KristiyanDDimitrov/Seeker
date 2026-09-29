# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** `718781a` (round 11 S2 close-out) plus this handoff commit,
  pushed. Tree clean apart from the untracked `Claude outputs/` (§1.6,
  waiting on Kris).
- **Local pytest** (offscreen Qt, 2026-09-29):
  `1232 passed, 1 skipped, 6 warnings in 109.73s` (X9 Pro mounted;
  identical to S1).
- **`mypy --strict src/`:** clean, 104 files. **`ruff check src
  tests`:** 0 findings.
- **CI on `718781a`:** run `36569645359`, `success` (`1204 passed, 29
  skipped`).

## 2. Where we are

Phase A done (S1, S2). **Next row: S3** (downloads never overwrite,
never guess, BRIEF §3), the first critical data-safety fix. Then S4.

## 3. Session report (S2)

- `53dd2d8` §2.1: HISTORY split into eight files under `docs/history/`,
  lossless (byte-identical minus 128 anchors). HISTORY §137.
- `ee74749` §2.2: `docs/history/README.md`, one line per entry.
- `00b8864` §2.3: `docs/HISTORY.md` is a stub pointing at the index.
- `b39f5bd` §2.4: 74 markdown links repointed to `file#N`, plus
  `pyproject.toml`, `README.md`, one `main_window.py` comment.
- `718781a` close-out: §137 (both scripts, lossless and link-check
  output); append rule promoted to CLAUDE.md working agreement 1.

## 4. Key context

- **Your HISTORY entry is §138: append it to `docs/history/121-150.md`**
  with `<a name="138"></a>` on the line directly above `### 138 — …`,
  then add its line at the end of `docs/history/README.md`. That file
  is 79 KB; the range reserves room through §150.
- **Link to entries as `docs/history/<file>#N`** (from the repo root;
  `../../history/<file>#N` from a round doc). `HISTORY §N` in plain text
  is also fine: the index resolves it.
- **§37, §57–§61, §97 and §108 never existed**; §62 is only a
  follow-up heading inside §56's phases. Nothing references the others.
- **28 source/test comments still say `docs/HISTORY.md item N`** (prose,
  not links). They land on the stub, and S24/S25 rewrite those comments
  anyway, so they were deliberately left alone.
- **The link checker must skip fenced code blocks** in Markdown:
  quoted output in a HISTORY entry otherwise reads as dead links. The
  fixed script is pasted in §137 if a later row needs to re-run it.
- **Pytest's skip count depends on the X9 Pro being mounted** (1 skip
  mounted, 29 unmounted, same total). Compare totals, not the split.
- **In zsh, an unquoted `$files` is not word-split.** Pass paths inline.
- **Still true from the audit:** three critical findings (S3: A-01,
  A-02; S5: A-03) and a privacy bug (S5 §5.5, A-54); reproductions in
  BRIEF Appendix A. A stale `_build_info_generated.py` makes dev runs
  claim build `d38d80f` until S39. Never start, stop or recreate
  Kris's slskd container, never write real data (BRIEF §0.7).

## 5. Decisions made

- **Ranges were measured, not the brief's proposal:** 1–30 alone was
  274 KB. Files: `001-024`, `025-031`, `032-046`, `047-071`, `072-107`,
  `108-120`, `121-150`, each under 150 KB.
- **The last file is a reserved range (`121-150.md`)** so appending
  never forces a rename; §151 opens `151-180.md`. Renaming would break
  every `file#N` link.
- **Anchors sit on their own line even after list-continuation text**,
  where they join that paragraph invisibly and land one line above the
  heading. Putting them inside the heading would break losslessness.
- **Skill divergence:** `codebase-onboarding` was not loaded; the brief
  fully specifies the index format, and S1 found its templates target
  full onboarding packets.

## 6. Blockers

None for S3.

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
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S6 close-out (HISTORY §198). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2052 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S1–S5 (S9 owns it).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** see §3 for the S6 push's run.

## 2. Where we are

**Round 12 S6 is done:** `docs/rounds/round-12/AUDIT.md`, S-01 to
S-15, no critical or high finding. **Next: S7, which is [ASK]**
(urllib3, a CI dependency audit, the image digest, checkout
credentials: S-01, S-02, S-08, S-13). It waits for Kris to read
`AUDIT.md` and say yes. S8 follows the same gate.

## 3. Session report (S6)

- One commit: `AUDIT.md`, HISTORY §198 and its index line, the plan
  tick, the docs-index link, this file. No `src/` or test change.
- Pushed; CI run: CI_LINE.

## 4. Key context

- **Medium findings:** S-01 urllib3 (unreachable, but `pip-audit` 0
  is an exit criterion), S-02 no CI audit (and native libraries are
  invisible to `pip-audit`: record their versions), S-03 peer files
  reach libsndfile 1.2.2 and ffmpeg, which sniff content past the
  extension gate, S-04 the DMG has no GPL/LGPL licence texts.
- **For S8:** S-05 (check OAuth `state` before showing `error`; a
  wrong-state request must not end the wait) and S-07 (data and log
  dirs 0700) are pure hardening. S-06 (sanitize the peer basename),
  S-03(c) and S-09 change behaviour: [ASK].
- **For S14:** S-15. The automatic check must stay disclosed (opt-in
  or a visible toggle), link-only, at most once a day.
- **For S16:** S-04 (a `licenses/` folder, plus GPL wording Kris
  approves) and S-14 (the bundle ID is still `com.seeker.app`).
- **A new, undiagnosed Cocoa observation (for S9):** S6's first full
  run reported `6 failed, 2048 passed, 1 skipped`. At least five were
  `test_theme.py::test_selected_text_reads_on_a_selection_that_stands_off_the_field`
  (`dark-plain-text-edit`, `dark-label`, `light-line-edit`,
  `light-plain-text-edit`, `light-label`; only the summary's tail was
  kept, so the sixth is unknown). mypy and ruff ran alongside it.
  `test_theme.py` alone, and a second full run, gave the baseline
  of 2. The docs-only change cannot reach it. Not reproduced, so not
  diagnosed.
- **Carried:** Sharing's 20 s rebuild of its per-row button (S15).
  `uv build --wheel` picks up a gitignored `_build_info_generated.py`
  (S16). S9 owns the radon-D pair and the two undiagnosed tests.
  Set `set -o pipefail` before `pytest … | tail && git commit`. Never
  touch slskd or real data.

## 5. Decisions made

- **Severity scale written into AUDIT.md**, so that "no critical or
  high" is checkable: critical is RCE or credential theft without
  user action.
- **Same-user attackers are outside the model** (S-10, S-11 accepted
  on that basis); they can already read every asset.
- **Skills:** only `security-pen-testing` was loaded (the report
  shape). `security-review` targets a diff, which this row did not
  have. `dependency-auditor` and `adversarial-reviewer` were
  replaced by running `pip-audit` and `pip-licenses` directly, to
  keep the row in budget. That is a divergence from the plan's
  skills list, recorded here.

## 6. Blockers

S7 and S8 wait for Kris's yes on `AUDIT.md`.

## 7. Files in progress

None: S6 is committed whole.

## 8. Waiting on Kris

**Read `docs/rounds/round-12/AUDIT.md`** and answer:
1. Yes to S7 (no behaviour change)?
2. S8: yes to S-05 and S-07; decide S-06 (rename peer files with a
   leading dot or control characters?), S-03 (accept, and optionally
   skip analysing a file whose content does not match its
   extension?), and S-09 (cap slskd's search body, or accept?).
3. S-04: the GPL wording for the DMG (an S16 decision).

**Still open from S1–S5:** the live checks of §193–§196, the S5
wording veto, the wordmark's brows (`9ff777b`), BRIEF §17, and
`git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
three nested locations.

## 9. Open questions

- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED; it needs a throwaway container.)
- Sharing's 20 s rebuild: S15, or a row of its own?
- Unchanged from S36: `git show 1b415a4:docs/HANDOFF.md` §9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

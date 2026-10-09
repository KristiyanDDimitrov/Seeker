# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S7 close-out (HISTORY §199). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `6 failed, 2063 passed, 1 skipped` (+15 tests).
  Failing: the six
  `tests/test_theme.py::test_selected_text_reads_on_a_selection_that_stands_off_the_field`
  cases (`dark-`/`light-` × `line-edit`, `plain-text-edit`, `label`).
  This is **pre-existing**: the same six fail at `e85e951`. It replaces
  the old two (`test_a_cell_widget_paints_the_rows_own_background`),
  which now pass in a full run but still fail when `test_theme.py`
  runs alone. S9 owns both. `mypy --strict src/` clean, 138 files;
  `ruff check src tests tools` 0.
- **CI:** CI_PLACEHOLDER

## 2. Where we are

**Round 12 S7 is done:** S-01, S-02, S-08 and S-13 are fixed.
**Next: S8**, approved by Kris on 2026-10-09. It covers S-05, S-07
and S-12 (pure hardening), then S-06 (sanitize at placement, decided),
then the written acceptances: S-03 (a)+(b), S-09 (all three hosts,
no cap), S-10 and S-11, into AUDIT.md and CLAUDE.md. The decisions are
in `AUDIT.md` → Summary → Status.

## 3. Session report (S7)

- `d2dc571` urllib3 2.8.0 · `4fbcd8e` `tools/audit_dependencies.py`,
  the CI `audit` job (push, PR, weekly) and the native-library record
  in `docs/packaging.md` · `c67b589` the slskd digest, plus Dependabot's
  `docker-compose` ecosystem · `06319a1` `persist-credentials: false`
  · `34ce3a3` the adversarial review's fix (a wrong-shaped ignore
  list is refused in a sentence) · the close-out (HISTORY §199,
  AUDIT status, CLAUDE.md, the plan tick, this file).
- Each fix had its failing check first (pip-audit's three IDs; the
  missing tool; `assert None` on the image line; `AttributeError` on
  the shapes).

## 4. Key context

- **The audit tool:** `uv run --no-project tools/audit_dependencies.py`.
  It audits the dev group too (beyond the brief's `--no-dev`), since
  that group builds the DMG. `PIP_AUDIT` is bumped by hand, because
  Dependabot cannot see it.
- **The slskd digest** is the 0.26.0 index digest, read from the
  registry. It was not compared with Kris's local image, because
  Docker was not running.
- **For S8, S-06:** run the peer basename through
  `clean_path_component` or a peer-name variant at placement, while
  `_locate_completed_file` keeps matching slskd's raw name. Test
  first with `.hidden.mp3`, a U+202E name and a name over 255 bytes.
- **For S9:** the failure flip above. Lead, UNVERIFIED: whether the
  window is active (QPalette Active vs Inactive), since the two tests
  fail inversely. Each full Cocoa run takes ~5 min; don't start
  another Qt pytest process during it.
- **Carried:** Sharing's 20 s per-row rebuild (S15). `uv build
  --wheel` picks up a gitignored `_build_info_generated.py` (S16).
  The radon-D pair (S9). Set `set -o pipefail` before `pytest … |
  tail && git commit`. Never touch slskd or real data.

## 5. Decisions made

- **Kris, 2026-10-09:** S7 yes; S8 hardening yes; S-06 sanitize;
  S-03 accept + track, no extension check; S-09 accept for all hosts.
- The `audit` job runs on `ubuntu-24.04`: it reads only `uv.lock`,
  so it needs no Mac.
- **Skills:** `adversarial-reviewer` ran before close-out, as the plan
  asks, and found the wrong-shape bug. `tdd` and `env-secrets-manager`
  were not loaded. The row had no secrets work, and the failing-check-
  first rule was followed directly. That is a divergence, recorded
  here.

## 6. Blockers

None for S8.

## 7. Files in progress

None: S7 is committed whole.

## 8. Waiting on Kris

- **S-04:** the GPL wording for the DMG (an S16 decision).
- **Still open from S1–S6:** the live checks of §193–§196, the S5
  wording veto, the wordmark's brows (`9ff777b`), BRIEF §17, and
  `git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
  three nested locations.

## 9. Open questions

- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED; it needs a throwaway container.)
- Does Dependabot's `docker-compose` ecosystem bump a `tag@digest`
  line as a pair? The first PR will show.
- Sharing's 20 s rebuild: S15, or a row of its own?
- Unchanged from S36: `git show 1b415a4:docs/HANDOFF.md` §9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S37 close-out (HISTORY §191). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2011 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background[dark]`
  and `[light]`. Not from S37: they fail the same at `1b415a4` and
  pass offscreen (see §4).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** CI_LINE

## 2. Where we are

S1–S37 ticked. **Next: S38, the CLAUDE.md refresh** (BRIEF §38).
Its first item is now easy: `docs/architecture.md` has the one
canonical module map, so CLAUDE.md's "Current layout" becomes a link
plus at most ten lines.

## 3. Session report (S37)

Evidence in HISTORY §191.
- `f3578b5` (§37.2): `docs/architecture.md`, `docs/cli.md`,
  `docs/packaging.md`; four packaging files repointed from the
  README to `docs/packaging.md`.
- `86a69fa` (§37.1): README 755 → 178 lines, live CI badge; tech
  stack and design principles moved to `architecture.md`;
  CLAUDE.md line 10 now points at `docs/cli.md`.
- `d65e860` (§37.3): `docs/README.md` links every document; every
  relative link and anchor checked.

## 4. Key context

- **CLAUDE.md's "Current layout" is stale against the tree.** It
  lacks `library/nesting.py`, `login_item.py`,
  `ui/pages/library_page.py`, `ui/playlist_selection.py`,
  `ui/table_sort.py`, `ui/tag_result_panel.py`,
  `ui/spotify_authorization.py`, `models/slskd_start.py`, and says
  `main_window.py` is 1,283 lines (1,229). S38 replaces it with a
  link rather than fixing it (`find src/seeker -name '*.py'` is how
  the architecture map was built).
- **The CLI reads the saved match thresholds**, like the GUI: every
  service gets `get_config=lambda: self._config_store`. The old
  README said otherwise.
- **chromaprint is not bundled** (`seeker.spec` has `binaries=[]`);
  Duplicates needs `brew install chromaprint`. The README says so.
- **Order for a docs move:** write the new home and commit it, then
  cut the source; the commit in between holds both copies, never
  neither.
- **Two Cocoa-only theme test failures appeared between S36 and
  S37** with no code change: a one-unit colour difference in
  `test_a_cell_widget_paints_the_rows_own_background` (e.g.
  `(249, 250, 250)` against `(248, 249, 250)`). They reproduce at
  `1b415a4` in a clean worktree and pass under
  `QT_QPA_PLATFORM=offscreen` (CI's platform). An external 5K display
  was the main display; that it changes what `grab()` returns is
  UNVERIFIED. First check: rerun with only the built-in display. If
  they still fail, the test needs a tolerance or an offscreen-only
  pixel comparison, as its own test-first row. Diagnose; don't adopt
  2011 as the baseline.
- Carried: `set -o pipefail` before `pytest … | tail && git commit`;
  never touch slskd or real data; the full suite takes ~4.5 min, so
  run it in the background.

## 5. Decisions made

- **§37.2 was committed before §37.1**, so the README was cut only
  after its content had a home.
- **The five non-hero screenshots stay in the README, behind a
  `<details>`**: the brief asks for one hero image, and
  `tools/screenshots.py --readme` still writes all six, so none is
  orphaned.
- **The README describes the released state** (DMG from Releases,
  SHA-256). S42 publishes it; until then the Releases page is empty.
- **CLAUDE.md was touched in one line only** (its pointer to the
  README's command table, which this row removed). The rest is S38's.

## 6. Blockers

None.

## 7. Files in progress

None: S37 is committed whole.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`; `seeker.spec` still says
`com.seeker.app`), the S42 publishing commands, X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`),
shown in the README's hero image.

**Live checks (S41 checklist):** unchanged from S36, plus one: view
`docs/architecture.md` on github.com and confirm the Mermaid state
diagram renders (UNVERIFIED). Everything else as carried in
`git show 1b415a4:docs/HANDOFF.md` §8.

## 9. Open questions

Unchanged from S36: see `git show 1b415a4:docs/HANDOFF.md` §9 (the
Downloads first-poll header, Settings' Reachable lamp, Duplicates'
Quality at 960, and the carried items).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S2 close-out (HISTORY §194). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2041 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S1 and S37/S38 (S9 owns it).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** see §3 for the S2 push's run.

## 2. Where we are

**Round 12 S2 is done.** **Next: S3**, Review's tooltips survive the
2 s poll by rendering only on change (BRIEF §3; `focused-fix` and
`tdd`). S4 follows it because both touch table rebuilds and sort keys.
Read `src/seeker/ui/CLAUDE.md` first: its `_RenderedRows` fact (the
Dashboard's render-on-change) is the pattern S3 likely wants.

## 3. Session report (S2)

- `1f4b82d`, §2.1: `apply_theme` sets or clears the scheme override
  before resolving `"system"`.
- `2414ce5`, §2.2: spin-box buttons in QSS, up/down chevrons per
  palette (`packaging/icons/spin_*`).
- `06eac99`, §2.2: the match thresholds take `QLocale.c()`.
- The close-out: HISTORY §194 (image `docs/history/images/194-spin-arrows.png`),
  two facts and the §166 link fix in `src/seeker/ui/CLAUDE.md`, the
  plan tick, this file.
- CI: pending at the close-out commit; recorded by the follow-up.

## 4. Key context

- **Cocoa's `colorScheme()` reports the app's own override** until
  `setColorScheme(Unknown)`, and reverts synchronously; offscreen
  stays `Unknown` throughout. A test of anything scheme-dependent
  stubs `theme.QGuiApplication.styleHints` (`_CocoaStyleHints` in
  `test_theme.py`).
- **A "some pixel reaches 3:1" grab test can pass on a speck.** The
  spin test measures the mark's width instead. The combo chevron and
  tick tests still use the weaker floor; they pass because the marks
  are real, but S15 could tighten them.
- **Screens diff:** `tools/screenshots.py` wrote 76 PNGs this time
  (S1 said 78). The harness runs under the Mac's comma locale, so
  number formatting shows in it.
- **Planning found, for later rows:** Review rebuilds every row on
  each 2 s tick, which kills tooltips (S3). The Dashboard's Status
  column sorts by label text (S4). The "daily" retry never existed
  (S10). `urllib3 2.7.0` has three advisories, fixed in 2.8.0, and CI
  has no dependency audit (S7). All in BRIEF §3–§10.
- **For S16: `uv build --wheel` packages whatever is in
  `src/seeker/`,** including a gitignored `_build_info_generated.py`
  left by a local DMG build. `wheel-exclude` already drops
  `CLAUDE.md`.
- **S9 owns:** the two radon-D functions and the two undiagnosed
  tests (the CI flake
  `test_search_download_best_passes_the_already_fetched_results`,
  `37599402903`; the Cocoa-only theme failure, whose first untried
  check is a rerun with only the built-in display).
- **Carried:** set `set -o pipefail` before `pytest … | tail && git
  commit`. Never touch slskd or real data. The full suite takes
  ~4.5 min, so run it in the background. `git stash push -- <paths>`
  to test HEAD's `src/` with the new tests: a bare stash takes the
  tests too.

## 5. Decisions made

- **Thresholds in `QLocale.c()`, not the system locale everywhere.**
  Every score prints through `f"{score:.1f}"` (UI and CLI); the CLI
  cannot follow Qt's locale, and the threshold is read against those
  scores.
- **The spin arrows reuse the combo chevron's geometry**, separate
  files per direction and palette, as the brief asked
  (`_palette_icon`). Buttons are transparent at rest, so the field
  reads as one control; hover `BG_SURFACE_2`, pressed `BORDER`.
- **The tdd skill asks to confirm seams with the user;** the brief
  already named them (the applied palette; a grab of a spin box), so
  no question was asked.

## 6. Blockers

None.

## 7. Files in progress

None: S2 is committed whole.

## 8. Waiting on Kris

**A cheap veto:** the new colours. Dark selection is `#4A3799`, the
light amber `#AD7400` (images in HISTORY §193). The pill outline now
shows as ACCENT. From S2: the spin arrows and `90.0` with a point
(HISTORY §194's image).

**A live check:** on the real Mac in Dark, choose Light, then Follow
system; the app should turn dark at once.

**Open gates:** reading `AUDIT.md` after S6, the S5 wording veto, the
first live Cancel (S12) and cleanup (S13), and the S18 publishing
commands. Also the wordmark's brows over "ee" (`9ff777b`).

**Live checks:** round 12 BRIEF §17, plus the carried list in
`git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
three nested locations.

## 9. Open questions

- Unchanged from S36: see `git show 1b415a4:docs/HANDOFF.md` §9 (the
  Downloads first-poll header, Settings' Reachable lamp, Duplicates'
  Quality at 960, and the carried items).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S1 close-out (HISTORY §193). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2026 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S37/S38 (see §4).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** `f1627f7`'s run `37824275052` green: `2000 passed, 29
  skipped`, coverage 94.53 % (floor 92 %).

## 2. Where we are

**Round 12 S1 is done.** **Next: S2**, "Follow system" applies at
once, and the spin-box arrows in dark mode (BRIEF §2). S2 edits
`theme.py` as S1 did; read `src/seeker/ui/CLAUDE.md` first.

## 3. Session report (S1)

- `e69813f`: the round-12 planning docs, as planning left them.
- `2311429`, §1.1: one selection pair, `TEXT` on a new `SELECTION`.
- `1feb150`, §1.2: `CUE`, the lamp and meter amber, split from
  `WARNING`.
- The close-out: HISTORY §193 (with before and after images,
  `docs/history/images/193-*.png`), the UI rule, the plan tick, this
  file.
- Evidence (probe tables, failing then passing tests, screens read):
  HISTORY §193. CI: run `37824275052`, green.

## 4. Key context

- **Light mode's field selection was broken too:** white text on
  `#E9E4FB`. Fixed with the dark case in §1.1.
- **`QStyleSheetStyle` writes a rule's `selection-*` into the
  widget's palette.** A table's `Highlight` is therefore its
  `selection-background-color`, not the app palette's. That is why
  the Upgrade/Locked pill's "ACCENT" outline never showed. It now
  reads `QPalette.Link`. Anything reading `option.palette` inside a
  styled view gets the QSS colours.
- **The token pin:** `tests/shell/test_theme_toggle.py::
  test_palettes_carry_the_approved_tokens` pins every `Palette` field
  in order. A new token goes there and in
  `docs/design/visual-direction.md`.
- **Screens diff:** `tools/screenshots.py` (offscreen, ~2 min, safe
  beside a running suite). Copy `tools/.screens` to the scratchpad
  before and after, then compare pixels with `QImage`. That lists
  exactly which screens a change touched.
- **Planning found, for later rows:** "Follow system" resolves the
  palette before it clears the scheme override (`theme.py`
  `apply_theme`; grep it, the lines moved by ~10). Review rebuilds
  every row on each 2 s tick, which kills tooltips (S3). The
  Dashboard's Status column sorts by label text (S4). The "daily"
  retry never existed (S10). `urllib3 2.7.0` has three advisories,
  fixed in 2.8.0, and CI has no dependency audit (S7). All of this is
  in BRIEF §2–§10.
- **CLAUDE.md is two files:** the root (29.9 KB) and
  `src/seeker/ui/CLAUDE.md` (12.6 KB). Its link at line 74
  (`HISTORY\n  §166`) wraps, so the `src/` history grep flags it.
  This predates S1; fix it in passing.
- **For S16: `uv build --wheel` packages whatever is in
  `src/seeker/`,** including a gitignored `_build_info_generated.py`
  left by a local DMG build. `wheel-exclude` already drops
  `CLAUDE.md`.
- **S9 owns:** the two radon-D functions and the two undiagnosed
  tests. One is the CI flake
  `test_search_download_best_passes_the_already_fetched_results`
  (`37599402903`, §128's race shape). The other is the Cocoa-only
  theme failure; its first untried check is a rerun with only the
  built-in display.
- **Carried:** set `set -o pipefail` before `pytest … | tail && git
  commit`. Never touch slskd or real data. The full suite takes
  ~4.5 min, so run it in the background. `git stash push -- <paths>`
  to test HEAD's `src/` with the new tests: a bare stash takes the
  tests too.

## 5. Decisions made

- **One selection colour, for text and table rows alike** (the
  brief: "apply it everywhere"). The nav's current page and menu
  hover keep `ACCENT_SUBTLE`: they mark a place, not a selection.
- **Light `SELECTION` `#E4DDFB`, not the stronger `#DCD3FA`**, so
  that `CUE` keeps 3:1 on a selected row. The field test's
  "stands off" floor is 1.2:1. The old colours, at 1.07 and 1.18,
  fail it.
- **Light `CUE` `#AD7400`:** the lightest golden amber that meets all
  four floors. Higher hues read mustard in a swatch.
- **The warning notice's left edge is a mark, so it takes `CUE`.**
- **Images in HISTORY are new.** Two compact composites
  (~35 KB each), not whole screens, to keep the repository light.
  This diverges from earlier entries, which only named screens. The
  brief asked to show the screens.

## 6. Blockers

None.

## 7. Files in progress

None: S1 is committed whole.

## 8. Waiting on Kris

**A cheap veto:** the new colours. Dark selection is `#4A3799`, the
light amber `#AD7400` (images in HISTORY §193). The pill outline now
shows as ACCENT.

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

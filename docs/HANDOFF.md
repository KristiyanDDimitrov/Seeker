# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S27 part-1 close-out commit, after `f60f26f`
  (§27.1). Tree clean apart from the untracked `Claude outputs/`.
- **Local** (at `f60f26f`): pytest `1705 passed, 29 skipped`;
  `mypy --strict src/` clean, 131 files; `ruff check src tests tools`
  0.
- **CI:** see the close-out push (recorded in the next session's
  report if not below).

## 2. Where we are

S1–S26 ticked. **S27 stopped at its split point (after §27.1),** on
budget, not a blocker. **Next: S27 part 2** — §27.2 combo chevron,
§27.3 button sizing, §27.4 focus ring and accessible names, §27.5
splitters and progress-text contrast. Then S28.

## 3. Session report (S27 part 1)

Evidence in HISTORY §173.
- `765ba8f` §27.0: `tools/screenshots.py` replaces
  `docs/screenshots/generate.py`; README images regenerated;
  `tests/test_screenshots_tool.py`; CI ruff covers `tools/`.
- `f60f26f` §27.1: generic `QWidget` paints no background;
  `QCheckBox`/`QRadioButton` transparent; two pixel tests, both
  themes, failing first on HEAD.

## 4. Key context

- **Use the harness for every UI row from here on:** `uv run python
  tools/screenshots.py --page review --theme light` takes seconds;
  the full run (72 images) ~45 s. View images by contact sheet to
  save tokens: compose four 1280×820 shots at half size with
  `QImage`/`QPainter` (the S27 script was scratchpad-only).
- **`MainWindow` does not apply the theme; `main_ui.py` does,** before
  construction. Anything building a window outside `main_ui.py` calls
  `theme.apply_theme(app, mode)` first.
- **Harness teardown:** stop the window's `QTimer`s and drain
  `thread_pool` before `deleteLater`, or a poll result lands on a
  deleted widget.
- **Local pytest grabs at Retina 2×; offscreen at 1×.** A pixel test
  maps through `image.width() / widget.width()`.
- What part 2 will see in the images: combos without arrows
  (Duplicates' location, History's Show, Settings' location pickers);
  full-width buttons in Settings (Connection tab), the wizard and
  Duplicates; 6 px `BORDER_STRONG` splitters on Review; "65%" dark on
  violet in the light Dashboard. S28 material also visible: the
  Downloads Progress column takes most of the width; Search's Filename
  column collapses at 960 px.
- Carried: radon not in the env; never touch slskd or real data; zsh
  does not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` (800×800) first; a shared fake missing a
  method stalls the suite instead of failing it (§171).

## 5. Decisions made

- **Background fix by removal, not a generic `transparent`:** the
  generic rule keeps only `color`. Page roots needed no rule (they sit
  in `QMainWindow`'s stack; a top-level plain widget fills with the
  palette's `BG_APP`, probed). Diverges from the brief's "page roots"
  wording; same result, one fewer selector.
- **The harness imports `tests/fakes.py`** (already shared since S18)
  rather than a copy, so the screenshots render what the UI tests
  exercise. It lives in `tools/`, linted by CI, not type-checked
  (mypy covers `src/`).
- **README images regenerated now** (they carried the 0.91 score
  bug); S36 regenerates them after the refresh.
- **Standing rule promoted to CLAUDE.md:** "Only a real surface paints
  a background" (Qt section), plus the harness command.
- **Skills:** `frontend-design` not loaded for part 1 (harness and a
  root-cause fix, no design choices); load it for §27.3–§27.5.

## 6. Blockers

None.

## 7. Files in progress

None; §27.2–§27.5 not started.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Live checks (S41 checklist), unchanged from S26:** the nested-location
Fix… with the X9 Pro mounted (keep `Music`, compare §172's counts);
the stress test; the carried list in `git show 5db1162:docs/HANDOFF.md`.
New, small: glance at Settings and Duplicates on a real display in
both themes — the banding should be gone.

## 9. Open questions

- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); Settings and Duplicates results on
  status labels (S28/S29); four CLI items (§156); the unrecorded
  transfer id and leftover `.tmp` files (X1); why a shared fake's
  missing method stalls the suite (§171, UNVERIFIED); a location whose
  stored path differs in case from disk maps no files in a merge.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

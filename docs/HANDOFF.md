# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S27 part-2 close-out commit, after `34559a8`
  (§27.3). Tree clean apart from the untracked `Claude outputs/`.
- **Local** (at `34559a8`): pytest `1710 passed, 29 skipped`;
  `mypy --strict src/` clean, 131 files; `ruff check src tests tools`
  0.
- **CI:** part 1's close-out run `37506767842` green. This push: see
  the next session's report if not recorded below.

## 2. Where we are

S1–S26 ticked. **S27 part 2 done (§27.2–§27.3); stopped on the
session budget,** not a blocker. **Next: S27 part 3** — §27.4 focus
ring for buttons, checkboxes, radios and tabs, plus accessible names
(the icon-only theme toggle; per-row Confirm/Reject named for the row,
e.g. "Confirm Nova Reyes – Voltage Drop"), then §27.5 (1 px splitter
line with a wider grab area; progress text contrast in light). Then
tick S27 and start S28.

## 3. Session report (S27 part 2)

Evidence in HISTORY §174.
- `3c391e8` §27.2: SVG combo chevron per palette in
  `packaging/icons/`, `theme.combo_chevron_path()` (`_MEIPASS`);
  pixel test (failed 1.0:1 on HEAD) and a stroke-equals-token test.
- `34559a8` §27.3: `theme.action_row()` at 19 sites; Settings tabs
  scroll; `tests/shell/test_button_sizing.py` sweeps every harness
  screen (failed with 19 misfits on HEAD).

## 4. Key context

- **Harness for every UI row:** `uv run python tools/screenshots.py
  --page settings --theme light` (seconds). Contact sheets save
  tokens: compose four shots at half size with `QImage`/`QPainter`
  (scratchpad-only script; ~20 lines).
- **The `screenshots` fixture is in `tests/conftest.py`** now: any
  test can load the harness module and walk `SCREENS` (see
  `test_button_sizing.py` for the loop; ~20 s per walk).
- **A palette change must update the chevron SVGs:** S31 changes
  `TEXT_MUTED`, and `test_the_combo_chevron_is_drawn_in_the_palettes_
  muted_text` fails until both files follow.
- For §27.4: there are zero `setAccessibleName` calls; the theme toggle
  is `ui/widgets.py`'s `ThemeToggleButton` (custom-painted). A focus
  ring QSS on `QPushButton:focus` also hits nav items and segment
  buttons; check both in the images. Tabs: `QTabBar::tab:focus`.
- S28 material seen: Duplicates' Path column collapses to ~30 px at
  960 wide; Downloads' Progress column takes most of the width;
  Search's Filename column collapses at 960.
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  harness teardown stops `QTimer`s and drains the pool; local pytest
  grabs at 2×, offscreen 1×; radon not in the env; never touch slskd
  or real data; zsh does not word-split `$var`; reproduce CI-only UI
  failures with `QT_QPA_PLATFORM=offscreen` first; a shared fake
  missing a method stalls the suite (§171).

## 5. Decisions made

- **Chevron as two bundled SVGs, not generated at runtime:** the brief
  asks for a bundled file through `_MEIPASS`; a test ties each file to
  its token so drift fails. Writing per-palette files to a cache dir
  at theme-apply time was the alternative, rejected as more moving
  parts.
- **Sizing by layout, not a global policy:** each offender moves into
  an action row (the house convention) rather than an app-wide
  `QEvent.Polish` filter forcing button size policies; the sweep test
  makes the rule enforced instead of implicit. Opt-out is a
  `fullWidth` property (unused today).
- **Every Settings tab scrolls,** not only Connection: one rule, and
  any tab can outgrow 640 px.
- **Standing rule promoted to CLAUDE.md:** "A button takes its size
  hint" (Qt section). S41 checklist gains the packaged-app chevron.

## 6. Blockers

None.

## 7. Files in progress

None; §27.4–§27.5 not started.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron (new); the carried list in
`git show 5db1162:docs/HANDOFF.md`. Small: glance at Settings and
Duplicates on a real display in both themes.

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

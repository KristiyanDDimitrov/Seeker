# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S27 part-3 close-out commit, after `8eb8859`
  (§27.5). Tree clean apart from the untracked `Claude outputs/`.
- **Local** (at `8eb8859`): pytest `1748 passed, 29 skipped`;
  `mypy --strict src/` clean, 131 files; `ruff check src tests tools`
  0.
- **CI:** the close-out commit `9e8c4a8`'s run `37512975028` green
  (part 2's `37508982327` green too).

## 2. Where we are

S1–S27 ticked. **Next: S28** (BRIEF §28: column policy, eliding,
empty states, copy). Split point: after §28.2.

## 3. Session report (S27 part 3)

Evidence in HISTORY §175.
- `ce1eabf` §27.4: `:focus` rings (buttons, nav, theme toggle,
  indicators, tabs); `cell_widget(..., row_label=)` names per-row
  buttons; focus starts on the playlist list. Focus test failed 1.0:1
  ×24 on HEAD; name sweep found 31 gaps.
- `9f8c873` §27.4 follow-up: `_SeekerStyle` (clicks never focus a
  button); `_show_page` keeps focus off a hidden page.
- `8eb8859` §27.5: 1 px splitter line in a 7 px band;
  `TwoToneProgressBar` (HEAD: 3.13 light / 3.65 dark on the fill).

## 4. Key context

- **Harness for every UI row:** `uv run python tools/screenshots.py
  --page review --theme light` (seconds). The `screenshots` fixture
  (`tests/conftest.py`) lets a test walk `SCREENS`; see
  `test_button_sizing.py`, `test_keyboard_access.py`.
- **Testing a `:focus` look:** paint through `style().drawControl()`
  with `State_HasFocus` on the option (`test_theme.py`'s `_render`).
  Real focus needs an active window: unreliable offscreen and on a
  busy desktop.
- **Pixel tests of small text:** offscreen renders at 1×, where
  glyph stems never reach the full colour. Render at an explicit 2×
  (`QImage.setDevicePixelRatio(2)` + `widget.render`), as
  `test_progress_text.py` does.
- **For §28.4's close control:** the notice's "X" now carries
  `accessibleName("Dismiss")`. An icon-only replacement must keep a
  name; the keyboard-access sweep fails otherwise.
- **A new per-row button** must pass `row_label=` to
  `theme.cell_widget`, or the sweep fails.
- S28 material seen in the images: the Dashboard's Track column
  collapses to ~40 px at 960 wide; Downloads' Progress takes most of
  the width; Duplicates' Path and Search's Filename collapse at 960;
  Review's Track wraps in light but elides in dark at 960 (same data).
- **For S31:** a palette change must update the chevron SVGs (test
  ties them to `TEXT_MUTED`); white on dark's ACCENT is 4.35:1, short
  of AA 4.5 (palette test floor 4.3).
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  harness teardown stops `QTimer`s and drains the pool; radon not in
  the env; never touch slskd or real data; zsh does not word-split
  `$var`; reproduce CI-only UI failures with `QT_QPA_PLATFORM=
  offscreen` first; a shared fake missing a method stalls the suite
  (§171).

## 5. Decisions made

- **Buttons are `TabFocus` app-wide (`_SeekerStyle`):** otherwise the
  ring stays on every clicked button. Consequence, accepted: on macOS
  with keyboard navigation off, Tab skips buttons, as in native apps.
- **Initial focus on the Dashboard's playlist list,** not left to
  Qt's chain (which picked the theme toggle).
- **Progress label painted by a subclass,** not moved outside the
  bar: keeps every layout and ETA label as is; Qt's stylesheet painter
  cannot draw two colours.
- **Splitter line by QSS gradient,** not a `QSplitterHandle`
  subclass: no new class, and the hover rule stays in QSS.
- **Standing rule promoted to CLAUDE.md:** "Focus is visible, and only
  keyboard focus" (Qt section). S41 checklist gains a real-Mac
  keyboard/VoiceOver check.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron; keyboard focus and VoiceOver on a
real Mac (new); the carried list in `git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); Settings and Duplicates results on
  status labels (S28/S29); four CLI items (§156); the unrecorded
  transfer id and leftover `.tmp` files (X1); why a shared fake's
  missing method stalls the suite (§171, UNVERIFIED); a location whose
  stored path differs in case from disk maps no files in a merge.
- New: should item views (tables, lists) get a themed focus indicator?
  Fusion draws its own grey frame on a keyboard-focused current cell;
  §27.4 scoped only buttons, checkboxes, radios and tabs.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

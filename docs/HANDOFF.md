# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S32 close-out (HISTORY §182). Tree clean apart from the
  untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 1930 passed, 1 skipped`. The two
  are `test_a_cell_widget_paints_the_rows_own_background[dark]` and
  `[light]`, the same order-dependent Cocoa-only pair as S31 (§181);
  +27 passing are S32's new tests. `mypy --strict src/` clean, 136
  files; `ruff check src tests tools` 0.
- **CI:** `62e2c50`'s run `37621636784` green (offscreen, so the
  Cocoa-only pixel failure does not reach it).

## 2. Where we are

S1–S32 ticked. **Next: S33, the onboarding wizard** (BRIEF §33).

## 3. Session report (S32)

Evidence in HISTORY §182.
- `a32d604`: Lucide nav icons for all eleven sidebar entries,
  `ui/icons.py` (`TokenIconEngine`, `NAV_ICONS`, `nav_icon`); vendored
  unchanged with `LICENSE` and `SOURCE.txt`; sidebar contrast floors.
- `9ff777b`: `ui/wordmark.py`, the brows over "ee" as an overlay on
  the plain `QLabel#wordmark`.
- `3baaad5`: `build_page` header as one unit; subtitles wrap at
  `SUBTITLE_MEASURE_CHARS` (90).
- `3e1379a`: the activity strip leads with a lit `CUE` lamp
  (`status_lamp.StatusLamp`).
- `f10a612`: notices: neutral hairline, variant colour on the left
  edge only; info's edge is `TEXT_MUTED`.

## 4. Key context

- **Icons:** `icons.token_icon(path, IconColours(...))` for any new
  bundled line icon; it reads `active_palette()` per draw, so nothing
  needs rebuilding on a theme switch. A Lucide file is never edited;
  add a name to `NAV_ICONS` (or a new mapping) and copy the file from
  the same release. `test_icons.py` fails on an unused or missing file.
- **The wizard (S33) has no sidebar**, but its title role and notices
  now follow the shell: use `#pageTitleLabel`, and `InlineNotice` for
  results. Lamps are available as a widget (`StatusLamp`).
- **The strip's progress bar is still the accent.** S34's segmented
  amber meter should be applied to `activity_strip_bar` too.
- **Render scale:** `tools/screenshots.py` writes at 1× (the brows are
  ~2 px tall there); a Cocoa `window.grab()` is 2×. Judge fine detail
  on a 2× grab (scratch: build `MainWindow(build_demo_application())`
  from `tools/screenshots.py`, `grab()`).
- From S31: lamps are not yet in cells (S34, S35a); `fit_widths` and
  `ElidedTextDelegate` must count the icon's width.
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  radon is not in the env; never touch slskd or real data; zsh does
  not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171); old-commit checks run in a `git worktree`
  with `PYTHONPATH=<wt>/src:<wt>/tests uv run --project <repo> pytest
  …`; `QStyle.subElementRect(..., None, ...)` segfaults: pass a real
  option (`initStyleOption`); PIL is not in the env (crop with
  `QImage.copy`); qtbot holds widgets weakly (keep a host referenced).

## 5. Decisions made

- **Nav icons recolour at draw time, not one file per palette.** It
  keeps the vendored files identical to upstream and follows a theme
  switch for free. A QSS `image:` still needs per-palette files.
  Promoted to CLAUDE.md.
- **The brows wordmark is revived** because Kris picked it (§106) and
  §114 removed it only for a clip the overlay design cannot have. Its
  geometry was tuned until it no longer read as accents ("Sèéker").
- **Info notices do not use the accent**, which is reserved for
  selection, focus and the primary action.
- **Nav badges stay text** (`"Downloads  (7)"`); a count pill is a
  separate change that touches the harness and tests.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the sidebar wordmark
(`9ff777b`). If they read wrong on your display, deleting the overlay
is a one-commit revert; the word itself is unchanged.

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron and checkbox tick (both need `qsvg`
in the bundle), Barlow in the titles (the fonts directory must reach
`_MEIPASS`) **and the nav icons** (`icons/lucide/` must reach
`_MEIPASS`; QtSvg must be collected); keyboard focus and VoiceOver on
a real Mac; hover tooltips on elided cells; the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- **The cell-widget pixel test on Cocoa** is order-dependent (§181):
  hover from the cursor? It does not affect CI.
- **Result messages still on status labels:** `settings_window.py`
  ~:577–1161 and 12 sites in `duplicates_page.py` :440–979; fold into
  S35a/S35b or its own commit.
- Settings' subtitle leaves "thresholds." alone on its second line at
  the 90-character measure (copy, S35b).
- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); four CLI items (§156); the
  unrecorded transfer id and leftover `.tmp` files (X1); why a shared
  fake's missing method stalls the suite (§171, UNVERIFIED); a
  location whose stored path differs in case from disk maps no files
  in a merge; should item views get a themed focus indicator (§175);
  the Dashboard's Status links clip instead of eliding (S34); Review's
  column budget at 960 (S35b); three copies of the basename logic in
  `soulseek/` (a refactor commit).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

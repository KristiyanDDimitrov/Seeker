# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S31 close-out (HISTORY §181). Tree clean apart from the
  untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 1903 passed, 1 skipped`. The two
  are `test_a_cell_widget_paints_the_rows_own_background[dark]` and
  `[light]`, order-dependent on Cocoa and failing identically at
  `860d521` before any S31 change (§181). The same files pass under
  `QT_QPA_PLATFORM=offscreen` (289 passed). `mypy --strict src/` clean,
  134 files; `ruff check src tests tools` 0.
- **CI:** `096acd0`'s run `37614880162` green (offscreen, so the
  Cocoa-only pixel failure does not reach it).

## 2. Where we are

S1–S31 ticked. S30 closed with Kris's pick (2026-10-07: **Booth with
the violet accent, A′, no BPM or key on the Dashboard**). **Next: S32,
the shell** (BRIEF §32: Lucide nav icons, the wordmark, the page
header, the activity strip, the notices).

## 3. Session report (S30 close + S31)

Evidence in HISTORY §180 (the pick) and §181.
- `860d521` §30.3: the pick recorded in `visual-direction.md` →
  Decision, §180 and the plan.
- `9ba724f` §31.1: A′ tokens in `DARK`/`LIGHT`, radii 4/6, chevrons;
  new AA floors (eight failures on the old palettes); native
  `HighlightedText` is `ON_ACCENT`.
- `1fb03e7` §31.2: `theme.active_palette()`; `_set_module_tokens` and
  the 17 module globals gone.
- `a22e1bd` §31.3: Barlow Semi Condensed in `packaging/fonts/` (OFL),
  `seeker.spec`, `bundled_dir()`, type tokens; titles 26 px SemiBold,
  section headers 16 px Medium.
- `56e9cf5` §31.4: `ui/status_lamp.py` (`PLAY`, `CUE`, `CUE_WAITING`,
  `FAULT`, `STANDBY`; `TRACK_LAMPS`, `DOWNLOAD_LAMPS`, `lamp_icon`).
- `b803845`: a checked checkbox shows an `ON_ACCENT` tick.

## 4. Key context

- **Read colours through `theme.active_palette()`, at paint or render
  time.** No `theme.ACCENT` exists any more. A test that needs a
  different accent monkeypatches `theme.active_palette` (see
  `test_a_theme_change_recolors_the_review_link`).
- **`ON_ACCENT` is dark ink in dark mode** (`#120E1F` on the lit
  `#9A7DFF`, 6.09:1), white in light. White on the dark accent is
  3.1:1; never put white text on it.
- **Status lamps are ready, not placed** (S34 Dashboard, S35a
  Downloads). `fit_widths` and `ElidedTextDelegate` must count the
  icon's width, or Status elides at 1280 (§180). S34 also owns the
  segmented amber meter: per-instance QSS only, since a global
  `::chunk` rule kills the indeterminate animation.
- **Display type is QSS-only** (`#pageTitleLabel`, `#wordmark`,
  `#sectionHeaderLabel`); body text stays on the system font.
- **Bundled resources: `theme.bundled_dir(name)`**; a token-coloured
  SVG gets one file per palette (`_palette_icon`). S32's nav icons too.
- Lucide's page-to-icon names are unconfirmed (S32). The scratch
  mockup module no longer runs as-is (`visual-direction.md`).
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  radon is not in the env; never touch slskd or real data; zsh does
  not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171); old-commit checks run in a `git worktree`
  with `PYTHONPATH=<wt>/src:<wt>/tests uv run --project <repo> pytest
  …`; `QStyle.subElementRect(..., None, ...)` segfaults: pass a real
  option (`initStyleOption`).

## 5. Decisions made

- **Section headers use Barlow Medium, titles SemiBold.** It answers
  S30's open question; rendered on Sharing, Medium reads as a header
  without competing with the title. Both bundled weights are now used.
- **Queued downloads light amber (`CUE`):** the wait is on the
  network, not the user. Superseded is `STANDBY`, a faint ring.
- **Status colours: 4.5 on a surface (text), 3.0 on the page ground
  and a selected row (mark).** As text, they belong on a surface.
- **New HISTORY range file `181-210.md`.** CLAUDE.md gained the
  `active_palette()` rule and `status_lamp.py`.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker` recommended), the S42 publishing
commands, and X1 and X2 (optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron **and checkbox tick** (both SVGs need
`qsvg` in the bundle) **and Barlow in the titles** (the fonts
directory must reach `_MEIPASS`); keyboard focus and VoiceOver on a
real Mac; hover tooltips on elided cells; the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- **The cell-widget pixel test on Cocoa** is order-dependent (§181):
  hover from the cursor? It does not affect CI.
- **Result messages still on status labels:** `settings_window.py`
  ~:577–1161 and 12 sites in `duplicates_page.py` :440–979; fold into
  S35a/S35b or its own commit.
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

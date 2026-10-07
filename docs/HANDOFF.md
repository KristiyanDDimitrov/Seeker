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
- **CI:** recorded in the final message of the session that pushed this.

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
- **Status lamps are ready, not placed.** S34 puts `lamp_icon` in the
  Dashboard's Status cells, S35a in Downloads'. Both must make
  `fit_widths` and `ElidedTextDelegate` count the icon's width (§180:
  otherwise "Needs review (SoulSeek candidate found)" elides at 1280).
  The segmented amber meter (`WARNING` chunks, per-instance QSS through
  `style_determinate_progress_bar`) is S34's too. A global `::chunk`
  rule still kills the indeterminate animation.
- **Display type is QSS-only:** `QLabel#pageTitleLabel`, `#wordmark`
  and `#sectionHeaderLabel` carry `DISPLAY_FAMILY`. A new title role
  uses those tokens; body text stays on the system font.
- **Bundled resources go through `theme.bundled_dir(name)`**
  (`packaging/<name>/` from source, `_MEIPASS/<name>` frozen). S32's
  nav SVGs belong in `packaging/icons/`, with one file per palette
  (`_palette_icon`) if the icon is drawn in a token colour.
- **Lucide's page-to-icon names are still unconfirmed** (S32).
- **The scratch mockup module no longer runs as-is:** it reads
  `theme.WARNING`/`theme.TEXT` (`visual-direction.md` → "Reproducing
  the mockups").
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
- **Queued downloads light amber (`CUE`), not a neutral lamp.** The
  user's part is done; the wait is on the network. Superseded requests
  are `STANDBY`, a faint ring.
- **The status-colour floors are 4.5 on a surface (text) and 3.0 on
  the page ground and a selected row (mark).** Light `SUCCESS` on
  `BG_APP` is 4.14, so a status colour as *text* belongs on a surface.
- **New HISTORY range file `181-210.md`.** `151-180.md` is full.
- CLAUDE.md gained the `active_palette()` rule and `status_lamp.py` in
  the layout.

## 6. Blockers

None.

## 7. Files in progress

None. S31 finished, with no split.

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

- **The cell-widget pixel test on Cocoa:** order-dependent (§181), the
  row pixel tinted a few units toward the accent. Is it hover from the
  cursor? A fix would move the cursor off-screen or clear hover before
  the grab. It does not affect CI.
- **Result messages still on status labels:** Settings' destinations,
  Spotify, Test connection and credentials (`settings_window.py`
  ~:577–1161), and 12 sites on Duplicates (`duplicates_page.py`
  :440–979). One channel migration; fold it into S35a/S35b or give it
  its own commit.
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

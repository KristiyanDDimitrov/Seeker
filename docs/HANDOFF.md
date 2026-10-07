# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S29 part-1 close-out (after `bdf27a4`). Tree clean
  apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 1817 passed, 1 skipped`. Both
  failures are `test_theme.py::test_a_cell_widget_paints_the_rows_own_background[dark|light]`,
  the display-specific failure carried from S28 (§4). `test_theme.py`
  offscreen: 62 passed. `mypy --strict src/` clean, 133 files;
  `ruff check src tests tools` 0.
- **CI:** see the follow-up handoff commit for the run id and result.

## 2. Where we are

S1–S28 ticked; **S29 part 1 (§29.1) done**, stopped at the row's split
point at ~175 K tokens. **Next: S29 part 2** (BRIEF §29.2 Settings,
§29.3 Library). Then S30 (**[ASK]** visual direction).

## 3. Session report (S29 part 1)

Evidence in HISTORY §178.
- `bdf27a4` §29.1: Review candidates show the file name with quality
  and peer as `SECONDARY_ROLE` text; local matches show "Tags: artist
  – title"; section titles count rows; regression test for the tall
  rows (fails on `38fc5a4`, passes on HEAD).

## 4. Key context

- **`elided_text.SECONDARY_ROLE`:** quieter right-aligned text after
  a cell's primary text, colour blended from the item palette
  (`secondary_text_color`, ≥5.9:1 on every row ground). It takes what
  the primary text leaves, with a 45 % floor. Rule in CLAUDE.md (Qt
  section).
- **Review at 960 is tight:** both match columns stretch (Track must
  stay ≥160 px for `test_table_columns`), so the candidate's peer
  elides even at 1280. Worth a column-budget pass in S35b.
- **For §29.2 (mapped, not started):**
  - Tabs: `SETTINGS_TAB_*` at `settings_window.py:63`, built in
    `SettingsPage.__init__` (~:128); groups: Appearance
    `_build_appearance_group` :1171, Notifications inside
    `_build_thresholds_tab` :1234 (group at :1294), Startup
    `_build_startup_group` :1346; thresholds load :1442, save
    `_on_save_thresholds_clicked` :1466.
  - Tab users: `dashboard_page.py:59/1439/1441` (CONNECTION,
    LOCATIONS); `main_window.py:1139` `select_tab`;
    `tests/shell/test_shell_navigation.py:237`;
    `tests/shell/test_elided_text.py:79` and `tools/screenshots.py:549`
    select tabs **by index**, so they move when tabs regroup.
  - Back button: `main_window.py:459` (`settings_back_button`, passed
    to `build_page(header_extra=)`), handler `_on_settings_back_clicked`
    :567. It and the sidebar both call `_show_page(key)`; the only
    extra is "which page". `_previous_page_key` must stay: it also
    drives `_page_to_reopen` (persisting the page before a Settings
    detour). `context.py:84` documents `header_extra` as used only by
    Settings.
- **Harness:** `uv run python tools/screenshots.py --page review
  --theme light` (seconds). To check old behaviour, a `git worktree`
  at an older commit runs with `PYTHONPATH=<wt>/src:<wt>/tests uv run
  --project <repo> pytest …` (verified: imports the worktree's
  `seeker`).
- Carried: the theme-test display failure (cause UNVERIFIED; passes
  offscreen); `MainWindow` does not apply the theme, `main_ui.py`
  does; radon not in the env; never touch slskd or real data; zsh does
  not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171); a palette change must update the chevron
  SVGs (S31).

## 5. Decisions made

- **Secondary text, not a second line or more columns:** CLAUDE.md
  keeps cells one line, and two extra columns (quality, peer) don't
  fit at 960. Peer and quality share one secondary string ("FLAC,
  1050kbps from peer").
- **Both match columns stretch** (Track and the file): Track is half
  the comparison; the file-only stretch failed the 160 px floor.
- **No count at zero** in a Review section title: the empty state says
  it.
- **The row-height item needed no code change**, only a regression
  test, because §176 fixed it; the test was reworked until it failed
  on the old code.
- **Not done:** the three existing copies of the backslash-basename
  logic in `soulseek/` (`client.py:398`, `quality.py:23`,
  `placement.py:250`) were left alone; folding them into
  `formatting.remote_basename` is a refactor for its own commit.

## 6. Blockers

None.

## 7. Files in progress

None. §29.2 and §29.3 are not started.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction (and whether the Dashboard
shows BPM and key); S39 bundle identifier; S42 publishing commands;
X1 and X2 (optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron; keyboard focus and VoiceOver on a
real Mac; hover tooltips on elided cells (now also a Review
candidate's path and a local match's tags); the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); Settings and Duplicates results on
  status labels (S29 part 2); four CLI items (§156); the unrecorded
  transfer id and leftover `.tmp` files (X1); why a shared fake's
  missing method stalls the suite (§171, UNVERIFIED); a location whose
  stored path differs in case from disk maps no files in a merge;
  should item views get a themed focus indicator (§175); the
  Dashboard's Status links clip instead of eliding (S34); why the
  cell-widget background test fails on this display (§177).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

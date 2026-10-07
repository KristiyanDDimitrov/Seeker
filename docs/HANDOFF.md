# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the CI-result handoff note, after the S29 part-2
  close-out `0c9e227` (HISTORY §179). Tree clean apart from the
  untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `1825 passed, 1 skipped`. `mypy --strict
  src/` clean, 133 files; `ruff check src tests tools` 0. The
  display-specific `test_theme.py::test_a_cell_widget_paints_the_rows_own_background[dark|light]`
  passed this run and failed in an earlier one this session
  (`2 failed, 1821 passed, 1 skipped`): intermittent here, not fixed.
- **CI:** `0c9e227`'s run `37595631436` green.

## 2. Where we are

S1–S29 ticked. **Next: S30, an [ASK] row** (BRIEF §30, visual
direction): it starts only after Kris's explicit yes, and it ends at
§30.3's hard stop for Kris's pick. Then S31.

## 3. Session report (S29 part 2)

Evidence in HISTORY §179.
- `0d536e7` §29.2a: Settings tabs General / Library / Connections /
  Matching; every `SETTINGS_TAB_*` tested; copy names the new tabs.
- `9c88063` §29.2b: thresholds as 0–100 spin boxes, needs-review
  below auto (refused), warning below 80; results on an InlineNotice.
- `08ef76f` §29.2c: found defect, a saved threshold of 0 read as
  unset; `matching.resolve_thresholds` (`is None`).
- `83646f0` §29.2d: Back button removed, sidebar only.
- `b7fa6e2` refactor: `theme.scrollable`.
- `4e37c5f` §29.3a: Library options and actions grouped by job; the
  page scrolls.
- `ff3f410` §29.3b: "Tag N selected on Dashboard", or disabled.

## 4. Key context

- **Settings tabs** are `SETTINGS_TAB_GENERAL/LIBRARY/CONNECTIONS/
  MATCHING`; the screenshot harness writes `settings-general` …
  `settings-matching`. Delete stale `tools/.screens/settings-*`
  images if an old run left them.
- **Library is a `theme.scrollable` page** of four `QGroupBox`es
  (Tag Options, Tags, Cover Art, File Names); the job sentences are
  `help_text.LIBRARY_*_TEXT`. §34 does its visual treatment.
- **`tag_selected_button`'s state is render-decided**
  (`_render_tag_selected_button`, skips while `tag_selected` is busy).
  A Library test that needs a selection to survive a run must select
  a playlist whose statuses the fake serves: the post-tag
  `refresh_track_table` otherwise empties the table.
- **Spin boxes:** `QDoubleSpinBox` shows the system locale's decimal
  comma here ("75,0"); Return is `lineEdit().returnPressed`
  (observed). Their arrows are tiny under the current theme (S31).
- **The tooltip sweep** cannot tell a helper's `tooltip` parameter
  from peer text: keep `setToolTip(help_text.X)` at the call site.
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  radon not in the env; never touch slskd or real data; zsh does not
  word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171); a palette change must update the chevron
  SVGs (S31); old-commit checks run in a `git worktree` with
  `PYTHONPATH=<wt>/src:<wt>/tests uv run --project <repo> pytest …`.

## 5. Decisions made

- **Sidebar only, no Back** (BRIEF's recommendation, tested): Back
  passed no focus or state, and every page has a sidebar button.
  Promoted to CLAUDE.md (Qt section).
- **Threshold warning, not a floor:** auto below 80 saves, with an
  InlineNotice warning naming Tag playlist's consequence (brief: warn,
  don't forbid). Needs-review ≥ auto stays refused.
- **Three sibling groups on the Library tab**, not the Default
  Destination group nested inside Playlist Destinations.
- **`resolve_thresholds` folded four copies** in the fix commit: the
  fix is replacing `or`, and one helper is that fix. Rule promoted to
  CLAUDE.md.
- **Group title "Notifications"** (brief's wording), not "Menu Bar
  Notifications"; the checkboxes already say what they notify.

## 6. Blockers

None. S30 waits on Kris's yes (an approval gate, not a blocker).

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction ("Booth", "Harmonic", a mix
or neither, and whether the Dashboard shows BPM and key); S39 bundle
identifier; S42 publishing commands; X1 and X2 (optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron; keyboard focus and VoiceOver on a
real Mac; hover tooltips on elided cells; the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- **Result messages still on status labels** (scoped this session):
  Settings' default and per-playlist destinations, Spotify, Test
  connection and credentials (`settings_window.py` ~:577–1161), and
  12 sites on Duplicates (`duplicates_page.py` :440–979). One channel
  migration; fold into S35a/S35b or its own commit.
- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); four CLI items (§156); the
  unrecorded transfer id and leftover `.tmp` files (X1); why a shared
  fake's missing method stalls the suite (§171, UNVERIFIED); a
  location whose stored path differs in case from disk maps no files
  in a merge; should item views get a themed focus indicator (§175);
  the Dashboard's Status links clip instead of eliding (S34); why the
  cell-widget background test fails on this display, intermittently
  (§177); Review's column budget at 960 (S35b); three copies of the
  basename logic in `soulseek/` (a refactor commit).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

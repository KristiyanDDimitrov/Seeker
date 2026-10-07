# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the CI-result handoff note, after the S28 part-2 close-out `dccaeca`. Tree
  clean apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 1807 passed, 1 skipped`. Both
  failures are `test_theme.py::test_a_cell_widget_paints_the_rows_own_background[dark|light]`,
  which also fails on `bda43a1` (see §4). Offscreen: `1809 passed, 1 skipped`.
  `mypy --strict src/` clean, 133 files; `ruff check src tests tools` 0.
- **CI:** `dccaeca`'s run `37585880304` green.

## 2. Where we are

S1–S28 ticked. **Next: S29** (BRIEF §29, Review and Settings
information architecture; split point after §29.1).

## 3. Session report (S28 part 2)

Evidence in HISTORY §177.
- `b6442c8` §28.3: `ui/empty_state.py` `EmptyState` on Search, both
  Sharing tables (the span-row fake is gone), History, the three Review
  sections and Downloads.
- `c7b3122` §28.4: copy pass; Downloads' Role column becomes an Upgrade
  `BADGE_ROLE` pill; `widgets.CloseButton` replaces the notice's "X";
  build time shown in local time.

## 4. Key context

- **Empty tables:** `EmptyState(table, EmptyGlyph.X, text, action=)`
  shows itself from the row count. It also sets the table's
  **minimum height** (chrome + sentence + action). A new page with a
  short table should check its layout in the harness at 960×640.
- **Badges:** `item.setData(elided_text.BADGE_ROLE, "Upgrade")` paints
  a pill before the text. The colours come from the item's palette
  (Highlight/AlternateBase/Text) because `theme.py` imports
  `elided_text`, so importing `theme` back is a cycle (reproduced).
- **The local theme-test failure** (see §1): on this machine's LG 4K
  at DPR 2.0 the row samples (253,253,254) against the cell widget's
  (255,255,255). It fails the same on clean `bda43a1`, passes
  offscreen, and moving the cursor away doesn't change it. Part 1 saw
  no failures, with the X9 Pro tests skipping (29 skipped); they ran
  here (1 skipped). Cause UNVERIFIED. Re-check on the next run before
  calling it a regression.
- **For S29:** Settings and Duplicates still report some results on
  status labels (the open question carried below). Review now has
  `review_needs_empty`/`review_upgrades_empty`/`review_local_empty`;
  keep them if sections move. Sharing's framing text is clipped at
  960×640, a little more now that its tables reserve height (S35b).
- **Harness:** `uv run python tools/screenshots.py --page review
  --theme light` (seconds). An empty-state screenshot needs an empty
  `FakeApplication`; the harness's demo data fills every table.
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  radon not in the env; never touch slskd or real data; zsh does not
  word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171); a palette change must update the chevron
  SVGs (S31).

## 5. Decisions made

- **The empty state lives inside the viewport, driven by the model**,
  not a stacked widget swapped by each page: headers stay put and no
  render can forget to switch it. The Dashboard's own track panel
  (a stack with Load tracks) was left as it is for S34.
- **Review's empty sections use a check glyph:** nothing to decide is
  good news, so they offer no action.
- **Downloads got an empty state too**, beyond the brief's list.
- **"Scan library" / "Match tracks"**, named by verb so they no longer
  read as synonyms, and matching their existing outcomes.
- **The Upgrade badge marks only upgrades.** A plain download is what
  every other row is, so it gets no badge.
- **Standing rule promoted to CLAUDE.md:** empty tables use
  `EmptyState`, row markers are `BADGE_ROLE` pills (Qt section).

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
real Mac; hover tooltips on elided cells; the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); Settings and Duplicates results on
  status labels (S29); four CLI items (§156); the unrecorded transfer
  id and leftover `.tmp` files (X1); why a shared fake's missing
  method stalls the suite (§171, UNVERIFIED); a location whose stored
  path differs in case from disk maps no files in a merge; should item
  views get a themed focus indicator (§175); the Dashboard's Status
  links clip instead of eliding (S34).
- New: why the cell-widget background test fails on this display
  (§1, §4).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

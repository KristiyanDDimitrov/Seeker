# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S34 part 2 close-out (HISTORY §185). Tree clean apart
  from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `1979 passed, 1 skipped` (+17). The known
  Cocoa-only pair
  `test_a_cell_widget_paints_the_rows_own_background[dark]`/`[light]`
  passed this run; it is order-dependent (§181) and failed in an
  earlier full run this session. `mypy --strict src/` clean, 137
  files; `ruff check src tests tools` 0.
- **CI:** `e2d7653`'s run `37638242820` green.

## 2. Where we are

S1–S34 ticked. **Next: S35a** (BRIEF §35, first bullet): Search,
Downloads, History, Duplicates.

## 3. Session report (S34 part 2)

Evidence in HISTORY §185.
- `108221e`: `local_files.has_art` (schema, migration, scanner read
  and NULL backfill, set by tagging and Fix missing cover art).
- `4e9dd67`: `TrackStatus.has_art` for in-library tracks.
- `d68c187`: Library's tag-state track list (writes and shows the
  shared track selection); action groups as titled cards in a
  wrapping 280 px column; results panel under the list.

## 4. Key context

- **The first scan after this upgrade reads every file's art once**
  (6,921 rows NULL in the real DB, rehearsed on a copy). Scans count
  those as unchanged, so the summary looks normal; it is just slower
  once, longest on the X9 Pro.
- **`_action_group` (`tagging_panel.py`) is the titled-card
  component**: `make_card` + `sectionHeaderLabel` title + muted
  sentence + rows, title as accessible name. Settings' bare Fusion
  `QGroupBox`es (S35b) should move to it; lift it into `theme` or a
  `ui/` module when the second user arrives.
- **Buttons in a narrow column go in `FlowLayout`**, not
  `action_row`: an `action_row`'s minimum width made the 340 px column
  scroll sideways. `test_button_sizing` accepts flow rows.
- **Lamp-in-cell recipe, now used twice** (Dashboard, Library): item
  icon `status_lamp.lamp_icon(lamp, theme.active_palette())`, table
  `setIconSize(LAMP_SIZE)`, `set_secondary_min_share(view, 0.0)`, and
  reload on theme switch (`MainWindow.on_theme_changed`). Downloads
  (S35a) wants `DOWNLOAD_LAMPS` the same way.
- **Showing a shared selection in a table**: build a `QItemSelection`
  and `ClearAndSelect` with both the table's and the selection model's
  signals blocked, deferred off `changed` (`LibraryPage.
  _show_shared_track_selection`).
- Carried: `set -o pipefail` before `pytest … | tail && git commit`;
  never touch slskd or real data; zsh does not word-split `$var`;
  judge fine detail on a 2× Cocoa grab; the full suite takes ~4 min,
  so run it in the background.

## 5. Decisions made

- **`has_art` is a column, not a per-visit tag read**: the fact is
  the file's, the scanner already opens each file, and a read per row
  per playlist switch from an external drive was too slow to repeat.
  NULL means "not read", never 0. Promoted to CLAUDE.md.
- **Library lists in-library tracks only**: tagging skips anything
  else, and the Dashboard already shows the rest.
- **"Tag N selected"** drops "on Dashboard": the selection is now
  visible on Library itself. Promoted to CLAUDE.md (both tables write
  `track_ids`).
- **Tag options sit under Tags** in their own card, with a sentence
  saying they also apply to the Dashboard's Tag (§29.3 kept them a
  group of their own; this keeps that). Titles in sentence case.
- **One commit for the list and the cards**: the results panel's move
  and the column width belong to both.

## 6. Blockers

None.

## 7. Files in progress

None: S34 is committed whole.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** after the next scan, Library's Cover
art column against a few real files (Embedded/Missing); the first
scan's extra time on the X9 Pro; the Dashboard's lamps and amber
meter on a real display in both themes; the playlist counts against
the real library; plus everything carried in
`git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account wizard with
Docker, nested-location Fix…, the stress test, `qsvg` and Barlow and
nav icons in the packaged app, keyboard focus and VoiceOver).

## 9. Open questions

- **Refresh playlists drops the Dashboard's selection** (pre-existing:
  `_populate_playlists`' `clear()` fires `currentItemChanged(None)`).
  Not folded into part 2; take it in S35b or as its own test-first fix.
- The Dashboard's table does not show a selection made on Library
  (harmless: nothing there acts on it). Library's context sentence
  could shrink now that the list shows what it acts on.
- `poll_selected_playlist` renders a pre-switch result for one tick
  (pre-existing, self-correcting).
- **Result messages still on status labels:** `settings_window.py`
  ~:577–1161, 12 sites in `duplicates_page.py`, and the wizard's
  Spotify and Library steps (S35a/S35b).
- Carried unchanged: `git show cd3ba1a:docs/HANDOFF.md` §9 and
  `git show 8eee663:docs/HANDOFF.md` §9 (Review's column budget at 960
  for S35b, Settings' subtitle wrap, the wizard's empty progress row).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S34 part 1 close-out (HISTORY §184). Tree clean apart
  from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 1962 passed, 1 skipped`
  (+20). The two are the known Cocoa-only pair
  `test_a_cell_widget_paints_the_rows_own_background[dark]`/`[light]`
  (order-dependent, §181; pass offscreen, as on CI). `mypy --strict src/`
  clean, 137 files; `ruff check src tests tools` 0.
- **CI:** CI_RESULT.

## 2. Where we are

S1–S33 ticked; **S34 stopped at its split point, after the
Dashboard.** **Next: S34 part 2, Library** (BRIEF §34, second bullet),
then tick S34.

## 3. Session report (S34 part 1)

Evidence in HISTORY §184.
- `56b8a18`: a cell's icon counts against its primary text
  (`elided_text._icon_width`).
- `4ae6879`: secondary text asks for the right margin it is painted
  inside (`_secondary_area`).
- `8140b0f`: the Dashboard's Status column is lamps, not links;
  candidate note and percentage as secondary text.
- `bae6ef7`: the strip's busy bar animates again after progress
  (`theme.set_indeterminate`).
- `2f68c98`: `theme.style_meter`, the segmented amber meter (Dashboard
  and the strip).
- `bb24f84`: `MISSING_STATES` (refactor).
- `c41822c`: secondary width measured fractionally, rounded up.
- `c79e3a3`: playlist rows with counts
  (`DashboardService.get_playlist_summaries`, `PlaylistSummary`).

## 4. Key context

- **Part 2's main question: nothing stores whether a file has
  embedded art.** `local_files` has `tagged_at`; `tracks` has
  `album_art_url` (Spotify's URL), no "art embedded" flag anywhere
  (`grep -n art src/seeker/database/schema.py`). "Missing art" on
  Library's track list needs either a tag read per file on a worker
  (mutagen; slow at scale) or a new `local_files` column filled at
  scan and tag time (a migration, rehearsed on a copy, §0.7). Decide
  before building the table.
- **"Tag selected" today reads `PlaylistSelection.track_ids`**, which
  only Dashboard's track table writes (`_on_track_selection_changed`).
  Library's own list must write the same seam, never a second one.
- **New reusable pieces for S35:** `theme.style_meter(bar)` (no
  label; call again on a theme switch), `theme.set_indeterminate(bar)`,
  `elided_text.set_secondary_min_share(view, share)`, and the lamp as a
  cell icon (`item.setIcon(status_lamp.lamp_icon(lamp, palette))`, the
  table's `setIconSize(LAMP_SIZE)`, the palette in the rebuild key).
  Downloads (S35a) is the last `style_determinate_progress_bar` and
  `TwoToneProgressBar` user, and its status column wants
  `DOWNLOAD_LAMPS`.
- **`test_progress_text` measures every bar whose `text()` is
  non-empty**; a hidden label still formats "50%", so a label-less bar
  needs `setFormat("")` (style_meter does it).
- **The selector-less-sheet sweep now accepts `""`.**
- Carried: `set -o pipefail` before `pytest … | tail && git commit`;
  the cell-widget pixel pair is order-dependent on Cocoa (failed in a
  narrow run on stashed HEAD this session, passes offscreen); never
  touch slskd or real data; zsh does not word-split `$var`; judge fine
  detail on a 2× Cocoa grab.

## 5. Decisions made

- **The Dashboard's primary action is the next-step notice's button**,
  already the page's only accent button; the row's Download hides while
  the notice offers it. No second primary.
- **A status label wins its cell** (`set_secondary_min_share(…, 0.0)`
  on the Dashboard): at 960 the percentage and candidate note give way
  first, readable on hover. Review keeps the 45 % share.
- **Count copy:** "8 · 2 missing", "34 · complete", "21 tracks" (never
  loaded). "all in library" was tried and elided beside names at 1280.
  "SoulSeek candidate found" shortened to "Candidate found" (the column
  is already about SoulSeek).
- **Counts refresh in place by playlist id**, never by repopulating,
  which drops the selection. Promoted to CLAUDE.md: lamps in cells,
  `style_meter`, `set_indeterminate`, the palette rebuild key.

## 6. Blockers

None.

## 7. Files in progress

None: part 1 is committed whole. Part 2 starts from
`src/seeker/ui/pages/library_page.py` (202 lines) and
`tagging_panel.py`.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** the Dashboard's lamps and amber meter
on a real display in both themes (light mode's lit lamps look muddy at
1× in the harness; judge at 2×); the playlist counts against the real
library (6 loaded playlists of 215); plus everything carried in
`git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account wizard with
Docker, nested-location Fix…, the stress test, `qsvg` and Barlow and
nav icons in the packaged app, keyboard focus and VoiceOver).

## 9. Open questions

- **Refresh playlists drops the Dashboard's selection** (pre-existing:
  `_populate_playlists`' `clear()` fires `currentItemChanged(None)`).
  Fold into part 2 or S35b as its own test-first fix.
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

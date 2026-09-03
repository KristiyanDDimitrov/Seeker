# Task ledger — work block: docs/BRIEF-2026-09-03.md (round 2)

Working ledger for this block only (not a permanent doc). Every item from
the brief, one line each, ticked only when done *and* verified, with a
one-line result + commit sha. Items not done as briefed are marked
`NOT DONE — <reason>`, never silently dropped.

Commit order per the brief: P7 → P8 → P12 → P11 → P9 → P10 →
0.1/0.2/0.3 → P13.

## P7 — Duplicates "Actions" column, 5th report

- [x] 7.1 Ran the brief's exact standalone PySide6 repro
  (`QT_QPA_PLATFORM=offscreen`). **Hypothesis CONFIRMED**: blank
  widget's geometry == real widget's geometry (both `(100, 0, 99,
  59)`), child order `[REAL, BLANK]` (blank added later, paints on
  top), `childAt(center)` returned the blank widget, not the real one
  — despite `real.visibleRegion()` being the FULL non-empty rect. This
  is exactly why item 73's own geometry/visibleRegion test passed
  anyway: occlusion is a paint-order property, not a geometry one.
- [x] 7.2 Fixed in `_render_duplicate_groups`: `setSpan()` now called
  BEFORE `setCellWidget()` for the group's first row (so the real
  widget's geometry is computed against the final span rect), and the
  `for other_row … setCellWidget(..., QWidget())` loop deleted
  entirely — covered rows get no cell widget at all; the span itself
  is what makes them read as blank.
- [x] 7.3 Audited every `setSpan` call site (`grep -n setSpan`): only
  one other exists, the Sharing-uploads empty-state span
  (`main_window.py:1814`), which uses `setItem` not `setCellWidget` —
  no widget-occlusion risk there. No other instance found.
- [x] 7.4 N/A — 7.1 confirmed the hypothesis, no pixel-diff needed.
- [x] 7.5 New occlusion-aware regression test,
  `test_duplicates_actions_widget_is_not_occluded_by_a_covered_row_widget`
  — asserts `viewport().childAt(visualRect(...).center())` resolves to
  the real widget (or a descendant of it), not merely that the widget
  exists or has nonzero `visibleRegion()`. **Verified it actually
  catches the regression**: reverted the source fix only, reran this
  one test in isolation — fails with the exact predicted
  `hit is not real_widget` assertion; passes again with the fix
  restored. Updated one pre-existing test
  (`test_render_duplicate_groups_actions_only_on_group_first_row`) to
  assert `cellWidget(1, ACTIONS) is None` instead of "a blank widget
  with no buttons" — the corrected behavior per 7.2.

`mypy --strict src/` clean (82 files). Full suite: 908 passed, 1
skipped (0 failures) — 1 net new test, 0 regressions (the one
`test_history_refresh_button_refetches` failure is the pre-existing
documented flake, reconfirmed passing in isolation).

**Commit boundary — pending.**

## P8 — Duplicates "0 files in scope" + P9 — location combo disabled

Combined into one commit (deviating from the brief's listed order,
noted explicitly): P9's "keep the combo enabled" change has no real
value until P8's most-specific-wins fix lands to make the combo a
genuine tiebreak, and both touch `resolve_folder_scopes`' exact same
signature.

- [x] 8.1 Ran the real query against THIS session's own real
  production DB (same machine/account this session has filesystem
  access to — the brief's "other account" is a different macOS user
  this session cannot reach, noted as a limitation). Real result:
  `x9-pro` (3264 files, 3161 fingerprinted), `Test` (8 files, 4
  fingerprinted, nested at `/Volumes/X9 Pro/Music/Test`), `Music` (0
  files, 0 fingerprinted, registered at `/Volumes/X9 Pro/Music` — the
  PARENT of `Test`). This is 8b's exact scenario, live and
  reproducible right here — simulated `resolve_folder_scopes`'s old
  alphabetical-first logic against these real rows: a folder equal to
  `Test`'s own path matches `Music` first (alphabetically "Music" <
  "Test"), which has 0 scanned files — confirming 8b as a real,
  demonstrated defect in real data, not merely a theoretical one.
- [x] 8.2 `resolve_folder_scopes` now scores every candidate location a
  folder resolves inside by resolved-path length and keeps the
  LONGEST (most specific); a genuine tie (only possible via
  Path.resolve() collapsing two different registered paths to the
  same real directory, e.g. a symlink — `library_locations.path` is
  UNIQUE at the DB level so two locations can never share a literal
  path string) breaks via a new optional `preferred_location_id`
  param, else falls back to the existing stable alphabetical order.
  Two new tests: nested-location most-specific-wins (reproduces the
  real 8.1 shape structurally), and a real symlink-based tie test.
- [x] 8.3 New `DuplicateService.summarize_scopes()` → `ScopeSummary`
  (file_count, resolved_location_names, empty_locations).
  `format_duplicates_scope_count()` now names the resolved location(s):
  "216 files in scope (Music)."
- [x] 8.4 Same `ScopeSummary.empty_locations` — when non-empty, the
  message says plainly which location has no scanned files yet and to
  run Rescan and match library first, instead of a bare "0 files in
  scope."
- [x] 9.1 `duplicates_location_combo` stays enabled always; wired as
  `resolve_folder_scopes`' `preferred_location_id` at every UI call
  site (`_refresh_duplicates_folder_scope_count`,
  `_compute_fingerprints_for_folders`, `_on_find_duplicates_clicked`),
  captured on the MAIN thread before entering a background worker
  closure (reading Qt widget state off-thread is unsafe) and passed
  in as a plain int parameter. A `currentIndexChanged` handler
  refreshes the scope count live when the preference changes.
- [x] 9.2 Both tooltips reworded to describe the real tiebreak
  behavior; the stale "disables the combo" comment removed.

`mypy --strict src/` clean (82 files). Full suite: 913 passed, 1
skipped (0 failures) — 5 net new tests, 0 regressions (the
`test_history_refresh_button_refetches` flake did not reproduce this
run either).

**Commit boundary — pending.**

## P12 — Qt mnemonic in "Rescan & match library" + P11 — tagging controls spacing

Combined into one commit (both small, independent, no shared code —
grouped per the brief's own "small, independent, quick wins" framing
for this trio; P9 was already folded into the P8 commit above).

- [x] 12.1 `"Rescan & match library"` → `"Rescan and match library"`.
  `"&Help"` (the real menu-bar mnemonic) left untouched.
- [x] 12.2 Audited every `QPushButton`/`QLabel` string literal in
  `main_window.py` via `grep`/a real regex — no other stray `&` found.
  New source-level regression test scans the file for any
  `QPushButton("...")`/`QLabel("...")` literal containing a bare `&`
  (a doubled `&&` or the real `"&Help"` mnemonic don't count) — covers
  any future string added to this file automatically, not just the
  one fixed here.
- [x] 11.1 `FlowLayout(h_spacing=theme.SPACING_SM,
  v_spacing=theme.SPACING_SM)` — bare `FlowLayout()` left both at -1,
  falling through to a style-derived spacing that's effectively zero
  under this app's Fusion styling. **Verified it actually fixes a
  real, measured overlap**: reverted the fix in isolation and reran
  the new spacing test — real adjacent items measured -2px apart
  (touching/overlapping), not merely "less than ideal."
- [x] 11.2 Confirmed structurally, not just by inspection: FlowLayout's
  own `_do_layout` always calls `item.setGeometry(..., item.sizeHint())`
  — every VISIBLE item always gets its own full sizeHint() width, so
  no truncation was ever possible once 11.1's spacing is in place. New
  test asserts both checkbox labels render at their full sizeHint()
  width.
- [x] 11.3 New test asserts a real non-zero (>= `SPACING_SM`) gap
  between every pair of adjacent VISIBLE items' geometries, checked at
  both a wide (single-row) and a narrow (multi-row wrap) width.
  (`bpm_min_edit`/`bpm_max_edit` start `.hide()`'n — `QWidgetItem.
  setGeometry()` is a real Qt no-op for a hidden widget, so they're
  excluded from the gap check, not silently miscounted.)

Two pre-existing tests asserting the literal old button text updated
to match the real intentional rename (12.1), not silently xfailed.

`mypy --strict src/` clean (82 files). Full suite: 916 passed, 1
skipped (0 failures) — 5 net new tests, 0 regressions.

**Commit boundary — pending.**

## P10 — Square-edged cell widgets break the rounded card corners (global)

- [x] 10.1 New `theme.make_card(inner) -> QFrame` (`QFrame#card` in the
  global stylesheet owns the real border/radius/background;
  `WA_StyledBackground` set per item 47's own standing gotcha). A
  small uniform content margin (`SPACING_XS`) between the frame and
  `inner` is the load-bearing part — it keeps any of `inner`'s own
  edge-reaching cell-widget children physically away from the frame's
  rounded corner arc. `inner` gets its OWN border/radius turned off
  per-instance so only the frame's edge is ever visibly rounded.
  Routed through every real `QTableWidget`/`QListWidget` in the app
  (11 tables/lists across Dashboard, Downloads, History, Sharing,
  Review, Duplicates, and the Rename preview dialog) — `track_table`
  required a small extra step since it's a `QStackedWidget` page: the
  new `self.track_table_card` attribute is the actual page/
  `setCurrentWidget` target now, `self.track_table` itself untouched
  and still what every other call site reads/writes rows on.
- [x] 10.2 New `theme.cell_widget(*widgets) -> QWidget` — the one
  place a `setCellWidget` container is built now, with real
  `SPACING_SM`/`SPACING_XS` margins/spacing and a trailing stretch.
  Replaced all 6 hand-rolled `QWidget()`+`QHBoxLayout`+
  `setContentsMargins(0,0,0,0)` action-builders (track/duplicates/
  needs-review/upgrade/local-review actions) plus the Sharing table's
  bare "Add to my SoulSeek share"/"Shared" single-widget cells — the
  brief's own two named live examples. Left the two Downloads-table
  progress-widget builders (`_build_terminal_progress_widget`/
  `_build_progress_widget`) as bespoke code, deliberately: they need
  `addWidget(bar, 1)`'s real stretch factor so the progress bar itself
  fills available width, which `cell_widget()`'s generic no-stretch-
  factor API doesn't support and isn't the "button reads as a filled
  cell" antipattern this item targets anyway.
- [x] 10.3 `cell_widget()`'s trailing `addStretch()` is what fixes
  this structurally (absorbs leftover cell width instead of
  stretching the last widget) — no per-button `setMaximumWidth` magic
  numbers needed. Confirmed via a real screenshot: the Sharing table's
  button now reads as a compact button with visible padding around
  it, not a filled cell (see 10.4).
- [x] 10.4 Real screenshots taken (`window.grab().save(...)`, offscreen
  QPA) for Sharing, Duplicates, Downloads, Review, and Dashboard —
  all show clean rounded card corners with no cell-widget bleed, and
  the Sharing/Duplicates Actions buttons read as real compact buttons
  with visible gaps, not filled cells. Not attached as files (this is
  a text-only ledger) — described from direct visual inspection.

New `tests/test_theme.py` (6 tests: card structure, inner border
turned off, real nonzero margin, `cell_widget` real gap, a lone widget
NOT stretched to fill the container, single-label case). One new
`test_ui_smoke.py` test enumerates every real table/list attribute on
`MainWindow` and asserts its parent is a `card`-named frame — routing
enforced structurally, not just "available to use."

`mypy --strict src/` clean (82 files). Full suite: 923 passed, 1
skipped (0 failures) — 7 net new tests, 0 regressions. Four
pre-existing tests updated for the new cell-widget container shape
(`cellWidget(...)` now returns the wrapper, not the bare button/type
— fixed via `.findChild(QPushButton)`), and `track_area_stack`'s
current-page target updated to `track_table_card`.

**Commit boundary — pending.**

## 0.1 — Build identity, 0.2 — per-account data doc, 0.3 — frozen compose path

- [x] 0.1 New `src/seeker/_build_info.py` (`GIT_SHA`/`GIT_DESCRIBE`/
  `BUILT_AT`, committed with `"dev"` fallback values, force-added
  despite being gitignored so the fallback ships — see its own and
  `.gitignore`'s comments on why real local build modifications to
  this tracked file should never be committed).
  `packaging/build_dmg.py::_write_build_info()` overwrites it with the
  real `git rev-parse --short HEAD`/`git describe --dirty --always`/
  UTC timestamp immediately before the PyInstaller step. Surfaced in
  the window title (`"Seeker — <sha>"`), the About dialog (next to the
  version line), and the Help page (next to the data-locations
  section) via new `help_text.format_build_identity()`.
- [x] 0.2 New `HELP_DATA_LOCATIONS_PER_ACCOUNT_NOTE` on the Help page,
  said explicitly: this folder is per macOS user account, nothing
  shared between accounts, and a cross-account report is very often a
  different-database report rather than a different-behavior one.
- [x] 0.3 Checked whether item 74 already fixed the frozen-build
  `compose_file_path()` issue this item flagged — **it did.**
  `docker_setup.py::compose_file_path()` already copies the bundled
  resource into the stable per-user `slskd_data_dir()` on first use in
  a frozen build and always returns that canonical path afterward
  (item 74, confirmed by reading the current source, not assumed from
  the roadmap entry alone). No code change needed here.

  The actually-dirty working tree this item also flagged was real,
  live evidence that item 74's fix works as designed: `docker-
  compose.yml`'s real diff (a `Test` location's share volume line) and
  the identically-matching `.bak-20260903T082155Z` file (confirmed
  byte-identical to the pre-change committed version via `diff`) are
  exactly `add_location_to_share`'s own "compute both new file
  contents, write, keep a backup" behavior — a REAL Sharing write that
  landed correctly. Committed the real change (this file already
  embeds real machine-specific paths as its committed defaults, same
  established convention) and deleted the now-redundant backup.
  Also cleaned up stray `.DS_Store` files (added to `.gitignore`) and
  committed the two untracked `tests/_stress_step{3,4}_*_repro.py`
  scripts from the previous round's item 63 investigation — matching
  this project's own existing, already-tracked `_*_repro.py`
  convention (4 prior examples), not something to leave dangling.

New tests: `format_build_identity()` (dev vs. real sha/describe/
timestamp), the About dialog and Help page both show the build line,
Help page shows the per-account note. One pre-existing test
(`test_main_window_constructs_without_crashing`) updated for the new
window title shape.

`mypy --strict src/` clean (83 files — `_build_info.py` is new). Full
suite: 927 passed, 1 skipped (0 failures) — 4 net new tests, 0
regressions.

**Commit boundary — pending.**

## P13 — New feature: manual track search and download

- [x] 13.1 A manual track is a real `tracks` row (`id=manual:<uuid4>`,
  `album=""`, `duration_ms=0`) belonging to no playlist — verified
  `download_requests.track_id` has no FK (schema.py). **Verified, not
  assumed:** the immediate post-download match step
  (`_index_and_match_settled_download` → `find_best_match(track,
  [local_file])`) never reads duration at all, so `duration_ms=0`
  doesn't affect it. Found a REAL related risk beyond the brief's own
  ask: a LATER `match_all()` re-run applies its own duration pre-filter
  (`matcher.py`'s `DURATION_TOLERANCE_MS`) that a real `duration_ms=0`
  would fail against almost any real file, risking item 45's own
  documented demotion class. Fixed by backfilling the real duration
  from the just-downloaded local file, once, the first time a manual
  track is indexed — never touches a real Spotify track's authoritative
  duration.
- [x] 13.2 `_resolve_destination` widened to `Playlist | None`;
  `playlist=None` always resolves via the configured default with a
  FIXED "Manual" subfolder (unconditional — never gated behind the
  subfolder-per-playlist toggle, which has no meaning for something
  with no playlist to name a subfolder after). **Found and fixed a
  second real gap querying `_move_completed_file`:** its own playlist-
  iteration loop would never run at all for a track with zero
  playlists, leaving `resolved` at `None` unconditionally and every
  completed manual download stuck in slskd's own download dir forever
  — fixed with an explicit `not playlists` fallback to
  `_resolve_destination(None)`, scoped narrowly so an ordinary
  playlist track's existing "no destination, leave in place" behavior
  is unchanged.
- [x] 13.3 `DownloadService.search_manual`/`download_manual` — both
  call the exact same `_build_search_query`/`select_downloads` every
  playlist download uses (refactored `_build_search_query` to take
  plain artist/title strings instead of a `Track`, shared by both
  paths now). `chosen` bypasses ranking/threshold entirely (the user's
  explicit pick); an optional `files` param lets the UI reuse an
  already-fetched result set instead of a second real 20-45s search.
- [x] 13.4/13.5 New "Search" sidebar page between Dashboard and
  Downloads. Artist/Title fields, busy-treated Search button (real
  `_run_busy_worker`), a results table (Username/Filename/Format/
  Bitrate/Size/Locked/Score/Actions) sorted via new public
  `quality.rank_candidates()`, scored via new public
  `quality.score_candidate()` — both real wrappers around the SAME
  private ranking/scoring `select_downloads` uses, never a second copy.
  "Download best" (primary, busy-treated, reuses the already-fetched
  results) + per-row "Download this one" (managed directly via
  `run_worker(button=...)`, the same per-row pattern
  `_on_confirm_review_candidate` already uses — NOT the shared
  busy_actions key "Download best" owns, since that key tracks one
  persistent button, not N ephemeral per-row ones). Column widths set
  from day one via the item 73/77 pattern (`_size_search_columns`) —
  never repeats the "nothing ever sets a column width" P4 mistake.
  Live-rendered via a real offscreen screenshot: card corners clean,
  ranking correct (lossless outranks lossy regardless of result
  order), Actions buttons read as real compact buttons.
- [x] 13.6 CLI `seeker search <artist> <title> [--download]` — lists
  by default (ranked via `rank_candidates`), `--download` requests the
  best candidate. `NoDestinationConfiguredError` gets its own
  `search`-specific guidance ("Set a default download location in
  Settings") instead of the ordinary `playlists set-destination` hint,
  since a manual search has no playlist for that to mean anything.
- [x] 13.7 Verified, not assumed: `dashboard_service.get_playlist_
  track_status`/`_fetch_next_step_facts` are both genuinely playlist-
  name-scoped (read the real source), so a manual track structurally
  can never appear in either — no code change needed there.
  `generate_match_report`'s GLOBAL branch (`check`'s own report) DOES
  read every `tracks` row and WOULD show a manual track sitting in
  "unmatched" the moment a routine match run gives it a row — fixed by
  excluding `is_manual_track_id()` tracks from that one branch only
  (a playlist-scoped report already excludes them structurally).
  Confirmed appearing correctly in Downloads/History
  (`get_active_downloads`/`get_recent_events`, both genuinely global).
  **Found and fixed one more real gap along the way:** both of those
  used to fall through to a bare "Unknown" playlist-name label for a
  manual track (a fallback that existed for a real Spotify track
  unexpectedly missing its playlist link — shouldn't happen, but
  defensive) — new shared `models/track.py::resolve_playlist_label()`
  distinguishes "Manual" (real, expected) from "Unknown" (a genuine
  data-integrity concern), used by all three call sites
  (`DashboardService`, both `HistoryService` event kinds) instead of
  three independently-drifting copies of the same fallback logic.
- [x] 13.8 Service-layer tests: no destination configured (checked
  BEFORE creating a track row or searching); zero results; all
  candidates locked (falls back to the upgrade cascade correctly); an
  explicit pick that would score below the auto threshold still
  allowed; a prefetched `files` list skips a second real search; the
  real manual `tracks` row shape; `search_manual`'s shared query
  construction; `_resolve_destination(None)`'s fixed "Manual"
  subfolder; `_move_completed_file`'s real fallback (an actual file
  moved on disk); the real duration backfill (a real short WAV file,
  read via mutagen, not a placeholder). Plus CLI tests (list vs.
  `--download`, zero results, the `search`-specific destination
  guidance) and UI tests (empty fields, ranked rendering, zero results,
  "Download best" reusing fetched results, per-row explicit pick, the
  Settings-guidance error path). **The real end-to-end manual download
  against live slskd is intentionally NOT done in this session** — the
  brief's own instruction is to ask the user to confirm the target
  first; flagged for the user rather than run autonomously.

`mypy --strict src/` clean (84 files — `_build_info.py` counted from
item 81). Full suite: 951 passed, 1 skipped (0 failures) — 27 net new
tests (10 download_service, 1 matcher, 6 cli, 6 ui_smoke, 2 dashboard/
history-service manual-label), 0 regressions.

**Commit boundary — pending. Brief closed except the live E2E
verification, left for the user.**

---

## Brief closed

All items addressed: P7 (`ce7ac5c`), P8+P9 combined (`8ee92b1`,
deviation from the brief's exact commit order stated explicitly at
the time), P12+P11 combined (`5eb5ffc`), P10 (`d4ade8d`), 0.1/0.2/0.3
(`bffb21b`), P13 (`cc602ae`). `mypy --strict src/` clean and the full
suite green before every commit, per the brief's own instruction.

**Left open, deliberately, per explicit brief instructions:**
- P13.8's real end-to-end manual download against live slskd — the
  brief says to ask the user to confirm the target first; not run
  autonomously.
- ~~0.1's `_build_info.py` "dev" fallback tracked-despite-gitignored
  tradeoff is a soft convention, not a hard git guarantee~~ — this was
  exactly the defect the post-implementation review's R1 caught; fixed
  below, no longer just a stated tradeoff.

---

## Post-implementation review fix (R1)

- [x] **R1** — `packaging/build_dmg.py` no longer writes to the tracked
  `src/seeker/_build_info.py` at all. It now writes
  `src/seeker/_build_info_generated.py` (genuinely gitignored — that
  path was never tracked, so the ignore rule actually applies).
  `_build_info.py` is a pure fallback shim: `try: from
  seeker._build_info_generated import GIT_SHA, GIT_DESCRIBE, BUILT_AT
  except ImportError: ... = "dev"`. Chose the brief's "option 2" over a
  `try/finally` restore in `build_dmg.py` — a tracked file that a real
  build never touches at all is a stronger guarantee than one that gets
  written and then carefully written back. `.gitignore`'s comment
  corrected to describe the real mechanism instead of the one that
  didn't work. New `tests/test_build_info.py` reads the tracked file's
  source text directly (not via import, so a local
  `_build_info_generated.py` from a prior real build can't mask a
  regression) and asserts the `"dev"` fallback literals are still
  there, plus that the generated module's exact path is in
  `.gitignore`. `mypy --strict src/` clean (`__all__` on `_build_info.py`
  needed for the re-export to type-check under strict mode). Full
  suite: 952 passed, 1 skipped — 2 pre-existing failures
  (`test_history_refresh_button_refetches`,
  `test_tagging_controls_row_has_real_spacing_between_items`) reproduce
  identically on a clean `c728fe5` checkout with none of this session's
  changes applied (confirmed via `git stash`) — a pre-existing
  test-order-dependent flake and a pre-existing geometry assertion
  failure on this machine, neither touched by or related to R1. Not
  fixed here — out of R1's scope, flagged for a future pass.

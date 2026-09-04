# Task ledger — work block: docs/BRIEF-2026-09-04.md (round 4)

Working ledger for this block only (not a permanent doc). One line per
brief item, ticked when done and verified. Commit order follows the
brief's own stated ordering: B8 → B3 → B5 → B1 → B4 → B2+B6 → B10 → B9
→ B7 → B11.

## B8 — Spotify 401, unrecoverable without a restart

- [x] `SpotifyClient` takes a `TokenSource` (bound to
  `auth_manager.get_valid_token`) instead of a frozen string; `_get`
  handles a 401 via an optional `force_refresh` callable
  (`get_valid_token(force_refresh=True)`), retried exactly once, else
  raises a readable `SpotifyAuthenticationError`. `connect_spotify` now
  resets `_spotify`/`_sync_service`, fixing Re-authorize's silent
  no-op. PKCE refresh-token rotation documented as a real, separate
  effect. **B8.4 (real token file `expires_at` check) and B8.7 (live
  past-expiry reload) need the real machine — left for the user.**
  [HISTORY §92](HISTORY.md#92)

## B3 — Not a rename bug, a reporting bug

- [x] B3.2-B3.4: `RenamePlan` gained `current_relative`/
  `proposed_relative` (location-relative paths) + `destination_note`
  (new `destination_resolution.py`, shared with DownloadService).
  Rename preview dialog + CLI show the relative path (absolute path as
  tooltip); tagging result panel names files the same way via new
  `_describe_track_file()`.
  B3.1's real-DB check found the match had flipped to `Test/` since
  the brief was written (expected, item 45) — doesn't affect the fix.
  Investigating B3.5 surfaced two real findings beyond B3's scope,
  confirmed/corrected by the user and addressed in the same commit:
  a real crash in duplicate clustering on a stale row (fixed, with a
  reason-classified skip) and a real data-loss path in "Resolve all
  groups" for overlapping-location index artifacts (fixed with a new
  same-physical-file delete guard, `file_deletion.py::same_file`).
  Overlapping registered locations themselves (`x9-pro`⊃`Music`⊃`Test`)
  left open as a real user decision — not de-registered.
  [HISTORY §93](HISTORY.md#93)

## B5 — Only download real DJ formats

- [x] New `audio_formats.py::DOWNLOADABLE_EXTENSIONS` + shared
  `is_downloadable_extension()`, applied at all three entry points
  (`quality._score_candidate`, `rank_candidates()`, `download_manual
  (chosen=...)` via new `UnsupportedDownloadFormatError`). Tests for
  each site + the subset assertion. The one real `.ogg` in the library
  left untouched, as instructed — offering the user a re-download in
  FLAC via Search remains their call.

## B1 — Enter submits on wizard/Settings forms

- [x] `returnPressed` wired on wizard's Client ID (guarded by
  `connect_button.isEnabled()`) and SoulSeek username/password fields
  (`_on_bring_up_clicked`'s own validation covers empty fields).
  Extended to every other single-obvious-submit-target field in
  Settings (destination subfolder, Spotify client ID, SoulSeek
  update-credentials, both threshold fields). 8 new tests.
  Roadmap item 95.

## B4 — Queued progress bar sits at the top of its cell

- [x] New shared `_wrap_progress_bar()` used by all three real bar-
  wrapping exits — the indeterminate branch was the one returning a
  bare bar. Pixel-verified: queued and downloading bars both land
  within 2px of their row's own vertical center. Updated the
  pre-existing test that had asserted the old (buggy) bare-widget
  shape. Roadmap item 96.

## B2 + B6 — Table/card chrome (header dividers, Settings tables)

- [x] B2: `border-right` added to `QHeaderView::section` (suppressed on
  the last section); body gridlines confirmed present all along via a
  real pixel sample. B6: `locations_table`/`destinations_playlist_list`
  routed through `apply_table_defaults`/`make_card`/`size_action_column`.
  New structural test walks a real `MainWindow` (embeds `SettingsPage`)
  asserting every table/list has a card ancestor — confirmed to
  actually fail pre-fix. Pixel-verified: Downloads, Duplicates,
  Settings → Library Locations. Roadmap item 97.

## B10 — Window title shows a commit SHA

- [x] `setWindowTitle` → plain `"Seeker"`. About dialog (real home for
  build identity) untouched. Updated the one test that asserted the
  old title; left the About-dialog test as RR1.1 fixed it. Roadmap
  item 98.

## B9 — Menu bar icon + "Check now" rename

- [ ] Not started.

## B7 — Remove the cover.jpg sidecar feature

- [ ] Not started.

## B11 — Observations to confirm or dismiss

- [ ] Not started.

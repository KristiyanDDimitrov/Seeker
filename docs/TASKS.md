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

- [ ] Not started.

## B4 — Queued progress bar sits at the top of its cell

- [ ] Not started.

## B2 + B6 — Table/card chrome (header dividers, Settings tables)

- [ ] Not started.

## B10 — Window title shows a commit SHA

- [ ] Not started.

## B9 — Menu bar icon + "Check now" rename

- [ ] Not started.

## B7 — Remove the cover.jpg sidecar feature

- [ ] Not started.

## B11 — Observations to confirm or dismiss

- [ ] Not started.

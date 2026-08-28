# seeker

Personal DJ music library management assistant. Syncs Spotify playlists to a
local SQLite cache (to minimize API calls against Spotify's rate/quota
limits), and will eventually match cached tracks against a SoulSeek search
to identify and download the highest-quality available file for each track.

This is a portfolio project. Code quality, structure, and test coverage
matter as much as functionality — prefer the idiomatic/correct approach over
the fastest one.

## Architecture

Strict layering, always respected:

```
Presentation layer (cli.py, ui/*)
  -> Application / services (application.py, spotify/sync_service.py, dashboard_service.py)
    -> Repositories (database/repositories/*)
      -> Database (database/connection.py, database/schema.py)
```

Rule: presentation-layer code (CLI *or* UI) must never import or call a
repository directly. Every CLI handler and every Qt widget goes through
`Application` (or a service it exposes), the same way `handle_sync` goes
through `application.sync_service` and `MainWindow` goes through
`application.dashboard_service`. If a screen or command needs data,
add/extend a method on the service layer rather than reaching past it —
this is what `dashboard_service.py` exists for (see roadmap item 22):
the dashboard's playlist-scoped track status was a real gap in the
service layer, not something to assemble ad hoc from Qt code by calling
multiple repositories directly.

## Current layout

```
src/seeker/
├── database/
│   ├── connection.py
│   ├── schema.py
│   └── repositories/{playlist,track,track_match,local_file,
│                      library_location,download_request}_repository.py
├── spotify/
│   ├── auth.py, auth_manager.py, token.py, token_store.py
│   ├── callback_server.py
│   ├── client.py          # raw Spotify Web API calls
│   ├── sync.py, sync_service.py
├── soulseek/
│   ├── client.py           # slskd REST wrapper — search, request_download,
│   │                       #   get_download_status
│   ├── quality.py          # candidate filtering + best-file selection
│   └── download_service.py # playlist destinations, download_playlist,
│                            #   poll_downloads (status + file move)
├── library/
│   ├── scanner.py, matcher.py, service.py
│   └── metadata_service.py   # tag_tracks/tag_playlist — writes Spotify
│                              #   metadata + art onto matched local files
├── models/{playlist,track,track_match,local_file,library_location,
│           soulseek_file,download_request}.py
├── matching.py               # shared fuzzy artist/title matching —
│                              #   artist_matches, score_title,
│                              #   resolve_text_source — used by BOTH
│                              #   library/matcher.py and
│                              #   soulseek/quality.py; neither has its
│                              #   own copy
├── metadata.py                # write_text_tags, embed_album_art,
│                              #   write_analysis_tags (TBPM/TKEY) —
│                              #   format dispatch (ID3/FLAC/MP4) used by
│                              #   library/metadata_service.py
├── audio_analysis.py          # analyze_audio (librosa BPM + Krumhansl-
│                              #   Schmuckler key estimate), CAMELOT_MAP
├── audio_formats.py         # AUDIO_EXTENSIONS, shared by scanner + quality
├── config.py
├── application.py
├── cli.py
└── main.py
```

## Conventions

- Python 3.13, `uv` for env/build (not pip/poetry).
- Type hints on everything; run mypy before considering work done.
- Models are dataclasses (see `models/track.py`, `models/playlist.py`) —
  keep it that way, no getter/setter classes.
- The SoulSeek integration runs against `slskd` (self-hosted daemon, REST
  API) rather than a raw protocol library. `SoulseekClient` should be
  synchronous `httpx`, matching `SpotifyClient` exactly — same pattern,
  same testing approach (mock the HTTP layer). This supersedes an earlier
  note in this file recommending async for SoulSeek work; that assumption
  no longer applies now that it's a REST wrapper, not raw protocol
  handling.
- DB access is raw SQL via the repository pattern (see `schema.py` /
  `*_repository.py`), not an ORM. Keep new tables/queries consistent with
  that style unless we explicitly decide to add SQLAlchemy.
- Tests: pytest, mock all external HTTP (Spotify, SoulSeek) — never hit
  real APIs in tests.

## Commands

```
uv sync              # install deps
uv run seeker         # run the CLI
uv run pytest         # run tests (add pytest to dev deps if not present)
```

## Known issues / backlog

- [x] Fixed: `cli.py::handle_playlists` instantiating `PlaylistRepository`
      directly instead of going through `Application` — now goes through
      `application.sync_service`/`application.download_service`
      exclusively, matching every other CLI handler. (Fixed by the point
      the polish pass below audited it — likely folded into an earlier
      phase's cleanup rather than its own dedicated change.)
- [x] Fixed (polish pass, item 15 below): `SpotifyClient._get`'s 429-retry
      loop had no max-attempt ceiling — a server that kept returning a
      short `Retry-After` indefinitely would have retried forever. Now
      bounded by `MAX_RETRY_ATTEMPTS = 5`.
- [x] Fixed: `check` command was a stub — now reports the full
      auto-matched/needs-review/unmatched breakdown (see roadmap item 7).
- [x] Fixed: `library/matcher.py` and `soulseek/quality.py` each had
      their own copy of the artist/title fuzzy-matching logic
      (`artist_matches`, title scoring, `normalize_filename_text`), and
      the two copies drifted apart twice — same root cause as the
      `AUDIO_EXTENSIONS` duplication (roadmap item 2's scanner/quality
      split), just not caught as early. First drift: `quality.py` was
      fixed to score artist+title combined instead of title-only
      (roadmap item 5, the 62.5-on-a-clean-match discovery); `matcher.py`
      never got that fix, so a real download (`3AMDISCO - Get Back.wav`,
      untagged WAV, `240KM/H` playlist) stayed unmatched even once
      indexed. Second drift, found investigating that: `matcher.py`'s
      `artist_matches(track.artist, candidate.tag_artist)` hard-gated on
      `tag_artist` with no filename fallback — `tag_artist is None`
      (routine for WAVs; mutagen extracted no tags at all here) rejected
      the candidate outright before title scoring ever ran, whereas
      `quality.py` never had this problem because `SoulseekFile` has no
      tag concept at all — it always passed the normalized filename
      itself as the "local artist" for containment-checking. Fixed by
      consolidating both into `seeker/matching.py`
      (`artist_matches`, `score_title`, `resolve_text_source`,
      `normalize_filename_text`, `AUTO_MATCH_THRESHOLD`,
      `NEEDS_REVIEW_THRESHOLD`) — `resolve_text_source(tag_value,
      filename)` gives both call sites (artist and title) the same
      tag-or-filename-stem fallback, so `matcher.py` now falls back to
      filename-containment for a null `tag_artist` exactly like
      `quality.py` already did. Applying `quality.py`'s combined-scoring
      fix naively to `matcher.py` caused a *new* regression, caught by
      the existing `test_close_match_scores_at_least_90_and_lands_in_auto`
      test: a clean, correctly-tagged match (`tag_title` with no artist
      in it, e.g. "Blinding Lights") scored *worse* combined (73.2) than
      title-only (100), because the combined fix was specifically
      compensating for artist-prefixed filenames, not clean tags. Fixed
      `score_title` to compute both title-only and combined scores and
      take the max — robust to either shape without needing to know
      which one `local_title_source` actually is. Verified against real
      data: `seeker library match` now auto-matches `3amdisco - Get Back`
      at score 94.44 against the real untagged WAV (`local_file_id`
      3218), and `seeker check` reflects it as matched instead of
      unmatched. See `tests/test_matcher.py::
      test_untagged_file_matches_via_filename_alone`.
- [x] Fixed: `download_requests` table now tracks in-flight/completed
      SoulSeek downloads (see roadmap item 6).
- [x] Fixed: `SpotifyClient.get_current_user_playlists` was reading
      `playlist["tracks"]["total"]`. **Correction (found during the first
      real `seeker sync` run, 2026-08-27):** live `/me/playlists` responses
      never contain a `tracks` key — the per-playlist total is under
      `playlist["items"]["total"]` instead (confirmed against all 214 real
      playlists, 0 had `tracks`). This code path had never actually run
      against the live API before (blocked on quota), so the earlier
      "fix" to `tracks` was never live-verified and was wrong. Fixed for
      real this time; `tests/test_spotify_client.py` updated to match.
- [x] Fixed: `SpotifyClient.get_playlist_tracks` was reading
      `item.get("item")` instead of `item.get("track")`. **Endpoint path
      history (not random flip-flopping — tracks a real API change):**
      originally `/playlists/{id}/items`, changed to
      `/playlists/{id}/tracks` based on pre-migration docs, then a live
      403 plus current Spotify developer community reports confirmed
      Spotify's Feb 2026 API migration deprecated
      `/playlists/{id}/tracks` in favor of `/playlists/{id}/items` — so
      the path is now back to `/playlists/{id}/items` for real.
      **Per-entry field history (same root cause, second symptom):**
      originally read each entry's payload from `entry["track"]`,
      "corrected" to `entry["item"]` when the endpoint path was first
      fixed, but that field-name change was never live-verified — the
      switch to `/items` also silently swapped `seeker sync-tracks` to
      the `/items` endpoint but the parsing logic still read `"track"`,
      so every entry was skipped and playlists synced "0 tracks" for
      real playlists with real tracks (found live against `240KM/H`,
      playlist `1xfPRHLLuGBLlB3bIo5kA5`, 3 real tracks). A raw
      unparsed GET confirmed: the paging envelope's `items` array is
      fine (3 entries, `total: 3`, `next: null`), but no entry has a
      `"track"` key at all — the per-track payload now lives under
      `entry["item"]`, and the old `"track"` key is repurposed as a
      *boolean* type-discriminator field living inside that `item` dict
      (`item["track"] == True` for tracks, presumably `False` for
      podcast episodes) alongside `item["type"] == "track"`. So: field
      name `track` (original, correct pre-migration) → `item` (the fix
      that shipped with the endpoint-path change, but never actually
      live-verified) → `item` (now confirmed correct via a raw live
      GET, with an explicit `track_data.get("type") != "track"` filter
      added as a defensive skip for non-track entries, using the real
      discriminator field rather than relying only on empty `artists`
      as an incidental signal). `tests/test_spotify_client.py` updated
      to match the real live entry shape and to cover the non-track
      skip.

## Roadmap (direction, not urgent)

1. ~~Confirm end-to-end `sync` works~~ — done, verified for real
   (2026-08-27) once quota reset. Along the way: `seeker sync` was split
   into a metadata-only `sync` and an explicit, single-playlist
   `sync-tracks <playlist_name>` — track syncing (the expensive,
   per-playlist Spotify call) is no longer triggered automatically for
   every playlist `sync` finds; it's now always a deliberate, scoped
   action. `SpotifySyncService.sync_playlists()` now persists each
   playlist's metadata itself (id/name/track_count/snapshot_id) rather
   than relying on `sync_playlist_tracks()` to do it — previously that
   only happened as a side effect of the (now-removed) automatic
   per-playlist track-sync loop, so a metadata-only sync would have left
   new/changed playlists unpersisted. `seeker sync` prints the local
   playlist list (name + track_count) straight after syncing, so the
   result is visible without a separate command.
   `SpotifySyncService.get_playlist_by_name()` does the case-insensitive
   lookup for `sync-tracks`, raising `PlaylistNotFoundError` with
   close-name suggestions (`difflib.get_close_matches`) when nothing
   matches. Real run against the live API: 214 playlists synced (all
   "Updated" — first real sync of this DB), 0 rows in `tracks` (confirms
   metadata-only really means metadata-only). See the
   `get_current_user_playlists` correction below — this run is what
   surfaced it.
2. ~~Local library scanning~~ — done. `library_locations` +
   `local_files`, multi-location aware, per-location reachability
   handling, AppleDouble sidecar files filtered.
3. ~~Matching~~ — done. `matcher.py` classifies each track as
   auto-matched / needs-review / unmatched (`track_matches`, with a
   `score` column). Thresholds (auto ≥90, review 70–90) are untuned
   defaults — revisit once real match data exists.
4. ~~SoulSeek search client~~ — done. `SoulseekClient.search` against
   `slskd`'s real API (`/api/v0/searches`), synchronous httpx.
   **Correction (found during Phase 1 verification):** the initial
   implementation always got zero results against the live network. Root
   cause was NOT Soulseek account privilege (that affects transfer queue
   position, not search visibility — an earlier "unprivileged account"
   explanation in this file was wrong and has been removed). The real
   bug: `GET /api/v0/searches/{id}` only returns populated `responses`
   when called with `?includeResponses=true` — without it, the endpoint
   reports `isComplete: true` / a real `responseCount` while `responses`
   is silently `[]`. Fixed by adding that query param on the
   post-completion fetch. Also bumped the default `search()` timeout
   15s → 45s (poll_interval 1s → 2s) — real searches against the live
   network were observed taking 20-45s+ to complete, so 15s was cutting
   most searches off before peer responses arrived, independent of the
   above bug. The old test fixture mocked responses inline on the plain
   poll call, which is why this passed tests while being broken live —
   `tests/test_soulseek_client.py` now mocks the two calls distinctly.
5. ~~Quality-ranking logic~~ — done. `soulseek/quality.py`:
   `filter_candidates` (extension + `artist_matches` reuse + fuzzy title
   score ≥90, scored against `artist + title` combined — scoring the bare
   title alone against an "Artist - Title"-style Soulseek filename tanks
   the ratio even for a clean match), `quality_tier`/`effective_bitrate`
   (flac/wav > mp3/m4a/aac/ogg, VBR-reported bitrates distrusted), and
   `select_best` (practical-queue candidates preferred, degrades to
   best-available if none are practical). `select_downloads` (Phase 2)
   returns both halves — see item 8.
6. **Phase 1 download orchestration — done**: `download_requests` table
   (`role`/`status` lifecycle, `queued → downloading → completed/failed`)
   plus a `transfer_id` column beyond what was originally sketched —
   slskd's only documented per-transfer status endpoint is
   `GET /transfers/downloads/{username}/{id}`, and that `id` is slskd's
   own UUID from the enqueue response, not derivable from
   username+filename alone. Destination is per-playlist
   (`playlists.download_location_id` + `download_subfolder`, set via
   `seeker playlists set-destination`). slskd's batch-enqueue
   `options.destination` is relative to *slskd's own* configured download
   root (confirmed via `slskd-data/downloads` in this repo's
   docker-compose setup), not an arbitrary filesystem path — so it can't
   target a library location directly. Seeker therefore moves the
   completed file itself: `seeker downloads status` polls
   `get_download_status`, and on a `Succeeded` state, locates the file by
   basename under `SLSKD_DOWNLOAD_DIR` (new `.env`/`config.py` var, host
   path to slskd's download dir) and moves it into the resolved
   destination. **Verified end-to-end against a real transfer** (2026-08-26):
   real search (527 files for "Dom Dolla Rhyme Dust" after the client fix
   above) → `select_best` picked a practical 320kbps candidate → real
   `request_download` against live slskd → observed real state
   transitions `queued → downloading → "Completed, Succeeded"` via
   `seeker downloads status` → file moved to
   `/Volumes/X9 Pro/Music/DnB/17 - Dom Dolla - Rhyme Dust.mp3` (byte-exact
   size match with the search result) → `download_requests.status`
   ended at `completed` with a real `completed_at` → `seeker library
   scan` picked the file up into `local_files` with correct
   artist/title/duration tags. The playlist/track rows for this run were
   manually seeded (not from a real Spotify sync) because Spotify dev
   quota is still exceeded (see item 1) — everything from
   `set-destination` onward ran through the real, unmodified CLI/service/
   client code against the real slskd instance and real filesystem. Also
   added `tests/test_download_service.py` covering the state-classification
   logic directly: several `Completed, X` combinations (`Succeeded`,
   `Errored`, `Cancelled`, `TimedOut`, `Rejected`) are asserted to route
   to the correct status, including that bare `"Completed"` (no
   recognized outcome flag) must NOT be treated as done — only an
   explicit `Succeeded` triggers the move + `completed` status.
   Deliberately not yet built (Phase 1): upgrade-tracking, background
   quality-chasing, replacement confirmation — that's item 8.
7. `check` command already reports auto/needs-review/unmatched — a
   `review` command to confirm/reject needs-review matches is still
   outstanding. Note: `download_playlist` currently targets tracks with
   no track_match at all (`match_method IS NULL`) — needs-review tracks
   are left for that future `review` command, not auto-downloaded.
8. **Phase 2 upgrade-tracking — done**: `quality.select_downloads(track,
   files)` ranks all filtered candidates and returns `(settled, upgrade)`
   — if the top pick is practical there's no upgrade (`upgrade=None`,
   matches Phase 1 exactly); if it's impractical, `settled` becomes the
   best *practical* candidate and `upgrade` becomes that impractical top
   pick, requested in parallel (`download_playlist` now requests both,
   `role='settled'` / `role='upgrade'`, same call with no destination
   either way — both land in slskd's own download dir). `download_requests
   .status` gains `ready_for_review`: `poll_downloads()` marks a completed
   `role='settled'` transfer exactly as before (move + `completed`); a
   completed `role='upgrade'` transfer is *not* moved — it's marked
   `ready_for_review` and left in slskd's dir.

   **Two separate commands, split deliberately** — `seeker downloads
   status` calls only `poll_downloads()`, which talks to slskd and
   updates status but contains no `input()` anywhere; it's safe to run
   from cron/a scheduled task with no attached terminal.
   `seeker downloads review` calls only `review_pending_upgrades()`,
   which never talks to slskd at all — it just reads every
   `ready_for_review` row straight from the DB and, for each, prompts:
   "Higher quality version of ... ready (X vs current Y). Replace?
   [y/n]". Yes moves the file (reusing `_move_completed_file`, which
   returns `(location, relative_path)` rather than a bare bool so both
   the settled auto-path and this confirmation path share one code
   path), calls `scanner.index_single_file()` to register it in
   `local_files` immediately (unlike settled downloads, which rely on
   the next `library scan`), repoints `track_matches` at the new file,
   and asks a *separate* y/n on deleting the old file (no → left on
   disk, self-heals as an unmatched file on the next scan since nothing
   still points at it). No on the replace prompt is a no-op — stays
   `ready_for_review`, offered again next `downloads review`. Prints
   "Nothing to review." rather than silently doing nothing when the
   queue is empty. Originally these two were one combined method
   (`poll_downloads` polled *and* prompted in the same call, per the
   original Phase 2 spec: "after polling, for every ready_for_review
   request — this run's and any left over — prompt"); split into two
   commands once real verification showed the practical problem with
   that: the first `downloads status` run after a real completion would
   itself immediately block on `input()`, so it was never actually safe
   to automate. `library/scanner.py`'s inline "read tags → build
   LocalFile → upsert" logic was extracted into `index_single_file
   (location, relative_path, local_file_repository, connection)`
   specifically so the review flow and the scan loop can't drift apart
   — `tests/test_library_scanner.py::
   test_index_single_file_matches_scan_loop_result` asserts a direct
   call and a `scanner.scan()` pass produce the identical row.
   `poll_downloads()` tests assert status transitions and the
   settled/upgrade branching with zero `input()` mocking (one test
   monkeypatches `input()` to raise if called at all, as a guardrail);
   `review_pending_upgrades()` tests mock `input()` via
   `monkeypatch.setattr("builtins.input", ...)` and seed
   `ready_for_review` rows directly — no poll step needed, since the two
   are fully decoupled now. See `tests/test_download_service.py`.

   **Verified end-to-end against real transfers** (2026-08-26, before the
   split, using the then-combined method): two real fast/available files
   requested via real `request_download` calls, watched through genuine
   `queued → downloading → Completed, Succeeded` on live slskd. Confirmed
   for real: a completed upgrade rests at `ready_for_review` without
   moving anything or touching `track_matches`; a real yes/yes replaced
   the file (byte-exact size match), `index_single_file` read real tags
   off the new file, `track_matches` repointed to the new `local_file_id`,
   the old file was actually deleted, `download_requests` ended at
   `completed` with a real `completed_at`; a real "no" left everything
   untouched and the request came back up for review on a third run,
   not lost or auto-declined. (The confirm-vs-poll split above is a
   direct consequence of that verification session.)

   Not yet built (Phase 3, if ever): background re-polling that upgrades
   a `settled` file automatically without an explicit re-run of `seeker
   download`; the queue-depth threshold used to decide "practical" is
   still the untuned `DEFAULT_MAX_QUEUE = 200` guess from Phase 1.
9. **Metadata normalization, Phase A — multi-artist fix, done; tag-writing
   not yet built.** Motivation: an upcoming feature will write Spotify
   metadata (and eventually album art) onto downloaded files' tags, so
   the capture had to be correct first — `get_playlist_tracks` was only
   ever reading `artists[0]["name"]`, silently dropping every
   collaborating artist (e.g. a track credited "MK, Dom Dolla" on
   Spotify would have been tagged/matched as just "MK"). Fixed to join
   ALL of `item["artists"]` with `", "` — matches the exact convention
   already seen in real local tags, so `Track.artist` stays a plain
   `str` with no model change needed, just a documented multi-value
   convention. This forced two matching.py changes, found in that
   order:
   1. `artist_matches` previously required the *entire* (single) spotify
      artist string to be contained in the local text — now splits
      `spotify_artist` on `", "` and passes if the local text contains
      ANY one of the names, so a local tag/filename crediting only "MK"
      still matches a Spotify track credited "MK, Dom Dolla".
   2. That alone wasn't sufficient — `score_title`'s combined-scoring
      (item 5 in this list) was still combining the FULL multi-artist
      string with the title, which dilutes the ratio when the local
      source only credits one of them (measured: 71.8 combined-with-
      "MK, Dom Dolla" vs. 92.9 combined-with-just-"MK", against the same
      filename — found by the new
      `test_filter_candidates_matches_multi_artist_track_crediting_only_one`
      test, which failed on the first pass). Fixed by having
      `score_title` also try each individual artist name combined with
      the title (not just the full joined string), taking the max
      across title-only / combined-all / combined-per-artist.
   Also updated `soulseek/download_service.py`'s search-query
   construction (new `_build_search_query` helper): a literal comma in
   the query text (e.g. `"MK, Dom Dolla Rhyme Dust"`) isn't a sane
   Soulseek search string — search matching isn't guaranteed to ignore
   stray punctuation — so the comma is stripped for the query
   specifically (`track.artist.replace(",", " ")`), while the
   human-readable `print` logging keeps the comma. Verified against real
   240KM/H data after all of the above: `3amdisco - Get Back` (a
   single-artist track, unaffected by any of this) still auto-matches at
   the same score, 94.4 — no regression.

   **Album art investigated, not yet implemented.** A real
   `GET /playlists/{id}/items` response's nested `item["album"]` already
   includes a populated `images` array — no separate
   `GET /v1/albums/{id}` call needed. Confirmed live for all 3 real
   240KM/H tracks: each had 3 image sizes (640/300/64px),
   `images[0]["url"]` in the form
   `https://i.scdn.co/image/ab67616d0000b273...`, and one URL was
   fetched directly and confirmed a real, loadable `image/jpeg` (94KB).
   Tag-writing (art + the rest of the metadata) is Phase B — not started.
10. **Metadata normalization, Phase B — writing tags — done.**
    **WAV finding (investigated live before building anything, since the
    original ask assumed WAV might not support art at all): WAV fully
    supports both text tags and embedded album art.** mutagen's WAV tag
    class (`_WaveID3`) is a genuine subclass of `mutagen.id3.ID3` — the
    exact same mechanism MP3 uses. Verified directly on a copy of the
    real `3AMDISCO - Get Back.wav` (never the original): wrote
    TIT2/TPE1/TALB, reopened fresh, read back correctly; embedded a real
    JPEG (downloaded live from Spotify's CDN) as an APIC frame, reopened
    fresh, `data == original_bytes` (byte-exact); confirmed with both
    mutagen's own reader and the stdlib `wave` module that the RIFF
    structure and audio (301.5s, matching `local_files.duration_ms`)
    survived untouched. So WAV was **not** excluded from art embedding —
    it uses the same code path as MP3. Also verified live on real files:
    FLAC's top-level dict assignment (`flac['title'] = [...]`) and native
    `Picture`/`add_picture`, and MP4's atom keys (`\xa9nam`/`\xa9ART`/
    `\xa9alb`, `covr` with `MP4Cover`).

    `seeker/metadata.py`: `write_text_tags(mutagen_file, artist, title,
    album)` and `embed_album_art(mutagen_file, image_bytes, mime_type)`
    both dispatch on the mutagen object's actual tag type
    (`isinstance(mutagen_file.tags, ID3)` — covering MP3 *and* WAV in one
    branch — vs. `isinstance(mutagen_file, FLAC)` vs. `isinstance(
    mutagen_file, MP4)`), not on file extension. An unrecognized format
    makes `write_text_tags` raise `ValueError` (caller treats the whole
    track as `skipped_format_unsupported`) but makes `embed_album_art`
    return `False` and print a skip reason instead of raising — a
    missing/unsupported art mechanism must not sink an otherwise-good
    text-tag write for one field. In practice mp3/flac/wav/m4a — every
    format actually present in this library — are all fully supported;
    only a hypothetical ogg/aac would hit the unsupported branch, and
    none exist in the scanned data to test against for real (covered by
    a synthetic fake-tags-object test instead).

    Album art needed a place to live in the DB before any of this could
    work offline: `tracks.album_art_url` (new column; existing DBs
    migrated via a guarded `ALTER TABLE` in `Database.initialize()` —
    there's no migration framework yet, so this stays a one-off,
    idempotent, PRAGMA-guarded statement rather than one). Captured in
    `get_playlist_tracks` from `item["album"]["images"]`, picking the
    largest by `width` rather than trusting array order. `MetadataService
    .tag_tracks(track_ids)` (`library/metadata_service.py`) does the DB
    lookups (track_matches → local_file → library_location →
    filesystem path), calls `write_text_tags` + `embed_album_art`, and
    returns `{tagged, skipped_no_match, skipped_format_unsupported,
    failed, details}` — `details` is a list of `{track_id, reason,
    message}` beyond what was originally sketched as a plain counts
    dict, because the CLI needs to report *which* tracks were skipped
    and why (layering rule: it can't just query the DB itself for that).
    Album art download failure is caught separately, inside the
    per-track handler, and only prints a warning — it does not fail the
    track (the text tags still get written and it still counts as
    `tagged`); every other exception is caught by the outer per-track
    try/except in `tag_tracks` and counted as `failed`, so one bad file
    can't abort the batch. `tag_playlist(playlist_name)` scopes to
    `match_method = 'auto'` only, deliberately excluding
    `needs_review` — same caution as the existing
    `download_playlist`/`review` split (item 7): writing Spotify's
    canonical metadata onto a possibly-wrong file would be actively
    harmful, and a human hasn't confirmed a needs_review match yet.
    Deliberately does *not* re-index the file into `local_files`
    afterward (mirrors the settled-download design in item 6/8) — a
    `library scan` picks up the updated tags on its own next run.

    `seeker library tag <playlist_name>` is the CLI entry point.

    **Tests use real files from the scanned x9-pro library** (copied to
    `tmp_path` first — originals are never opened for writing; the drive
    being unmounted skips those tests rather than failing them, same
    treatment as an unreachable library location elsewhere in this
    codebase) for the mp3/flac/mp4 art+tag round-trip checks in
    `tests/test_metadata.py`, and for the `3amdisco - Get Back.wav`
    integration check in `tests/test_metadata_service.py`
    (`test_tag_tracks_real_wav_round_trips`) — tags a copy, reads them
    back, and re-asserts the real original on the drive still has no
    tags at all, confirming nothing touched it. The service-level skip
    counting and the mocked-art-download happy path use a synthetic
    silent WAV (`wave` stdlib module) instead, so most of the suite
    doesn't depend on the drive being mounted.

    **Run for real** (2026-08-27, on explicit request in a follow-up
    turn — writing real metadata onto a real file is a much less
    reversible action than the read-only investigation and DB-only
    re-syncs used to build this, so it was deliberately held back until
    asked for directly): `seeker library tag '240KM/H'` against the
    actual x9-pro drive tagged the real `3AMDISCO - Get Back.wav`.
    Read back directly off the real file afterward (not just "the
    command exited cleanly"): `TIT2`/`TPE1`/`TALB` = "Get Back"/
    "3amdisco"/"Get Back EP", and a real embedded `APIC:Cover` — 97,276
    bytes, `image/jpeg`, first bytes `ffd8ffe0...` (a real JPEG SOI/APP0
    signature, not a stub). Audio integrity reconfirmed after the write
    via both mutagen and the stdlib `wave` module: still a valid 2ch/
    44.1kHz WAV, duration unchanged at 301.5s.
11. **Metadata normalization, Phase C — local audio analysis (BPM +
    estimated key) — done.**

    **`librosa` chosen over Essentia deliberately: Windows wheel
    support.** Essentia has no official Windows PyPI wheels (source
    build only), which would break the app for any Windows-using DJ;
    `librosa` installs cleanly everywhere via pip/uv. Confirmed live
    before committing to it, not assumed: `uv add librosa` on this
    Python 3.13.15 environment resolved and installed cleanly
    (`librosa==1.0.0`, `numba==0.67.0`, `numpy==2.5.2`) and imported
    without error — numba (librosa's JIT-compiled inner loops) has
    historically lagged new Python releases, but that's no longer true
    here.

    **Real, current API confirmed live before writing any code against
    it** (librosa's public API has shifted across versions — the
    project has already been burned twice by trusting an assumed API
    shape instead of a checked one, for the Spotify endpoint and field
    rename in Phase A/roadmap item 1): `librosa.beat.beat_track(y=y,
    sr=sr)` returns `(tempo, beats)`, and in this version `tempo` comes
    back as a length-1 `ndarray`, not a bare float — extracting the BPM
    needs `float(np.atleast_1d(tempo)[0])`, not `float(tempo)` (the
    latter raises `TypeError` in current numpy). `librosa.feature
    .chroma_cqt(y=y, sr=sr)` returns a `(12, t)` chromagram, averaged
    over time (`.mean(axis=1)`) into a single 12-bin pitch-class
    profile for key correlation; bin 0 is C, per librosa's documented,
    version-stable chroma convention (unlike the tempo return shape,
    this one wasn't re-checked live since it's long-established and not
    something that's been observed to drift). Real tempo extraction
    against a copy of the real `3amdisco - Get Back.wav`: **161.499
    BPM**, confirmed bit-identical across repeated runs on the same
    file (determinism check, not just "didn't crash"). Real key
    estimate on the same file: **3A** (A# minor) at correlation/
    confidence **0.477** — reported as-is, not adjusted toward a more
    "plausible" DJ-genre tempo/key; a beat tracker's octave/mode errors
    are a known real limitation of onset-based estimation, not
    something to paper over.

    **Key detection is a confidence-scored estimate, not a ground
    truth.** `analyze_audio()` correlates the mean chroma vector against
    all 24 standard Krumhansl-Schmuckler major/minor profiles (a
    well-established empirical model of tonal perception, not derived
    from this project's own analysis) and returns the best-correlating
    key's normalized Pearson correlation as `key_confidence` — this is
    a similarity score against a generic psychoacoustic model, not a
    measured certainty, and can be — and on real dance music often is —
    wrong, especially for tracks with ambiguous or shifting tonality.
    `camelot_key` is deliberately `None` (not an arbitrary guess) when
    the best candidate's correlation isn't even positive, e.g. for
    near-silent or noise-dominated audio. `AudioAnalysis` and any UI
    built on this data should treat `key_confidence` as a hint for how
    much to trust `camelot_key`, never as a guarantee.

    `seeker/audio_analysis.py`: `analyze_audio(file_path) ->
    AudioAnalysis(bpm, camelot_key, key_confidence)`, plus the fixed
    `CAMELOT_MAP` (standard DJ wheel convention — 12 major + 12 minor
    keys in sharp notation, each pair sharing a number because they're
    relative major/minor — this part needed no live investigation, only
    getting a well-documented convention right, which
    `tests/test_audio_analysis.py::
    test_camelot_map_pairs_relative_major_minor_correctly` spot-checks
    against known pairs rather than trusting a renumbering that could
    still pass a naive "24 unique codes" check).

    `local_files` gained `bpm REAL`, `camelot_key TEXT`,
    `key_confidence REAL` — same guarded/idempotent `ALTER TABLE`
    pattern as Phase B's `tracks.album_art_url` migration
    (`connection.py::_migrate`, now generalized into a small
    `_add_column_if_missing(connection, table, column, sql_type)`
    helper reused for both). Deliberately NOT included in
    `LocalFileRepository.upsert()`'s `ON CONFLICT ... DO UPDATE SET` —
    a routine `library scan` re-run must not wipe out previously-computed
    analysis, so a new `update_analysis(local_file_id, bpm, camelot_key,
    key_confidence, connection)` method writes just those three columns
    instead.

    `metadata.py` gained `write_analysis_tags(mutagen_file, bpm,
    camelot_key)` — the real `TBPM` (ID3 text frame, integer BPM as a
    string) and `TKEY` (ID3 text frame) for mp3/wav, `"BPM"`/`"KEY"`
    Vorbis comments for FLAC, and the `tmpo` atom (native integer, not a
    freeform atom) plus a `----:com.apple.iTunes:initialkey` freeform
    atom for MP4/M4A — all confirmed round-tripping live on real copied
    files before being locked in. `TKEY` conventionally holds standard
    key notation per the ID3v2 spec, but stores the Camelot value here
    instead — a deliberate choice matching what real-world DJ tagging
    tools commonly do in practice, since Camelot is the practically
    useful DJ-facing convention. Same unsupported-format contract as
    `write_text_tags` (raises `ValueError`, not a silent skip) — unlike
    album art, analysis tags are core data once `analyze_audio=True` is
    requested, not an optional extra.

    `MetadataService.tag_tracks(track_ids, analyze_audio=False)` /
    `tag_playlist(playlist_name, analyze_audio=False)`: a **genuinely
    independent toggle**, per the ask (the UI will eventually offer this
    as a separate checkbox from the base metadata/art write). When
    `False` (the default), `analyze_audio()` is never even called —
    `tests/test_metadata_service.py::
    test_tag_tracks_analyze_audio_false_is_completely_inert` monkeypatches
    the analysis call to raise if invoked at all, as a guardrail, the
    same technique already used elsewhere in this suite for the
    poll/review split. When `True`, analysis runs per-track *after* the
    base text/art tagging succeeds, on the same open `mutagen_file`
    object, and is wrapped in its own try/except: an analysis failure
    (or a format `write_analysis_tags` doesn't recognize) only prints a
    warning and skips the three DB columns + TBPM/TKEY for that track —
    it does not undo the text-tag write or count the track as `failed`,
    matching the same best-effort treatment already established for
    album art.

    `seeker library tag <playlist_name> --analyze-audio` is the CLI
    entry point. **Not yet run for real** against the x9-pro drive with
    `--analyze-audio` — verified instead via the same real-file-copy
    approach as everything else in this phase
    (`test_tag_tracks_analyze_audio_true_writes_and_persists_real_analysis`
    tags a copy of the real 3amdisco WAV with `analyze_audio=True` and
    asserts real BPM/Camelot values land in both `local_files` and the
    file's TBPM/TKEY frames).

    **Octave-error correction (follow-up).** Beat trackers (this one
    included) routinely lock onto half or double the perceived tempo —
    a systematic problem on genres like DnB, where the actual tempo and
    its double both look plausible to onset-based detection. Confirmed
    on the real 3amdisco file: unbiased detection is 161.5 BPM; the
    genuinely correct tempo for that track is ambiguous between that and
    its half (80.75) without genre/DJ context the analyzer doesn't have.

    Two independent, stacked fixes, both optional via a new
    `expected_bpm_range: tuple[float, float] | None = None` parameter
    threaded through `analyze_audio` → `MetadataService.tag_tracks`/
    `tag_playlist` → `seeker library tag --analyze-audio --bpm-range MIN
    MAX`. `None` (the default) is byte-for-byte the same code path as
    before this feature existed — `prior=None` is `beat_track`'s own
    default, so nothing changes when no range is given; confirmed via a
    dedicated regression test pinned to the exact real BPM/key/confidence
    values recorded when Phase C first shipped, not just "didn't crash."

    1. **Internal biasing** — `librosa.beat.beat_track` (and
       `librosa.feature.tempo`, confirmed via its own docstring example)
       accepts `prior`, a `scipy.stats.rv_continuous` over BPM, which
       actually changes the *search* rather than post-hoc adjusting its
       output. Confirmed live before use, not assumed from the parameter
       name (librosa's API has already burned this project twice — see
       the endpoint/field-name saga in item 1): a
       `scipy.stats.uniform(70, 20)` prior (uniform over 70-90 —
       `scipy.stats.uniform(loc, scale)` means `[loc, loc+scale]`, NOT
       `[loc, scale]`, a real gotcha caught by testing the actual
       behavior) changed the real 3amdisco detection from 161.5 to
       80.75 BPM, exactly the expected half.
    2. **`correct_octave_error(bpm, expected_range) -> (bpm, was_corrected)`**
       — a pure, audio-free function in `audio_analysis.py`: if `bpm` is
       already in range, unchanged; otherwise checks `2x/0.5x/3x/1.5x`
       (the last two for triplet-feel, included since they were trivial
       to add) and corrects only if *exactly one* candidate lands in
       range — zero or multiple candidates in range is genuine
       ambiguity, and forcing a correction there would just be
       substituting one guess for another, so the raw value is returned
       unchanged instead. `analyze_audio` always runs this as a
       belt-and-suspenders check when a range is given, regardless of
       whether the internal `prior` biasing already got there — the
       check is cheap and doesn't depend on the biasing having worked.

    `--bpm-range MIN MAX` requires `--analyze-audio` (`nargs=2` gives
    "both together" for free; the CLI layer adds an explicit check for
    "requires `--analyze-audio`" and prints a clear error rather than
    silently ignoring the range when it's given without that flag).
12. **Centralized playlist-name resolution with an offer-to-refresh
    UX.** Four CLI commands take a `playlist_name` argument
    (`sync-tracks`, `playlists set-destination`, `download`,
    `library tag`) and had each grown its own playlist lookup —
    `sync-tracks` alone had case-insensitive matching with
    close-match suggestions (`SpotifySyncService.get_playlist_by_name`);
    the other three did a plain case-sensitive exact lookup inside
    their respective service methods, relying on the user typing the
    name exactly right. Consolidated into one CLI-layer helper,
    `resolve_playlist_or_offer_sync(name, application)` in `cli.py`,
    used by all four before they call their underlying service method —
    it resolves the canonical `Playlist` (case-corrected name) once, and
    each command then calls its existing service method with that exact
    name, so `download_service`/`metadata_service`'s own internal
    lookups (unchanged) always succeed. Deliberately a free function
    taking `application` rather than a method on any one service — it's
    a cross-service orchestration concern (looks up via `sync_service`,
    but the result feeds into whichever *other* service the command was
    actually calling), which is exactly a CLI-layer responsibility per
    the layering rule, not something that belongs bolted onto
    `SpotifySyncService` or duplicated three more times.

    Behavior: found locally (case-insensitive) → returned immediately,
    zero change from before. Not found, but a close match exists
    (`difflib`-based, extracted from `get_playlist_by_name` into a
    shared `find_close_playlist_matches(name, candidates)` in
    `sync_service.py` so the CLI helper and the original method use the
    exact same tuning rather than two independently-drifting copies —
    same lesson as the `matching.py` and `AUDIO_EXTENSIONS`
    consolidations) → the existing "Did you mean...?" error, **no**
    refresh offered — a close match means the name is probably a typo
    or a stale local rename, and a resync wouldn't fix either of those,
    so offering one would be actively misleading. Not found and no close
    match → "No playlist named '{name}' found locally — it may be new.
    Refresh from Spotify now? [y/n]"; a real `sync_playlists()` call
    (metadata-only, already proven safe to call repeatedly — see item 1)
    followed by exactly one retry of the local lookup. Still not found
    after a real refresh → a distinct, clear error stating the name
    doesn't exist on the account at all, not the generic
    "not found locally" message (the user already knows it's not local;
    what they need to know now is that refreshing didn't help either).
    Declining the offer re-raises the original "not found locally" error
    unchanged.

    Verified live against the real DB: `seeker sync-tracks 'Totally Fake
    Playlist Name XYZ'`, declining the offer, printed the offer prompt
    then the original "Available playlists: ..." listing and exited 1 —
    confirming the real CLI wiring, not just the unit-tested helper in
    isolation.

    **Correction, found live the same day:** `seeker sync-tracks 'Test'`
    was silently taking the "Did you mean: sesh?" suggestion branch
    instead of ever offering a refresh — item 12's own "no refresh when
    a close match exists" rule was working exactly as designed, but the
    close-match *detection* itself was wrong. Confirmed directly rather
    than guessed: `find_close_playlist_matches` was still using
    `difflib.get_close_matches`/`SequenceMatcher`, whose ratio inflates
    for short strings — `SequenceMatcher(None, "Test", "sesh").ratio()`
    is `0.5`, landing exactly on (and clearing) the `cutoff=0.5` used,
    purely from sharing a couple of letters at a workable alignment, not
    genuine resemblance. Checked against the real 214 local playlist
    names at the time: "The Stage" (0.462), "Treehouse" (0.462),
    "Metal"/"Faces"/"The Most Hated" (0.444) all clustered suspiciously
    close to that same cutoff for the same 4-character query — the same
    failure mode, not an isolated fluke.

    Replaced with `rapidfuzz.distance.Levenshtein.distance` (already a
    project dependency via `matching.py`), case-insensitive, scaled to
    query length rather than a fixed ratio cutoff: a candidate counts as
    close only if its absolute edit distance is `<= max(1, len(query) //
    4)` — roughly one tolerated edit per four characters, floored at 1
    so even a 3-character query tolerates a single typo. Untuned initial
    constant, same treatment as the 90/70 matcher thresholds elsewhere
    in this codebase. Re-verified against the same real data both
    directions: "Test" now produces zero close matches (confirmed none
    of "sesh"/"The Stage"/"Treehouse"/"Metal"/"Faces"/"The Most Hated"
    survive), while a genuine one-character typo of a real name
    ("Afterlife Releasea" for "Afterlife Releases") is still correctly
    caught. Re-ran the exact same live CLI check as above with `'Test'`
    instead of a nonsense string: now shows the refresh prompt, not the
    suggestion — closing the loop on the actual reported bug, not just
    the isolated unit behavior.
13. **slskd shares the local library (upload side) + Phase 3: locked-file
    retry — done.** `docker-compose.yml` mounts the real music drive
    read-only (`/Volumes/X9 Pro/Music:/shared/music:ro`, alongside the
    existing `slskd-data` mount unchanged); `slskd.yml` gets
    `shares.directories: [/shared/music]` (container-side path, not the
    host path — the host path only matters to the volume mount).
    Recreating (not restarting — a restart doesn't pick up a new mount)
    took noticeably longer than a plain restart the one time it was
    actually run; not a hang, just slow, confirmed by checking back
    rather than assuming. Verified for real, three separate ways, not
    just "the command exited 0": `docker exec slskd ls /shared/music`
    listed real folders matching the actual drive; `GET
    /api/v0/application` showed `server.state: "Connected, LoggedIn"`
    under `user.username: "seekerapp"`, reconfirmed post-recreate; the
    same response's `shares` block — slskd's own acknowledgment, not
    just config file presence — showed `ready: true, scanning: false,
    directories: 74, files: 3478`.

    **The real locked-file rejection signal, confirmed live before
    building anything on top of it (2026-08-27):** a real search for
    "Dom Dolla Rhyme Dust" surfaced files in a genuinely separate
    top-level `lockedFiles` array per response (not `isLocked: true`
    within `files` — a real entry's own `isLocked` field was itself
    `False`, so array membership is the actual signal, not that field).
    `request_download` against a real locked file **succeeded
    immediately** — no exception, a real transfer_id came back. The
    rejection only showed up moments later via `get_download_status`:
    polled 3 times over 30s, stable from `t=0.0s`: `"Completed,
    Rejected"` every time. The full transfer record's `exception` field
    carried the real reason: `"Transfer rejected: File not shared."`,
    with `startedAt`/`endedAt` the same instant. Conclusion this design
    is built on: it's an **explicit, immediate, machine-readable failure
    state**, not an indefinite hang — so Phase 3 keys off `state`
    containing `"Rejected"` plus `exception` text matching a known
    lock-rejection pattern, not a timeout heuristic.

    **Why Phase 3 reuses Phase 2's upgrade/review infrastructure as-is
    instead of building a parallel locked-download pipeline:** a locked
    file is structurally identical to an "upgrade" candidate — something
    better than what's already settled, not guaranteed, not urgent,
    worth chasing in the background. Building a separate
    locked-tracking table/flow would duplicate the settled/upgrade role
    split, the `ready_for_review` confirm step, and `poll_downloads`'
    daily-cadence design for no real benefit — a locked file that
    unlocks becomes exactly a completed upgrade, which Phase 2 already
    knows how to hand to the user for confirmation.

    STEP 1 — `SoulseekFile.locked: bool`. `_parse_search_response` now
    includes both `files` and `lockedFiles` entries (previously
    `lockedFiles` was dropped entirely, and a per-file `isLocked: true`
    within `files` was assumed but never confirmed against real data);
    `locked=True` for anything from `lockedFiles`, and defensively also
    for any `files` entry with `isLocked: true`, in case that shape is
    ever real too — the confirmed-live signal is array membership, not
    trusted alone.

    STEP 2 — `quality.select_downloads`: a locked candidate is never
    eligible as `settled` (checked separately from `is_practical()` —
    being locked is a harder blocker than a long queue: a long queue
    still downloads, eventually; a locked file, confirmed live, gets
    rejected instantly every time). `_sort_key` gained a third tiebreak
    element (`0 if locked else 1`) so a locked candidate only wins the
    upgrade slot when it's genuinely higher quality than the best
    unlocked option, not merely tied — ties go to whichever is actually
    downloadable right now. When nothing unlocked is practical either,
    settled falls back to the best *unlocked* candidate (still
    downloadable, just slow) rather than a higher-quality locked one
    (not downloadable at all); if literally every filtered candidate is
    locked, `settled` is `None` but `upgrade` still tracks the best one
    for the retry cycle.

    STEP 3 — `download_requests` gains `status = 'locked'` and a `size`
    column (not originally scoped, but required: Phase 3's retry
    re-issues `request_download(username, filename, size)` against the
    exact same candidate, and `size` was previously never persisted —
    only used transiently at request time — so retries had nothing to
    send). Same guarded/idempotent `ALTER TABLE` migration pattern as
    every prior phase. An upgrade-role request rejected with exception
    text matching `LOCK_REJECTION_PATTERNS` (currently just `"not
    shared"`, matched case-insensitively by substring against the one
    real confirmed string — more patterns get added here if a different
    real rejection reason for a locked file ever turns up) becomes
    `'locked'` instead of `'failed'`. Deliberately scoped to
    `role == 'upgrade'` only: `select_downloads` never picks a locked
    file as `settled`, so a settled-role rejection is never expected to
    be lock-related, and doesn't get the retry treatment even if its
    exception text happened to match.

    STEP 4 — `poll_downloads()` fetches requests already `'locked'`
    *before* this run started (a request that newly becomes `'locked'`
    during the main loop waits for the next run — matching the
    daily-cadence design, not retried within the same call) and calls
    `_retry_locked_request` for each: re-issues `request_download`
    against the identical username+filename (not a fresh search — this
    is retrying access to the same candidate, not looking for a new
    one). Since a rejection doesn't raise from `request_download` itself
    (confirmed above), the retry does an immediate follow-up
    `get_download_status` check rather than waiting a full poll cycle to
    find out it failed again — rejected again (any reason) stays
    `'locked'`; anything else transitions to `'queued'`/`'downloading'`
    and ordinary polling takes over. `transfer_id` is updated to the new
    attempt either way (`update_transfer_id_and_status`, a new
    repository method), so a repeat-locked request's next status check
    targets the latest attempt, not a stale one. `SoulseekDownloadError`
    (a genuine batch-level rejection, rather than the async
    "succeeds-then-shows-Rejected" pattern) is caught the same way —
    stays locked, tries again next run. This makes a single daily
    `seeker downloads status` invocation double as the entire locked-file
    retry mechanism — no separate command, matching the daily-cadence
    habit already planned for that command.

    STEP 5 — `seeker downloads status` gains `Locked (retrying): N` in
    its summary line, computed fresh from the DB after both the main
    loop and the retry loop run (same pattern as the existing
    `ready_for_review` count), not an incremental counter — so it always
    reflects the true post-run state regardless of how many requests
    moved in or out of `'locked'` during this call.

    Tests cover: lock-pattern exception routes to `'locked'` not
    `'failed'`; any other rejection reason (including on a settled-role
    request, even with lock-shaped exception text) still routes to
    `'failed'`; a locked retry that succeeds transitions to
    `'downloading'`; a locked retry rejected again (including a raised
    `SoulseekDownloadError` at the batch level) stays `'locked'`, not
    `'failed'`; the `select_downloads` ranking rules (never-settled,
    tie-goes-to-unlocked, quality-based upgrade precedence, all-locked
    fallback) directly; and the existing `poll_downloads()` `input()`
    guardrail test was extended (not duplicated) to also cover a
    newly-locked detection and a locked-retry in the same call, still
    with zero interactive prompts.
14. **Phase 4: upgrade-candidate shortlisting — done.** Extends Phase 3
    (a single upgrade candidate, retried once locked) to a ranked
    shortlist of up to `MAX_UPGRADE_SHORTLIST = 3` (untuned starting
    constant, same convention as every other threshold in this codebase)
    candidates per track: rank 1 is requested immediately as before; 2
    and 3 are persisted (`status='shortlisted'`) but not sent to slskd
    until needed.

    **Real tiebreak gap fixed first, standalone (Step 1):** `_sort_key`
    previously ended at the locked-vs-unlocked tiebreak (Phase 3) with no
    further tiebreak — two candidates equal on tier/bitrate/lock status
    fell through to incidental input-list order rather than genuinely
    preferring the shorter queue. Added `-queue_length` as an explicit
    final element (ascending queue preferred, via negation, matching the
    same reverse=True sort as the rest of the key).

    **Sequential cascade, not simultaneous multi-request — deliberate,
    not just simpler to build.** The Soulseek protocol doesn't swarm the
    way BitTorrent does — there's no benefit to a peer for serving a
    fragment of a file to multiple downloaders in parallel toward one
    listener's goal, and firing every shortlisted candidate as a
    simultaneous request would just mean requesting (and then cancelling
    or ignoring) uploads from 2-3 real people's clients for a track that
    only needs one to actually succeed — real bandwidth and real queue
    slots taken from real users for no benefit to anyone. Sequential
    "try the next one only once this one is confirmed unavailable"
    respects that shared-network reality instead of treating it like a
    CDN. `select_downloads` returns `(settled, upgrade_shortlist:
    list[SoulseekFile])` — settled logic unchanged; the shortlist is
    everything ranked strictly ahead of settled (by the Step 1
    tiebreak-aware key — locked candidates fully eligible, per Phase 3's
    existing precedence), capped at 3.

    `download_requests` gains `rank INTEGER` (1 = immediately requested,
    2/3 = shortlisted, `NULL` for `role='settled'` — ranking is an
    upgrade-only concept) and two new status values: `'shortlisted'`
    (known candidate, persisted, not yet sent to slskd) and
    `'superseded'` (dropped because a better-ranked entry for the same
    track already won) — kept distinct from `'failed'` deliberately, so
    a genuinely-dead attempt (real rejection, no retry coming) is never
    confused in the summary with one abandoned only because a sibling
    candidate already succeeded. Same guarded/idempotent `ALTER TABLE`
    migration pattern as every prior schema change.

    `poll_downloads()`'s cascade: when the currently-active upgrade
    request for a track comes back rejected — locked-pattern or
    otherwise, the exact reason doesn't matter for *whether* to cascade,
    only for how *that* row's own status gets classified — the next
    `'shortlisted'` row for the same track (lowest surviving rank) is
    activated immediately, in the same `poll_downloads()` call: a fresh
    `request_download`, then an immediate follow-up status check (same
    reasoning as Phase 3 — a rejection doesn't raise from
    `request_download` itself, confirmed live, so waiting a full cycle
    to find out it failed again would be pointless). This repeats
    through the whole shortlist until one succeeds/goes genuinely
    in-progress, or the shortlist for that track is exhausted for this
    run. Once exhausted (every entry locked or failed), Phase 3's
    existing retry loop already does the right thing with no changes
    needed: `get_locked()` fetches every `'locked'` row globally, with no
    per-track "just the top one" limitation, so on the next run every
    locked entry for that track gets retried, not only the originally
    top-ranked one.

    The moment any entry for a track reaches `'ready_for_review'`
    (cascade, a Phase 3 retry, or the ordinary main-loop path — all
    three call the same `_supersede_others_for_track`), every other
    still-in-the-running entry for that track
    (`queued`/`downloading`/`locked`/`shortlisted`) is marked
    `'superseded'` in one query and stops being touched by anything.

    **Real bug found and fixed while wiring this up, not just assumed
    away:** the natural-seeming move was to unify the Phase 3 retry and
    the new cascade activation into one shared "submit and check"
    helper, since their bodies looked identical. A test
    (`test_locked_request_rejected_again_stays_locked_not_failed`)
    caught that they're NOT the same: Phase 3's retry is reactivating an
    ALREADY-confirmed-locked row, where *any* rejection reason on the
    retry should keep it `'locked'` (no need to re-verify why); the
    cascade's activation is a candidate's genuine FIRST attempt, where
    the rejection reason still needs proper locked-vs-failed
    classification. Unifying them silently broke the "any reason stays
    locked" retry guarantee. Kept as two small, separately-correct
    methods instead of one over-generalized one. While fixing this, also
    caught and fixed a real latent bug in the original Phase 3
    `_retry_locked_request`: it never checked for a `"Succeeded"` state
    on the immediate follow-up check, so a retry that succeeded
    instantly would have been mislabeled `'downloading'` and never
    triggered supersede — fixed as part of the same pass, now correctly
    checked in both methods.

    **A second real race found while writing the "rank 2 success
    supersedes rank 1" test, not incidentally:** `poll_downloads()`
    fetches the `'locked'` list once at the very start, before the main
    loop runs. If a *different* row for the same track succeeds during
    that loop and supersedes a locked entry, the retry loop — still
    working off that stale, pre-run snapshot — would otherwise reactivate
    it anyway, resurrecting a status that should have stayed
    `'superseded'`. Fixed by having `_retry_locked_request` re-fetch the
    row's current status (new `DownloadRequestRepository.get_by_id`) and
    bail out if it's no longer actually `'locked'`, before ever calling
    `request_download` again.

    `seeker downloads status` gains `Shortlisted (pending): N` and
    `Superseded: N`, both computed fresh from the DB each run (same
    pattern as `ready_for_review`/`locked`), alongside the existing
    counts.

    Tests use real peer usernames/file sizes captured from the live
    "Dom Dolla Rhyme Dust" search during the Phase 3 investigation
    (Wolfring/lifelooop/CDM-Addicted) for realistic shortlist data at
    this layer — `download_service` tests operate on already-selected
    DB rows, not raw search JSON, so the messier real filenames (several
    of which are mashup/multi-track contaminated and wouldn't survive
    `filter_candidates`' fuzzy title matching — a separate, correctly
    working concern exercised in `test_quality.py`) don't need to
    round-trip through the matcher here. Cover: same-run cascade through
    two rejections to a third candidate that succeeds, with the first
    two correctly ending up `'superseded'` (not left `'locked'`) the
    instant the third wins; full-shortlist exhaustion in one run
    correctly falling back to per-entry retry on the next; the
    rank-2-succeeds-supersedes-rank-1-and-rank-3 race scenario, with an
    `AssertionError`-raising fake `request_download` response wired to
    rank 1's filename as a guardrail that fails loudly if the stale-retry
    race bug were ever reintroduced; and the existing `poll_downloads()`
    `input()` guardrail extended once more to also cover a cascade
    landing in-progress, alongside everything Phase 3 already added.

15. **Polish pass — dead code, mypy --strict, docstrings, error-handling
    audit, coverage audit, README, dependency audit — done (2026-08-27).**

    **Dead code removed:** `src/seeker/__init__.py` was a leftover stub
    `main()` unrelated to the real `seeker.main:main` entry point —
    emptied. `soulseek/quality.py::select_best()` had zero production
    callers (superseded by `select_downloads` back in item 8) but was
    still hanging around, exercised only by its own now-redundant tests —
    removed, tests converted to exercise `select_downloads` directly. The
    phantom `playlist_selector.py` line in this file's layout tree (never
    existed on disk) was removed.

    **`mypy --strict` now passes clean (0 errors, 44 files)** — previously
    only run in a looser mode. Mechanical fixes (return types, `dict[str,
    Any]`/`cast()` at real `Any` boundaries like `httpx.Response.json()`)
    made up most of it, but a few were genuine bugs, not just type noise:
    `soulseek/client.py::_parse_search_response`/`_build_soulseek_file`
    now actually validate that `username`/`filename`/`size`/etc. are
    non-`None` before building a candidate from them (previously assumed
    present and would have produced a candidate mypy could not have caught
    downstream); `library/metadata_service.py::tag_tracks`'s return value
    used to silently mutate a `dict[str, int]` to also hold a `list` under
    `"details"`, which strict mode caught as a real type mismatch — fixed
    by returning a merged dict instead of mutating. `mutagen` ships no
    type stubs at all (confirmed: no `py.typed` marker, no `types-mutagen`
    on PyPI) — rather than scatter per-line ignores across
    `metadata.py`'s many mutagen call sites, one scoped
    `[[tool.mypy.overrides]] module = "seeker.metadata"
    disallow_untyped_calls = false` in `pyproject.toml`, with a comment
    explaining why. `librosa.beat.beat_track`'s `prior` parameter stub
    expects `scipy.stats.rv_continuous`, but `scipy.stats.uniform(...)`
    actually returns `rv_continuous_frozen` (confirmed at runtime, not
    guessed) — typed `Any` with an inline comment rather than fighting the
    stub. A handful of `assert x is not None` were added at points where a
    real invariant guarantees non-null (e.g. a row just upserted and
    refetched in the same transaction) — each has an inline comment
    explaining the invariant, not a silent assertion.

    **Docstrings/comments added** where the "why" wasn't derivable from
    code alone: the 90/70 auto/needs-review matching thresholds
    (`matching.py`), the Camelot key relative-major/minor pairing
    convention (`audio_analysis.py::CAMELOT_MAP`), the full 8-state
    `download_requests.status` state machine including every real
    transition (`database/schema.py`), and `resolve_playlist_or_offer_sync`'s
    docstring was rewritten to explicitly enumerate all 4 real outcomes.

    **Error-handling audit — root cause of the original "searched only 4
    of 6 unmatched tracks" run, confirmed:** `download_playlist()`'s
    per-track loop had no exception handling at all — any uncaught
    exception during one track's processing (a search timeout, a
    malformed response, anything) silently aborted every track after it
    in the batch with zero accounting; the batch just ended early and
    looked like a smaller, successful run. Fixed by wrapping each
    iteration individually with a new `failed` bucket, so every track now
    lands in exactly one of `requested`/`skipped`/`failed`, and the CLI
    prints all three plus the true `total`. The same audit found
    `poll_downloads()`'s two loops (main per-request loop and the locked-
    retry loop) had the identical gap and applied the identical fix —
    wrapping each request individually rather than the whole loop.
    `tests/test_download_service.py` gained
    `test_download_playlist_mid_batch_exception_does_not_abort_remaining_tracks`
    and `test_poll_downloads_mid_batch_exception_does_not_abort_remaining_requests`,
    each simulating a mid-batch exception and asserting every item is
    still accounted for. `library/metadata_service.py::tag_tracks` already
    had this pattern (added in Phase B, item 10) and was extended with the
    same test as a genuine gap it was still missing coverage for
    (`test_tag_tracks_mid_batch_exception_does_not_abort_remaining_tracks`).
    Separately, `SpotifyClient._get`'s 429-retry loop had no ceiling on
    retry *count* (only on each individual wait being ≤60s) — a server
    returning a short `Retry-After` indefinitely would have retried
    forever; bounded with `MAX_RETRY_ATTEMPTS = 5`.

    **Correction, found during the Phase 2 live re-verification run
    against the real "Test" playlist:** the exception-handling gap above
    is real and worth having fixed regardless, but is very likely **not**
    what actually caused the original "searched only 4 of 6" observation.
    `TrackMatcher.generate_match_report()` (what `check` prints) and
    `match_all()` (what `library match` prints) both report counts
    **across every track in the entire local DB, from every synced
    playlist combined** — neither takes a playlist argument or scopes to
    one. `download_playlist(playlist_name)` is correctly scoped to just
    that one playlist's tracks via a real `playlist_tracks` join. Queried
    the real DB directly: the "Test" playlist has exactly 10 tracks — 6
    auto-matched, 4 unmatched — and a real `seeker download "Test"` run
    (2026-08-27) searched and accounted for all 4, none dropped. The "6
    unmatched" in the original observation almost certainly came from
    `check`'s global count (this DB's other synced playlists, e.g.
    `240KM/H`, contribute additional unmatched tracks of their own),
    compared against Test's own, smaller, correctly-scoped download
    count — not two numbers that were ever supposed to match. `check`'s
    output doesn't say anywhere that it's reporting globally rather than
    for "whatever playlist I was just looking at," which is a genuine,
    separate, easy-to-misread gap — worth a future `check [playlist_name]`
    scoping option, but that's a new feature, out of scope for this
    verification-only pass.

    **Coverage audit — real gaps closed, not a percentage chase.**
    `spotify/token_store.py` (0% → 100%, pure file I/O, cheapest real
    gap), `spotify/auth.py` (PKCE helpers + token exchange/refresh, 52% →
    100%, including a `refresh_access_token` test for the documented "old
    refresh_token retained when Spotify doesn't return a new one"
    behavior), `spotify/callback_server.py` (35% → 100% — genuinely
    testable despite being HTTP-server code, since it's a real local
    socket server with no external dependency; driven with real requests
    over a background thread in `tests/test_callback_server.py`),
    `spotify/auth_manager.py::get_valid_token()` (25% → 67%, covering all
    3 reachable branches — valid token returned as-is, expired token
    refreshed, and the documented refresh-fails-so-reauthorize fallback
    from an earlier session's git history — via a real `TokenStore`
    against `tmp_path` and monkeypatched `refresh_access_token`/
    `_authorize`). `library/metadata_service.py` (76% → 94%): added
    direct tests for `tag_playlist()` (previously only exercised via
    `tag_tracks` directly, never its own auto-matched-only filtering or
    its `PlaylistNotFoundError`), the mid-batch exception handler (see
    above), the real "mutagen can't identify this file at all" branch
    (distinct from "identified but unsupported for writing" — confirmed
    live that only `.m4a`/`.ogg` return `None` gracefully on unparseable
    content; `.mp3`/`.flac`/`.wav`/`.aac` raise instead and are caught by
    the outer handler, so the extension used in the test matters), and the
    best-effort album-art/analyze-audio failure isolation branches (a
    download or analysis failure must not undo an already-successful
    text-tag write — both now directly tested). `soulseek/client.py`
    (implicitly covered only via `FakeSoulseekClient` before — 9 new
    tests added directly mocking `httpx`, covering `request_download`/
    `get_download_status`/`get_download_exception` including the exact
    real rejection string confirmed live in item 13,
    `"Transfer rejected: File not shared."`).

    **Explicitly judged not worth closing further:** `auth_manager.py`'s
    remaining gap is `_authorize()` itself — opening a real browser and
    running a real local OAuth callback server round-trip. This was
    verified live in earlier sessions (real Spotify authorization flows
    completed against this exact code), and mocking `webbrowser.open` +
    a real socket server round-trip for a unit test would test the mock,
    not the integration — this project's stated preference is
    real-data verification over synthetic mocks of external flows, and
    that verification already happened, just not as an automated test.
    `application.py` (lazy-init one-line getters) and `cli.py` (argument
    dispatch/print formatting) stay thin by design — the logic they wrap
    is tested at the service layer; testing the getters/dispatch
    themselves would mostly be re-asserting `if self._x is None:
    self._x = X(...)`. `main.py`'s argparse entry point is a two-line
    wrapper with no branching logic of its own.

    **README.md written** (didn't exist before) — what/why, the
    CLI→service→repository layering and why it's enforced, full setup
    (Spotify app registration, required `.env` vars, `slskd`/Docker
    setup), a full command reference table, and a design-principles
    section naming the four patterns this codebase actually holds to:
    transactional integrity via `PRAGMA foreign_keys = ON` + real
    transactions, one-bad-item-can't-abort-a-batch, verify-against-real-
    data-over-docs, and never touching a file destructively without an
    explicit confirmation prompt.

    **Dependency audit:** all 5 original runtime dependencies
    (`httpx`, `librosa`, `mutagen`, `python-dotenv`, `rapidfuzz`)
    confirmed genuinely imported in `src/`. Found one real gap the other
    direction: `audio_analysis.py` does `import scipy.stats` directly and
    calls it at runtime (`scipy.stats.uniform(...)`, from item 11's
    octave-error-correction prior), but `scipy` was never listed as an
    explicit dependency — only present because `librosa` happens to pull
    it in transitively, and only `scipy-stubs` (a type-checking-only dev
    dependency) referenced it explicitly. Added `scipy>=1.18.1` (the
    version actually resolved/installed) to `dependencies` in
    `pyproject.toml` so this isn't silently relying on another package's
    transitive dependency graph never changing.

    Final state after this pass: 142 tests passing, `mypy --strict` clean
    across all 44 source files, 85% overall coverage with the remaining
    gaps identified and each one either closed or explicitly justified
    above.
16. **Live re-verification against the real "Test" playlist (2026-08-27),
    after item 15's polish pass — two real findings, not yet fixed.**
    Full pipeline run for real: `scan` (3215 unchanged) → `match` (global:
    auto 7, needs_review 0, unmatched 6 — see the correction in item 15)
    → `check --verbose` → `download "Test"` → `downloads status` →
    `downloads review` → `library tag "Test" --analyze-audio`. Queried the
    real DB directly rather than trusting printed output: "Test" has
    exactly 10 tracks — 6 auto-matched (several genuinely multi-artist,
    e.g. "Audio, REEBZ - Tractor Beam" and "Joe Ford, Task Horizon -
    Ultraviolet", both scoring 100.0 — confirms item 9's multi-artist fix
    is working live, no regressions), 4 unmatched. `download "Test"`
    searched and accounted for all 4 (0 requested, 4 skipped, 0 failed,
    total 4) — full accounting confirmed for real, not just in tests.
    `library tag --analyze-audio` tagged all 6 auto-matched tracks; spot-
    checked one end-to-end, not just trusted the summary line: DB says
    `Prolix - Cannibals` bpm=172.27/key=4A, and the real file's own TBPM/
    TKEY frames read back `172`/`4A` — matches exactly.

    **Finding 1 — a locked-but-real candidate was silently discarded
    instead of entering the retry cascade — investigated and fixed
    (2026-08-27).** For `Jade Venom - Scared Now? - DIVERGENCE VI`, a real
    raw search (using the exact query `_build_search_query` builds)
    returns exactly one candidate passing `filter_candidates`: score 90.9
    (above `AUTO_MATCH_THRESHOLD`), `locked=True`, `queue_length=7`.
    Traced the real data through each stage before touching any code, to
    confirm which of three hypotheses was the actual cause rather than
    guessing: (1) did it fail the ≥90 filter before locked-status was
    considered? — no, it's the one candidate `filter_candidates` lets
    through; (2) did `select_downloads`'s ranking/shortlist logic mishandle
    this case? — no, `select_downloads` correctly returns `(settled=None,
    shortlist=[that locked file])`, exactly per its own documented
    contract (item 13): nothing practical/unlocked exists, but the real
    candidate is preserved in the shortlist for the retry cascade; (3) was
    it `download_playlist`'s handling of the returned shortlist? — **yes,
    confirmed**: `if settled is None: print("No candidates found.");
    skipped += 1; continue` (`soulseek/download_service.py`) never checked
    `upgrade_shortlist` before discarding it, and the `continue` meant the
    `if upgrade_shortlist:` block below (which *does* handle this
    correctly when `settled` is found) was unreachable for this case.

    Fixed by extracting the existing "request rank 1 immediately, persist
    the rest as `shortlisted`" logic into a shared
    `_request_upgrade_shortlist()` helper, called from both the normal
    settled-found path and a new `settled is None but upgrade_shortlist
    is non-empty` branch — the latter requests rank 1 as `role='upgrade'`
    (landing it in `poll_downloads`'s existing locked-retry cascade,
    unchanged) and counts the track as `requested`, not `skipped` — a real
    download was requested, just not a settled one.
    `tests/test_download_service.py::
    test_download_playlist_requests_locked_only_candidate_as_upgrade`
    reproduces the exact real candidate data (`ofoijacussa`, the real
    filename/size/queue_length captured live above) rather than a
    synthetic stand-in, and was confirmed to actually fail against the
    pre-fix code (`result["requested"] == 0`, "No candidates found."
    printed) before the fix was applied, then pass after.

    **Re-verified live against real slskd, not just in tests:** a real
    `seeker download "Test"` after the fix printed "Requested upgrade
    from ofoijacussa: ...(rank 1)" for Jade Venom, and — peer results
    varying run to run, as always with live Soulseek search — also found
    a second real locked-only match this time (`Balron, Audio - Breach`,
    peer `long25`). Both landed as real `role='upgrade', rank=1,
    status='queued'` rows; a follow-up `seeker downloads status` showed
    both genuinely rejected by slskd and transitioned to `status='locked'`
    ("Locked (retrying): 2"), confirming they're now enrolled in the
    existing Phase 3 daily retry cascade instead of vanishing.

    **Finding 2 — Soulseek matching has no needs-review tier, unlike the
    local-file matcher.** Real searches for the other 3 unmatched tracks
    (`Prdk - ONE MORE NIGHT`, `Balron, Audio - Breach`, `Zigi SC, A-Cray -
    Bit Perfect`) all returned real, clearly-correct-artist candidates —
    just none scoring ≥90. Real scores observed: 70.4 (Prdk, filename
    carries a `(Clean) 4A 87` DJ-pool suffix), up to 79.2 (Balron/Audio,
    `(Original Mix)` suffix), up to 73.2 (Zigi SC/A-Cray, same pattern).
    `soulseek/quality.py::filter_candidates` only has a single hard cutoff
    (`score < AUTO_MATCH_THRESHOLD` → reject) — there's no
    `NEEDS_REVIEW_THRESHOLD` equivalent the way `library/matcher.py` has
    for local files, so a real, plausible-but-not-clean-filename match is
    silently dropped with no way for a human to confirm it, rather than
    being surfaced the way a 70-90-scoring local file already is via
    `check`'s needs-review bucket. Not a bug — `filter_candidates` is
    doing exactly what it's coded to do — but a real, consistent pattern
    across 3 of 4 real unmatched tracks in this run, worth a deliberate
    decision (add a Soulseek needs-review tier, or accept the gap) rather
    than staying an unnoticed side effect of never having had real search
    data to look at before now.

    (Investigated and ruled out as a red herring along the way: initially
    suspected `Path(filename).stem`'s POSIX-only backslash handling as
    the cause of Prdk's low score — confirmed `Path(...).stem` really
    doesn't split on `\` on this OS, but `quality.py` never actually calls
    it; it has its own `normalize_soulseek_title()`, which already
    handles both separators correctly. The real explanation was the DJ-
    pool filename noise above, not a path-parsing bug.)
17. **Soulseek needs-review tier — done (2026-08-27), addressing item
    16's Finding 2.** Mirrors `library/matcher.py`'s three-tier design
    (auto/needs_review/none, same `AUTO_MATCH_THRESHOLD`/
    `NEEDS_REVIEW_THRESHOLD` from `matching.py`) rather than inventing a
    parallel threshold scheme, for the same reason `matching.py` itself
    was consolidated (item 3's backlog entry): one shared notion of
    "confident enough" across local files and Soulseek results, not two
    independently-tunable ones.

    `soulseek/quality.py`: extracted `_score_candidate(track, file)` —
    the extension + `artist_matches` + `score_title` logic
    `filter_candidates` already had — as a shared helper, returning
    `None` when the file isn't audio or the artist doesn't match at all
    (distinct from a real low score). `filter_candidates` (auto tier,
    unchanged behavior) and the new `find_best_needs_review_candidate`
    (70 ≤ score < 90, returns the single best-scoring match across ALL
    files, not just the auto-filtered ones) both call it.
    `select_downloads` gained a third return value —
    `tuple[SoulseekFile, float] | None` — computed once up front and
    passed through unchanged at every existing return point; the
    settled/upgrade ranking logic itself is untouched, exactly as
    intended (needs_review is informational, never influences what gets
    downloaded).

    New `soulseek_review_candidates` table (`track_id` PRIMARY KEY —
    one row per track, the single best-known candidate, not a history
    log) + `SoulseekReviewCandidateRepository`
    (`upsert`/`delete`/`get_all`) + `SoulseekReviewCandidate` model,
    following the same repository-per-table pattern as everything else.
    Considered extending `download_requests` instead (its own `role`/
    `status` state machine was right there), but rejected: every row in
    that table represents something actually submitted to slskd via
    `request_download` — a needs_review candidate never is, and forcing
    it into that state machine would mean inventing a status with no
    `transfer_id`, no real `requested_at`-as-"we asked slskd" semantics,
    and no real transition path in or out. A dedicated table keeps the
    "submitted to slskd" and "merely observed, never requested" concepts
    from blurring together.

    `download_playlist()` populates it exactly when `settled is None`
    AND `upgrade_shortlist` is empty (i.e. truly nothing auto-tier at
    all — not even a locked one, which already goes through item 16's
    upgrade-shortlist path instead) AND a needs_review candidate exists;
    counted as `skipped`, not `requested` — nothing was actually
    downloaded. Real gap caught while wiring this up, not merely assumed
    away: a stale needs_review row from an earlier, worse run would
    otherwise keep being surfaced by `check` even after a later run finds
    something genuinely better. Fixed by clearing any existing row for a
    track the moment `settled is not None or upgrade_shortlist` — i.e.
    something real and auto-tier now exists — covered by
    `test_download_playlist_clears_stale_review_candidate_once_settled`.

    `seeker check` gains a new `Needs review (SoulSeek candidate found)`
    section, printed unconditionally (not gated behind `--verbose`,
    matching the existing local needs_review/unmatched sections'
    convention) and clearly separate from `Unmatched` — a track can
    legitimately appear in both (no local file match, but a real,
    plausible Soulseek candidate exists) since the two buckets measure
    different things. **Real design snag found and fixed while wiring
    this up:** the obvious implementation — `handle_check` calling
    `application.download_service.get_review_candidates()` — would have
    broken `seeker check` outright for anyone without `slskd` configured
    at all, because `Application.download_service`'s property eagerly
    constructs a real `SoulseekClient` (which raises `RuntimeError` if
    `SLSKD_BASE_URL`/`SLSKD_API_KEY` aren't set) before `DownloadService`
    even exists — even though `get_review_candidates()` itself never
    touches the Soulseek client at all, it's a pure DB read. `config.py`
    already documents slskd as optional for `sync`/`playlists`/`scan`/
    `match`; `check` was always in that group too, so this would have
    been a real regression. Fixed with a new, cheap
    `Application.soulseek_configured` property (a plain config check, no
    client construction) that `handle_check` checks before ever touching
    `application.download_service` — configured: the new section runs
    normally; not configured: silently omitted, matching `check`'s
    existing behavior exactly. `tests/test_cli.py` covers both.

    **Interactive confirm/reject is deferred to a future UI, not another
    CLI prompt loop — explicitly, matching `library/matcher.py`'s own
    identical open item** (roadmap item 7: "a `review` command to
    confirm/reject needs-review matches is still outstanding"). This
    tier is read-only and informational by design, per the ask — no
    `seeker check review` or similar was added.

    **Real data note — STEP 4 was written expecting the Jade Venom/
    Kamäleon/ZENEA tracks; only Jade Venom is real, and it turned out not
    to belong in this tier.** Investigated rather than assumed: Jade
    Venom's real candidate (item 16) scores 90.9 — genuinely auto-tier,
    just locked — so by design it's in the upgrade-shortlist path (item
    16's fix), never the needs_review tier; using it here would have
    tested the wrong thing. Kamäleon and ZENEA were never actually
    searched live in this session — they surfaced only in `check`'s
    *global* unmatched list (see item 16's correction) from a different,
    unexamined playlist, so there was no real captured Soulseek data for
    them to use. Used the two tracks that genuinely landed in the real
    70-89 band during today's actual live investigation instead — `Prdk -
    ONE MORE NIGHT` (70.4, real DJ-pool `(Clean) 4A 87` suffix) and `Zigi
    SC, A-Cray - Bit Perfect` (73.2, real `(Original Mix)` suffix) — same
    real captured data (`tests/test_quality.py`'s
    `REAL_PRDK_CANDIDATE`/`REAL_ZIGI_SC_CANDIDATE`) reused at both the
    pure-classification layer (`test_quality.py`) and the persistence
    layer (`test_download_service.py::
    test_download_playlist_records_real_prdk_and_zigi_sc_as_needs_review`).

    **Re-verified live**, not just in tests: real `seeker download "Test"`
    after this change printed "No auto-match candidate — needs-review
    candidate found" for both Prdk (score 70.4) and Zigi SC/A-Cray (score
    73.2, this run's best real candidate was `DJ-Promo`'s copy — Soulseek
    peer results vary run to run, as always); a real `seeker check`
    immediately after showed both listed under the new section with their
    real scores and real usernames/filenames, and — confirmed
    deliberately, not just assumed — both also still appear in the
    ordinary `Unmatched` section beneath it, since the two sections
    measure genuinely different things.

18. **Migrated the SQLite database path from CWD-relative to an
    OS-conventional app-data directory via `platformdirs` — done
    (2026-08-28).** `.seeker/seeker.db` (relative to wherever `seeker`
    happened to be run from) was never a real per-user location — it
    just happened to work because the CLI was always invoked from this
    project's own directory. Replaced with
    `platformdirs.user_data_dir("Seeker", appauthor=False)` (e.g.
    `~/Library/Application Support/Seeker` on macOS, `~/.local/share/
    Seeker` on Linux, `%LOCALAPPDATA%\Seeker` on Windows) —
    `appauthor=False` since this is a personal project with no separate
    publisher/org identity worth a vendor subdirectory on Windows.
    `Application._resolve_database_path()` creates that directory
    (`mkdir(parents=True, exist_ok=True)`) before `Database()` is ever
    constructed. Scoped to the SQLite database only, per the ask — the
    Spotify token cache (`.seeker/spotify_token.json`) is untouched and
    stays where it was.

    **A real, non-empty database already existed at the old location**
    (2.1MB, 215 playlists, 13 tracks, 13 track_matches, 7
    download_requests, 3215 local_files — this project's actual daily-use
    data, not a fixture) — so a silent "just create fresh at the new
    path" would have orphaned all of it. `Application._migrate_legacy_database()`
    checks for exactly that: if a DB already exists at the new
    platformdirs location, never touch anything (guards against a stale
    leftover `.seeker/seeker.db` ever clobbering current real data on a
    later startup); if not, and the old `.seeker/seeker.db` exists, moves
    it (`shutil.move`) into the new location and prints exactly what
    happened; if neither exists, does nothing and a fresh DB is created
    at the new location as normal.

    Tests (`tests/test_application.py`) cover `_resolve_database_path`
    and `_migrate_legacy_database` directly (fresh-directory creation;
    real-bytes-preserved move; neither-exists no-op; existing-new-DB
    never overwritten by a stale legacy file), plus full `Application()`
    integration tests for both the fresh-install and real-migration
    paths — the migration test seeds a real schema-initialized DB with
    an actual row via `Database`/`.transaction()` (not just arbitrary
    bytes) and asserts that exact row is readable back through
    `app.database` after construction, confirming the moved file is
    still a genuinely working, queryable database, not just a
    byte-for-byte copy that happens to sit at the right path.

    **Verified live against this project's real, actual database, not a
    copy:** ran `seeker playlists` for real. Output line one:
    `Migrated existing database from .seeker/seeker.db to
    /Users/sinthesis/Library/Application Support/Seeker/seeker.db.` —
    then all 215 real playlists listed normally, same as always. Directly
    confirmed after: `.seeker/` now holds only `spotify_token.json` (no
    `seeker.db`); the new location has a `seeker.db` that is
    byte-identical in size (1,437,696 bytes) to the pre-migration file;
    row counts at the new location match the pre-migration counts
    exactly (215/13/13/7/3215, queried directly via `sqlite3`, not
    trusted from the app's own output alone); `seeker check` against the
    migrated DB reproduced the exact same auto-matched/needs-review/
    unmatched breakdown as the last real verification run before this
    migration (7 auto-matched, the same 2 SoulSeek needs-review
    candidates, the same 6 unmatched tracks). A second real
    `seeker playlists` run immediately after printed no migration
    message (nothing left to migrate) and still listed all 215
    playlists correctly — confirming the guard against re-migrating or
    double-running is genuinely idempotent, not just implemented.

19. **Frontend Phase 0, Task 1 — local JSON config store for
    SoulSeek/slskd settings, with legacy `.env` migration — done
    (2026-08-28).** Groundwork for a future onboarding wizard/Settings
    screen: those need something they can write to directly, not a
    `.env` file a human hand-edits. `.env` conceptually narrows to just
    `SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI` (genuinely fixed at
    install time) — `SLSKD_BASE_URL`/`SLSKD_API_KEY`/`SLSKD_DOWNLOAD_DIR`
    move to a small JSON store the app owns. `config.py` itself is
    unchanged (still reads all five vars from `.env`/`os.environ`) —
    the SLSKD_* reads there are still needed as the migration source and
    as the fallback described below, so removing them wasn't the ask;
    only what a *new* setup should ever need to hand-edit narrows.

    New `config_store.py`: a typed `SeekerConfig` dataclass
    (`slskd_base_url`/`slskd_api_key`/`slskd_download_dir`, all
    `str | None = None`) rather than a generic dict, matching this
    codebase's existing typing discipline. Deliberately **excludes**
    SoulSeek network username/password — nothing consumes them yet
    (`SoulseekClient` only ever needed `base_url`+`api_key` for slskd's
    REST API); those get added when the onboarding wizard that actually
    generates slskd's own config is built, not speculatively now.
    `resolve_config_path()` mirrors `application.py`'s
    `_resolve_database_path()` exactly — same
    `platformdirs.user_data_dir("Seeker", appauthor=False)` directory
    the database lives in (item 18), `config.json` alongside
    `seeker.db`. `load_config`/`save_config` are a plain JSON
    round-trip; a missing file, a partial/old-shape file (missing
    keys), or genuinely corrupt JSON all resolve to all-`None`
    defaults rather than crashing — this is deliberately *not*
    versioned/guarded-migration machinery the way the DB schema is,
    since a flat JSON file with defaulted optional fields is inherently
    additive. `save_config` chmods the file `0600` where the OS
    supports POSIX permission semantics (a no-op on Windows) — this
    file will eventually hold real credentials, even though this task
    doesn't add any yet.

    `migrate_legacy_slskd_env_config(path)` mirrors
    `_migrate_legacy_database`'s contract field-by-field rather than
    whole-file: a field the store already has a value for is never
    overwritten from `.env` (guards a stale env var from clobbering a
    value changed since via a future Settings screen); a field the
    store is missing gets copied in from the matching env var if set,
    saved, and reported in one summary print naming exactly which env
    vars were migrated; nothing to migrate is a genuine no-op with no
    output; running it twice produces no second migration message —
    confirmed via a real idempotency test, not just asserted by
    inspection. The real `.env` file itself is never read from or
    written to directly — only `os.environ` (already populated by
    `config.py`'s `load_dotenv()`, which runs at import time) is read,
    so nothing about the user's `.env` file changes.

    `Application.__init__` calls this once, right after
    `Database.initialize()` and before anything can construct a
    `SoulseekClient` — same ordering principle as the DB migration
    itself. `soulseek_configured`/`soulseek_client`/`download_service`
    now resolve `base_url`/`api_key`/`download_dir` through three new
    private properties (`_slskd_base_url`/`_slskd_api_key`/
    `_slskd_download_dir`), each `self._config_store.<field> or
    config.SLSKD_*` — config store wins, `.env` is the fallback. This
    preserves exact existing behavior for anyone who hasn't been
    through migration yet (env-only stays working) while letting a
    future Settings write reach the store and take effect without
    touching `.env` at all.

    **A real gotcha caught while writing the Application-level
    integration test, not left implicit:** `config.py`'s
    `SLSKD_BASE_URL`/`SLSKD_API_KEY`/`SLSKD_DOWNLOAD_DIR` are plain
    module-level constants fixed once at import time — `monkeypatch
    .setenv` on `os.environ` has zero effect on them after the fact
    (unlike `config_store.py`'s own migration function, which reads
    `os.environ` live via `os.getenv` on every call and IS correctly
    affected by env monkeypatching). A test asserting the
    store-empty-falls-back-to-env property path has to monkeypatch
    `seeker.application.config.SLSKD_*` directly, not just
    `os.environ` — `tests/test_application.py`'s two new
    Application-level tests do both (env vars, for the real migration
    step to pick up live; the frozen `config.*` constants, for the
    property fallback itself) and explicitly re-null the config store
    after construction to isolate the fallback branch from migration
    already having copied the value in.

    Tests: `tests/test_config_store.py` covers path resolution,
    save/load round-trip, missing/partial/corrupt-JSON loads, the
    `0600` permission check (skipped on Windows, same treatment as the
    drive-unmounted skip elsewhere in this suite), and all of the
    migration contract points above (copy-when-empty, never-overwrite,
    no-op, idempotent, partial-fields-only). Every migration test
    explicitly clears all three `SLSKD_*` env vars before setting only
    the ones it means to exercise — caught for real during this task:
    the first version of `test_migrate_never_overwrites_value_already
    _in_store` only set `SLSKD_BASE_URL` and left the real project
    `.env`'s own `SLSKD_API_KEY`/`SLSKD_DOWNLOAD_DIR` values live in
    `os.environ`, so the test unexpectedly migrated those two for
    real (into a `tmp_path` store, harmlessly, but the test's own
    "no output" assertion failed) — fixed by adding a shared
    `_clear_slskd_env` helper used at the top of every migration test
    that doesn't explicitly set all three fields itself, rather than
    depending on whichever machine happens to run the suite.
    `tests/test_application.py` adds two full `Application()`
    integration tests: config store values winning over a
    deliberately-different env value across all three fields and every
    consumer (`soulseek_configured`, `soulseek_client.base_url`,
    `download_service.slskd_download_dir`); and the env-only fallback
    path, both end-to-end (through real migration) and isolated
    (store forced back to empty post-construction).

    **Explicitly not run for real against this machine's actual `.env`
    or config directory**, per the ask — this is a real, once-only
    action on real user state (even though `.env` itself is never
    touched, it changes what the running app reads), held back for an
    explicit go-ahead the same way Phase B's real tag-write and the DB
    migration itself were both held back until asked for directly.
    Confirmed no stray `config.json` exists at the real
    `~/Library/Application Support/Seeker` location after building and
    testing this — every test redirects `platformdirs.user_data_dir`
    into `tmp_path` first.

20. **Frontend Phase 0, Task 2 — real download progress tracking
    (bytes_transferred/total_bytes) — done (2026-08-28).** Unblocks a
    future progress-view screen with real per-track numbers instead of
    something simulated; no UI work in this task.

    **Real field names confirmed live before writing any parsing code**
    (per this project's own repeated lesson — see the Spotify
    endpoint/field-name saga, roadmap item 1): hit
    `GET /api/v0/transfers/downloads/{username}/{id}` directly against
    two real transfers on the live instance — a genuinely completed one
    (`kingdomcum`, the real 3AMDISCO WAV) and a genuinely rejected-locked
    one (`ofoijacussa`, Jade Venom). Confirmed: the real fields are
    `size` (total bytes — matches the convention `SoulseekFile` already
    uses, so the new `TransferStatus` type follows that rather than
    introducing a `total_bytes`/`size` inconsistency at the client
    layer) and `bytesTransferred` (progress so far). Both are always
    real integers on a real transfer body — a rejected-before-any-bytes-
    moved transfer reports `bytesTransferred: 0` for real, not
    absent/null; a genuinely completed transfer reports
    `bytesTransferred == size` exactly (confirmed:
    `79776980 == 79776980`).

    `soulseek/client.py::get_download_status` changed from returning a
    bare `state: str` to a new `TransferStatus` dataclass
    (`state`/`bytes_transferred`/`size`, the latter two `None` only on
    the existing 404/"NotFound" sentinel path, where there's no real
    transfer body to read them from). All three real call sites
    (`poll_downloads`'s main loop, `_activate_shortlisted_entry`,
    `_retry_locked_request`) updated to read `.state` instead of
    treating the return value as a plain string.

    `download_requests` gains two new nullable columns,
    `bytes_transferred INTEGER` / `total_bytes INTEGER`, via the
    existing `_add_column_if_missing` helper — no new migration
    machinery invented. `DownloadRequest` gains the matching two fields.
    New `DownloadRequestRepository.update_progress(request_id,
    bytes_transferred, total_bytes, connection)` — deliberately kept
    separate from `mark_status`/`update_transfer_id_and_status`, same
    reasoning as `update_analysis` being kept out of `upsert`'s
    `ON CONFLICT DO UPDATE`: a routine progress poll must not risk
    disturbing any unrelated column.

    `poll_downloads()`'s main loop calls `_update_progress` for every
    request it polls from `pending` (queued/downloading only) —
    unconditionally, whether the state transition changes or not, since
    real bytes move every poll regardless. Two edge cases handled
    deliberately, not left to fall out accidentally: a rejection
    (anything matching `FAILED_STATE_MARKERS`) `continue`s *before*
    reaching the progress call, so a rejected-before-any-bytes-moved
    transfer's progress fields stay genuinely unset (`NULL`) rather than
    persisted as a misleading `0`; a request that reaches `pending` and
    then succeeds this same poll still gets its final, real
    `bytes_transferred == total_bytes` recorded (confirmed this really
    is what the live data shows — see below). `locked`/`shortlisted`/
    `superseded` requests never enter `pending` at all, and the two
    retry/cascade-activation call sites deliberately do **not** call
    `_update_progress` — those rows were never actually transferring at
    the moment of that call, matching the ask exactly.

    Tests: `tests/test_connection.py` (new file — no dedicated DB-layer
    migration test existed before this; the BPM/Camelot column
    migrations this task's ask referenced as precedent were, in fact,
    only ever verified live, not with a standing test, so this is a
    genuinely new addition, not a mirror of something that turned out to
    exist) covers the guarded `ALTER TABLE` against a hand-built
    pre-migration `download_requests` table with a real seeded row,
    confirming the two new columns appear, default to `NULL`, and every
    original column survives untouched, plus idempotency on a second
    `initialize()` call. `tests/test_soulseek_client.py` extends the
    existing `get_download_status` tests to assert `.state` and adds two
    new tests parsing the real completed/rejected payload shapes above
    directly. `tests/test_download_service.py` adds: a direct
    repository-level `update_progress` non-disturbance test (mirroring
    `update_analysis`'s own guarantee, which likewise had no standing
    test before now); an in-flight-progress-updates-while-state-doesn't-
    change test; the settled-completion
    `bytes_transferred == total_bytes` edge case; the
    rejection-leaves-progress-unset (not zeroed) edge case; and a
    guardrail test (same style as the existing `input()` guardrails)
    asserting `update_progress` is never attempted for a locked,
    shortlisted, or superseded row even when a locked retry and a
    shortlist cascade activation both happen in the same run — a
    forbidden-id assertion wrapping the real repository method, not just
    a call-count check.

    **Verified live against real, currently-downloading transfers, not
    only mocked tests** (2026-08-28): the two pre-existing real `queued`
    rows in this project's actual database (day-old, from an earlier
    session) turned out to be permanently-locked files that bounce
    `queued → locked → queued` every retry without ever really
    transferring, so a fresh, genuinely downloadable pair was requested
    for real instead (`seeker download "240KM/H"` against the real
    unmatched ZENEA/Kamäleon tracks, both landing real *unlocked*
    candidates this run: `earobic`/`ZENEA - INFINITE .flac`,
    `torogod`/`Kamäleon - Quadrat.mp3`). Three successive real
    `seeker downloads status` runs captured genuine progress advancing
    through the real database:
    row 11 (ZENEA) `36,755,488 → 68,278,944 → 72,005,805` of
    `72,005,805` total; row 12 (Kamäleon)
    `4,456,448 → 5,997,594 (completed)` of `5,997,594` total — both
    finished with `bytes_transferred == total_bytes` exactly, confirming
    the completion edge case against real data, not just the documented
    API shape. Both real files were then moved and confirmed present at
    the real configured destination
    (`/Volumes/X9 Pro/Music/240KMH/ZENEA - INFINITE .flac`,
    `.../Kamäleon - Quadrat.mp3`). The earlier real rejection case was
    also captured live and unmodified by this change: the two real
    day-old `queued` rows, once finally polled, transitioned to
    `locked` with `bytes_transferred`/`total_bytes` genuinely left
    `NULL` — confirming the "rejection isn't progress" design choice
    against real production data, not a synthetic scenario.

    **Two real, honestly-reported side effects hit while doing this live
    verification, neither part of this task's own change:**
    1. Running the real CLI to observe live progress necessarily
       triggered `Application.__init__`'s startup migration from item
       19 for real, for the first time, against this machine's actual
       `.env`/config directory — `config.json` was created for real at
       `~/Library/Application Support/Seeker/`, copying the real
       `SLSKD_*` values in. Item 19 explicitly held that migration back
       pending a separate go-ahead; this task's live-verification step
       caused it to happen as an unavoidable side effect of running
       `seeker` for real at all, not a deliberate decision to run it —
       flagged here rather than left unmentioned.
    2. A genuine, pre-existing, unrelated issue surfaced during the same
       live runs: the Phase 3 locked-retry path
       (`_retry_locked_request` → `request_download` →
       `POST /api/v0/transfers/downloads/batches`) intermittently
       returned a real `404 Not Found` for the already-locked
       `NeuroFunk26\Balron, Audio - Breach.flac` retries, printed as
       `Failed to retry locked '...'` and caught by `poll_downloads`'s
       existing per-request exception handling (so it didn't abort the
       run — that guardrail did its job). `request_download` itself is
       completely unmodified by this task, so this isn't a regression
       from this change — logged here as a real observation for a
       future session to investigate, not fixed as part of this task
       (out of scope, and not requested).

21. **Fix: a real, live-discovered rejection shape (peer-offline 404)
    escaped the recognized-rejection handling at both call sites that
    depend on it — done (2026-08-28), following a dedicated diagnostic
    pass (item 20's Balron/long25 observation).**

    **Root cause, confirmed against the real API before touching any
    code.** `SoulseekClient.request_download`'s `response
    .raise_for_status()` had no try/except around it — a non-2xx
    response raised a bare `httpx.HTTPStatusError`, a type neither
    `_retry_locked_request` nor `_activate_shortlisted_entry` catches
    (`except SoulseekDownloadError` only). `SoulseekDownloadError` was
    only ever constructed later, in the 2xx-with-empty-transfers
    branch — a 404 never reaches that code at all. Confirmed live by
    replaying the exact failing enqueue request directly against the
    live instance: `POST /api/v0/transfers/downloads/batches` for the
    real Balron/`long25` case returns `404` with body `"User long25
    appears to be offline"` — a **third, distinct rejection shape**
    from the one Phase 3 was built and tested against
    (`"Transfer rejected: File not shared."`, which arrives
    asynchronously — the POST itself succeeds with a real transfer_id,
    and the rejection only shows up moments later via
    `get_download_status`/`get_download_exception`). A peer being
    briefly unreachable is a synchronous, immediate refusal at enqueue
    time instead.

    **Fixed at the source, once, not at both call sites** — same
    consolidation reasoning as `matching.py`/`AUDIO_EXTENSIONS`
    (roadmap items 2-3): `request_download` now wraps a
    `httpx.HTTPStatusError` in a try/except around the POST, inspects
    the response body (`.json()`, falling back to `.text` if the body
    isn't valid JSON) against a shared pattern list, and raises
    `SoulseekDownloadError` with the real message when it matches — so
    every current and future caller inherits correct handling from one
    place instead of needing its own audit. An unrecognized 4xx/5xx
    (auth failure, malformed request, a genuine server error)
    re-raises the original `httpx.HTTPStatusError` unchanged — this is
    deliberately not broadened past what's actually been confirmed,
    same discipline the async-side pattern list already applied.

    The pattern list itself moved down to `client.py` (below
    `download_service.py` in the layering — the same "shared thing
    lives at the lowest layer that needs it" rule the earlier
    consolidations followed) and was renamed:
    `LOCK_REJECTION_PATTERNS`/`_is_lock_rejection` →
    `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection` — the old
    name undersold what it now covers ("locked" was never really the
    concept; "a recognized, known-transient rejection reason worth
    retrying later" is). Now holds two confirmed real strings:
    `"not shared"` (2026-08-27) and `"appears to be offline"`
    (2026-08-28). `download_service.py` imports the function rather
    than keeping its own copy — `tests/test_download_service.py::
    test_single_source_of_truth_for_recognized_rejection_patterns`
    guards this directly (asserts the old names no longer exist on the
    module, and that the imported function is the exact same object as
    `client.py`'s).

    **Verified, not assumed, that both existing call sites now behave
    correctly with zero further changes needed beyond the import:**
    - `_retry_locked_request`: still just `except SoulseekDownloadError:
      return` — unchanged, and correctly so. A synchronous rejection
      (peer offline) never produces a new `transfer_id` at all, so
      there is nothing new to persist; `update_transfer_id_and_status`
      is confirmed (via a direct spy in the new test) to NOT be called
      for this row, same as before the fix — what changes is that this
      branch is now actually *reached*, instead of the exception
      escaping past it entirely. (This corrects an assumption in the
      diagnostic task's own test spec, which expected that method to
      fire here — re-reading the exact code showed it's a clean no-op
      by design, and forcing a call that doesn't belong would be wrong,
      not a fix.) The real, previously-observed symptom — a
      `"Failed to retry locked '...'"` print on every single retry
      cycle — is confirmed gone in the new test
      (`test_retry_locked_request_recognizes_real_peer_offline_rejection`)
      and live (see below).
    - `_activate_shortlisted_entry`: **this was the real bug.** Before
      the fix, an uncaught `httpx.HTTPStatusError` here would propagate
      up through `_cascade_upgrade`'s while loop into
      `poll_downloads`'s main-loop outer per-request handler (the item
      15 audit's "one bad item can't abort the batch" guardrail) —
      correctly not crashing the run, but leaving the row stuck at
      `'shortlisted'` forever, since `mark_status` is never reached on
      that escape path. This is the case the original diagnostic
      flagged as never having been exercised live (unlike the retry
      path, no real peer-offline shortlisted candidate happened to be
      sitting in the queue that day). Fixed the same way, verified with
      a dedicated new test
      (`test_cascade_activation_recognizes_peer_offline_and_locks_not_stuck`)
      built from the real captured 404 body as a fixture, since this
      path depends on a specific live peer-offline state that isn't
      reliably reproducible on demand — consistent with how Phase 4
      already handles hard-to-reproduce live scenarios (its own tests
      use real captured peer data rather than waiting for a live repro
      every time). Confirms the row now genuinely transitions to
      `'locked'` via `is_recognized_rejection`'s classification, not
      left in `'shortlisted'` and not misrouted to `'failed'`.

    Tests: `tests/test_soulseek_client.py` adds
    `test_request_download_wraps_real_peer_offline_404` (the exact real
    captured body, not a paraphrase) and a parametrized
    `test_request_download_does_not_wrap_unrecognized_error` (401, 500
    — guards against over-broad catching) using a new `FakeErrorResponse`
    helper that raises a genuine `httpx.HTTPStatusError` carrying a real
    response object, exactly like the real client sees.
    `tests/test_download_service.py` adds the two call-site tests above
    plus the single-source-of-truth guardrail.

    **Live re-verification against the real, still-reproducible
    Balron/`long25` scenario** (2026-08-28, same day, confirmed
    reproducible immediately beforehand via a direct replay of the
    exact failing request): two consecutive real `seeker downloads
    status` runs after the fix landed produced **zero** `"Failed to
    retry locked"` output — a real, visible behavior change from every
    prior run that day. All 3 real Balron rows (ids 5, 7, 9) stayed
    `'locked'` with their `transfer_id` genuinely unchanged across both
    runs, confirmed directly via `sqlite3`, not just inferred from the
    absence of an error line. The two real Jade Venom rows (ids 6, 10 —
    the unrelated async-shape "not shared" case) continued retrying and
    picking up new `transfer_id`s normally in the same runs, confirming
    the fix didn't disturb the already-working path.

22. **Frontend Step 3: UI scaffolding + main dashboard — done
    (2026-08-28).** The first real UI on top of everything built so
    far: a Qt (PySide6) desktop shell showing a playlist's tracks with
    live status, backed by the exact same service layer the CLI uses.

    **New service-layer piece — `DashboardService.get_playlist_track_status()`.**
    The dashboard's entire premise is "select a playlist, see that
    playlist's tracks with live status" — nothing in the codebase
    answered that before this (`TrackMatcher.generate_match_report()`
    reports globally across every synced playlist, per item 15's own
    correction). New `DashboardService` (top-level, alongside
    `application.py`, since it's cross-cutting — matching + downloads +
    soulseek candidates, not owned by any one existing domain), exposed
    via `Application.dashboard_service`, the same lazy-init-property
    pattern every other service uses.
    `get_playlist_track_status(playlist_name)` returns one `TrackStatus`
    (new `models/track_status.py`) per track, with exactly one
    mutually-exclusive primary state, first match wins: `IN_LIBRARY`
    (an auto track_matches row resolving to a real local file — takes
    precedence over any stale download_requests row left over from
    before the track was matched), `DOWNLOADING` (an active
    queued/downloading request, carrying real `bytes_transferred`/
    `total_bytes` from item 20 so a progress bar renders without a
    second query), `AWAITING_REVIEW` (`ready_for_review`, or an active
    `locked`/`shortlisted` row), `NEEDS_REVIEW` (a needs_review
    track_matches row with no active download activity), or
    `NOT_FOUND`. A secondary "SoulSeek candidate found" tag can only
    surface on `NEEDS_REVIEW`/`NOT_FOUND`, enforced by construction —
    the candidate lookup is only ever consulted from those two
    branches, so it's structurally impossible for a track to report
    both `IN_LIBRARY` and the tag at once, not just conventionally
    avoided. Verified the invariant against the real database before
    relying on it: zero rows currently have an auto match and a
    soulseek_review_candidates entry for the same track — item 17's
    clearing logic is working correctly on real data. New
    `DownloadRequestRepository.get_all()` (whole-table fetch, same
    pattern as `TrackMatchRepository`/`LocalFileRepository`'s own
    `get_all()`) lets the service build the playlist-scoped view in a
    handful of queries rather than one per track. 18 dedicated tests:
    one per primary state, the in-library-over-stale-request and
    downloading-over-awaiting-review precedence cases, both
    secondary-tag co-occurrence cases plus the suppressed-invariant
    case, and a two-playlists-sharing-no-tracks scoping test — the
    exact bug class item 15 already found once in the global report.

    **Package structure.** New `src/seeker/ui/` package, sibling to
    `cli.py` — both are presentation-layer callers of the service
    layer now, so the architecture rule at the top of this file was
    reworded from "CLI code" to "presentation-layer code" to actually
    say what it means. New `src/seeker/main_ui.py`, a thin bootstrap
    mirroring `main.py`'s exact existing shape (load `.env`, validate
    `SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI`, construct `Application`)
    with a `QApplication`/`MainWindow` in place of `cli.run()`. New
    `seeker-ui` console-script entry alongside `seeker` in
    `pyproject.toml` — a separate entry point rather than a `seeker ui`
    subcommand, since Qt's event-loop bootstrap doesn't fit argparse
    dispatch cleanly. Added `PySide6` as a runtime dependency and
    `pytest-qt` as a dev dependency.

    **Concurrency check — verified, not assumed, before building the
    worker pattern on top of it.** `database/connection.py`'s
    `Database.transaction()` opens a brand-new `sqlite3.connect()` per
    call and closes it when the context manager exits — never one
    long-lived shared connection — so no `sqlite3.Connection` object is
    ever used across threads (each is created and used entirely within
    the thread that opened it). Stress-tested directly rather than
    reasoning about it in the abstract: 10 writer threads + 10 reader
    threads, 50 transactions each (1,000 total), zero errors, correct
    final state, ~0.4s. Python's `sqlite3.connect()` default 5-second
    lock-acquisition timeout is what actually absorbs the write
    contention here (no explicit `busy_timeout`/WAL configured, and
    none needed for this access pattern) — confirmed empirically that
    this was already safe for the new multi-threaded UI access pattern
    the CLI never exercised. No change made to `connection.py`.

    **Background worker pattern — `ui/workers.py`.** `Worker`
    (`QRunnable` + a separate `WorkerSignals` `QObject` for
    `finished(object)`/`error(str)`, since `QRunnable` itself isn't a
    `QObject` and can't emit signals directly) plus `run_worker(pool,
    fn, button=None, status_label=None, on_finished=None)` — one
    reusable abstraction every long-running action (sync, scan, match,
    download, the dashboard's own status poll) goes through. The
    triggering button (if any) disables for the duration and
    re-enables on completion either way; an error clears to the status
    line, never a modal.

    **A real bug found and fixed in this same pass, not filed for
    later:** the first version of `run_worker` created its `Worker`
    as a local variable and returned it, with nothing else holding a
    reference. `QThreadPool.start()` schedules execution on a real OS
    thread and returns immediately — well before that thread actually
    calls `run()` — so the only Python reference to the worker (and
    its `WorkerSignals` `QObject`) went out of scope the instant
    `run_worker()` returned, long before the background thread was
    done with it. `QRunnable` isn't a `QObject`, so it can't rely on
    Qt's own parent-child ownership to survive the way a `QObject`
    could. Caught for real, not theoretically: a smoke test using
    `qtbot.waitUntil` to wait for a populated playlist list timed out
    with the worker's result silently never arriving (garbage-collected
    before `run()` executed); running the same scenario as part of the
    full smoke-test file instead produced a genuine interpreter
    segfault (a cross-thread signal emission racing a half-finalized
    object) — two different symptoms of the identical root cause,
    depending on GC timing. Fixed with an explicit `_active_workers:
    set[Worker]` registry in `workers.py`, holding a strong reference
    to every in-flight worker until its own `finished`/`error` signal
    fires and removes it — the standard, defensive pattern for this
    exact PySide6/`QThreadPool` gotcha. Re-verified stable across
    repeated runs after the fix (no flaky pass/fail), not just "passed
    once."

    **DB-polling pattern — a single `QTimer` on the dashboard**,
    `POLL_INTERVAL_MS = 2_000` (explicitly flagged as an untuned
    constant in code, matching the convention for every other
    threshold in this codebase — chosen to match the ~2s cadence
    already observed against real slskd elsewhere in this project),
    re-querying `get_playlist_track_status()` for whichever playlist is
    currently selected, routed through the same `run_worker` so a slow
    poll can never block the UI thread. First cut rebuilds the visible
    table each tick rather than diffing for minimal repaints — an
    acceptable v1 simplification, matching this project's habit of
    shipping a working real version before optimizing.

    **Main window (`ui/main_window.py`).** Sidebar populated from
    `sync_service.list_playlists()` — the identical call `seeker
    playlists` already uses. Toolbar actions kept honest to what the
    CLI already established rather than implied broader by placement:
    Sync/Scan/Match are labeled "Sync all playlists"/"Scan all
    locations"/"Match all tracks" (global, same scope as the CLI —
    selecting a playlist in the sidebar must not imply these narrow to
    it); only Download is playlist-scoped, matching `seeker download
    <playlist>` exactly. Deliberately does **not** auto-trigger
    `sync-tracks` on playlist selection — track syncing was
    deliberately split out from playlist syncing specifically to keep
    Spotify API calls scoped and intentional (roadmap item 1); an
    auto-fetch on every sidebar click would silently reintroduce the
    exact unscoped-quota-burning behavior that split was meant to
    prevent. A playlist with zero cached tracks shows an explicit empty
    state and a "Sync tracks" button instead.

    **UI-layer testing kept proportionate, per this project's own
    established philosophy** (`cli.py`/`main.py`'s argparse dispatch is
    deliberately untested beyond the service layer it wraps, since it's
    thin by design) — `tests/test_ui_smoke.py` confirms the window
    constructs, the playlist list populates from a fake service, the
    empty-state/"Sync tracks" prompt shows correctly with zero
    auto-fetch, and `Worker`/`run_worker`'s signals and button
    disable/re-enable/error-to-status-line behavior fire correctly —
    not deep Qt coverage for what is, by design, thin glue around
    already-tested services — `DashboardService` (above) is where the
    real logic depth lives.

    **Verified live against the real application, not only fakes or
    mocked tests:** launched the real `MainWindow` against the real
    `Application` (real client ID, real cached Spotify token) — the
    background worker refreshed the real expired token without
    blocking the UI thread, and all 215 real playlists loaded into the
    sidebar. Selecting the real "Test" playlist and letting the poll
    timer run rendered all 10 real tracks with genuinely correct,
    live-matching status: the 6 real auto-matched tracks as "In
    library"; Prdk and Zigi SC/A-Cray as "Not found (SoulSeek candidate
    found)", matching item 17's real needs-review candidates exactly;
    Balron/Audio as "Awaiting review" (its real `locked` status at the
    time); Jade Venom as "Downloading" — a real, live status change
    from the `locked` state it was in earlier in this same session,
    confirming the dashboard reflects genuinely current DB state, not
    a stale snapshot.

23. **Frontend Step 4: onboarding wizard — done (2026-08-28).** Three
    steps (Spotify connect, library location, SoulSeek/Docker setup —
    the last skippable), resumable across restarts, landing in the
    dashboard once the two required steps are done.

    **Prerequisite fix (item landed as its own commit first, verified
    in isolation before any wizard UI was built on top of it):**
    `config.py` enforced `SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI` at
    import time — a wizard whose entire job is collecting that value
    can't function if importing the module that leads to it crashes
    first. Removed the import-time raise; `Application` no longer takes
    these as constructor args at all — they're resolved the identical
    store-value-or-env-fallback way `SLSKD_*` already was
    (`config_store.py`'s `SeekerConfig` gained `spotify_client_id`/
    `spotify_redirect_uri`; the migration function is renamed
    `migrate_legacy_env_config`, since its scope is no longer
    SLSKD-only — the same one extended, not a second mechanism).
    `auth_manager` became a lazy property, raising only when actually
    touched. `redirect_uri` falls back to a real, fixed,
    app-controlled default rather than free text —
    `callback_server.py` now exports `CALLBACK_PORT`/
    `DEFAULT_REDIRECT_URI` as the one source of truth both the server
    and this default read from, so they can never drift apart. Verified
    with a real subprocess-based test (not just unit-level): a
    genuinely clean environment (no `.env` — sidestepping
    `load_dotenv()`'s walk-up-from-the-module's-own-file-location
    search required setting the `SPOTIFY_*`/`SLSKD_*` keys to empty
    strings beforehand, confirmed empirically that `override=False`
    leaves an already-present-but-empty var alone) imports every module
    the wizard needs and constructs `Application()` without error, with
    `auth_manager` raising only when actually accessed — confirmed this
    test genuinely catches the original bug by temporarily restoring
    the old import-time raise and watching it fail first.

    **Real ambiguity investigated and resolved before writing any
    wizard code, not assumed from docs** — slskd's own `--envars`
    output, read directly off the real running binary, is the actual
    source of truth:
    - `SLSKD_USERNAME`/`SLSKD_PASSWORD` → the **web UI** login
      (`--help` says so explicitly: "username/password for web UI",
      default `slskd`/`slskd`) — NOT what the wizard's SoulSeek
      credential fields should map to.
    - `SLSKD_SLSK_USERNAME`/`SLSKD_SLSK_PASSWORD` → the **SoulSeek
      network** login — confirmed live: a throwaway container
      (isolated ports/volume, never touching the real running
      instance) started with these two produced a real
      `"Logged in to the Soulseek server as seekerapp"`. Two
      plausible-looking wrong guesses were tested first and both
      failed with `"Not connecting to the Soulseek server; username
      and/or password invalid"`: `SLSKD_SOULSEEK_USERNAME`/`PASSWORD`
      (doesn't exist at all) and bare `SLSKD_USERNAME`/`PASSWORD`
      (that's the web UI, confirmed above). Locked in as
      `docker_setup.py`'s `SLSKD_NETWORK_USERNAME_ENV_VAR`/
      `SLSKD_NETWORK_PASSWORD_ENV_VAR`, with a regression test pinned
      to these exact confirmed strings.
    - **A second real risk, checked before templating
      `docker-compose.yml`:** does an env var passed as an *empty
      string* (as `${VAR}` substitution produces when unset) clobber
      an already-persisted real credential in `slskd-data/slskd.yml`,
      or does slskd correctly fall through to the yaml value? Verified
      against a real container with a real persisted credential
      (`realpersisted`/a real password) and `SLSKD_SLSK_USERNAME=`
      (present, empty) set: the container logged in as
      `realpersisted` — slskd falls through, empty does **not**
      clobber. This is what makes plain `${VAR}` substitution in the
      tracked compose file safe for a manual `docker compose up`
      without the wizard's env vars — confirmed, not assumed, before
      relying on it for a file that governs this project's own real,
      currently-running production container.

    **`docker-compose.yml` templated accordingly:**
    `SLSKD_SLSK_USERNAME`/`SLSKD_SLSK_PASSWORD`/`SLSKD_API_KEY` as bare
    `${VAR}` substitutions (no default — safe to leave unset per the
    finding above); `SLSKD_DATA_DIR`/`SLSKD_SHARE_PATH` default to this
    repo's existing real values (`./slskd-data`, the real
    `/Volumes/X9 Pro/Music` path already hardcoded there) so a manual
    `docker compose up` with no wizard involved behaves exactly as
    before. No real secret was ever added to the tracked file as a
    fallback default — the real SoulSeek password/API key live only in
    the already-gitignored `slskd-data/slskd.yml`, confirmed never
    committed. `docker_setup.py::bring_up_slskd` passes the collected
    credentials/API key/paths directly as the `docker compose up`
    subprocess's environment — no second, compose-specific env file,
    per the explicit ask (same discipline Task 1 already established
    for `.env`).

    **The other real ambiguity, checked live before building the
    health-poll UI:** does `/api/v0/application`'s (or the dedicated
    `/api/v0/server`'s) `state` field distinguish "still negotiating"
    from "rejected — bad credentials"? Checked the real swagger schema
    for `ServerState` directly: it carries only
    `state`/`isConnected`/`isLoggedIn`/`isTransitioning` — no
    error/reason field at all. Confirmed live with two real scenarios
    that both converge on the identical terminal `state:
    "Disconnected"`: a genuine bad-password rejection, and an unrelated
    "kicked, another client already logged in with this username" case
    (hit by accident testing the real account while the production
    container was also connected). The real reason only ever shows up
    via `/api/v0/logs`' `Error`-level entries — confirmed live for a
    deliberately wrong password:
    `"Disconnected from the Soulseek server: invalid username or
    password"` / `"...The server rejected login attempt: INVALIDPASS"`.
    `docker_setup.py::check_slskd_health` polls `/api/v0/application`
    for the real, confirmed success state (`"Connected, LoggedIn"`,
    re-confirmed live against the actual running production instance)
    and, when not yet healthy, checks `/api/v0/logs` for the confirmed
    bad-credential substrings — matched case-insensitively, same
    discipline as `RECOGNIZED_REJECTION_PATTERNS` elsewhere in this
    codebase, not broadened past what's actually been confirmed.
    Deliberately a single-shot check, not a blocking poll loop with
    `time.sleep` — the wizard's own `QTimer` calls it repeatedly (same
    pattern as the dashboard's live-status poll from Step 3), tracking
    elapsed wall-clock time itself for the 60s timeout (explicitly
    flagged as an untuned constant, same convention as every other
    threshold here).

    **Resumability — a real tension in the brief, resolved
    deliberately, not left implicit.** The brief's literal completeness
    definition ("Spotify configured + at least one library location
    exists") only covers the two *required* steps, and
    `Application.onboarding_complete` implements exactly that — once
    true, `main_ui.py` always routes straight to the dashboard on a
    fresh launch, never back into the wizard, even if step 3 was never
    touched. This is in genuine tension with the brief's own
    "a `docker compose up` that succeeded in a prior session shouldn't
    need repeating" rationale, which only makes sense if the wizard
    *can* still reopen at step 3. Resolved without adding a second
    "step 3 resolved" flag to the config store: step 3, whenever it
    *is* shown (every session until steps 1+2 are both done — step 3 is
    only ever reached in the same session as completing step 2, per the
    brief's fixed 1→2→3 ordering), always re-checks Docker's real state
    live on entry rather than assuming anything — so a prior successful
    `docker compose up` is reflected immediately (verified directly:
    `test_wizard_soulseek_step_checks_real_docker_state_on_entry`)
    without ever being blindly repeated. `OnboardingWizard._initial_step()`
    only ever needs to choose between step 1 and step 2 in practice,
    since `onboarding_complete` being false is what got the wizard
    shown at all.

    Reused the Step 3 worker abstraction for every long-running
    action — OAuth wait, `docker compose up`, Docker detection, each
    health-check tick — no second threading pattern.

    **A real cosmetic bug caught and fixed in the same pass:** the
    Docker-state-button's re-wiring (`NOT_INSTALLED` → download link,
    `INSTALLED_NOT_RUNNING` → launch/check-again, `RUNNING` → hidden)
    blindly called `.disconnect()` before reconnecting, which prints a
    real `libpyside` `RuntimeWarning` (not a raised exception, so a
    bare `try/except` around it did nothing) the first time the button
    had no existing connection. Fixed with an explicit
    `_docker_action_connected` flag instead of a swallowed exception.

    Tests: `tests/test_docker_setup.py` covers the three Docker-state
    subprocess outcomes (mocked), the credential-mapping regression
    (locks in the confirmed real env var names), API key length, and
    `check_slskd_health`'s three classifications including the
    kicked-vs-bad-credentials disambiguation case using the real
    captured log text. `tests/test_wizard.py` covers all three
    resumability starting points (fresh / Spotify-done / Spotify+
    library-done → step 3), the live Docker re-check on step-3 entry,
    and the skip path. Kept proportionate to this project's UI-testing
    philosophy, same as Step 3's dashboard smoke tests — the service
    layer (`docker_setup.py`) carries the real logic depth and gets
    real coverage; the Qt wiring stays thin and lightly checked.

    **Verified live against the real application, not only mocked
    tests:** constructed the real `Application()` (real Spotify config,
    real library location already registered from earlier sessions) —
    `onboarding_complete` correctly read `True`, and constructing
    `OnboardingWizard` directly against it landed on step 3 exactly as
    designed, with a real (non-mocked) Docker-state check running
    against this machine's actual Docker installation without error.
    This run also triggered the real `.env`→config-store migration for
    the two new Spotify fields for the first time (the first real
    command run against this machine since the prerequisite fix
    landed) — confirmed the real `config.json` now correctly holds the
    real `spotify_client_id`/`spotify_redirect_uri` matching `.env`
    exactly, same expected one-time side effect as item 19's SLSKD
    migration.

    **Real gap found and fixed in a follow-up pass, prompted by a
    direct question rather than caught the first time through:** the
    original `check_slskd_health` scanned the *entire* `/api/v0/logs`
    buffer on every poll with no time bound at all — a stale `Error`
    entry from an earlier attempt (e.g. a mistyped password the user
    already corrected and retried) would have false-positived every
    later poll as `BAD_CREDENTIALS` forever, even after a real
    successful reconnect. Fixed by threading a real `since: datetime`
    timestamp through — the wizard captures it once, right when the
    health-poll sequence starts for that specific bring-up attempt —
    and filtering out any `Error` entry timestamped before it (an
    entry with an unparseable timestamp is skipped too, not trusted
    either way). Verified this fix is real, not just plausible-looking:
    a new test seeds a stale bad-credential entry before `since` and
    asserts `NOT_READY`, and — same discipline as every other
    regression test in this session — confirmed it actually fails
    without the fix by reverting it and watching the assertion break,
    then restoring.

    Also directly asked and checked, before this became "the thing a
    future slskd upgrade quietly breaks": is the bad-credentials match
    scoped to log *level* rather than message-text substring? Only
    half — `level == "Error"` is a real structured field and genuinely
    not fragile, but discriminating *which* error happened still
    relies on substring-matching the two confirmed real message
    strings, because a live-captured entry's full shape
    (`timestamp`/`context`/`level`/`message`) has no structured
    error-code field — `context` is real (`"slskd.Application"`) but
    too coarse to narrow anything beyond `level`. This is genuinely the
    most specific signal available today, not a shortcut taken over a
    better one — but it's real, honest fragility against a future
    slskd wording change, documented directly in
    `BAD_CREDENTIALS_LOG_PATTERNS`'s own comment as something worth
    re-checking against a real container after any slskd upgrade,
    rather than left implicit.

    **Also directly confirmed, since it was the reassurance asked
    for:** applying the templated `docker-compose.yml` to this
    machine's real setup does *not* happen automatically. Checked
    `docker inspect`'s real `Created` timestamp (predates the file
    edit) and `docker compose ps` (still the same 28-hours-old
    container instance) — editing the file, and even running
    Compose's own read-only `config`/`ps` commands, never recreates a
    running container; only an explicit `docker compose up` does, and
    the only code path that ever calls one (`_on_bring_up_clicked`) is
    gated behind the wizard's step 3, which is gated behind
    `onboarding_complete` being `False` — already `True` for this real
    setup, so `seeker-ui` never reaches it without deliberately
    resetting onboarding state first.

Keep this file updated as decisions get made — treat it as the standing
brief, not a changelog of everything that happened.
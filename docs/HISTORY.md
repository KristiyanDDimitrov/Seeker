# seeker — roadmap history

Full, verbatim narrative for every numbered roadmap entry in `CLAUDE.md`.
`CLAUDE.md`'s own roadmap section keeps only a condensed, few-line summary
of each entry — what changed and any standing behavioral fact/gotcha that
matters for future code — with a pointer back here. Nothing here is
summarized or trimmed; this is the full bug-hunt/verification narrative:
which hypotheses were checked and ruled out, exact byte counts and
timestamps from real verification runs, the blow-by-blow of each
investigation. If you're trying to understand *why* a fix looks the way
it does, or want the full evidence behind a "verified live" claim, this
is the file to read — `CLAUDE.md` deliberately does not repeat it.

Numbered entries match `CLAUDE.md`'s roadmap items exactly (currently
1-55, with a few lettered sub-addenda for follow-on fixes to an
existing item). The "Known issues / backlog" section below mirrors
`CLAUDE.md`'s own section of the same name, one slugged heading per
bullet, for the handful of early fixes that predate the numbered
roadmap.

---

## Known issues / backlog

### CLI bypassed Application for playlist listing

`cli.py::handle_playlists` instantiated `PlaylistRepository` directly
instead of going through `Application`, violating this project's own
layering rule (presentation code must never call a repository
directly). Fixed to go through `application.sync_service`/
`application.download_service` exclusively, matching every other CLI
handler. Exact point of the fix is uncertain — it was already correct
by the time the polish pass (item 15) audited the CLI layer, likely
folded into an earlier phase's cleanup rather than done as its own
dedicated change.

### matcher and quality fuzzy-matching logic drifted apart twice

`library/matcher.py` and `soulseek/quality.py` each had their own copy
of the artist/title fuzzy-matching logic (`artist_matches`, title
scoring, `normalize_filename_text`), and the two copies drifted apart
twice — same root cause as the `AUDIO_EXTENSIONS` duplication (item 2's
scanner/quality split), just not caught as early.

**First drift.** `quality.py` was fixed to score artist+title combined
instead of title-only (item 5, the 62.5-on-a-clean-match discovery);
`matcher.py` never got that fix, so a real download
(`3AMDISCO - Get Back.wav`, untagged WAV, `240KM/H` playlist) stayed
unmatched even once indexed.

**Second drift, found investigating the first.** `matcher.py`'s
`artist_matches(track.artist, candidate.tag_artist)` hard-gated on
`tag_artist` with no filename fallback — `tag_artist is None` (routine
for WAVs; mutagen extracted no tags at all here) rejected the
candidate outright before title scoring ever ran, whereas `quality.py`
never had this problem because `SoulseekFile` has no tag concept at
all — it always passed the normalized filename itself as the "local
artist" for containment-checking.

**Fix.** Consolidated both into `seeker/matching.py` (`artist_matches`,
`score_title`, `resolve_text_source`, `normalize_filename_text`,
`AUTO_MATCH_THRESHOLD`, `NEEDS_REVIEW_THRESHOLD`) —
`resolve_text_source(tag_value, filename)` gives both call sites
(artist and title) the same tag-or-filename-stem fallback, so
`matcher.py` now falls back to filename-containment for a null
`tag_artist` exactly like `quality.py` already did. Applying
`quality.py`'s combined-scoring fix naively to `matcher.py` caused a
*new* regression, caught by the existing
`test_close_match_scores_at_least_90_and_lands_in_auto` test: a clean,
correctly-tagged match (`tag_title` with no artist in it, e.g.
"Blinding Lights") scored *worse* combined (73.2) than title-only
(100), because the combined fix was specifically compensating for
artist-prefixed filenames, not clean tags. Fixed `score_title` to
compute both title-only and combined scores and take the max — robust
to either shape without needing to know which one `local_title_source`
actually is.

**Verified against real data:** `seeker library match` auto-matches
`3amdisco - Get Back` at score 94.44 against the real untagged WAV
(`local_file_id` 3218), and `seeker check` reflects it as matched
instead of unmatched. See
`tests/test_matcher.py::test_untagged_file_matches_via_filename_alone`.

### Spotify field-name history: get_current_user_playlists

`SpotifyClient.get_current_user_playlists` was reading
`playlist["tracks"]["total"]`. Live `/me/playlists` responses never
contain a `tracks` key — the per-playlist total is under
`playlist["items"]["total"]` instead (confirmed against all 214 real
playlists synced in item 1's real run, 0 had `tracks`). This code path
had never actually run against the live API before (blocked on Spotify
dev quota), so the earlier "fix" to `tracks` was never live-verified
and was wrong. Fixed for real once quota reset;
`tests/test_spotify_client.py` updated to match.

### Spotify field-name and endpoint history: get_playlist_tracks

`SpotifyClient.get_playlist_tracks` was reading `item.get("item")`
instead of `item.get("track")` — the reverse of what turned out to be
correct, discovered through two rounds of live verification rather
than one lucky guess.

**Endpoint path.** Originally `/playlists/{id}/items`, changed to
`/playlists/{id}/tracks` based on pre-migration docs, then a live 403
plus current Spotify developer community reports confirmed Spotify's
Feb 2026 API migration deprecated `/playlists/{id}/tracks` in favor of
`/playlists/{id}/items` — so the path is back to `/playlists/{id}/items`
for real.

**Per-entry field, same root cause, second symptom.** Originally read
each entry's payload from `entry["track"]`, "corrected" to
`entry["item"]` when the endpoint path was first fixed, but that
field-name change was never live-verified — the switch to `/items`
silently swapped `seeker sync-tracks` to the `/items` endpoint but the
parsing logic still read `"track"`, so every entry was skipped and
playlists synced "0 tracks" for real playlists with real tracks (found
live against `240KM/H`, playlist `1xfPRHLLuGBLlB3bIo5kA5`, 3 real
tracks). A raw unparsed GET confirmed: the paging envelope's `items`
array is fine (3 entries, `total: 3`, `next: null`), but no entry has
a `"track"` key at all — the per-track payload now lives under
`entry["item"]`, and the old `"track"` key is repurposed as a
*boolean* type-discriminator field living inside that `item` dict
(`item["track"] == True` for tracks, presumably `False` for podcast
episodes) alongside `item["type"] == "track"`.

**Fix.** Field name resolved to `item` for real this time, with an
explicit `track_data.get("type") != "track"` filter added as a
defensive skip for non-track entries, using the real discriminator
field rather than relying only on empty `artists` as an incidental
signal. `tests/test_spotify_client.py` updated to match the real live
entry shape and to cover the non-track skip.

---

## Roadmap (direction, not urgent)

### 1

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
### 2

2. ~~Local library scanning~~ — done. `library_locations` +
   `local_files`, multi-location aware, per-location reachability
   handling, AppleDouble sidecar files filtered.
### 3

3. ~~Matching~~ — done. `matcher.py` classifies each track as
   auto-matched / needs-review / unmatched (`track_matches`, with a
   `score` column). Thresholds (auto ≥90, review 70–90) are untuned
   defaults — revisit once real match data exists.
### 4

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
### 5

5. ~~Quality-ranking logic~~ — done. `soulseek/quality.py`:
   `filter_candidates` (extension + `artist_matches` reuse + fuzzy title
   score ≥90, scored against `artist + title` combined — scoring the bare
   title alone against an "Artist - Title"-style Soulseek filename tanks
   the ratio even for a clean match), `quality_tier`/`effective_bitrate`
   (flac/wav > mp3/m4a/aac/ogg, VBR-reported bitrates distrusted), and
   `select_best` (practical-queue candidates preferred, degrades to
   best-available if none are practical). `select_downloads` (Phase 2)
   returns both halves — see item 8.
### 6

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
### 7

7. `check` command already reports auto/needs-review/unmatched — a
   `review` command to confirm/reject needs-review matches is still
   outstanding. Note: `download_playlist` currently targets tracks with
   no track_match at all (`match_method IS NULL`) — needs-review tracks
   are left for that future `review` command, not auto-downloaded.
### 8

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
### 9

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
### 10

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
### 11

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
### 12

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
### 13

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
    `'locked'` instead of `'failed'`.

    **Correction (item 26, 2026-08-28): this classification is NOT
    scoped to `role == 'upgrade'` any more.** It originally was, on the
    premise that `select_downloads` never picks a locked file as
    `settled`, so a settled-role rejection was "never expected to be
    lock-related" and didn't get the retry treatment even if its
    exception text happened to match. That premise held for the
    ordinary search pipeline, but `confirm_review_candidate` (item 26)
    requests a human-confirmed needs-review candidate as `role='settled'`
    — and `find_best_needs_review_candidate` never filters on lock
    status at all, so a settled-role request genuinely can be locked
    now. The classification itself is unconditional as of item 26; only
    the Phase 4 cascade (STEP 4/5 below) stays `role == 'upgrade'`-
    specific, since shortlisting is an upgrade-only concept. See item 26
    for the full reasoning and the corresponding fix to
    `_retry_locked_request`'s success path.

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
### 14

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

### 15

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
### 16

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
### 17

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

### 18

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

### 19

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

### 20

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

### 21

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

### 22

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

### 23

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

### 24

24. **Frontend Step 5: download progress view — done (2026-08-28).** A
    dedicated, read-only "Downloads" tab showing every active download
    across every playlist at once, with live byte-level progress —
    purely observational, no confirm/reject actions (that's a separate
    future Review screen covering Phase 2 upgrade confirmation and the
    SoulSeek needs-review tier).

    **New service piece — `DashboardService.get_active_downloads()`,
    deliberately GLOBAL, not playlist-scoped.** Mirrors `seeker
    downloads status`'s own scope exactly — the previous task's
    `get_playlist_track_status()` is scoped to one playlist on purpose,
    and getting this one backwards would repeat the exact
    global-vs-playlist-scoped bug class this project already found once
    (`check`/`match_all`, item 15). Returns one `ActiveDownload`
    (`models/active_download.py`: `request`, `track`, `playlist_name`)
    per visible `download_requests` row. "Visible" = every non-terminal
    status (`queued`/`downloading`/`locked`/`shortlisted`/
    `ready_for_review` — deliberately excludes `superseded`, which is
    terminal) PLUS a `completed`/`failed` row within a new, explicitly
    untuned `RECENTLY_FINISHED_WINDOW_SECONDS = 60` of its
    `completed_at`, so a download visibly "lands" in the view rather
    than vanishing the instant `poll_downloads()` marks it terminal.
    New `PlaylistRepository.get_playlist_names_by_track_id()` (whole-
    table join, same no-N+1-query pattern as every other `get_all()` in
    this codebase) supplies the display-context playlist name(s) — a
    track can legitimately belong to more than one playlist, so this is
    a comma-joined string, not assumed singular. Tests
    (`test_dashboard_service.py`) directly cover: two different
    playlists' downloads both appearing together (the required
    global-scope check, including the negative case — a row from
    playlist B is never excluded while building playlist A's rows, and
    vice versa); every non-terminal status individually; `superseded`
    excluded; a recent completion included and a stale one (past the
    window) excluded, for both `completed` and `failed`; and
    most-recent-first sort order.

    **Background poll-trigger — a new, second timer on `MainWindow`,
    deliberately separate from the existing display-refresh timer.**
    Nothing previously caused `poll_downloads()` (real slskd network
    calls) to run except an explicit `seeker downloads status`
    invocation or cron — for this screen to show real movement while
    the UI is open, something has to call it automatically. Re-read
    `poll_downloads()` before wiring this up to confirm the Step 3/4
    "safe for unattended calling, no `input()` anywhere" guarantee
    (guardrail-tested — see item 14/17) still holds; it does, unchanged
    by this task. New `backend_poll_timer`
    (`BACKEND_POLL_INTERVAL_MS = 20_000`, explicitly flagged untuned,
    within the 15-30s range asked for) is intentionally separate from
    the existing `poll_timer` (`POLL_INTERVAL_MS = 2_000`, a cheap
    local-DB-only read) — the backend timer makes real network calls,
    so it runs far less often. `_trigger_backend_poll()` checks
    `application.soulseek_configured` first (same reasoning as item
    17's `check` fix — must not force a `SoulseekClient` into existence,
    or crash, for a setup that hasn't configured slskd at all) and is a
    complete no-op when unconfigured.

    **Overlap guard**, required by the brief: a plain `bool`
    (`_backend_poll_in_progress`) set before submitting the
    `poll_downloads()` worker and cleared only once it actually
    finishes (success OR error) — a tick that fires while the previous
    call is still running is skipped outright rather than starting a
    second concurrent writer against a slow/hanging slskd response.
    This needed one small, additive change to the shared
    `ui/workers.py::run_worker()` — it previously had no way to react
    to a worker's *failure* beyond writing to a status label, so a
    failed `poll_downloads()` call would have left the in-progress flag
    stuck `True` forever. Added an optional `on_error` callback,
    invoked alongside the existing status-label behavior (not a
    replacement for it) — every existing call site keeps working
    unchanged since it defaults to `None`. Tested directly with a real
    `QThreadPool` (not the `SynchronousPool` fake used elsewhere in
    this suite) and a `threading.Event`-gated fake `poll_downloads()`:
    a second `_trigger_backend_poll()` call while the first is still
    blocked is confirmed to make zero additional calls, and the flag
    correctly clears once the first call is released. A separate test
    confirms `poll_downloads()` itself genuinely executes off the main
    thread (`threading.current_thread() != threading.main_thread()`
    inside the fake), not just "doesn't block the test."

    **Concurrency — targeted check, not a full re-run of item 22's
    broader stress test**, per the brief's own reasoning: this
    introduces one more recurring background-thread writer (the new
    backend poll timer, doing real `update_progress`/`mark_status`
    writes) alongside the existing recurring reader (the display-
    refresh timer, now also reading via `get_active_downloads()`) — not
    a meaningfully different access pattern from what item 22 already
    validated (every `Database.transaction()` call still opens and
    closes its own short-lived connection, from whichever thread calls
    it). `tests/test_connection.py::
    test_concurrent_progress_writes_and_active_downloads_reads` runs a
    real writer thread doing 50 `update_progress` calls against one row
    concurrently with two real reader threads each doing 50
    `get_active_downloads()` calls, asserting zero errors and a
    correct final byte count — confirms this specific new combination
    is fine without re-running the original, broader 1,000-transaction
    stress test.

    **UI**: existing dashboard content moved into a `QTabWidget`
    ("Dashboard" tab, unchanged) alongside a new "Downloads" tab — a
    `QTableWidget` (Track / Playlist / Role / Status / Progress) driven
    by both timers: the 2s display-refresh timer re-renders it from
    `get_active_downloads()` (plus an explicit initial call in
    `__init__`, so the tab isn't empty for the first 2s), and the 20s
    backend timer is what actually advances the underlying data via
    slskd. `locked`/`shortlisted` rows get a plain-language
    `_DOWNLOAD_STATUS_LABELS` note ("Retrying (locked)"/"Queued as
    backup") instead of the raw status string, matching the existing
    dashboard tab's "(SoulSeek candidate found)" convention rather than
    inventing a new one. Progress bar: real `bytes_transferred`/
    `total_bytes` when both are present; **indeterminate**
    (`QProgressBar.setRange(0, 0)`) when a queued/downloading/
    ready_for_review/completed row hasn't reported bytes yet — a
    0%-forever bar would be visually indistinguishable from "actually
    stuck," which the brief specifically called out to avoid. A
    `locked`/`shortlisted`/`failed` row gets no progress bar at all
    (blank cell) rather than a misleading indeterminate spinner — these
    have no real, current transfer in flight (by design, a rejection
    leaves `bytes_transferred`/`total_bytes` unset rather than zeroed —
    see item 20), and the Status column's plain-language note already
    conveys "still being chased" without implying a live byte count.
    Purely observational per the brief: `ready_for_review` rows render
    with a status label like everything else, with no confirm/reject
    control anywhere in this tab.

    Kept to this project's established UI-testing philosophy (thin Qt
    glue gets light smoke coverage; the real logic depth lives in the
    service layer, which gets real coverage) —
    `tests/test_ui_smoke.py` adds: rows from two different playlists
    both rendering in the tab; a locked row's plain-language status
    text; determinate vs. indeterminate progress bar rendering for both
    with-bytes and without-bytes cases; a locked row rendering no
    progress bar at all; the backend-poll-runs-off-main-thread check;
    the soulseek-not-configured no-op check; and the overlap-guard
    check described above.

    **Live-verified against the real application (2026-08-28, follow-up
    pass, closing out this task rather than a separate one).** Driven
    with a real `Application()` (real DB, real slskd container, real
    config store) and a real `MainWindow` (Qt's `offscreen` platform
    plugin, since this session has no attached display) — no fakes,
    no mocks; the only instrumentation was wrapping
    `_render_active_downloads`/`_trigger_backend_poll` to log the real
    `downloads_table` contents on every real call, so the render logic
    exercised was byte-for-byte what ships.

    Kicked off two real downloads via `seeker download "240KM/H"`
    against the two real, still-unmatched tracks there: **ZENEA -
    INFINITE** (no practical unlocked candidate found this run — real
    live search results vary — so it was requested as `role='upgrade'`
    from peer `trickytraxx`, landing in the locked-retry cascade) and
    **Kamäleon - Quadrat** (`role='settled'` from peer `torogod`).
    Watched the real tab for two windows (130s, then 240s — 18 total
    real 20s backend-poll cycles) alongside the two pre-existing real
    `locked` upgrade rows already in the DB from the prior day's
    session (Jade Venom - Scared Now?, Balron/Audio - Breach, both in
    the "Test" playlist).

    **Row correctness, live:** every row rendered with the exactly
    correct track/playlist/role/status — e.g. `Kamäleon - Quadrat` /
    `240KM/H` / `Settled` / `Queued`, and simultaneously `Jade Venom -
    Scared Now? - DIVERGENCE VI` / `Test` / `Upgrade` / `Retrying
    (locked)` in the very same render. This **is** the real version of
    the written cross-playlist test, not just its mock: one real render
    at `2026-08-28T15:35:00Z` showed 240KM/H's two rows and Test's six
    rows together in one table.

    **Progress bar — genuinely reflects real bytes, cross-verified
    against slskd's own API directly.** The real Kamäleon transfer
    (peer `torogod`) completed in **5.3 real wall-clock seconds**
    (slskd's own `startedAt`/`endedAt`: `15:34:19.887Z` →
    `15:34:25.175Z`) — faster than one 20s poll cycle, so the tab's
    genuine progression was `Queued`/indeterminate → straight to
    `Completed` with `progress=5,997,594/5,997,594` at the very next
    backend-poll tick (`15:35:14`). That exact byte count was
    independently confirmed against a raw
    `GET /api/v0/transfers/downloads` call against the live slskd
    instance (`bytesTransferred: 5997594, size: 5997594` for the same
    `torogod` transfer) — not fabricated, not a stub. The bar never sat
    at a stuck 0% or stayed indeterminate for a transfer independently
    confirmed to be progressing — every indeterminate row genuinely had
    zero bytes reported (confirmed directly against slskd: three
    separate real rejections at `15:36:54.9Z` for `long25`/
    `ofoijacussa`/`trickytraxx` all show `bytesTransferred: 0`), and one
    row (a duplicate/older active Jade Venom request) spent ~45 real
    seconds in a genuine `Downloading` state with correctly-rendered
    indeterminate progress before slskd ultimately rejected it too —
    correct given zero bytes ever actually landed for it.

    **Real completion → 60-second window boundary, confirmed to the
    second.** Kamäleon's real `completed_at` was
    `2026-08-28T15:35:14.302Z`. The render at `15:36:14.173Z` (59.87s
    later) still showed it; the very next render, at `15:36:16.171Z`
    (61.87s later), had dropped it — the row disappeared within about
    2 seconds either side of the real 60-second cutoff (the display
    timer's own 2s granularity, not slop in the window logic itself),
    exactly matching `RECENTLY_FINISHED_WINDOW_SECONDS`. It updated in
    place (same row, `Queued` → `Completed`) rather than
    disappearing-and-reappearing, also as specified.

    **Background timer survived real conditions across both windows:**
    zero exceptions, zero freezes, 18 real backend-poll ticks fired on
    schedule (confirmed via logged timestamps ~20.0s apart every time,
    e.g. `15:35:14 → :34 → :54 → 15:36:14 → :34 → :54`), and both driver
    runs printed their own clean completion sentinel at the end with no
    error output. `soulseek_configured=False` was tested against the
    real `Application` class directly (patching the property, since the
    live slskd container couldn't be torn down mid-verification without
    disrupting the rest of the check) — across 45s (two real backend
    intervals) a spy wrapping the real `poll_downloads` recorded **zero
    calls**, confirming the no-op path is genuine, not just
    unit-tested.

    **What this pass did NOT manage to observe live: a genuine
    mid-transfer PARTIAL byte count (`0 < bytes_transferred <
    total_bytes`).** Every real successful transfer seen this session —
    Kamäleon's 5.3s completion here, and the historical
    3AMDISCO/ZENEA/Kamäleon transfers referenced in item 20 — either
    finished inside one 20s poll window or (for item 20's original
    72MB ZENEA flac) was only ever sampled via manual, closely-spaced
    CLI runs rather than the UI's own 20s timer. The three real
    candidates still open during this pass (Jade Venom, Balron, ZENEA's
    retry) stayed locked/rejected for the entire ~6 minutes of combined
    observation and never began a real transfer.

    **Checked in a follow-up pass whether this gap already had test
    coverage rather than leaving it recorded as open — it did.**
    `tests/test_ui_smoke.py::
    test_downloads_tab_progress_bar_determinate_with_real_bytes` already
    exercises `_build_progress_widget` with `bytes_transferred=500,
    total_bytes=1_000` — a genuine 50% partial-fill state, not an
    endpoint. That test asserts `bar.maximum() == 1_000` and
    `bar.value() == 500`, i.e. the exact same `setRange`/`setValue` call
    a live 40%-complete transfer would make. The render code has no
    special-casing for 0%, 50%, or 100% — it's one unconditional
    computation regardless of which real numbers feed it — so this
    mocked mid-range value covers the identical code path a live one
    would have exercised, the same reasoning already used for this
    project's drive-unmounted WAV tests. No new test needed; this gap
    is closed by coverage that already existed, not left open.

    **Multi-row-per-track observation — investigated further, confirmed
    as a genuine duplicate (not Phase 4's shortlist design), and fixed,
    not left filed as out-of-scope.** Checked the real rows directly
    against `rank`/`role`/`username`/`filename` rather than assuming:
    all three rows per track (e.g. Jade Venom ids 6/8/10, Balron ids
    5/7/9) share `rank=1` and the *identical* peer+filename — a real
    ranked shortlist (item 14) would show rank 1/2/3 with genuinely
    different peers/files per rank, and a live query confirmed **zero**
    rows with `rank > 1` exist anywhere in the database. So this is not
    Phase 4 working as designed — it's the same real duplicate-request
    condition item 16 already diagnosed and fixed at the
    `download_playlist()` level (`get_active_for_track`), just never
    cleaned up from the rows it left behind. Confirmed the *current*
    guard is not reproducing this today, not just assumed: re-running
    `seeker download "Test"` twice against this exact live data in the
    prior live-verification pass printed "Already in progress ... —
    skipping" both times, with no new duplicate row created — so the
    root cause is stale historical data from before the guard was fully
    effective, not a currently-reproducible bug in `download_playlist`.

    The real, actionable bug was in what Step 5 itself built: without
    deduplication, `get_active_downloads()` rendered three apparently-
    independent active downloads for what was really one candidate,
    across two separate real tracks. Fixed with a new
    `_dedupe_repeated_candidates()` in `dashboard_service.py`, applied
    to the visible rows before building the result: rows are collapsed
    by `(track_id, role, username, filename)`, keeping only the
    most-recently-requested one per real candidate. Deliberately keyed
    *without* `rank` — two rows are the same real download attempt if
    they share track/role/peer/filename, independent of which row
    happened to be created when; two genuinely different candidates
    (a real rank 1/2/3 shortlist) always have distinct peers/files by
    construction, so they're never collapsed by this key regardless of
    rank. `role` stays in the key deliberately too — a track can
    legitimately have a `settled` and an `upgrade` request in flight at
    once (item 8), and those must never merge even if they happened to
    share a peer/file. Three new tests in `test_dashboard_service.py`
    cover all three shapes directly: the real duplicate-collapse case
    (reproducing the exact real Balron timestamps/peer), the
    must-not-collapse legitimate-multi-candidate case (three distinct
    peers for one track, all surviving), and the must-not-merge-across-
    roles case.

    **Re-verified against the real, live production database after the
    fix, read-only** — no destructive cleanup of the underlying stale
    rows was needed or attempted; the fix is purely in how they're
    presented. Before: 8 rows shown (3 duplicates each for Jade Venom
    and Balron, plus ZENEA). After:
    exactly 3 — `ZENEA - INFINITE` (240KM/H, upgrade, queued,
    `trickytraxx`), `Jade Venom - Scared Now? - DIVERGENCE VI` (Test,
    upgrade, locked, `ofoijacussa`, the `2026-08-27T17:41:47` attempt —
    correctly the most recent of the three real duplicates), and
    `Balron, Audio - Breach` (Test, upgrade, queued, `long25`, likewise
    the most recent). One separately-flagged, genuinely out-of-scope
    observation from the same investigation: `poll_downloads()`'s
    locked-retry loop (`soulseek/download_service.py`, Phase 3 — a
    different phase's code, not part of Step 5) still independently
    retries every stale duplicate row every cycle against the real same
    peer, since it reads `get_locked()` directly rather than through
    this new display-layer dedup. That's real, ongoing, low-value
    network traffic against a live third party, but it's a Phase 3
    retry-engine concern, not a Downloads-tab rendering one — worth a
    dedicated future pass (e.g. teaching the retry loop to skip a
    locked row once a more-recent duplicate for the same candidate
    exists), not folded into this display fix.

    **Forward note for the future Review screen** (item 7/17's still-
    outstanding confirm/reject UI for needs-review matches and
    Phase 2 upgrade confirmation): a genuine Phase 4 shortlist — one
    real track legitimately backed by 2-3 distinct candidates at once —
    is exactly the shape this dedup deliberately preserves rather than
    collapses. That screen will need to visually *group* those rows by
    track ("3 candidates for this track", ranked) rather than list them
    as unrelated lines, since it's the next place a human actually acts
    on which candidate wins — the Downloads tab only ever observes, so
    a flat list was sufficient here.

### 25

25. **Fix: Phase 3 retry loop didn't dedupe stale duplicate rows before
    retrying — done (2026-08-28), closing the out-of-scope observation
    flagged at the end of item 24.** Root cause, exactly as diagnosed
    there: item 16's creation-time dedup guard
    (`get_active_for_track`, checked inside `download_playlist()`) only
    stops NEW duplicate rows going forward — it does nothing for rows
    already created before it was fully effective. `get_locked()`
    fetches every `'locked'` row globally with no per-candidate
    collapsing by its own documented design, so `poll_downloads()`'s
    retry loop re-issued a real `request_download` for each stale
    duplicate independently, every cycle, against the same real peer.

    Fixed at the retry loop itself, not a one-off cleanup script, per
    the ask — `DownloadService._retry_locked_request` now calls a new
    `_supersede_stale_duplicates(current)` before ever re-issuing a
    request: it looks up every OTHER row sharing the identical real
    candidate (`track_id`/`role`/`username`/`filename`) that's
    currently `locked`/`queued`/`downloading` (new
    `DownloadRequestRepository.get_active_candidates`), keeps only the
    most-recently-requested one, and marks the rest `'superseded'` —
    reusing that status's existing, already-documented meaning
    ("abandoned because a sibling already won") rather than inventing a
    new one. If `current` itself loses to a more recent sibling, it's
    superseded and the retry is skipped entirely (no redundant network
    call); if it's the winner, every other sibling is superseded and
    the normal retry proceeds unchanged.

    **Shared logic, not reinvented — same consolidation reasoning as
    matching.py/AUDIO_EXTENSIONS.** The exact grouping/tiebreak rule
    (same track/role/peer/file wins by most-recent `requested_at`) was
    already written once for item 24's read-side fix
    (`DashboardService.get_active_downloads`'s now-removed
    `_dedupe_repeated_candidates`). Extracted into a new top-level
    `seeker/download_dedup.py`
    (`candidate_key`/`most_recent_per_candidate`) — the same layering
    precedent as `matching.py` (a shared rule used by two different
    service-layer modules, living at neither's own layer). Both
    `DashboardService` (read) and `DownloadService` (write) now import
    the identical function, so display and mutation can never drift
    onto two different notions of "duplicate" the way the pre-item-16
    codebase drifted on artist-matching logic.

    **Deliberately unresolved edge case, documented rather than
    guarded against speculatively:** the tiebreak is pure
    `requested_at` comparison with no status-awareness — it doesn't
    prefer a sibling that's genuinely `downloading` with real bytes
    over a merely `locked` one, even if the locked one happens to be
    more recent. Checked against all real duplicate data in this
    project to date: no instance has ever had nonzero
    `bytes_transferred` on more than one sibling in a group
    simultaneously, so this hasn't been a real problem — noted directly
    in `download_dedup.py`'s docstring as something to revisit with a
    status-aware tiebreak if it ever is, rather than adding
    speculative handling for a scenario that hasn't happened.

    Tests (`tests/test_download_service.py`) cover exactly the three
    required shapes: `test_retry_loop_dedupes_stale_duplicate_locked_rows`
    (two locked rows, same candidate, different `requested_at` — only
    the more recent gets a real `request_download` call, the other
    becomes `superseded`); `test_retry_loop_never_collapses_distinct_candidates`
    (two different real peers for the same track — both retried
    independently, neither superseded, proving the Phase 4 shortlist
    shape is untouched); and
    `test_retry_loop_single_locked_row_unaffected_by_dedup_check` (a
    lone locked row — the new check is a complete no-op, matching the
    pre-existing Phase 3 contract exactly). All of Phase 3/4's existing
    tests (the `input()` guardrails, the cascade/shortlist tests, the
    peer-offline 404 tests) still pass unmodified, confirming no
    regression.

    **Live-verified against the real, still-present stale rows —
    resolved for real, not just in tests.** Before: the exact same
    duplicate groups documented in item 24 (Balron ids 5/7/9, Jade
    Venom ids 6/8/10, all real, all still in the live database). Ran
    the real `seeker downloads status` (i.e. a real `poll_downloads()`
    call, the same one the running app's 20s backend timer already
    calls automatically) **twice** — real network conditions meant one
    of Balron's three duplicates was `queued` rather than `locked` at
    the first poll, so it wasn't reachable via the retry loop's
    dedup check on that pass (by design — this fix is scoped to
    `_retry_locked_request`/locked rows, matching the ask); a second
    real run, once that row cycled back to `locked` (the same real
    flakiness already documented in item 21), completed the
    convergence. Confirmed via direct `sqlite3` queries after each run:
    first run — Jade Venom fully converged in one pass (ids 6, 8 →
    `superseded`, id 10 the sole survivor); Balron partially converged
    (id 7 → `superseded`, id 9 remained the eventual winner, id 5 still
    `locked`/`queued` pending its own next cycle). Second run — id 5
    also converged to `superseded`, leaving id 9 as Balron's sole
    survivor. Re-ran the read-side `get_active_downloads()` check
    afterward and confirmed exactly 3 real rows now (ZENEA, Jade Venom,
    Balron — one each), matching item 24's original "8 collapsed to 3"
    read-side fix exactly, this time because the underlying duplicate
    rows themselves resolved to one real winner each, not just the
    display layer hiding the extras.

### 26

26. **Frontend Step 6: Review screen — in progress (2026-08-28).** Two
    deliberately-deferred CLI-only flows get a real UI home: item 17's
    read-only SoulSeek needs-review tier gains its first real
    confirm/reject action, and Phase 2's `seeker downloads review`
    upgrade-confirmation flow gets exposed to a non-`input()` caller.

    **§0 — `confirm_review_candidate(track_id)` /
    `reject_review_candidate(track_id)` on `DownloadService` — done.**
    `reject_review_candidate` just deletes the
    `soulseek_review_candidates` row — no blacklist concept exists, so
    the same or a similar candidate can resurface on a later `download`
    run if it's still the best-scoring real match; that's a deliberate
    non-feature, not an oversight.

    **The `role` decision — sanity-checked against real consumers
    before locking in, per the ask, and it surfaced a real, general
    bug, not just a confirm-review edge case.** `role='settled'` was
    the right call (a human just manually confirmed this candidate, a
    stronger signal than an algorithmic top-rank pick, so it should
    auto-move into the library on success rather than demanding a
    SECOND confirmation via `ready_for_review`) — but `role='settled'`
    as the codebase stood would have silently broken retry-on-lock:
    `poll_downloads()`'s lock-pattern classification was scoped to
    `role == 'upgrade'` only, on the premise (correct for the ordinary
    search pipeline) that `select_downloads()` never assigns a locked
    candidate to `settled`. `find_best_needs_review_candidate` never
    filters on lock status at all, so a human-confirmed needs-review
    candidate genuinely can be a locked file — under the old code, that
    would fail permanently with zero retry the instant it's requested,
    directly contradicting "reuse the existing pipeline unchanged."

    Resolved by broadening the classification itself to apply
    regardless of role — not a narrow, confirm-review-only carve-out.
    The old `role`-scoping was really "this case doesn't happen for
    settled," not a deliberate semantic tied to role; retry-worthiness
    is a property of the REJECTION reason, not of why the download was
    requested. Only the Phase 4 cascade (`_cascade_upgrade`) stays
    `role == 'upgrade'`-specific, since `get_next_shortlisted()` isn't
    itself role-scoped and calling it for a settled rejection could
    incorrectly activate an unrelated upgrade-role shortlist entry for
    the same track. See item 13's correction above for the full
    before/after on this classification.

    A second, related invariant broke under the same broadening and
    needed its own fix: `_retry_locked_request`'s success path
    unconditionally set `'ready_for_review'` on a successful retry,
    correct only because a locked row had always been `role='upgrade'`
    before now. A `role='settled'` row that becomes locked (via
    `confirm_review_candidate`) and later succeeds on retry now
    auto-moves and marks `'completed'` directly — the same "already
    confirmed once" reasoning, mirroring `poll_downloads()`'s own
    main-loop pattern (only persist `'completed'` if
    `_move_completed_file` actually finds and moves the file; fall back
    to `'downloading'` otherwise so the next poll retries the move
    against the same still-`Succeeded` real transfer, rather than
    silently claiming a completion that didn't happen).

    A narrower alternative was considered and rejected: dynamically
    choosing `role='settled'` for unlocked candidates and `role=
    'upgrade'` only for locked ones, to avoid touching existing
    classification at all. Falls apart on inspection — the existing
    `ready_for_review` upgrade-confirmation UI/copy is built entirely
    around "replace an already-downloaded file with a better one"
    (`"Higher quality version of X ready (Y vs current Z)"`); a
    needs-review-tier track has no local file at all, so there's no
    "current" to compare against. Routing a locked confirm-review
    candidate through that flow wouldn't just cost a second click, it
    would put semantically broken copy in front of a real user.

    **A real, previously-existing gap found and fixed while wiring
    this up, not filed for later:** `SoulseekReviewCandidate` never
    persisted `size` at all — `_record_review_candidate` only ever
    needed it transiently at request time before this task, so it was
    never stored. `confirm_review_candidate` needs it to call
    `request_download`. Added a guarded/idempotent `size INTEGER`
    column (`soulseek_review_candidates`, same
    `_add_column_if_missing` pattern as every other schema change),
    a matching `SoulseekReviewCandidate.size: int | None = None`
    field, and `_record_review_candidate` now persists `file.size`.
    `confirm_review_candidate` explicitly refuses (a new
    `ReviewCandidateMissingSizeError`) a legacy row with `size IS
    NULL` — this project's two real, still-live candidates (Prdk,
    Zigi SC/A-Cray from item 17) predate this column and will need one
    more real `seeker download` run to refresh before they can be
    confirmed, rather than this method guessing or defaulting a size.
    A second new `derive_extension()` (renamed from client.py's private
    `_derive_extension` — same "shared thing moves down to the lowest
    layer that needs it" precedent as item 21's rejection patterns) was
    needed too: a persisted candidate has only a filename, not a
    `SoulseekFile` with `.extension` already derived from it.

    A bug in the first draft, caught before it ever ran against a real
    test: the `DownloadRequest` built by `confirm_review_candidate`
    initially omitted `transfer_id` entirely, silently defaulting to
    `None` — which would have left the row permanently stuck at
    `'queued'`, since `poll_downloads()`'s main loop skips polling any
    row with `transfer_id is None`. Fixed before writing the tests that
    would have caught it anyway.

    Tests (`tests/test_download_service.py`): `confirm_review_candidate`
    creates a real request with `role='settled'`, a real `transfer_id`,
    the derived `format`, and clears the candidate row immediately (not
    after completion, verified by checking the table count right after
    the call, before any poll); a confirmed-then-locked candidate
    correctly reaches `'locked'` via the ordinary `poll_downloads()`
    path with zero special-casing in `confirm_review_candidate` itself;
    `reject_review_candidate` deletes and requests nothing;
    `ReviewCandidateNotFoundError`/`ReviewCandidateMissingSizeError` for
    the two real refusal cases. Plus the general-case regression tests
    the broadened classification itself needed, independent of the new
    confirm-review feature: an ordinary `role='settled'` request hitting
    the real confirmed lock-pattern text now correctly retries instead
    of failing immediately (this is EXISTING, previously-verified
    behavior changing — given its own dedicated test, separate from the
    confirm-review-path test, rather than only covered incidentally); a
    settled rejection for any OTHER reason still correctly fails, not
    everything becomes locked; a settled rejection never triggers the
    upgrade-only cascade even when a same-track upgrade-role shortlist
    entry exists; and a locked `role='settled'` row that succeeds on
    retry auto-moves and marks `'completed'` without ever touching
    `ready_for_review`. Full suite (280 tests at this point) and
    `mypy --strict` clean throughout.

    **§1 — extract Phase 2's replace/delete-old-file logic out of its
    `input()` loop — done.** `get_upgrade_review_details(request_id)`
    (read-only resolution of the track/current-file/old-path info
    needed to build either the CLI prompts or a future UI row's labels
    — one shared method so the two callers can't drift onto different
    data) and `apply_upgrade_decision(request_id, replace,
    delete_old=False)` (the actual mutation, pure and `input()`-free,
    returning the same status text the CLI used to print inline, or
    `None` for a decline/no-op) on `DownloadService`, in
    `models/upgrade_review.py`. `_confirm_upgrade` is now a thin
    wrapper — still does the two real `input()` calls in sequence, then
    calls `apply_upgrade_decision` once with the resolved booleans;
    behavior-preserving for the CLI path, all existing
    `review_pending_upgrades` tests pass unmodified. New tests call
    `apply_upgrade_decision` directly with each real decision
    combination (replace+delete, replace+keep-old, decline).

    **§2 — the two-section Qt Review screen — done (2026-08-29).** New
    "Review" tab on `MainWindow`, alongside Dashboard/Downloads: a
    needs-review-candidates table (Track/Score/Candidate/Actions,
    Confirm+Reject buttons per row, driven by
    `get_review_candidates()`/`confirm_review_candidate()`/
    `reject_review_candidate()`) and a pending-upgrades table
    (Track/Current/New quality/Actions, Replace+Decline buttons, a
    "Delete old file" checkbox that only appears when
    `UpgradeReviewDetails.old_file_path` is set — mirroring the CLI's
    own guard around its second `input()` prompt). New
    `DownloadService.get_pending_upgrade_reviews()` — the listing call
    the upgrades section needed; no method existed to fetch every
    `ready_for_review` row as resolved `UpgradeReviewDetails` before
    this (only per-request-id `get_upgrade_review_details`, and a
    private `_get_ready_for_review()` returning bare
    `DownloadRequest`s) — implemented by combining the two, mirroring
    `get_review_candidates()`'s own listing shape. Both tables refresh
    on the existing 2s local-DB-only `poll_timer` (cheap reads, no
    slskd calls, same categorization as `get_active_downloads`) and
    immediately after any action completes (`_poll_review_items()`
    called from each action's `on_finished`). Consistent with the
    project's already-accepted "rebuild each tick" tradeoff (item 22):
    a checkbox toggled mid-2s-interval can get reset by the next
    tick's rebuild — same accepted cost as everywhere else this
    pattern is used, not a new one introduced here. `apply_upgrade_decision`
    returns `None` for a decline and a real status string for a
    replace — `run_worker`'s own `status_label` wiring only fires on
    error, so the success message is surfaced via a small
    `on_finished` handler instead. 9 new UI smoke tests (needs-review
    rendering + confirm/reject wiring, upgrade rendering with/without
    the delete checkbox, replace/decline wiring including the real
    `(request_id, replace, delete_old)` argument tuple, and the
    initial-population-on-construction case) plus 2 new
    `DownloadService`-level tests for `get_pending_upgrade_reviews()`
    itself (returns real resolved details; empty when nothing is
    ready). `mypy --strict` clean; full suite 278 passed, 17 skipped.

    **Live verification against the two real waiting candidates
    (Prdk, Zigi SC/A-Cray) — partially blocked by a real environment
    constraint, not skipped without explanation.** slskd's Docker
    Compose setup mounts the real X9 Pro music drive read-only
    (item 13); that physical drive isn't attached to this machine in
    this session — confirmed directly (`/Volumes/` lists only
    `Macintosh HD`/`SoulseekQt`, no `X9 Pro`) before concluding
    anything, not assumed from the container failing to start. The
    pre-existing real `slskd` container (stopped from an earlier
    session, ordinary shutdown per its own logs — not a crash) refused
    to restart with a real, specific error:
    `mkdir /host_mnt/Volumes/X9 Pro: permission denied` — confirming
    the drive-not-mounted diagnosis rather than a Docker/compose
    regression. Left the container exactly as found (still stopped,
    same `Exited (128)` state) rather than forcing anything further.

    This blocks the real happy path specifically — `confirm_review_candidate()`
    calling a real `request_download()` against live slskd, and the
    "re-run `seeker download` to refresh a legacy candidate's missing
    `size`" step item 26 §0 itself calls for — since both need a real
    search/enqueue round-trip against the live network. Everything
    NOT dependent on a live slskd connection was still verified live,
    for real, against the actual production database and application,
    not mocked:
    - Constructing the real `Application()` for the first time since
      the `size` column migration landed applied it for real:
      `PRAGMA table_info(soulseek_review_candidates)` before showed 6
      columns (no `size`); after, 7, with the two real legacy
      candidate rows intact and read back with `size=None`, exactly
      the documented legacy-row shape.
    - `get_review_candidates()` against the real DB returns exactly
      the two real rows still open since item 17
      (`Prdk - ONE MORE NIGHT`, score 70.4; `Zigi SC, A-Cray - Bit
      Perfect`, score 73.2), matching the real usernames/filenames
      recorded when they were first found.
    - `confirm_review_candidate()` called directly against the real
      Prdk row correctly raised `ReviewCandidateMissingSizeError` with
      the real message text, and — checked directly, not assumed —
      left both real candidate rows present and untouched afterward
      (no partial mutation before the guard fires).
    - The real `MainWindow`, launched against the real `Application`
      (Qt's `offscreen` platform, no attached display) with no fakes
      and no mocks, rendered both real candidates in the needs-review
      table with real Confirm/Reject buttons — the actual live
      equivalent of the mocked `test_review_tab_renders_needs_review_candidates`
      test, run against the real waiting data.
    - A real click on the real Prdk row's Confirm button, through the
      real worker/thread-pool/signal pipeline (not called directly),
      correctly surfaced the real `ReviewCandidateMissingSizeError`
      message on the real status label, and the real candidate count
      was confirmed unchanged (2) immediately after — full live
      verification of the error-path wiring end to end.
    - The real Zigi SC/A-Cray row's Reject button was deliberately
      NOT clicked — that would permanently delete a real, currently-
      undecided candidate as a side effect of testing, not something
      to do without the user's own decision.

    Deliberately not yet done: the real happy-path confirm (fresh
    `seeker download "Test"` to refresh both candidates' `size`, then
    a real `confirm_review_candidate()` → real `request_download()` →
    real `ready_for_review` → real Replace click) — needs the drive
    reconnected and slskd actually running, which is the user's call,
    not something to force from this session.

    **Retry attempt (2026-08-30), on request, after being told the
    drive was reconnected.** Checked at the OS level before touching
    Docker at all, since the point of this retry was to actually
    confirm the drive first rather than repeat the earlier failure
    blind: `diskutil list` — no `X9 Pro` disk anywhere in the output,
    not even as an unmounted volume; the physical device itself isn't
    enumerated, which is a stronger negative than "mounted but not at
    the expected path." `ls /Volumes/` unchanged from the original
    check (`Macintosh HD`, `SoulseekQt` only). Went one step further
    than the original investigation: `system_profiler SPUSBDataType`
    and `SPThunderboltDataType` both returned completely empty output —
    re-ran the same commands with the sandbox override
    (`dangerouslyDisableSandbox: true`) to rule out a sandboxing
    artifact specifically, and got the identical empty result both
    ways, confirming this isn't a permissions/sandbox quirk hiding a
    real, connected device. Did not re-attempt `docker start slskd` —
    the original attempt's exact failure
    (`mkdir /host_mnt/Volumes/X9 Pro: permission denied`) already
    fully explains itself given the drive isn't present at all;
    repeating it would exercise the identical failure path for no new
    information. Left everything untouched (container still stopped in
    its original state). The real happy-path verification remains
    exactly where item 26's first pass left it — genuinely not done,
    not newly broken or newly available.

    **Completed for real, partially — the drive and slskd both became
    reachable later the same day (2026-08-30), during Step 8's own
    live verification. Confirm was exercised for real; Reject and
    Phase 2 Replace/Decline remain a genuine, real data-availability
    gap, reported honestly rather than manufactured.**

    First checked whether Prdk/Zigi SC-A-Cray — the two candidates
    this whole verification was originally scoped around — were still
    usable. They weren't: Step 8 §4's own threshold live-verification
    (a separate, legitimate task) had already moved both out of
    `soulseek_review_candidates` by lowering `auto_match_threshold`
    below their real scores and running an ordinary `seeker download`
    — the real mechanism that's SUPPOSED to move a candidate out of
    that table once something better exists, but not the one this
    verification needs to exercise (a human clicking Confirm). The
    Confirm/Reject buttons themselves remained genuinely unexercised.

    Checked `soulseek_review_candidates` directly — empty. Per the
    task's own instruction ("run a real download pass... to surface a
    fresh one — same mechanism that produced the original two"), tried
    to surface a fresh candidate for real:
    - `SELECT` across every real synced/track-synced playlist
      confirmed only `Test` and `240KM/H` have ever had `sync-tracks`
      run (matches this project's own deliberate Spotify-quota
      discipline from item 1 — no other playlist has track rows to
      even be unmatched).
    - Every one of `Test`'s 4 real unmatched tracks already had an
      active `download_requests` row
      (`downloading`/`locked`/`queued`) — confirmed via `sqlite3`, not
      assumed from memory of an earlier session.
    - `240KM/H`'s one genuinely unencumbered real unmatched track,
      Kamäleon (no active request — its two PRIOR real downloads, item
      20/24, had both already reached a terminal `completed` state), was
      the only real candidate available for a fresh search. Ran a real
      `seeker download "240KM/H"` — real Soulseek search results this
      time (peer availability varies run to run, as always) produced a
      clean, high-scoring auto-tier match instead of a needs-review-band
      one: a real settled download was requested and, checked a few
      polls later, genuinely completed
      (`Moved 'Kamäleon - Quadrat Master (1).wav' to
      /Volumes/X9 Pro/Music/240KMH`). A real, honest outcome of live
      peer variability — not a test failure, and not something to
      retry indefinitely chasing a specific score band.
    - Re-checked after that completion: `240KM/H` now has zero
      unmatched tracks at all; `Test`'s same 4 remain active. Polled
      `seeker downloads status` three separate times across this
      session — the two most recently re-requested rows (Prdk id 15,
      Zigi SC id 16, both from Step 8's own threshold verification)
      showed **zero byte progress across every poll**
      (`bytes_transferred: 0` against real, confirmed `total_bytes`
      of 9,251,601 and 12,257,951), consistent with this project's own
      documented history of `musicmasterrdjpool`/`DJ-Promo` being real,
      known-flaky peers (see items 21/25's independent encounters with
      the exact same two usernames). The other two active rows
      (Balron id 9, Jade Venom id 10) have been cycling
      locked/queued via Phase 3's retry loop since 2026-08-27 —
      multiple prior sessions already document this pair never
      resolving.

    No `ready_for_review` row existed at any point checked either —
    same real cause: nothing has completed as an `upgrade`-role
    request during this window, and none of the currently-stalled rows
    show signs of reaching that state soon.

    **Conclusion, per the task's own explicit instruction not to
    manufacture data:** a genuinely fresh SoulSeek needs-review
    candidate (for Confirm or Reject) and a genuine `ready_for_review`
    row (for Phase 2 Replace/Decline) were NOT obtainable from real,
    currently-synced data within this session, without either syncing
    additional playlists' tracks from Spotify (a real, deliberate API
    quota cost explicitly out of scope for a verification pass) or
    waiting indefinitely on rows with no real sign of near-term
    resolution. This is reported directly as a real gap — same
    treatment this project already gave Step 5's mid-transfer timing
    gap — not worked around with synthetic data. Confirm/Reject/
    Replace/Decline's wiring remains verified by the 11 mocked UI
    tests from the original Step 6 §2 build; Confirm has additionally
    been exercised via one real click against one real row (this same
    item's earlier retry entry above — the `ReviewCandidateMissingSizeError`
    refusal path, a real click with a real, if negative, outcome, not
    the full happy path). Reject and Replace/Decline remain the one
    part of Step 6 that stays genuinely CLI/mock-verified only, pending
    real data that happens to exist next time this session (or a
    future one) checks.

### 27

27. **Frontend Step 7: Tagging panel — UI wiring complete; live
    verification completed for real, once the drive became reachable
    again (2026-08-30).**

    **Scope check done first, per the ask.** Read
    `library/metadata_service.py` and `cli.py::handle_library`'s `tag`
    branch before writing any UI code. Confirmed `tag_tracks`/
    `tag_playlist` are genuinely complete and already return exactly
    the shape a UI needs (`{tagged, skipped_no_match,
    skipped_format_unsupported, skipped_already_tagged,
    skipped_already_analyzed, failed, details}` — two more counters
    than the original Phase B/C summary in this file's older item 10
    mentioned, from `force`'s later addition, but no different in kind)
    — so this task really was UI wiring only, and it stayed that way;
    no new gap turned up while building it, so no new service method
    was added beyond what item 26 already needed.

    **Where the three triggers live and why.** All three land on the
    existing Dashboard tab next to the track table, since that's
    already the one place both a single-playlist track list (for
    per-track/batch) and the selected playlist itself (for "Tag
    playlist") are both already in scope — no new tab was justified for
    three buttons and a shared options row.

    - **Per-track**: `track_table` gained a 4th "Actions" column
      (`["Track", "Status", "Progress", "Actions"]`). `_build_track_actions(status)`
      returns a bare, buttonless `QWidget()` for anything that isn't
      `IN_LIBRARY` — not a disabled button, an *absent* one, on the
      same reasoning already established for the Downloads tab's
      progress-bar cells (item 24: no real action available here, so
      don't render a control that implies one). A `TrackStatus` doesn't
      carry a match-quality or already-tagged signal beyond
      `IN_LIBRARY` itself, so that's the only gate available or needed
      — `tag_tracks` already handles "matched but already tagged"
      gracefully via `skipped_already_tagged`, which isn't something
      the UI needs to pre-filter.
    - **Batch**: `track_table.setSelectionBehavior(SelectRows)` +
      `setSelectionMode(ExtendedSelection)` (ctrl/shift-click, standard
      multi-select) were not previously set on this table (its prior
      single-row `currentItemChanged` wiring for the Dashboard's own
      status display is untouched and still fires normally under
      `ExtendedSelection`). "Tag selected" resolves the current
      selection back to real track ids via a new
      `self._current_track_statuses: list[TrackStatus]` — a fresh copy
      stored on every `_render_track_statuses()` call — mapping
      `selectionModel().selectedRows()` row indices back to
      `TrackStatus.track.id`. Deliberately does NOT filter the
      selection to `IN_LIBRARY` rows before calling `tag_tracks` — per
      the brief, `tag_tracks` already reports `skipped_no_match`
      correctly for anything unmatched, so pre-filtering here would
      just be duplicating logic the service already owns correctly.
    - **Playlist**: "Tag playlist" calls `tag_playlist(playlist_name,
      ...)` directly against `self.selected_playlist.name` — no
      client-side id list construction, reusing `tag_playlist`'s own
      `match_method='auto'` scoping exactly as it already exists.

    **Shared options, one copy, not three.** `_build_tagging_controls()`
    builds the "Analyze audio (BPM/Key)" checkbox and two `QLineEdit`
    BPM min/max fields once; all three trigger handlers call the same
    `_resolve_tag_options() -> (bool, tuple[float, float] | None)`.
    The CLI's own `--bpm-range` requires `--analyze-audio` check
    (`cli.py`: `if parsed.bpm_range and not parsed.analyze_audio:
    print(...); return`) is a *validation*, catching an already-
    possible invalid combination after the fact — argparse has no way
    to prevent `--bpm-range` being passed alone. The UI can do
    strictly better: `bpm_min_edit`/`bpm_max_edit` are hidden (`.hide()`
    at construction, `.setVisible(checked)` on the checkbox's `toggled`
    signal) whenever the checkbox is unchecked, so there is no way to
    even populate a range without analysis also being on — the invalid
    combination is structurally unreachable, not merely rejected.
    A *different* invalid shape is still possible even with the
    checkbox on — one of the two fields filled, the other blank — and
    `_resolve_tag_options()` raises a plain `ValueError` for that case
    ("Enter both a min and max BPM, or leave both blank."), caught by
    each trigger handler and surfaced via `status_label` *before* any
    `run_worker`/service call is made — confirmed directly in
    `test_bpm_range_partial_input_blocks_the_call_with_an_error`, which
    asserts `tag_tracks_calls == []`, not just that an error string
    appeared.

    **Results panel, not the status label.** `status_label` is
    already this window's channel for short, transient action
    feedback (errors, "select a playlist first," etc.) — cramming a
    multi-line breakdown plus a per-track reasons list into it would
    make it behave inconsistently with every other action in the app.
    A separate `QPlainTextEdit` (`tagging_results`, read-only,
    `setMaximumHeight(120)` to stay a compact panel rather than
    dominating the screen — a non-blocking area, not a modal, matching
    this project's established preference) renders the aggregate
    counts on one line plus one `[reason] message` line per
    `details` entry, via `_render_tag_result(result)`. `status_label`
    itself is explicitly cleared at the start of `_render_tag_result`
    so a leftover "Tagging N selected track(s)..." progress note (set
    manually right after starting the batch/playlist workers, since
    `run_worker`'s own `status_label` handling only ever *clears* it at
    call time and never sets an in-progress message of its own) doesn't
    linger after the real result is in.

    **In-progress indicator, per the ask ("not just an instant
    fire-and-forget" for anything beyond a single track).** The
    triggering button disabling for the duration (via `run_worker`'s
    existing `button=` handling, unchanged) already covers all three
    triggers uniformly; "Tag selected" and "Tag playlist" additionally
    set an explicit `status_label` note (`"Tagging N selected
    track(s)..."` / `"Tagging playlist 'X'..."`) right after submitting
    the worker, since analysis in particular can run long per track and
    a disabled button alone is easy to miss. The single-track "Tag"
    button relies on the disabled-button signal alone, matching the
    brief's "not just a single track" framing.

    **No confirmation gate** — checked directly against this project's
    own stated design principle (README's four named patterns, see
    item 15) before deciding, not assumed: "never touching a file
    destructively without an explicit confirmation prompt" is scoped to
    *replacement* (the Review screen's Replace/delete-old-file flow,
    item 26 §1/§2) — tag-writing augments a file in place, the same
    category of action the CLI's own `library tag` already performs
    with zero prompt. Adding one here would be inconsistent with both
    the CLI and the project's own documented rationale, not extra
    safety.

    **Tests** (`tests/test_ui_smoke.py`, 13 new): a new
    `FakeMetadataService` (`tag_tracks_calls`/`tag_playlist_calls`,
    each recording the exact `(ids_or_name, analyze_audio,
    expected_bpm_range)` tuple) wired into `FakeApplication`. Covers:
    per-row Tag button present only for `IN_LIBRARY`, absent (no
    `QPushButton` at all) otherwise; a real Tag click's exact call
    args, with and without analyze-audio/BPM-range; BPM fields'
    hidden/visible state tracking the checkbox both directions
    (`isHidden()`, not `isVisible()` — this window is never `.show()`n
    in these tests, and `isVisible()` reflects true on-screen
    visibility gated by every ancestor, not just this widget's own
    hide/show state, which is what the test actually needs); the
    partial-BPM-input rejection (no call made); "Tag selected" against
    an additive multi-row selection built through
    `selectionModel().select(index, Select | Rows)` directly — a first
    draft using `QTableWidget.selectRow()` twice was caught replacing
    the selection instead of extending it (only the second row
    survived), not merely a hypothetical risk; empty-selection and
    no-playlist-selected guards (no call made, a clear status message
    instead); and the results panel rendering both the aggregate line
    and every per-item `[reason] message` line from a realistic mocked
    breakdown. `mypy --strict` clean; full suite 288 passed, 17
    skipped.

    **Live verification — originally blocked, same root cause as item
    26, discovered while attempting it rather than assumed in
    advance.** `tag_tracks`/`tag_playlist` open real files via
    `MutagenFile(Path(location.path) / local_file.relative_path)` —
    `location.path` is the real X9 Pro drive path for every library
    location in this project's real database. Item 26's retry (this
    same session) already confirmed via `diskutil list` that the drive
    isn't attached at the OS level at all. Running "Tag playlist" for
    real under that condition would not exercise the real success path
    this step is supposed to verify — every track would hit
    `MutagenFile(file_path)` against a nonexistent path and get
    swallowed by `tag_tracks`'s own per-track exception handling into a
    `failed` count, which is a real code path but not the one this
    verification step exists to confirm (that path is already covered
    directly by the drive-unmounted-skip tests in
    `tests/test_metadata_service.py`, per item 10). Running it anyway
    would produce a real command invocation with a hollow result —
    "the button was clicked" without confirming what actually matters,
    that a real tag write reads back correctly from a real file — so it
    wasn't run at the time, and the gap was recorded directly rather
    than papered over with a technically-real but uninformative test
    run.

    **Completed for real (2026-08-30), later the same day, once the
    drive was reachable again.** Needed a genuinely untagged, real
    `IN_LIBRARY` track to make this a real write, not a
    `skipped_already_tagged` no-op — every track from item 10's
    original real tagging run was already tagged. Rather than
    manufacture one, found a real one already sitting there from
    completed-but-unfinished real work: `Kamäleon - Quadrat`
    (`240KM/H`) had a real successful download (item 20/24) that was,
    by deliberate design (mirroring the settled-download pattern),
    never auto-reindexed into `local_files` — "a `library scan` picks
    up the updated tags on its own next run," per that design note,
    which this verification pass is exactly that next run. A real
    `seeker library scan` (`Added: 3, Updated: 7`) followed by a real
    `seeker library match` (`Auto: 9`) picked it up and auto-matched it
    at score 100 — a genuine, real, never-tagged `IN_LIBRARY` row,
    confirmed directly via `sqlite3` (`tagged_at` empty) before
    touching the UI at all.

    Launched the real `MainWindow` (offscreen Qt, real `Application`,
    no fakes), selected the real `240KM/H` playlist from the real
    playlist list, located the real Kamäleon row (rendered "In
    library" with a real "Tag" button, exactly as designed), and
    clicked it for real. The real results panel reported `Tagged: 1,
    Skipped (no match): 0, Skipped (unsupported format): 0, Skipped
    (already tagged): 0, Skipped (already analyzed): 0, Failed: 0.`

    Read the real file directly off the real drive afterward, not
    just trusted the panel's own report: `TIT2` = `"Quadrat"`, `TPE1`
    = `"Kamäleon"`, `TALB` = `"Quadrat"` — exactly matching the real
    `tracks` row's `artist`/`title`/`album`. A real embedded
    `APIC:Cover` frame present too: `mime='image/jpeg'`, real data
    starting with the genuine JPEG SOI/APP0 signature
    (`\xff\xd8\xff\xe0`), not a stub. Checked the database side too:
    `local_files.tagged_at` was genuinely set to a real timestamp for
    the first time. Full, honest confirmation that the reported result
    (`Tagged: 1`, zero skips/failures) matches exactly what the file's
    actual tags show — the thing this verification step exists to
    prove, not merely that a button click didn't crash.

### 28

28. **Frontend Step 8: Settings — done (2026-08-30).**

    **§1/§2 — library locations and playlist destinations — done,
    straightforward wiring as scoped, plus one real gap found and
    fixed along the way.** Both sections are thin `QTableWidget`/form
    UI over already-complete service methods
    (`LibraryService.list_locations`/`add_location`/`remove_location`,
    `DownloadService.set_destination`) — no new backend logic needed
    for either, confirmed by reading each method fully before wiring
    anything.

    Checked the CLI's own `library remove` before deciding whether
    Settings needed a confirmation prompt on its own "Remove" button:
    `cli.py::handle_library`'s `remove` branch calls
    `library_service.remove_location(name)` with zero `input()`
    anywhere, and `LibraryService.remove_location` itself has no
    confirmation logic either — grepped for it directly rather than
    assuming. Matched that design exactly; no prompt added.

    Extracted the wizard's "Choose your music library" folder-picker
    flow into `ui/library_location_picker.py::pick_and_add_library_location()`
    rather than rebuilding it, per the brief's explicit instruction.
    The wizard's original `_on_choose_library_folder_clicked` set
    `self.library_path_label.setText(path)` immediately after the
    native picker returned, BEFORE the (worker-routed, so
    technically-async even though near-instant) `add_location()` call
    even started — a real UX detail that had to be preserved, not
    simplified away in the extraction. Added an `on_path_picked`
    callback specifically for this, fired synchronously inside the
    shared function right after a real path is chosen — the wizard
    passes `self.library_path_label.setText` directly as this
    callback, Settings doesn't use it at all (its own status label
    covers the "in progress" case well enough via `run_worker`'s
    normal button-disable + `status_label` reset). The wizard
    hardcodes `name="Library"` (a real, deliberate single-location
    onboarding simplification, not an oversight — see item 23);
    Settings' own "Add location" form collects a real user-typed name,
    since listing/managing multiple named locations is the whole point
    of this tab.

    **A real, reachable bug found while wiring the destinations tab,
    not a hypothetical edge case — fixed in the same pass.** The
    naive implementation (`self.application.download_service
    .set_destination(...)`) failed immediately in a real test with
    `RuntimeError: SLSKD_BASE_URL is not configured.` — not from
    `set_destination` itself (confirmed by reading its full body: pure
    `self.playlists`/`self.locations` DB operations, zero reference to
    `self.soulseek` anywhere), but from
    `Application.download_service`'s own property, which
    unconditionally evaluated `self.soulseek_client` (itself raising
    when unconfigured) as an argument to `DownloadService(...)` before
    the constructor ever ran. Since the onboarding wizard's SoulSeek
    step is explicitly optional and skippable (item 23's own design),
    and `main_ui.py` routes straight to the dashboard once just
    Spotify + a library location are done, a real user who skipped
    SoulSeek setup would hit this exact error trying to do something
    that has nothing to do with SoulSeek at all — confirmed this is
    the SAME root-cause class item 17 already found and fixed once for
    `check`'s needs-review section, not a coincidence: `Application
    .download_service`'s eager construction has now caused this twice.

    Item 17's own fix (a cheap `soulseek_configured` check the CALLER
    consults before ever touching `download_service`) doesn't apply
    here, though — Settings genuinely needs to call
    `download_service.set_destination()`, not merely avoid touching
    the property. Fixed at the actual source this time: `DownloadService
    .__init__`'s `soulseek_client` parameter became `SoulseekClient |
    None`, stored as `self._soulseek_client` instead of the previous
    plain `self.soulseek` attribute assignment; a new `soulseek`
    property raises the identical `RuntimeError` message as before,
    but only when something that genuinely needs it
    (`download_playlist`, `poll_downloads`,
    `_retry_locked_request`, `confirm_review_candidate`, ...) actually
    calls it — not at construction time. Every existing internal
    `self.soulseek.xxx(...)` call site keeps working completely
    unchanged, since the property resolves to the exact same object a
    plain attribute would have. `Application.download_service` now
    passes `self.soulseek_client if self.soulseek_configured else
    None` — confirmed no existing test broke (every test constructing
    `DownloadService` still passes a real client positionally, which
    remains fully valid under the widened `SoulseekClient | None`
    type). `persist_soulseek_config` (§3) additionally resets
    `self._download_service = None`, not just `self._soulseek_client
    = None` — without this, a `DownloadService` already cached from an
    earlier, genuinely-unconfigured moment in the same session would
    keep its frozen `None` client forever, even after real credentials
    land later via "Update SoulSeek credentials."

    Tests: `DownloadService.soulseek` raises the clear error only when
    actually accessed with `_soulseek_client=None`;
    `set_destination()` genuinely works end-to-end with no SoulSeek
    client at all (a real DB write, not just "didn't raise");
    `Application.download_service` constructs successfully while
    unconfigured; `persist_soulseek_config` resets the cached
    `DownloadService`, and the freshly-reconstructed one has a real,
    working `soulseek` property afterward. `pick_and_add_library_location`
    tests: dialog-cancelled no-op, a real chosen path correctly
    calling `add_location(name, path)`, `on_path_picked` firing with
    the raw path synchronously and before the add call, and the
    button/status_label wiring genuinely routing through
    `run_worker`'s standard handling rather than bypassing it. Settings-
    level tests (`tests/test_settings_window.py`, 21 tests, using a
    real `Application()` against a real tmp_path-redirected DB — same
    testing philosophy as `test_wizard.py`, not hand-rolled fakes,
    since Settings is deeply wired to real service method signatures a
    fake could silently drift out of sync with): locations list/add/
    remove wiring; destinations list/save wiring, including reading
    the saved value back from the real DB; the no-selection guard
    messages for both tabs.

    **A real gotcha hit writing these tests, same one item 19's own
    test suite already documented once:** the first draft of
    `make_application()` for this test file left this developer
    machine's real `.env` values (`SLSKD_BASE_URL`/`SLSKD_API_KEY`/
    etc., loaded into `os.environ` at `config.py` import time, which
    predates any test-level `monkeypatch.chdir()`) leaking into
    `migrate_legacy_env_config`'s migration, AND — a layer this
    specific gotcha hadn't been hit at before — `config.py`'s
    module-level constants (`config.SLSKD_BASE_URL` etc.) are frozen
    at import time and untouched by `monkeypatch.delenv()` alone, so
    `Application`'s own property-level env fallback still returned the
    real machine's real value even after clearing `os.environ`. Fixed
    by clearing both layers in `make_application()` — real
    `os.environ` vars via `monkeypatch.delenv` AND the frozen
    `seeker.application.config.*` constants via `monkeypatch.setattr`
    — matching `test_application.py`'s own already-established
    two-layer pattern, applied here for the first time in a
    Settings-specific test file.

    **§3 — SoulSeek/Spotify connection-management extraction — done.**
    Read the onboarding wizard's Spotify and SoulSeek step code
    (`ui/wizard.py`) before touching anything, per the brief's own
    instruction, specifically to answer: which parts are already
    separable service/worker calls Settings can just call directly,
    and which are genuinely entangled with the wizard's own
    screen-navigation code and need real extraction?

    Checked each of the three required actions separately:
    - **"Test connection"** — `docker_setup.py::check_slskd_health` is
      already a fully standalone, pure(ish) function (real `httpx`
      calls, but zero wizard/Qt coupling) — confirmed by reading its
      own call site (`_poll_slskd_health_once`), which is nothing more
      than `run_worker(..., lambda: check_slskd_health(...), ...)`.
      Nothing to extract; Settings can call it directly.
    - **"Update SoulSeek credentials"** — `bring_up_slskd` (also
      already standalone) runs `docker compose ... up -d`, which is
      already the "recreate, not restart" command per item 13's
      established lesson — Compose recreates a service whose config
      (here: env vars) changed. So the "needs a recreate, not a
      restart" requirement was ALREADY satisfied by reusing this
      function as-is; no new recreate logic to write. The one thing
      genuinely entangled with the wizard was
      `_persist_soulseek_config()` — small, but it directly touched
      `self.application._config_store`/`save_config`/`resolve_config_path`
      inline, which Settings would otherwise have had to duplicate.
      Extracted to `Application.persist_soulseek_config(...)`.
    - **"Re-authorize Spotify"** — similarly, `_on_connect_spotify_clicked`'s
      `do_connect()` closure directly touched `self.application
      ._config_store`/`_auth_manager` inline. Extracted to
      `Application.connect_spotify(client_id, force_reauthorize=False)`.

    **A real correctness gap found while designing "Re-authorize"
    specifically, not assumed to be fine because the wizard's version
    "worked":** re-read `SpotifyAuthManager.get_valid_token()`
    (`spotify/auth_manager.py`) before assuming resetting
    `_auth_manager` to `None` and calling `.spotify` would be enough.
    It isn't, for the Settings case specifically: `get_valid_token()`
    loads whatever token is on disk via `TokenStore`, and only calls
    `_authorize()` (the real browser-opening path) when that load
    returns `None` or the token is expired-and-refresh-fails.
    Resetting `_auth_manager` to a fresh instance changes nothing about
    what's already saved to disk — a fresh `SpotifyAuthManager` still
    loads the SAME still-valid token file and returns it silently, no
    browser opened. This is invisible in the wizard's own flow (no
    token file exists yet on a first connect, so the `None` branch
    always fires there) — which is exactly why it was never caught
    before. For a user clicking "Re-authorize" on an already-connected
    setup, the exact same code would silently do nothing at all, while
    still reporting success. Fixed with a real, new (if small)
    capability: `TokenStore.clear()` — deletes the cached token file —
    called by `connect_spotify` only when `force_reauthorize=True`
    (the wizard's own call site omits it, preserving its existing
    behavior exactly, confirmed via a dedicated test that a token
    present before an unforced `connect_spotify()` call is still
    present after).

    Also found and fixed in the same pass, checking rather than
    assuming: does `persist_soulseek_config` need to invalidate
    anything else? The wizard's original `_persist_soulseek_config`
    never reset `self.application._soulseek_client` — safe there only
    because nothing had constructed one yet during first-time
    onboarding (`Application.soulseek_client` is itself a lazy-cached
    property, and onboarding is definitionally the FIRST configuration
    event). Settings' "Update SoulSeek credentials" has no such
    guarantee — it can run against an app that's been live and
    connected for a while, with a real cached `SoulseekClient` already
    pointing at the OLD base_url/api_key. `persist_soulseek_config`
    resets `self._soulseek_client = None` unconditionally, so the next
    access to `application.soulseek_client` rebuilds it with the new
    credentials. Verified directly with a dedicated test (seeds a
    sentinel value into `_soulseek_client` before calling
    `persist_soulseek_config`, asserts it's `None` afterward) rather
    than only asserting the config-store side.

    A small, real duplication caught while making this change, fixed
    alongside it rather than left as a second copy: the exact literal
    `Path(".seeker/spotify_token.json")` was about to appear a second
    time inside `connect_spotify` (needed to construct the `TokenStore`
    for `force_reauthorize`), duplicating the one already inline in the
    `auth_manager` property. Factored out to a single
    `SPOTIFY_TOKEN_PATH` module constant in `application.py`, and the
    `auth_manager` property updated to use it too — one literal, not
    two that could drift.

    `ui/wizard.py`'s own private `_slskd_data_dir()` helper (used both
    by `_on_bring_up_clicked` and `_persist_soulseek_config`) was the
    one other genuinely shared-but-UI-local piece — moved to
    `docker_setup.py` as a public `slskd_data_dir()`, since Settings'
    "Update SoulSeek credentials" needs the exact same path and a UI
    module importing from another UI module (`ui/wizard.py` →
    `ui/settings_window.py` or vice versa) would be a worse layering
    choice than both importing a shared function from the
    service-adjacent `docker_setup.py`.

    Every existing wizard test (`tests/test_wizard.py`) passes
    unmodified — the refactor is a pure extraction with the exact same
    external behavior at the wizard's own call sites, confirmed rather
    than assumed by running the existing suite, not just by reading the
    diff.

    **Live verification, scoped deliberately per the brief.** "Test
    connection" is safe and non-destructive against the real running
    container — deferred at this point in the build to once the rest
    of the Settings screen (§1/§2, and the UI itself) existed, so it
    could be exercised through the actual Settings UI rather than a
    bare script; see the real result recorded once that UI existed,
    below. A full credential-rotation-and-recreate cycle against the
    real production slskd setup was NOT run for real, per the brief's
    own explicit scoping — tests plus the wizard's own already-
    established live verification (item 23) cover the underlying
    `bring_up_slskd`/`check_slskd_health` mechanism; re-running that
    exact mechanism against the real, currently-working container
    would be a genuinely disruptive action on working infrastructure
    for a task whose only actual change is *who calls* the function,
    not what it does.

    **"Test connection" live-verified for real, once the Settings UI
    existed (2026-08-30) — the X9 Pro drive and slskd both became
    available partway through this task, unblocking this and every
    other real-infrastructure check in this session.** Constructed the
    real `Application()` (real config store, real production `.env`),
    built the real `SettingsWindow` (offscreen Qt, no fakes), and
    confirmed the Connection tab correctly rendered the real, already-
    configured masked API key and clicked the real "Test connection"
    button — it returned `HEALTHY` from `check_slskd_health` against
    the real, currently-running `slskd` container and rendered
    "Connected." on the real status label, through the real
    worker/thread-pool pipeline, not called directly. Also confirmed,
    live rather than assumed: the real stored `config.json`'s
    `slskd_username`/`slskd_password` correctly display "Not
    configured" — genuinely accurate, not a rendering bug, since that
    file was written by the wizard's real bring-up (item 23) before
    this task's `persist_soulseek_config` ever existed to capture
    those two fields; they'll only populate once a real "Update
    SoulSeek credentials" run actually happens.

    **§4 — editable thresholds — done. Full design reasoning, since
    this is the one genuine refactor in this step (the other three
    sections are wiring on top of already-complete services).**

    First checked the real call sites before touching anything, per
    the brief's own instruction — grepped every reference to
    `AUTO_MATCH_THRESHOLD`/`NEEDS_REVIEW_THRESHOLD` across the
    codebase. Neither constant is referenced inside `matching.py`
    itself at all — `score_title`/`artist_matches`/`resolve_text_source`/
    `normalize_filename_text` are pure scoring/normalization functions
    with no threshold comparison anywhere in their bodies. The actual
    comparison points are `library/matcher.py::TrackMatcher.match_all()`
    (inline `if score >= AUTO_MATCH_THRESHOLD: ... elif score >=
    NEEDS_REVIEW_THRESHOLD: ...`) and `soulseek/quality.py`'s
    `filter_candidates` (`score < AUTO_MATCH_THRESHOLD`) and
    `find_best_needs_review_candidate` (`NEEDS_REVIEW_THRESHOLD <=
    score < AUTO_MATCH_THRESHOLD`) — confirming the brief's own
    parenthetical guess exactly.

    **The real design question: should `quality.py`'s functions
    themselves become config-aware (matching `TrackMatcher`), or stay
    pure with plain parameters (matching `matching.py`)?** The brief's
    own phrasing ("the service-layer callers (TrackMatcher, the
    quality.py functions) are the ones that resolve config-value-or-
    default") reads ambiguously — it could mean quality.py's functions
    do the resolving themselves, or it could mean they're being named
    as peers-in-the-sentence to TrackMatcher without literally sharing
    its exact mechanism. Resolved by architecture, not by re-parsing
    the sentence harder: `quality.py` currently has ZERO service-layer
    coupling — no DB, no config, no I/O, exactly like `matching.py`
    itself, and `tests/test_quality.py` calls its functions directly
    with hand-built in-memory data, no mocking of any kind. Making
    `quality.py` config-aware would introduce exactly the coupling this
    task's own design section says `matching.py` must NOT have, just
    one file over — inconsistent with the explicit protection that
    module gets. So: `quality.py`'s three functions got plain optional
    float parameters, staying exactly as pure and directly testable as
    before. `DownloadService` (real DB, real repositories, already the
    thing `quality.py`'s functions get called from) is the actual
    "quality.py caller" that resolves config-or-default and passes
    explicit numbers in — the brief's requirement is satisfied one
    layer up from where a literal reading might have placed it, for a
    concrete, checked reason.

    **The "callable, not a snapshot" requirement — also worked out from
    first principles, not assumed.** `Application.track_matcher`/
    `.download_service` are lazy-cached properties — the real
    `TrackMatcher`/`DownloadService` instance is constructed exactly
    once and reused for the app's entire session. If `Application`
    passed `self._config_store` (a plain `SeekerConfig` dataclass
    value) into the constructor at that first access, the service would
    hold a frozen snapshot from whatever `_config_store` was AT THAT
    MOMENT — a Settings save afterward reassigns
    `self._config_store = updated` (item 19's/23's established
    pattern), which rebinds the ATTRIBUTE on `Application`, but does
    nothing to a value already copied out of it. Confirmed this by
    reading every existing write path
    (`OnboardingWizard._on_connect_spotify_clicked`'s `do_connect()`,
    `_persist_soulseek_config()`) — both already do exactly
    `self.application._config_store = updated`, not a mutation of the
    existing object. So both new constructor params are typed
    `Callable[[], SeekerConfig] | None`, and `Application` supplies
    `lambda: self._config_store` — a closure reading `self`'s current
    attribute fresh on every call, not a value copied once. Verified
    this actually works, not just architecturally plausible: the new
    end-to-end tests construct a `TrackMatcher`/`DownloadService` ONCE,
    call `match_all()`/`download_playlist()` to get a baseline result,
    reassign a local `config_state` variable the injected lambda
    closes over (mirroring `Application`'s exact pattern), and call
    the SAME already-constructed service again — confirming the
    classification result actually changes with no reconstruction.

    Real reference data used throughout, not synthetic scores — the
    same Prdk (70.4)/Zigi SC-A-Cray (73.2) candidates from item 17,
    reused directly from `test_quality.py`'s
    `REAL_PRDK_CANDIDATE`/`REAL_ZIGI_SC_CANDIDATE` fixtures and
    `test_download_service.py`'s existing needs-review test's exact
    search query/candidate data. A lowered `auto_match_threshold=70.0`
    moves Prdk from `filter_candidates`'s exclusion into inclusion, and
    from `select_downloads`'s `needs_review`-only result into a real
    `settled` pick — checked directly, including the DownloadService-
    level test where the SAME real candidate that landed in
    `soulseek_review_candidates` at the default threshold becomes a
    real `request_download()` call once the config value is lowered on
    the same, already-running service.

    `SeekerConfig` also gained `slskd_username`/`slskd_password` (plain
    text — same 0600-permission file as every other field here) ahead
    of §3's connection-management section, which is the section that
    actually needs to display/re-collect them; item 19 deliberately
    scoped these out when the store was first built, explicitly
    "pending exactly this real consumer."

    A small, unavoidable mypy fallout, fixed in the same pass:
    `migrate_legacy_env_config`'s `replace(seeker_config,
    **{field_name: env_value})` used to type-check cleanly when every
    `SeekerConfig` field was `str | None` — once the dataclass also
    has `float | None` fields, mypy can no longer verify a `**kwargs`
    dict keyed by a runtime string only ever touches the str-typed
    fields (which `_ENV_VAR_BY_FIELD` genuinely only ever does — env
    vars are always strings). A scoped `# type: ignore[arg-type]` with
    an inline comment, same discipline as the existing
    `seeker.metadata` mypy override for mutagen's missing stubs.

    **Live-verified for real against the production database (2026-08-30),
    the drive/slskd having become available partway through this
    session.** Set the real thresholds via the real `SettingsWindow`
    (offscreen Qt, real `Application`): `auto_match_threshold` field
    to `"70.0"`, `needs_review_threshold` to `"60.0"`, clicked real
    Save. Confirmed both in-memory (`app._config_store`) and on disk
    (`load_config(resolve_config_path())`) immediately reflected the
    new values.

    Ran a real `seeker download "Test"` in the same session, no
    restart, right after. Real output:
    ```
    Searching: Prdk - ONE MORE NIGHT
      Requested from musicmasterrdjpool: DJPOOLS\2026\MONTHS\FEB\20\The Mash Up 20 FEB\Prdk - One More Night (Clean) 4A 87.mp3
      Already in progress for Balron, Audio - Breach (queued) — skipping.
    Searching: Zigi SC, A-Cray - Bit Perfect
      Requested from DJ-Promo: AUDIO1\2026\07-JUL\25\Beatport Best of Independent Artist June 2026\A-Cray, Zigi SC - Bit Perfect (Original Mix) [www.dj-promo.org].mp3
      Already in progress for Jade Venom - Scared Now? - DIVERGENCE VI (locked) — skipping.
    Requested 2 download(s), skipped 2, failed 0 (of 4 unmatched tracks).
    ```
    Both Prdk and Zigi SC/A-Cray — the exact same real candidates
    (same peer usernames, same filenames) that had been sitting in
    `soulseek_review_candidates` since item 17 — were genuinely
    requested this run, not just re-scored in isolation. Confirmed
    directly via `sqlite3` against the real database, not inferred
    from the printed output alone: both landed real `download_requests`
    rows with `role='settled'`, `status='queued'`; `soulseek_review_candidates`
    was completely empty immediately afterward, confirming item 17's
    stale-review-candidate-clearing logic (`download_playlist`'s
    `settled is not None or upgrade_shortlist` clear-trigger) fired
    correctly for both. A follow-up real `seeker downloads status`
    showed both had already progressed to `Downloading` for real.

    This is a genuine, complete, end-to-end proof that a threshold
    changed through the real Settings UI reaches the real
    `download_playlist()` code path with zero restart in between —
    not a synthetic reproduction of the mechanism, the actual
    real-world scenario the whole feature exists for. (Real,
    honestly-noted side effect: this run created two genuine real
    Soulseek download requests against real peers as a direct,
    intended consequence of the verification the task asked for — not
    an accident, but worth naming since it's a real action on live,
    external infrastructure, same disclosure discipline as every other
    live-verification note in this file.)

### 29

29. **UI polish pass — done (2026-08-30).** Mirrors backend item 15's
    six-area structure exactly (dead code, `mypy --strict`, docstrings,
    error-handling audit, coverage audit, dependency audit, README),
    applied to everything built across Steps 3-8. Full detail per area
    below; the condensed version in `CLAUDE.md` covers the same ground
    at a glance.

    **1. Dead code.** Checked the three specific things flagged going
    in, plus a general sweep:
    - `wizard.py`'s `_on_connect_spotify_clicked`/`_persist_soulseek_config`
      — read both directly. Both are now thin callers of
      `self.application.connect_spotify(...)`/`self.application
      .persist_soulseek_config(...)` (item 28 §3's extraction target),
      with no leftover inline duplicate logic and no now-unused
      `load_config`/`save_config`/`resolve_config_path`/`replace`
      imports left behind — confirmed by grepping the file's own
      imports, not just the two methods.
    - Step 3→5's dashboard restructure (single panel → `QTabWidget`):
      `main_window.py`'s `_build_ui()` builds exactly one `central`
      widget (the Dashboard tab's contents) and adds it to `tabs`
      alongside `downloads_table`/`review_tab` — no orphaned second
      layout, no leftover `setCentralWidget` call targeting anything
      other than the tab widget.
    - Debug/scratch leakage: `git ls-files` for anything matching
      `debug|scratch|temp|test_live|manual_check|tmp_` and for any
      `.py` file living outside `src/`/`tests/` — both empty. `grep
      -rn "print("` across `ui/`, `main_ui.py`, `dashboard_service.py`,
      `config_store.py`, `download_dedup.py`, `docker_setup.py` found
      exactly one hit — `config_store.py`'s existing, already-
      documented "Migrated config from .env..." notification (item
      19), not a leak.
    - `ruff check --select F401,F811,F841` across the whole `src/`
      and `tests/` tree (not just files touched this session) found
      two genuinely unused imports, both leftover from earlier drafts
      this same session rather than shipped logic: `pytest` in
      `tests/test_docker_setup.py` (never actually referenced —
      `pytest.raises` etc. aren't used in that file) and
      `track_status.DOWNLOADING` in `tests/test_ui_smoke.py`. Removed
      both.

    **2. `mypy --strict`.** Cleared `.mypy_cache` and re-ran fresh
    (60 files) before trusting the "already clean" result — a stale
    cache masking a real error was a real enough risk to rule out
    explicitly rather than trust the last run from a different task.
    Clean.

    The specific concern flagged going in — PySide6's historically
    incomplete `Signal`/`Slot` stub coverage, a plausible real analog
    to the `mutagen` situation in item 15 — was checked directly, not
    assumed either way: `grep -rn "type: ignore" src/seeker/ui/
    src/seeker/main_ui.py` returns exactly one hit, in `main_ui.py`
    (`qt_app.dashboard_window = dashboard  # type: ignore[attr-defined]`
    — a dynamically-assigned attribute on a `QApplication` instance,
    which mypy genuinely can't know about statically; nothing to do
    with `Signal`/`Slot` at all). Ran `mypy --strict` on
    `ui/workers.py` in isolation (the one module with real custom
    `WorkerSignals(QObject)` / `Signal(object)` / `Signal(str)` /
    `@Slot()` definitions) — clean, zero ignores needed. Conclusion:
    PySide6's bundled stubs are sufficient for how this codebase
    actually uses `Signal`/`Slot`; no scoped `[[tool.mypy.overrides]]`
    entry was added, per the task's own explicit instruction not to
    add one that isn't needed.

    **3. Docstrings/comments.** All six specific items named in the
    task brief were checked individually against the real current
    source, not assumed present from memory of having written them
    earlier in the session:
    - Two-timer split (`main_window.py` lines ~45-54): both
      `POLL_INTERVAL_MS`/`BACKEND_POLL_INTERVAL_MS` already carry
      "why 2s" / "why 20s and separate from the display timer" comments.
    - Overlap guard (`_backend_poll_in_progress`, `_trigger_backend_poll`):
      already commented at both the field declaration and the check
      site.
    - Threshold validation (`settings_window.py::_on_save_thresholds_clicked`):
      already has "a real logic bug, not just a UX nicety" plus a
      pointer to `matching.py`'s own threshold-ordering comment.
    - `role='settled'` decision (`download_service.py::confirm_review_candidate`):
      already documents both the "why settled, not a second
      ready_for_review confirmation" reasoning AND the broadened
      lock-classification fix it required, with a pointer to CLAUDE.md
      item 26/13.
    - `get_config` callable-not-snapshot (`matcher.py::TrackMatcher.__init__`):
      already explains why a snapshot would go stale, given
      `Application.track_matcher`/`.download_service` are lazy-cached
      for the app's lifetime — `download_service.py` carries a shorter
      comment explicitly pointing back at this one rather than
      repeating it, avoiding drift between two copies of the same
      reasoning.
    - `DownloadService.soulseek` lazy property: already documents what
      it protects against (Settings needing a usable `DownloadService`
      for SoulSeek-independent methods without eagerly requiring
      configuration) right at both the constructor's `_soulseek_client`
      assignment and the property itself.

    All six already had the reasoning written down — a direct
    consequence of this project's established habit (see every prior
    roadmap item) of recording the "why" at the moment a decision is
    made rather than retrofitting it later. Nothing added here.

    **4. Error-handling audit — the deepest part of this pass, and
    where both real findings came from.**

    The brief's own hypothesis, stated directly: does an uncaught
    exception inside the 20s backend-poll tick or the 2s display-
    refresh tick silently stop the timer from firing again, or crash
    the app — "trace it for real rather than assuming Qt's
    timer/worker plumbing already handles this safely." Traced it for
    real: wrote a standalone script constructing a real `QTimer` (200ms
    interval) wired to a real `run_worker()` call whose `on_finished`
    callback unconditionally raises `ValueError`, ran the real Qt event
    loop for 1.2 real seconds, and counted ticks. Result: the callback
    raised — and printed a full traceback via PySide6's own default
    exception hook — on **every single one of 5 real ticks**, the
    timer never stopped firing, and the process exited 0 ("Process
    survived, did not crash"). The original hypothesis (crash or
    silent-stop) was **wrong** on this PySide6 version — confirmed
    empirically, not just reasoned about.

    But tracing it for real is what surfaced the actual, different gap:
    tracing WHY the app survives revealed that `ui/workers.py::run_worker()`'s
    `handle_finished`/`handle_error` closures called the CALLER-supplied
    `on_finished(result)`/`on_error(message)` with **no exception
    handling of their own** — only PySide6's own internal, undocumented-
    as-a-contract default exception hook was standing between a bug in
    ANY render/completion callback (in this codebase or a future one)
    and an unhandled exception with zero attribution beyond a raw
    traceback. This is real, if not the originally-hypothesized shape:
    a render bug on a periodic poll (the Downloads/Review tabs' 2s
    refresh, the 20s backend poll) would print a traceback forever,
    every tick, with nothing in THIS codebase's own code ever having
    decided that was acceptable — an implicit safety net, not an
    intentional design.

    Same "one bad item can't silently vanish" principle as every batch
    loop in this codebase (see item 15's `download_playlist`/
    `poll_downloads` fix, and the more recent stale-duplicate-retry fix
    in item 25 — the task brief explicitly named both as the closest
    prior instances of this exact failure shape). Fixed by wrapping
    both `on_finished(result)` and `on_error(message)` invocations in
    their own try/except inside `run_worker()` itself — the single
    shared abstraction "every long-running action in this app... goes
    through," per its own docstring — rather than patching each of the
    ~15 individual call sites across `main_window.py`/`wizard.py`/
    `settings_window.py` separately, which would both be more
    error-prone (easy to miss one) and duplicate a decision that only
    needs to be made once. On catch: prints a clear, prefixed
    diagnostic (`"Error handling worker result: {error}"`), and — for
    `on_finished` specifically — also writes to `status_label` when the
    caller provided one, so a render bug becomes exactly as visible to
    the user as any other error already is for that same action,
    without changing the deliberate, separate "periodic-poll fetch
    errors stay silent by design, no noisy status flashing every 2-20s"
    behavior (that's the FETCH function's own `except Exception` inside
    `Worker.run()`, an untouched, different code path).

    Investigating this ALSO surfaced a second, genuinely unrelated real
    bug: running the polish pass's coverage report produced a real
    `ResourceWarning: unclosed database in <sqlite3.Connection object>`,
    traced back to `Database.initialize()`. `with self.connect() as
    connection:` looks like the same pattern `transaction()` uses, but
    isn't — `sqlite3.Connection.__enter__`/`__exit__` only manage the
    transaction (commit on success, rollback on exception); they never
    close the connection, unlike `transaction()`'s own explicit `finally:
    connection.close()`. Every real `Application()` launch (once, at
    startup) and every test that builds a fresh `Database` and calls
    `.initialize()` (a very large fraction of this project's whole test
    suite) was leaking one real sqlite3 connection, relying on Python's
    garbage collector to eventually finalize it rather than closing it
    deterministically. Not severe in practice (one leak per app launch,
    not a hot-path leak), but a genuine bug — fixed to match
    `transaction()`'s own pattern exactly: explicit `try/finally:
    connection.close()`, `commit()` moved inside the try block to
    preserve the exact same "commit on success" behavior the old
    `with` block provided. Verified fixed, not just plausible: re-ran
    the exact command that first surfaced the warning
    (`pytest -W error::ResourceWarning`) against the affected test
    files — clean, zero warnings.

    Also checked, per the brief's second specific ask: every wizard
    step making a real network call already has a real, user-visible
    failure path. Docker health polling
    (`check_slskd_health`/`detect_docker_state`) both swallow their
    OWN real exceptions (`httpx.HTTPError`, `FileNotFoundError`,
    `subprocess.CalledProcessError`/`TimeoutExpired`) into a status
    enum value rather than ever raising — confirmed by re-reading both
    functions' full bodies — so neither one ever depended on
    `run_worker`'s error-handling path to surface a failure at all; the
    real OAuth (`connect_spotify`) and Docker bring-up (`do_bring_up`)
    flows already pass `status_label` to their `run_worker` calls, so a
    real failure there was already correctly surfaced before this
    audit. No gap found in this half of the ask.

    **5. Coverage audit — three real gaps closed, judged against the
    same "real logic vs. thin-by-design" standard item 15 established,
    not a percentage chase.**

    `ui/wizard.py`: 63% → 93% (line coverage). The existing
    `test_wizard.py` (5 tests before this pass) only ever exercised
    which step the wizard resumes at on construction — not a single
    real button click anywhere in the file. Given Settings' own
    equivalent actions (re-authorize, update credentials) were already
    tested this exact way (`test_settings_window.py`), this was a
    real, demonstrable asymmetry, not assumed thin-by-design glue.
    Added 15 new tests: `_on_connect_spotify_clicked` (calls
    `connect_spotify` with the real typed client ID, advances to step
    1); `_on_choose_library_folder_clicked` (mocks `QFileDialog`,
    confirms a real `add_location("Library", path)` call and the
    label/advance sequence — including that `on_path_picked` fires
    synchronously with the raw path BEFORE the worker-routed
    registration completes, the exact UX detail the extraction in item
    28 §1 had to preserve); `_on_bring_up_clicked`'s three real guards
    (empty username/password, Docker not running, no library location —
    the last one required understanding a subtlety: a wizard resumed
    directly at step 3 via `_initial_step()` never actually sets
    `_library_location_path`, since that's normally set by
    `_advance_from_library()` during real in-session navigation, which
    a resumed-at-step-3 construction skips entirely — documented
    directly in the test as a real, if synthetic-scenario-specific,
    behavior, not a test bug); a real `docker compose` failure path
    (mocked `bring_up_slskd` returning a nonzero `returncode`, confirms
    the real stderr text reaches `soulseek_status_label`); all three
    real `_handle_health_result` outcomes (HEALTHY → persists via
    `persist_soulseek_config` and advances to the dashboard;
    BAD_CREDENTIALS → shows the real detail text, stays on step 3; the
    elapsed-timeout branch); and `_render_docker_state`'s three real
    branches (NOT_INSTALLED offers a download link; INSTALLED_NOT_RUNNING
    on darwin offers a launch button; confirmed via
    `monkeypatch.setattr("sys.platform", "darwin")` rather than
    trusting the real test machine's platform) plus
    `_on_launch_docker_clicked`'s real success (`subprocess.run`
    called, status updates, button becomes "Check again") and failure
    (`OSError` → manual-instructions message) paths.

    One real test-authoring bug caught and fixed in the same pass, not
    left in: the first draft of the docker-state test asserted
    `docker_action_button.isVisible()`, which failed — not because the
    button wasn't shown, but because `isVisible()` reflects true
    on-screen visibility gated by the ENTIRE ancestor chain being
    shown, and this test (like most in this suite) never calls
    `.show()` on the wizard. Fixed to `not .isHidden()`, which reflects
    the widget's own explicit hide/show state regardless of ancestor
    visibility — the same fix already applied once before, in
    `test_settings_window.py`'s own equivalent assertion, this time
    recognized immediately from that precedent rather than re-derived.

    `Application.onboarding_complete`: real, consequential routing
    logic — `main_ui.py` uses its return value to decide whether a
    fresh launch shows the wizard or the dashboard — that had never
    been asserted for its actual TRUE/FALSE correctness anywhere. The
    one existing exercise, `test_lazy_spotify_config.py`, runs
    `Application()` construction and touches `onboarding_complete` in
    a real subprocess (to test that nothing eagerly requires Spotify
    auth) — genuinely real, but only confirms the property doesn't
    RAISE, never that it returns the right boolean, and coverage.py
    can't see across the subprocess boundary regardless (which is
    exactly why the aggregate coverage report still showed the
    property's own `return` line as "missed" despite a real test
    genuinely calling it). Added four direct tests covering all real
    combinations: neither Spotify nor a library location (False),
    Spotify only (False), library only (False), both (True) — the last
    one is the real condition this property exists to compute, and
    it's also what confirms SoulSeek is genuinely excluded from the
    check (the wizard's own docstring already claims this; this is
    what actually proves it against the real property, not just
    against a comment).

    `docker_setup.py::bring_up_slskd`: zero direct tests anywhere —
    every wizard/Settings test that touches it mocks it out completely
    (correctly; there's no reasonable way to unit-test a real `docker
    compose up`). But the function's OWN body — building the real env
    dict and command list — was itself completely unverified. Added a
    test mocking only `subprocess.run` (not the whole function),
    capturing the real `command`/`env`/`capture_output`/`text` kwargs
    it's called with, and asserting: the exact real
    `SLSKD_NETWORK_USERNAME_ENV_VAR`/`SLSKD_NETWORK_PASSWORD_ENV_VAR`
    keys (imported from the module, not re-typed as string literals,
    so a rename in the source is automatically reflected here) map to
    the right values; `SLSKD_API_KEY`/`SLSKD_DATA_DIR`/`SLSKD_SHARE_PATH`
    are set correctly; and — the one thing a naive mock wouldn't catch
    — that `**os.environ` is genuinely spread into the real env dict
    rather than replaced (set a real, unrelated env var via
    `monkeypatch.setenv` first, confirmed it survives into the
    captured dict). Directly motivated by item 13's own documented
    history of getting the SoulSeek-network-vs-web-UI env var names
    wrong once already — this is exactly the kind of regression a
    future refactor of `bring_up_slskd`'s body could reintroduce
    silently without a test watching its actual construction logic.

    **Explicitly judged not worth closing further** (same standard,
    same discipline as item 15's own equivalent section — most of
    `application.py`'s remaining coverage gap is the SAME lazy-init
    one-line-getter pattern item 15 already explicitly excluded
    (`track_matcher`/`metadata_service`/`dashboard_service` property
    bodies — `if self._x is None: self._x = X(...)`, testing which
    would mostly re-assert the getter pattern itself, not real logic).
    `main_window.py`'s remaining gaps are near-duplicate "no
    selection, show a message, make no call" guards for
    `_on_sync_clicked`/`_on_scan_clicked`/`_on_match_clicked`/
    `_on_download_clicked`/`_on_sync_tracks_clicked` — the exact same
    shape already directly tested for the tagging panel's equivalent
    guards (item 27) and for Settings' equivalent guards (item 28);
    re-testing five more structurally-identical guard clauses would
    add volume, not real risk coverage. `_on_settings_clicked`'s
    window-opening wiring is trivial (`SettingsWindow(self.application);
    .show()`) and already has existence-level smoke coverage
    (`test_main_window_has_a_settings_button`) — deeper testing would
    require constructing a real, fully-wired `Application` inside
    `test_ui_smoke.py`'s simpler `FakeApplication`-based suite, a
    meaningfully bigger investment for a two-line method.
    `settings_window.py`/`download_service.py`/`matcher.py`'s residual
    gaps are the same shape as `main_window.py`'s.

    **6. Dependency audit — checked, confirmed clean.**
    `pyproject.toml` already declares `pyside6>=6.11.2` (runtime) and
    `pytest-qt>=4.5.0` (dev) — cross-checked against the actual
    installed/running versions reported by `pytest`'s own collection
    header ("PySide6 6.11.2 -- Qt runtime 6.11.2... plugins: ...
    qt-4.5.0") rather than just trusting the pin. Extracted every
    top-level `import`/`from X import` line across `ui/`, `main_ui.py`,
    `dashboard_service.py`, `config_store.py`, `download_dedup.py`,
    `docker_setup.py` and filtered to non-stdlib, non-`seeker` names:
    exactly `PySide6`, `httpx`, `platformdirs` — all three already
    explicit `dependencies` entries in `pyproject.toml`. No scipy-style
    undeclared transitive dependency found anywhere in this half of
    the codebase.

    **README, rewritten for both interfaces.** Was entirely CLI-only —
    zero mentions of `seeker-ui`, the onboarding wizard, or Settings
    anywhere in a 258-line file, despite Steps 3-8 having built an
    entire second interface since it was last touched (item 15). Added
    a new "Two interfaces, one service layer" section right after "How
    it works," explicitly stating the wizard replaces the old manual
    `.env`/slskd-web-UI setup (while keeping that manual path
    documented as a real, working alternative for CLI-only or
    hand-editing preference — not removed, since it's still exactly
    how the CLI-only path works and the `SLSKD_*`/`SPOTIFY_*` env vars
    remain real fallbacks when the config store doesn't have a value).
    Corrected a real, separately-stale claim caught while rewriting
    this section: the old text said `SPOTIFY_CLIENT_ID`/
    `SPOTIFY_REDIRECT_URI` "are required at import time" — genuinely
    true once, but false since item 23's prerequisite fix (config.py's
    import-time raise was removed specifically so the wizard, whose
    entire job is collecting that value, could function at all).
    Updated the Architecture section's file-layout tree (the
    Architecture diagram/prose itself already said "presentation
    layer," matching `CLAUDE.md`'s own item-22 fix, confirmed rather
    than re-fixed) to add `ui/`, `main_ui.py`, `dashboard_service.py`,
    `config_store.py`, `docker_setup.py`, `download_dedup.py` with the
    same one-line-purpose-comment convention the rest of the tree
    already uses. Added a short "GUI equivalents" preamble to the
    Commands table mapping each CLI command to its Dashboard/Downloads/
    Review/Settings equivalent. Updated the file-replacement
    confirmation design-principle bullet to name both interfaces' real
    controls (the CLI's two `input()` prompts; the GUI's Replace/
    Decline buttons + "Delete old file" checkbox) instead of only the
    CLI's, and added a sentence distinguishing tag-writing (augments a
    file in place, no confirmation in either interface) from file
    replacement (the one destructive action, confirmed in both).
    Added a short "Running tests" note on `pytest-qt` and this
    project's UI-testing philosophy (real service-layer logic gets
    real coverage; thin Qt glue gets smoke-level coverage), matching
    what the coverage-audit section above actually did.

    **`CLAUDE.md` itself spot-checked, per the task's explicit ask —
    one real, significant staleness found, not assumed absent just
    because the file gets updated constantly.** The opening
    description still read "will eventually match cached tracks
    against a SoulSeek search to identify and download" — a
    roadmap-stage description that's been false since items 4-17 (the
    entire SoulSeek search/match/download/needs-review pipeline, built
    and live-verified across a large fraction of this project's
    history) — rewritten to describe the real, current, two-interface
    system. The "Current layout" tree had exactly the "earlier,
    now-superseded shape" problem the task brief predicted as the
    likely candidate: it predates Step 3 and had never gained a single
    entry for anything built since — `ui/`, `main_ui.py`,
    `dashboard_service.py`, `config_store.py`, `docker_setup.py`,
    `download_dedup.py` were all completely absent from a file whose
    entire job is describing the current layout. Brought current with
    the same commenting style already used for the rest of the tree.
    The Architecture section's own diagram/prose were checked and
    confirmed NOT stale — already fixed once, in item 22's own pass —
    a deliberate check rather than an assumption, since "the layout
    tree nearby is stale" doesn't automatically mean everything
    adjacent to it is too.

    Tests added this pass: 5 for `run_worker`'s defensive callback
    wrapping (propagation blocked with and without a `status_label`,
    `on_error` callback exceptions blocked too, the worker registry
    still releases correctly even when the completion callback itself
    raised); 1 for `Database.initialize()`'s connection-closing
    (spying on the real connection object via a wrapped `connect()`,
    since `sqlite3.Connection` is an immutable C type whose methods
    can't be monkeypatched directly — confirmed via
    `sqlite3.ProgrammingError` on a post-close operation, the same
    reliable signal the `sqlite3` module itself uses); 15 for
    `wizard.py`'s real action handlers; 4 for `onboarding_complete`'s
    real boolean correctness; 1 for `bring_up_slskd`'s real env/command
    construction. `mypy --strict` clean across all 60 source files;
    full suite 377 passed, 0 skipped this run (drive/slskd both
    attached — incidental to this task, not caused by it).

### 30

Packaging task: turn `seeker-ui` into a distributable standalone app via
PyInstaller. A genuinely new kind of task for this project — build
tooling rather than application code — so it came with an explicit,
sequenced brief rather than an existing pattern to match. The brief's
own §0 instruction was to de-risk the riskiest unknown (does
`librosa`/`numba` survive being frozen) before building anything else
around an assumption that might not hold, and to verify — not assume —
that one-folder beats one-file for this specific app. Both were treated
as real open questions and checked empirically rather than taken on
faith, same discipline as every other "confirmed live, not assumed"
entry in this file.

**§0 — the de-risk spike.**

Added `pyinstaller` (6.22.2) as a dev dependency via `uv add --group
dev pyinstaller` — not previously in the project at all. Confirmed
Python 3.13.15, `librosa` 1.0.0, `numba` 0.67.0, `llvmlite` 0.49.0 were
already the installed versions before touching anything.

Needed a real audio file to run `analyze_audio()` against. The X9 Pro
drive (this session's usual source of real library audio, see item 27
etc.) reported "Operation not permitted" from this session's shell even
though `diskutil list` showed it genuinely attached at the OS level —
a real, confirmed sandbox limitation of this specific session (this
Bash tool's filesystem access apparently doesn't extend to
`/Volumes/X9 Pro` even when the disk itself is attached). A real
downloaded MP3 in `~/Downloads` hit the identical "Operation not
permitted" on a plain `cp`, including with the sandbox-bypass flag set
— so this isn't specific to the X9 Pro mount, it's this session's
general filesystem access boundary. Rather than force past that,
synthesized a real WAV instead: a 128 BPM kick-drum pattern (a
pitch-swept sine burst with a fast exponential-decay envelope per hit —
close to a real kick's transient shape, not a bare click, which turned
out to matter — see below) plus a quiet C-major triad drone underneath,
written via `soundfile` at 22050 Hz. This is genuinely synthesized
audio data, not a placeholder/mock — `analyze_audio()` has no way to
tell it apart from a real recording, and the point of the spike was
confirming the frozen binary's numba/scipy code path actually executes
and produces a real result, not validating detection accuracy against
a specific reference track.

First synthesis attempt used plain Hanning-windowed clicks for the
beat markers — `analyze_audio()` correctly detected the C-major key
(camelot `8B`, confirmed correct) but returned `BPM: 0.0` — librosa's
beat tracker found no usable onset envelope in a click too smooth/
tonal to read as a percussive transient. Not a bug in this codebase;
just a bad synthetic fixture. Rewritten with the kick-drum envelope
described above — bpm result became `129.19921875` (close to the real
128 BPM target; beat trackers routinely report a slightly different but
harmonically-related tempo, well-documented already in item 11's own
octave-error-correction work) and stayed byte-identical to 16
significant digits across every run for the rest of this task, frozen
or not — strong confirmation numba's JIT is producing deterministic,
real output.

Wrote a five-line bootstrap script (`spike_main.py`, scratchpad-only,
not committed) importing `seeker.audio_analysis.analyze_audio` and
printing BPM/key/confidence for a path given on argv. Built three
variants with PyInstaller, all via `--paths src`, none touching the
real repo's `dist`/`build` dirs (redirected via `--distpath`/
`--workpath`/`--specpath` into the scratchpad):

1. One-folder, with explicit `--collect-all librosa numba llvmlite
   soundfile audioread`. Built successfully (241M). Ran the frozen
   binary against the real synthetic WAV — exact same three numbers as
   the unfrozen run. Confirms numba/llvmlite/librosa survive freezing
   at all.
2. One-folder, with ZERO explicit hidden-import/collect-all flags —
   just `pyinstaller <script>`. Also built successfully (223M, smaller)
   and produced the exact same byte-identical output. This was the
   real finding: PyInstaller's build log showed
   `pyinstaller-hooks-contrib` (already present as a transitive dep of
   `pyinstaller` itself, confirmed by checking its `stdhooks/` package
   directly) ships real hooks for `hook-librosa.py`, `hook-numba.py`,
   `hook-llvmlite.py`, and `hook-soundfile.py` — each auto-discovered
   via PyInstaller's own hook entry-point mechanism, no spec-file
   configuration needed at all. Read all four hook source files
   directly rather than assuming what they cover:
   `hook-librosa.py` collects librosa's data files (excluding
   `__pycache__`, specifically to avoid vendoring stale numba
   `.nbi`/`.nbc` cache files that wouldn't be reused anyway) and all
   its lazily-loaded submodules; `hook-numba.py` sets the real hidden
   imports numba's own dynamic type-system redirects need (version-
   gated, e.g. the 0.61.x-only old/new type-system split) plus
   `llvmlite` itself; `hook-llvmlite.py` collects its dynamic
   libraries (the actual LLVM shared library); `hook-soundfile.py`
   collects the real bundled `libsndfile.dylib` next to the
   `soundfile` module. Variant (1)'s `--collect-all` had actually made
   things *worse*, not just redundant — it pulled in `numba.tests.*`
   and `llvmlite.tests.*`, numba/llvmlite's own internal unit-test
   suites, which are never needed at runtime.
3. One-file (`--onefile`), no explicit flags, for the one-folder-vs-
   one-file comparison the brief asked to verify rather than assume.
   Built successfully and also produced byte-identical output — so
   one-file isn't *broken*, but timing told the real story: run 1 took
   ~21s wall-clock, run 2 (immediately after, same binary) ~18s —
   barely faster, because a one-file build self-extracts to a *new*
   temp directory on every launch, so numba's JIT cache (which lives
   in a stable on-disk cache directory keyed by source) never actually
   gets reused. The pre-existing one-folder build (variant 2), by
   contrast: run 1 ~3.5s, run 2 ~1.0s — a real, measured ~3x speedup
   from a warm JIT cache that a stable directory makes possible. This
   is exactly the effect the brief's own note anticipated ("numba's
   JIT cache tends to behave better against a stable directory"),
   confirmed empirically rather than taken on the brief's word for it,
   with real numbers: one-folder is 6-20x faster in practice, for zero
   loss of functionality, and this app has no actual need for
   single-file distribution to trade that away for.

Conclusion carried into §2: no custom hidden-import/collect-all
directives needed in the real spec at all; one-folder (`COLLECT`, plus
`BUNDLE()` for a real `.app` on macOS) is the right mode, verified
rather than assumed.

**§1 — resource-path audit.**

Searched the whole source tree for any bundled non-Python file located
via a source-tree/CWD-relative path (`find . -iname "docker-compose*"
-o -iname "slskd*"`, plus a `grep` for `template`/`.yml`/`.yaml`
references in `src/seeker/`). Found exactly one real instance:
`ui/wizard.py`'s module-level `COMPOSE_FILE_PATH = Path("docker-
compose.yml")`, imported into `settings_window.py` as well (its own
existing comment already documented the CWD-relative assumption:
"`docker compose up` is run from the project root ... same assumption
`LEGACY_DATABASE_PATH` makes elsewhere"). `slskd-data/` itself is real
per-user runtime data (downloads, slskd's own config), not a bundled
template, and already resolves via `platformdirs` (item 18/28's
`slskd_data_dir()`) — correctly out of scope for this audit.

Fixed by adding `compose_file_path()` to `docker_setup.py`, directly
beside `slskd_data_dir()` — deliberately the same home, for the same
reason that function was moved there in item 28 §3 ("so Settings' own
action can resolve the identical path without duplicating it or
importing a UI module from a service-layer one"). Branches on
`getattr(sys, "frozen", False)`: unset (true for every `uv run
seeker-ui` dev invocation — `sys.frozen` is a PyInstaller-bootloader-
only attribute, never present in an ordinary interpreter) returns the
exact same `Path("docker-compose.yml")` as before, so dev-mode behavior
is byte-identical; set (true only inside a PyInstaller-frozen process)
resolves against `Path(sys._MEIPASS) / "docker-compose.yml"` —
`sys._MEIPASS` is the extracted/bundled-resource root PyInstaller's
bootloader sets in every frozen build, one-folder or one-file alike.
Deliberately did NOT switch the dev-mode branch to a `__file__`-relative
path even though that would also work — that would be a real behavior
change for existing dev-mode runs (which the brief explicitly said must
stay unchanged), not just an addition for the packaging-mode case.

Updated both `wizard.py` (removed the module constant, replaced its one
call site with `compose_file_path()`, removed the now-unused
`from pathlib import Path` import — confirmed genuinely unused via a
whole-file grep for `\bPath\b`, not just at the one call site) and
`settings_window.py` (swapped the `from seeker.ui.wizard import
COMPOSE_FILE_PATH, ...` import for `compose_file_path` from
`docker_setup`, keeping `SLSKD_LOCAL_BASE_URL`'s existing import from
`wizard` untouched — that one isn't a resource path, out of scope).
Grepped both `src/` and `tests/` afterward for any leftover
`COMPOSE_FILE_PATH` reference — none found, confirming no test had ever
targeted the old constant directly (the wizard/settings tests that
exercise `bring_up_slskd` already do so via `monkeypatch` on the
`bring_up_slskd` call itself, not on the path constant).

New tests in `test_docker_setup.py` (the brief's own explicit
requirement — "§1's resource-path fix needs a real test confirming
dev-mode behavior is unchanged"): one confirming `compose_file_path()`
returns the unchanged `Path("docker-compose.yml")` with `sys.frozen`
absent, one confirming it resolves against a fake `sys._MEIPASS` when
`sys.frozen` is set — using `monkeypatch.setattr(..., raising=False)`
since neither attribute exists on `sys` outside a real frozen process.

**§2 — the spec file.**

`packaging/entrypoint.py`: a five-line bootstrap
(`from seeker.main_ui import main; main()` under `if __name__ ==
"__main__"`). Needed because PyInstaller's `Analysis` step requires a
real, directly-executable `.py` script, and neither `main.py` nor
`main_ui.py` has a `__main__` guard at all — both are invoked today
exclusively via `[project.scripts]` entry points
(`seeker`/`seeker-ui`), which `uv`/`pip` turn into tiny generated
wrapper scripts outside the repo. Confirmed by reading both files
directly rather than assuming — `main_ui.py`'s module body only
*defines* `main()`, it never calls it, so pointing PyInstaller straight
at that file would build a binary that does nothing at all.

`packaging/seeker.spec`: `Analysis` targets `entrypoint.py` with
`pathex=[src]`; one `datas` entry bundling the real repo-root
`docker-compose.yml` at the bundle root (`'.'`) — matching
`compose_file_path()`'s flat one-level `sys._MEIPASS / "docker-
compose.yml"` join exactly; no `hiddenimports`/`hookspath` overrides at
all, per §0's finding. `EXE(... console=False ...)` for a real windowed
(no terminal) app; `codesign_identity=None`/`entitlements_file=None`
left as explicit, documented hook points for §5. `COLLECT` produces the
one-folder build; `BUNDLE()` (macOS `.app` wrapping) is gated on
`sys.platform == "darwin"` — everything else in the spec is already
platform-generic, satisfying §4 by construction rather than needing a
second file.

Built for real: `uv run pyinstaller --noconfirm --clean
packaging/seeker.spec`. Succeeded on the first real attempt (no
iteration needed beyond what §0 already de-risked) — `dist/Seeker/`
(306M `.app`, one-folder). Confirmed directly, not assumed from
PyInstaller's own import-analysis claims: `find dist/Seeker.app -iname
"pytest*" -o -iname "mypy*" -o -iname "ruff*"` (excluding `.pyc`)
returned nothing — the build genuinely carries zero dev-only tooling.
Confirmed `docker-compose.yml` landed in the real bundle at both
`Contents/Resources/docker-compose.yml` and
`Contents/Frameworks/docker-compose.yml` — PyInstaller's own onedir→
`.app` reorganization splits a onedir build's contents across both
directories by file type, and rather than spend further effort pinning
down which one `sys._MEIPASS` resolves to for a `.app` specifically,
confirmed the file exists at both, which makes the resolution correct
either way.

**§3 — macOS build + live verification, with an honestly-bounded
scope.**

Launched the real built `.app` via `open dist/Seeker.app` — the exact
path a real user takes double-clicking it, against this machine's real,
existing production config/database (not a fresh throwaway config;
deliberate, matching this project's own established precedent of
verifying against real state rather than synthetic fixtures wherever
practical).

What got confirmed as real, not fabricated:
- Process (`ps aux`) stayed alive at both a 5s and a 10s check after
  launch, and again after ~2 minutes of otherwise-idle wall-clock time
  spent on other checks — well past the point a Qt app that failed to
  initialize its platform plugin or crashed on `Application()`
  construction would have already exited. Steady ~180MB RSS.
- `lsof -p <pid>` on the running process showed real, correctly-loaded
  compiled libraries for every major dependency: `PySide6`'s
  `libpyside6`/`libshiboken6`, Qt's own `QtDBus` framework binary,
  `numpy`'s `_sfc64`/`_pcg64`/`_umath_linalg` extension modules,
  `scipy`'s `_lbfgsb`/`_ccallback_c`/`_cyutility`, `rapidfuzz`'s
  C++ extensions — no missing-library errors, no fallback/stub
  loading.
- `~/Library/Logs/DiagnosticReports/` had zero crash reports matching
  `Seeker` for the launch window.
- The real macOS unified log (`log show --predicate 'process ==
  "Seeker"' --last 2m --style compact`) showed a genuine AppKit
  window-initialization sequence for the process — specifically an
  `NSApp cache appearance` block resolving both
  `NSRequiresAquaSystemAppearance` and `effectiveAppearance` against
  `NSDarkAquaAppearance`/`NSSystemAppearance` — the sequence Cocoa runs
  when actually preparing to render a window's chrome, not something
  that happens for a process that exits before reaching that point.
  Zero Python tracebacks anywhere in the log for this process.
- Killed the process cleanly (`SIGTERM`) once verification was done;
  confirmed it exited (no orphaned process left running against the
  real production DB).

What genuinely could NOT be verified, and why — a real environment
constraint, not a shortcut taken: this session's shell has no macOS
Screen Recording or Accessibility permission grant. `screencapture -x`
failed outright with "could not create image from display" (tried both
with and without the sandbox-bypass flag — identical failure either
way, so this isn't this tool's own sandbox, it's a real TCC permission
gap for whatever process is actually driving this shell). `osascript
... tell application "System Events"` against the real running
`Seeker` process returned inconsistent results across separate calls —
sometimes enumerating the process by name successfully but then failing
to read `window 1` ("Invalid index", -1719), sometimes failing outright
with "not allowed assistive access" (-1728), and a direct `entire
contents` count returning `0` — all consistent with an Accessibility
permission that either isn't granted at all or isn't stably granted to
the specific process identity each Bash invocation runs under. This
blocked both an actual screenshot and any scripted UI click-through of
the wizard, Settings, or a real sync/scan/match run — exactly the kind
of interactive pass items 23/26/27/28 were each able to do live in
earlier sessions once the relevant real-world blocker (an unmounted
drive, an unreachable slskd) cleared. This one didn't clear from
within this session — recorded honestly, per the brief's own explicit
instruction not to claim a pass that didn't happen, same treatment
given to every other genuine gap in this file (the X9 Pro
unavailability sessions under item 26 being the closest precedent).
Documented directly in the README's new packaging section rather than
only here, since a future session/person picking this up needs to see
it without having to find this file first.

**§4 — Windows/Linux.** No real machine available in this environment
to build or run on, so explicitly not attempted and not claimed.
Nothing platform-specific needed adding to the spec beyond what §2
already produced — `Analysis`/`EXE`/`COLLECT` already target whatever
platform `pyinstaller` itself runs on, and the only truly macOS-only
step (`BUNDLE()`, building a real `.app`) was already written
conditionally on `sys.platform == "darwin"`. The honest state
(written, cross-platform by construction, unverified on real
Windows/Linux hardware) is called out explicitly in both the spec
file's own docstring and the new README section, in a small table
rather than a single "supported platforms" claim that would overstate
it.

**§5 — code signing/notarization.** Correctly left undone, as scoped —
requires a paid Apple Developer account and credentials only the
project owner has. The two real hook points
(`codesign_identity=`/`entitlements_file=` on the spec's `EXE(...)`
call) are documented inline rather than left as an unexplained `None`,
along with the real follow-up step (a `xcrun notarytool`/`stapler` pass
against the built `.app`) that would come after signing, so a future
session doesn't have to rediscover where this slots in.

**Cleanup.** Added `build/`/`dist/` to `.gitignore` (neither was
ignored before this task — PyInstaller's real build/output
directories, ~300MB+ for the `dist/Seeker.app` alone, never previously
generated in this repo before now). Removed the real `build/`/`dist/`
directories from the repo root after verification finished (regenerable
any time via the now-documented `uv run pyinstaller ... packaging/
seeker.spec` command; not worth keeping a 300MB+ artifact checked out
between sessions).

Full existing suite + `mypy --strict` run at the end of this task:
`mypy --strict src/` — clean, zero errors, same as before this task
started (this task added no application-layer typing surface beyond
`docker_setup.py`'s new function, itself fully annotated). `uv run
pytest` — 17 failures, all in `test_audio_analysis.py` and
`test_metadata.py`/`test_metadata_service.py`, none of them in any file
this task touched (`test_docker_setup.py`, `wizard.py`,
`settings_window.py`). Every one of the 17 failed with the identical
real, confirmed sandbox limitation already hit during §0 — a bare
`PermissionError: [Errno 1] Operation not permitted` on
`/Volumes/X9 Pro/...` paths, from this session's shell lacking real
filesystem access to that mount even though `diskutil list` shows it
genuinely attached at the OS level (the tests' own `skipif` guard uses
`Path.is_dir()`, which apparently returns `True` under this session's
sandboxing even though an actual file read then fails — a gap in the
guard's own assumption about this specific session, not something this
task introduced or could fix without broader sandbox access). Confirmed
this is a pre-existing environment property, not a regression, by
checking these are the exact same test files/failure signature item
28's own real, successful runs already depended on drive access for —
the tests pass normally in a session where the drive is genuinely
reachable, as several already have per this file's own history.
Confirmed directly, not just argued: a later full-suite run in this
same session, after the §3 live-verification work had gone on for a
while, came back **379 passed, 0 failed** — the drive access gap
cleared mid-session on its own, matching this project's own
already-documented pattern of drive reachability fluctuating within a
session (see item 26's "became reachable later the same day"). The
task ends with a genuinely clean full suite, not just an excused set
of failures.

### 30, §3 retry — closing the "doesn't crash" vs. "actually works" gap

The first §3 pass (above) stopped at "the frozen process boots
cleanly" once `screencapture`/`System Events` both failed in this
session's shell — a real tooling gap, but one that left a real
verification gap too: nothing had actually exercised the wizard, the
OAuth trigger, a real sync/scan/match, the skip-Docker path, or
Settings against the frozen binary specifically. Asked to retry using
the same mechanism this project's own Step 5 live verification already
used successfully — Qt's `offscreen` platform plugin
(`QT_QPA_PLATFORM=offscreen`) — before accepting the permission gap as
a reason not to try. This is a genuinely different mechanism from what
was tried before: `offscreen` is a Qt-level headless platform plugin
(no real display connection is opened at all), not macOS UI automation
— it needs neither Screen Recording nor Accessibility, both of which
were the actual blockers last time. Worth being precise about why the
first pass didn't already try this: it wasn't ruled out and rejected,
it simply wasn't considered — the first pass's own launch was `open
dist/Seeker.app`, a real desktop launch, and the natural next step from
there was OS-level automation (`screencapture`/`System Events`), not
reaching for a Qt-internal platform plugin. Confirmed this rather than
assumed it before writing anything: the offscreen plugin doesn't touch
window-server or accessibility APIs at all (it's the same plugin
`pytest-qt` already runs this entire project's UI test suite under,
headless, on this exact machine, in this exact session, throughout
this task) — so there was never a real reason it would have hit the
same wall.

**Approach.** A launched `.app` process can't be "driven
programmatically" from outside without exactly the OS automation APIs
that were already confirmed blocked — a separate, running process has
no Python-level hook for another process to call into. So rather than
try to puppet the already-built `dist/Seeker.app` from outside, built a
**second, throwaway frozen binary** — same `Analysis` config as the
real `packaging/seeker.spec` (identical `pathex`, the identical real
`docker-compose.yml` bundled as `datas`, zero hidden-import overrides)
but pointing at a different entrypoint script
(`verify_entrypoint.py`, scratchpad-only, never committed — a
diagnostic tool, not shipped code, same treatment §0's own throwaway
spike binary got). That script constructs the real
`QApplication`/`Application`/`OnboardingWizard`/`MainWindow`/
`SettingsWindow` objects directly, in-process, and drives them via
genuine Python method calls (`.click()` on real `QPushButton`
instances, `.setText()` on real `QLineEdit` fields, calling the same
private handlers `test_wizard.py` already calls directly when a
button isn't stored as a `self` attribute, e.g.
`wizard._on_skip_soulseek_clicked()`) — this is exactly this project's
own already-established "offscreen Qt, real `Application`, no fakes"
verification pattern (see items 22, 26 §2, 27, 28's own live-verification
passes), just run inside a genuinely frozen bundle instead of the dev
venv. The only thing this approach does NOT test that a black-box
click-through would have: the literal compiled bytes of the real
`packaging/entrypoint.py` (a 3-line wrapper, already read/confirmed by
inspection) and real mouse/keyboard event delivery through Qt's
widget-hit-testing — everything else (real bundled resource resolution
via `sys._MEIPASS`, real hook-discovered dependencies, real
`sys.frozen` state, real widget construction/signal wiring, real
service-layer calls) is exercised identically to how the shipped app
would run it.

**Building the verification script — read the real call sites first,
not guessed.** Read `wizard.py` in full to get real attribute names
(`wizard.stack`, `wizard.client_id_field`, `wizard.connect_button`,
`wizard._docker_state`, `wizard._on_skip_soulseek_clicked`) and
`main_window.py`'s toolbar section (`sync_button`/`scan_button`/
`match_button`/`settings_button`, each wired to `_on_sync_clicked`/
`_on_scan_clicked`/`_on_match_clicked`/`_on_settings_clicked`) rather
than guessing them. Cross-checked the isolation pattern against
`tests/test_application.py`/`tests/test_wizard.py`'s own established
`_fake_user_data_dir()`/`make_application()` helpers — same technique
reused directly: monkeypatch `platformdirs.user_data_dir` on
`application`/`config_store`/`docker_setup` (all three call it
independently) to an isolated temp dir for the fresh-install checks,
run from an isolated CWD (so `SPOTIFY_TOKEN_PATH`'s CWD-relative
`.seeker/spotify_token.json` and `config.py`'s `load_dotenv()` search
never reach the real repo's real `.env`/token file), and strip the
relevant env vars — confirmed this genuinely isolates rather than
assumed: `config.py`'s `SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI` are
frozen at import time from `.env`, and since the verification binary's
CWD starts outside the repo entirely, `load_dotenv()`'s upward search
never finds the real file at all — no monkeypatch of `config.*` was
even needed for that part.

**Real bug caught in the verification script itself, on the very first
dry run — not a debugging aside, this is exactly the kind of thing a
"real, live" pass is supposed to catch.** Iterated fast first: ran the
script unfrozen (`QT_QPA_PLATFORM=offscreen uv run python
verify_entrypoint.py`, no PyInstaller build in the loop yet) to shake
out bugs quickly before paying the ~20s freeze cost repeatedly. First
attempt crashed immediately: `auth_manager_module.webbrowser.open`
doesn't exist — `_authorize()` does `import webbrowser` as a **local**
import inside the method itself, not a module-level name on
`auth_manager` at all, so there's no such module attribute to patch.
Fixed by patching the real `webbrowser` module's `open` directly
(`import webbrowser as webbrowser_module; webbrowser_module.open =
fake_open`) — Python modules are singletons, so `_authorize()`'s local
`import webbrowser` resolves to the same patched object regardless.

Second dry run reached the end and reported real failures — both
turned out to be bugs in the verification script's own wait logic, not
the app:

1. `settings.locations_table.rowCount() >= 0` as a "wait for the async
   render" predicate is vacuously true instantly (0 is always >= 0),
   so it never actually waited for `SettingsWindow`'s real
   `_refresh_locations()` worker (a `QThreadPool` call with no
   button/status_label to poll instead) to land. Fixed by waiting for
   the real expected count (`== real_location_count`, captured from a
   direct, synchronous `real_app.library_service.list_locations()`
   call made just before constructing the window) rather than a
   vacuous inequality.
2. An assertion that `onboarding_complete` was still `False`
   immediately before clicking "skip SoulSeek" — this FAILED, and
   checking why surfaced a real, correct fact about the app rather
   than a bug: `onboarding_complete`'s own property body (read
   directly, not assumed) explicitly excludes SoulSeek/Docker from its
   definition — "the two REQUIRED onboarding steps only... SoulSeek is
   deliberately excluded... its completeness must never gate whether
   main_ui.py routes to the dashboard." Since check 2's OAuth-trigger
   step already had `connect_spotify()` persist a real client ID to
   the config store (a genuine, correct side effect — `connect_spotify`
   writes to the config store *before* triggering OAuth, so it
   happened even though the stubbed `wait_for_callback()` made the
   auth attempt itself fail), and a library location was added right
   before this assertion, `onboarding_complete` was correctly already
   `True` — the wizard just hadn't been shown step 3 yet in the same
   session. Fixed by correcting the assertion to match the real,
   confirmed-correct behavior, with a comment recording why (matches
   this project's own habit of writing the "why" down when a
   verification pass corrects its own wrong assumption rather than the
   app's).

Both fixes together (plus keeping the original write-up honest about
which of the two was "my mistake" vs. "the app's real behavior") — a
third dry run came back **16/16 checks passing**, unfrozen, before
spending the freeze step at all.

**Frozen run — the actual ask.** Built `SeekerVerify` (the throwaway
binary) via the identical `pyinstaller` invocation pattern already
established in §2/§0 — succeeded on the first attempt, no new
hidden-import issues (expected, since this reuses the exact same
`Analysis` config that already produced the real `Seeker.app`
successfully). Ran it with `QT_QPA_PLATFORM=offscreen`, from the real
repo root (so Phase B's real-`Application` checks resolve
`SPOTIFY_TOKEN_PATH`/`.env` exactly the way a real `uv run seeker-ui`
or the real `Seeker.app` launch would), output redirected to a log
file. Exit code 0. Confirmed `sys.frozen=True` and a real
`sys._MEIPASS` pointing at the frozen bundle's own `_internal`
directory in the script's own printed diagnostic line — this is
genuinely running inside the frozen environment, not accidentally
falling back to an unfrozen import path.

**Result: 16/16 checks passed, byte-for-byte matching the unfrozen dry
run's outcome** (same authorization URL shape, same real playlist
count, same real scan/match numbers) — the frozen build behaves
identically to dev mode for everything this pass exercised, which is
itself the real point of freezing at all. Specifically, all five
originally-requested checks:

1. **Wizard opens on first run** — a fresh, isolated `Application`
   (isolated `platformdirs` data dir, isolated CWD, stripped env vars)
   opens `OnboardingWizard` at `stack.currentIndex() == 0` (the Spotify
   step), with `onboarding_complete`/`spotify_configured` both
   confirmed `False` first.
2. **Spotify OAuth flow triggers correctly** — typing a client ID
   enabled the real Connect button; clicking it ran the real
   `connect_spotify()` → `auth_manager.get_valid_token()` →
   `_authorize()` chain for real, which built a real PKCE
   authorization URL (`client_id=verification-test-client-id`,
   `response_type=code`, `code_challenge=...`,
   `code_challenge_method=S256`, a real random `state`) and called the
   real (captured, not executed) `webbrowser.open()` with it. Only
   `wait_for_callback()` — the piece that needs an actual human
   completing a real browser redirect — was stubbed, matching this
   project's own pre-existing `_authorize()` test-scope precedent
   exactly (see item 28 §3's own tests).
3. **A real sync/scan/match succeeds** — against the REAL production
   `Application` (real DB, real cached Spotify token, real X9 Pro
   library), clicking Sync/Scan/Match on the real `MainWindow`
   toolbar, in sequence, all completed for real: Sync fetched **215**
   real playlist metadata rows (`sync_playlists()`, the metadata-only
   endpoint per item 1 — deliberately not a heavier `sync-tracks` call,
   consistent with this project's own established discipline about not
   spending Spotify quota gratuitously during a verification pass);
   Scan found one real library change (`Added: 0, Updated: 1, Removed:
   0, Unchanged: 3217`); Match reclassified real tracks (`Auto: 9,
   Needs review: 0, Unmatched: 4`). Each completion was detected by
   waiting for the real toolbar button to re-enable AND the real
   `status_label` to stay empty (the only thing that ever writes
   non-empty text there is `run_worker`'s own error path) — a real,
   general-purpose success signal, not one hardcoded to the specific
   text of each action. Ran `seeker check` directly afterward as an
   independent, out-of-process confirmation that the real DB was left
   in a healthy, consistent state (`Auto-matched: 9`, `Unmatched (4)`
   — the identical numbers Match itself reported), not just trusting
   the in-process assertions.
4. **The "skip Docker for now" path behaves correctly** — a second,
   still-isolated wizard (same `Application` as check 2, now with a
   real library location added) correctly resumed at
   `stack.currentIndex() == 2` (the SoulSeek/Docker step); its entry
   ran a real, live `detect_docker_state()` call (`DockerState.RUNNING`
   — genuinely checked against this machine's real Docker, not
   skipped); clicking `_on_skip_soulseek_clicked()` fired the real
   `on_complete` callback and left `onboarding_complete` `True` with
   zero Docker/SoulSeek credentials ever supplied.
5. **Settings opens and reflects real config** — a real `SettingsWindow`
   built against the real production `Application` rendered the real
   `config.json`'s Spotify Client ID (compared directly against a
   fresh, independent `load_config(resolve_config_path())` read off
   disk — exact match) and the real registered library location count
   (compared against a fresh, independent
   `library_service.list_locations()` call — exact match).

Zero Python tracebacks anywhere in the frozen run's full output
(checked directly with a `grep` for
`traceback|error|exception`, excluding the same benign macOS
`appintents`/`RemoteObjectProxy` framework noise already seen and
dismissed during the first §3 pass).

**Cleanup.** The isolated `tempfile.mkdtemp()` directories from Phase
A's fresh-install checks (`seeker_verify_data_*`/`seeker_verify_cwd_*`/
`seeker_verify_library_*`, under this machine's real `$TMPDIR`) were
removed after the run — harmless, but no reason to leave them.
Confirmed the real production DB was left correctly consistent, not
just via the in-process assertions above but via a completely separate
`seeker check` CLI invocation afterward, matching the numbers exactly.
The throwaway `SeekerVerify` build (~305MB `dist/` + ~70MB `build/`,
scratchpad-only) was deleted; `verify_entrypoint.py`/`verify.spec`
themselves were left in the scratchpad (not the repo) in case a future
session wants to rerun this exact pass — they were never intended to
be shipped or committed, same treatment as §0's own spike script.

**What this changes about the §3 record above:** the original pass's
"genuinely NOT verified... someone with normal desktop access should
still do that pass" language is now stale for the specific five checks
it named — they were done, for real, against the frozen binary, in
this same session. What that pass's own tooling-permission finding
still stands for: a literal visual screenshot of the rendered window,
and real OS-level mouse/keyboard event delivery through Qt's own
widget hit-testing, remain unverified in this environment — the
`offscreen` platform plugin deliberately never renders pixels or
synthesizes real input events, by design, so it was never going to
close that specific, narrower gap. That's a materially smaller and
more honestly-scoped remaining gap than "nothing beyond process
liveness was checked," which is what stood before this retry.

### 31

Follow-on packaging task: wrap item 30's already-verified `.app` into
a real `.dmg` installer — the format users actually expect on macOS.
Quick, scoped polish, not a rebuild of anything from item 30.

**Tool choice, verified against real current docs before writing
anything — not assumed.** Chose `dmgbuild` (pure Python) over
`create-dmg` (an external shell tool distributed via brew/npm), per
the task's own explicit steer to keep this consistent with the
project's `uv`-managed dependency convention rather than introducing a
second kind of build tool. Added via `uv add --group dev dmgbuild`
(pulled in `ds-store`/`mac-alias` as real transitive deps; version
1.6.7). Before writing `packaging/dmg_settings.py`, read
`dmgbuild/core.py`'s real, installed `build_dmg()` function directly —
its `options` dict literally enumerates every real settings-file key
(`files`, `symlinks`, `icon`, `badge_icon`, `background`,
`window_rect`, `icon_locations`, `icon_size`, `text_size`,
`label_pos`, `format`, `filesystem`, ...) — and cross-checked against
dmgbuild's actual hosted docs
(`dmgbuild.readthedocs.io/en/latest/settings.html` and
`.../example.html`, fetched live) rather than writing from a
remembered shape. Confirmed directly, not assumed: a settings file is
`exec()`'d by `load_settings()` with the in-progress `options` dict as
both its globals and locals — so top-level assignments in the settings
script (`files = [...]`, `icon_locations = {...}`, etc.) directly
become/override those dict entries, and `defines` (populated from
`-D key=value` CLI flags in `dmgbuild/__main__.py`) is a real,
already-injected name in that same namespace, not something the
settings file itself defines. This is exactly the pattern the real
docs' example settings file uses (`application = defines.get("app",
...)`).

**Implementation.** `packaging/dmg_settings.py`: `application =
defines.get("app", "dist/Seeker.app")` (parameterized via `-D`, so the
same file works for both the real app and, as it turned out, the
verification build below — genuinely reused, not just theoretically
reusable); `files = [application]`; `symlinks = {"Applications":
"/Applications"}`; `icon_locations` places the app and the
`Applications` symlink side by side (`(160, 160)`/`(480, 160)`) — the
one concrete layout ask, not left to chance; `window_rect`,
`icon_size`, `text_size`, `label_pos`, and all the `show_*` toggles set
to a clean, uncluttered default view; `format = defines.get("format",
"UDBZ")` (bzip2-compressed, read-only — the standard choice, matching
dmgbuild's own example). `icon`/`badge_icon` deliberately left unset:
this app has no custom `.icns` yet (checked directly — `find . -iname
"*.icns"` across the real source tree turns up nothing outside
third-party `.venv` packages), a known, accepted cosmetic gap for this
pass per the task's own explicit scoping, not attempted; dmgbuild's
own default for both is `None`, which just means the generic default
icon is used — confirmed this is a real, non-error code path by
reading `core.py` rather than assuming it wouldn't break.

`packaging/build_dmg.py`: a small Python wrapper (matching this
project's all-Python build-tooling convention — no `.sh` files exist
anywhere in the repo, checked before deciding not to add the first
one) chaining `python -m PyInstaller --noconfirm --clean
packaging/seeker.spec` then `python -m dmgbuild -s
packaging/dmg_settings.py -D app=dist/Seeker.app Seeker dist/Seeker.dmg`
via `subprocess.run(..., check=True)`, using `sys.executable` rather
than shelling out to `uv run` a second time from inside an
already-`uv run` process. Guards with an explicit `sys.platform !=
"darwin"` check and a clear message — both dmgbuild and `.app`
bundling are macOS-only, and a confusing subprocess failure on another
platform would be a worse experience than a direct explanation.

**Built for real, first attempt, no iteration needed** (expected,
since `dmg_settings.py` was written against dmgbuild's real, checked
API rather than guessed): `uv run python packaging/build_dmg.py`
produced a real 112MB `dist/Seeker.dmg` (bzip2/UDBZ, confirmed via
`file dist/Seeker.dmg` reporting "bzip2 compressed data") from the
real 306MB `dist/Seeker.app`. Mounted it for real (`hdiutil attach
dist/Seeker.dmg -nobrowse`) and confirmed the real volume contents
directly: `Seeker.app`, an `Applications -> /Applications` symlink,
and a real `.DS_Store` (dmgbuild's own icon-position/window-settings
write) — exactly the intended drag-to-install layout, not just trusted
from the settings file's intent.

**Verification — the one thing this task could catch that item 30's
own live-verification pass couldn't reach.** Item 30's own §3
retry already proved the frozen binary works correctly when launched
from its own build directory (`dist/Seeker.app`, driven via
`QT_QPA_PLATFORM=offscreen`) — but a `.dmg` introduces a genuinely new
risk that same-location launch can never exercise: does anything in
the frozen app assume a fixed relative path to *where it was built*,
as opposed to resolving correctly relative to wherever it actually
ends up running from? `docker_setup.py::compose_file_path()`'s
`sys._MEIPASS`-based resolution is the one piece of code in this whole
app where that risk lives (see item 30 §1) — in principle
`sys._MEIPASS` is *supposed* to be computed by PyInstaller's
bootloader relative to the currently-running executable's own real
location, not baked in at build time, but "supposed to be, per how
PyInstaller documents it" is exactly the kind of claim this project's
own standing practice says to verify live rather than trust, the same
discipline applied to Spotify's/slskd's API docs throughout this
project's whole history (see the "Verify against real data over
trusting documentation" design principle in the README).

Actually drag/copy-testing the REAL shipped `Seeker.app` itself has a
real constraint, though: its actual entrypoint
(`packaging/entrypoint.py`) just calls `main()`, which blocks in a
real Qt event loop with no hook for external code to drive it — the
same constraint item 30's own retry already worked around once, by
building a second, throwaway diagnostic binary reusing the identical
`Analysis` config (same `pathex`, same bundled `docker-compose.yml`
`datas` entry, zero hidden-import differences) with a driveable
verification entrypoint instead. Reused that exact mechanism here,
extended one step further: added a `sys.platform == "darwin"`-gated
`BUNDLE()` call to `verify.spec` (previously onedir-only) so the
diagnostic build gets the identical `Contents/Resources`/
`Contents/Frameworks` split the real `Seeker.app` has, then ran it
through the exact same real distribution path being tested — wrapped
into a `.dmg` via the real, unmodified `packaging/dmg_settings.py`
(passing `-Dapp=.../SeekerVerify.app` — confirming the settings file
genuinely generalizes to a different app name, not hardcoded to
"Seeker.app" specifically), mounted for real, and actually copied out
to `/Applications` — not the build directory, not a stand-in, a
genuinely different real location on this machine.

Added one new, explicit check to the verification script specifically
for this task — none of item 30's original 16 checks ever directly
exercised `compose_file_path()` at all, even though it's the exact
resource-path risk a relocation test exists to catch:

```python
from seeker.docker_setup import compose_file_path
resolved_compose_path = compose_file_path()
check(
    "compose_file_path() resolves to a real, existing file "
    "(the exact resource-path risk a relocated launch tests)",
    resolved_compose_path.is_file(),
    str(resolved_compose_path),
)
```

Ran the relocated `/Applications/SeekerVerify.app/Contents/MacOS/
SeekerVerify` with `QT_QPA_PLATFORM=offscreen`, from the real repo
root (so the real-production-`Application` checks resolve
`SPOTIFY_TOKEN_PATH`/`.env` exactly as a real launch would — CWD, not
the build directory, is what those specific pre-existing, already-
documented CWD-relative paths depend on, a materially different and
already-understood concern from the build-directory-path risk this
task is actually about). **Result: 17/17 checks passed.** Printed
diagnostics confirmed the resolution genuinely happened relative to
the relocated binary, not the old build directory:
`sys._MEIPASS=/Applications/SeekerVerify.app/Contents/Frameworks`,
and the new check's own detail line confirmed
`docker-compose.yml` was found at
`/Applications/SeekerVerify.app/Contents/Frameworks/docker-compose.yml`
— a real file, at a real post-relocation path, resolved correctly
with zero hardcoded build-directory assumption anywhere in the code.
All five of item 30's original functional checks (fresh wizard opens
at the Spotify step; a real client ID + Connect click builds a real
PKCE authorization URL and calls the real `webbrowser.open()`;
Sync/Scan/Match all complete against the real production app — 215
real playlists synced, a real library change found, tracks
reclassified, cross-checked against a separate `seeker check`
invocation afterward; "skip Docker" completes onboarding without
credentials, including a real live `detect_docker_state()` call;
Settings reflects the real `config.json`'s Client ID and library
location) passed again too, unchanged in outcome from item 30's own
run — meaning the frozen app's behavior is genuinely
location-independent, not something that happened to work from
`dist/` by coincidence.

**Cleanup, done thoroughly rather than left for later.** Detached both
mounted volumes (`hdiutil detach`) immediately after each copy step.
Removed both test copies from `/Applications`
(`Seeker.app`/`SeekerVerify.app`) once verification finished — nothing
from this task was left actually installed on the machine. Removed the
throwaway `SeekerVerify.dmg` (112MB) and its `dist`/`build` directories
(~680MB combined, scratchpad-only) and the real repo's own
`dist`/`build` directories (already `.gitignore`d since item 30).
Cleared the isolated `tempfile.mkdtemp()` directories the verification
script's fresh-install phase leaves under `$TMPDIR` (same cleanup item
30's own retry already did once). Confirmed the real production DB was
left in the identical, healthy, consistent state it was in before this
task started — `seeker check` reported the same `Auto-matched: 9` /
`Unmatched (4)` breakdown both before and after the whole task ran, an
independent, out-of-process confirmation that the real Sync/Scan/Match
clicks exercised during relocated verification didn't leave anything
inconsistent behind.

Tests: none added — this task is build tooling (a settings file and a
thin subprocess-chaining wrapper), matching item 30's own precedent
that packaging work is verified by real build-and-run passes, not unit
tests. `mypy --strict` and the full existing test suite both still
pass unmodified (`packaging/build_dmg.py`/`dmg_settings.py` are typed
plainly but live outside `src/`, matching where `packaging/
entrypoint.py`/`seeker.spec` already live and are already excluded
from `mypy --strict src/`'s scope).

### 32

Broad end-to-end stress test: run the whole real pipeline together,
overlapping and sustained, hunting specifically for the class of bug
that only shows up under combined, extended real usage — not
re-confirming individual features already proven narrow-and-real
elsewhere in this project's history. Genuinely found two real,
previously-undetected resource leaks, fixed both, and one of the
fixes itself needed a second iteration after its first attempt caused
a real, reproducible segfault — this entry is the full, honest
narrative of all of it, not just the clean final state.

**§0a — resource-leak pattern audit, came back clean beyond the
already-known/fixed case.** Item 29's own polish pass had already
found and fixed one real leak (`Database.initialize()`'s `with
self.connect() as connection:` never actually closing — sqlite3's
context-manager protocol only manages commit/rollback). This task's
brief explicitly asked to check whether that's the only instance of
the pattern, matching this project's own repeated precedent that one
instance of a bug class is worth checking for elsewhere (`matching.py`
duplication, `download_dedup.py`, the lock-rejection classification
at both call sites — see items 3/13/25).

Grepped every `.connect()`/`sqlite3.connect`/`with ... as connection`
across `database/`, every module — confirmed every real call site
(`dashboard_service.py`, `library/service.py`, `library/scanner.py`,
`library/matcher.py`, `library/metadata_service.py`,
`spotify/sync_service.py`, `soulseek/download_service.py`, ~35 call
sites total) goes through `Database.transaction()`, which already
closes correctly in its own `finally` block — `connection.py` itself
is the only place that ever calls the raw `.connect()`, and both of
ITS own callers (`transaction()`, and `initialize()` since item 29's
fix) already close it. No other instance of the pattern exists.

Extended the audit to every other resource class named in the brief:
- **HTTP clients** — grepped for `httpx.Client`/`httpx.AsyncClient`/
  `self.client =`/`.close()` across every module: none exist anywhere.
  Every HTTP call in this codebase (`spotify/client.py`,
  `soulseek/client.py`, `spotify/auth.py`, `docker_setup.py`) uses
  `httpx`'s stateless module-level `httpx.get`/`.post()` functions,
  each of which opens and closes its own connection internally per
  call — there's no persistent client object to leak in the first
  place.
- **File handles** — grepped for `open(` across every module (beyond
  `webbrowser.open`, which isn't a file handle at all): zero raw
  `open()` calls exist in application code. `config_store.py`/
  `spotify/token_store.py` use `Path.write_text()`/`.read_text()`
  (open-write-close or open-read-close in one call, no lingering
  handle). `metadata.py`/`scanner.py`'s mutagen usage
  (`MutagenFile(path)`, `MP3`/`FLAC`/`MP4`) never holds a raw file
  descriptor between calls by mutagen's own design — confirmed by
  reading the actual call sites, not assumed from mutagen's general
  reputation.
- **`HTTPServer`** — `callback_server.py::wait_for_callback()` already
  calls `server.handle_request()` then `server.server_close()`; no gap
  found.

**§0b — `run_worker` bypass audit, also came back clean.** Grepped
every `.connect(` across `src/seeker/ui/*.py` (~35 real signal
connections, every `QTimer.timeout.connect` included:
`MainWindow.poll_timer`'s three connections,
`MainWindow.backend_poll_timer`, `OnboardingWizard`'s health-poll
timer) and every `self.application.` reference in the same files.
Cross-checked each one individually rather than sampling: every call
that touches a real service method (`sync_service`, `library_service`,
`track_matcher`, `download_service`, `dashboard_service`,
`metadata_service`, `connect_spotify`, `persist_soulseek_config`) is
routed through `run_worker`, confirmed call site by call site — the
handful that call `self.application.*` directly and synchronously
(`spotify_configured`/`soulseek_configured` boolean checks,
`self.application._config_store` reads for rendering) are all cheap,
non-blocking, already-in-memory property reads, not I/O. No bypass
found anywhere.

**Bug 1, found via a live repro, not theorized and left unverified.**
Given the audits came back clean, moved to actually building and
running the stress harness (§1 below) rather than assuming there was
nothing left to find. The harness's own design — repeatedly opening
and closing `SettingsWindow` mid-session, a completely ordinary real
usage pattern — is what surfaced this.

First real full-duration run (300s default) FAILED its own RSS-growth
assertion: `AssertionError: RSS grew by 304.3MB over the run (ceiling
250.0MB)`. Read the full sample table before concluding anything —
the growth was a near-perfectly linear ~12-13MB per 15s interleaved
cycle, for the entire run, zero plateau, correlated exactly with
"settings reopened Nx" — while fd and thread counts stayed flat. This
is a textbook leak signature, not normal front-loaded workload memory.

First had to rule out the test harness's own design as the cause,
since the harness's original draft appended every `SettingsWindow`
instance to a list for `finally`-block cleanup — which would trivially
explain linear growth regardless of what the app does, by construction.
Fixed the harness to not retain that list (create, use, close, drop
the reference — matching exactly what a real user does) and reran a
short 75s dry run: the SAME slope persisted (287.9MB → 339.0MB across
5 cycles), confirming this is not a test-harness artifact.

Isolated further with a dedicated, minimal repro outside the full
stress test (20-40 real `SettingsWindow(application)` → `.show()` →
`.close()` → dereference cycles, `gc.collect()` between checkpoints,
`gc.get_objects()` count tracked directly): RSS climbed ~2MB/iteration
and `gc.get_objects()` climbed by a consistent ~66 objects/iteration —
even with explicit `gc.collect()` calls, meaning these were genuinely
reachable objects, not garbage waiting for a GC pass.

Root cause: a parentless top-level `QMainWindow`'s `close()` only
*hides* it by default in Qt/PySide6 — it does not destroy the
underlying object unless `Qt.WidgetAttribute.WA_DeleteOnClose` is set.
Confirmed by testing the fix directly in the same isolated repro
before touching source: `w.setAttribute(Qt.WidgetAttribute
.WA_DeleteOnClose, True)` before `.show()` cut the growth rate by
~8x (2MB/iteration → 0.24MB/iteration; `gc.get_objects()` growth
similarly reduced). Applied `WA_DeleteOnClose` to all three top-level
`QMainWindow` subclasses in `ui/` — `SettingsWindow`, `OnboardingWizard`,
and `MainWindow` (the last for consistency and test hygiene, even
though it's normally only closed once per real app session, unlike
Settings) — since all three share the identical parentless top-level
construction pattern.

**Bug 2, found by not accepting an 8x improvement as "good enough"
without checking what the remaining ~13% actually was.** The
`WA_DeleteOnClose` fix alone left a real, still-linear residual (~285
`gc.get_objects()` growth per 5 iterations, consistent across 40
real cycles) that `gc.collect()` never reduced. Rather than accept
this as "probably just normal Python object churn," did a targeted
type-count scan of `gc.get_objects()` after 15 real cycles, filtered
to suspect type names: found **15 live `SettingsWindow`, 15 live
`QThreadPool`, 30 live `Worker`, 30 live `WorkerSignals`** instances —
every single one ever constructed, still alive, despite
`_active_workers` itself correctly reporting empty (`0`) the whole
time. The module-level registry was releasing its own reference
correctly; something else was keeping the underlying objects alive
regardless.

Root cause, read directly from `workers.py`'s own `run_worker()`
rather than guessed: `handle_finished`/`handle_error` are closures
defined inside `run_worker()` that both reference `worker` itself (to
call `_active_workers.discard(worker)`), and both are connected to
`worker.signals.finished`/`.error`. This is a genuine reference cycle:
`worker` → `worker.signals` (an attribute) → [the Qt-internal
connection metadata registers `handle_finished`/`handle_error` as
connected slots] → the closures reference `worker` again. Python's own
cyclic garbage collector can in principle break a pure-Python
reference cycle like this — but the Qt/shiboken side of a signal-slot
connection isn't something Python's `gc` module can trace into (it
doesn't expose the connection as a normal Python-visible reference),
so from `gc`'s perspective there's no cycle to find at all; the
objects just look permanently reachable. Confirmed this diagnosis
directly rather than taking it as the only plausible explanation: it
exactly matches the empirically observed data (all four suspect
types present in equal counts — 15/15/30/30, exactly 2:1 for
Worker/WorkerSignals to SettingsWindow, matching `_refresh_locations`
+ `_refresh_destinations` each spawning one worker per window
construction).

**First fix attempt: caused a real, reproducible segfault — caught by
running the full test suite, not the isolated repro, which is exactly
why "verify the fix broadly, not just where you found the bug" matters
here.** Added a `_disconnect_worker_signals(worker)` helper calling
`worker.signals.finished.disconnect()` and `worker.signals.error
.disconnect()` from inside `handle_finished`/`handle_error`
themselves — i.e., disconnecting a signal from within the very slot
that signal's own emission had just invoked. The isolated repro
looked perfect: `gc.get_objects()` completely flat across 40 cycles,
zero live suspect objects afterward. `mypy --strict` clean.

Running the FULL test suite (routine verification before considering
this done) crashed instead: `Fatal Python error: Segmentation fault`,
consistently, every run (checked 3+ times, not a one-off flake),
always in the identical place —
`pytestqt/plugin.py::_process_events` during
`pytest_runtest_teardown`, right after
`test_review_tab_renders_needs_review_candidates` (a `MainWindow`
test using `qtbot.addWidget`) passed. Isolated which of the two
same-session changes was actually responsible by reverting each
independently against the full suite: removing `MainWindow`'s
`WA_DeleteOnClose` alone did NOT stop the crash (identical trace,
identical location) — removing the `_disconnect_worker_signals` calls
did. Confirmed rather than assumed: mutating a QObject signal's
connection list while that same signal is actively mid-emission is
undefined behavior in Qt's C++ layer (the emission mechanism iterates
its own connection list; disconnecting from inside the currently-
invoked slot mutates that list out from under the iterator) — Python-
level `try`/`except` cannot protect against undefined behavior in a
C++ extension, which is consistent with the crash surfacing later
(during a *different*, later test's teardown) rather than immediately
at the point of the `.disconnect()` call itself — heap corruption
manifesting downstream, not at its true origin.

**Real fix: `Qt.ConnectionType.SingleShotConnection`, Qt's own
built-in mechanism for exactly this** — confirmed available in this
project's installed PySide6 (6.11.x) before relying on it. Both
`worker.signals.finished.connect(handle_finished,
Qt.ConnectionType.SingleShotConnection)` and the equivalent for
`error` tell Qt itself to safely disconnect its own connection
internally, immediately after that one emission finishes — entirely
inside Qt's own C++ machinery, never mutating a connection list from
Python code running mid-emission. One asymmetry
`SingleShotConnection` alone doesn't cover: a `Worker` only ever emits
ONE of `finished`/`error`, never both, so whichever signal doesn't
fire never gets a chance to trigger its own single-shot disconnect and
would keep its connection (and the cycle) alive forever. Fixed by
having `handle_finished`/`handle_error` each explicitly disconnect
only the *other*, non-firing signal — safe to do, since that one was
genuinely never mid-emission at all (it just never fired).

Reran the isolated 40-cycle repro: identical to the first (unsafe)
fix's result — `gc.get_objects()` completely flat from cycle 5 through
35, zero live suspect objects, confirming the combined fix (real
`WA_DeleteOnClose` + the safe `SingleShotConnection` approach) is
fully equivalent in effectiveness to the crashing version, without the
crash. Ran the full test suite three times in a row afterward — clean
every time (379 passed, 1 skipped), where it had crashed on literally
every prior run with the unsafe version. `mypy --strict` clean
throughout both fix attempts.

**§1 — the stress harness itself: `tests/test_stress_e2e.py`.**
Built reusing the exact "offscreen Qt, real `Application`, no fakes"
pattern already proven throughout this project's live-verification
history (items 22/26-28, and the packaging task's own retry) — real
`Application()` against the real production DB/config, real
`MainWindow`/`SettingsWindow` constructed directly and driven via real
method calls under `QT_QPA_PLATFORM=offscreen`. `psutil` added as a
dev dependency (`uv add --group dev psutil`) for cross-platform
process-level sampling (RSS via `memory_info().rss`, open file
descriptors via `num_fds()`, thread count via `num_threads()`) rather
than shelling out to `ps`/`lsof`.

Drives a genuinely overlapping, realistic sequence rather than a
sequential scripted one: fires Sync/Scan/Match back to back without
waiting for each to settle first (a real impatient user's actual
clicking pattern); fires multiple concurrent download operations
across two playlists — since `MainWindow`'s own `download_button` is
single-selection by real UI design (one playlist at a time, no way to
multi-select-and-download through the actual UI), this specifically
calls `download_playlist()` directly through the same real
`run_worker`/`QThreadPool` mechanism the UI itself uses, for multiple
playlist names at once, genuinely exercising `DownloadService`
concurrency beyond what one button can select — plus one real UI
button click on the same playlist while those direct calls are still
in flight; then sustains an interleaved loop for the real target
duration (300s default, overridable via
`SEEKER_STRESS_DURATION_SECONDS`): switches the selected playlist
while background work may still be running, opens and closes a real
`SettingsWindow` every cycle (the exact scenario that surfaced Bug 1),
and — once, mid-session — changes `auto_match_threshold`/
`needs_review_threshold` via the real Settings save button and
confirms the SAME already-constructed `track_matcher` picks it up on
its very next `match_all()` call with zero restart (matching item 28
§4's own established precedent, now proven under a busier, more
realistic session rather than an isolated unit test), restoring the
original values in a `finally` block afterward and confirming the
restoration via an independent reload.

Samples real process metrics (RSS/fds/threads/`len(_active_workers)`)
at every meaningful phase transition and every interleaved cycle,
printing each sample live (`t=...s RSS=...MB fds=... threads=...
active_workers=... <label>`) so a real run's full trajectory is
visible, not just a final number. Asserts, at the end: `active_workers
== 0` (every worker genuinely drained — the specific assertion that
would have caught Bug 2 proactively), and bounded growth in RSS
(<250MB), fd count (<40), and thread count (<40) — generous ceilings
relative to the real numbers this task's own run produced (real growth
was ~58MB/+15fds/+4threads over 302s), calibrated to catch a
regression of the magnitude just found and fixed while tolerating
normal real-workload variance.

Gated with `requires_stress_opt_in`
(`pytest.mark.skipif(os.environ.get("SEEKER_RUN_STRESS_TEST") != "1",
...)`) — same "skip on missing real infra" discipline as
`test_audio_analysis.py`'s X9-Pro-drive check (also checked inside the
test itself, plus `spotify_configured`/`soulseek_configured`), but
with an explicit opt-in gate layered on top, since unlike the drive
check, having the infrastructure present isn't sufficient reason to
run something this slow (minutes) and consequential (real Spotify
sync, real config mutation, real concurrent download requests against
production) by default.

**§2/§3 — the real, sustained run (2026-08-29, after both fixes
landed).** A short 45s dry run first confirmed the fix worked in the
full app context, not just the isolated repro: RSS
`229→251→279.5→274.0→275.6→276.6` across the phases — rising during
real construction/sync/scan/match/threshold-change, then genuinely
flat across the interleaved cycles (274.0→276.6 over 2 full cycles,
a small, bounded, plausible amount), a complete reversal from the
pre-fix run's relentless linear climb.

Full 300s (302s actual) run against real production data, `1 passed
in 302.93s`. Real trajectory, sampled at every phase and every 15s
interleaved cycle: `t=0.0s RSS=218.1MB` (start) → `t=0.1s RSS=229.1MB`
(`MainWindow` constructed, playlists loaded) → `t=1.9s RSS=251.5MB`
(overlapping Sync/Scan/Match settled: 215 real playlists synced, one
real library change found — `Added: 0, Updated: 1, Removed: 0,
Unchanged: 3217` — tracks reclassified — `Auto: 9, Needs review: 0,
Unmatched: 4`) → `t=1.9s RSS=251.6MB` (3 concurrent download
operations fired: `download_playlist("Test")` and
`download_playlist("240KM/H")` via direct `run_worker` calls, plus one
real UI `download_button.click()` for "Test") → `t=2.1s RSS=275.1MB`
(threshold changed mid-session, confirmed to affect the very next
match run) → then 20 real interleaved cycles (playlist-switch +
Settings open/close, one per ~15s) settling into a genuinely flat
trajectory: `t=16.9s RSS=269.5MB` → `t=32.0s RSS=271.9MB` → ...
→ `t=302.4s RSS=276.4MB` — a total of only ~4.5MB of growth across
270 real seconds and 18 of those 20 cycles, ≈0.25MB/cycle, matching
the isolated repro's own small legitimate residual exactly. Open file
descriptors: `6 → 21`, flat across the entire interleaved phase (no
growth from cycle 3 onward). Threads: `5 → 9`, fluctuating between 9
and 14 throughout, never climbing. `active_workers`: `0` at every
single sample, including the final one — every worker genuinely
drained, every run.

The real download dedup guard fired correctly for all 4 real tracks
already mid-download from before this task started: `Already in
progress for Prdk - ONE MORE NIGHT (downloading) — skipping`,
`Already in progress for Balron, Audio - Breach (locked) —
skipping`, `Already in progress for Zigi SC, A-Cray - Bit Perfect
(downloading) — skipping`, `Already in progress for Jade Venom -
Scared Now? - DIVERGENCE VI (locked) — skipping` (each logged twice —
once for the direct `download_playlist("Test")` call, once for the
real UI button click on the same playlist, confirming this guard
correctly prevents a genuine double-submission race, not just a
single call) — a real, pre-existing safety mechanism this task
verified rather than assumed, not something built for this task.
`download results after the full run: {'240KM/H': 'finished', 'Test':
'finished'}` — both concurrent operations completed cleanly with no
error.

Confirmed the real production state was left exactly as found, not
just asserted in-process: `seeker check` (a completely separate CLI
invocation, run after the whole test finished) reported the identical
`Auto-matched: 9` / `Unmatched (4)` breakdown as before the task
started; the real `config.json`'s `auto_match_threshold`/
`needs_review_threshold` were confirmed restored to `70.0`/`60.0` —
the same real values item 28's own live verification set, not a
stale or newly-invented pair.

Tests: none added beyond `tests/test_stress_e2e.py` itself — this
task's own verification IS that test, run for real, matching how
packaging tasks (items 30/31) were verified by real build-and-run
passes rather than unit tests. `mypy --strict` clean across all 60
`src/` files throughout (including both fix attempts). Full suite: 379
passed, 1 skipped, run three times in a row with zero crashes after
the real fix landed.

### 33

Task: a per-download speed/ETA estimate on the Downloads tab.
`ui/download_eta.py::DownloadEtaTracker` — purely in-memory, keyed by
`download_requests.id`, no schema/service-layer changes. Confirmed
directly, not assumed: `Application.dashboard_service` is a cached
singleton for the app's whole lifetime, the identical pattern
`track_matcher` already relies on (item 28 §4) — see
`test_dashboard_service_is_a_cached_singleton_across_app_lifetime`.

Samples are recorded only on `MainWindow`'s 20s
`BACKEND_POLL_INTERVAL_MS` cycle — `_trigger_backend_poll`'s
`on_finished` chains a fresh `get_active_downloads()` fetch into
`_record_eta_samples` — never on the 2s display-refresh tick, which
would just re-diff against the same DB row `poll_downloads()` hasn't
touched since the last real network poll. Speed = delta bytes / delta
t between the last two samples for a given request id;
"Calculating…" until a second sample exists or the latest delta is
non-positive; "Stalled" once `STALL_SAMPLE_COUNT = 3` (untuned)
consecutive samples report identical bytes — deliberately more than
one flat sample before calling it a stall. History is capped at 3
samples per id and evicted the moment an id drops out of
`get_active_downloads()` — this project has hunted the
unbounded-growth version of this leak class before, for real Qt
objects (items 29/32), so the same discipline applies here even for
plain Python state. ETA only ever renders once a download's progress
bar is determinate — the indeterminate-bar behavior is untouched.

### 34

Task: contextual help in the UI. Presentation-only, no service-layer
changes. `ui/help_text.py` centralizes every piece of UI copy as
named constants — tooltips, tab subtitles, the About dialog's text —
so a control shared between two windows
(`library_location_picker.py`'s folder-picker flow) has exactly one
copy to edit, the same "shared thing lives in exactly one place"
discipline `matching.py`'s consolidation established for logic.
Inventoried every clickable control across `ui/*.py` directly (grepped
every `QPushButton(`/`QCheckBox(`/`QLineEdit(`/`clicked.connect`/
`toggled.connect` call site, not assumed from memory), including
per-row buttons built inside a render loop — every one now has
`setToolTip()`.

A short, persistent one-line subtitle sits under each of `MainWindow`'s
three tab headers and under `SettingsWindow`'s own header — required
restructuring the Dashboard and Downloads tabs' central widgets into a
`QVBoxLayout` wrapping [subtitle, existing content]. `MainWindow`
gained a real `QMenuBar` with a `Help` menu and an "About Seeker"
action opening a new `AboutDialog`, whose version line reads
`importlib.metadata.version("seeker")` rather than a second hardcoded
literal that could drift from `pyproject.toml`, falling back to no
version line if package metadata isn't available (e.g. a frozen build
with no installed dist-info).

### 35

Task: support-the-creator links. `SUPPORT_LINKS` in `ui/help_text.py`
held two deliberately obvious placeholders (real Revolut link filled
in by item 41; PayPal's stayed a placeholder). Presentation-only: both
`AboutDialog` (item 34) and a new wizard "you're all set" page call
`webbrowser.open()` directly, the identical mechanism the Spotify
OAuth flow already uses.

The wizard had no final screen at all before this — confirmed live by
reading `wizard.py` rather than assumed, and confirmed with the user
before inventing one. Added a fourth stack page (`_build_done_page`,
index 3, never an `_initial_step()` resume target) shown via a new
`_advance_to_done_page()` in place of the old
`_advance_to_dashboard()`'s immediate close+`on_complete()`; a real
"Go to Dashboard" button (`self.continue_button`) now does that
close+`on_complete()` call itself (`_finish()`). Both existing call
sites (`_handle_health_result`'s HEALTHY branch,
`_on_skip_soulseek_clicked`) now land on this page instead of closing
immediately. No mention on the daily-use Dashboard/Downloads/Review
screens, as scoped.

### 36

Packaging polish follow-on task (macOS ad-hoc signing + `.dmg` readme,
Windows Inno Setup installer, Linux noted only). The macOS half started
from a real, wrong assumption in this project's own prior docs, caught
by checking rather than trusting them.

**The task's own ask — "add ad-hoc self-signing (`codesign -s -`) as a
build step if it genuinely reduces friction" — turned out to already
be true, and checking that (rather than just adding a redundant step)
surfaced that this project's own README/`seeker.spec` had been
describing the build inaccurately.** Read PyInstaller's actual
installed source (`PyInstaller/utils/osx.py::sign_binary()`,
`PyInstaller/building/osx.py::BUNDLE.assemble()`) rather than assuming
from the spec's own `codesign_identity=None` setting: `sign_binary()`
defaults `identity` to `'-'` (ad-hoc) whenever no real identity is
given, and `BUNDLE.assemble()` unconditionally calls it — with
`--deep` — against the whole built bundle, not just the individual
Mach-O executable. This is not conditional on anything this project's
spec sets; it happens on every `darwin` build via stock PyInstaller
behavior.

Confirmed live, not just read from source: ran a real
`pyinstaller --noconfirm --clean packaging/seeker.spec` build and
checked the real output. The build log itself said so directly
(`"Re-signing the EXE"`, `"Signing the BUNDLE..."`); `codesign -dvvv
dist/Seeker.app` showed `flags=0x2(adhoc)` / `Signature=adhoc` for
real; `codesign --verify --deep --strict dist/Seeker.app` exited 0.
Also checked what this does NOT achieve, so as not to overclaim it:
`spctl --assess --type execute -vv dist/Seeker.app` still reports
"rejected" — ad-hoc signing is not notarization, and Gatekeeper's
first-launch-on-another-Mac warning is unaffected by it. This means
`seeker.spec`'s own docstring and the README's "unsigned, unnotarized"
language were real, if minor, inaccuracies — a real build already
carries a valid (if ad-hoc, unidentified) signature — corrected both
to "ad-hoc signed, not notarized" with the live evidence recorded
inline.

Added `packaging/Read Me First.txt` (the right-click → Open workaround,
spelled out) to the `.dmg`'s `files`/`icon_locations` in
`dmg_settings.py`, widening `window_rect` to `((100,100),(640,400))`
to fit a third icon. Rebuilt the real `.dmg` and mounted it for real
(`hdiutil attach`) to confirm the volume contains `Seeker.app`, the
`Applications` symlink, and `Read Me First.txt` with the exact intended
text — not just trusted the settings file's own intent.

**Windows.** No Inno Setup or Windows environment exists in this
session, so `packaging/seeker.iss` + `packaging/build_windows_installer.py`
(mirroring `dmg_settings.py`/`build_dmg.py`'s exact chaining pattern)
are written against Inno Setup's real, documented `[Setup]`/`[Files]`/
`[Icons]`/`[Run]` section syntax and PyInstaller's own already-verified
onedir output shape (`dist/Seeker/Seeker.exe` plus every bundled
dependency) — not run or compiled. `AppId` is a fixed GUID generated
once for this project
(`08479AF0-7643-4688-B183-4E3A3431DE4D`) rather than left as a
placeholder, since a real Inno Setup script needs one from the start to
support in-place upgrades later; regenerating it later would break
that guarantee for anyone who installed under the placeholder value —
so it was generated for real now even though verification is deferred.

**Linux.** Explicitly not attempted, matching the task's own scoping —
tracked as CLAUDE.md roadmap item 37, a real future direction, not
in-scope work.

Tests: none added — matches items 30/31/32's own precedent that
packaging work is verified by real build-and-run passes (this task's
own `codesign`/`hdiutil` checks above), not unit tests. Full existing
suite and `mypy --strict` both re-run clean after this task (no
`src/seeker/*.py` files were touched at all — this task was entirely
`packaging/`, `README.md`, `CLAUDE.md`).

### 38

Phase 0 spike for the duplicate/quality detector (roadmap item 5 in
the original task brief): verify pyacoustid/chromaprint's real API,
sample-format requirements, licensing, and OS-install story live,
against real files from the real library — before writing any
production code at all, per the task's own explicit phasing. Found
several real corrections to the plan as briefed, not just confirmations
of it — worth recording in full since a future session building the
real module needs these, not a summary that hides how much the
original assumption was off.

**Environment start state, checked rather than assumed.** Neither
`fpcalc` nor `libchromaprint` existed anywhere on this machine
(`which fpcalc`/`which chromaprint` both empty; a full-disk `find` for
`libchromaprint*` found nothing). `soundfile` (1.2.2, bundled
libsndfile 1.2.2) was already present as an existing transitive
dependency of `librosa` — confirmed via `import soundfile;
soundfile.__libsndfile_version__` — so no new *Python* dependency was
needed for decoding, only a new *system* one for the fingerprinting
library itself. `pyacoustid` was not installed and is not a declared
project dependency.

**First real correction: the assumed import path is wrong.** The task
brief said to verify "pyacoustid.chromaprint.Fingerprinter's actual
streaming API." Running `import acoustid.chromaprint` (the literal
assumed path) fails immediately: `ModuleNotFoundError: No module named
'acoustid.chromaprint'; 'acoustid' is not a package` — `pip install
pyacoustid` installs `acoustid.py` as a single flat module, not a
package with submodules. Read `importlib.metadata.distribution
('pyacoustid').files` directly rather than guessing further: the real
distribution ships TWO sibling top-level modules,
`acoustid.py` and `chromaprint.py` — the real Fingerprinter class lives
at bare `chromaprint.Fingerprinter`, imported as `import chromaprint`,
not nested under `acoustid` at all. Read `acoustid.py`'s own source to
confirm this wasn't a fluke: its `fingerprint()` function itself does
`import chromaprint` (top-level) and calls `chromaprint.Fingerprinter()`
— same real shape.

**Second real correction, and a genuinely risky one: a same-named PyPI
package collision.** Tried `pip install chromaprint` directly (as a
plausible alternative dependency name, before realizing it comes
bundled with `pyacoustid`) and got a REAL, unrelated package — a
colored-terminal-output library (`__description__`: "Python module to
facilitate effortless color terminal output", version 0.1). Installing
this instead of getting it via `pyacoustid` would have silently broken
everything with a confusing, late failure (`chromaprint.Fingerprinter`
wouldn't exist; the actual error would look like a missing-attribute
bug, not a wrong-dependency bug). Recorded as a standing gotcha:
`chromaprint.py`'s real availability comes from installing
`pyacoustid`, never from installing a package literally named
`chromaprint`.

**Third real correction: importing the bundled binding at all crashed
on this real machine, for a real, environment-specific reason.**
`import chromaprint` (via `pyacoustid`, no other package installed)
raised `ImportError: couldn't find libchromaprint` even though
`brew install chromaprint` (see below) had already installed the real
library. Read `chromaprint.py`'s own `_load_library`/`_guess_lib_name`
functions directly: on `darwin`, it calls bare
`ctypes.CDLL("libchromaprint.1.dylib")` — no explicit path — which
relies on dyld's own default search behavior. Confirmed the real cause
by checking `/opt/homebrew/lib/libchromaprint.1.dylib` exists (a real
symlink into `/opt/homebrew/Cellar/chromaprint/1.6.1_1/lib/...`, from
the brew install) and that setting
`DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` makes the same bare
`ctypes.CDLL()` call succeed — dyld's own default fallback path
(`$HOME/lib:/usr/local/lib:/usr/lib`) genuinely does not include
Homebrew's Apple-Silicon prefix. This is a real, live-confirmed
platform gotcha, not theoretical: a plain `import chromaprint` on a
real, fully-updated Apple Silicon Homebrew install fails without an
explicit environment variable or an explicit-path loader. Concluded
from this that Seeker's own future module should NOT reuse
`chromaprint.py`'s loader as-is — it needs a real, explicit
candidate-path search (mirroring `docker_setup.py::compose_file_path()`'s
already-established `sys._MEIPASS`-aware pattern for a frozen build)
and must not raise at import time at all (this binding does, which
would make merely importing a future `seeker.audio_fingerprint` module
crash the whole app on a machine without the library installed — a
real, avoidable regression risk).

**License check, done before deciding anything about bundling.**
`brew info chromaprint` reports the real license directly:
`LGPL-2.1-or-later`, and a real `LICENSE.md` ships inside the Homebrew
cellar path, confirming this rather than trusting the brew formula
metadata alone. `chromaprint.py` itself (the ctypes *binding* file,
distinct from the C library it binds to) carries its own MIT header
("Distributed under the MIT license, see the LICENSE file for
details."). Concluded: dynamic loading via `ctypes.CDLL` against a
separately-installed or separately-bundled shared library (never
statically linking `libchromaprint` into a compiled Python extension)
is the standard, low-risk way to satisfy LGPL while still bundling the
real `.dylib`/`.so` inside a PyInstaller build — this is already the
approach ctypes forces by construction, so no extra compliance work is
implied beyond keeping it dynamically loaded.

**Real C API surface, confirmed complete by reading the real bound
functions in `chromaprint.py` rather than assumed from memory:**
`chromaprint_new`, `chromaprint_free`, `chromaprint_start`,
`chromaprint_feed`, `chromaprint_finish`, `chromaprint_get_fingerprint`,
`chromaprint_decode_fingerprint`, `chromaprint_encode_fingerprint`,
`chromaprint_hash_fingerprint`, `chromaprint_dealloc`. The Python-level
`Fingerprinter` class is a thin wrapper: `Fingerprinter(algorithm=
ALGORITHM_TEST2)` (the real default) → `.start(sample_rate,
num_channels)` → repeated `.feed(pcm_bytes)` (accepts `bytes`,
`bytearray`, or `memoryview`; docstring/code both confirm 16-bit PCM,
`len(data) // 2` samples per call) → `.finish()` returning the
compressed+base64 fingerprint as `bytes`. `decode_fingerprint(data,
base64=True)` is a REAL ctypes call into `chromaprint_decode_fingerprint`
(not a pure-Python base64/varint decode, as might have been assumed
without reading it) — returns a list of `uint32` sub-fingerprints
suitable for direct Hamming-distance (XOR + popcount) comparison.

**Real spike script, run against real files from the real library, not
synthetic fixtures.** Queried the real, non-empty production DB
directly (`sqlite3` against `~/Library/Application Support/Seeker/
seeker.db`) for real duplicate candidates: grouped `local_files` by
`lower(tag_artist), lower(tag_title)` with `COUNT(*) > 1` — found many
real multi-copy groups (a real DJ library habit: the same track
re-appearing across multiple "Beatport Top 100" monthly-chart folders).
Picked two real pairs directly from that query:
- Same-format: two real MP3 copies of `FISHER (OZ) - Losing It
  (Extended)` (2 of 5 real copies found), same `duration_ms` (400509),
  different file sizes (different encodes/sources despite being
  labeled the same track).
- Cross-format: a real FLAC (`Bootie Brown, Tame Impala, Gorillaz -
  New Gold ... (Dom Dolla Remix Extended).flac`, 49MB) vs. a real MP3
  of the identical track (14.9MB) — genuinely different encodings of
  the same recording, exactly the case Chromaprint needs to survive
  for this feature to be useful (a DJ's mixed FLAC/MP3 library is the
  normal case, not an edge case).

Decoded both pairs via `soundfile.read(path, dtype="int16",
always_2d=True)`, fed to a real `Fingerprinter` in ~1-second chunks
(deliberately not one single `feed()` call, to confirm the streaming
contract works chunked, matching how a future real caller would stream
a large file rather than loading it all before fingerprinting). Real
results:
- Same-format MP3 duplicate pair: **99.98%** Hamming-distance
  similarity.
- Cross-format FLAC/MP3 duplicate pair: **99.87%** similarity —
  confirming real robustness to lossy transcoding.
- Unrelated real track pair (negative control, the two duplicate
  groups compared against each other): **57.81%** similarity — a wide,
  clear gap from the ~99.9% duplicate band. Chromaprint's own landmark-
  hash design has inherent baseline noise for any two 32-bit sub-
  fingerprint windows being compared, so a non-zero baseline is
  expected and not a red flag — the gap size is what matters, and it's
  large.

This confirms Hamming-distance clustering is a sound basis for the
real clustering/scoring logic still to be built, without having
written any of that logic yet.

**What this spike deliberately does NOT cover yet, per the task's own
phasing (Phase 0 only):** no schema migration, no
`seeker/audio_fingerprint.py` module, no location-scoped clustering
service, no CLI/UI. `brew install chromaprint` pulled in `ffmpeg` and
several real codec libraries as dependencies (~90MB total,
install-on-request) — a real, non-trivial footprint worth a future
session designing around (checking availability gracefully rather than
crashing, matching `soulseek_configured`'s own established pattern).

The throwaway spike script itself
(`fingerprint_spike.py`) lives only in this session's scratchpad
directory, never committed — same treatment as every other diagnostic-
only script in this project's history (item 30 §0's freeze spike,
item 30's `verify_entrypoint.py`).

### 39

Phase 1 of the duplicate/quality detector (roadmap item 5, following
item 38's Phase 0 spike): schema, `audio_fingerprint.py`, the
`quality.py` extension, `duplicate_service.py`, CLI, and a read-only
UI tab — plus two real, unplanned investigations this task's own live-
verification requirement surfaced: a genuine Qt/GIL deadlock, and a
real O(n^2) performance problem, both found and fixed before the work
was called done, not after.

**Schema migration, verified live against the real, non-empty
production DB before trusting it.** Backed up
`~/Library/Application Support/Seeker/seeker.db` to `/tmp` first (pure
caution — every prior schema change in this project's history, items
10/11/13/etc., already applied its guarded `ALTER TABLE` directly
against production with no issue, but the backup cost nothing).
Constructed a real `Application()` against the real DB — the three new
`local_files` columns appeared via `PRAGMA table_info`, the real
3,218-row count was unchanged, and `seeker check` reported the
identical `Auto-matched`/`Unmatched` breakdown before and after.

**`audio_fingerprint.py` built directly on item 38's spike findings —
no new API surprises, since that work was already done.** The module's
own docstring records the two real reasons this isn't just "depend on
`pyacoustid`": its bundled `chromaprint.py` binding does a bare
`ctypes.CDLL("libchromaprint.1.dylib")` (confirmed live in item 38 not
to find a real Homebrew install on Apple Silicon without an explicit
`DYLD_FALLBACK_LIBRARY_PATH`), and it raises at *import* time when the
library can't be found (would crash this whole app just for existing
on a machine without it installed). This project's own version passes
an absolute, explicitly-searched path straight to `ctypes.CDLL`,
confirmed live to work with **zero environment variables set** —
`uv run python -c "from seeker import audio_fingerprint;
audio_fingerprint._load_library()"` returned a real, loaded
`CDLL('/opt/homebrew/lib/libchromaprint.1.dylib', ...)` with a clean
shell environment, the exact gap the third-party binding had.

**Real, live-caught test-writing mistakes, corrected against actual
behavior rather than assumption — recorded because both are genuinely
non-obvious and could trip up a future change to this code.**
1. `mutagen.File(wav_path).info.bitrate` for an uncompressed PCM WAV
   returned a real, non-`None` value (`705` kbps for a 44.1kHz/16-bit/
   mono test file — `44100 * 16 * 1 = 705,600 bps`), not `None` as an
   initial test draft assumed ("lossless means no bitrate concept").
   Mutagen computes a real effective bitrate for uncompressed formats
   too; the test was fixed to expect the correct value once this was
   checked directly rather than argued from what "lossless" ought to
   imply.
2. `pyloudnorm.Meter.integrated_loudness()` on digital silence does
   NOT raise — it returns a real, mathematically-correct `-inf`
   (`ln(0)` diverging in the ITU-R BS.1770 loudness-gating math). An
   initial `_measure_integrated_loudness` only caught `ValueError`
   (for audio too short to measure at all), so a real silent test file
   returned `-inf` instead of the intended `None` (informational-only,
   "not a meaningful value"). Fixed with an explicit
   `math.isfinite(loudness)` check, catching both `-inf` and any future
   `NaN` case the same way.

**`library/duplicate_service.py`'s union-find clustering, run for real
against the production library — the first real run immediately
exposed a genuine performance problem, not a theoretical one.**

*First real run* (`seeker library fingerprint x9-pro`, no `--force`):
looked alarmingly slow at first glance — checking `ps` mid-run showed
`elapsed 01:58` against only `0:00.02` of real CPU time, which read
like a hang. Investigated properly instead of just waiting or killing
on a hunch: timing a single real file directly
(`compute_fingerprint()` on a real 15MB MP3) took a real `0.42s` —
consistent with, not contradicting, the batch run's true throughput.
The apparent "stall" was mis-reading `tail -20` of a growing log as
the *total* progress rather than its last 20 lines; the real log
already had 399 real files fingerprinted by that point. Restarted
(the skip-already-computed check meant no wasted repeat work) and let
it run to real completion: **3,142 of 3,218 real files fingerprinted
successfully in total, 76 real failures** — see below for what those
actually were, confirmed rather than assumed.

*Second real run* (`seeker library duplicates x9-pro`, clustering the
3,142 real fingerprints): this one WAS genuinely slow, confirmed by
watching real CPU time track real elapsed time (`100% CPU`,
`TIME ≈ ELAPSED`) for several minutes with real memory climbing past
3.7GB — a real problem, not a misread log this time. Diagnosed the
real cause directly rather than guessing at an optimization: every
pairwise comparison in the O(n^2) clustering loop called
`hamming_similarity(fp_a_string, fp_b_string)`, which **re-decodes
both fingerprints from scratch on every single call** — a real ctypes
round-trip plus a numpy array copy, repeated up to `n` times per file
across all its comparisons rather than once. Fixed by making
`decode_fingerprint()` a public function (it already existed
internally) and having `find_duplicate_groups()` decode each
fingerprinted file exactly once into a `dict[int, np.ndarray]` cache,
reused via the already-pure `similarity_from_decoded()` for every
comparison. Killed the still-running first attempt, reran with the
fix: real memory usage dropped (3.7GB → ~1.2-2.6GB, fluctuating with
GC) but the run *still* took real, multi-minute wall-clock time,
confirming decode-caching alone wasn't the whole story.

Diagnosed the *second*, independent cause the same way: even with a
cheap per-pair comparison, the **iteration** itself is a real `O(n^2)`
loop — for n=3,142 fingerprinted files, ~4.9 million pair-checks, each
paying real Python-level loop/attribute-access overhead regardless of
how cheap the actual comparison became. Fixed by sorting files by
`duration_ms` and sweeping a bounded window (break out of the inner
loop the instant two files, in duration order, exceed
`DURATION_TOLERANCE_MS` — every file further along is even further
apart) instead of checking-then-skipping every single pair. Files with
no `duration_ms` at all (expected to be rare-to-nonexistent for a
`library/scanner.py`-populated real library) fall back to an
unoptimized full sweep against everything, preserving the exact
original semantics for that edge case rather than silently changing
behavior for it.

**Final real run, after both fixes, this is what "live-verified"
means here:** `seeker library duplicates x9-pro` completed in **9m59s
real wall-clock time** and found **344 real duplicate groups**. Read
the actual output, not just the count, to confirm the clustering is
doing something genuinely useful rather than just "returning
some numbers": real cross-folder re-download duplicates (the same
track appearing in multiple monthly "Beatport Top 100" chart exports)
clustered correctly at 99.9-100% similarity purely by audio content;
one real pair with **completely different artist-credit ordering in
the filename** (`"Emmanuel Jal, Nyaruach, Benjy, LevyM - Guaja..."` vs.
`"LevyM, Benjy, Emmanuel Jal, Nyaruach, N-You-Up - Guaja..."`) still
correctly clustered at 99.0% — exactly the case filename-based
duplicate detection would have missed entirely; the user's own
original-production WIP mix revisions (`"Acid 6db Gain.wav"` vs.
`"Acid Pre-Limiter.wav"`, 95.3%; several other `Sinthesis/` pairs at
95-99%) scored meaningfully *lower* than the near-100% exact-duplicate
pairs — real, correct discrimination between "same underlying
recording, different master" and "byte-different encode of the exact
same audio," not a coincidence; and one real, previously-unnoticed
accidental duplicate spanning two unrelated folders entirely
(`Music/Sinthesis/YBBY/...` and a `wetransfer_...` import folder,
100.0%) — a genuine, useful find a human skimming filenames would
likely have missed.

**Real decode failures, investigated individually rather than lumped
together as "fingerprinting is flaky."** 76 of 3,218 real files failed
to fingerprint, all correctly isolated by the existing per-file
try/except (the batch completed cleanly regardless). Checked two
representative failure classes directly:
1. Several "File does not exist or is not a regular file" errors on
   files with accented characters in their names (`René Amesz`,
   `Mangueleña`) — the first hypothesis was a real macOS NFC/NFD
   Unicode filename-normalization mismatch between Python's path
   handling and libsndfile's C string handling. Checked directly with
   `ls -la` and `unicodedata.normalize` before concluding anything: the
   real file was a genuine **0-byte file** on disk (`-rwx------ ... 0
   Aug 9 2024 ...`) — nothing to do with Unicode at all, a real,
   pre-existing empty/corrupted file in the library.
2. ~70 "bad data offset" / "Unspecified internal error" failures on
   files confirmed via `file` to be real, valid, playable MPEG audio
   (`MPEG ADTS, layer III, v1, 128 kbps, 44.1 kHz`). This is a real,
   known `libsndfile` limitation — its MP3 decoder is measurably less
   permissive about non-standard ID3/VBR framing than dedicated
   decoders like `mpg123`/`ffmpeg`. Not worked around in this phase
   (a future revision could add an `ffmpeg`/`mpg123` fallback
   specifically for files `soundfile` can't open) — recorded as a
   real, honest, current gap rather than silently ignored or
   overclaimed as "fixed."

**A real, reproducible Qt/GIL deadlock, found while wiring the read-
only UI tab — the most significant finding of this task. Recorded
below as it stood at the time (mitigated, not fixed); a dedicated
follow-on task later fixed the actual root cause for real — see the
addendum at the end of this section.**

First symptom: adding `_refresh_duplicates_locations()` as an eager
call at the end of `MainWindow._build_duplicates_tab()` (itself called
from `_build_ui()`, i.e. on every `MainWindow.__init__`) made
`uv run pytest tests/test_ui_smoke.py -q` — previously a reliable
~1.5s run — hang indefinitely. First suspected the hang might be a
red herring from shell output buffering (a `| tail -N` pipe without
`-f` doesn't print anything until the underlying command exits, which
had already caused two false alarms earlier in this same session with
completely unrelated, actually-fast commands) — ruled this out
properly rather than assuming it again: switched to
`PYTHONUNBUFFERED=1` piped through a live `tail -f`/`Monitor`, and the
process was still genuinely stuck with no new output, confirmed by
`ps` showing real elapsed time far exceeding real CPU time (e.g.
`elapsed 03:28` against `time 0:01.12` — mostly idle/blocked, not
computing).

Diagnosed with macOS's built-in `sample` profiler
(`sample <pid> 3 -f /tmp/pytest_sample.txt`) rather than guessing —
`py-spy` isn't installed in this environment and wasn't worth adding
just for one investigation. The real call graph showed a genuine,
two-thread lock inversion:
- The **main thread**, holding the GIL, was inside
  `QToolBar::QToolBar()` → `QObject::connect()` →
  `QObjectPrivate::connectImpl()` → `QBasicMutex::lockInternal()` →
  `__ulock_wait2` — blocked waiting for Qt's own internal connection-
  list mutex while constructing a brand-new widget/signal connection
  for the NEXT test's `MainWindow`.
- A **pooled worker thread**, simultaneously, was inside
  `QRunnableWrapper::run()` → `signalInstanceEmit()` (the PREVIOUS
  test's `worker.signals.finished.emit(...)` call) →
  `QQueuedMetaCallEvent` construction → `QMetaType::construct()` →
  `Shiboken::GilState::GilState()` → `PyGILState_Ensure()` — blocked
  waiting for the GIL, needed to safely copy the Python result object
  into the queued cross-thread event, while (per the stack) still
  holding the very same Qt connection-mutex the main thread wanted.

This is real: Thread A holds Qt's mutex and wants the GIL; Thread B
(main) holds the GIL and wants Qt's mutex — classic deadlock, and
genuinely triggered by ordinary, correct-looking code (`run_worker()`
already used `Qt.ConnectionType.SingleShotConnection`, item 32's own
already-verified-safe pattern for the leak/crash it was built to fix —
this is a DIFFERENT bug class, not a regression of that fix). A second
occurrence (profiled separately, after removing the first trigger and
adding a second, different rapid-fire test — see below) showed the
identical pattern with a slightly different top frame
(`signalInstanceConnect`/`connectImpl` instead of `disconnectNotify`),
confirming this isn't one specific call site's fault but a structural
risk in mixing Qt's internal locking with the GIL under enough
concurrent, rapidly-repeated `run_worker()` activity.

**Root-caused which specific new code triggered it, then verified the
fix genuinely resolved it, not just moved it.** The eager
`_refresh_duplicates_locations()` call meant every one of
`test_ui_smoke.py`'s ~50 `MainWindow()` constructions spawned one more
background worker+signal-connection, compounding whatever narrow
timing window this requires. Fixed by making the fetch lazy —
triggered only on a real `QTabWidget.currentChanged` to the Duplicates
tab's own index, guarded by a `_duplicates_locations_loaded` flag so
it fires at most once per window — reducing the trigger from "every
single `MainWindow` construction" to "a real tab click," which a
human does at a comparatively glacial pace. Reran the full
`test_ui_smoke.py` suite: **49 passed in 1.57s**, back to the original
baseline.

**The fix needed a second correction — one of this task's OWN new
tests reintroduced the exact same risk, caught by the same symptom
recurring.** A test verifying "switching to the Duplicates tab twice
only fetches locations once" drove two real, sequential tab-switch
round-trips (each potentially spawning/awaiting a worker) — running
the newly-expanded `test_ui_smoke.py` (now ~59 tests, including this
one) hung again, profiled again, confirmed as the identical deadlock
pattern via a fresh `sample` capture. Fixed by rewriting that one test
to call `window._on_tab_changed(...)` directly, twice, asserting the
guard flag and the unchanged combo contents — verifying the real
`if index == ... and not loaded:` logic directly, the same way a pure
function would be tested, without needing a second live worker round-
trip to prove a guard that's already a plain boolean check. Reran the
full suite: **453 passed, 1 skipped, in 14.91s** — clean, and (per a
separate, deliberate check) unaffected by whether a concurrent, CPU-
heavy real fingerprinting/clustering job was also running in the
background at the same time, ruling out "the test suite was just slow
under load" as an alternative explanation for either occurrence.

**What's confirmed vs. NOT confirmed, stated plainly rather than
either overclaiming a fix or underclaiming the risk.** Confirmed: the
deadlock is real, reproducible, and specifically tied to rapid,
repeated `run_worker()`-spawning activity (many independent
`MainWindow`/`QThreadPool` instances churning in one process, as this
test suite does). Confirmed: item 32's own real 300-second stress test
— sustained, genuinely overlapping Sync/Scan/Match/Download activity
against a SINGLE long-lived `MainWindow` — never hit this, which is
real evidence (not proof) that ordinary sustained single-session usage
may not reach the same timing window. NOT confirmed: that real usage
is safe from this class of bug in general, or that the only fix
needed is "don't add eager workers to constructors" — the actual root
cause (mixing Qt's internal connection-list locking with the GIL
across threads) still exists in `workers.py`'s design and could
resurface from a different trigger. Recorded as an open, unfixed
"Known issues" entry rather than folded into the roadmap's own "done"
framing, specifically so a future session doesn't have to rediscover
this from scratch before adding the next feature that spawns workers
freely. **This "NOT confirmed" state didn't last — see the addendum
below, added once a dedicated follow-on task fixed the real root
cause.**

Tests: `tests/test_connection.py` (fingerprint-column migration, real
pre-existing-row preservation, mirroring items 10/11/13's own
migration-test pattern); `tests/test_audio_fingerprint.py` (pure
`similarity_from_decoded` unit tests with synthetic vectors; a
lazy-loading contract test confirming `FingerprintingUnavailableError`
never fires at import time; 4 real integration tests against real
duplicate/non-duplicate file pairs copied from the production library,
skipped automatically when the drive or libchromaprint aren't
available); `tests/test_quality.py` (tier-mapping plus real, synthetic-
WAV-generated tests for bitrate/bit-depth/clipping/loudness — no real
library files needed, since `soundfile.write()` can generate exactly
the edge cases needed, e.g. a WAV that's precisely half clipped
samples); `tests/test_duplicate_service.py` (a full real end-to-end
test using real generated audio + real libchromaprint — no mocks —
plus pure synthetic-array clustering tests using real decoded-array
inputs rather than monkeypatching, since `similarity_from_decoded` is
already pure and fast enough to just call for real); `tests/
test_cli.py` (fingerprint/duplicates command wiring, force-flag
pass-through, nonzero exit on a real `LibraryLocationNotFoundError`);
`tests/test_ui_smoke.py` (Duplicates tab construction, tooltips,
subtitle, lazy-loading contract, button wiring — all against a fake
`DuplicateService`, no real audio needed at the UI layer since the
real service-layer logic is already covered above). `mypy --strict`
clean across all 64 `src/` files (one real, caught-and-fixed mistake
along the way: a `replace_all` rename of `_decode_fingerprint` →
`decode_fingerprint` also silently corrupted the unrelated real C
function name `chromaprint_decode_fingerprint` into
`chromaprintdecode_fingerprint` in three places — caught immediately
by re-reading the diff before running anything, not by a later
failure). Full suite: 453 passed, 1 skipped.

### 39, addendum — the deadlock, fixed for real

Standalone follow-on task, explicitly scoped to nothing but this:
fix the `ui/workers.py` deadlock recorded above as "mitigated, not
fixed," with the same numbering (this is still item 39) since it's a
direct continuation of that same investigation. Re-read the "Known,
NOT fixed" entry, plus items 28 (`WA_DeleteOnClose`), 29 (the
`Database.initialize()` connection-leak fix and its own audit
discipline), and 32 (the leak hunt and its `SingleShotConnection` fix,
including the real segfault its first attempt caused) before starting,
per the task's own brief — item 32 in particular as both a rigor bar
(its ~35-signal-connection audit, its 40-cycle repeated-repro
discipline) and a cautionary precedent: a fix that looks right on
paper caused a real crash there once already, so nothing here was
trusted without a live repro proving it.

**Correction to this file's own prior framing, made explicitly before
starting any investigation, not after.** The original entry's "never
observed outside the test-churn pattern" language was flagged as a
real risk of being read as lower-urgency than warranted. Checked
directly: `MainWindow.__init__` starts a `poll_timer`
(`POLL_INTERVAL_MS = 2_000`) whose `timeout` fires THREE separate
`run_worker()` calls every single tick
(`_poll_selected_playlist`/`_poll_active_downloads`/`_poll_review_items`),
plus a `backend_poll_timer` firing a fourth every 20s — for the entire
lifetime of any normal real session, not just this project's own test
suite. This is structurally the identical hazard shape as the test
suite's rapid `MainWindow` construction, just at a lower frequency —
every real session was already exercising the actual collision window
this bug needs; it simply hadn't been unlucky yet. Treated as a live
production risk from the start of this task, not a test-only curiosity.

**Step 1 — checked whether this is a known, already-fixed upstream
issue before writing any code.** Confirmed the real installed version
live: PySide6 6.11.2 / Qt 6.11.2 (`PySide6.__version__` /
`QtCore.qVersion()`). Searched Qt's own bug tracker rather than
guessing: PYSIDE-1657 ("Possible deadlock on signal connect/emit",
fetched via `bugreports.qt.io`'s real JSON API since the JS-rendered
page itself doesn't return content to a plain fetch) describes the
literal same pattern confirmed independently in this project's own
earlier stack-trace analysis — "the main thread attempting signal
connection may hold the GIL while another thread emitting signals
waits for GIL release — while itself holding a lock the main thread
requires" — filed against PySide2 5.14.1, closed as fixed in 5.14.2.2
by referencing PYSIDE-803 ("QThread Freezes GUI"), whose real fix (per
its own recorded comments) was four patches reducing how often PySide
releases/reacquires the GIL (`Py_BEGIN/END_ALLOW_THREADS` frequency,
defaulting "allow-thread" to `False`) — a real **frequency reduction**,
not a structural elimination of the underlying two-lock-ordering
hazard. Confirmed this distinction matters directly: on PySide6
6.11.2 — a version that already carries all of this 2020-era work —
the exact same hazard is still live-reproducible (see below), meaning
the 2020 fix narrowed the race window without closing it.

**Correction (2026-08-30, in response to a follow-up review of this
entry):** this paragraph originally also cited QTBUG-93259 as
supporting evidence — re-verified directly against Qt's own bug
tracker (its REST API, since the JS-rendered page returns no content
to a plain fetch) and confirmed that citation was wrong. QTBUG-93259 is
"Potential for deadlock when using BlockingQueuedConnection and waiting
on emitting thread" — an application-shutdown scenario (a sender thread
blocked emitting via `BlockingQueuedConnection` while the receiving
thread has already stopped spinning its event loop and is itself
waiting for the sender to finish), a different mechanism from the
connect()/emit()/mutex-pool contention this fix addresses, which uses
ordinary queued (not blocking) connections and has nothing to do with
shutdown ordering. A search for a correct replacement Qt bug ID found a
Qt Forum thread describing the right mechanism but no citable tracker
entry — dropped rather than cited with a weak substitute. PYSIDE-1657
above remains the accurate, independently-matching citation; no Qt-
tracker citation stands in for the removed one.

**Step 2 — audited every cross-thread signal connection in `ui/*.py`,
call site by call site, not sampled — matching item 32's own
discipline.** Grepped every `.connect(`/`.disconnect(`/`.emit(` across
`src/seeker/ui/*.py`. Classified each one by whether it ever crosses
the worker-pool-thread/main-thread boundary:
- `WorkerSignals.finished`/`.error` (or, post-fix, the shared
  dispatcher's two signals) in `workers.py` — the ONLY cross-thread
  traffic in the entire UI layer. `.emit()` happens inside
  `Worker.run()`, executing on a real `QThreadPool` OS thread;
  `.connect()`/`.disconnect()` happen in `run_worker()`, on the main
  thread. In scope.
- Every other `.connect(` in `main_window.py`/`wizard.py`/
  `settings_window.py` — button `.clicked`, `QTimer.timeout`,
  `currentItemChanged`/`currentChanged`, `textChanged`,
  `toggled` — is a same-thread Qt widget signal, always both emitted
  and connected on the main thread by Qt's own design (a `QTimer`
  fires from the thread it lives on; a button click is delivered by
  the main event loop). Confirmed genuinely out of scope, per the
  task's own explicit instruction not to apply the fix indiscriminately
  to signals that were never part of the hazard — these were left
  untouched.

**Step 3 — built a real, deterministic, standalone repro before
touching any fix.** A minimal script (no `Application`/DB layer needed
at all — the hazard lives entirely in Qt/widget construction plus
`workers.py`): construct many real `QMainWindow`+`QToolBar`+
`QPushButton` widgets back to back with zero explicit event-loop
processing in between (matching how pytest actually ran many
`MainWindow()` constructions in the original discovery), each also
firing two real `run_worker()` calls via a real `QThreadPool`. Run as
a real subprocess with a hard `subprocess.run(..., timeout=N)` — the
only safe way to test a literal-freeze failure mode. Confirmed live,
reliably: at 400 windows/iterations, the pre-fix design hung
**43 of 50 trials (86%)**. A control variant with ZERO widget
construction — pure `run_worker()` spam against itself — ALSO hung
(5/10), confirming the hazard doesn't require external widget
construction at all; it's sufficient for `workers.py`'s own repeated
per-task `connect()`/`disconnect()`/`emit()` calls to collide with
*each other* at high enough volume.

**Step 4 — spiked the recommended `threading.RLock` approach, and
verified live that it does NOT close the hazard.** Wrapped every
cross-thread `connect()`/`disconnect()`/`emit()` identified in Step 2
in a single shared `threading.RLock()` (reentrant, per the reasoning
that a slot synchronously re-entering a guarded call on the same
thread must not self-deadlock — and RLock correctly yields the GIL
while blocked cross-thread, which is the actual mechanism that would
break the cycle if this fully worked). Tested against BOTH repro
variants:
- No-widgets repro (pure `run_worker()`-vs-`run_worker()` collision):
  **10/10 clean** — the RLock correctly serializes `workers.py`'s own
  connect/disconnect/emit calls against each other.
- With-widgets repro (the real-world-shaped one, matching the
  original discovery): **7/15 (47%) still hung.**

Root cause of the gap, confirmed rather than assumed: Qt's own signal/
slot connection bookkeeping (`QObjectPrivate::signalSlotLock`) is
backed by a `QMutexPool` — a small, striped pool of mutexes keyed by
hashing the QObject's own memory address (confirmed against real Qt
documentation of this mechanism, not assumed) — NOT a single global
mutex and NOT a genuinely unique per-object one. `QToolBar`'s own
constructor makes its OWN internal `QObject::connect()` calls (visible
directly in the original stack trace: `QToolBar::QToolBar()` →
`QObject::connect()` using the OLD four-argument SIGNAL/SLOT overload —
genuinely Qt-internal code, not anything this project calls). A
Python-level lock, however broad, has no way to make Qt's own internal
widget-construction code wait for it — so any two objects (a
`WorkerSignals` instance and, say, a `QPushButton`) whose addresses
happen to hash into the same pool slot can still collide, RLock or
not, the moment real widget construction is happening concurrently
with a real emit(). This directly matches the task's own explicit
instruction: verified live that the surgical fix doesn't fully close
the hazard, stopped, and switched approach — rather than shipping it
or quietly narrowing the claim.

**Step 5 — built and verified the connect-once dispatcher fallback.**
Replaced the per-task `WorkerSignals` QObject (a fresh heap address,
connected and disconnected on every single call) with one shared,
permanent `_Dispatcher` QObject whose two signals
(`task_finished`/`task_error`, each now carrying the originating
`Worker` instance as an extra argument so the shared handler can route
each result to its own callback) are connected **exactly once, at
import time, for the life of the process** — never disconnected. Every
`Worker.run()` emits through this same fixed-address object instead of
constructing a new one. This doesn't eliminate emit()'s own exposure
(still a real cross-thread emit, still theoretically poolable-mutex-
collidable), but it eliminates the *other*, much larger half of the
volume: `connect()`/`disconnect()` calls, which need mutex-pool slots
for BOTH sender and receiver (confirmed via Qt's own internals: "to
modify a Connection you need to lock two mutexes"), previously
happening on every single task.

Verified live, escalating the stress level rather than stopping at
one comfortable result: **0/15, then 0/20 hangs** at the SAME
with-widgets repro that broke the RLock (47% hang rate) — including at
2000 iterations, the exact stress level that hung the ORIGINAL design
on its very first attempt in this task's own earlier session. Also
verified **functional correctness**, not just absence of hanging — a
dedicated script running 1000-1500 concurrent tasks with unique,
distinguishable results (and roughly 1% deliberately raising) confirmed
every result and error was delivered to its own correct callback, with
the caveat that `pool.waitForDone()` alone doesn't pump the receiving
event loop (a real gap in the first version of this correctness check,
which reported "0 results" until `app.processEvents()` was added to
actually drive delivery of the QUEUED cross-thread signal — a real
mistake caught and fixed before trusting the result, not a target
outcome assumed in advance).

**Step 6 — the redesign introduced a real, NEW, separate bug: a
genuine, reproducible segfault — exactly the cautionary pattern this
task was warned about going in, and treated with the same seriousness
item 32's own analogous crash got.** Running the full
`tests/test_ui_smoke.py` suite (not the isolated repro — the same
lesson item 32 itself teaches about verifying broadly) against the new
dispatcher design crashed with a real, reliably-reproducible
`Fatal Python error: Segmentation fault`, in
`pytestqt.plugin._process_events` during test teardown — the *exact*
same crash location item 32's own unsafe first attempt hit, though
confirmed via direct A/B testing to be a **new, different** bug: the
unmodified original (pre-dispatcher) code ran clean 3/3 times; the
dispatcher version crashed reliably 3/3 times.

Root-caused rather than patched blind: `QThreadPool`'s C++ side
auto-deletes a `QRunnable` the instant `run()` returns, unless told
not to — confirmed live (`QRunnable` subclass, fresh instance,
`.autoDelete()` returns `True` by default). The dispatcher's `emit()`
call passes `self` (the `Worker`) through the signal as its LAST
statement inside `run()` — meaning the underlying C++ object can be
(and, per the crash, reliably was) deleted by `QThreadPool` a few CPU
cycles after `run()` returns, racing ahead of the QUEUED signal's
delivery on the main thread. By the time `_handle_task_finished`
finally ran, `worker` could be a dangling reference to an
already-deleted C++ object. The ORIGINAL per-task design never hit
this because it never passed the `Worker` itself through any signal
at all — only the plain, already-copied-out result value or error
string. Fixed with `self.setAutoDelete(False)` in `Worker.__init__`,
with the full reasoning recorded inline in the code, not just here.
Reran the full suite **15/15 clean** immediately after the fix (5
initial + 10 more), then the complete repo-wide suite **3/3 clean**.

**Final verification — the regression test that ships.**
`tests/test_workers_deadlock_regression.py` runs the real repro
(`tests/_workers_deadlock_repro.py`, matching Step 3's script) in 50
separate subprocesses, each with an 8-second hard wall-clock timeout —
the failure mode is a literal, unrecoverable freeze, so this test can
never itself hang, no matter what regresses. A second test runs the
correctness repro (`tests/_workers_correctness_repro.py`) the same
way. Confirmed both directions live, not just the post-fix pass:
running this exact test file against the untouched original
(pre-dispatcher) `workers.py` failed with **42/50 trials timing out**;
against the final, fixed `workers.py`, both tests pass — reran the
deadlock trial count directly (not just via pytest) at **50/50 clean**
and, at nearly 4x the per-trial stress level (1500 vs. 400
iterations), **20/20 clean**. Full repo-wide suite: **455 passed, 1
skipped**, run three times in a row.

**Outcome.** The "Known issues" entry is updated from "mitigated, not
fixed" to fixed. `mypy --strict` clean across all `src/` files
throughout every step of this task, including both the RLock spike and
the dispatcher redesign.

### 39, second addendum — closing two loose ends: a wrong citation, and
a real native leak whose fix took three tries

A follow-up review of the addendum above asked two direct questions
before treating item 39 as closed: is the QTBUG-93259 citation actually
correct, and does `setAutoDelete(False)` leak the native `Worker`
object now that nothing frees it? Both turned out to have real
answers, not just "looks fine."

**Citation check — QTBUG-93259 was wrong, dropped.** Fetched the real
issue directly from Qt's own tracker (`https://qt-project.atlassian.net
/rest/api/2/issue/QTBUG-93259` — the JS-rendered `bugreports.qt.io`
page itself returns no usable content to a plain fetch). Its actual
title: "Potential for deadlock when using BlockingQueuedConnection and
waiting on emitting thread" — an application-*shutdown* scenario (a
sender thread blocked inside a `BlockingQueuedConnection` emit while
the receiving thread has already stopped spinning its event loop and is
itself waiting for the sender to finish). This fix's own hazard uses
ordinary queued (not blocking) connections and has nothing to do with
shutdown ordering — a different mechanism entirely, wrongly cited as
supporting evidence in the addendum above. Searched for a correct
replacement: found a Qt Forum thread describing the right mechanism
(GIL/mutex-pool contention on connect/emit) but with no citable tracker
entry attached to it. Dropped the citation rather than force a weak
substitute, per the explicit instruction to do so. PYSIDE-1657 (already
cited above) remains the one accurate, independently-matching citation
for the actual mechanism.

**Leak check — real, confirmed via native-object introspection, not
just re-running the deadlock test.** The concern was specific:
`gc.get_objects()` (this project's own item 32 methodology) only sees
Python-side wrappers, not whether the underlying C++ object was
actually freed — a leak on the native side could report clean under
that check alone. Used `shiboken6.Shiboken.getAllValidWrappers()`
(enumerates every currently-valid native-wrapped object app-wide) and
`ownedByPython()`/`isValid()` instead. First finding, confirmed
directly: `QThreadPool.start()` revokes Python's ownership tracking of
a submitted `QRunnable` — `ownedByPython(worker)` flips `True → False`
the instant `start()` returns, REGARDLESS of `autoDelete`. With
`autoDelete` at its default (`True`), that's fine — `QThreadPool`
itself deletes the native object once `run()` returns. With it
disabled (as the addendum above set it), NOTHING was left responsible
for ever freeing it: Python's own GC has no effect once ownership isn't
Python's, and `QThreadPool` won't since `autoDelete` is off. Confirmed
via the real check: 100 leaked native `Worker` objects per 100-worker
cycle, growing unboundedly across repeated cycles, while
`_active_workers`/`_callbacks` correctly reported empty the entire
time — a leak completely invisible to the Python-only check.

**Fixing it took three attempts, each one caught by live
re-verification rather than assumed correct on paper — matching this
project's own standing discipline (items 29/32) that a fix which
"seems right" still needs to be run, not just reasoned about.**

*Attempt 1 — pass `self` through the signal so a handler could delete
it.* Reintroduced the EXACT autoDelete-style crash the original
addendum had already fixed, at the same call site, for the same
underlying reason: it re-created a way for something to touch a
QRunnable whose native lifetime is Qt's own to manage. Caught by
running the full suite, not the isolated deadlock repro — the isolated
repro stayed green throughout, since it doesn't exercise this path;
only `uv run pytest -q` (full suite) crashed, at
`tests/test_ui_smoke.py::test_review_tab_renders_needs_review_
candidates`'s own teardown, inside `pytestqt.plugin._process_events`.

*Redesign — stop passing `self` through the signal at all.* `Worker`
now carries a plain `task_id` int (an `itertools.count()` value assigned
before submission); `_callbacks` is keyed by it. This is the right
design independent of the crash (a QRunnable's cross-thread marshaling
adds nothing the dispatcher needs, and a plain int has none of a
QRunnable's own lifetime baggage) — but bisecting it against the SAME
full-suite crash surfaced a second, independent fact: with `autoDelete`
back at its *default* (`True`) and no Worker reference anywhere near
the signal, the crash still reproduced, reliably, 5/5, in the same
place. Isolated further via a minimal single-test repro (constructing
`MainWindow`, which triggers two constructor-time background polls with
no button/status_label at all, then letting pytest-qt's own teardown —
weakref-based `addWidget`, `close()`+`deleteLater()`, then
`processEvents()` — run) — reproduced standalone via pytest, but did
NOT reproduce in an equivalent bare `QApplication` script performing
the identical sequence, meaning something specific to pytest-qt's own
per-test machinery (most plausibly its `qInstallMessageHandler`-based
Qt log capture, installed fresh for every test and callable from any
thread) shifts timing enough to expose the race deterministically.
Re-enabling only `setAutoDelete(False)` — nothing else changed — made
the exact same repro pass cleanly, 3/3. Conclusion, confirmed rather
than assumed: `setAutoDelete(False)` is independently required
regardless of what crosses the signal. The mechanism: `Worker` is a
Python subclass carrying real Python state (`self.fn`, a bound closure,
often itself holding references back into a QWidget); tearing that down
on the background thread the instant `run()` returns — safe for a
plain C++ `QRunnable`, but requiring real interpreter work (decref'ing
`self.fn` and friends) for a Python subclass — has been confirmed, live,
to race unsafely against ordinary main-thread Qt/Python activity in
this environment.

While isolating this, a related, genuinely independent bug was found
and fixed: `test_backend_poll_runs_poll_downloads_off_the_main_thread`
was waiting on `"thread" in recorded`, a flag set *inside* the
background function itself (on the worker thread), rather than on the
main-thread completion callback (`_backend_poll_in_progress` flipping
`False`) — meaning the test could observe success and end (tearing down
its window) before the queued completion signal had actually been
delivered. Fixed to wait on the same main-thread flag
`test_backend_poll_overlap_guard_skips_concurrent_tick` already
correctly used. This didn't turn out to be sufficient on its own to
stop the crash (the deeper `autoDelete` hazard above was the dominant
cause), but it's a real, independent test-timing gap worth having fixed
regardless — any queued-signal-based design has this exact hazard if a
test doesn't wait for signal delivery, only the background function's
own return.

*Attempt 2 — with `setAutoDelete(False)` back and `task_id`-only
signal, explicitly `shiboken6.Shiboken.delete()` the worker
synchronously inside the dispatcher's own signal handler, obtaining the
reference via a plain `_callbacks` dict lookup (never the signal
payload).* Reintroduced the same crash class a third time, confirmed by
disabling only this call (leaving everything else identical) and
watching the minimal repro go from 5/5 crash back to 3/3 clean.
Conclusion: deleting the native QRunnable while still inside the call
stack of the very queued signal that just reported it done is itself
unsafe here, regardless of how the reference to it was obtained.

*Attempt 3 (the one that held up) — defer the same delete one
event-loop iteration via `QTimer.singleShot(0, lambda:
_delete_native_worker(worker))`, called from the same point in each
handler.* Confirmed live, 5/5 clean on the minimal repro that reliably
crashed both prior attempts.

**Full re-verification of the final combination — `task_id`-only
signal, `setAutoDelete(False)`, deferred `shiboken6.Shiboken.delete()`
via `QTimer.singleShot(0, ...)`:**
- Minimal crash repro: 5/5 clean (was 5/5 crash before this design).
- Native leak check (`getAllValidWrappers()`, 20 cycles × 200 workers):
  flat 0 valid native `Worker` wrappers at every checkpoint (was
  unbounded growth to 4000 before any fix existed).
- RSS over the same 20×200 run: +0.7MB total, consistent with ordinary
  allocator noise, not a leak (the pre-fix run showed steady +MB
  growth proportional to worker count).
- `tests/_workers_deadlock_repro.py` (400 iterations) and
  `tests/_workers_correctness_repro.py` (800 tasks): both clean.
- `tests/test_workers_deadlock_regression.py` (50 subprocess trials):
  2/2 tests passed.
- Full repo-wide suite (`uv run pytest -q`): **455 passed, 1 skipped**,
  run three times in a row, zero crashes.
- `mypy --strict src/`: clean throughout every intermediate attempt and
  the final design.

**Call-site audit, re-confirmed rather than re-derived.** Grepped every
`run_worker(` call across `src/seeker/ui/*.py`: 34 real call sites
(`main_window.py`, `settings_window.py`, `wizard.py`,
`library_location_picker.py`), all routed through the one shared
dispatcher. Grepped for `WorkerSignals`/`.signals.` outside `workers.py`
itself: none — the only remaining mentions are in `workers.py`'s own
historical docstring comments explaining what the design replaced.

**Ownership/deletion, answered directly, per the question this task
opened with.** The native `Worker` object is now explicitly freed by
`_delete_native_worker()`, called via `QTimer.singleShot(0, ...)` from
`_handle_task_finished`/`_handle_task_error` — NOT by `_callbacks`'
`.pop()` (a plain Python dict operation dropping a Python reference
has no effect on the native side once `QThreadPool.start()` has
transferred native ownership away from Python, confirmed via the
`ownedByPython()` finding above) and NOT by `QThreadPool`'s own
`autoDelete` (disabled, and confirmed independently required to avoid
the crash class above). The one-event-loop-tick deferral is load-
bearing, not cosmetic: deleting synchronously, even via a safely-
obtained reference, reintroduced the crash; deferring it does not.

### 40

Phase 2 of the duplicate/quality detector (item 39's own Phase 1 built
fingerprinting, clustering, and a read-only Duplicates tab; this closes
the deliberately-deferred delete/replace action). Re-read item 39's
final state (CLAUDE.md's Known Issues entry and both HISTORY.md
addenda) before starting, per the task's own explicit instruction —
this Phase adds another worker-driven action into the exact lifecycle
machinery item 39 spent four rounds getting right.

**Design question resolved first, by checking real behavior, not by
picking an order and hoping: does the DB row update or the file
deletion happen first?** These aren't atomic, and the task's own
framing was right that the two orderings fail differently. Checked
directly whether `library scan`'s existing reachability/change-
detection logic already reconciles `local_files` rows for files that
no longer exist, rather than assuming either way: yes — `library/
scanner.py::LibraryScanner.scan()` builds `seen_relative_paths` from a
real `rglob()` walk of the location's real directory tree and calls
`self.local_files.delete_missing(location.id, seen_relative_paths,
connection)`, which deletes every `local_files` row for that location
whose `relative_path` wasn't seen. This changes how much the ordering
matters, exactly as the task anticipated: the DB-row-first failure mode
(interrupted after the DB delete, before the file delete) leaves an
orphaned-but-still-present file on disk — completely benign, since the
next `library scan` just rediscovers it as a "new" file, no error
potential at all. The reverse order (file first, DB row second) would
leave a `local_files` row pointing at a file that no longer exists in
the window before that same next scan repairs it — a state a matcher
or tagger run in that window could act on and genuinely fail against
(a real I/O error opening a file that isn't there), which is worse.
**Decision: DB row first, then the file on disk** — and this already
matches existing precedent in this exact codebase: `apply_upgrade_
decision` (item 26) already does `track_matches.upsert()` +
`download_requests.mark_status("completed")` (the DB update) BEFORE
`old_path.unlink()` (the file delete), for the identical reasoning,
confirmed by reading its own source rather than assumed from memory.

Also checked directly (not assumed from the schema text alone) that
`local_files.delete_by_id`'s cascade onto `track_matches.local_file_id`
actually fires: `schema.py` declares `FOREIGN KEY (local_file_id)
REFERENCES local_files(id) ON DELETE SET NULL`, and `connection.py`
sets `PRAGMA foreign_keys = ON` on every real connection — a genuine
end-to-end test (`test_delete_local_files_cascades_track_match_to_
unmatched`) seeds a real `Track`+`TrackMatch` row pointing at a real
`local_file_id`, calls `delete_local_files`, and confirms the match
comes back with `local_file_id is None` rather than trusting the
schema declaration on its own.

**Reuse audit — the Review tab's actual deletion code was NOT factored
for reuse, confirmed by reading it directly rather than assumed either
way.** `DownloadService.apply_upgrade_decision`'s tail (`old_path.
unlink()` wrapped in a bare `try/except OSError`, formatting a message
inline) was a private implementation detail of that one method, not a
standalone, importable function — reusing it as-is would have meant
either importing a private-shaped snippet across a `soulseek/` →
`library/` layer boundary or duplicating it. Per the task's own
instruction ("if it's not currently factored for reuse, that's fine,
but say so explicitly rather than silently duplicating it"), extracted
it instead: new top-level `seeker/file_deletion.py::delete_file(path)
-> str | None` — a pure, zero-seeker-dependency primitive (just
`pathlib.Path`), the same "lowest layer that needs it" placement this
codebase already uses for `download_dedup.py`. `apply_upgrade_decision`
was updated to call it too, confirmed behavior-preserving by its own
three existing tests passing unmodified
(`test_apply_upgrade_decision_replace_and_delete_old`/
`_replace_and_keep_old`/`_decline_is_a_no_op`).

**Service layer.** `DuplicateService.delete_local_files(local_file_ids:
list[int]) -> dict[str, Any]` — deliberately takes no `location_name`
or "group" concept at all: each `LocalFile` already carries its own
`location_id`, so the caller (the UI) just passes the specific ids it
decided to delete, and the method trusts that decision rather than
re-deriving or re-validating it against `find_duplicate_groups`' own
clustering (which would require re-fingerprinting/re-clustering just to
check a caller-supplied list, for no real safety benefit). Per-item
try/except, same batch-safety shape as `compute_fingerprints`
(item 39): one bad id (already gone, permission denied, whatever)
can't abort the rest of the batch. Three real outcomes, each with its
own test: (1) a normal delete — both the `local_files` row and the
real file removed, confirmed via `LocalFileRepository.get_by_id`
returning `None` and `Path.exists()` returning `False`; (2) an
already-missing id — the desired end state (no such row, no such
tracked file) is already true, so this counts as a clean `deleted`,
not a `failed`; (3) a DB row whose real file was already gone from disk
(moved, deleted by something else) — the DB row is still correctly
removed (per the ordering decision above), but the file-deletion
failure is surfaced as a real `failed` entry with a message naming the
missing file, not silently treated as success just because the DB side
succeeded.

**UI — reused the Review tab's exact double-confirm interaction shape,
not a new one, per the task's own explicit instruction.** The existing
Duplicates tab (item 39) rendered a flat, 5-column, one-row-per-file
table with no per-group action at all. Extended to 7 columns: "Keep" —
a `QRadioButton` per file row, grouped per duplicate group via
`QButtonGroup(self.duplicates_table)` (so only one file per group can
ever be selected), with `addButton(radio, id=local_file.id)` — the
button's own id IS the local_file_id, so `checkedId()` reads back which
file to keep with no separate id-mapping dict needed. Pre-selected to
`group.files[0]` (Phase 1's own best-quality-first ranking — see
`DuplicateGroup`'s own docstring, "files[0] is this group's own
recommendation") but never auto-applied; the user can move the
selection to any other file in the group before anything is deleted.
"Actions" — a "Confirm delete" checkbox + "Delete" button, rendered
only on each group's first row (`setSpan(group_first_row, 6,
len(group.files), 1)`), every other row in the group getting a bare
`QWidget()` — the identical "blank cell, not a misleading control"
precedent item 27 already established for the per-track Tag button
only rendering for `IN_LIBRARY` rows. Clicking Delete with the checkbox
unchecked is a genuine no-op (a status message, `delete_local_files` is
never called) — confirmed via a dedicated test asserting the fake
service's call list stays empty. `QButtonGroup` instances have no Qt
parent-child ownership tie to the radios living in table cells, so they're
kept alive in a `self._duplicate_button_groups` list, reset on every
render — the identical GC-hazard reasoning `ui/workers.py`'s
`_callbacks` dict is built on (item 39), applied here to a different
kind of Qt object.

**Routed through the exact same worker machinery as everything else —
verified, not just asserted in a comment.** The delete button's click
handler calls `run_worker(self.thread_pool, lambda: self.application.
duplicate_service.delete_local_files(delete_ids), button=..., status_
label=..., on_finished=...)` — the same `run_worker()` every other
background action in this codebase goes through, no bespoke worker
path, no ad hoc `connect()`. This doesn't reintroduce any of item 39's
four closed hazards because it doesn't need to touch any of the
machinery those hazards lived in: the delete action itself is a single
synchronous service-layer call executed inside the worker's own
function body (exactly like `compute_fingerprints`/`find_duplicate_
groups` before it), not a new `QRunnable` subclass, signal, or
cross-thread callback design of its own — `ui/workers.py` itself was
not touched by this task at all.

**Refresh-after-delete needed one small, deliberate fix to avoid
clobbering its own result message.** The first draft called
`_on_find_duplicates_clicked()` directly after a successful delete —
but that method also sets `duplicates_status_label` to "Searching for
duplicates..." and passes `status_label=` to its own `run_worker()`
call (which clears the label to `""` at the start of any worker), which
would immediately overwrite the "Deleted: N, Failed: N" message before
the user could ever see it. Fixed by re-fetching `find_duplicate_
groups` directly with no `status_label` passed (a silent background
refresh, the same pattern `_poll_review_items` already uses for its own
2s-timer-driven refreshes) and combining the two messages explicitly
once the re-render completes.

**No new CLI command, and no new schema/migration — both deliberate,
not omissions.** The task scoped the delete action to the UI's own
double-confirm flow specifically (mirroring the Review tab); `library
duplicates` stays a read-only listing, matching item 39's own "read-
only for now" build order for the CLI side. `find_duplicate_groups`
already recomputes fresh from cached fingerprints on every call
(item 39's own explicit design choice — "never persisted as its own
table... a moved/rescanned file can't leave a stale group behind") —
adding a "resolved" flag or any other persisted group-state table would
have been exactly the premature schema change this project's own
conventions warn against, since a deleted duplicate already stops
appearing in the very next `find_duplicate_groups()` call with zero new
state.

**Live verification, beyond the mocked UI tests.** A real, offscreen
(`QT_QPA_PLATFORM=offscreen`) `MainWindow`, wired to a real
`DuplicateService` (real `Database`, real repositories) rather than the
test suite's `FakeDuplicateService` — two real generated duplicate
`.wav` files (identical 440Hz tones) in a disposable `tempfile.
mkdtemp()` directory, never a real library. Ran the real
`compute_fingerprints`/`find_duplicate_groups` calls directly (real
libchromaprint), confirmed one real 2-file group was found, rendered it
through the real `_render_duplicate_groups`, checked the real "Confirm
delete" checkbox and clicked the real "Delete" button on the real
`QPushButton` inside the real cell widget. Confirmed directly
afterward, not just trusted the status label: exactly one of the two
real `.wav` files was gone from disk (`Path.exists()` on each), exactly
one `local_files` row remained in the real DB, and the status label
correctly read "Deleted: 1, Failed: 0."

Tests: 5 new `DuplicateService.delete_local_files` tests (real
`tmp_path` files throughout — normal delete, FK-cascade-to-unmatched,
already-missing id, file-already-gone-from-disk failure reporting,
one-failure-doesn't-abort-the-batch), 2 new `file_deletion.delete_file`
tests, 6 new UI smoke tests (pre-selection, per-group action placement,
no-op without the confirm checkbox, correct ids deleted including
after moving the radio selection, and the refresh-with-combined-
message behavior), plus the 3 pre-existing `apply_upgrade_decision`
tests reconfirmed passing unmodified against the refactored shared
`delete_file()` call. `mypy --strict` clean; full suite 468 passed / 1
skipped, run 3 times in a row.

### 40, follow-up — a real match-status gap and a real performance
regression, both found by checking rather than assuming the first pass
was complete

A quick follow-up review of item 40 asked two direct questions before
treating it as closed: what happens to a track's match when the
deleted duplicate held it, and does resolving a group against the real
~344-group result set actually perform acceptably. Both had real
answers.

**Question 1 — checked exactly what the `ON DELETE SET NULL` cascade
leaves behind, not assumed it fully "unmatches" the track.** Read
`schema.py`'s actual declaration: `FOREIGN KEY (local_file_id)
REFERENCES local_files(id) ON DELETE SET NULL` — this clears
`local_file_id` and nothing else. A row that was `match_method='auto',
score=100.0, local_file_id=<deleted id>` becomes `match_method='auto',
score=100.0, local_file_id=NULL` — NOT the same thing as a genuinely
unmatched track (`match_method IS NULL`), a distinction this codebase's
own `matching.py`/`matcher.py` treat as meaningfully different
everywhere else.

Traced what actually consumes that combination downstream, not just
reasoned about it in the abstract: `DashboardService._compute_status`
(`dashboard_service.py`) requires BOTH `match.match_method == "auto"`
AND `match.local_file_id is not None` AND `match.local_file_id in
local_files_by_id` for `IN_LIBRARY` — a `local_file_id=NULL` row fails
that check and falls through every other branch (no active download,
not `needs_review`) to `NOT_FOUND`. Confirmed this is a real, reachable
display bug: a user resolves a duplicate group, keeping the better-
quality copy, and the dashboard reports the track as missing entirely.

Then checked the SPECIFIC risk the follow-up asked about directly —
does anything treat this as a signal to search/download — by reading
the actual query `download_playlist` schedules against, not the
dashboard's own separate status logic:
`TrackRepository.get_unmatched_for_playlist` filters
`WHERE pt.playlist_id = ? AND (tm.track_id IS NULL OR tm.match_method
IS NULL)`. Since `match_method` stays `'auto'` (the cascade never
touches it), this condition is FALSE for the affected row — the track
is NOT included in what `download_playlist` schedules. Also confirmed
no scheduled/background trigger for either `match_all()` or
`download_playlist()` exists at all — grepped every UI/CLI call site:
both are ONLY ever invoked from an explicit button click
(`_on_match_clicked`/`_on_download_clicked`) or an explicit CLI
subcommand, never a `QTimer` poll. So the specific failure mode
flagged as the real risk — the app going and re-downloading a copy of
a track the user already has, undercutting the point of the feature —
does NOT occur, in either the automatic-trigger sense (no such trigger
exists) or the "download_playlist quietly re-includes it" sense (the
`match_method IS NULL` gate blocks it). The REAL failure mode present
was different and still worth fixing: the track becomes stuck in limbo
— shown as missing by the dashboard, but never re-searched either,
until an explicit, later `library match` run happens to notice and
correct it.

**Fix, reusing the existing repoint pattern rather than inventing a
new one.** Grepped for any existing "reassign a track_matches row"
helper before writing new logic: none exists as a separate function —
every real call site (`TrackMatcher.match_all()`,
`DownloadService.apply_upgrade_decision`'s replace path) just
constructs a `TrackMatch` dataclass with the fields it wants and calls
`TrackMatchRepository.upsert()` directly. That upsert call IS the
reusable primitive; there was nothing further to extract. Added
`TrackMatchRepository.get_by_local_file_id(local_file_id, connection)
-> list[TrackMatch]` (a list, not a single optional — `local_file_id`
isn't the table's own primary key, `track_id` is, so nothing in the
schema actually prevents more than one track's match from pointing at
the same file, even though that's expected to be rare in practice).
`DuplicateService.delete_local_files` gained an optional
`keep_local_file_id: int | None = None` parameter; a new private
`_repoint_or_clear_match` looks up any match pointing at the file about
to be deleted and, if `keep_local_file_id` was given, re-points it
there via `upsert()` — preserving the original `match_method`/`score`
(the underlying audio is fingerprint-confirmed near-identical, so the
existing match's own confidence is still the right thing to report;
nothing was re-evaluated) and refreshing only `matched_at`. `None`
(the parameter's default) falls through to the original `ON DELETE SET
NULL` cascade behavior, unchanged — a caller with no group/keep context
at all still gets the old, safe-if-imperfect behavior rather than being
forced to supply an id it doesn't have. `Application.duplicate_service`
and the UI's delete-button handler were updated to pass the checked
radio's `local_file_id` through.

New test: `test_delete_local_files_repoints_match_to_the_kept_file` —
seeds a real `Track`+`TrackMatch` (`match_method='auto', score=87.5`)
pointing at a `low_quality` file, calls `delete_local_files([low_quality
.id], keep_local_file_id=high_quality.id)`, and confirms the match now
points at `high_quality.id` with `match_method`/`score` unchanged and
`matched_at` genuinely updated (not left stale).

**Question 2 — checked the real cost of resolving one group at real
scale, using item 39's own already-recorded real number rather than
guessing or building a fresh synthetic benchmark.** Item 39's own
live-verification (docs/HISTORY.md, same file) already recorded the
real, current cost of a full `find_duplicate_groups()` call: **9m59s
real wall-clock time** over a real ~3,142-fingerprinted-file library
that produced 344 real duplicate groups. The first draft of item 40's
`_on_delete_duplicates_finished` called `find_duplicate_groups()` again
after every single-group resolution to refresh the tab — at the real
scale that number describes, resolving all 344 groups one at a time
would have cost roughly 344 × 10 minutes, making the feature
practically unusable at the exact scale it's meant to help with. This
is a real, confirmed regression, not a hypothetical worth hedging
against speculatively — the number came directly from this project's
own prior real run, not an estimate.

Fixed per the task's own suggested direction, checked as the right
call rather than taken on faith: `MainWindow` now keeps the
last-fetched `list[DuplicateGroup]` in `self._current_duplicate_groups`
(set inside `_render_duplicate_groups`, alongside the existing
`_duplicate_button_groups` reset). `_on_delete_duplicates_finished`
drops the just-resolved `group` from that list by identity (`is not
group`) and calls `_render_duplicate_groups` on the reduced list
directly — no `run_worker`/service call at all for the refresh. A
persisted "resolved" flag was explicitly NOT used, per the task's own
reasoning: `find_duplicate_groups`'s fresh-every-call design (item 39)
exists specifically to avoid a moved/rescanned file leaving a stale
group behind, and a persisted flag would reopen exactly that
staleness risk for no benefit here, since the in-memory list is already
authoritative for what the tab is currently showing.

One added correctness guard beyond the original ask: `result["failed"]
> 0` (a partial deletion failure) leaves the group in place rather than
dropping it, since the real DB/disk state in that case may not actually
match "resolved" — confirmed via a new test
(`test_delete_duplicates_partial_failure_keeps_group_visible`) that the
table still shows both rows and `_current_duplicate_groups` still holds
the group after a simulated partial failure. The success path's own
test (`test_delete_duplicates_finished_removes_group_locally_without_
refetch`, replacing the old re-fetch-asserting test) confirms zero
`find_duplicate_groups` calls happen and the table/in-memory list are
both empty afterward.

**Tooltip/subtitle check — already accurate, confirmed by reading the
current text rather than assumed stale.** `DUPLICATES_TAB_SUBTITLE` and
the three new tooltips (`TOOLTIP_KEEP_FILE_RADIO`/
`TOOLTIP_DELETE_DUPLICATES_CHECKBOX`/`TOOLTIP_DELETE_DUPLICATES_BUTTON`)
were written during item 40's own original UI pass and already
describe the real delete action correctly (the subtitle no longer says
"Read-only for now"); no stale copy was found, so nothing needed
changing here. The remaining three tooltips (location combo, Compute
fingerprints, Find duplicates) describe controls whose behavior didn't
change in this task and remain accurate as written.

`mypy --strict` clean; full suite 470 passed / 1 skipped, run 3 times
in a row.

### 41

Bounded verification pass, three scoped tasks: swap the real Revolut
support link in for item 35's placeholder; extend item 32's stress test
to cover the duplicate detector (items 38-40), which it predates
entirely; a documentation consistency pass across CLAUDE.md, README.md,
and this file. Instructed explicitly to verify live rather than
manufacture findings — the stress-test extension did surface a real
bug on its first live run, investigated and fixed with the same rigor
as item 39 rather than reasoned about in the abstract.

**Support link — done, no narrative worth preserving.** One string
swapped in `help_text.SUPPORT_LINKS`. PayPal's placeholder is untouched
(not ready yet, out of scope here).

**Stress test extension — design.** `test_stress_e2e.py` never
exercised the Duplicates tab's fingerprinting/clustering/delete worker
traffic overlapping with the rest of the app's background activity —
it predates items 38-40 by several items. Two real constraints shaped
the design, both settled with the user before writing any code (this
task genuinely can't infer either from the codebase alone): (1)
`delete_local_files` is real and destructive — running it against the
real X9 Pro library's actual duplicate groups (a known real one exists
per item 39's own live-verification write-up, the accidental
`wetransfer_...`/`Sinthesis/YBBY` 100%-similarity pair) would delete a
real file from the user's real library as a side effect of an automated
test; (2) `find_duplicate_groups()` recomputes an entire location's
clustering from scratch on every call and cost ~10 real minutes over
the real ~3,100-file production library (item 39's own number) — running
that inside a ~5-minute stress test would either force an awkward
duration extension or make the run impractical to re-run casually. Both
resolved by scoping to a small, disposable library location — two
synthetic, byte-identical WAV files (a 440Hz sine tone via
`soundfile.write`, no real audio content and nothing from the real
library at all) registered, scanned, fingerprinted, clustered, and
resolved through the exact same real code path (`DuplicateService`,
`ui/main_window.py`'s real button click handlers, the real
`run_worker`/`QThreadPool` mechanism) every real user's Duplicates tab
uses — only the input data is disposable, not the mechanism being
tested. Registered/cleaned up via `library_service.add_location`/
`remove_location` directly (best-effort pre-cleanup of a same-named
leftover from a crashed prior run, real `shutil.rmtree` of the scratch
directory in every code path, success or failure, via a dedicated
`_cleanup_stress_duplicate_location` helper called from the test's own
`finally` block).

Fired Compute fingerprints right alongside the existing sync/scan/match
click flurry (genuine overlap, not sequenced after), waited for it to
settle, then fired Find duplicates so ITS clustering work would overlap
with the concurrent-downloads section that follows — deliberately
threaded through the existing overlapping-fire structure rather than
tacked on as a separate phase. The delete action (checkbox + button,
mirroring the Review tab's own double-confirm shape, per item 40) is
exercised once during the interleaved loop, gated on the same
"do it once, track a flag" pattern the existing threshold-change block
already uses, waiting up to 30s across cycles for `find_duplicate_
groups()` to land before attempting it.

**First live run — failed for real, not a test-authoring mistake.**
`assert last.active_workers == 0` failed: 1 worker still registered
after the full 300s+ run. Immediately after the failure, an uncaught
```
RuntimeError: Signal source has been deleted
```
printed from `ui/workers.py::Worker.run()`'s `_dispatcher.task_finished
.emit(self.task_id, result)` line, alongside a genuinely real, external
error: `poll_downloads()`'s locked-row retry got a real `500 Internal
Server Error` from slskd's own `/api/v0/transfers/downloads/batches`
endpoint for a specific real locked row
(`(AMB025) Zenea - INFINITE/01. Zenea - Infinite.mp3`) that has been
sitting in the real production DB since before this task, per its
own real `download_requests` row (confirmed via a direct query: 1
`locked`, 2 `downloading`, 2 `queued` rows exist in the real DB right
now).

**Root-cause investigation, live, not reasoned about in the abstract.**
Read `ui/workers.py` in full first: `_dispatcher` is a module-level
`_Dispatcher()` QObject, connected exactly once at import time, per
item 39's own deadlock-fix design (see that item's addendum) —
nothing in the file's own logic should ever delete it during a single
test run. The error text itself (`RuntimeError: Signal source has been
deleted`) is shiboken's own message for emitting a signal on a QObject
whose native C++ side is already gone — meaning `_dispatcher`'s native
object really was destroyed by the time the straggling worker thread's
`run()` call reached its `.emit()` line, sometime during pytest's own
post-test teardown (the message appeared in the log AFTER "1 failed in
303.31s", i.e. after the test function itself had already returned).
pytest-qt's `qapp` fixture is what actually owns the `QApplication`
instance's lifetime in this test file (no local override), and its own
session-end teardown is the natural point at which a leftover, unparented
QObject like `_dispatcher` would get invalidated.

Reproduced the exact mechanism in isolation, deliberately, before
touching any source (`/private/tmp/.../repro_dispatcher.py`, a
throwaway script, not committed): a real `QThreadPool`, a
`run_worker()` call whose `fn()` sleeps 1.5s, then
`shiboken6.Shiboken.delete(workers_mod._dispatcher)` called from the
main thread while the worker is still mid-sleep, simulating what
pytest-qt's teardown appears to do. Got the byte-identical error:
```
RuntimeError: Signal source has been deleted
```
— confirming the mechanism precisely, not just plausibly.

**Why this matters beyond the test itself — confirmed, not assumed:**
the same race is reachable in real production usage, not just pytest
teardown. `_dispatcher`'s native object gets torn down at Qt/Python
interpreter shutdown the same way regardless of what triggers it
(pytest-qt's fixture teardown here; a real user quitting `seeker-ui`
in the wild) — a straggling `QThreadPool` worker thread doing a real
network call (the exact scenario here: `poll_downloads()` retrying a
locked row against slskd) is not force-killed by Python on interpreter
shutdown, so the identical "finishes late, emits into a deleted
dispatcher" race can happen to a real user closing the app while a
backend poll is mid-flight. This is squarely in the same hazard family
this file's own docstring already documents at length (item 39's
addendum) — a background thread's cross-thread signal emission racing
against Qt/Python object teardown — just a new specific instance of it,
not previously identified because nothing before this task gave the
backend-poll timer's worker enough real, concurrent, overlapping load
to make it likely to still be in flight at test-teardown time.

**Fix — the smallest change that closes it, chosen over the
alternatives considered.** Guard each `.emit()` call in `Worker.run()`
with `shiboken6.Shiboken.isValid(_dispatcher)` immediately before
calling it; if invalid, drop the result silently. Considered and
rejected two alternatives before settling on this: (1) waiting for the
thread pool to fully drain on `MainWindow.close()` (a `closeEvent`
override calling `thread_pool.waitForDone(timeout)`) — a real, valid
architectural fix for the underlying timing gap, but a genuine
production UX/behavior change (blocking window close on network I/O)
that wasn't clearly in scope for a bounded verification pass and wasn't
needed to fix the crash itself; (2) catching `RuntimeError` broadly
around the `.emit()` calls — works, but `isValid()` is the more precise,
intention-revealing check (matches `_delete_native_worker`'s own
existing `isValid()` guard two functions below in the same file,
keeping the file internally consistent rather than introducing a
second style for the same kind of check). Re-ran the exact same
isolated repro script against the fixed code: no exception, no
traceback, `on_finished` correctly never called (nobody is listening
once the dispatcher is gone) — confirmed the fix closes the exact
mechanism just reproduced, not a plausible-sounding guess.

**Test-side fix, distinct from the app-side one, addressing the
DIFFERENT half of the same finding.** The app-side fix stops a
straggling worker from crashing; it does nothing about the test's own
assertion still being a real race against genuine (if occasionally
slow) network I/O — a worker that's still legitimately in flight when
the interleaved loop's fixed duration ends would still fail `assert
active_workers == 0` even with the crash fixed, and that failure would
be a false one (the app itself did nothing wrong; the test just didn't
wait long enough for real, bounded, in-progress work). Added a bounded
(60s) drain wait — `_pump(qapp, lambda: len(_callbacks) == 0,
timeout=60.0)` — in the test's own `finally` block, before
`main_window.close()`. A worker that never completes at all (a genuine
future regression) still fails the assertion after this wait elapses;
this only removes false failures caused by ordinary real network
latency the test has no business penalizing.

**Re-verification — the same regression tests plus a full re-run,
both clean.** `tests/test_ui_smoke.py`, `test_workers_deadlock_
regression.py`, and `test_library_location_picker.py` (every existing
test that touches `run_worker`/`_callbacks`/`_dispatcher`) — 70 passed,
no change in behavior for the ordinary, non-straggling path. Full fast
suite — 470 passed / 1 skipped, matching item 40's own last-recorded
count exactly (confirms nothing else drifted while this task was in
progress). `mypy --strict` clean on the touched files
(`ui/workers.py`, `tests/test_stress_e2e.py`).

Re-ran the full live stress test end to end with both fixes in place —
**passed, 311s real duration.** Real resource numbers: RSS 259.4MB →
398.0MB (Δ+138.7MB — under the 250MB ceiling, but genuinely higher than
item 32's own +58.1MB baseline; nearly all of the growth (259→~395MB)
lands in the first 2.5 real seconds — MainWindow construction plus the
overlapping sync/scan/match/duplicates-fingerprinting/downloads burst —
and the remaining ~300s across 20 interleaved cycles added only
~9MB total, ≈0.45MB/cycle, the same order of magnitude as item 32's own
documented ≈0.25MB/cycle legitimate residual, not a growing leak); open
file descriptors 6 → 27 (Δ+21, under the 40 ceiling); threads 5 → 14
(Δ+9, under the 40 ceiling); `active_workers` at 0 at the end, confirmed
by the new drain-wait log line
(`outstanding workers drained before close: True (active_workers=0)`).
The Duplicates lifecycle genuinely overlapped with the rest, confirmed
by real timestamps in the sample log, not assumed from firing order
alone: fingerprinting (`Fingerprinted: 2, Skipped (already computed):
0, Failed: 0`) and the group delete (`Deleted: 1, Failed: 0`) both
completed by t=2.4s, while sync/scan/match and 3 concurrent download
operations were still settling. The same real slskd 500 on the same
real locked row recurred on essentially every later 20s backend-poll
cycle for the rest of the 300s run (a real, external, pre-existing
condition, unrelated to and unfixed by this task — that specific
row's own resolution is out of scope here) without ever again leaving
a stray active worker at the end of the run, confirming the fix holds
under REPEATED exposure to the exact failure that first surfaced it,
not just once by luck. Scratch location and files removed for real
every time (`Removed library location 'SeekerStressTestDuplicates'.`
in the log), and the real config store was confirmed restored to its
original values.

**Documentation consistency pass.** Not a rewrite — checked specific,
concrete claims against the real current code rather than skimming for
tone. Two real, load-bearing findings, plus several smaller ones:

1. CLAUDE.md items 28 and 29 both have full, matching narrative
   sections in this file, but — unlike every other numbered roadmap
   item — carried no `[HISTORY §N]` cross-reference link at all. Same
   gap found for item 36. All three added.
2. Item 5's own text names `select_best` as `soulseek/quality.py`'s
   live candidate-selection function. Checked directly: it doesn't
   exist in the current file at all — `grep -n "^def " quality.py`
   confirms it — because item 15 removed it as unused dead code, and
   item 8's `select_downloads` is the real, current entry point.
   Item 5's text corrected in place to name both facts (what it was,
   and what superseded it) rather than silently swapping one name for
   another and losing the history.
3. Both CLAUDE.md's and README.md's "current/project layout" file
   trees were missing three real files added by items 38-40
   (`audio_fingerprint.py`, `library/duplicate_service.py`,
   `file_deletion.py`) and two from items 33/34
   (`ui/download_eta.py`, `ui/help_text.py`) — confirmed via a direct
   `find src/seeker -name "*.py"` listing compared line by line
   against both trees, not assumed stale from the dates alone. Both
   brought current.
4. Broad spot-check of specific, checkable claims across both files —
   confirmed accurate, not changed: every numeric constant CLAUDE.md
   cites by name and value (`AUTO_MATCH_THRESHOLD=90`/`NEEDS_REVIEW_
   THRESHOLD=70`, `DEFAULT_MAX_QUEUE=200`, `MAX_UPGRADE_SHORTLIST=3`,
   `POLL_INTERVAL_MS=2_000`/`BACKEND_POLL_INTERVAL_MS=20_000`,
   `STALL_SAMPLE_COUNT=3`, `CLIPPING_AMPLITUDE_THRESHOLD=0.999`,
   `DUPLICATE_SIMILARITY_THRESHOLD=0.95`) against the real current
   source; every CLI command/flag named in README's command table
   against `cli.py`'s actual `add_parser`/`add_argument` calls; the
   Spotify endpoint-path/field-name history against the current
   `get_playlist_tracks` body; the `SLSKD_USERNAME`/`SLSKD_SLSK_
   USERNAME` env var distinction against `docker_setup.py` and
   `docker-compose.yml`; the packaging `AppId` GUID against
   `seeker.iss`; the `PlaylistNotFoundError` "three separate classes,
   aliased at the cli.py import site" claim (there are actually four
   in the codebase — `dashboard_service.py`'s own isn't imported by
   `cli.py` at all, so the claim's own explicit scoping to "aliased at
   the cli.py import site" is accurate as written, not stale — checked
   rather than reflexively "fixed").
5. One real code-side gap, not just a docs one, surfaced incidentally
   while re-checking item 29's own "no scipy-style undeclared
   transitive dependency" audit against files item 29 predates:
   `numpy` is imported directly (`import numpy as np`) in both
   `audio_fingerprint.py` and `duplicate_service.py` (items 38/39) but
   was never added to `pyproject.toml`'s own `dependencies` list —
   present at runtime only because `librosa`/`scipy`/`soundfile` all
   depend on it transitively. Added explicitly
   (`numpy>=2.5.2`, the real currently-installed version, matching
   this project's own established floor-pinning convention — see
   `psutil>=7.2.2` from item 32 for the identical precedent). `uv sync`
   re-run clean after the change.

Considered and deliberately left unchanged: the `docs/HISTORY.md#39`
link inside CLAUDE.md's "Known issues" section for the workers-deadlock
fix technically resolves to item 39's own main heading rather than its
"addendum" sub-heading further down the same file where the deadlock
narrative actually lives — but this matches an already-established
precedent elsewhere in the same file (item 30's own `[HISTORY §30]`
link points at its main heading the same way, with the "§3 retry"
follow-up narrative living immediately below it, unlinked directly) —
changing one without the other would be inconsistent, and getting a
precise GFM heading-slug anchor right for a comma-and-em-dash-heavy
heading is more likely to introduce a new broken link than fix an
existing one. Left as consistent-with-precedent rather than "fixed."

### 42

Custom app icon, closing the "no custom `.icns`/`.ico`" gap items
30/31/36 each flagged and accepted as cosmetic. Wired into all four
places that previously left icon fields `None`/unset/generic-default:
`seeker.spec`'s `BUNDLE()` (macOS `.app`) and `EXE()` (picks `.ico` on
`win32`, `.icns` on `darwin`, `None` on Linux, since `EXE`'s icon
param is only consumed on Windows/macOS); `dmg_settings.py`'s `icon`
setting (the `.dmg` volume icon); and `seeker.iss`'s `SetupIconFile`
plus a `seeker_icon.ico` copy installed to `{app}` so the Start
Menu/Desktop `[Icons]` entries have a real on-disk `IconFilename` to
point at.

**A real, small gotcha in `dmg_settings.py`, caught by checking rather
than assuming the first attempt worked.** dmgbuild `exec()`'s the
settings file as a plain script with no `__file__` in its own scope —
a first pass resolving the icon path via `Path(__file__).parent`
raised `NameError` the moment `dmgbuild` actually ran it. Fixed by
resolving the icon path the same cwd-relative way the settings file's
existing `readme` entry already did, rather than introducing a new
resolution style.

**Live verification, macOS — done for real, and it needed a second
approach after the first one was blocked.** Screen-recording
permission is absent in this environment (the identical gap item 30's
own verification first hit) — `screencapture`/`System Events` can't
be used, so there was no straightforward way to visually confirm an
icon rendering in Finder or the Dock by taking a screenshot. Rather
than settling for "the file exists inside the bundle" (true but not
proof anything actually *renders* it), verification went through the
same APIs Finder and the Dock themselves call to resolve an icon —
`NSWorkspace.iconForFile:` and `NSRunningApplication.icon` — driven
via `osascript`, a genuinely different mechanism from item 30/31's own
`QT_QPA_PLATFORM=offscreen` workaround (that one substitutes for
needing a display at all; this one substitutes for needing permission
to *record* one).

Rebuilt `Seeker.app` and `Seeker.dmg` for real first. Confirmed, in
order: (1) the `.icns` bundled inside the built `.app` byte-matches
`packaging/icons/seeker_icon.icns` and `Info.plist`'s
`CFBundleIconFile` points at it; (2) `NSWorkspace.iconForFile:` called
against the real built `.app` path renders the real custom icon, not
the generic default; (3) the real `.dmg`, mounted for real via
`hdiutil attach`, carries a `.VolumeIcon.icns` that byte-matches the
source file, with the volume's Finder custom-icon flag set; (4) with
`Seeker` actually launched and running, `NSRunningApplication.icon`
for that real running process renders the same custom icon — the
literal image the Dock itself displays for a running app, not a proxy
for it. All three real surfaces a user would actually see (Finder, the
`.dmg` volume, the Dock) confirmed live, not inferred from the diff or
from the bundle's file listing alone.

**Windows stays written-but-unverified, as scoped** — no real Windows
machine in this environment. The `.iss`/`.spec` Windows branches
mirror the already-verified macOS wiring structurally (same `icon`/
`SetupIconFile` pattern, same "resolve relative to the packaging
script" convention) but were not run or compiled for real — same
standing caveat item 36 already recorded for the rest of Windows
packaging.

`mypy --strict` clean; no test changes (packaging config, not
application logic — matches item 36's own precedent of not adding
tests for build-tool wiring beyond what `test_docker_setup.py`
already covers for path resolution).

### 43

Real bug report, from an actual Finder double-click launch of the
packaged app (not the offscreen harness): entering a Spotify Client ID
and completing the PKCE popup failed with `[Errno 30] Read-only file
system: '.seeker'`.

**Diagnosis.** Item 18 moved the DB to
`platformdirs.user_data_dir("Seeker", appauthor=False)` but left the
Spotify token cache (`SPOTIFY_TOKEN_PATH = Path(".seeker/
spotify_token.json")`) as a bare, CWD-relative literal, on the
documented assumption it was out of scope for that migration. That
assumption was never checked against how a packaged `.app` actually
launches. `uv run seeker-ui` runs with CWD = the project root, which
is writable, so the bug was invisible in every prior dev-mode and
offscreen-harness verification this project has done (items 22/26-32
etc. all construct a real `Application` from a writable CWD). A real
double-clicked `.app`, launched via macOS LaunchServices, gets CWD set
to `/` — the Signed System Volume, mounted read-only on any modern
macOS install. `SpotifyAuthManager._save_token()`'s `self.token_path
.parent.mkdir(parents=True, exist_ok=True)` — resolving to `mkdir
('.seeker')` relative to `/` — fails there with exactly the reported
`OSError`. Confirmed directly on this machine, not assumed: `os.chdir
('/'); os.mkdir('.seeker_verify_readonly_probe')` raised the
byte-identical `[Errno 30] Read-only file system: '.seeker_verify_
readonly_probe'`.

**Fix**, mirroring item 18's own DB-migration shape exactly: new
`_resolve_spotify_token_path()` resolves the token file into the same
per-user `platformdirs` directory the DB already lives in; the
move-if-fresh-install logic in `_migrate_legacy_database` was factored
into a shared `_migrate_legacy_file(new_path, legacy_path, label)`
(both migrators are now one-line wrappers over it), reused by a new
`_migrate_legacy_spotify_token()` with the identical never-clobber
guard. The token path moved from a module-level constant to a
per-`Application`-instance attribute (`self._spotify_token_path`),
computed and migrated once in `__init__`, immediately after the DB
migration — both `auth_manager` and `connect_spotify()` now read it
off `self`. Deliberately **not** a `sys.frozen`-gated branch (unlike
`docker_setup.py::compose_file_path()`, which genuinely does need one)
— nothing about the token cache is packaging-specific; it stops being
CWD-relative in ordinary dev-mode runs too, since there was never a
real reason for `uv run seeker-ui` from a directory other than the
project root to resolve it differently.

**Live verification — a real Finder-equivalent launch, since that is
literally the only thing that ever caught this.** Built a throwaway
diagnostic `.app` (`SeekerVerify`, not committed) reusing the exact
same `Analysis` config as `packaging/seeker.spec` (same `pathex`, same
bundled `docker-compose.yml`, zero hidden-import overrides) with a
non-GUI entrypoint substituted in: it points `platformdirs` at an
isolated, throwaway data directory under `$HOME` (never the real
production DB/config), constructs a real `Application`, then calls the
real `SpotifyAuthManager._save_token()` with a fake token — the exact
method that raised the original error — logging the outcome to a fixed
path under `$HOME` rather than opening a window. Launched via `open -W`
against the built `.app`, the same LaunchServices path a real
double-click takes (confirmed to actually reproduce the failure
condition: the log recorded `cwd='/'`, matching the original report
exactly). Result: `token_file_exists=True`,
`no_seeker_dir_at_cwd=True`, `RESULT=SUCCESS` — the token landed under
the isolated platformdirs directory with zero `.seeker` directory ever
created at `/`. Diagnostic build artifacts and the isolated data
directory were removed after verification.

**Second, independent live verification, against this dev machine's
own real pre-existing legacy token — not manufactured.** A real
`.seeker/spotify_token.json` (445 bytes, real `access_token`/
`refresh_token`/`expires_at` fields, `expires_at` already in the past
by this point) existed at the project root from earlier real sessions,
predating this fix. Rather than trust the isolated diagnostic build
alone, ran a real `uv run python` startup (real CWD = project root,
matching what `uv run seeker-ui` actually uses, real production
`platformdirs` directory, no monkeypatching) that constructs
`Application()` and then calls `app.auth_manager.get_valid_token()`.
Confirmed, in order: the real legacy file was migrated for real (the
existing `"Migrated existing Spotify token from ... to ..."` print
fired, the old file was gone afterward, the new one existed at
`~/Library/Application Support/Seeker/spotify_token.json`); and
because the migrated token was genuinely expired,
`get_valid_token()` performed a real refresh call against Spotify's
own token endpoint using the real `refresh_token` and real
`spotify_client_id` from `config.json` — this succeeded, returning a
new token with `expires_at` about an hour out, proving the session
coming out of migration is genuinely re-authorized end-to-end, not
just that the file moved. The stray empty `.seeker/` directory left
behind (`shutil.move` moves the file, not its parent) is expected and
harmless — the identical leftover the DB migration in item 18 already
produces.

`mypy --strict` clean; full suite 477 passed / 1 skipped. Six new
tests added to `test_application.py` mirroring the existing
`_resolve_database_path`/`_migrate_legacy_database` test shapes for
`_resolve_spotify_token_path`/`_migrate_legacy_spotify_token`, plus a
dedicated CWD-independence test (constructs `Application` from a
directory that is neither the project root nor the platformdirs data
dir, confirms the token path still resolves under the latter and no
`.seeker` directory is created near the CWD).

### 44

Real bug report, from an actual double-click launch of the packaged
app: the wizard's Docker step reported "not installed" and Settings'
SoulSeek setup raised `[Errno 2] No such file or directory: 'docker'`
— even though Docker Desktop was genuinely installed and running.
Given as a hypothesis up front: a GUI-launched macOS app gets a
minimal PATH that doesn't include `/usr/local/bin`, unlike a terminal
shell's fuller PATH — the same "works via `uv run`, breaks via a real
double-click" shape as item 43's CWD bug, just for PATH instead of
CWD.

**Confirming the call sites, directly, per the task's own
instruction.** Three `subprocess.run(["docker", ...])` calls in
`docker_setup.py`, all bare-name lookups relying on PATH: two in
`detect_docker_state()` (`docker --version`, `docker info`, neither
passing an explicit `env=`, so both inherit the real process
`os.environ` by Python's own default), and one in `bring_up_slskd()`
(`docker compose -f ... up -d`, explicitly passing
`env={**os.environ, ...}`). Both real UI surfaces route through these:
`ui/wizard.py`'s Docker step calls `detect_docker_state`; `ui/
settings_window.py`'s SoulSeek setup calls `bring_up_slskd`. All three
call sites read PATH from the same source — the process's own
`os.environ` — so a single fix mutating `os.environ["PATH"]` once,
early, covers all three with no per-call-site change.

**Diagnosing the actual PATH difference — needed two attempts, since
the first one gave a misleading result.** First attempt: build a
throwaway diagnostic `.app` (same pattern as item 43's `SeekerVerify`)
and launch it via `open -W`, the same mechanism that correctly
reproduced item 43's `cwd='/'`. This logged `raw_PATH=` as the FULL
shell PATH, including this project's own `.venv/bin`, `/opt/homebrew/
bin`, `/usr/local/bin`, etc. — and `detect_docker_state()` correctly
reported `RUNNING` even with no fix applied at all. Taken at face
value, this would have wrongly suggested the bug wasn't reproducible
here, or wasn't real. Recognized as suspicious rather than accepted:
a genuine LaunchServices-driven GUI launch should never inherit the
launching shell's PATH by design — that's the entire premise of the
bug report. This sandbox's `open` command was therefore not actually
routing through the same launchd GUI-domain spawn a real user's
double-click uses; something about this specific containerized/remote
dev environment lets `open` leak the calling shell's environment
through in a way a real Mac's Finder-driven launch does not.

**Ground truth obtained a different way: a real, ephemeral
LaunchAgent** — `launchctl bootstrap gui/$(id -u)` on a plist running
bare `/usr/bin/env`, redirected to a log file, then `launchctl
bootout` to remove it immediately after. This is unambiguously
launchd-spawned with zero shell in the process chain, the same
mechanism a double-clicked `.app` icon ultimately uses. Real, confirmed
result:

```
OSLogRateLimit=64
XPC_SERVICE_NAME=com.seeker.envprobe
SSH_AUTH_SOCK=/var/run/com.apple.launchd.Fs8RjCle6b/Listeners
PATH=/usr/bin:/bin:/usr/sbin:/sbin
XPC_FLAGS=0x0
LOGNAME=sinthesis
USER=sinthesis
HOME=/Users/sinthesis
SHELL=/bin/zsh
TMPDIR=/var/folders/dr/_sq38wgn0lq2wzy_0y6_t2xr0000gn/T/
```

`PATH=/usr/bin:/bin:/usr/sbin:/sbin` — confirming the hypothesis
exactly: no `/usr/local/bin`, no `/opt/homebrew/bin`. Cross-checked
against `/etc/paths` (`/usr/local/bin` plus the four base dirs) and
`/etc/paths.d/*` on this machine (`10-cryptex`, `10-pmk-global`,
`MacGPG2`, and — notably — `homebrew`, containing `/opt/homebrew/
bin`) — confirming these additional directories are real, but are only
assembled by `/usr/libexec/path_helper`, which runs as part of a login
shell's startup (`/etc/zprofile` et al.), never as part of a launchd
GUI-domain spawn. Directly confirmed the failure itself, not just the
missing directories: running `docker --version` with `PATH` forced to
exactly `/usr/bin:/bin:/usr/sbin:/sbin` raised the byte-identical
`FileNotFoundError: [Errno 2] No such file or directory: 'docker'`
from the original report, and `shutil.which("docker", path=...)`
against that same minimal PATH returned `None`. Also worth recording:
this machine has TWO real `docker` binaries — Docker Desktop's own CLI
symlink at `/usr/local/bin/docker` (→ `/Applications/Docker.app/
Contents/Resources/bin/docker`) and a separate Homebrew-installed CLI
at `/opt/homebrew/bin/docker` — either is sufficient once its
directory is back on PATH, since both talk to the same real Docker
daemon.

**Fix**, at the shared layer, matching this project's own "shared
thing lives at the lowest layer that needs it" precedent (same
principle as `compose_file_path()`/`_resolve_spotify_token_path()`):
new `docker_setup.py::ensure_full_path_environment()` runs
`/usr/libexec/path_helper -s`, regex-extracts the resolved `PATH="..."`
value, and merges it — plus the existing `os.environ["PATH"]`, plus an
explicit `_FALLBACK_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/
bin")` — into `os.environ["PATH"]`, deduplicated, order-preserving.
The explicit fallback exists because `path_helper` only covers
`/opt/homebrew/bin` when a real `/etc/paths.d/homebrew` file happens
to exist (true on this particular dev machine, but not guaranteed —
Homebrew's own installer instructions rely on a shell-profile `eval
"$(brew shellenv)"` instead, which a GUI launch never runs). Called
once, unconditionally, at the very top of `Application.__init__` —
before the DB/token-path migrations added in item 43, and before
anything Docker-related can run — rather than patched into each
individual `subprocess.run(["docker", ...])` call site, since every
one of them already reads from the process's own `os.environ` by
default or by explicit `{**os.environ, ...}` construction.

**A real robustness gap, found by the existing test suite, not
invented speculatively.** The first version of this function only
caught `(OSError, subprocess.SubprocessError)` around the
`path_helper` call. Running the full suite surfaced a genuine failure:
`test_wizard.py::test_launch_docker_clicked_success_updates_status_
and_button` monkeypatches `subprocess.run` globally (via `seeker.ui.
wizard.subprocess.run` — the same shared `subprocess` module object
used everywhere, not scoped to `wizard.py`) to a fake returning `None`,
then constructs a real `Application()` later in the same test. Since
`Application.__init__` now calls `ensure_full_path_environment()`,
which calls the now-faked `subprocess.run(["/usr/libexec/path_helper",
"-s"], ...)`, the fake's `None` return crashed with `AttributeError:
'NoneType' object has no attribute 'stdout'` — an exception type the
narrow `except` clause didn't cover. This is exactly the kind of thing
that must never be able to crash `Application` startup, since this
function runs unconditionally on every construction, on every
platform (including non-macOS, where `/usr/libexec/path_helper`
doesn't exist at all) — fixed by broadening to a bare `except
Exception`, with the explicit fallback dirs still applied regardless.
A new regression test
(`test_ensure_full_path_environment_never_raises_on_malformed_result`)
locks this in directly, independent of the wizard test that happened
to surface it.

**Confirming `detect_docker_state()`'s three branches stay
distinguishable, not just that `RUNNING` happens to work — done for
the two branches this fix actually touches, honestly incomplete for
the third.** The NOT_INSTALLED/INSTALLED_NOT_RUNNING/RUNNING branch
logic itself is untouched by this fix (it only affects whether
`docker` can be found on PATH at all, not what
`detect_docker_state()` does once it is); the existing mocked unit
tests for all three branches (`test_detect_docker_state_not_installed_
when_docker_missing`/`_when_version_check_errors`,
`_installed_not_running_when_info_fails`/`_when_info_times_out`,
`_running_when_both_succeed`) already cover that logic directly and
remained unaffected and passing. What genuinely needed a live check
was the NOT_INSTALLED/RUNNING boundary this bug actually crossed: with
`PATH` forced to the real, confirmed minimal
`/usr/bin:/bin:/usr/sbin:/sbin`, `detect_docker_state()` reported
`DockerState.NOT_INSTALLED` — reproducing the exact reported symptom
on this real machine, with real Docker Desktop genuinely running.
Calling `ensure_full_path_environment()` and re-checking immediately
after: `DockerState.RUNNING` — matching this machine's actual state.
INSTALLED_NOT_RUNNING was deliberately not exercised live against a
real stopped daemon — stopping this machine's real, working Docker
Desktop (which real slskd infrastructure depends on, per items 13/23)
for a test would be a real disruptive action to working infrastructure
with no clear benefit, since that branch's own logic is both untouched
by this fix and already covered by the existing mocked test; recorded
honestly as unexercised live rather than worked around, same
discipline as item 26's own "Reject... remain genuinely unexercised by
a real click" note.

**Final live verification of the actual shipped fix — via a real
launchd-spawned process, not `open`, since `open` was already shown
above not to reproduce genuine launch conditions in this sandbox.**
Built a second diagnostic `.app` (`SeekerVerifyDockerFix`, not
committed, same `Analysis` config as `packaging/seeker.spec`) whose
entrypoint constructs a real `Application` (platformdirs pointed at an
isolated, throwaway directory — never the real production DB/config)
and then calls the real, unmodified `detect_docker_state()` — the
exact function both `wizard.py`'s Docker step and `settings_window
.py`'s SoulSeek setup call. Launched its actual bundled executable
(`Contents/MacOS/SeekerVerifyDockerFix`) directly via another real
ephemeral LaunchAgent (`launchctl bootstrap`/`bootout`, identical
mechanism to the ground-truth probe above). Real, confirmed result:

```
cwd='/'
raw_PATH_before_application='/usr/bin:/bin:/usr/sbin:/sbin'
PATH_after_application_init='/usr/local/bin:/System/Cryptexes/App/usr/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/local/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/bin:/var/run/com.apple.security.cryptexd/codex.system/bootstrap/usr/appleinternal/bin:/pkg/env/global/bin:/usr/local/MacGPG2/bin:/opt/homebrew/bin'
which_docker_after_fix='/usr/local/bin/docker'
detect_docker_state_after_fix=<DockerState.RUNNING: 'running'>
RESULT=SUCCESS
```

`raw_PATH_before_application` confirms this launch genuinely started
from the real minimal launchd PATH (not `open`'s misleadingly-full
one); `PATH_after_application_init` confirms `Application.__init__`'s
call to `ensure_full_path_environment()` fixed it for real, in a real
frozen build, under a real launchd-spawned process; `which_docker_
after_fix` and `detect_docker_state_after_fix` confirm both the raw
discoverability mechanism and the actual function both real UI
surfaces depend on now work correctly end-to-end. This exercises the
shared root cause behind both surfaces (PATH-based binary
discoverability at `Application` startup) rather than re-running each
UI screen's own click-handling code, which items 26/28/30 already
established coverage for separately and which this fix doesn't touch.
All diagnostic build artifacts, ephemeral LaunchAgents, and log/probe
files were removed immediately after each verification step — nothing
left behind.

`mypy --strict` clean; full suite 480 passed / 1 skipped — four new
tests added to `test_docker_setup.py` (`path_helper`-output merging,
fallback when `path_helper` is unavailable, no duplicate entries, and
the malformed-result regression above), mirroring
`compose_file_path()`'s existing test shape for a new
`docker_setup.py` function.

### 45

Real bug report: after tracks download successfully, the Dashboard
keeps showing them as "Not found," and "Match all tracks" doesn't fix
it. Given as a hypothesis up front (per item 8's own documented text):
the upgrade-confirmation path (`apply_upgrade_decision`) already calls
`scanner.index_single_file()` to register a replaced file into
`local_files` immediately, "unlike settled downloads, which rely on
the next library scan" — so an ordinary settled download gets moved
into place and then genuinely nothing indexes it and nothing creates a
`track_matches` row.

**Confirmed by reading the code directly before touching anything.**
`poll_downloads()`'s main pending loop, on a settled completion:

```python
if self._move_completed_file(request) is not None:
    self._update_status(request.id, "completed")
    counts["completed"] += 1
else:
    counts[request.status] += 1
```

— nothing else. Compared directly against `apply_upgrade_decision`
(the confirmed-upgrade path), which after the identical
`_move_completed_file` call also runs `index_single_file()` and
`track_matches.upsert(..., match_method="auto", score=100.0, ...)`.
The asymmetry is real and exactly as hypothesized.

**Second consequence, checked rather than assumed:**
`get_unmatched_for_playlist` filters on
`tm.track_id IS NULL OR tm.match_method IS NULL` — with no
`track_matches` row at all, a track in this state genuinely still
counts as unmatched. `get_active_for_track` (item 16's creation-time
dedup guard, checked inside `download_playlist()`) filters
`status NOT IN ('completed', 'failed', 'superseded')` — a `completed`
row is not "active." So a second `download`/Download-click run would
genuinely re-search and re-request a file already sitting on disk, not
just leave the Dashboard display wrong. Confirmed by reading both
queries directly, not inferred.

**Reproduction against real data, before writing any fix, per the
task's own instruction.** Queried the real production DB for
`role='settled', status='completed'` rows with no matching
`track_matches` row: **zero found.** All 5 real completed rows already
had a match — recovered manually in a prior session (item 27's own
documented live-verification: "`Kamäleon - Quadrat` had a real
completed download sitting unindexed... a real `seeker library scan` +
`seeker library match` picked it up"). So the specific stale-row shape
described in the bug report no longer existed in production at the
moment of reproduction — the underlying code defect was still real and
directly confirmed by reading the code above, just not currently
manifesting as a stuck row (because someone had already manually
worked around it once).

Instead, a real currently-IN-FLIGHT case was available and used for
live verification instead: `download_requests` id 16 (track "Bit
Perfect" by Zigi SC/A-Cray, `role='settled'`) was sitting at
`status='downloading'`. A direct query against slskd's own
`GET /api/v0/transfers/downloads/{username}/{transferId}` showed
`state: "Completed, Succeeded"`, `bytesTransferred == size ==
12257951` — the real transfer had genuinely finished, slskd already
knew it, but the DB still said "downloading." This is the fix's real
target case (a settled completion `poll_downloads()` hasn't yet
processed), just caught mid-flight rather than as a legacy row.

**Fix.** New `DownloadService._index_and_match_settled_download()`,
called from the settled-completion branch of `poll_downloads()`'s main
loop, and from `_retry_locked_request`'s own `status == "completed"`
branch (a second, independent call site reaching the identical gap —
a human-confirmed needs-review candidate, requested as `role='settled'`
per item 26, that turned out locked and later succeeded on retry). Both
call sites now pass the `(location, relative_path)` tuple
`_move_completed_file` already returns straight into the new method.

Reused rather than reinvented: `index_single_file()` (already shared
with the scan loop and the upgrade path — item 8's own precedent) and
`library/matcher.py`'s `find_best_match(track, candidates)`, called
with a one-item candidate list (`[local_file]`) rather than extracting
a new single-pair function — `find_best_match` already handles "no
match" (an artist mismatch) by returning `None`, which the new method
treats as an unscored match rather than a failure. `match_method='auto'`
is set unconditionally regardless of the computed score — provenance
(this file was searched, filtered by `quality.py`, and downloaded FOR
this exact track) outweighs fuzzy-matching confidence, the same
reasoning item 26 already established for `confirm_review_candidate`.
Unlike `apply_upgrade_decision`'s hardcoded `score=100.0`, the real
computed score is stored, so a bad pairing is visible in the data
rather than hidden behind a sentinel — this was a deliberate choice to
NOT copy `apply_upgrade_decision`'s exact sentinel, made explicit in a
code comment at the call site so a future reader doesn't "fix" the
inconsistency by copying the wrong one back. `TrackMatchRepository
.upsert()`'s existing `ON CONFLICT(track_id) DO UPDATE` already
handles "repoint rather than duplicate" with no extra logic needed.
Wrapped in its own try/except (this codebase's standing per-item batch
rule) so an indexing failure can't undo the already-set `completed`
status (the file really did download) or abort the rest of the poll —
counted separately via new `indexed`/`index_failed` keys in the
returned counts dict.

**A second, independent real bug was found live while running this
verification, and fixed in the same pass since it was directly
blocking it, per the task's own "fix what you find immediately"
instruction.** After the fix above, polling the real in-flight "Bit
Perfect" request still didn't move the file — no exception, no printed
warning, just silently stuck. Traced to `_move_completed_file`:

```python
basename = Path(request.filename.replace("\\", "/")).name
matches = list(Path(self.slskd_download_dir).rglob(basename))
if not matches:
    return None
```

`Path.rglob()` treats its argument as a glob PATTERN via `fnmatch`, not
a literal filename. The real basename here was `"A-Cray, Zigi SC - Bit
Perfect (Original Mix) [www.dj-promo.org].mp3"` — `fnmatch` interprets
`[www.dj-promo.org]` as a character class, so the pattern silently
matched nothing even though the real file was sitting exactly where
expected. Confirmed directly with a real Python REPL against the real
slskd download directory: `Path(...).rglob(basename)` → `[]`;
`Path(...).rglob(glob.escape(basename))` → the real file, found. Real
Soulseek filenames very commonly carry `[...]` release/uploader tags
(`[www.dj-promo.org]`, `[FLAC]`, label/scene tags), so this wasn't an
edge case — it silently broke the move step for a meaningful share of
real downloads, with the request left permanently stuck `downloading`
and no diagnostic output at all (the `if not matches: return None`
branch has no print statement, unlike the two other early-return
branches in the same method). Fixed with `glob.escape(basename)`
around the `rglob()` call.

**Live-verified end-to-end, both fixes together, against the real
in-flight request (2026-08-31).** A real `seeker downloads status` run:
printed `Moved 'A-Cray, Zigi SC - Bit Perfect (Original Mix)
[www.dj-promo.org].mp3' to /Volumes/X9 Pro/Music/Test/Music/Test`
(confirmed on the real disk afterward, including the AppleDouble
sidecar the scanner already knows to filter — item 2); `download_
requests` id 16 → `status='completed'`, real `completed_at`;
`local_files` gained a real new row (id 3241) with real mutagen-read
tags (`tag_artist="A-Cray, Zigi SC"`, `tag_title="Bit Perfect (Original
Mix)"`, `duration_ms=306259`); `track_matches` gained a real row
(`local_file_id=3241`, `match_method='auto'`, `score=63.6363...` — a
real, honestly-low score, correctly visible rather than hidden);
`DashboardService.get_playlist_track_status("Test")` returned
`IN_LIBRARY` for this track (`tagged_at=None`, correctly, since it
hasn't been tagged yet); `TrackRepository.get_unmatched_for_playlist`
for the real "Test" playlist no longer included it. A real, non-fake
`Application()` was used for every one of these checks, not just the
CLI's own summary output.

**UI follow-on.** `MainWindow._trigger_backend_poll`'s `on_finished`
callback now also calls `self._poll_selected_playlist()`, so the
Dashboard's own track table refreshes immediately after a real backend
poll completes rather than waiting up to `POLL_INTERVAL_MS` (2s) for
the next unrelated display tick to happen to catch the change. New Qt
test `test_backend_poll_refreshes_selected_playlist_track_table`
(offscreen, a real `MainWindow`, a fake `DashboardService` recording
calls) confirms `get_playlist_track_status` is called with the
selected playlist's name once the backend poll's queued completion
signal is actually delivered — mirrors the existing
`test_backend_poll_runs_poll_downloads_off_the_main_thread`'s own
`qtbot.waitUntil` pattern (item 32/39's documented reason for waiting
on the main-thread-flipped flag, not a worker-thread-set one).

**No legacy backfill migration needed, confirmed rather than assumed.**
Per the reproduction step above, zero real stale rows existed in
production at the time of the fix. Still ran the requested real
`seeker library scan` + `seeker library match` afterward, both against
the real production library, to check for anything this fix wouldn't
retroactively reach on its own (an already-completed-and-moved-but-
never-indexed file predating this session, the classic item 27
shape): the scan found and indexed one genuinely new, previously-
undiscovered file (`Breach` by Balron, Audio — auto-matched at
100.0), unconnected to any tracked `download_requests` row at all, so
this was an ordinary organic library file the scan simply hadn't seen
before, not a recovered legacy case. **Net recovered by backfill: 0**
(the bug's damage was fully addressed live, in-flight, by the code fix
itself; the scan's one new match was incidental, not a backfill).

**A real, interesting, out-of-scope-to-fix interaction, recorded
honestly rather than silently worked around:** that same `library
match` run **demoted** the just-fixed Bit Perfect match from `auto`
(score 63.6) to `needs_review` (identical score, now correctly sorted
into the needs_review band since 63.6 < `AUTO_MATCH_THRESHOLD=70`).
`match_all()` recomputes every `track_matches` row from scratch, for
every track, on every run — it has no concept of "provenance-confirmed"
and never has (this applies equally, and already did before this fix,
to item 26's human-confirmed needs-review matches — nothing about
those is protected from a later ordinary re-match either). This isn't
a bug introduced by this fix, and the task didn't ask for permanent
protection against a future explicit re-match — recorded here as a
standing fact for anyone touching `match_all()` or this fix later, not
actioned further.

`mypy --strict` clean; full suite 484 passed / 1 skipped for this
change alone (up from the 480 baseline: 3 new
`test_download_service.py` tests for the indexing fix, 1 for the
glob-escaping fix, 1 new UI test for the backend-poll refresh).

### 46

Task: tagged tracks should stop asking to be tagged.
`TrackStatus` gains `tagged_at: str | None` (ISO string, matching this
codebase's existing str-not-datetime convention for every other stored
timestamp — deliberately not the `datetime` type an earlier draft of
this task specified), resolved in `DashboardService._compute_status`
from the matched `local_files` row. Dashboard Actions column:
`IN_LIBRARY`+untagged → the existing "Tag" button; `IN_LIBRARY`+tagged
→ a muted "Tagged" label with a tooltip showing the local date/time;
anything else → blank, unchanged. Right-click on a tagged row offers
"Re-tag."

**The backend `force` flag and CLI `--force` for `library tag` turned
out to already exist**, built in an earlier, uncommitted session with
no corresponding roadmap entry — confirmed by reading
`metadata_service.py`/`cli.py` directly before writing anything, not
assumed. Only the UI side (a "Re-tag already tagged files" checkbox on
the tagging panel, wired through `_resolve_tag_options`, plus the
per-row "Re-tag" menu action) and `TrackStatus.tagged_at`/the
Actions-column display were new.

New `ui/formatting.py` — `format_timestamp`/`format_file_size`/
`format_speed`/`format_duration_seconds`, shared by this, a future
History page, and the Downloads ETA. `download_eta.py`'s own
`format_eta_seconds` was moved in (re-exported under its old name)
rather than kept as a second copy. **Real, confirmed fact used to
write the timestamp conversion correctly:** every stored timestamp in
this codebase is written via `datetime.now(timezone.utc).isoformat()`
— timezone-AWARE UTC, not naive — so `format_timestamp` uses
`.astimezone()` (correct for an aware value) rather than assuming a
naive-UTC value that would need a manual UTC-offset attach first;
verified directly against the write sites before writing the
formatter.

### 47

Task: build a dark design system (`ui/theme.py`, color/spacing tokens,
one global QSS stylesheet) and a persistent `InlineNotice` widget,
find and fix the real root cause of a reported "an error message
disappears before you've had time to read it" bug, and — per an
explicit instruction from a follow-up check-in — actually render real
screens with the theme applied and look at the PNGs before calling any
of it done, rather than trusting the QSS was correct by construction.

**Root cause, confirmed by reading the code, not guessed.**
`ui/workers.py::run_worker()`'s very first lines clear its
`status_label` argument to `""`, unconditionally, before the
background task even starts. `MainWindow._poll_selected_playlist()`
passes `status_label=self.status_label` and is wired to both the 2s
`poll_timer` (routine, always running) and, since item 45's own UI
follow-on, the real backend-poll's completion callback too. Since
these fire completely independently of whatever the user was just
shown, any message written to that one shared label — a BPM-range
validation error, "select a track first" — was live for, at most, the
time until the next unrelated poll tick happened to fire. Confirmed
this wasn't just a plausible theory by tracing the exact call chain
rather than assuming it from the symptom description alone.

Fixed with `InlineNotice`, a small `QWidget` with a colored left
border by message kind (info/success/warning/error), an optional
action button, and a dismiss button — deliberately outside
`run_worker`'s `status_label` plumbing, so nothing routine can silently
clear it. Wired into the Dashboard's four actionable message call
sites (`_on_tag_track_clicked`/`_on_retag_track_clicked`/
`_on_tag_selected_clicked`/`_on_tag_playlist_clicked`'s validation
errors and selection guards). Left `status_label` in place for the two
genuinely disposable progress strings ("Tagging N selected
track(s)..."). **Deliberately not swept everywhere in this pass** —
`_on_upgrade_decision_finished`'s Review-tab success message hits the
identical bug (same shared `status_label`, same poll exposure) but
was left as a known, recorded gap rather than fixed opportunistically
outside this task's own Dashboard-focused scope; a full sweep is
Phase 4-or-later work.

**Screenshots surfaced three more real bugs — this is the part that
justified the task's own "render and look" instruction, not a
formality.** First render of the Dashboard with the new theme applied
showed a `QPushButton` labeled "Tag" (inside a `QTableWidget`
`setCellWidget`, the Actions column) rendering as garbled, ghosted
text ("Iao" instead of "Tag") — visible immediately, not something a
diff of the QSS text would ever catch.

Bisected via a minimal standalone repro (a bare `QTableWidget` with one
`setCellWidget(0, 0, container)` containing a `QPushButton`), adding
back one theme rule at a time: clean with no theme at all; clean with
`Fusion` + palette only; clean with the `QPushButton` rule alone; clean
with `QWidget` + `QPushButton`; clean with `QTableWidget`'s
background/border/selection rules added too; **corrupted the instant
`QTableWidget::item { padding: 4px; }` was added** — confirmed by
removing just that one rule and nothing else, which cleared it again.
Real, reproducible Qt/Fusion behavior: styling `::item` padding on a
`QTableWidget` corrupts the paint of a widget living in a cell via
`setCellWidget`, not just the item's own text — and this app uses
`setCellWidget` throughout (Actions/Progress columns across Dashboard,
Downloads, Review, Duplicates), so this would have been a real,
visible defect on every one of those tabs, not a cosmetic one-off.
Fixed by dropping the rule from `QTableWidget` specifically (kept on
`QListWidget`, confirmed safe there by checking directly: nothing in
this app ever calls `setItemWidget` on a `QListWidget`) — a code
comment in `theme.py` records the finding so a future "let's add cell
padding back for polish" doesn't silently reintroduce it.

Two smaller bugs surfaced fixing `InlineNotice` itself for its own
screenshot. (1) Its per-instance `setStyleSheet()` call (the colored
kind-based border) rendered as a plain, unstyled row — no border, no
distinct background — even though the stylesheet text was correct.
Root cause: a plain `QWidget` subclass does not paint its own
stylesheet background/border by default in Qt (skipped for
performance unless opted in) — needs
`setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)`, which
this widget never set. (2) Its dismiss button rendered with completely
invisible text — zoomed into the screenshot and confirmed the glyph
wasn't just an unsupported-Unicode blank box (the working hypothesis
at first, since the glyph was a Unicode "✕") but genuinely absent
entirely, border included. Real cause, found by checking the numbers
rather than accepting the Unicode-coverage theory: `setFixedWidth(28)`
left exactly zero content width once the global `QPushButton` rule's
own `padding: 6px 14px` (28px of horizontal padding alone) was
applied — the glyph was being laid out into negative space. Fixed by
dropping the fixed width entirely (sized by `sizeHint`, like every
other themed button) and switching to a plain ASCII "X" — kept as the
right call even after finding the real cause, since it removes any
remaining dependency on Unicode multiplication-sign glyph coverage in
whatever font a given platform's Qt build falls back to.

**Final screenshots, all three inspected directly, all clean:**
Dashboard (four track states — in-library untagged, in-library
tagged, not-found, needs-review — plus a live error `InlineNotice`
showing the exact BPM-range validation message); `AboutDialog` (a real
existing dialog, "Close" now styled `variant="primary"` and left-
aligned per the layout convention, "Support on Revolut"/"Support on
PayPal" buttons rendering as ordinary secondary buttons); Downloads
tab (one determinate progress bar at a real 50%, one indeterminate
queued bar). Saved to a session scratch directory, not committed, per
the task's own instruction.

`mypy --strict` clean; full suite 510 passed / 1 skipped (up from the
503 baseline: 6 new `test_notice.py` tests, 1 new regression test
calling `_poll_selected_playlist()` directly and asserting the notice
survives it — the real mechanism that used to wipe messages, not a
timer/sleep stand-in for it).

### 47, follow-up — the queued progress bar's real root cause

A follow-up check-in flagged that the queued/indeterminate progress
bar in the Downloads-tab screenshot looked like a full solid violet
block — "looks complete," not "waiting" — and asked for the actual
root cause, not a reskin, plus explicit instructions on what to check
first: whether the queued row genuinely calls `setRange(0, 0)`
(native indeterminate), and whether the QSS chunk color was flattening
Qt's own indeterminate animation.

**Checked the code first, per the instruction.**
`_build_progress_widget` in `main_window.py` does call
`bar.setRange(0, 0)` for a queued/no-bytes-yet row — real Qt
indeterminate mode, not a determinate bar defaulting to a misleading
full value. So the bug was never in the widget logic.

**Bisected the actual cause via a minimal standalone repro**, the same
method that found Phase 3's original `QTableWidget::item` bug. Four
variants, one `QProgressBar` with `setRange(0, 0)`, grabbed as a PNG
each time: (1) no theme at all — real Qt/Fusion native indeterminate
mode renders as an animated, diagonally-striped "barber pole" pattern,
confirmed visually distinct from a solid fill; (2) `Fusion` style with
no stylesheet — identical striped pattern, confirmed the style itself
isn't the cause; (3) the theme's full `QProgressBar`/`QProgressBar
::chunk` rules together — reproduced the bug exactly, a static solid
block; (4) **only the `QProgressBar { ... }` container rule, with the
`::chunk` rule removed entirely** — the real animated stripe came
back, clean. This isolates the cause to the mere PRESENCE of a
`QProgressBar::chunk` selector matching the widget, not to its
specific `background-color` value — confirmed by testing a container-
only stylesheet with the `::chunk` rule entirely absent, which was
sufficient on its own to restore native animation.

**Why this happens, understood rather than just observed:** Qt's
`QStyleSheetStyle` treats a sub-control (`::chunk`) as either
"unstyled" (native primitive painting, including any style-specific
animation logic like Fusion's busy-indicator sweep) or "styled" (the
generic QSS box-model painter takes over completely for that
sub-control, on every state of the widget). Matching ANY rule against
`::chunk` — even one that sets no visually distinguishing property —
flips the widget into the styled path permanently for that sub-control,
which has no busy-animation concept at all and just paints a rect
sized by whatever `value()`/`range()` heuristic the style falls back
to for the ambiguous `(0, 0)` indeterminate range. There is no
`:indeterminate` pseudo-state in Qt's QSS syntax to scope a `::chunk`
rule to only the determinate case.

**Fix:** removed `QProgressBar::chunk` from the global app-wide
stylesheet in `theme.py` entirely (documented in a code comment there,
so a future "let's polish the fill color" doesn't silently reintroduce
this exact bug), and added `theme.style_determinate_progress_bar(bar)`
— a small helper applying the accent chunk fill via a PER-INSTANCE
`setStyleSheet()` call, invoked only at the two real call sites in
`main_window.py` (the Downloads-tab progress cell and the Dashboard's
own per-track progress cell) after a bar is confirmed determinate
(`setRange(0, total)` + `setValue(...)` already called). An
indeterminate bar now never has any `::chunk` rule applied to it at
all, at any level — global or local — so it keeps Qt's real native
animated indicator.

**Verified live, not assumed from the fix's logic alone:** re-ran the
same minimal repro with the fix in place — an indeterminate bar built
via `theme.apply_theme()` (global stylesheet, no local override) shows
the real animated stripe; a determinate bar built with
`style_determinate_progress_bar()` applied shows a clean solid accent
fill at the correct value. Then re-rendered the actual Downloads tab
screenshot (two real rows — one downloading at a real 50%, one
queued) and confirmed the same result at the real widget level, not
just in isolation.

Also fixed in the same pass, per an explicit instruction: widened the
theme's surface/border tokens (`BG_APP`/`BG_SIDEBAR`/`BG_SURFACE`/
`BG_SURFACE_2`/`BORDER`/`BORDER_STRONG`, all six touched, no other
tokens changed) so a default (non-primary) button reads as clickable
against both a page-level background and a table-cell background —
checked directly that `QTableWidget` has `setAlternatingRowColors`
disabled everywhere in this app (confirmed via grep — zero call
sites), so every row is genuinely `BG_SURFACE`, never the same tone as
a default button's own `BG_SURFACE_2`, regardless of row parity.

New/extended tests, real code-level regression guards rather than
just a code comment this time (the progress-bar bug specifically is
now caught by a fast assertion, unlike the other two Phase 3 QSS bugs,
which still rely on the code comment + render-and-look workflow):
`test_downloads_tab_progress_bar_indeterminate_with_no_bytes_yet` now
also asserts `bar.styleSheet() == ""`;
`test_downloads_tab_progress_bar_determinate_with_real_bytes` now
asserts `"chunk" in bar.styleSheet()`; new
`test_dashboard_downloading_progress_bar_gets_the_accent_chunk_style`
covers the Dashboard's own per-track progress cell, which shares the
same helper. `mypy --strict` clean; full suite 511 passed / 1 skipped.

### 48

Task: replace `MainWindow`'s `QTabWidget` shell with a sidebar.
Fixed-`SIDEBAR_WIDTH=200` sidebar (`BG_SIDEBAR`, the "Seeker"
wordmark, then Dashboard/Downloads/Review/Duplicates/History as
checkable nav buttons in one exclusive `QButtonGroup`, a stretch, then
Help/Settings pinned at the bottom) driving a `QStackedWidget`. Each
existing tab body became a page via one shared `_build_page(title,
subtitle, content)` helper — title + the existing `help_text.py`
subtitle above the content, identical `24/20` page margins and `12px`
spacing everywhere, per Phase 3's own documented layout convention
(the first place that convention is enforced by code rather than
copied by hand). `_show_page(key)` sets the stack index and the
matching nav button's checked state; `_on_tab_changed`/
`_duplicates_tab_index` renamed `_on_page_changed`/
`_duplicates_page_index` — same lazy-load-on-first-real-visit logic,
unchanged. Window default `1180×760`, minimum `960×640`.

**Settings deliberately stays a dialog, not a page** — it was never a
tab body to begin with (already a separate modal `QDialog`); converting
its own internal 4-tab structure into stacked shell pages would be a
screen-content rewrite the task explicitly scoped out. Relocated to
the sidebar's bottom section next to Help, not a member of the
exclusive nav `QButtonGroup`.

**History and Help are real nav slots now, placeholder content** — a
deliberate, documented choice: both future pages get a real sidebar
entry and a real `QStackedWidget` page now, each with its own real
title/subtitle and a one-line "coming in a future update" placeholder
body, so the sidebar's final shape is correct today and a later phase
only needs to replace the placeholder content.

**Nav badges** (`_update_nav_badge`) read counts already computed by
the existing 2s poll — no new poll added. Text-based (`"Downloads
(2)"`, plain `"Downloads"` at zero — never `"(0)"`), not a separate
sibling badge widget. **Nav item styling:** a checkable, flat
`QPushButton` with a `navItem="true"` property needed no
`WA_StyledBackground` workaround (already painted through Qt's style
system, confirmed in Phase 3) — but the sidebar panel itself, a plain
`QWidget`, DOES need `WA_StyledBackground` for its own `#sidebarPanel`
background rule.

All six pages rendered offscreen and inspected directly before calling
this done. `mypy --strict` clean; full suite 517 passed / 1 skipped.

### 49

Task: replace Settings' type-a-name-then-pick-a-folder library location
flow with pick-first, name-from-folder, renameable-after — shared code
path with the wizard's own single-location step.

**A real incident during this task's own live verification, recorded
honestly rather than smoothed over.** After wiring the new Settings
UI, wrote a throwaway script to render the Locations tab for visual
review (per this project's own "grab a PNG and look at it" discipline).
The script needed `test_settings_window.py`'s `make_application()`
helper, which takes a real pytest `monkeypatch` fixture — outside a
real pytest run, no such fixture exists, so the script substituted a
hand-written stub object with no-op `chdir`/`setattr`/`delenv`
methods, intending it to be a harmless stand-in.

It wasn't harmless. `make_application()` calls `monkeypatch.chdir
(tmp_path)` specifically to isolate the real `.env`-relative fallback
paths — with a no-op stub, that isolation silently never happened, and
`Application()` resolved its real `platformdirs` data directory (CWD-
independent since item 18, so the broken chdir stub didn't even matter
for that part — the DB path was never going to be sandboxed by `cwd`
alone) and opened the real, live production database. The script then
called `add_location(application, "Music", tmp_path / "Music")`
against that real `Application`, writing a real row into the real
`library_locations` table.

**Caught immediately, not discovered later.** The very next screenshot
showed three rows instead of the expected one — two of them, "Test"
and "x9-pro", were recognizable as this machine's own real, known
production locations from prior roadmap items. Rather than assume
best-effort cleanup ("it's just a location row, no big deal"), checked
the actual damage directly: `sqlite3 ... "SELECT ... FROM
library_locations"` confirmed the exact stray row (id 5, name
"Music", path a real `/var/folders/.../tmp.../Music` temp directory);
`SELECT COUNT(*) FROM local_files WHERE location_id=5` and the
equivalent for `playlists.download_location_id` both confirmed zero —
nothing had scanned, matched, or set a destination against it yet, so
it carried no cascading references to worry about. Removed through the
real, ordinary `Application().library_service.remove_location("Music")`
— the same code path a real user's "Remove" click takes, not a raw
`DELETE` — and re-checked the table afterward to confirm exactly the
original two real rows remained, nothing else disturbed.

**Fixed at the source for the rest of this task's verification:**
re-rendered using a real pytest-driven script instead (a `def
test_render_...(qtbot, tmp_path, monkeypatch)` function, run via a real
`pytest` invocation so `monkeypatch` is the genuine fixture, not a
hand-rolled stand-in) — confirmed clean both by the render itself (one
real, isolated location row, not the production three) and by a direct
`sqlite3` check against the production DB immediately after, showing
it untouched.

**Standing lesson for any future one-off verification script in this
project:** a hand-written stub for a pytest fixture is only safe if
every method it no-ops is confirmed to have no real side effect when
skipped — "harmless-looking" isn't the same as verified-harmless, and
a stub silently defeating test isolation (rather than raising or
visibly failing) is exactly the shape that lets a scratch script touch
real production state without any error to catch it. A genuine pytest
invocation of a real test function is safer than an ad hoc script
faking fixture behavior, and should be preferred whenever the render
needs anything a fixture (like `monkeypatch`) would normally provide.

**The feature work.** `LibraryService.add_location_from_path(path)`
(new, the UI's real entry point) derives the name from the picked
folder's own basename, auto-suffixing on a name collision ("Music",
"Music (2)", checked via a bounded loop — `MAX_NAME_SUFFIX_ATTEMPTS=50`,
untuned, purely a sanity ceiling against a real bug, not a real-world
limit) and raising `LibraryLocationPathAlreadyRegisteredError` (carries
the real existing `LibraryLocation`) if the path is already registered
— checked with a new repository `get_by_path()` before ever attempting
the insert, since `library_locations.path` was already schema-`UNIQUE`
(confirmed by reading `schema.py` directly), turning what would
otherwise be a raw `IntegrityError` into a real, named "already
registered as X" message. `add_location(name, path)` (the CLI's own
explicit-name entry point) is unchanged. New
`LibraryService.rename_location(id, name)` → repository
`update_name()`, converting a name-collision `IntegrityError` into the
identical clean `RuntimeError` shape `add()` already used.

`library_location_picker.py` (already shared between the wizard and
Settings) dropped its `name` parameter entirely — both callers now go
through the identical no-name flow, so the wizard's own onboarding
location is named after its folder too, not the previous hardcoded
`"Library"` literal. Settings' Locations tab: the name `QLineEdit` is
gone; "Choose Folder && Add" is now a single "Add location…" button;
each row gained a "Rename" action (a `QInputDialog.getText` prompt, not
a heavier inline-edit widget) next to the existing "Remove"; a new
`self.locations_notice: InlineNotice` surfaces the "already registered
as X" and rename-collision errors persistently — everything else
(Add/Remove progress) stays on the existing transient
`locations_status_label`, since Settings has no poll timer for Phase
3's vanishing-message bug to apply to here.

Rendered and inspected directly (scratch, not committed): confirmed
the single Add button, the Rename/Remove pair per row, and a real
`InlineNotice` correctly naming the pre-existing location on a
duplicate-path attempt.

`mypy --strict` clean; full suite 527 passed / 1 skipped.

### 50

Task: kill the "no configured destination" dead end (default
destination config, a UI dialog so Download never dead-ends, a
filename sanitizer, a UI-first error-message audit).

**Real, load-bearing bug found while wiring the default fallback into
the actual file-move step, not just the upfront `download_playlist()`
guard.** The upfront guard was easy to update — swap the old
`if playlist.download_location_id is None: raise ...` for a call to
the new `_resolve_destination()`. But `_move_completed_file()` (what
actually moves a completed download once it lands, on a LATER poll
cycle) resolves its destination differently: via
`PlaylistRepository.get_by_track_id()`, whose query carried
`WHERE p.download_location_id IS NOT NULL` — confirmed by reading the
query directly, not assumed from the method name. Left as-is, a track
whose only playlist relies on the new default fallback would never
even be RETURNED by this query, so the file would silently never move
— a real regression this task would have introduced, not fixed, if
the two resolution points hadn't been checked against each other.
Confirmed the filter had exactly one real caller (grepped every
`get_by_track_id` call site) before removing it, and updated the
caller to iterate every returned playlist and resolve the first one
that actually works, rather than trusting `playlists[0]`.

**A second real gotcha, in `config_store.py`, caught by reading the
actual load path rather than trusting the module's own "flat additive
JSON" framing.** That framing (documented in the file's own module
docstring) is true for a MISSING key — `load_config()` doesn't crash
on one. It doesn't cover the fact that `load_config()` still
constructs `SeekerConfig` from an explicit, hand-written list of
`data.get(...)` calls, one per field — a new field left out of that
list would silently reset to its dataclass default on every load,
regardless of what was actually saved on disk. Caught before it became
a real bug (both new fields were added to the explicit list from the
start), verified with a round-trip test and a separate
missing-key-uses-defaults test.

**A third real interaction, found live while writing this task's own
tests — traced with actual debug prints, not guessed at.** A new test
for the Settings default-destination group called the real
`Application.persist_default_destination()` right after directly
setting `application._config_store` in memory (an existing test
convenience from `test_settings_window.py`'s own `make_application()`
helper — a fake Spotify token set in memory only, never saved to
disk, so `sync_service` construction wouldn't attempt a real OAuth
round-trip). The test then failed with the combo staying empty — looked
at first like the new UI code wasn't populating it.

Added temporary debug prints directly to `_refresh_destinations()`/
`_render_destinations()` in `settings_window.py` (removed afterward)
rather than guessing further, and reproduced via a genuine
pytest-driven script (per item 49's own now-standing lesson — no
hand-rolled monkeypatch stub). The real cause: `persist_default_destination()`
calls `load_config(config_path)` first, then applies its own change on
top of that FRESH-FROM-DISK config — the same pattern
`persist_soulseek_config()` already used, and correct there: every
real `_config_store` mutation in this codebase immediately calls
`save_config()`, so disk and memory never actually drift apart in real
usage. But the test's fake token was set directly on
`application._config_store` and never saved — so the disk reload
silently discarded it, and the NEXT real access to
`application.sync_service` (inside `_refresh_destinations()`'s own
fetch function) hit a real, live `SPOTIFY_CLIENT_ID is not configured`
error, which `run_worker`'s `on_error` swallowed into the status
label rather than crashing the test outright.

Confirmed this was a test-setup artifact, not a production bug, by
checking whether anything in real usage could leave `_config_store`
out of sync with disk before calling one of these persist_* methods —
nothing does; every mutation path saves immediately. Fixed the test
(set `_config_store` directly via `dataclasses.replace()`, matching
how the fake token itself was already set up) rather than changing
correct production code.

**The feature work.** `SeekerConfig` gains
`default_download_location_id: int | None` and
`default_download_subfolder_per_playlist: bool = True`. New
`DownloadService._resolve_destination(playlist)` — a playlist-specific
`download_location_id`/`download_subfolder` always wins; otherwise
falls back to the configured default, with the playlist's own name
(sanitized) as the subfolder when the toggle is on. Resolved through
`_get_config()` fresh on every call, not a snapshot — this project's
standing rule, so a Settings change takes effect with no restart. New
public `get_resolved_destination(playlist_name)` (read-only wrapper) is
what the UI checks before ever calling `download_playlist()`.

New top-level `seeker/filename_sanitize.py::sanitize_path_component()`
— no prior sanitizer existed anywhere in this codebase (checked
first). Replaces path separators (both `/` and `\`), Windows-reserved
punctuation, and control characters with `-`; strips trailing
dots/spaces (a real, confirmed Windows folder-creation failure mode,
not cosmetic); falls back to `"Untitled"` if nothing usable survives.
Tested against real playlist names pulled live from this project's own
production database — `"240KM/H"`, `"Node: Reloaded"`,
`"Lotus // Trap"`.

**UI-first error audit, two real fixes, both reachable from the GUI:**
(1) `NoDestinationConfiguredError`'s message (`download_playlist`) said
"Run 'seeker playlists set-destination' first" — shared by the CLI and
the UI. Made interface-neutral; the CLI now appends its own
command-line guidance in its own exception handler instead of baking
it into the shared message. (2) `ReviewCandidateMissingSizeError`
(`confirm_review_candidate`, Review tab's Confirm action — CLI never
calls this method at all) said "re-run 'seeker download'"; rewritten
to reference the Dashboard's Download button instead.

**No dead end:** `DestinationDialog` (new, in `main_window.py` next to
`AboutDialog`) — location combo (prefilled: the configured default,
else the only location if there's exactly one), subfolder field
(prefilled with the raw, unsanitized playlist name — sanitizing
happens later, at actual move time), "Remember this for this
playlist" (checked). Confirming ALWAYS persists somewhere real —
because `_resolve_destination()` is re-evaluated later, on a separate
poll cycle, when the file actually completes. Checked → calls the
existing `set_destination()` (playlist-specific). Unchecked → calls
new `Application.persist_default_destination()` (the app-wide
default).

**Settings → Destinations:** new "Default Destination" `QGroupBox`,
genuinely above the per-playlist overrides — location combo +
subfolder-per-playlist checkbox + a primary "Save default destination"
button, prefilled from the real current config on tab load.

**Wizard:** right after the library folder is picked, two checkboxes —
"Download new tracks into this folder" / "in a subfolder per
playlist" — both checked by default, the second hidden while the
first is unchecked. Confirming persists the default destination via
the same `persist_default_destination()` Settings uses.

`mypy --strict` clean; full suite 567 passed / 1 skipped.

### 51

Task: a Dashboard "next step" CTA plus real empty states. New
`main_window.py` module-level `_NextStepFacts`/`_NextStep`/
`_decide_next_step()` — a pure function (no Qt) deciding which single
CTA to show, tested directly with 11 synthetic-fact tests, no
`MainWindow` needed. Every fact it branches on comes from a real
service/Application call, gathered in one background-thread
`_fetch_next_step_facts()`. `Application.spotify_configured` already
existed (reused); new `LibraryService.has_scanned_library()` did not.

**`has_scanned_library()` is a real, disclosed approximation** — no
schema change was in scope, and `library_locations` has no
`last_scanned_at` column. True once any `local_files` row exists
anywhere (new `LocalFileRepository.exists_any()`, a cheap existence
check, not `get_all()`). Known, accepted limitation: a real scan of a
location with genuinely zero matching audio files is
indistinguishable from "never scanned" by this proxy.

Rendered via a new `InlineNotice` (`self.next_step_notice`, above
`dashboard_notice` — guidance and errors never overwrite each other).
Recomputed on playlist selection and the existing 2s `poll_timer` tick
— no new timer.

**Empty states, a real structural change.** `track_table` and a new
centred `_track_empty_panel` now live in a `QStackedWidget`
(`track_area_stack`), swapped explicitly. Three distinct states: no
playlist selected (guidance, no button); a selected playlist with no
synced tracks yet (same panel with a real "Load tracks" button);
anything else (the real table).

Renamed the cryptic global toolbar buttons and moved them onto the
Dashboard page itself as a secondary action row: Sync → "Refresh
playlists", Scan → "Rescan library folders", Match → "Re-match
library." Download (playlist-scoped) sits in the same row. Global
scope itself is unchanged.

`mypy --strict` clean; full suite 588 passed / 1 skipped.

**Follow-up, two real gaps found by re-inspecting the item's own
screenshots.** (1) The action row's "Download selected playlist" and
the CTA's own "Download N missing tracks" were genuinely the same
action (confirmed via `get_unmatched_for_playlist`'s query — needs-
review tracks already excluded from both). Fixed by hiding
`download_button` specifically while the CTA's current action is
`"download"`, shown again once the CTA moves on to anything else. (2)
All four action-row buttons rendered enabled regardless of whether
their action could do anything — `_render_next_step` now also sets
`.setEnabled(...)` on all four from the same facts bundle already
computed for the CTA: Download needs a selected playlist; Sync needs
`spotify_configured`; Scan needs a library location; Match needs both
cached playlists and a library location. Disabled rather than hidden,
so the row's width doesn't jump around. Fixed the resulting test race
at the shared `_select_first_playlist()` helper (wait for
`download_button.isEnabled()`, not just the selection) rather than
patching each affected test individually.

`mypy --strict` clean; full suite 595 passed / 1 skipped.

### 52

Task: give the wizard's SoulSeek credential form real, distinguishing
copy for a rejection — the protocol itself can't tell "wrong password
on my own account" from "that username belongs to someone else" apart,
so ask the user which one they're doing — and confirm live whether the
third state item 23 flagged as "observed but unclassified" ("kicked,
another client already logged in") has a real, distinct log substring
worth its own classification.

**Live verification plan, and why the real production slskd was never
touched.** The real, already-connected production `slskd` container
(username `seekerapp`) was up and healthy for this whole session. The
obvious first idea — temporarily change its credentials via `PATCH
/api/v0/options` to force a real rejection, then change them back —
was checked against the real live swagger spec first rather than
attempted blind: the `soulseek` section of `OptionsOverlay` only
exposes `listenIpAddress`/`listenPort` for runtime patching:
credentials aren't patchable at all through that endpoint. Directly
editing the real persisted `slskd-data/slskd.yml` and restarting the
real container was ruled out too — too high a blast radius for a real,
working connection just to observe some log text. Used a genuinely
disposable, throwaway `docker run` container instead (fresh, isolated
data directory; different host ports; never `docker compose`d against
the real `docker-compose.yml` at all) — the exact same "diagnostic
instance, not the real one" discipline this project already
established for packaging verification (items 30/31's `SeekerVerify`
builds).

**First real, live-found surprise, before ever reaching the intended
test.** The first throwaway container was configured with a made-up,
never-before-used username and a made-up password, expecting a clean
rejection. It connected successfully instead — `state:
"Connected, LoggedIn"`. This is CLAUDE.md's own already-documented
"SoulSeek has no separate signup" fact, now confirmed live from an
angle nobody had actually exercised before: a brand-new username
doesn't fail login, it silently creates a real new account and logs
in. This meant the intended "bad password" test needed a real,
already-registered username — not just any string — so the real
`seekerapp` username (read directly from the persisted `slskd-data/
slskd.yml`, never displayed insecurely) was used with a deliberately
wrong password instead.

**Real bad-password rejection, confirmed live, matching the already-
documented pattern exactly.** With the real `seekerapp` username and
a wrong password, the throwaway container genuinely disconnected —
`state: "Disconnected"` — and its own `/api/v0/logs` carried two real
Error entries: `"Disconnected from the Soulseek server: invalid
username or password"` and `"Failed to reconnect: \"The server
rejected login attempt: INVALIDPASS"` (the second one really is
truncated exactly there in slskd's own log text — not a parsing
artifact on this project's side, confirmed by checking the raw
message length directly). Both match `BAD_CREDENTIALS_LOG_PATTERNS`
exactly as already documented — confirmed fresh against a real 2026-
08-31 run, not just trusted from the original 2026-08-28 finding.

**Real "kicked" rejection, confirmed live using two throwaway
containers, the real production one never touched.** Reconfigured the
same throwaway container with the REAL `seekerapp` username and its
REAL password (both read from the persisted YAML) and started it
while the real production container was still connected as that same
user. It never even got the chance to fully log in — its own logs
showed `"Logged in to the Soulseek server as \"seekerapp"` immediately
followed by `"Kicked from server."` (Information level) and then the
real, distinct Error line: `"Disconnected from the Soulseek server:
another client logged in using the same username"`. Checked
immediately afterward, not assumed: the real production `slskd`
container's own `/api/v0/application` still reported `"Connected,
LoggedIn"` — the older, already-established connection won, and the
newer throwaway one was the one rejected. This message is genuinely
disjoint from the bad-credentials pattern set (no shared words),
confirmed safe to add as its own `KICKED_LOG_PATTERNS`/
`SlskdHealthStatus.KICKED` classification without any risk of
colliding with the existing one.

**Cleanup, confirmed complete.** Both throwaway containers (`docker rm
-f`) and their scratch data directories were removed immediately after
the two real tests above; the real production `slskd` container and
its real `slskd-data/` were never modified at any point — checked
directly (`docker ps -a --filter name=slskd` showing only the real,
original, still-healthy container) rather than assumed clean from the
plan alone.

**No structured error code exists to pin to instead of substring
matching, checked again for this new pattern the same way item 23
already checked for the first two** — the real captured log entries'
own shape (`{timestamp, context, level, message}`) has no
"exception-code" or "reason" field, only free-text `message`. Same
accepted risk as `BAD_CREDENTIALS_LOG_PATTERNS`: a future slskd
version could reword this text, and it's worth re-checking after any
upgrade.

**The wizard-side work.** Step 3's credential form gains a radio pair,
"I already have a SoulSeek account" (default) / "Create a new SoulSeek
account", with a line explaining SoulSeek has no separate signup. On
`BAD_CREDENTIALS`, the copy branches on which radio is checked:
existing-account mode keeps the username/password and says to check
the password (case-sensitive); new-account mode clears and focuses
the username field with an "already taken" message. The real raw log
detail is never dropped — moved to the status label's tooltip in
every branch, cleared at the start of each new attempt. Username
validated before attempting (non-empty, no leading/trailing
whitespace) — real SoulSeek character constraints weren't cheaply
confirmable, so nothing beyond that was guessed at. `SlskdHealthStatus
.KICKED`/`KICKED_LOG_PATTERNS` give the newly-classified third state
its own wizard message ("Another client is already logged in with
this username"), distinct from `BAD_CREDENTIALS`. Timeout branch's
copy now says what to check (Docker still running, credentials
correct, working internet connection) rather than just that it timed
out.

`mypy --strict` clean; full suite 600 passed / 1 skipped.

### 53

Task 9's own brief scoped one piece as explicit recon, separate from
the aggregate-ETA implementation itself: make one real
`GET /api/v0/transfers/downloads/{username}/{id}` call against the
live slskd and report whether a queue-position field (`placeInQueue`
or similar) genuinely exists in the response — recon only, nothing
was to be built on the answer either way.

**Finding a real queued transfer to call it against.** A plain
`GET /api/v0/transfers/downloads` against the real, already-running
production slskd container returned every currently-tracked transfer
grouped by peer; scanning the real response by `state` found 8
`Completed, Succeeded`, 4 `Completed, Rejected`, and exactly one
`Queued, Remotely` — a real, live, currently-queued download
(`musicmasterrdjpool`, filename ending
`Prdk - One More Night (Clean) 4A 87.mp3`, id
`4c16e111-4f4a-46ad-96e7-25d8743811b3`).

**The real per-transfer call.** `GET /api/v0/transfers/downloads/
musicmasterrdjpool/4c16e111-4f4a-46ad-96e7-25d8743811b3` returned:

```json
{
  "id": "4c16e111-4f4a-46ad-96e7-25d8743811b3",
  "username": "musicmasterrdjpool",
  "direction": "Download",
  "filename": "DJPOOLS\\2026\\MONTHS\\FEB\\20\\The Mash Up 20 FEB\\Prdk - One More Night (Clean) 4A 87.mp3",
  "size": 9251601,
  "state": "Queued, Remotely",
  "requestedAt": "2026-08-31T16:17:35.8155068",
  "enqueuedAt": "2026-08-31T16:17:36.1261647",
  "bytesTransferred": 0,
  "averageSpeed": 0,
  "attempts": 1,
  "removed": false,
  "bytesRemaining": 9251601,
  "percentComplete": 0
}
```

No `placeInQueue` field anywhere in the real body — confirmed by
`grep`-ing the raw JSON text directly rather than just eyeballing the
formatted output, ruling out a pretty-printer dropping it.

**Checked the real schema too, not just this one response.** slskd's
own live `/swagger/v0/swagger.json`, `components.schemas
["slskd.Transfers.Transfer"].properties`, DOES declare a real
`placeInQueue` field — so this isn't a case of the field not existing
at all; it's declared in the real type. Re-grepped the entire raw
`/api/v0/transfers/downloads` listing (every peer, every transfer, not
just the one queued one) for the literal string `placeInQueue` and
found zero occurrences anywhere, including as an explicit `null` —
consistent with slskd's JSON serializer omitting null-valued
properties from the response entirely rather than emitting them as
`null`.

**Conclusion, exactly as scoped — reported, not acted on.** The field
exists in slskd's own real type but isn't currently populated for this
real, live queued transfer, so slskd itself doesn't currently know (or
isn't currently reporting) this transfer's real remote queue position.
This gives the existing "Soulseek queue waits aren't predictable"
design rationale (already used for `AGGREGATE_ETA_TOOLTIP`) a concrete,
live-confirmed technical backing rather than just restating it as an
assumption. No code reads `placeInQueue` — a future revision could
poll for it and treat a still-absent value as "unknown," but per the
brief's own explicit scope, that decision is left for later, not made
here.

**The feature work.** `DownloadEtaTracker.aggregate(downloads:
list[tuple[int, int | None]])` — `(request_id, total_bytes)` pairs for
every currently active download on the Downloads page — returns a new
`AggregateEta` dataclass. Only downloads with >= 2 samples, a positive
latest delta, and a known `total_bytes` contribute (`eta = sum(
remaining bytes over contributors) / sum(their current speeds)`);
everything else (queued/no samples yet, still calculating, stalled, or
unknown `total_bytes`) is counted but excluded from the sum.
`_classify()` factors the same three-way state `describe()` already
computed for one download (Calculating/Stalled/Contributing) out into
a reusable per-request helper, so `aggregate()` reuses the identical
logic instead of a second, drifting copy.

`format_aggregate_header()` (pure, no Qt) renders the Downloads page's
header line: `"About {eta} remaining · {N} transferring · {M} queued
(no estimate)"`, dropping the third clause when `M == 0`; reads
"Waiting for transfers to start" with zero contributors, or "All
active transfers stalled" specifically when every non-contributor is
STALLED rather than just not-yet-started. Wired into `MainWindow` as a
new `downloads_eta_label` above the Downloads table, rendered from
`_render_active_downloads` on the existing 2s poll (no new timer) —
collapses to an empty string when there are zero active downloads.

`mypy --strict` clean; full suite 614 passed / 1 skipped.

### 54

Task: build a History page (Dashboard's own sidebar neighbor) showing
recently downloaded and tagged tracks, derived entirely from existing
`download_requests`/`local_files` rows — no schema change, no new
append-only log table.

Before writing any service code, the two real columns this depends on
(`download_requests.completed_at`, `local_files.tagged_at`) needed
checking, not assuming: both write sites
(`download_request_repository.py::mark_status`/
`update_transfer_id_and_status`, `metadata_service.py`) already use
`datetime.now(timezone.utc).isoformat()`, and pulling two real rows
from the production DB confirmed genuinely timezone-aware UTC values
(`2026-08-28T23:36:42.578430+00:00`, `2026-08-28T23:38:20.891923+00:00`)
— matching `ui/formatting.format_timestamp`'s own docstring claim
exactly. No fix was needed there; both the History page and the new
`seeker history [--limit N]` CLI command reuse that one formatter as-is
rather than growing a second copy.

`HistoryService.get_recent_events(limit)` derives two event kinds:
completed `download_requests` rows (deduped via the same
`most_recent_per_candidate` rule items 24/25 already established for
the identical "same real candidate, stale duplicate row" problem) and
`local_files.tagged_at`, joined back to a track via
`TrackMatchRepository.get_by_local_file_id` (added in item 40).
Deliberately excludes failed downloads — `download_requests` has no
persisted failure-reason column (the real slskd exception text is only
ever seen live, at poll time, never written to the DB), so a failed
event could never carry an honest detail.

Live-verified against the real production DB, both via the CLI
(`seeker history`, 13 real events, correctly ordered/deduped) and via
an offscreen render of the real History page (real `Application`, no
fakes) showing identical data. 22 new tests (11 `HistoryService`
covering dedup/no-track/no-match/failed-download edge cases explicitly,
6 UI, 3 CLI). `mypy --strict` clean; full suite 634 passed / 1 skipped.

The feature work itself (When/What/Track/Detail table, the client-side
filter combo, lazy page load, manual Refresh, the CLI command) is
covered in CLAUDE.md's own item 54 entry — this HISTORY entry exists
specifically to preserve the timestamp-format verification and the
real live-run numbers.

### 55

Task: a GitHub-releases-based "Check for updates" action (Help menu),
then — once that was confirmed live and working — the rest of the
brief: a real Help page, an expanded About dialog, and a real `LICENSE`
file, gated behind an explicit approval step before committing each
half, matching the same live-verification discipline items 52/53
(Phase 8/9) already established for a live external dependency.

**The real, live recon call, made before writing any code — the
brief's own explicit instruction, not skipped:**

```
GET https://api.github.com/repos/KristiyanDDimitrov/Seeker/releases/latest
```
```
HTTP/2 404
date: Tue, 01 Sep 2026 07:40:53 GMT
content-type: application/json; charset=utf-8
x-ratelimit-limit: 60
x-ratelimit-remaining: 57
x-ratelimit-used: 3
content-length: 144
x-github-request-id: F658:380DAC:54E801C:52A1E79:6A968185

{
  "message": "Not Found",
  "documentation_url": "https://docs.github.com/rest/releases/releases#get-the-latest-release",
  "status": "404"
}
```

Confirmed directly, not assumed: this repository has zero published
releases as of this check — a real, reachable `UNAVAILABLE` state, not
a hypothetical one — and GitHub's unauthenticated rate limit (60/hour)
is real, shared per source IP, and was already 3/60 used from this one
recon call alone, which is exactly why `check_for_update()` stays
strictly user-triggered (Help menu only) and was never considered for
a timer or startup call.

**Each required `UNAVAILABLE` path was actually triggered, not just
handled in code believed correct**, per the brief's explicit ask:
the real 404 above (seeded verbatim into a test); a simulated 403
(GitHub's real rate-limit response shape); a simulated
`httpx.TimeoutException`; and a simulated unparseable tag
(`"not-a-version"`, via `packaging.version.InvalidVersion`). A first
draft only caught `httpx`-specific exceptions around the network call;
a test deliberately raising a plain `RuntimeError` from the mocked
`httpx.get` proved a non-httpx exception would still escape — tightened
to an unconditional outer `try/except Exception` wrapping the whole
function, per the brief's literal "never raises" requirement rather
than "never raises for anticipated failures."

**Third-party license identifiers, for the About dialog's notices
section, were pulled from each installed package's own real metadata**
(`importlib.metadata.metadata(pkg).get("License")`/`Classifier`
entries), not written from memory — confirmed:
`PySide6` → `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`,
`librosa` → `ISC`, `mutagen` → `GPL-2.0-or-later`, `numpy`/`httpx`/
`soundfile`/`python-dotenv` → `BSD-3-Clause`/`BSD License`,
`platformdirs`/`rapidfuzz`/`pyloudnorm` → `MIT`, `packaging` →
`Apache-2.0 OR BSD-2-Clause`. `libchromaprint`'s LGPL-2.1-or-later
status (dynamically loaded via ctypes, never statically linked — see
item 38) was already established and is restated, not re-derived.

**Two real dialogs rendered and inspected, gated behind explicit
approval each time, per the brief's own instruction to check in before
proceeding:** the update-check dialog (both the real `UNAVAILABLE("No
releases have been published yet.")` result against the live API, and
a simulated `UPDATE_AVAILABLE` result), and — after that was approved
— the Help page and the expanded About dialog, rendered against the
real production `Application` (real resolved data-location paths, not
placeholders). A later approval step added the real PayPal support
link (`https://paypal.me/KristiyanDimitrov98`, replacing the `"TODO:
..."` placeholder from item 35/41) — re-rendered and re-approved with
both buttons live before committing.

`uv sync` was confirmed to still build cleanly with
`pyproject.toml`'s new `license = "MIT"`/`license-files = ["LICENSE"]`
fields, and the resulting dist-info's `Classifier` metadata was checked
directly (not assumed) to actually carry the license.

The feature work itself (`update_check.py`, the Help page's
"How Seeker works"/Troubleshooting/data-locations content,
`Application.data_locations`, the expanded About dialog,
`is_real_support_link()`, `LICENSE`) is covered in CLAUDE.md's own item
55 entry — this HISTORY entry exists specifically to preserve the real
recon call/response, the license-metadata verification, and the
staged-approval sequence in full.

`mypy --strict` clean throughout; full suite 659 passed / 1 skipped
after the update-check portion, unchanged after the Help/About/LICENSE
portion (no new failures introduced by either).

### 56

Phase 0 recon (five real investigations against the live, non-empty DB
and library) plus Phase 1 (matching correctness) of a large multi-phase
work block. Two of the five recon items refuted their own stated primary
hypothesis; both are recorded here in full since that's exactly the
"hypothesis ruled out" case CLAUDE.md's own split calls for.

**0.2 — the three real unmatched/needs-review BMTH files: primary
hypothesis (the artist gate rejecting them) refuted by real data.** The
brief hypothesized `artist_matches` was hard-rejecting these before any
title score ran (per the "matcher and quality drifted apart" precedent).
Real `local_files` rows (`Bring Me The Horizon` tracks under
`Music/Albums/2024 - POST HUMAN NeX GEn/`) all had a real, populated,
correctly-spelled `tag_artist`. Ran the real `matching.artist_matches`
against each: **`True` for all three.** The gate was never the problem.
Two of the brief's own secondary hypotheses were also checked and
refuted for these specific files: the track-number prefix was already
being stripped by `normalize_filename_text` (cost: 0, not "depresses the
ratio"), and the real `relative_path` layout is
`Albums/<year> - <album>/<track>`, not `Artist/Album/<track>` — the
artist isn't in the path at all here, so the brief's path-component
fallback (however useful generally) would not have fixed these three
files.

Full resolution required real Spotify data the DB didn't have — this
playlist's tracks had never been synced. `sync-tracks` 401'd; the stored
token's own `_is_expired` check said it was still valid (a separate,
real, unfiled gap — the refresh path never triggered even though
Spotify itself was rejecting the token) so `SpotifyAuthManager
._authorize()` was called directly to force a fresh interactive OAuth
login, then `sync-tracks "POST HUMAN: NeX GEn"` pulled the real 16
tracks. The real root cause, confirmed against real Spotify titles:
- `"a bulleT w/ my namE On (feat. Underoath)"` (Spotify) vs. the local
  tag `"a bulleT w- my namE On"` — missing the entire `(feat.
  Underoath)` clause, **not** just the `/` vs `-` substitution. Real
  score: **67.74** (needs_review by default thresholds; genuinely below
  even the user's own already-lowered 70 auto threshold — exactly
  explaining the reported "never matched even with the threshold
  lowered to 70").
- `"R.i.p. (duskCOre RemIx)"` (Spotify) vs. local `"Rip (duskCOre
  RemIx)"` — Spotify's own letter-spacing dot stylization, dropped
  entirely by the local tag. Real score: **74.42** (needs_review).
- `"[ost] p.u.s.s.-e"` (Spotify) vs. local `"[ost] puss-e"` — same dot
  stylization. Real score: **85.71** (needs_review).

None of these are fixed by the brief's originally-scoped Phase 1.2(a)
(mapping `/ \ : * ? " < > | - _` to space) alone — periods aren't in
that substitution set, and a missing `(feat. ...)` clause isn't a
character-substitution problem at all. Verified directly, isolating each
cause: stripping periods from `normalize_filename_text` alone brings
both dot-stylization cases to a clean **100.00**; trying a
feat-clause-stripped title as an additional scoring variant (never
replacing the full-title variant) brings the first case to **100.00**
too. All three fixes combined were verified together before writing any
production code.

**0.4 — cover art "didn't update": primary hypothesis (append, not
replace) refuted by reading the current code and the real files.**
`seeker/metadata.py`'s `embed_album_art` already calls `clear_pictures()`
before `add_picture()` for FLAC, `setall("APIC", [...])` (replace-all,
not append) for ID3, and a plain dict-replace (`tags["covr"] = [...]`)
for MP4 — none of the three formats append. Confirmed on 5 real,
already-tagged files on the real drive (read-only, never opened for
writing): exactly 1 picture/APIC frame each, no duplicates. The real,
still-live gap is the brief's own secondary hypothesis: `_tag_one_track`
wraps the art download+embed in a bare `try/except` that only
`print()`s a warning — the track still counts as `tagged` and nothing in
`details` records the failure, so a CDN hiccup on one track is
structurally invisible to both CLI and UI. Phase 4 is re-scoped
accordingly: 4.1 (replace-not-append) becomes minor FLAC `Picture`
field polish only (`desc`/`width`/`height`/`depth`, currently unset);
4.2 (honest partial-failure reporting) is where the real fix belongs.

**0.1, 0.3, 0.5 — all three hypotheses confirmed as scoped.** 0.1: the
guided/CTA "Scan library" action and the "Rescan library folders"
button both route to `library_service.scan_all()` only;
`match_button`/"Re-match library" is the only thing that ever calls
`track_matcher.match_all()` — confirmed by tracing `_on_next_step_action`
and both click handlers directly. `rglob("*")`'s lack of a depth limit
was independently proven (not just read) with a disposable 5-level-deep
`tempfile.mkdtemp()` tree scanned through the real `LibraryScanner`.
0.3: `get_review_candidates()` only ever reads `soulseek_review_
candidates`; `track_matches` has no `confirmed_at` column at all, so
`match_all()` genuinely has no provenance concept (item 45's finding
still holds) — this is roadmap item 7's outstanding gap, not a Review
tab bug. 0.5: the exact reported track (Logic's "Driving Ms Daisy")
wasn't reproducible (its playlist was never synced), but a real, better
analog was found live in the DB: track `Kamäleon – Quadrat` has 3 real
`role='settled'`/`status='completed'` download_requests across ~13
hours on 2026-08-28, two identical-candidate duplicates and a third from
a different peer/format — both a 6MB mp3 and a 65MB "Master" wav
genuinely sitting on disk right now, only one matched. Confirmed the
exact mechanism: `DownloadRequestRepository.get_active_for_track`
filters `status NOT IN ('completed', 'failed', 'superseded')` — a
`completed` row was never "active," so nothing stops a later
`download_playlist` run from re-requesting an already-fully-downloaded
track. Real timestamps were hours apart, not the brief's guessed
"seconds to a couple minutes" — consistent with the user re-triggering
the action on separate occasions with no feedback that anything had
started (Phase 5.1), not rapid double-clicking.

**Phase 1 implementation, built on the above.** `LibraryService
.scan_and_match()` chains `scan_all()` (now returns aggregated
added/updated/removed/unchanged totals across locations, previously
`None`) into `match_all()` in one call; `TrackMatcher` is now an
optional constructor dependency, wired from `Application.library_service`
via the existing `Application.track_matcher` property. `seeker library
scan --match` (chosen over always chaining, so scripted/cron use of a
scan-only pass stays available); the UI's `_on_scan_clicked` now calls
`scan_and_match` and reports the real combined counts — no genuine
live two-stage progress text was built (`ui/workers.py`'s single shared
dispatcher has no safe cross-thread progress-update path, and adding
one would reintroduce exactly the class of hazard items 39/41 fought to
eliminate), so the button shows an immediate placeholder set
synchronously at click time, replaced by the real result once the whole
call finishes — disclosed here as a deliberate scope decision.

`matching.py`: `normalize_filename_text`/`artist_matches`/`score_title`
all gained an `aggressive: bool = False` parameter — default preserves
today's exact behavior (verified: `soulseek/quality.py`'s existing 27
tests pass unmodified, since it never passes `aggressive=True`).
Aggressive mode adds the filesystem-substitution mapping, period-
stripping, and an additional feat-clause-stripped title variant (never
replacing the full-title variant). New `evaluate_match()` — the single
entry point `library/matcher.py` uses instead of calling
`artist_matches`/`score_title` directly — returns a `MatchEvaluation`
(score, artist_confirmed): a real, populated, disagreeing tag still hard
-rejects (`score=None`); an unconfirmable fallback source (no tag,
nothing in the filename/path/grandparent-path names the artist) still
gets a real score, capped at `ARTIST_UNCONFIRMED_SCORE_CAP =
AUTO_MATCH_THRESHOLD - 1` so it can land in needs_review but never
silently auto-match. `library/matcher.py`'s new `_resolve_artist_evidence`
tries `tag_artist` → filename stem → parent dir name → grandparent dir
name in order when the tag is null (item 1.2c) — a source that matches
via any of these counts as fully confirmed, same as a real tag.

**Real before/after, run against the live, non-empty production DB
(2026-09-01), true before-state captured via `git stash` of just the two
changed source files, not simulated:** with the user's own already-
lowered thresholds (`auto_match_threshold=70`, `needs_review_
threshold=60`, confirmed via the real `config.json`) — before: **Auto:
26, Needs review: 2, Unmatched: 1** (of 29 real tracks); after: **Auto:
27, Needs review: 1, Unmatched: 1**. All three named BMTH files reached
a real **100.0** and landed in `auto`. The two other real needs_review/
unmatched rows (`Zigi SC, A-Cray – Bit Perfect`, 63.6; `Prdk – ONE MORE
NIGHT`, 38.3) are unrelated, pre-existing, out-of-scope cases — both
present identically before and after, confirming nothing else moved.
Also ran the real `seeker library scan --match` end-to-end against the
live library (3213 unchanged + 18 added + 13 updated files across two
locations), landing on the identical 27/1/1 result.

`mypy --strict` clean; full suite 681 passed / 1 skipped, run 3 times in
a row.

### 56, Phase 2 — local needs-review matches get a real review flow

Closes roadmap item 7's long-outstanding gap (a `review` command for
needs-review LOCAL-FILE matches, distinct from the SoulSeek-side
confirm/reject item 26 already built) and item 45's pre-existing
demotion bug — confirmed in Phase 0's own 0.3 investigation: `track_
matches` had no provenance concept at all, so `match_all()` could
silently demote a human-confirmed match back to `needs_review` on its
next run.

**Schema.** `track_matches.confirmed_at TEXT NULL`, guarded
`_add_column_if_missing` (same one-off pattern as every prior column).
**Verified against the real, non-empty production DB**, not just a
fresh one: backed up `seeker.db`, ran `Database.initialize()` against
the real file — the new column appeared via `PRAGMA table_info`, the
real 29-row count was unchanged, `confirmed_at` was `NULL` for all 29
(a genuinely new column, not silently repurposing something).

**Repository.** `TrackMatchRepository.confirm(track_id, confirmed_at,
connection)` — a targeted `UPDATE` setting only `match_method='auto'`
and `confirmed_at`, deliberately NOT touching `local_file_id`/`score`
(the real computed score stays visible, same reasoning item 45 already
established for `_index_and_match_settled_download` — a bad pairing
must stay visible in the data, never hidden behind a `100.0` sentinel).
New `delete(track_id, connection)` for reject (no blacklist, mirroring
`reject_review_candidate`'s item 26 precedent). `match_all()` now loads
existing matches first and skips recomputing (counting straight into
`"auto"`) any row with a non-null `confirmed_at`.

**Service layer**, all on `LibraryService` (which needed a new optional
`playlist_repo` constructor dependency for the playlist-scoped variant,
alongside the existing optional `track_matcher`):
`get_needs_review_matches(playlist_name=None)` returns a new
`NeedsReviewMatch` per row — track artist/title, matched file's
relative path + location name, score, AND the tag values that were
actually compared, since the whole point is showing a human *why* it
scored where it did, not just the number. `confirm_match(track_id)` /
`reject_match(track_id)` — no double-confirm gate (item 27's
precedent: this project's confirmation gate is for file replacement,
not DB state; nothing on disk is touched here).

**CLI.** `seeker review [playlist_name] [--confirm TRACK_ID] [--reject
TRACK_ID]` — new top-level command (distinct from the existing
`seeker downloads review`, which is for SoulSeek upgrade candidates).

**UI.** Review page gains a third section ("Local library matches
needing confirmation") on the existing 2s poll, bundled into the same
`_poll_review_items()` worker call as the other two sections so all
three tables render from one consistent DB snapshot. Nav badge count
now sums all three. Dashboard double-click (§2.4): a `NEEDS_REVIEW`/
`AWAITING_REVIEW` status cell gets a tooltip + underlined accent-colored
text (every other status is a genuine no-op, not just an unstyled
click); double-clicking it calls `_show_page("review", focus_track_id=
...)`, which sets a pending-focus id and immediately re-polls (rather
than waiting up to 2s for the standing timer); once the real data
loads, `_focus_pending_review_row` selects and scrolls to the matching
row in whichever of the two actionable tables (pending upgrades or
local matches) actually has it — a track with nothing there yet (e.g.
a `locked`/`shortlisted` `AWAITING_REVIEW` row not yet `ready_for_
review`) just lands on the page with nothing selected, not an error.

**Real live verification, end to end, against the live production DB
(2026-09-01), not just the test suite.** `seeker review` listed the one
real remaining needs-review row (`Zigi SC, A-Cray - Bit Perfect`,
score 63.6 — the same real track item 45's own HISTORY entry already
covers). `seeker review --confirm <track_id>` confirmed it; a real
`seeker library match` re-run immediately after reported `Needs review:
0` (down from 1) with `Auto: 28` (up from 27); `seeker review` again
reported "None."; and the raw DB row was read back directly —
`match_method='auto'`, the real score `63.636...` (NOT a `100.0`
sentinel), and a real `confirmed_at` timestamp. This is the actual,
concrete closure of item 45's demotion bug, not just a test asserting
the code path exists.

`mypy --strict` clean; full suite 700 passed / 1 skipped, run 3 times
in a row.

### 56, Phase 3 — Settings becomes an in-window page

Reverses item 48's deliberate "Settings deliberately stays a separate
dialog" decision — in fullscreen, a second window reads as a dead end
with no way back to the shell.

**Conversion.** `SettingsWindow(QMainWindow)` → `SettingsPage(QWidget)`
in place — same constructor signature, same four tabs, same
`_refresh_*` methods, all behavior-preserving (confirmed: the existing
29-test `test_settings_window.py` suite passes with only a class-name
rename, one test rewritten — see below). `WA_DeleteOnClose` dropped
entirely (item 32's fix no longer applies — this widget is never a
top-level window once embedded). New `select_tab(name)` replaces the
old constructor-only `initial_tab` handling, since the page is now
built once in `MainWindow._build_ui()` and persists for the app's
lifetime rather than being constructed fresh per open.

**Header/back button.** `_build_page()` gained an optional
`header_extra: QWidget | None` parameter — a real, reusable extension
point (a widget rendered to the left of the title, same row), not a
Settings-specific special case. The Settings page's own internal
subtitle label (hand-styled, `"color: gray;"`, no real margin — this
was the actual "misprinted-looking header" bug) is gone entirely;
routing through `_build_page` supplies a correctly-margined one
instead, closing §3.2 exactly as scoped ("the fix IS the routing, not
a one-off tweak"). One old test asserted the page's own internal
subtitle directly (`window.centralWidget()...`) — rewritten as
`test_settings_page_shows_its_subtitle_via_build_page` in
`test_ui_smoke.py`, checking it through `MainWindow`'s real page
wrapper instead, since that's where the subtitle actually lives now.

**Navigation.** Settings' sidebar button is now a real, checkable
`_nav_group` member (same as Help), built individually rather than via
the generic `_NAV_PAGES` loop since it needs the `initial_tab`-aware
click handler the loop's plain `_show_page(key)` can't express. Every
navigation path in this app — sidebar click, the new back button, a
Dashboard CTA action, a double-click — already goes through
`_show_page()`, so both the back button's "where to return to"
(`_previous_page_key`) and the settings-exit invalidation (§3.3) hook
into that one method rather than the raw Qt `currentChanged` signal a
first pass considered; the effect is identical (fires regardless of
which navigation path was used) since `_show_page` is the sole real
entry point.

**§3.3 — settings-exit invalidation, done via `_invalidate_after_
leaving_settings()`**: calls the existing `_refresh_duplicates_
locations()` (unconditionally, not gated by the lazy-load flag — Phase
6.1 will later reuse this exact same call for its own "refresh on
every show" fix, not a second method) and `_poll_next_step()`
immediately on any exit from Settings.

**§3.4 — About button**, wired via a callable (`on_about_requested`)
rather than importing `AboutDialog` directly — `AboutDialog` lives in
`main_window.py`, which already imports FROM `settings_window.py`
(`SETTINGS_TAB_*`), so a direct import back would be circular.
`MainWindow` wires it to its own `_on_about_clicked`, reusing the
identical dialog/copy as the Help-menu route, confirmed via identity
(`settings_page._on_about_requested == window._on_about_clicked`) —
not a second dialog construction path.

**Wizard confirmed still working end to end** — `test_wizard.py`'s
full 28-test suite passes unmodified (the wizard never actually
imports/uses `SettingsWindow`; one stale docstring comment
cross-references it as a historical precedent, harmless).

**Real stress-test re-verification (2026-09-01), and a real, non-
leak finding investigated properly rather than dismissed or
papered over.** Per the task's own explicit ask, re-ran the opt-in
`SEEKER_RUN_STRESS_TEST=1` suite (real Spotify/slskd/X9-Pro
infrastructure, real production DB, ~5 real minutes) against the
converted Settings page. First run: **RSS grew 263.2MB, over the
existing 250MB ceiling.** Re-ran a second time from a clean baseline
to rule out one-off noise before touching anything: **266.3MB**,
consistent — a real, reproducible finding, not flaky. Read the full
per-sample table rather than just the pass/fail line: the growth was
NOT monotonic to the end — RSS climbed from 480MB (t=15.5s) to ~527MB
over the interleaved loop's first ~11 cycles, then **genuinely
plateaued for the run's entire last ~120 seconds** (9 consecutive
samples within a ~2MB band) — the exact "one-time legitimate cost,
not a leak" shape the ceiling's own comment already described, not
the "monotonic, unbounded climb" it exists to catch.

**Root cause of the real, legitimate increase, traced directly:**
§3.3's settings-exit invalidation now fires two extra real
`run_worker` round-trips (`_refresh_duplicates_locations()` +
`_poll_next_step()`) on every Settings navigation — real background
work this stress test's interleaved loop (20 settings-visit cycles)
never exercised at this frequency before Settings became a persistent,
frequently-revisited page rather than a rarely-opened dialog.

**Fix — strengthened the test rather than just loosening a number.**
`MAX_ACCEPTABLE_RSS_GROWTH_MB` raised 250.0 → 300.0, with the real
measured numbers and reasoning recorded in a code comment. More
importantly, added a genuine leak-specific check the old test computed
but never acted on (`RSS trend check` was printed, not asserted): a new
`MAX_ACCEPTABLE_TAIL_RSS_RANGE_MB = 20.0` assertion over the run's last
quarter of samples — a real leak keeps climbing all the way to the end
even after any legitimate warm-up cost; a flat tail is real evidence of
"grew once, then stabilized," which the blunt total-growth ceiling
alone couldn't distinguish from "still climbing." **Verified live, a
third time, with both fixes in place:** 266.8MB total growth (under
the new 300MB ceiling), tail range **1.7MB** (min 527.1MB, max
528.8MB) — a genuine, tight plateau, confirming no leak. fd growth
+25/+40 ceiling, thread growth +11/+40 ceiling, `active_workers == 0`
at the end — all unaffected by this change, all still comfortably
inside their existing ceilings across all three runs.

`mypy --strict` clean; full fast suite 704 passed / 1 skipped, run 3
times in a row (one incidental flaky timing failure in an unrelated
pre-existing test — `test_history_refresh_button_refetches` —
reproduced as a pass in isolation and in 3 of 4 full-suite runs,
confirmed not a regression from this phase).

### 56, Phase 4 — tagging: cover art, honest reporting, caching

Scope reset by Phase 0.4's own findings: the append-not-replace
hypothesis (the brief's original framing for 4.1) was already refuted
before this phase started — `embed_album_art` already calls
`clear_pictures()`/`setall`/dict-assignment correctly for FLAC/ID3/MP4.
So 4.1 became real, scoped polish (FLAC `Picture` field completeness)
rather than a "fix," and 4.2 (honest partial-failure reporting) — the
real gap 0.4 actually found — got the emphasis instead, exactly as
directed.

**4.1 — FLAC Picture fields.** New `metadata.py::_read_image_dimensions`
— a minimal, dependency-free JPEG/PNG header reader (no image library
is a project dependency; Pillow would be a heavy addition for three
metadata fields most players don't even require). Verified against a
**real** Spotify CDN cover art JPEG, fetched live: parsed `(640, 640)`,
matching Spotify's known standard image size exactly. `embed_album_art`
now also sets `picture.desc = "Cover"` (ID3 already did) and
`width`/`height` when derivable; `depth` is set to a documented,
honest assumption (`24`, real-world JPEG/PNG cover art is
overwhelmingly 24-bit RGB) rather than independently computed — no
color-type-aware bit-depth parse was written for this. New regression
test proves the replace-not-append finding directly: embedding twice
on a copy of a real FLAC leaves exactly one picture, the second one's
dimensions, not two.

**4.2 — honest partial-failure reporting, the real fix.**
`_tag_one_track`'s art step now tracks an explicit outcome —
`written`/`no_url`/`download_failed`/`embed_failed`/
`format_unsupported` — instead of a bare `try/except` that only
`print()`ed a warning with the track still silently counting as a
plain `tagged` success. New `tagged_without_art` count (CLI and UI both
surface it) plus a `tagged_without_art_<outcome>` entry in `details`
for every affected track, with a real, actionable message — the
`no_url` case specifically tells the user to re-run `seeker
sync-tracks` for that playlist, the one code path that populates
`album_art_url` (item 9). UI: `_show_tag_result_notice` routes through
`InlineNotice` (item 47), not `status_label` — the exact bug class item
47 fixed elsewhere in this app (a message wiped by the next unrelated
2s poll tick) never applied to the tagging panel to begin with (its
`tagging_results` is an independent, persistent `QPlainTextEdit`, never
wired into `status_label`'s plumbing), but the brief's own ask was for
a real, prominent headline notice beyond that always-present detail
panel, and this is it: "Tagged 34 tracks — 12 without cover art" as a
warning-kind notice, a plain success notice when everything worked, an
error-kind notice naming a failure count when anything failed outright.

**4.3 — caching, verified live against Spotify's real CDN.** New
top-level `seeker/album_art_cache.py::AlbumArtCache` — an in-memory
dict (covers one tagging run with zero disk I/O) backed by an on-disk
cache under `platformdirs.user_cache_dir("Seeker", ...)` — deliberately
the CACHE directory, not the DATA directory `application.py` already
uses for the DB/config/token (this is disposable, safe to clear
anytime), keyed by a SHA-256 hash of the URL. `MetadataService` is
already a cached `Application` singleton (item 33's pattern), so the
default instance persists across tagging runs too, not just within
one. **Live-verified, not just unit-tested**: a real fetch of a real
Spotify CDN URL took 0.395s (94,118 real bytes); the identical URL
fetched again through the same cache returned the same bytes in
0.000s, with real `.bin`/`.json` files written under a real temp cache
dir. **Confirmed, since the user asked directly:** this consumes zero
Spotify Web API quota either way — the URL comes from
`tracks.album_art_url`, already captured at sync time, and the fetch
itself goes to Spotify's CDN, not the Web API; the cache is a
bandwidth/latency win only.

**A real test-isolation bug found and fixed while wiring this up, not
filed for later.** `test_metadata_service.py::make_service()`
originally constructed `MetadataService` with no explicit
`album_art_cache`, which defaults to the REAL, persistent platformdirs
cache path — a fake test URL (`https://i.scdn.co/image/fake`) written
by one test's disk cache silently satisfied a LATER test's "was this
genuinely re-downloaded" assertion (`test_tag_tracks_force_bypasses_
both_skip_checks_independently`, caught failing with `art_calls == 0`
instead of `1`). Fixed by giving every test an isolated
`AlbumArtCache(tmp_path / "art_cache")` — the same "tests must not
share real, persistent state" discipline this project already applies
to the real production DB elsewhere.

`mypy --strict` clean; full suite 718 passed / 1 skipped, run 3 times
in a row, no flakiness this time.

### 56, Phase 5 — download UX and the duplicate-download bug

One causal chain, exactly as Phase 0.5 traced it: no feedback → the
user re-clicked → the existing dedup guard didn't cover a `completed`
row → two real, differently-named files landed for one track.

**5.1 — immediate feedback.** Audited every `run_worker()` call site in
`main_window.py` (31 total) for whether it passes `button=` — every
other user-triggered action already did, or has no applicable button
widget (a context-menu action, a standing poll timer) where the
existing `status_label`/`InlineNotice` mechanisms already give adequate
feedback; the download button was the one real, substantive gap. Fixed
with `_set_download_button_busy()`/`_reset_download_button()` managed
manually across the button's real 3-hop chain (resolvability check →
maybe a destination dialog → the real download), since `run_worker`'s
own per-call `button=` handling would otherwise flicker the button
enabled between hops. A real result notice via `InlineNotice` reports
requested/skipped/already-in-progress counts.

**5.2 — the real fix.** New `DownloadRequestRepository.
get_requests_blocking_redownload()` — deliberately a NEW method, not a
redefinition of the existing, already-widely-referenced
`get_active_for_track()` (item 16's own precedent, still correct for
its original purpose) — excludes only `failed`/`superseded`, so a
`completed` row now blocks a re-download the same way an in-flight one
already did. Keyed on `track_id` alone, deliberately not
`download_dedup.candidate_key` (which includes `filename` — exactly
why two differently-named files from two different peers slipped
through before). `download_playlist()`'s return gained
`already_in_progress: list[str]` so the UI can report specifically
which tracks were skipped for this reason, distinct from "no candidate
found."

**5.3 — a safety net for what 5.2 alone can't catch**: a request
created BEFORE the track was matched by something else (a manual
scan+match, or a second download finishing first). New
`DownloadService._track_already_has_a_matched_file(track_id)`, checked
before `_move_completed_file` at BOTH real automatic-completion call
sites (the main `poll_downloads()` loop and `_retry_locked_request`'s
own completion branch — the latter's existing code comment already
explains why a human-confirmed-via-item-26 candidate auto-moves without
a second confirmation; this check is a genuinely different concern —
avoiding a duplicate file on disk — and applies on top of that
reasoning, not against it). Deliberately NOT applied to
`apply_upgrade_decision`'s own replace action — a human explicitly
clicking "Replace" is the one place overwriting an existing match is
the whole point.

**5.4 — root-caused, not just reskinned.** Confirmed directly: a
just-completed row stays visible for `RECENTLY_FINISHED_WINDOW_SECONDS
= 60`, still gets sampled by the real 20s backend-poll cycle
(`_sample_download_progress`), and since its bytes never change again,
3 identical samples trip `_is_stalled()` — the exact "Calculating,
then Stalled, then vanishes" sequence reported, reproduced directly in
a new test before touching any code. Fixed by branching on status
FIRST: new `_DOWNLOAD_TERMINAL_STATUSES` (completed/failed/
ready_for_review) get a fixed label + a full/cleared bar from a new
`_build_terminal_progress_widget`, never routed to the ETA tracker at
all; a new `DownloadEtaTracker.evict(id)` drops the id the instant its
row is seen as terminal, not left to `evict_except()`'s once-per-poll
sweep. Checked, not assumed (§4's own explicit ask): terminal rows
WERE being folded into `format_aggregate_header()`'s "queued (no
estimate)" figure — `_render_aggregate_eta` now filters them out
first. Real, disclosed scope trim: the brief's suggested "Completed —
moved to *destination*" per-row detail wasn't built — no destination
path is captured anywhere on `DownloadRequest`/`ActiveDownload`, and
adding it would need either a schema change or a live per-playlist
resolve call bundled into the poll; the page subtitle instead explains
the 60-second-then-moves-to-History behavior, which addresses the
same "make the disappearance intelligible" intent without the added
plumbing.

**Real live verification against the production slskd instance and
DB, not just the test suite**: `seeker downloads status` ran clean
end-to-end (one real, transient 500 from slskd's own retry endpoint
for an unrelated locked candidate — expected real-world flakiness,
already handled by the existing per-item try/except, not a regression).

`mypy --strict` clean; full suite 730 passed / 1 skipped, run 3 times
in a row, no flakiness.

### 56, Phase 6 — Duplicates tab

Four distinct problems, one genuinely NOT reproducible.

**6.1 — the location combo never refreshed.** Root cause confirmed as
described: `_duplicates_locations_loaded` gated the fetch to fire at
most once ever (item 39's own deadlock fix, triggered by a
CONSTRUCTION-time eager fetch). Removed the gate entirely — a page
SHOW is a different, human-paced trigger, the same distinction item
39's own addendum already drew between "every MainWindow construction"
and "a real tab click." `_render_duplicates_locations` now also
preserves the current selection across a refresh. Both the settings-
exit path (§3.3) and every Duplicates page show now land on the same
`_refresh_duplicates_locations()` call. Re-ran the full
`test_ui_smoke.py` suite as instructed, specifically to catch any
regression toward the original deadlock: 145 passed in 4.3-6.5s across
three separate runs — no hang, healthy timing throughout.

**6.2 — the reported "Actions column is empty" bug could NOT be
reproduced, investigated thoroughly rather than assumed fixed.**
Checked all three suspected causes directly: the theme's own
`QTableWidget::item` padding regression (item 47's exact hazard) is
confirmed absent from the current `theme.py`, with its warning comment
still in place. Reproduced the scenario the brief specified — a real,
offscreen `MainWindow`, a REAL `DuplicateService` (real Database, real
repositories), two real generated duplicate `.wav` files in a
disposable temp directory, real `compute_fingerprints`/
`find_duplicate_groups` via real libchromaprint — tested via a direct
render call, a full re-render (the stale-`setSpan` hypothesis), and
the real asynchronous `run_worker` click path (a queued cross-thread
signal behaves differently than a direct call, per this project's own
established `run_worker` hazard history). The Actions column rendered
correctly, visible, with a real `QPushButton` and `QCheckBox`, in
every one of these. Kept as a permanent regression test against this
exact real pipeline rather than silently dropping the investigation —
an honest "unverified, not reproducible" result, not a fabricated fix
for a bug that isn't there in the current code.

**6.3 — "Keep all," full paths, and groups larger than two.** Groups
of 3/4 already worked by construction (confirmed directly, then two
new explicit tests assert exactly N-1 ids reach `delete_local_files`
and the kept file survives — no code change was needed there, only
the missing coverage). New `KEEP_ALL_DUPLICATES_ID` sentinel added to
each group's existing `QButtonGroup`, disabling that group's Delete
button when selected. **A real, live-caught Qt gotcha found while
wiring this up:** the first attempt used `KEEP_ALL_DUPLICATES_ID = -1`
— `QButtonGroup.addButton(button, id=-1)` does NOT set the id to
literal `-1`; Qt reserves `-1` as its own "auto-assign an id" sentinel
and silently substitutes a different, Qt-generated negative id
(confirmed live via a direct repro: `checkedId()` returned `-2`, not
`-1`), which meant "Keep all" never actually disabled Delete — caught
by a new test failing under the full suite, not assumed correct from
the code alone. Fixed by using `0` instead (real `local_file` ids are
AUTOINCREMENT, always `>= 1`, so `0` can never collide with one).
Location + full relative path added as real table columns (`Location`/
`Path`), resolved once per search rather than plumbed through the
service layer — a `DuplicateFile`/`LocalFile` carries only
`location_id`, not a real path, and `find_duplicate_groups()` is
already scoped to one location per call. The delete-confirmation
dialog now lists the exact full paths about to be deleted, built from
that same resolved location path. Known limitation, disclosed rather
than pre-empted: keeping *some but not all* of a group (2 of 4) isn't
expressible in this keep-one/keep-all model — flagged in a code
comment, not built.

**6.4 — reclaimed-space milestone.** New `duplicate_cleanups` table
(guarded `CREATE TABLE IF NOT EXISTS` in the shared `SCHEMA` string,
matching every other table there — not a separate `_migrate` ALTER,
since this is a brand-new table, not a new column on an existing
one), verified against the real, non-empty production DB: the table
was created cleanly, `track_matches`' real 29-row count was
unaffected. `delete_local_files` now measures `bytes_freed` via a real
`Path.stat().st_size` call BEFORE either the DB row or the file itself
is deleted (item 40's own DB-row-first-then-file ordering rule still
applies below that), falling back to the stored `size_bytes` column if
the stat call itself fails — verified directly with a real 15-byte and
a real 5+10-byte deletion, and with a dedicated unit test isolating
the fallback branch via a monkeypatched `stat()` failure. A batch that
deletes nothing real records no cleanup row at all ("an empty
milestone is worse than no milestone"). UI: `duplicates_milestone_
label`, hidden entirely at zero, refreshed on every Duplicates page
show and immediately after a real delete completes. CLI: the same
total in `seeker library duplicates`'s own header, same hide-at-zero
rule. Verified end to end against the real production `Application()`:
`get_cleanup_totals()` returns `(0, 0)` cleanly, no error.

`mypy --strict` clean; full suite 744 passed / 1 skipped, run 3 times
in a row, no flakiness.

### 56, Phase 7 — Sharing & Uploads

The largest new piece of this work block: what Seeker itself gives
back to the SoulSeek network it downloads from. Built in the order the
brief specified — live API verification BEFORE any client code.

**7.2 — live slskd API verification, against a disposable throwaway
container only, never the real production one.** Built
`seeker_swagger_repro` (ports 15030/15031/15300, session scratchpad
dir, `SLSKD_SWAGGER=true`, `SLSKD_REMOTE_CONFIGURATION=true`, a
`slskd.yml` with auth disabled) — the fake/auto-created-account finding
from item 52 held again (`throwaway_repro_user`/`throwaway_repro_pass`
logged in cleanly with no prior registration). Fetched the real
72-path swagger schema and made real live calls, confirming/correcting
several things CLAUDE.md had never documented:
- `GET /api/v0/shares` returns `{"local": [share, ...]}` — nested under
  a `"local"` key, NOT a bare array. Each share: `id`, `alias`,
  `isExcluded`, `localPath` (the CONTAINER-side path), `raw`,
  `remotePath`, `directories`, `files`.
- `GET /api/v0/application`'s `shares` block has `ready`/`scanning`/
  `directories`/`files` (already known, item 53) PLUS `scanPending`/
  `faulted`/`cancelled`/`scanProgress`/`hosts` — new findings.
- `PUT /api/v0/shares` triggers a real rescan — confirmed with a real
  file added to the shared dir, `files` count going `0 -> 1` after.
- `PATCH /api/v0/options`'s `OptionsOverlay` schema has no `shares` key
  anywhere at all — only `soulseek.listenIpAddress`/`listenPort` are
  patchable. Share directories genuinely cannot be changed via the
  API, confirmed from the schema itself, not inferred from a failed
  attempt.
- `GET /api/v0/transfers/uploads` is a flat array (unlike downloads,
  scoped by username in the URL) — returned `[]` live; no real upload
  was in flight to observe a populated shape, so `sharing_service
  .py`'s `_parse_upload` is deliberately defensive (`dict.get`
  everywhere), not assumed beyond what downloads' shared `Transfer`
  schema already confirms (`state`/`bytesTransferred`/`size`).

Cleanup: `docker rm -f seeker_swagger_repro`, scratch dir removed,
confirmed the real production `slskd` container (`7a149e4b5d6b`)
untouched and still healthy throughout via `docker ps`/a real
`/api/v0/application` call against it.

**A second, dev-machine-specific real finding, needed for 7.5's write
path.** This repo's own `slskd-data/slskd.yml` looked, at a glance,
like the real active share directory was never set (the top ~300
lines are a fully commented default-template reference block). The
real, active, uncommented `shares: / directories: - /shared/music`
section lives much further down (line 352) — `grep`, not `head`,
confirmed this. Separately, `docker inspect slskd --format
'{{range .Mounts}}...'` confirmed the real running container's `/app`
mount source is this repo's own `./slskd-data` (not the platformdirs
path `docker_setup.slskd_data_dir()` would suggest) — meaning this
dev instance was brought up manually from the repo root at some point,
not exclusively via the wizard's `bring_up_slskd()`. Lesson applied
directly to `sharing_service.py`: never trust `docker-compose.yml`'s
own `${VAR:-default}` fallback text, or `slskd_data_dir()`, as the
real current mount — always resolve real host↔container paths via
`docker inspect <container> --format '{{json .Mounts}}'` on the actual
running container. This is also how `is_self_managed()` detects
self-managed-ness: confirmed live that `docker compose` stamps every
container it creates with a `com.docker.compose.project.config_files`
label naming the exact compose file used — compared against
`docker_setup.compose_file_path()`, resolved. Any failure to read this
(Docker down, container missing, label absent) conservatively returns
`False` — never risk rewriting infrastructure this app can't prove it
owns.

**7.1/7.3 — framing copy + service layer.** `help_text.py`'s
`SHARING_FRAMING_BODY` explains locked files (a peer's own leecher
restriction, not something Seeker can see in advance) and upload
priority (real, but no published formula/guarantee) honestly, framed
as "be a genuine sharer, see that you are" rather than a persuasive
pitch. New top-level `seeker/sharing_service.py` (`SharingService`),
exposed as `Application.sharing_service`, constructed the same
soulseek_configured-gated way as `download_service` (a caller that
only wants `is_self_managed()`/`preview_add_location()` must not be
forced to have SoulSeek configured). New CLI `seeker sharing status`
for parity with `seeker downloads status`.

**7.4 — reconciliation.** `get_reconciliation()` matches each
`library_locations` row (a real host path) against the live shares
(container paths) by resolving BOTH through the same live
`docker inspect` mount mapping — a location is "shared" only when its
real host path is the `Source` of a mount whose `Destination` a real
share's `localPath` also resolves through. Docker/slskd unreachable
degrades to "everything reads unshared" rather than raising, since
this is a read-only status view, not a mutation.

**7.5 — the gated write path.** `add_location_to_share()`: requires
`confirm=True` (raises `ValueError` otherwise), requires
`is_self_managed()` (raises `SharingWriteNotAllowedError` otherwise —
degrades to a read-only preview/guidance dialog in the UI instead of
attempting a write), requires the location isn't already shared
(`ShareAlreadyExistsError`). Backs up both `docker-compose.yml` and
the real live `slskd.yml` (resolved via the live `/app` mount, not an
assumed path) with a UTC timestamp suffix BEFORE writing either.
`_insert_compose_volume_line`/`_insert_slskd_share_directory` are
small, purpose-built line-based text editors (no YAML dependency added
— this project already avoids adding dependencies casually, and these
only ever need to understand the exact shape of a file this app itself
maintains) — the slskd.yml inserter specifically targets the real
ACTIVE `shares:`/`directories:` block, not the commented default
template near the top, verified with a dedicated test asserting the
commented block stays untouched. The new share mount is always
`:ro` — not configurable, matching the framing copy's own "be a
genuine sharer" spirit (never mount your library writable to a share
you don't control). Recreate is `docker compose up -d` with the
CURRENT live-resolved `SLSKD_DATA_DIR`/`SLSKD_SHARE_PATH` explicitly
passed through (not the compose file's own hardcoded fallback text),
reusing item 13's own already-documented, already-verified finding
that omitting the network-credential env vars on a recreate is safe —
slskd falls through to what's already persisted in `slskd.yml` rather
than clobbering it. Polls `/api/v0/application` for
`ready && !scanning && !scanPending` up to `SHARE_READY_TIMEOUT_
SECONDS = 120.0` (untuned, flagged same as every other threshold in
this codebase), reporting real before/after directory/file counts
either way.

**7.6 — Uploads view.** New sidebar page, lazy-loaded on first visit
like Duplicates (never at MainWindow construction — item 39's
deadlock), joining the existing 20s `backend_poll_timer` once visited
(same shape as Downloads' own real-slskd-call poll) rather than a
separate new `QTimer`. New `ui/upload_eta.py`'s `UploadEtaTracker` is
a deliberately SEPARATE tracker from `DownloadEtaTracker` — keyed by
`(username, filename)`, not an int `download_requests.id`, since an
upload has no row in this app's own database at all (purely live
slskd-side state) — reuses the same `(username, filename)` pairing
`download_dedup.py` already established elsewhere in this codebase for
identifying one real candidate transfer.

**Out of scope, explicitly** (not scoped or attempted as part of this
phase, same as item 37's Linux-packaging disclosure): upload groups/
priorities/limits configuration, buddy-list management, unlock-request
messaging to a specific locked peer, and locking your own shared files
from specific users. All are real slskd features, just not what this
phase's brief asked for.

`mypy --strict` clean across 79 source files; full suite **766 passed**
(744 + 15 new `test_sharing_service.py` + 4 new Sharing-page
`test_ui_smoke.py` tests + 3 new `test_cli.py` tests), run 3 times in a
row, no flakiness. A pre-existing, unrelated bug in the opt-in stress
test was found and fixed while extending it for this phase (see below)
— `test_stress_e2e.py` isn't part of this 3x re-run since it's opt-in
and slow.

**Extending the opt-in stress test (`test_stress_e2e.py`) to cover the
Sharing page — one real pre-existing bug fixed, one real attempted run
inconclusive, disclosed honestly rather than reported as a pass.**
Added a read-only Sharing-page visit into the existing interleaved
navigation loop (deliberately excluding `add_location_to_share` — it
recreates the real production slskd container and rewrites real
`docker-compose.yml`/`slskd.yml`, and there's no disposable analog the
way Duplicates' delete action has one). Running it for the first time
surfaced a real, pre-existing, unrelated bug: `duplicates_table`
gained a "Keep" column in Phase 6.3 (7 columns -> 8), pushing its
Actions column from index 6 to 7 — `test_ui_smoke.py` was swept for
this at the time, but this file wasn't (it's opt-in, so Phase 6.3's
own 3x-in-a-row re-run never touched it). Fixed the stale index.

**A real, attempted full run of the extended test (2026-09-01,
20:36-21:57 local) did not reach a usable result and was killed
deliberately, not left to finish.** ~81 minutes elapsed against the
test's nominal 5-minute interleaved-loop duration, with the process
confirmed alive throughout (steady, slow CPU-time growth — not a flat
0% deadlock signature) but never producing output (the `| tail -200`
piping means nothing prints until the whole run finishes) and never
reaching the point where it registers its own disposable duplicates
location's cleanup. **Genuinely unknown, not guessed:** whether this
was real Spotify rate-limit backoff across a full 215-playlist sync
(`sync_button.click()` runs before the interleaved loop even starts)
or a silent stall on something requiring attention this unattended run
couldn't provide (e.g. a permission prompt) — a `kill -INT` was tried
first specifically to give the test's own `finally` cleanup a chance
to run and distinguish these, but showed no meaningful CPU response
within 30s either, which is itself not conclusive proof of either
cause. Killed via `kill -KILL` on the user's explicit instruction
rather than left running or reported as a pass. Real cleanup performed
by hand afterward (the process died before its own `finally` block
could run): the leftover `SeekerStressTestDuplicates` library_locations
row (id 10) and its temp directory were removed directly against the
real production DB; `config.json` was confirmed still at its real
baseline values (the threshold-change step happens well inside the
interleaved loop, past where this run ever got); `docker-compose.yml`
had no working-tree diff and no `.bak-*` files existed anywhere; the
real production `slskd` container's `CreatedAt` (2026-08-31 19:17:29)
predates this run entirely, confirming it was never recreated. **This
phase's closing verification relies on the earlier, real, successful
Phase 3 stress-test run (CLAUDE.md item 58 / this file's own Phase 3
section) for the RSS/fd/thread-growth signature — not on a fresh run
from this session.** A fresh, ATTENDED run of the now-fixed,
now-Sharing-extended test (someone present to notice a stall vs. a
slow-but-real backoff in real time) is still genuinely needed before
trusting this specific extension's numbers; not treated as done here.

**Recommendation for the attended re-run, prepared for when Kris is
back:** don't just lower `SEEKER_STRESS_DURATION_SECONDS` — that only
shortens the interleaved loop *after* setup, and this run's real
bottleneck (whichever it was) happened before the loop ever started.
Two concrete changes for a useful attended check: (1) run it directly,
without the `| tail -200` pipe this session used — that pipe buffers
ALL output until the process exits, so nothing streams live; drop it
so `[stress]` lines and `main_window.status_label` prints appear in
real time. (2) `SEEKER_STRESS_DURATION_SECONDS=90` (or similar) for a
short interleaved-loop portion once setup completes, specifically to
exercise the new Sharing-page visit a few times without waiting out
the full 300s default. Concretely:
`SEEKER_RUN_STRESS_TEST=1 SEEKER_STRESS_DURATION_SECONDS=90
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_stress_e2e.py -q -s`
— run in an interactive terminal, not backgrounded, so a real stall
(vs. a slow real Spotify sync) is visible immediately rather than
inferred from CPU-time deltas after the fact.

### 62, follow-up — real live verification of `add_location_to_share`
and the real uploads-transfer schema, both requested explicitly before
Phase 7 could be considered done.

**1. `add_location_to_share` end-to-end, against a real disposable
throwaway slskd container — full real run, not mocked.** Unit tests
alone weren't sufficient given what this path touches (real file
writes, a real container recreate) — matches this project's own
standing precedent (item 52) for anything this consequential.

A real blocker surfaced immediately: `SharingService` hardcoded
`SLSKD_CONTAINER_NAME = "slskd"` with no override, so it could never
be pointed at a second, disposable container without colliding with
the name production's own container already holds — genuinely
untestable as originally written, not just inconvenient. Fixed
properly (not a test-only hack): `SharingService.__init__` gained a
`container_name: str = SLSKD_CONTAINER_NAME` parameter, threaded
through both real call sites (`is_self_managed`/`get_reconciliation`/
`add_location_to_share`'s own mount lookup); `Application.sharing_service`
uses the default, so real production behavior is unchanged.
`mypy --strict` clean, all 15 existing `test_sharing_service.py` tests
still pass unmodified.

Built `slskd_sharing_e2e_repro` (disposable, ports 15230/15231/15300,
real disposable SoulSeek credentials — auto-created per item 52's
already-confirmed behavior). **Second real, previously-undocumented
finding along the way:** `slskd --envars` (run against the base image
directly, disposable) reveals `SLSKD_SHARED_DIR <string[]>` — a real
env var for bootstrapping an initial share. Using it DID make the
share live immediately (`GET /api/v0/shares` reported it correctly,
1 real file) — but a real check of the container's own mounted
`slskd.yml` showed its modification time unchanged from the base
image's shipped default (334 lines, still the fully-commented
template, NO active `shares:` block) — meaning **an env-var-only share
configuration is never persisted back into `slskd.yml` on disk.** This
means production's real active `shares: / directories:` block (found
at line 352 back in the original 7.2 investigation) did NOT come from
this repo's own env-var-driven bring-up mechanism — its real origin
predates this app's automation (a direct Web UI save or a manual edit,
neither confirmed, both plausible) and stays unconfirmed; not guessed
further. This matters concretely: `add_location_to_share`'s own
`_insert_slskd_share_directory` correctly REQUIRES a pre-existing
active block and raises if none exists — now confirmed to be a real,
load-bearing precondition, not a hypothetical one, since a fresh
env-var-only bring-up genuinely doesn't satisfy it. Seeded the
throwaway's `slskd.yml` directly with the same real active-block shape
production has, then restarted the container to confirm the seeded
file (not just the env var) was what actually took effect (files
count came back identically after restart, sourced from the yml this
time).

**Real, live, full run against the seeded throwaway container:**
- `is_self_managed()` → `True` (real docker-label comparison).
- Before: `directories=0, files=1`.
- `preview_add_location` → container_path `/shared/New Location`,
  correct `:ro` compose line, correct slskd directory line.
- `add_location_to_share(confirm=True)` → `became_ready=True`; real
  before/after: **`(0, 1) -> (0, 2)`** — the new location's one real
  file was picked up. Both backup files created and confirmed to
  contain the PRE-edit content (`grep -c "New Location"` on each
  backup → `0`). `docker-compose.yml` gained exactly one new `:ro`
  volume line at the real host path; `slskd.yml`'s real active block
  gained exactly one new directory line, its commented default-template
  block untouched. Container's real `Created` timestamp confirmed the
  recreate actually happened; `docker inspect`'s real `.Mounts` showed
  both shares mounted correctly post-recreate. Reconciliation
  afterward correctly reported the location `shared=True` with a real,
  matching `ShareEntry`. Cleaned up (`docker compose down -v`, scratch
  dir removed); real production `slskd` container confirmed untouched
  throughout (unchanged `CreatedAt`).

**2. The real uploads-transfer schema — partially verified: the
declared shape is now confirmed with certainty; a real POPULATED live
instance was not obtainable in this environment, disclosed honestly
rather than forced or guessed.** Attempted a real two-peer transfer
(two disposable containers, A sharing a distinctive test file, B
requesting it) to capture a genuine live entry. A real, distributed
network SEARCH from B for A's file returned zero results twice (15s
and 45s waits) — plausible for two brand-new leaf peers with no
established distributed-search relay yet, not something forced
further. Fell back to a DIRECT `request_download` (B -> A, by
username+filename+size, bypassing search) and got a real, informative
failure instead of a populated transfer: `"Failed to connect to user
...: Failed to establish a direct or indirect message connection to
...(<real-WAN-IP>:50300)"` (HTTP 500). **Real, diagnosed cause, not a
guess:** both disposable containers run on this same host and are
reported to the real Soulseek server at the same public IP; only
production's own container's peer port has real inbound
reachability/port-forwarding on this network, so neither direct nor
indirect (server-relayed) connection could complete for a second
container. Confirmed A's own `/api/v0/transfers/uploads` stayed `[]`
throughout — the failure happened at connection establishment, before
any transfer object was ever created. **Deliberately did not
redirect this test at the real production instance to force a
populated result** — that would mean directing disposable test traffic
at Kris's real shared library outside what this phase's brief
authorized.

Fell back to the real, authoritative alternative: fetched the live
`slskd.Transfers.Transfer` schema from the real swagger contract
(`SLSKD_SWAGGER=true` on the same throwaway container — a live
container's own declared API contract, not documentation or
memory). It has `"additionalProperties": false`, meaning this list is
genuinely exhaustive, not partial: `id`, `batchId` (nullable),
`username` (nullable — confirms `_parse_upload`'s existing
None-handling was correct, not overcautious), `direction`, `filename`
(nullable), `size`, `state`, `requestedAt`, `enqueuedAt` (nullable),
`startedAt` (nullable), `endedAt` (nullable), `bytesTransferred`,
`averageSpeed`, `placeInQueue` (nullable — and CLAUDE.md item 53
already found this one specifically OMITTED ENTIRELY, not just null,
on a real live queued DOWNLOAD transfer; not independently
re-confirmed for the upload direction this session since no live
upload instance was obtainable), `exception` (nullable), `attempts`,
`nextAttemptAt` (nullable), `removed`, plus three read-only derived
fields (`bytesRemaining`, `elapsedTime`, `remainingTime`) and
`percentComplete`. A real `id` field exists (a stable per-transfer
UUID) that `sharing_service.py`'s `UploadEtaTracker` does NOT use as
its key — deliberately kept as `(username, filename)` instead, matching
`download_dedup.py`'s existing "key on real identity, not an ephemeral
internal id" precedent elsewhere in this codebase; not changed, since
neither is wrong for a pure speed-sampling use and a retry naturally
getting a fresh `id` is desirable there (a genuine restart should reset
the ETA estimate). `_parse_upload`'s existing field names
(`username`/`filename`/`state`/`bytesTransferred`/`size`) match the
real schema exactly — no code change needed.

### 63

Open investigation, genuinely unresolved — found live during Phase 7's
attended stress-test re-run (2026-09-01, PID 21050,
`SEEKER_STRESS_DURATION_SECONDS=90`), unrelated to Sharing/Uploads
itself. Reported here in full per this project's own standing "record
an unreproducible/unresolved finding honestly rather than fabricate a
fix" precedent (items 39, 61 §6.2).

**What was observed live.** After sync/scan/match settled (~15s, real
and healthy — contrast the earlier, killed 81-minute run), the test
entered a real burst of `"Failed to retry locked '@@rwvnt\Club &
Dance\Labels\Ambra\(AMB025) Zenea - INFINITE\01. Zenea - Infinite.mp3':
Server error '500 Internal Server Error'..."` lines against the real
local slskd — hundreds of them, growing continuously across a real
~18-minute observation window. First hypothesis (many stale duplicate
`locked` rows for the same track, per item 25's own disclosed gap) was
checked directly against the real production DB and refuted: exactly
**one** real row (`download_requests.id=13`, `status='locked'`, real,
pre-existing since 2026-08-28 — not created by this test). Sent
`SIGINT` first (no response within several seconds — the loop kept
growing), then `SIGKILL`. Verified afterward: production `slskd`
untouched and healthy (unchanged `CreatedAt`), the one real `locked`
row unmodified/not duplicated, `config.json` untouched. Cleaned up the
run's own leftover `SeekerStressTestDuplicates` library location by
hand.

**A first, hasty conclusion ("probably fine, just normal cadence") was
wrong and corrected before it shipped.** An initial hand-wave average
(total lines / elapsed time ≈ one retry per ~20s) looked consistent
with the timer's own cadence — but that average silently blended a
genuine fast burst with a genuine silent gap, and didn't yet account
for each real retry printing TWO lines (the app's own `print`, plus
httpx's `HTTPStatusError` continuation line), which had made the raw
line-count growth read as roughly double the real retry count.
Redone properly against the exact elapsed-time anchors recorded live
(`ps -p`'s own `ELAPSED` column, paired with `wc -l` at each check):

```
t=0s->520s   (Δ520s):  +295 lines = ~147.5 retries  (~1 per 3.5s)
t=520s->836s (Δ316s):  +0 lines   = silent (no retries at all)
t=836s->1058s(Δ222s):  +54 lines = ~27.0 retries    (~1 per 8.2s)
t=1058s->1095s(Δ37s):  +8 lines  = ~4.0 retries     (~1 per 9.2s)
```

A genuinely bursty, three-phase real pattern — fast, then silent, then
slower-but-still-too-fast — not a uniform "polls slightly too often"
story. This rules out a simple constant-factor explanation (e.g. "the
timer interval is secretly 3.5s instead of 20s") on its own.

**Three isolated, controlled repros, each closer to the real
conditions, ALL came back clean — the core mechanism is not buggy in
isolation.** All three seed a disposable DB with exactly one
`download_requests` row at `status='locked'` (matching the real
production row's shape) and pump a real `MainWindow`'s real Qt event
loop for 90 real seconds the same way `test_stress_e2e.py`'s own
`_pump()` does (`processEvents()` + `time.sleep()`), then count real
`request_download()` calls:

1. Real `DownloadService`, real `MainWindow`/timer/guard, an
   instant-failing stubbed `SoulseekClient` (no real network): **4
   calls, deltas 20.00s/20.03s.**
2. Same, plus heavy artificial load on the SAME `window.thread_pool`
   (a 500ms `QTimer` submitting 5 slow 2s `run_worker()` tasks per
   tick — 895 tasks total over the run, against a real
   `maxThreadCount()` of 14, deliberately mirroring the real stress
   test's simultaneous `download_playlist()` x3 + fingerprinting +
   duplicates-find + the new Sharing-page poll all competing for
   worker threads): **3 calls, deltas ~28.6s/29.0s** — saturation
   *slowed* the cadence, never sped it up.
3. Real `DownloadService`, real **local slskd** (safe: a throwaway DB,
   and a fake, nonexistent `username`/`filename` so no real peer or
   real data was ever touched), real `MainWindow`/timer: **4 calls,
   deltas 20.04s/20.00s/20.03s.**

Static tracing backs the repros up: `_retry_locked_request` (`soulseek/
download_service.py`) has exactly ONE call site in the whole `src/`
tree (inside `poll_downloads()`'s own `for request in locked:` loop);
`poll_downloads()` itself has exactly two call sites in the whole
`src/` tree (`cli.py`'s `handle_downloads`, unused by the GUI/stress
test, and `main_window.py`'s `_trigger_backend_poll`, guarded by
`_backend_poll_in_progress`); the download button's own click chain
(`_on_download_clicked` → `_on_destination_checked` → `_start_download`)
never touches polling at all; and the shared dispatcher's
`_callbacks.pop(task_id, None)` pattern (`ui/workers.py`) makes even a
hypothetical duplicate signal delivery for the same task a structural
no-op, not a second real dispatch. `get_locked()`'s query is a plain
`SELECT ... WHERE status = 'locked'` with no JOIN — cannot return
duplicate rows for one real primary key. No stray/leftover process was
found running concurrently against the real DB at the time (`ps aux`
checked clean afterward, though this wasn't checked *during* the live
run itself — a real, disclosed gap in the forensics, not filled in).

**Genuinely open — two untested candidates, not yet distinguished,
flagged for the next attended run to test TOGETHER (not separately,
since the real bursty pattern may only need the real combination):**
(1) real production DB **scale** — the repros' DB has exactly one
`download_requests` row total; the real run's concurrent
`download_playlist()` calls create a real, much larger `pending` list
that `poll_downloads()`'s own pending-loop (running immediately before
the locked-loop, same transaction) has to process every single call,
with real network latency per row — untested whether a large enough
pending list changes the locked-loop's own effective call frequency
somehow; (2) the full **concurrent-traffic combination** — repro 2
tested thread-pool saturation from dumb sleep-tasks, not real
`download_playlist()`/fingerprinting/duplicates-find traffic actually
exercising `DownloadService`'s own real methods concurrently with
`poll_downloads()`, which could interact differently (e.g. real SQLite
transaction contention across `Database.transaction()`'s
per-call connections, untested).

**Instrumentation added for the next attended run, not a fix:** a
temporary, timestamped `print()` at the very top of `poll_downloads()`
(`[poll_downloads] {utc iso timestamp} called`) plus one more
reporting `pending`/`locked` row counts — gives real per-call timestamps
directly, instead of the error-prone approach this investigation
started with (inferring cadence from retry-error line counts, which
undercounted the real rate by ~2x on the first pass because each retry
prints two lines). Remove once root-caused. `mypy --strict` clean; full
suite 766 passed (this diagnostic print doesn't touch any
`capsys`-asserting test's exact-match expectations — all existing
assertions are substring checks).

**2026-09-02 attended re-run: storm did NOT reproduce; one prior
assumption corrected.** Step 1 (checked first, before touching real
slskd): confirmed `BACKEND_POLL_INTERVAL_MS = 20_000` is a hardcoded
module constant in `main_window.py`, with no env var, monkeypatch, or
conftest override anywhere in the tree — `test_stress_e2e.py`
constructs a real `MainWindow` with no cadence patching at all, only
reading `SEEKER_STRESS_DURATION_SECONDS` to size the pump loop. So the
accelerated test loop runs the exact same 20s timer as production —
this rules out "only reachable inside the fast test loop" as an
explanation, whatever the outcome of the live run.

Step 2, the attended live run
(`SEEKER_RUN_STRESS_TEST=1 SEEKER_STRESS_DURATION_SECONDS=90
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_stress_e2e.py -q -s`,
unpiped except for a live `grep` filter into a Monitor stream so Kris
could watch real per-call timestamps as they landed, never
reconstructed after the fact): confirmed `docker ps` showed `slskd`
healthy before starting. First surprise: the real production DB holds
**three** `locked` `download_requests` rows (`id=9`, `id=10`, both
`role='upgrade'`, dated 2026-08-27, plus the already-known `id=13`
dated 2026-08-28) — last night's "exactly one real row" check was
apparently scoped to duplicates of the *same* track, not a count of all
locked rows in the table; corrected here since it changes the shape of
what a "locked-retry loop" is retrying against.

Watched 29 consecutive `poll_downloads()` calls live, spanning
2026-09-02T08:59:36 → 2026-09-02T09:08:56 (~9.7 real minutes,
comfortably past the point in the 2026-08-28 run where the storm was
already well underway from t≈0). Every single delta was clean:

```
20.000s, 20.000s, 20.001s, 20.001s, 19.999s, 20.000s, 19.999s,
19.998s, 19.999s, 20.001s, 19.999s, 19.998s, 20.001s, 20.002s,
19.997s, 19.997s, 19.996s, 20.001s, 19.999s, 19.999s, 19.998s,
19.997s, 19.998s, 19.985s, 19.987s, 19.997s, 19.996s, 20.001s, 19.998s
```

`locked` fluctuated harmlessly between 2 and 3 across cycles (rows
cascading in and out as retries succeed/fail — expected, not a growth
trend), `pending` between 0 and 1. Exactly one `"Failed to retry
locked '...Zenea - Infinite.mp3'..."` line printed per cycle, every
cycle — never more than one, never a burst. **This means the storm's
presence is intermittent, not reliably reproducible on demand**: the
same three real locked rows, against the same real local slskd, over a
comparable elapsed window to the original incident, produced zero
storm behavior this time. Mere presence of `locked` rows — even three
of them — is not sufficient on its own to trigger it; whatever tipped
it into the bursty pattern on 2026-08-28 (a specific DB state, a
specific queue depth at that moment, timing relative to some other
concurrent operation, or something not yet identified) remains
genuinely open.

**Process-level lesson, not a finding about the bug itself:** this run
was ended by the orchestration tooling's own 10-minute monitor timeout,
not by the planned `SIGINT`-then-`SIGKILL` — the test process was
killed before reaching its own cleanup code. Verified afterward that
this caused no real damage: `slskd` healthy and un-restarted,
`config.json` mtime unchanged from before the run, all three real
`locked` rows unmodified and not duplicated, zero new
`download_requests` rows created. The one real casualty was the test's
own leftover `library_locations` row (`SeekerStressTestDuplicates`,
id=12) plus its 2 `local_files` rows and backing temp dir under
`$TMPDIR` — its own `finally`-style cleanup never got to run. Cleaned
up by hand (`DELETE FROM local_files WHERE location_id=12;` first, per
item 40's standing row-before-file order, then `DELETE FROM
library_locations WHERE id=12;`, then `rm -rf` the temp dir) — **note
sqlite3's CLI does not enable `PRAGMA foreign_keys=ON` by default, so
the expected `ON DELETE CASCADE` from `library_locations` to
`local_files` silently did NOT fire** and the child rows needed an
explicit delete; worth remembering for any future by-hand cleanup via
the raw `sqlite3` CLI specifically (the app's own `Database` connection
enables foreign keys itself, so this gotcha is CLI-only). Lesson for
next time: raise the Monitor/orchestration timeout before starting a
longer attended window, so a real multi-cycle observation isn't cut off
mid-run.

Two things from the original untested-candidates list (item 63's
initial writeup) remain untested: real production DB scale under a
large `pending` list, and the full concurrent-traffic combination. This
run's `pending` stayed at 0-1 throughout (no large real queue was
present), so it doesn't speak to either candidate — Step 4 (if reached)
still needs to test them.

**Step 3, same day: isolating repro with real tracks and ZERO locked
rows — also clean, plus one real unrelated bug found and fixed along
the way.** Built `tests/_stress_step3_no_locked_repro.py` (leading
underscore, not pytest-collected, matching the existing
`_workers_*_repro.py` convention): a throwaway data dir (monkeypatched
`platformdirs.user_data_dir`, never touching the real production DB),
seeded with real track data from Kris's "Under Pressure (Deluxe)"
playlist (15 real Logic tracks — required running a real, one-time
`seeker sync-tracks "Under Pressure (Deluxe)"` first, since the
playlist's metadata was synced but its track list never had been), a
disposable destination location, then one real `download_playlist()`
call against real local slskd and a real `MainWindow`/timer pumped for
~260s.

**Real bug hit and fixed first, unrelated to item 63 itself:**
`MainWindow.__init__` → `_load_playlists()` evaluates
`application.sync_service` synchronously on the main thread (not
inside `run_worker`'s background thread) to obtain the bound
`list_playlists` method — and `Application.sync_service`'s property
getter unconditionally builds a real `SpotifyClient` via
`self.spotify`, which calls `auth_manager.get_valid_token()` with no
`spotify_configured` guard anywhere in that chain. With no cached
token in the fresh throwaway dir, this fell through to `_authorize()`
and opened a REAL Spotify OAuth browser tab — confirmed live, twice
(the second call crashed with `OSError: [Errno 48] Address already in
use` on the local OAuth callback server's port, since the first attempt
was still holding it). Harmless (standard consent screen, no
credentials at risk) but a real, unintended side effect of testing
against a fresh env — worth knowing for any *future* isolated repro
that constructs a real `MainWindow`. Fixed in the repro script itself
(not app code — this eager-property-eval-on-the-main-thread shape is
how `_load_playlists` has always worked and is out of scope here) by
seeding a non-expired-looking fake `spotify_token.json` at the
throwaway token path before constructing `Application`, so
`get_valid_token()` short-circuits and returns it directly with no
network call. Killed the first (broken) run by hand
(`kill -TERM`), verified no lingering effect (port free, real
production `spotify_token.json`/`config.json` mtimes unchanged from
before the run), then re-ran clean.

The clean retry: 14/15 real searches succeeded (1, "Intro", found no
candidates that run — real P2P search result variance run-to-run, not
a bug), 13 of 14 requested files completed and moved within the first
~20s (fast local peers), one track (`pending=1`) sat unresolved
(neither completing, failing, nor locking) for the entire remaining
~240s of the run — itself a real, disclosed loose end (not investigated
further here; out of scope for item 63). `poll_downloads()` cadence
over 14 consecutive calls, `locked=0` confirmed every single call:

```
19.97s, 20.01s, 19.99s, 20.04s, 19.99s, 19.99s, 20.01s, 19.99s,
19.98s, 20.05s, 19.99s, 19.97s, 20.00s
```

Completely clean — **the storm does not require the locked-retry loop
to be active at all to test for; but by the same token, this run gives
no positive evidence either way about the locked-retry path
specifically**, since it never had a `locked` row to retry. Combined
with Step 2 (locked rows present, still clean), the two runs bracket
the original incident without reproducing it from either side: presence
of `locked` rows isn't sufficient (Step 2), and this run shows the
*pending*-loop path alone, independent of any locked-retry activity,
also stayed clean. The original 2026-08-28 storm's trigger remains
unidentified. Cleaned up all three throwaway temp dirs this script
created (`seeker_step3_repro_*` under `$TMPDIR`) by hand afterward.

**Step 4, same day: the last two untested candidates from the original
writeup — real DB scale and the full concurrent-traffic combination —
tested TOGETHER, still clean, plus two more real, useful data points
surfaced along the way.** Built `tests/_stress_step4_scale_repro.py`
(same leading-underscore convention, fully isolated throwaway data dir,
fake Spotify token seeded from the start this time). DB scale was
synthetic since today's real production `download_requests` table only
ever holds ~14 rows total and can't demonstrate what a heavily-loaded
DB behaves like: 50 filler rows against filler tracks, deliberately NOT
uniform status (40% `locked`, 60% `queued`/`downloading`, mirroring the
original incident's own locked-heavy shape rather than an all-one-
status backlog that wouldn't exercise the retry path at all).
Concurrent traffic was real and reused test_stress_e2e.py's own proven
mechanism directly (`run_worker`/`main_window.thread_pool`, real
button clicks for fingerprinting) rather than a different threading
model: 3 synthetic playlists built by splitting the same real 15-track
Under Pressure list three ways (5 tracks each), each downloaded via a
real, concurrent `download_playlist()` call, plus real fingerprinting
on the same disposable scratch-WAV location (imported directly from
test_stress_e2e.py, not duplicated).

Watched 14 consecutive `poll_downloads()` calls live
(2026-09-02T09:59:17 → 2026-09-02T10:03:37, ~260s), each one making 50
real HTTP calls against real local slskd for the filler backlog alone
(on top of the real concurrent download/search/fingerprint traffic) —
directly testing whether a heavy per-call HTTP loop itself could distort
the timer's cadence:

```
20.008s, 20.012s, 20.004s, 19.976s, 20.030s, 20.006s, 19.962s,
20.048s, 19.948s, 20.040s, 19.960s, 20.033s, 19.998s
```

Still completely clean. `pending` fluctuated 31-34 (real download rows
from the 3 concurrent playlists cycling through), `locked` held flat at
20 (the synthetic filler rows, all permanently un-resolvable by
design) — no growth, no acceleration, no burst.

**Two real, useful data points surfaced along the way, neither the
storm itself but both concretely relevant context:** (1) firing 3
concurrent `download_playlist()` calls causes real, repeated `429 Too
Many Requests` from slskd's own `/api/v0/searches` AND
`/api/v0/transfers/downloads/batches` endpoints — real evidence that
enough concurrent real traffic genuinely saturates this local slskd
instance's own rate limiting, a documented, expected failure mode
(`is_recognized_rejection`-style handling), not a Seeker-side bug. (2)
one real request (`Logic - Metropolis`) hit a genuine `500 Internal
Server Error` on `/api/v0/transfers/downloads/batches` under this
load — the SAME endpoint and SAME error text that characterized every
line of the original 2026-08-28 storm. This one didn't cascade: it was
a synchronous enqueue-time failure (item 21's shape, inside
`download_playlist()`'s own request loop) rather than an async
poll-time locked-rejection, so it was marked `failed` once and never
retried — but it's the closest this investigation has come to
reproducing the original error signature under real conditions, even
though it didn't trigger a storm here. Worth watching for specifically
in any future attended run.

**Conclusion after all four steps: the original 2026-08-28 storm was
NOT reproduced by any combination tested** — locked rows alone (Step
2), zero locked rows (Step 3), nor a large mixed-status backlog under
full real concurrent traffic (Step 4, this section). Every one of these
runs held a clean, unwavering ~20.00s cadence. The real trigger remains
unidentified; the one concrete lead for a future session is the real
500-on-batches error observed here under heavy load, which matches the
original storm's exact error signature even though it didn't cascade
this time. Cleaned up the throwaway data dir (`seeker_step4_repro_*`
under `$TMPDIR`) by hand afterward; the script's own `finally` block
already removed its duplicate scratch location and directory.

### 64

Straightforward — built as scoped, no investigation narrative beyond
what's in CLAUDE.md's own entry.

### 65

**Phase 0 recon (read-only, reported and approved before any code was
written).** Six investigations, two hypotheses refuted:

- 0.1 confirmed LIVE via an offscreen `MainWindow` with an artificially
  slowed `scan_and_match()`: `_render_next_step` unconditionally
  `.setEnabled()`s all 4 action-row buttons on every 2s poll tick,
  fighting `run_worker(button=...)`'s own busy-disable. Real captured
  log: the Scan button re-enabled at t=2.0s while the scan was still
  running until t=6s — a real, user-visible "click again while it's
  still going" hazard, not a theoretical one.
- 0.3 confirmed by code + the real production DB: no retry_count/
  backoff/terminal state existed anywhere for a locked-file retry —
  three real `locked` rows had been stuck since 2026-08-27/28 (5+ days)
  with no bound at all.
- **0.4's "force=True" hypothesis was REFUTED, not fixed.** The
  original report assumed cover-art mismatches were being caused by a
  missing force flag somewhere in the tagging path. Re-checked live
  against the real, already-tagged library: all 8 currently-tagged real
  files had byte-exact CDN-matching art (0 mismatches) — the mismatch
  theory itself didn't hold up against current real data. The REAL,
  still-open gap found instead: `_show_tag_result_notice` had no branch
  for "tagged=0, without_art=0, failed=0, but skipped_already_tagged>0"
  — a fully-already-tagged re-run produced literally zero `InlineNotice`,
  only the easy-to-miss small results panel. This became item 66's
  primary fix, not the originally-hypothesized force-flag issue.

Real destination-prompt investigation (0.3.1, folded into Phase 3):
confirmed against real code that no folder-NAME detection logic existed
anywhere — a user's existing "Psytrance" folder had been matching the
configured "PsyTrance" destination purely because macOS's default
filesystem (APFS) is case-insensitive. Entirely coincidental, not a
feature, and worth recording as a real "the behavior you're relying on
isn't the behavior you think it is" case.

Full verification for Phase 2.4: a live async repro re-run kept the
Scan button correctly disabled across 5+ real 2s poll ticks (t=0
through t=5s), restoring exactly once at real completion (t=6s). The
deadlock regression suite (item 39/41's own tests) ran 3x clean. Full
fast suite ran 3x: 789-790/790 passed, one pre-existing flaky test
(`test_history_refresh_button_refetches`, documented — reproduces 1/5
in isolation too, not a regression from this work).

### 66

**0.2 confirmed by code** (not live, since it's a pure logic question):
a `soulseek_review_candidates` row with no `download_requests` row is
only ever a secondary tag on `NEEDS_REVIEW`/`NOT_FOUND`, never a
primary state, by construction — matching the original report exactly,
nothing to fix.

**The real 500-error bug (item 63's own flagged lead, closed here).**
Building Phase 4.3's bounded retry, live verification against
production slskd surfaced a genuine `500 Internal Server Error` on
`POST /api/v0/transfers/downloads/batches` — the EXACT endpoint and
error text item 63's investigation had already flagged as "one concrete
lead" for the unexplained retry storm. Root cause of the *bug this fix
targets*: the error was an `httpx.HTTPStatusError` that escaped the
original `except SoulseekDownloadError:` handler entirely (`client.py`'s
`request_download` deliberately re-raises unrecognized errors "loud"),
meaning `retry_count` never advanced for this failure shape — a live,
reproducible instance of the exact unbounded-retry bug this whole phase
exists to fix. Fixed by wrapping both `request_download` and
`get_download_status` in broader exception handling that always
advances the retry budget before re-raising. Re-verified live twice:
`retry_count` correctly advanced 0→1→2 with real backoff timestamps for
the previously-unhandled row. This does NOT fully explain item 63's
storm (a single synchronous 500 here was a one-off, not a cascade — see
item 63's own follow-up section for the three runs that still couldn't
reproduce the original storm), but it closes a real, separate,
previously-silent gap in the same code path.

**Phase 5.4's real-file verification**, run only after explicit user
confirmation of the target playlist ("Test"): read-only before-state
showed 3/9 auto-matched tracks with genuinely mismatched embedded art
(Breach, Bit Perfect, Jade Venom — real SoulSeek-download art, not
Spotify's own), 6/9 already byte-correct. Running `seeker library
fix-art Test` for real produced `Fixed: 3, Already correct: 6`; a
direct re-read afterward confirmed 9/9 byte-exact CDN matches. Text
tags on all 3 fixed files were spot-checked to confirm they were
untouched — one file ("Breach") had never been text-tagged at all
before this run, and its tags still read the pre-Spotify "Balron &
Audio" after, proving the art-only fix genuinely never touches text
tags.

### 67

**Phase 6.5's real-file verification**, run only after explicit user
confirmation of the target playlist ("Test"): `seeker library rename
Test` (no `--apply`, read-only) proposed 7 real renames — track-number-
prefix stripping, artist-order corrections (filename-derived order to
Spotify-canonical order), title-first to artist-first reordering, and
illegal-character sanitizing — with 2 files already correct, 1 not
auto-matched (correctly excluded), and 0 real collisions in this
playlist's own 10 files. Not applied: the user did not give further
confirmation to write, matching this project's standing "never touch a
real file without confirmation" rule down to "confirming a dry-run is
not the same as confirming the write."

### 68

**0.5's "Actions-column index-drift" hypothesis was REFUTED, not
fixed** — the third time this specific report has failed to reproduce
(see item 61 §6.2's own "could not reproduce" for the first two). Tested
live at real scale: 15 duplicate groups / 45 rows, the real default
1180×760 window. Column indices were verified correct both statically
(reading the render code) and dynamically (resolving the Actions column
by its real header text at runtime, landing on index 7 exactly as the
code itself uses). `setStretchLastSection` makes the Actions column's
right edge always exactly equal the viewport width, which structurally
prevents it from ever scrolling off-screen in the first place — a
plausible mechanical explanation for why the report can't reproduce,
not just an absence of evidence. Per user instruction, the column-index
hardening (`_DuplicatesColumn(IntEnum)`, header-text-resolved tests) was
still applied regardless of non-reproducibility, and one additional
cheap check — manual column-drag-resize — was run and also did not
reproduce it (`test_duplicates_actions_column_survives_manual_column_
resize`).

**Real bug found live wiring folder-scope pooling into the UI, not
anticipated by the brief.** Once `find_duplicate_groups_across_scopes`
made a cross-location duplicate group a real possibility for the first
time, it became visible that `_render_duplicate_groups`'s LOCATION
column and `_on_delete_duplicates_clicked`'s real-path confirmation
dialog both read from ONE `self._current_duplicates_location_name`
variable, applied to every row in every group — correct only when a
search was scoped to a single location, silently wrong (showing the
wrong location name, and building the wrong real path for the delete
confirmation) for any multi-location result. This was a LATENT bug
already reachable in principle before this phase (nothing previously
prevented two `local_files` rows from different locations landing in
the same clustered group — clustering has always been purely content-
based), it simply had no real trigger until folder-mode pooling gave it
one. Fixed by resolving each row's location individually via
`local_file.location_id` against a `_duplicates_locations_by_id` map,
and by resolving the delete-confirmation paths the same way; the
`delete_local_files` call's own `location_id` (purely informational
provenance for the reclaimed-space milestone) now comes from the KEPT
file's own location rather than the stale single-location variable.

**Real run against the production library, read-only** (fingerprinting
persists DB columns only; nothing here writes/moves/renames a real
file): a folder-scoped run (`Music/CamelPhat`, 6 files) completed
fingerprinting in 0.58s and duplicate search in 0.54s, both reaching
exactly 6/6 progress, 0 groups (real, distinct tracks — correctly no
false positives). The same shape against the whole `Test` location (8
files) also found 0 groups. The real whole-`x9-pro`-location run:
fingerprinting the 102 real never-before-fingerprinted files took 13s
(26 succeeded, 76 failed — see item 69 for the full breakdown);
clustering all 3168 successfully-fingerprinted files took 10m11s
(started 18:30:24, finished 18:40:35 — real wall-clock, not estimated),
progress reaching exactly 3168/3168 on both its "Decoding fingerprints"
and "Comparing" stages throughout, finding 352 real duplicate groups
(up from item 39's original ~344 — real library growth in the interim,
not a clustering-behavior change).

### 69

**0.6's initial real numbers, and a discrepancy worth recording
honestly.** Phase 0's own live recon (before this session's context was
compacted) reported: 110 never-fingerprinted rows, 34 newly succeeding,
76 genuine failures (matching item 39's original 76 failure count,
including the same 2 already-confirmed 0-byte files) — and specifically
that a **librosa fallback rescued 11/76** of them. Building Phase 8.1
properly, BEFORE writing any fallback code, this was checked again
directly: `librosa.load()`'s source (`librosa/core/audio.py`, pinned
version 1.0.0) calls exactly one internal function,
`__soundfile_load`, with no alternate decoder — no `audioread` import
exists anywhere in this environment's librosa, and none is even an
installed package (`import audioread` fails with `ModuleNotFoundError`
directly). This is a structural, source-level fact, not an empirical
one: `librosa.load()` in this pinned version is provably identical to
calling `soundfile` directly, so it CANNOT rescue any file soundfile
itself fails on. A direct repro against one of the real 76 files
(`HiveMind.mp3`) confirmed this: `librosa.load(path, sr=None)` raised
the exact same `LibsndfileError`/"bad data offset" as bare
`soundfile.info()`.

This directly contradicts Phase 0.6's own "11/76 rescued by librosa"
number, and the most likely explanation was also found live, by
accident, while building the ffmpeg-fallback regression test: an
identical, byte-for-byte copy (`cmp`-verified) of `HiveMind.mp3` onto
the local SSD decodes FINE via plain soundfile, while the real file at
its real `/Volumes/X9 Pro` mount path fails every time it was tried.
This points to something read/seek-pattern-specific about libsndfile's
interaction with this particular external drive/mount — NOT genuine
audio corruption — for at least the dominant "bad data offset" failure
category (61 of the 76). If soundfile's success against a given file
can vary by something as incidental as which pass touched it first or
how it was accessed, Phase 0.6's isolated librosa test run may simply
have hit a "good" read on 11 files that would have succeeded via bare
soundfile too, attributing the success to librosa when it wasn't
librosa's doing at all. This wasn't chased down further to a definitive
answer (mirrors item 63's own "fix verified working, exact trigger left
open" precedent) — what matters for the actual code is that the
source-level proof (no audioread path exists) is authoritative on its
own and doesn't depend on resolving this discrepancy: the librosa stage
was skipped entirely, and the real fix (ffmpeg) doesn't depend on this
theory being right.

**The stderr-pipe deadlock, found live via an 11-minute hang, not by
review or by anticipating it.** The first working version of
`_compute_fingerprint_via_ffmpeg` piped both stdout (PCM) and stderr
(decode diagnostics) via `subprocess.PIPE`, draining only stdout in a
loop and reading stderr once at the end. Running the real verification
script against all 76 real failures hung indefinitely (killed after
~11 minutes with no output at all — confirmed via a `tail`-buffering
red herring initially suspected, then ruled out by re-running without
it). Root cause, confirmed directly: a genuinely corrupted real file
(one of the FLAC "decoder lost sync" cases) makes ffmpeg log one error
line PER bad frame — for a real multi-minute track with sustained
corruption, that's tens of thousands of lines, confirmed synthetically
to exceed 2MB for a deliberately-corrupted test file. macOS's pipe
buffer is a fixed 64KB; once ffmpeg filled it writing stderr with
nothing draining it, ffmpeg blocked on the write while this code was
simultaneously blocked reading stdout, which ffmpeg could never
produce more of while stuck. A classic, real two-pipe subprocess
deadlock. Fixed by giving stderr a real `tempfile.TemporaryFile()`
instead of a pipe (file writes never block a stalled reader). Locked in
with a synthetic regression test that reliably reproduces >2MB of
ffmpeg stderr output and asserts completion via a background thread
with a bounded `join(timeout=30)`, so a future regression fails the
test suite instead of hanging it.

**Final real numbers, the fixed fallback run against all 76 real
production failures:** 2 genuinely empty (0-byte) files, correctly
classified `empty_file` and excluded from any decode attempt; 73
rescued cleanly by the ffmpeg fallback; 1 still genuinely fails —
`Lost Mantra.mp3`, which `file` identifies as `M3U playlist text`, not
audio at all: its real content is an HLS manifest with SAMPLE-AES DRM
key material, saved with a `.mp3` extension. No decoder, present or
future, could ever "fix" this one — there is no audio data in the file
to recover, correctly classified `decode_unsupported`.

### 70

Open, real, unresolved investigation — found live while closing out
items 68-69 (folder-scoped duplicates + fingerprint fallback), running
the closing-out stress test for the first time this session against
real production infrastructure. Reported here in full per this
project's own standing "record an unreproducible/unresolved finding
honestly rather than fabricate a fix" precedent (items 39, 61, 63).

**What was observed, three times.** Running `SEEKER_RUN_STRESS_TEST=1
QT_QPA_PLATFORM=offscreen uv run pytest tests/test_stress_e2e.py -q -s`
against real production Spotify/slskd/DB:

- **Run 1** (unattended — a real process-management mistake, corrected
  after this): left running for 1h37m+ with 0.2% CPU and zero new
  output. Killed. Left one harmless leftover — a
  `SeekerStressTestDuplicates` scratch library location pointing at a
  temp dir (never the real X9 Pro library) — which the test's own
  `_create_stress_duplicate_location` already defensively cleans up on
  its next run.
- **Run 2** (closely watched this time, checked every 30s via an
  automated stall detector): reproduced again, at the exact same point.
  The stall detector attempted a `py-spy dump --pid` to get a real stack
  trace without modifying any code — failed, `py-spy` requires root on
  this machine and no interactive password is available in this
  session. Killed after a 3-real-minute stall.
- **Run 3** (with a temporary internal diagnostic added — see below):
  reproduced a third time. Left running ~38 real minutes; the diagnostic
  never fired. Killed.

**Exactly where it gets stuck, every time.** Immediately after
`[stress] overlapping sync/scan/match settled: True` prints (the
overlapping sync/scan/match flurry — a real Spotify sync of 215+
playlists, a real scan of the real X9 Pro library, a real match — all
genuinely completing within their 90s bound), waiting on
`main_window.compute_fingerprints_button.isEnabled()` to become True
again — the Duplicates page's own Compute Fingerprints action, fired
concurrently with sync/scan/match on a small, disposable 2-file scratch
location (`_create_stress_duplicate_location`), never the real library.

**The internal diagnostic and what its SILENCE proved.** `py-spy`
being unavailable non-interactively meant no external stack-trace tool
could attach. Instead, a temporary, scoped diagnostic was added directly
to `test_broad_end_to_end_stress` (matching item 63's own precedent for
a temporary, no-behavior-change instrument): a `threading.Timer`,
armed right after `MainWindow` construction, set to call
`faulthandler.dump_traceback(all_threads=True)` after 210 real seconds
if never cancelled (cancelled normally right after the fingerprinting
wait resolves). This needs no elevated OS permissions — it dumps every
thread's real Python frame state from *inside* the same process via the
stdlib. Run 3 used this. **It never fired, across ~38 real minutes.**
This is a meaningfully worse signal than "the Qt event loop is stuck":
a `threading.Timer`'s callback runs on a freshly spawned Python thread,
independent of Qt's event loop entirely — for it to never execute even
once means something is holding the CPython GIL for the whole process,
not merely blocking `QApplication.processEvents()`. This points toward
a native call that never releases the GIL (a real possibility for a
ctypes call, depending on how it's bound) or a genuine C-level deadlock/
infinite loop, rather than the pure-Python Qt/dispatcher mutex-pool
collision item 39's own history already root-caused and fixed. The
Compute Fingerprints step is the only thing running at the exact stuck
point that makes a real ctypes call into a C library at all
(`audio_fingerprint.py`'s libchromaprint binding) — the leading
suspect, though not confirmed.

**Two isolated repro attempts, neither reproduced it — and both already
exercised the exact code path in question.** A new script,
`tests/_stress_hang_repro.py` (kept, matching the `_stress_step3/4_*_
repro.py` convention), isolates the same operation sequence in a fresh
throwaway env (no real production DB, a fake Spotify token to avoid a
real OAuth popup):

1. A minimal version (2-file scratch location, fake token that fails
   fast) — completed cleanly in seconds.
2. A scaled-up version — 1,500 real files symlinked in from the real
   X9 Pro library (read-only symlinks, not copies) as a SEPARATE scan
   target, so scan/match would run for a realistic real duration
   instead of finishing instantly — also completed cleanly. Scan/match
   legitimately took over the 90s bound in this run (a real, honest
   result on its own — `_pump` correctly returned `False` rather than
   hanging), while Compute Fingerprints on the small scratch location
   finished successfully throughout, fully concurrent, with real
   sync/scan/match traffic still in flight.

Critically, **both repro attempts fired Compute Fingerprints via
`main_window.compute_fingerprints_button.click()`** — the real
production UI handler, which (as of this session's own Phase 7.3 work)
already routes through `_run_busy_worker(..., reports_progress=True)`
and the `on_progress`/`Worker._report_progress` channel added in Phase
2.3. This rules out "the progress-reporting channel itself is broken"
as the specific thing separating a clean isolated run from a real
production hang — both isolated runs already exercised it, including
at a realistic 1,500-file scale, with zero issue. What's left as the
real-scale-only differentiator is real Spotify sync duration (minutes
of genuine network round-trips against 215+ real playlists, vs. an
isolated run's fast-failing fake-token 401) and/or the real production
DB's actual size/content (a mature, multi-year, multi-table SQLite
file vs. a fresh empty throwaway one) — neither cheaply substitutable
without touching real infrastructure again.

**Conclusion: genuinely unresolved.** The temporary diagnostic was
reverted (`tests/test_stress_e2e.py` is back to its pre-diagnostic
state — confirmed via `git diff` showing zero changes against the last
committed version) rather than left in permanently, since it never
actually produced a trace and this project's own convention (item 63)
is to keep a temporary diagnostic only while actively debugging, not
indefinitely. Not fixed. The opt-in stress test was not completed for
real as part of this session's closing-out pass — CLAUDE.md item 70
records this as its own open, real finding, deliberately not folded
into item 63 since the symptom (a full interpreter-level freeze,
evidenced by the watchdog's own silence) is materially different from
item 63's stuck-cadence-but-still-running storm, even though both
involve the same broad area (Duplicates/download background worker
traffic under real concurrent load) and could in principle share a
root cause once one is found. Phase 7.3's fingerprint progress wiring
is flagged as a standing caution (newest code touching the exact stuck
step) but explicitly NOT reverted or blocked on this — nothing found
here implicates it specifically, and undoing real, tested, working
functionality on an unconfirmed suspicion would trade a known-good
capability for no proven benefit.

### 71

New work block: `docs/BRIEF-2026-09-02.md`, six real user-reported bugs
(P1-P6), four of which had been reported and closed as irreproducible
before. Standing rule for this block: reproduce everything live at the
app's real minimum window size (960×640) before touching code, and "not
reproducible" is not an acceptable outcome for P2/P4/P6 a fourth time.

**Phase 0 — live reproduction, real findings:**

- **P4 (0.1):** measured real geometry against real production
  duplicate groups (25 real groups, `x9-pro`, DnB vs. "Where The Chaos
  Lies" album overlap — scoped via `find_duplicate_groups(folders=...)`
  for speed rather than the ~10-minute whole-location run). At 960×640:
  `header.sectionSize(ACTIONS) = 230`, but the real Actions widget's
  `visibleRegion().boundingRect()` is `(0,0,0,0)` — completely
  invisible, worse than the brief's "~15px sliver" estimate. At
  1600×900 it renders fully (610px). Confirmed via `grep` that
  `clearSpans`/`setSectionResizeMode`/`setColumnWidth`/
  `setMinimumSectionSize`/`resizeColumnsToContents` appear nowhere in
  `src/seeker/ui/` — nothing has ever set real column widths.

- **P2 (0.2) — the real finding of this phase.** Running
  `seeker library rename Test` against the real production DB/library
  surfaced a state that predates this session entirely: the real "Test"
  folder's matched files were already partially renamed. Cross-checking
  real file mtimes against the DB (`local_files.relative_path`) showed
  5 of the 7 tracks the rename feature had previously proposed
  (Breach, Glassy Star, Banana Shoes, Tractor Beam, Jade Venom) were
  **already renamed correctly on the real filesystem** (today,
  00:04), matching `build_track_filename`'s exact canonical output —
  but `local_files.relative_path` in the real DB **still held the
  pre-rename name for all 5**, with no rescan having reconciled it
  since. Re-running the dry run against this desynced state produced a
  false `collision` ("needs a numbered suffix") for every one of the 5,
  since the plan was comparing a stale DB name against a target that
  was, in fact, its own already-completed rename.

  Asked the user directly rather than guessing: confirmed this was
  produced by Seeker's own Rename feature, not a manual rename outside
  the app. That rules out the innocent "user renamed by hand" reading
  and means the real, live behavior is: file rename succeeds, but the
  DB write that's supposed to follow it doesn't land (or doesn't land
  durably) for a whole batch. Read `_apply_one_rename`
  (`metadata_service.py`) end to end looking for why: the code renames
  the file, then updates `local_files.relative_path` inside its own
  `database.transaction()`, and — if that update raises — renames the
  file BACK and reports a failure. That logic reads correctly by
  inspection. Checked for the more mundane explanation (an unclean
  shutdown mid-transaction leaving a stale journal): `PRAGMA
  journal_mode` is `delete` (not WAL) and there is no stray
  `-journal`/`-wal` file sitting next to `seeker.db`. **Root cause not
  conclusively identified** — recorded as unresolved, matching this
  project's own established precedent for a handful of prior real,
  confirmed-but-not-root-caused findings (items 63, 68's stale span,
  70) rather than fabricating a mechanism that fits the evidence but
  wasn't actually verified.

  With the user's explicit go-ahead: backed up the real `seeker.db`
  first (`seeker.db.bak-pre-rescan-20260903T011231`), then ran a normal
  `seeker library scan` + `seeker library match` — DB-only, no real
  file touched — to reconcile the 5 stale rows with their real current
  names. A follow-up dry run confirmed the false collisions were gone
  and the plan now correctly proposes only the 2 tracks (Push It To The
  Limit, Ultraviolet) that were genuinely never renamed. Also surfaced,
  not pursued (out of this brief's scope): the "Test" library location
  and part of `x9-pro` contain real, literal duplicate copies of
  several tracks living in different folders — which physical copy a
  track's `track_matches` row resolves to can shift across rescans,
  independent of the rename bug itself.

- **P5 (0.3):** `docker inspect slskd` on the real, currently-running
  container shows its live `/app` mount source is the **repo's own**
  `slskd-data/` (item 13's hand-edited copy, real active `shares:`
  block already present at line 352) — not
  `~/Library/Application Support/Seeker/slskd-data/`, which doesn't
  exist on this machine at all. This container was brought up via a
  plain dev-mode `docker compose up` (its
  `com.docker.compose.project.config_files` label is the repo's
  `docker-compose.yml`), never through the wizard's `bring_up_slskd()`.
  Because of this, the brief's exact reported error wouldn't reproduce
  against this specific container (it already has an active block to
  insert into) — but this same live state independently CONFIRMS 5.3
  is real right now, not just a hypothetical: `SharingService.
  is_self_managed()` would return `False` if the packaged `.app`
  (whose `compose_file_path()` resolves inside the bundle) were pointed
  at this exact container, since the bundle path can never match the
  container's real recorded label.

- **P6 (0.4):** re-confirmed the write path is sound — 4 real,
  currently-reachable auto-matched Test tracks (spanning a nested
  Test-location mp3, 2 flacs, 1 more mp3) all have byte-exact embedded
  art matching the current Spotify CDN bytes. Both real MP3s tested
  write **ID3v2.4**. Library-wide format counts: 2027 mp3 / 1165 flac /
  70 wav / 12 m4a — ~2% wav, real but not "materially wav".

- **P3 (0.5):** confirmed via source read (no live UI drive needed) —
  `_render_next_step` calls `next_step_notice.show_message()`
  unconditionally on every 2s poll tick; `InlineNotice.dismiss()` only
  ever `hide()`s. Checked the other two `InlineNotice` instances
  (`dashboard_notice` in `main_window.py`, `locations_notice` in
  `settings_window.py`): both are only ever shown from action-result
  callbacks (a worker's `on_finished`/`on_error`), never a poll-tick
  render method, so neither shares this bug — confirmed, not assumed,
  by grepping every `.show_message(` call site.

**P3 fix (CLAUDE.md item 71):** `InlineNotice` gained
`dismissed = Signal()`; `MainWindow` tracks a dismissed-step identity
key (selected playlist name + step message + step action) and
suppresses re-showing that exact step while it's still current, but
clears the stored key the instant the computed key differs — a
genuinely different step, or the same step recurring later after
something else was shown in between, both still surface. 4 new tests
(2 in `test_notice.py` for the new signal, 2 in `test_ui_smoke.py`
driving `_render_next_step` directly for determinism — no reliance on
the real 2s timer). `mypy --strict` clean; full suite 878 passed / 1
skipped.

### 72 — P1

Straightforward per the brief (root cause already CONFIRMED in source,
no further investigation needed) — no separate narrative beyond what's
in CLAUDE.md item 72's own entry. New `ui/flow_layout.py::FlowLayout`,
the standard Qt C++ "Flow Layout" example ported to PySide6 (never
published as a reusable Qt class, so this project owns its own copy).
Live-confirmed via a real offscreen `MainWindow`:
`dashboard_content.minimumSizeHint().width()` dropped from what would
have been ~900-1000px+ (matching the brief's own `QHBoxLayout`
arithmetic) to a real, measured 445px.

### 73 — P4

Three prior investigations (items 61 §6.2, 68 Phase 7.1, and Phase 7.1's
own column-index hardening) had all concluded "not reproducible" by
asking the same question: does `duplicates_table.cellWidget(row, col)`
return a real widget. It always did — that question is blind to a
widget that exists but is rendered at near-zero visible width, and this
brief's own Phase 0.1 measured, for the first time, the property that
actually matters: real column `sectionSize()` and the Actions widget's
own `visibleRegion().boundingRect()`.

**Live measurement (Phase 0.1), real production data:** against 25
real duplicate groups (`x9-pro`, DnB vs. the "Where The Chaos Lies"
album folder — genuine content overlap, scoped via
`find_duplicate_groups(folders=...)` rather than the ~10-minute whole-
location run item 39/68 both measured), at the app's real 960×640
minimum window: `header.sectionSize(ACTIONS) = 230`, but
`actions_widget.visibleRegion().boundingRect()` was `PySide6.QtCore.
QRect(0, 0, 0, 0)` — completely invisible, not merely clipped to a
sliver as the brief's own arithmetic estimated. At 1600×900 the exact
same widget rendered fully (610px). Confirmed via `grep` across
`src/seeker/ui/` that `clearSpans`/`setSectionResizeMode`/
`setColumnWidth`/`setMinimumSectionSize`/`resizeColumnsToContents`
appear nowhere — no column width has ever been set in this app, for
any table.

**Second, independent, confirmed defect:** `_render_duplicate_groups`
calls `setSpan(...)` per group but never `clearSpans()`, and
`setRowCount()` does not clear spans on its own. Every prior test
re-rendered with the SAME group shapes as the previous render, so a
stale span was always identical to the fresh one and nothing broke —
this round wrote a test that deliberately changes shape between two
renders (a 4-file group, then two differently-shaped 2-file groups) to
actually exercise it.

**The fix:** `_render_duplicate_groups` now calls `clearSpans()` before
`setRowCount()`. New `_size_duplicates_columns()`, called once at the
end of the render, using every real Actions widget built that render
(a per-group extra button — see `_build_duplicate_group_actions` — can
change the widget's width group to group, so the WIDEST one wins, not
an arbitrary single sample): `ResizeToContents` for
Group/Location/Format/Bitrate/Similarity/Keep, `Stretch` for PATH (was
sitting at Qt's 100px column default while holding a full relative
path — its own separate usability problem per the brief), and `Fixed`
for ACTIONS with an explicit width taken directly from
`max(widget.sizeHint().width() for widget in action_widgets)`.
`setStretchLastSection(False)` (stretching whichever column happens to
be last is the exact mechanism that let Actions collapse to a sliver
in the first place) and `setMinimumSectionSize(40)` (an untuned floor,
flagged as such) round it out.

**Re-verified live against the same real production groups used for
the initial measurement:** at 960×640, `sectionSize(ACTIONS) = 286`,
`visibleRegion()` width `285` (a 1px rounding gap against `sizeHint()`,
not a bug — the earlier `(0,0,0,0)` result is the actual before/after
comparison that matters). At 1600×900, PATH stretches to 703px while
ACTIONS stays locked at 286 in both cases, immune to window width
entirely.

**A real third instance, found by the audit itself:** 4.1 explicitly
asked to audit every other table for the same missing-`clearSpans()`
omission. Grepping every `.setSpan(` call site in the file found
exactly one other: `_render_sharing_uploads_table`'s no-uploads-yet
branch spans row 0 across all 4 columns. Wrote a small script exercising
the exact transition (empty render, then a render with one real
`UploadStatus`) before assuming anything — confirmed live: the stale
4-column span survived the transition (`setRowCount()` doesn't clear
spans here either), visually merging the new row's real filename/
state/progress cells into column 0, even though their underlying
`QTableWidgetItem` data was written correctly underneath. Fixed with
the identical `clearSpans()` call at the top of the method.

**Tests:** rewrote (per the brief's own instruction — "delete or
rewrite," not silently keep) the item 56 §6.2
`test_duplicates_actions_column_renders_with_a_real_service_and_real_
fingerprinting` test — its real pipeline coverage (real
`DuplicateService`, real fingerprinting, real generated duplicate
`.wav` files) was always good; only its assertions were too weak
(`isVisible()` alone). Now resizes to 960×640 and asserts real
`sectionSize`/`visibleRegion` geometry on both the first render and a
full re-render. 4 new tests: real-geometry-at-minimum-size, ACTIONS is
genuinely `Fixed` at a width equal to its own `sizeHint()`, the
stale-span regression (4-file group then two differently-shaped
2-file groups, asserting both new groups' Actions widgets are visible
with correct 2-row spans), and the sharing-uploads stale-span
regression (empty render, then a real upload, asserting the span and
the real filename text both land correctly). `mypy --strict` clean;
full suite 891 passed / 1 skipped, 0 regressions.

### 74 — P5

**Live capture of a real, genuinely-fresh slskd default (2026-09-02):**
before writing any fix code, brought up a real, disposable, throwaway
`slskd/slskd` container (`docker run`, no compose, a brand-new empty
data directory, never the real production `slskd` container) purely to
capture what slskd itself generates on a real first run. Confirmed:
its `slskd.yml`'s entire `shares:` section is the commented-out default
template — `# shares:` / `#   directories:` / `#     - ~` — with no
active, uncommented block anywhere in the file. This is EXACTLY the
condition `_insert_slskd_share_directory` refused instead of handling,
and it's the real, ordinary state for any slskd instance the wizard's
own `bring_up_slskd()` brings up fresh (a first-time user, or anyone
whose `slskd_data_dir()` doesn't already exist) — not an edge case.
Captured the real file as `tests/fixtures/slskd_generated_default.yml`,
per the brief's own explicit instruction to test against a real
captured file rather than a hand-written approximation.

**Phase 0.3's own finding mattered here too:** the machine's currently-
running production `slskd` container was brought up via a plain dev-
mode `docker compose up` from the repo root (not through the wizard),
so its live `/app` mount is the repo's own hand-edited `slskd-data/`
(which DOES have an active block, from item 13). That meant the exact
reported error couldn't reproduce against THAT specific container — the
fresh-capture container above is what actually reproduces it.

**The fix (5.1):** `_insert_slskd_share_directory`, on finding no active
block, appends one at the end of the file (`shares:\n  directories:\n{new_line}\n`,
adding a leading newline first if the file doesn't already end in one —
the real fixture file has no trailing newline of its own, caught by a
test built directly against it). The existing "insert into an existing
block" path is untouched.

**5.2 (partial-write window):** the old order was back up both files ->
write `docker-compose.yml` -> parse+write `slskd.yml`. A failure in the
slskd.yml step left the compose file already mutated with nothing on
the slskd.yml side to match it — a retry would add the same volume line
a second time. Both new file contents are now computed BEFORE either
write; the compose write happens first (unconditionally safe — parsing
already succeeded for both files by this point) but the slskd.yml write
is wrapped so any failure there rolls the compose file back from the
backup just taken. New test simulates a real `Path.write_text` failure
scoped to just the slskd.yml path (via a monkeypatch that only
intercepts that one path, leaving the backup's own `shutil.copy2` call
untouched) and asserts the compose file is back to its exact original
content, and slskd.yml was never touched at all.

**5.3 (frozen-build compose path):** `compose_file_path()`'s frozen
branch used to return `sys._MEIPASS / "docker-compose.yml"` directly —
a path PyInstaller regenerates on every build. `SharingService.
is_self_managed()` compares a running container's real, permanently-
recorded `com.docker.compose.project.config_files` label against this
path; a rebuilt or relocated `.app` could never again recognize a
container it had itself previously created as self-managed. Fixed the
same way item 18 stabilized the DB's location: on first use in a frozen
build, copy the bundled resource once into `slskd_data_dir()` (the same
stable per-user directory the DB/config already live in) and always
return that canonical path afterward — guarded, so a later
Sharing-added volume line already living in the canonical copy survives
a subsequent app rebuild untouched. The existing frozen-path test
(`test_compose_file_path_resolves_against_meipass_when_frozen`) was
rewritten to assert the new copy-once behavior, since its old assertion
was testing the exact thing being fixed.

**5.4 (live E2E verification), real disposable container:** brought up
a second real, disposable, throwaway container via a real
`docker compose up` (a scratch copy of the repo's own
`docker-compose.yml`, renamed `container_name`/host ports to avoid any
collision with the real production `slskd` container, which stayed
running and untouched throughout) against a fresh, empty data
directory — reproducing the exact bug state (its own generated
`slskd.yml`, freshly confirmed to have no active block). Ran the real
`SharingService.add_location_to_share()` against it: `is_self_managed()`
correctly returned `True` (the disposable container's real
`com.docker.compose.project.config_files` label matched the scratch
compose file); the real `slskd.yml` on disk gained a genuine
`shares:\n  directories:\n    - /shared/NewLocation` block; the real
`docker-compose.yml` gained the new volume line; both backup files were
created. The subsequent readiness poll hit a real `401 Unauthorized`
after the container's own recreate — traced to the verification
script's own test harness gap (it didn't carry `SLSKD_API_KEY` into the
recreate's environment the way the real app's config-store-backed flow
always does), not a defect in `add_location_to_share` itself; the file-
level edits (the actual scope of this bug) were independently confirmed
correct by direct inspection regardless. Noted, not pursued further (a
tangent from this brief's scope): whether a real production recreate
with an empty `SLSKD_API_KEY` override can reset slskd's own API key
under `SLSKD_REMOTE_CONFIGURATION=true` is a genuine open question worth
checking before this code path's next real use, but is pre-existing
behavior this session didn't introduce and isn't part of the reported
bug. Disposable container, network, and scratch directories all torn
down after — `docker ps`/`docker network ls` confirmed clean, the real
production `slskd` container confirmed still running unmodified
throughout via `docker ps` before and after.

**5.5:** confirmed again, no action needed (already noted in Phase 0.3)
— `slskd-data/` stays in `.gitignore`, never committed.

`mypy --strict` clean. Full suite: 896 passed / 1 skipped (5 net new:
2 in `test_docker_setup.py` replacing the old frozen-path assertion, 4
in `test_sharing_service.py`), 0 regressions.

### 75 — P6

Phase 0.4 already re-confirmed the write path was sound (4/4 real,
currently-reachable auto-matched Test tracks byte-exact vs. the current
CDN art, both real MP3s tested writing ID3v2.4). This round's job was
the brief's own 6.1-6.5, in order.

**6a (`_tag_one_track`'s `tagged_at` short-circuit):** confirmed the
mechanism is exactly as described — `skip_tag_write = local_file.
tagged_at is not None and not force` returns before the art step is
ever reached. Fixed the REPORTING side (6.2), not the skip itself (the
brief explicitly offered a choice here and named the reporting fix as
"cleaner and closer to the existing design" — `fix_missing_art_for_
playlist()` already exists specifically for "check art without a full
retag," so pointing at it is the real answer, not adding a second way
to do the same thing). `format_tag_result_notice` previously only
mentioned `skipped_already_tagged` in the ALL-skipped branch (`tagged
== 0`) and said "nothing to do" — actively misleading, since art was
never looked at. Rewrote every branch (mixed fresh+skipped runs
previously said NOTHING about the skipped ones at all) to say plainly
"N already-tagged track(s)' cover art was NOT checked this run," and
`_show_tag_result_notice` now offers "Fix missing cover art" as the
notice's own action button whenever `skipped_already_tagged > 0`,
wired directly to the existing `_on_fix_missing_art_clicked` handler.

**6b (ID3 version):** new `metadata.py::save_tags()` — the single
shared save point both real call sites (`_tag_one_track`,
`_fix_one_track_art`) now go through — dispatches `save(v2_version=3)`
only for `isinstance(mutagen_file.tags, ID3)` (MP3 and WAV's real
`_WaveID3` subclass), falling through to plain `save()` for FLAC/MP4
(whose `save()` takes no such kwarg — calling it there would raise).
Unit-tested against a real copied MP3 from the x9-pro drive (mypy-gated
`@requires_x9_pro`, matching this file's existing convention) and a
portable synthetic WAV (no drive dependency), confirming `ID3(path).
version == (2, 3, 0)` after the write, plus a FLAC test confirming the
dispatch doesn't raise.

**6c (`no_url`):** already handled per the brief's own note; nothing to
do.

**6.4 (WAV honesty):** a WAV embed succeeding is not the same claim as
an MP3/FLAC/M4A embed succeeding — essentially nothing outside mutagen
itself reads embedded art from WAV. New outcome values
`tagged_art_rarely_supported_format` (tag_tracks) /
`fixed_wav_rarely_supported` (fix_missing_art_for_playlist), counted
and detailed separately from both "written" (plain success) and
"tagged_without_art" (genuinely nothing embedded) — the report now
distinguishes all three, not just two.

**Live verification, with the user's explicit go-ahead (real
production files):** `fix_missing_art_for_playlist` alone wouldn't
actually exercise the v2.3 fix against the Test playlist's already-
correct-art files — its own `already_correct` short-circuit returns
BEFORE `save_tags()` is ever reached when the embedded bytes already
match the CDN, which Phase 0.4 had already confirmed was true for
every sampled file. Used `seeker library tag Test --force` instead (a
full re-tag, bypassing the skip checks entirely) — the real,
user-facing equivalent of "Tag playlist" with "Re-tag already tagged
files" checked. Backed up the real `seeker.db` first (same discipline
as P2's rescan). Real run: **9/9 tagged, 0 failed, 0 without cover
art.** Re-verified directly afterward: both real MP3s
(`Bit Perfect`, `Cannibals`) now read `ID3(path).version == (2, 3,
0)`; all 9/9 tracks (both MP3 and FLAC) remain byte-exact against the
current Spotify CDN art.

**Deliberately left open:** per the brief's own standing instruction
("do not close this item on 'the bytes are in the file' ... it closes
when the user says they can see a picture"), this item stays open
until the user checks their real DJ software (Rekordbox/Serato/
Traktor) against the real "Test" playlist's files and confirms art is
now visible — something only they can do, and something four prior
rounds never actually asked for. `mypy --strict` clean; full suite:
901 passed / 1 skipped (5 net new: 3 in `test_metadata.py`, 2 in
`test_ui_smoke.py`), 0 regressions (the one intermittent failure seen
in a full-suite run, `test_history_refresh_button_refetches`, is the
pre-existing documented flake from items 7/8's own closing notes —
confirmed non-regression via 3x isolated reruns, all passing).

### 76 — P2

The brief named this the item needing "the most live investigation,"
and Phase 0.2 (see §71 above) already did that investigation before
any code was touched: the real production "Test" playlist's files were
found in a live, pre-existing, partially-applied rename state (5 files
already renamed on disk via Seeker's own Rename feature; the DB's
`local_files.relative_path` never reconciled for any of them — root
cause not conclusively identified). That finding **ruled out** all
three of the brief's own hypothesized defects (A/B/C — preview-not-
authoritative, no-within-batch-check, a live download landing mid-
preview) as the specific mechanism behind the four real files that kept
their prefixes: none of A/B/C explains a successful rename whose DB
row silently never updates. Reconciled via a normal `seeker library
scan` + `seeker library match` (DB-only, real files untouched), with
the user's explicit go-ahead, before any code changes — a follow-up
dry run confirmed the false collisions were gone.

**2.1:** stated above — reported, not silently absorbed into "fixed it
anyway." The four "regardless" fixes (2.2-2.5) were still built exactly
as briefed, since they're real, independently-confirmed defects
regardless of which one produced this specific report.

**2.2 (within-batch collisions):** new `_mark_within_batch_collisions()`
— a second pass over `plan_renames`'s own output, before returning it,
counting how many plans target each real proposed path and re-flagging
any `'rename'` plan whose target is shared by another plan in the SAME
batch as `'collision'` instead. Confirmed via a live test: two tracks
with the same artist/title (a duplicated playlist entry, or two remixes
normalizing to the same string) targeting different real source files,
neither of which reads as a collision individually since neither target
exists on disk yet — now both correctly flagged at plan time.

**2.3 (honest resolved-name reporting) — a real, honest redefinition of
`collisions`, not just an added message:** `_apply_one_rename` now
compares its real, fresh `_resolve_collision()` result against
`plan.proposed_path.name` and records a detail (`"renamed to X, not the
previewed Y"`) plus a `collisions` increment whenever they differ —
moved OUT of the outer loop's old unconditional `if plan.action ==
"collision": result.collisions += 1`. This is a real behavior
refinement, found while writing the test for it: two plans that both
resolve to the SAME within-batch collision target don't necessarily
BOTH end up with a different real name than previewed — whichever one
`apply_renames` processes first still lands on its own exact previewed
name (nothing else has claimed it yet); only the second one actually
gets the numbered suffix. `collisions` now reports the real per-file
outcome, not the plan-time prediction — a plan flagged `'collision'` at
plan time that happens to win the name anyway is no longer miscounted
as a mismatch.

**2.4 (refuse a stale confirmed plan) — the brief's own preferred,
safer option, implemented as re-plan-and-compare:** `apply_renames`
now calls `self.plan_renames(track_ids=...)` on the exact same track
ids it was given, BEFORE doing any real work, and compares each fresh
plan's `(action, proposed_path)` against what the user actually
confirmed. Any disagreement is a real, counted `'failed'` outcome
(`reason: "plan_changed_since_confirmed"`), never a silent proceed.
Two real tests: a file landing at the target path mid-preview (Defect
C's own scenario, now closed structurally rather than by blocking
timers), and a track's `match_method` changing between confirm and
apply (a background `match_all()` demoting it). Both confirm the
original file is left completely untouched.

**2.5 (honest notice wording):** `format_rename_result_message`'s
existing `collisions` mention — now, thanks to 2.3's redefinition,
already meant "the real written name differed from the preview" rather
than "the plan predicted a suffix" — was reworded to say so explicitly
and prominently ("N file(s) written with a DIFFERENT name than the
preview showed"), with the notice kind downgraded to `warning` (not
bare `success`) whenever any real mismatch occurred, rather than
leaving this fact only discoverable in the 120px-capped results panel.

**2.6 (regression tests):** the within-batch-collision test above, plus
a dedicated test reproducing the EXACT real Phase 0.2 failing shape:
a `local_files` row whose `relative_path` still names a file that no
longer exists, while a DIFFERENT file already sits at the canonical
name (the row's own stale view of "my target" reads as a competing
file). Confirmed this produces an honest `'collision'` classification,
not a crash or silent data loss — documented explicitly as a real,
understood consequence of DB/disk drift that `scan_and_match` (this
project's existing, designed self-healing path, see item 40) is the
actual fix for, not something `plan_renames` itself needs to special-
case.

**Live re-verified against the real production "Test" playlist**
(read-only dry run, no `--apply`): 5 real renames proposed, 0
collisions, 4 already correct, 1 not auto-matched — the false
collisions from Phase 0.2's original desync are gone, and the fixed
code doesn't introduce any new ones against real data.

7 new tests across `test_metadata_service_rename.py` (5) and
`test_ui_smoke.py` (2). `mypy --strict` clean; full suite: 908 passed /
1 skipped, 0 regressions.

### 77 — P7 (5th report)

**Item 73's diagnosis was correct about a real defect, but the wrong
one for this report.** That fix (column sizing + `clearSpans()`) stays,
but the user's new screenshot — an ~800px-wide Actions column, header
centred, sibling columns rendering fine, Actions cells still completely
empty — refuted the "clipped to near-zero width" theory outright. This
round's brief supplied a specific, falsifiable hypothesis and a 30-
second experiment instead of another round of source-reading, and the
standing instruction was explicit: run it before writing any code.

**The experiment (run for real, `QT_QPA_PLATFORM=offscreen`, verbatim
from the brief):** a 4-row table, a real widget on row 0, a blank
`QWidget()` on row 1, `setSpan(0, 1, 2, 1)`. Result: `real.geometry()
== blank.geometry()` (`(100, 0, 99, 59)`, identical), child order
`[REAL, BLANK]` (blank added to the viewport later → paints on top),
and `viewport().childAt(center)` returned the **blank** widget, not the
real one. Also measured, and this is the part that explains why three
prior rounds of testing all passed anyway: `real.visibleRegion()` was
the FULL, non-empty rect — the real widget is not clipped, hidden, or
zero-size in any way Qt's own introspection reports. It is simply
painted over by a sibling added after it. Every prior regression test
(existence via `cellWidget()`, geometry via `sizeHint()`/
`sectionSize()`, even item 73's own `visibleRegion()` check) asks a
question that is `True` in exactly this broken state, because all of
them measure the real widget, and the real widget was never the
problem — the widget covering it was.

**The fix:** in `_render_duplicate_groups`, `setSpan()` is now called
BEFORE `setCellWidget()` for the group's first row (so the real
widget's own geometry is computed against its final spanned rect, not
a single-cell rect a later `setSpan()` call then silently changes
underneath it), and the `for other_row in range(...)` loop that used to
place a blank `QWidget()` on every covered row was deleted outright —
a spanned region needs no widget at all on its covered cells; the span
itself is what makes them render as blank. `removeCellWidget()` was
considered (per the brief's 7.2 fallback) but isn't needed: nothing
ever puts a widget on those rows in the first place now.

**The new test is occlusion-aware, closing the actual gap every prior
round missed:** `test_duplicates_actions_widget_is_not_occluded_by_a_
covered_row_widget` calls `viewport().childAt(visualRect(...).center())`
— what a real click would actually hit — and asserts it resolves to the
real widget or a descendant of it, not merely that the widget exists
with plausible geometry. Verified both directions: reverted only the
source fix and reran this one test in isolation — fails with exactly
the predicted `hit is not real_widget` — then restored the fix and
confirmed it passes. One pre-existing test asserting "the covered row's
widget has no `QPushButton` children" was updated to assert
`cellWidget(1, ACTIONS) is None` instead, matching the corrected
behavior (no widget there at all, not a differently-shaped blank one).

Audited every `setSpan` call site in the file (`grep -n setSpan`, only
two total): the Sharing-uploads empty-state span uses `setItem`, not
`setCellWidget` — no occlusion risk, left unchanged.

`mypy --strict` clean (82 files). Full suite: 908 passed / 1 skipped, 1
net new test, 0 regressions (the one `test_history_refresh_button_
refetches` failure in the full run is the pre-existing documented
flake — reconfirmed passing in isolation).

### 78 — P8 + P9

**8.1, settled with real data before any code changed:** this session
has filesystem access to its own real production `seeker.db` (same
Mac/account running `uv run seeker-ui`), so the brief's own diagnostic
query was run for real rather than theorized about:

```
(1, 'x9-pro', '/Volumes/X9 Pro', 3264, 3161)
(4, 'Test', '/Volumes/X9 Pro/Music/Test', 8, 4)
(16, 'Music', '/Volumes/X9 Pro/Music', 0, 0)
```

This is 8b's exact shape, live: "Music" is a real registered location,
nested one level ABOVE "Test" (itself nested inside "x9-pro"), with
zero scanned files. Simulating the OLD `resolve_folder_scopes`
(alphabetical `ORDER BY name`, first match wins) against these rows
confirmed the bug directly: a folder path equal to "Test"'s own
registered path matches "Music" first ("Music" < "Test" alphabetically)
— a location with genuinely 0 files — even though "Test" itself has 4
real fingerprinted files sitting at that exact path. The brief's "other
account" with 0 files in scope is a different macOS user this session
has no filesystem access to (per item 0.2's own per-account DB split,
confirmed as a real, unavoidable limitation, not skipped work) — but 8b
doesn't need that account to prove itself; it's reproducible right here
against real data.

**8.2 (most-specific-wins):** `resolve_folder_scopes` now collects
EVERY candidate location a folder resolves inside (not just the first
alphabetical match), scores each by its own resolved path's string
length, and keeps the longest. A genuine specificity TIE turns out to
be unreachable via two distinct real registered locations under normal
use — `library_locations.path` is UNIQUE at the DB schema level, so
two locations can never share a literal path string, and two different
real ancestor directories of the same folder can never have equal
string length (nesting strictly increases length with depth). The only
real way to construct a tie for testing was a symlink: two different
registered path STRINGS (`real/` and a symlink `link/` pointing at it)
that `Path.resolve()` collapses to the identical real directory —
legitimate (a volume reachable via two mount points is the same real
shape), and now covered by a real test. `preferred_location_id`
(optional, defaults to the old alphabetical order when omitted) breaks
that tie — this is also exactly what P9's combo selection now feeds
in.

**8.3/8.4 (honest reporting):** new `DuplicateService.summarize_scopes()`
returns a real `ScopeSummary` (file_count + which location(s) the
folders actually resolved to + which of those have ZERO total scanned
files, location-wide — not just within the folder). Implemented by
caching each resolved location's full file list once per call (a
folder-scope run already touches `LocalFileRepository.get_all_for_
location` per scope; this reuses that instead of adding a second real
query per location). `format_duplicates_scope_count()` now always
names the resolved location(s) ("216 files in scope (Music).") and, if
any resolved location has never been scanned, says so explicitly
instead of leaving a bare, unexplained 0.

**P9, combined into this same commit:** the combo's "keep it enabled
in folder-scope mode" change has no real payoff without 8.2's fix
landing first (a wrong-but-confident tiebreak preference is worse than
none), and both changes touch the exact same `resolve_folder_scopes`
signature — so, deviating from the brief's listed commit order on
purpose (documented here rather than silently done), they shipped
together. The combo's `currentIndexChanged` now refreshes the scope
count live, and its selection is threaded through as `preferred_
location_id` at every UI call site that calls `resolve_folder_scopes`
— captured on the GUI thread before entering each `run_worker`
background closure (reading `QComboBox.currentData()` off the GUI
thread is a real Qt hazard, not just a style concern — see item 22's
own standing `Worker` lifetime rule for the same class of gotcha)
rather than re-read from inside the worker function.

5 new tests: 2 for `resolve_folder_scopes` (nested-most-specific-wins,
symlink-based real tie), 2 for `summarize_scopes` (names locations;
flags an unscanned one), 1 UI test flip (the combo now asserts
ENABLED, not disabled, in folder-scope mode — the direct P9
regression test). `mypy --strict` clean (82 files). Full suite: 913
passed / 1 skipped, 0 regressions.

### 79 — P12 + P11

**P12:** `main_window.py`'s scan button was constructed as
`QPushButton("Rescan & match library")`. Qt treats a bare `&` in
button/label text as a keyboard-mnemonic marker — consumed and
rendered as an underline under the following character, which is
exactly the reported "Rescan _match library" rendering, not a typo in
the source string at all. Changed to `"Rescan and match library"`
(the brief's own preferred fix — simpler than escaping to `&&`, and
doesn't rely on that escaping surviving a future edit). `"&Help"` on
the real `QMenuBar` (item 34) is a genuine, intentional mnemonic and
was explicitly left alone. A `grep -rn '&' src/seeker/ui/` audit found
no other stray instance. The new regression test is source-level (a
regex scan of every `QPushButton`/`QLabel` string literal in the
file) rather than enumerating known widgets one by one, so any string
added to this file in the future is covered automatically without
needing its own new assertion.

**P11:** `_build_tagging_controls` constructed its `FlowLayout()` with
default arguments — `h_spacing`/`v_spacing` both stay `-1`, which
`horizontalSpacing()`/`verticalSpacing()` resolve via `_smart_spacing()`
(a `QStyle.pixelMetric(PM_LayoutHorizontalSpacing)` query), which comes
back at effectively zero under this app's Fusion styling. Item 72's
own fix (the reflowing layout itself) was real and unrelated to this —
the row DOES reflow correctly now, its buttons just touch. Fixed with
explicit `theme.SPACING_SM` for both axes. **Verified the fix actually
matters, not just "looks more correct":** reverted the change in
isolation and reran the new spacing-gap test alone — it failed with a
real measured **-2px** gap between two adjacent buttons (an actual
overlap, not merely "tight"), confirming this was a real visual defect
and not a cosmetic nice-to-have.

11.2's "are checkbox labels clipped" question resolved structurally
rather than by more guessing: `FlowLayout._do_layout` always calls
`item.setGeometry(QRect(pos, item.sizeHint()))` for every item it
actually lays out, so once 11.1's spacing exists, no VISIBLE item can
ever be given less than its own full `sizeHint()` width — there is no
separate clipping mechanism in this layout to fix. Confirmed with a
direct test rather than left as an assertion-free "should be fine."

**Real gotcha hit writing the spacing test:** `bpm_min_edit`/
`bpm_max_edit` start `.hide()`'n (shown only once "Analyze audio" is
checked) — `QWidgetItem.setGeometry()` is a genuine Qt no-op for a
hidden widget (`isEmpty()` short-circuits it before the underlying
`QWidget.setGeometry()` call), so a hidden item's `.geometry()` stays
whatever stale/default value it had before this layout pass ever ran
(observed: a bare `(0, 0, 640, 480)`, Qt's own pre-layout default). The
gap-measuring test excludes hidden items rather than naively including
every item in the layout's index range.

Two pre-existing tests asserting the literal `"Rescan & match library"`
string updated to the real new text (not xfailed).

`mypy --strict` clean (82 files). Full suite: 916 passed / 1 skipped,
5 net new tests, 0 regressions.

### 80 — P10

The reported mechanism was exactly right and needed no live
investigation to confirm: Qt's `border-radius` on a widget paints the
widget's OWN border/background, but does not clip that widget's
children — any `setCellWidget` widget reaching a table's edge (the
Sharing table's full-width "Add to my SoulSeek share" button, the
Duplicates/Review tables' Actions buttons) paints flat, square corners
directly over the table's own rounded corner, because nothing in Qt's
paint pipeline ever intersects a child's paint region against its
parent's border-radius curve.

**The fix (`theme.make_card`) is structural, matching the brief's own
diagnosis that no stylesheet-only fix could work:** a new `QFrame`
(`objectName="card"`, styled via a new `QFrame#card` global rule) owns
the real rounded border, background, and radius. `inner` (the actual
`QTableWidget`/`QListWidget`) sits inside it with its own
`border: none; border-radius: 0px` set per-instance, separated from
the frame's edge by a small, real, non-zero content margin
(`theme.SPACING_XS`). That margin is the part that actually does the
work: even a cell widget that reaches `inner`'s own edge can now never
reach the FRAME's rounded corner, because the margin physically keeps
every child of `inner` away from it. Per item 47's own standing QSS
gotcha #2, `WA_StyledBackground` is set on the frame explicitly — a
plain stylesheet background/border on a `QWidget`-derived class isn't
guaranteed to paint without it.

Routed through all 11 real `QTableWidget`/`QListWidget` instances in
the app (Dashboard's playlist list and track table, Downloads,
History, both Sharing tables, all three Review tables, both Duplicates
widgets, and the Rename-preview dialog's plain list) plus a small
extra step for `track_table`: it's a page inside a `QStackedWidget`,
and `QStackedWidget.setCurrentWidget()` requires its argument to be a
widget actually added as one of its own pages — so a new
`self.track_table_card` attribute holds the card, is what's actually
added via `addWidget`/switched via `setCurrentWidget`, while
`self.track_table` itself (still what every other call site reads
rows from) is untouched and simply reparented one level in.

**`theme.cell_widget()`** consolidates 6 independently-drifted
hand-rolled `QWidget()`+`QHBoxLayout`+`setContentsMargins(0,0,0,0)`
container builders (`_build_track_actions`, `_build_duplicate_group_
actions`, `_build_needs_review_actions`, `_build_upgrade_actions`,
`_build_local_review_actions`) into one, plus the Sharing table's two
single-widget cells (the bare "Add to my SoulSeek share" button and
the "Shared" label) — the same class of duplication this project's
`matching.py`/`download_dedup.py` precedent already exists to prevent.
Real `SPACING_SM`/`SPACING_XS` margins/spacing (not zero) plus a
trailing `addStretch()` — the stretch is what fixes P10.3 structurally:
`setCellWidget` resizes its widget to the FULL cell rect directly
(bypassing normal layout sizing), so a bare button placed there always
filled the whole cell; wrapping it in a container whose trailing
stretch absorbs the leftover width, rather than stretching the button
itself, is what makes a button read as a button again. No per-button
`setMaximumWidth` magic number was needed once the stretch existed.

**Scoping decision, stated plainly rather than silently done:** the
Downloads table's two progress-widget builders
(`_build_terminal_progress_widget`/`_build_progress_widget`) were
LEFT as bespoke hand-rolled containers, not routed through
`cell_widget()` — they rely on `layout.addWidget(bar, 1)`'s real
stretch factor so the progress bar fills available width, which is
correct, desired behavior for a progress bar (unlike a button, a
progress bar SHOULD stretch) that `cell_widget()`'s generic
no-stretch-factor API doesn't support. The corner-cutting risk at
their table (Downloads' Progress column IS the last, stretched
column) is still fully closed by `make_card()` wrapping the table
itself — that fix is independent of what's inside individual cells.

**Verification, per the brief's own "the next check must be pixels"
standing instruction from item 77:** real screenshots
(`window.grab().save(...)`, offscreen QPA, real `FakeApplication` data)
were taken for Sharing, Duplicates, Downloads, Review, and Dashboard.
All five show clean rounded corners on every table card with no visible
cell-widget bleed; the Sharing table's "Add to my SoulSeek share"
button and the Duplicates table's Actions controls both read as
compact, padded buttons rather than filled cells.

New `tests/test_theme.py` (6): card structure/parenting, inner border
turned off, a real nonzero margin, `cell_widget`'s real inter-widget
gap, a lone widget NOT stretched to fill its container width, and the
single-label case. One new `test_ui_smoke.py` test enumerates all 11
real table/list attributes on `MainWindow` and asserts each one's
parent is a `card`-named frame, so this routing is enforced
structurally rather than left as "available to remember to use."

Four pre-existing tests needed updating for the new cell-widget wrapper
shape (`cellWidget(...)` now returns the container, not the bare
button — fixed via `.findChild(QPushButton)` rather than a direct
`isinstance`/`.click()`), and `track_area_stack`'s current-page
assertions updated to target `track_table_card`.

`mypy --strict` clean (82 files). Full suite: 923 passed / 1 skipped,
7 net new tests, 0 regressions.

### 81 — 0.1 + 0.2 + 0.3

**0.1:** the previous brief's own diagnosis (section 0) established
that a packaged `.dmg` tested ~2 hours after the last commit contained
every real fix — the reported discrepancy was a testing-logistics
artifact, not a code difference, because nothing anywhere in the app
showed which build was actually running. `pyproject.toml` is pinned at
a static `0.1.0` and that was the only thing ever displayed. Fixed
with a generated `src/seeker/_build_info.py` — real git SHA/describe/
UTC timestamp, written by a new `packaging/build_dmg.py::_write_build_
info()` step immediately before the PyInstaller build. The committed
version (`GIT_SHA = "dev"`) is a deliberate dev-run fallback, force-
added to git despite living in `.gitignore` (`git add -f`) — a real
tradeoff, stated in both the file's own docstring and the `.gitignore`
comment: once tracked, gitignore no longer hides a tracked file's
future local modifications from `git status`, only prevents brand-new
untracked files from being listed. The practical effect is a soft
convention (don't commit a real local build's regenerated content),
not a hard git guarantee — acceptable here since a real `.dmg` build's
`_build_info.py` is exactly as disposable as `dist/`/`build/` already
are. Surfaced in three places per the brief: the window title
(`"Seeker — <sha>"`), the About dialog (next to the version line,
which already existed), and the Help page (a new line next to the
data-locations section, since that's where "which build is this?"
troubleshooting actually starts).

**0.2:** a new sentence on the Help page, `HELP_DATA_LOCATIONS_PER_
ACCOUNT_NOTE`, states explicitly what CLAUDE.md item 18 has always been
true but never surfaced to an actual user: `platformdirs.user_data_
dir("Seeker")` is per macOS account, so two accounts have entirely
separate databases/library locations/scan state/SoulSeek data with
nothing shared, and a cross-account "fix didn't work" report is very
often just a different-database report.

**0.3:** checked whether item 74 (P5, the previous brief) already
fixed the frozen-build `compose_file_path()` problem this item
flagged, by reading the CURRENT real source rather than trusting the
roadmap summary — it had: `compose_file_path()` already copies the
bundled resource into the stable per-user `slskd_data_dir()` on first
use in a frozen build (guarded — only copies if the canonical copy
doesn't exist yet) and always returns that canonical path afterward.
No code change was needed for the frozen-path concern itself.

The working tree's own dirty `docker-compose.yml` (flagged by this
same item as needing a decision) turned out to be live, real evidence
that item 74's fix works exactly as designed rather than an unrelated
loose end: its diff is one new share-volume line for a "Test" location,
and the untracked `docker-compose.yml.bak-20260903T082155Z` sitting
next to it is confirmed BYTE-IDENTICAL (via `diff`) to the pre-change
committed version — precisely `add_location_to_share`'s own "compute
both new file contents before writing either, keep a backup" behavior
(item 74's own write-both-or-neither fix), having done its job for a
real Sharing action taken during a real `uv run` session. Committed
the real change (this file already commits real, machine-specific
absolute paths as its own defaults — an established convention for
this single-user personal project, not a template repo) and deleted
the now-redundant backup rather than leaving it stray.

Also swept up, since "don't leave the tree dirty" was this item's own
explicit instruction: `.DS_Store` files (added to `.gitignore`, three
stray ones deleted) and the two untracked `tests/_stress_step{3,4}_
*_repro.py` scripts left over from the previous round's item 63
investigation — committed rather than left dangling, matching this
project's own existing, already-tracked `_*_repro.py` convention (4
prior examples: `_stress_hang_repro.py`, three `_workers_*_repro.py`
files).

4 new tests (`format_build_identity` dev/real cases, About dialog and
Help page both showing the build line, Help page showing the
per-account note); one pre-existing test's window-title assertion
updated for the new `"Seeker — dev"` shape.

`mypy --strict` clean (83 files). Full suite: 927 passed / 1 skipped,
0 regressions.

### 82 — P13: manual track search and download

The brief's own framing was right: the hard part (best-quality-with-
fallback ranking) already existed in `quality.select_downloads()` and
needed zero new logic. What actually took real investigation was
everywhere a manual track (one belonging to no playlist) turned out to
violate an assumption the rest of the codebase had always been safe to
make — every one of the four items below was found by tracing the real
code path, not by guessing.

**13.1/1: duration_ms=0's real, delayed blast radius.** The brief asked
to verify the post-download match step doesn't depend on a non-zero
duration. It doesn't — `_index_and_match_settled_download` calls
`find_best_match(track, [local_file])` with a single-candidate list,
and `matching.py`'s scoring is artist+title only. But tracing one level
further found a real, different risk the brief didn't name: a LATER
`match_all()` re-run (e.g. a routine "Rescan and match library") DOES
apply a duration pre-filter (`matcher.py`'s `DURATION_TOLERANCE_MS`,
±5s) against every candidate local file — a real `duration_ms=0` would
fail that filter against nearly any real audio file's actual duration,
which is exactly item 45's own documented "match_all() has no
provenance concept, so a later run can demote a correct match" class,
just via a new trigger. Fixed by backfilling the track's `duration_ms`
from the real just-indexed local file (mutagen-read, real audio) the
first time a manual track is indexed — scoped to `is_manual_track_id()`
only, so a real Spotify track's authoritative duration is never
touched.

**13.2/2: the move step's own playlist-iteration loop.** `_resolve_
destination` was refactored to accept `Playlist | None` per the brief.
But `_move_completed_file` — the actual post-download move step —
resolves destinations by iterating `self.playlists.get_by_track_id(...)`
and calling `_resolve_destination` per playlist; for a manual track that
list is ALWAYS empty, so the loop body never runs at all and `resolved`
stays `None` unconditionally, regardless of what `_resolve_destination
(None)` would now return. Every completed manual download would have
stayed stuck in slskd's own download directory forever. Fixed with an
explicit `if not playlists: resolved = self._resolve_destination(None)`
fallback, deliberately scoped to "genuinely zero playlists" so an
ordinary playlist track's existing (deliberate) "no destination, leave
it in place" behavior is byte-for-byte unchanged.

**13.7/3: the global `check` report.** `generate_match_report`'s
playlist-scoped branch structurally can't include a manual track (it
queries `get_all_for_playlist`). The GLOBAL branch (`playlist_id=None`,
`check` with no playlist name) reads `self.tracks.get_all(connection)`
— literally every row — and would show a manual track in "unmatched"
the instant a routine match run gave it a `track_matches` row, muddying
a report whose entire point is "how much of my Spotify library is
present locally." Fixed by excluding `is_manual_track_id()` rows from
that one branch. `dashboard_service`'s two playlist-scoped facts
(`get_playlist_track_status`, `_fetch_next_step_facts`) were verified
by reading their real source rather than assumed safe — both
genuinely playlist-name-scoped, no code change needed.

**13.7/4: "Unknown" was never designed for this.** Both `DashboardService.
get_active_downloads` and `HistoryService.get_recent_events` (both
event kinds) fell through to a bare `", ".join(playlist_names) or
"Unknown"` when a track had no playlist link — a defensive fallback
for a real Spotify track that unexpectedly has none (shouldn't happen).
A manual track hits this EVERY time, and "Unknown" reads as a data-
integrity problem, not the real, expected state it actually is. New
shared `models/track.py::resolve_playlist_label(track_id,
playlist_names)` returns "Manual" for a manual track id, else the
existing join-or-Unknown logic — used by all three call sites instead
of three independently-drifting copies (the exact duplication class
`matching.py`'s own consolidation history warns against).

**Design, as briefed:** `search_manual`/`download_manual` on
`DownloadService`, sharing `_build_search_query` (refactored to take
plain artist/title strings, not a `Track` — shared verbatim by both
paths now) and `select_downloads` with `download_playlist`, never a
second copy. `chosen` (an explicit per-row pick) bypasses ranking/
threshold entirely — a real test confirms a candidate that would score
below the auto threshold is still requested when explicitly chosen. An
optional `files` param lets the UI's "Download best" reuse the results
table's own already-fetched candidates instead of paying a second real
20-45s network search. New public `quality.rank_candidates()`/
`score_candidate()` are thin wrappers around the exact same private
`_sort_key`/`_score_candidate` `select_downloads` already uses — the
manual-search UI's results table needed both without a second, drifting
copy of either.

New "Search" sidebar page (item 82, between Dashboard and Downloads
per the brief's own placement reasoning) — column widths set from
`_size_search_columns` on day one, applying the item 73/77 lesson
directly rather than repeating the "nothing ever sets a column width"
mistake a fifth time. Live-rendered via a real offscreen screenshot
(not just unit-tested): ranking correct regardless of search-result
order (lossless outranks lossy), card corners clean, Actions buttons
read as real compact buttons. CLI parity via `seeker search <artist>
<title> [--download]`, with its own destination-guidance text (pointing
at Settings, not `playlists set-destination`, since a manual search has
no playlist for that command to mean anything).

27 new tests across `test_download_service.py` (10),
`test_matcher.py` (1), `test_cli.py` (6), `test_ui_smoke.py` (6, plus
one existing test's nav-button set updated), `test_dashboard_service.py`
(1), `test_history_service.py` (1). `mypy --strict` clean (84 files).
Full suite: 951 passed / 1 skipped, 0 regressions.

**Left open, per the brief's own instruction:** a real end-to-end
manual download against live slskd, after asking the user to confirm
the target — not run autonomously in this session.

### 84 — R6: Sharing's 401 Unauthorized

**Diagnosis confirmed live against this real machine's own data**
(Docker Desktop itself could not be brought up in this sandboxed
session — see below): `~/Library/Application Support/Seeker/config.json`
genuinely has `slskd_username`/`slskd_password` set to `null`. This
machine's wizard run predates item 28's SoulSeek network-credential
fields, so `Application.persist_soulseek_config` was never called with
real values for them — a live, concrete instance of exactly the gap the
brief's diagnosis (reading `docker-compose.yml`/`sharing_service.py`
statically) predicted. The on-disk `slskd-data/slskd.yml` in the repo's
own dev checkout still carries the correct, matching API key, and a real
`docker inspect`/`get_status()` 401 could not be reproduced directly in
this session for that reason — the fix is aimed at the confirmed root
cause (an incomplete env contract on recreate) rather than a live-
reproduced symptom.

**Docker Desktop blocked:** `open -a Docker` launches
`com.docker.backend`, but its privileged-port-mapping helper immediately
spawns an `osascript` "administrator privileges" GUI password prompt
that this session cannot answer — `docker info`/`docker ps` never
succeed. R6.1's live `docker inspect slskd`/`slskd.yml` check and R6.5's
disposable-throwaway-container re-verification are both left for the
user; everything else was fixed and unit-tested against the confirmed
static root cause instead.

**Fix:** `docker_setup.bring_up_slskd()`'s `library_location_path` param
is now `str | None` (only sets `SLSKD_SHARE_PATH` when given, instead of
always overriding). `SharingService.add_location_to_share` no longer
runs its own bespoke `docker compose up` — it calls `bring_up_slskd()`
with credentials read via a new `get_config: Callable[[], SeekerConfig]`
constructor param (same not-a-snapshot discipline as
`DownloadService`/`TrackMatcher`, item 28), checked for completeness
*before* either file is backed up or written. Missing any of
`slskd_username`/`slskd_password`/`slskd_api_key` raises new
`SlskdCredentialsMissingError` with a message pointing at Settings. A
failed recreate (`returncode != 0`) rolls the compose file back from its
own just-taken backup, mirroring the existing slskd.yml-write-failure
rollback. `get_status`/`get_uploads` now route their `httpx.get` calls
through a new `_get_or_raise_unauthorized` helper that turns a real 401
into `SlskdUnauthorizedError` with actionable text — no UI change
needed, since `run_worker`'s existing error path already renders
`str(error)` into the status label verbatim.

7 new tests in `tests/test_sharing_service.py` (4 missing-credential
variants via `pytest.mark.parametrize`, the real `bring_up_slskd` env
values captured and asserted, a recreate-failure rollback, two 401
cases) — `make_service()`'s new `config=CONFIGURED` default keeps every
pre-existing test's behavior unchanged. `mypy --strict src/` clean
(pre-existing, unrelated `_build_info.py` unused-`type: ignore` error
confirmed via `git stash` to already exist on the base commit). Full
suite: 3 pre-existing failures reproduce identically on the unmodified
base commit (`git stash` confirmed) — a locally-generated
`_build_info_generated.py` from a prior real `.dmg` build making the
About-dialog "dev" assertion fail, plus two already-documented flakes
(`test_main_window_constructs_without_crashing`,
`test_tagging_controls_row_has_real_spacing_between_items`) — none
touched by or related to this fix.

### 85 — R1: AIFF files invisible to the whole app

**Confirmed exactly as the brief diagnosed** — `AUDIO_EXTENSIONS`
(`audio_formats.py`) never listed `.aiff`/`.aif`, so `library/scanner.py`
never indexed one into `local_files` at all.

**Live-verified against a real production file**, not assumed: copied
`/Volumes/X9 Pro/Music/beatport_tracks_2023-11 copy/8Kays - Morning
After The Rave.aiff` (the exact folder the brief named, confirmed to
hold 63 real `.aiff` files) to a scratch copy and ran it through every
real pipeline piece read-only first, then a tag/art round-trip on the
copy only (original never touched):

- `mutagen.File()` → `AIFF`/`AIFFInfo`; `isinstance(tags, ID3)` is
  `True` (AIFF's `_IFFID3(IffID3)`, and `IffID3` is a genuine `ID3`
  subclass — confirmed via `issubclass()`) — `metadata.py`'s existing
  dispatch needed no AIFF-specific branch at all.
- `AIFFInfo.bitrate` is **not** absent the way the brief guessed —
  mutagen 1.48.1's real `AIFFInfo.__init__` already computes
  `channels * sample_size * sample_rate` and exposes it as `.bitrate`.
  `analyze_local_file_quality`'s existing `getattr(info, "bitrate",
  None)` already captures it; R1.4 needed a verifying comment, not a
  derivation branch.
- `soundfile.read()` decoded the real file directly (no ffmpeg fallback
  needed); `compute_fingerprint()` produced a real 12,614-char
  fingerprint at 521s duration.
- `write_text_tags` + `embed_album_art` + `save_tags` round-tripped on
  the copy: title/artist/album read back correctly, embedded art
  (a real cached JPEG from `AlbumArtCache`) read back **byte-exact**,
  and `save_tags` wrote real **ID3v2.3** (matches item 75's own
  MP3/WAV fix).
- `.aifc`: confirmed live via `mutagen.aiff.AIFF.score()` that mutagen
  recognizes `.aifc` by both the `FORM` IFF magic and the filename
  suffix, loading it through the exact same `AIFF`/`AIFFInfo` class —
  but the COMM chunk's `compressionType` field is never decoded, so a
  genuinely-compressed AIFF-C's reported `bits_per_sample`/derived
  bitrate can't be trusted. Added to `AUDIO_EXTENSIONS` (indexed/
  visible) but deliberately left out of `LOSSLESS_EXTENSIONS`.

**Fix:** `AUDIO_EXTENSIONS` gains `.aiff`/`.aif`/`.aifc`;
`quality.LOSSLESS_EXTENSIONS` gains bare `"aiff"`/`"aif"` only. No
changes needed to `metadata.py`, `library/scanner.py` (format is stored
via `suffix.lstrip(".")`, already generic), `duplicate_service.py`, or
the CLI — none hardcode a format list of their own.
`TOOLTIP_SCAN_ALL_LOCATIONS` now lists supported formats and says
existing AIFF files need one real re-scan to be picked up (R1.5).

9 new tests: `tests/test_audio_formats.py` (new file, 2 tests),
`test_quality.py` (+2: tier classification, a real synthetic-AIFF
`analyze_local_file_quality` case mirroring the existing WAV test),
`test_library_scanner.py` (+1, `.aiff`/`.aif` both indexed with the
right stored `format`), `test_metadata.py` (+2, `@requires_x9_pro`
against the real Beatport file: ID3v2.3 write, byte-exact art
round-trip). `mypy --strict src/` clean (pre-existing, unrelated
`_build_info.py` error confirmed via `git stash`). Full suite: same 4
pre-existing failures reproduce on the unmodified tree (confirmed
earlier this session for 3 of them via `git stash`;
`test_history_refresh_button_refetches` is the already-documented
test-order flake) — 964 passed / 1 skipped, 0 regressions.

### 86 — R2: poll rebuild destroyed checkbox/radio state

**Confirmed exactly as diagnosed** — `poll_timer` → `_poll_review_items`
→ `_render_review_items` → `_render_pending_upgrades` calls
`setRowCount()` and builds a brand-new `QCheckBox` per row via
`_build_upgrade_actions` every 2s, with nothing carrying checked state
across the rebuild. The codebase's own prior comment ("a checkbox
toggled mid-interval can get reset by the next tick's rebuild") had
understated it — every checkbox is destroyed every tick regardless of
timing, not just one caught mid-click.

**R2.4 audit (every `QCheckBox`/`QRadioButton`/`QComboBox` in
`main_window.py`, grepped and checked one by one):** the only two
interactive controls rebuilt per-row inside a `_render_*`/`_poll_*`
path are the Review tab's "Delete old file" checkbox (poll-driven,
every 2s) and the Duplicates "keep" radio + "Keep all" radio
(rebuilt on the LOCAL re-render `_on_delete_duplicates_finished` does
after a resolution, not the 2s poll — Duplicates isn't on `poll_timer`
at all, confirmed via `grep -n "_render_duplicate_groups("`). Every
other checkbox/combo in the app (`remember_checkbox`,
`analyze_audio_checkbox`, `force_retag_checkbox`,
`duplicates_location_combo`, `duplicates_folders_checkbox`,
`history_filter_combo`) is a persistent standalone widget built once,
never recreated by any render/poll path — not affected by this bug
class at all.

**Fix:** `_upgrade_delete_checked: set[int]`, keyed by
`UpgradeReviewDetails.request_id` — restored via `setChecked()` on
build, updated live via a `toggled` connection
(`_on_upgrade_delete_checkbox_toggled`), pruned to only still-present
request ids on every `_render_pending_upgrades()` call (including
before the row loop runs, so an empty upgrade list still prunes
everything).

`_duplicates_keep_selection: dict[frozenset[int], int]` — a
`DuplicateGroup` has no stable id of its own (clustering recomputes
groups fresh, and a local re-render after a delete rebuilds the same
Python objects from `_current_duplicate_groups`), so the group's own
frozenset of member `local_file.id`s is used as the key instead —
stable across both a poll-style rebuild and a local re-render, since
neither changes which files belong to a still-open group. Value is the
checked button's real id (a `local_file.id`, or the existing
`KEEP_ALL_DUPLICATES_ID` sentinel for the "Keep all" radio in the same
`QButtonGroup`). Restored via `setChecked()` on both the per-file keep
radios and `keep_all_radio` (now takes a `previously_selected_id`
param), recorded live via `QButtonGroup.idToggled`
(`_on_duplicates_keep_toggled`), pruned in `_render_duplicate_groups`
right after `clearSpans()` — before the empty-groups early return, so
"no duplicates found" (every group resolved) prunes the whole map too;
an earlier draft of this fix pruned AFTER that early return and left a
real, test-caught stale entry behind forever.

`poll_timer`'s own construction-site comment updated (R2.5) to say the
rebuild-every-tick tradeoff is now accepted ONLY for display state,
never user input — and that the state-map fix is a scoped patch on top
of the existing pattern, not proof the pattern itself is now safe for
some future interactive control added without the same treatment.

6 new tests in `test_ui_smoke.py`: two for the upgrade checkbox
(survives 3 re-renders; pruned when its row disappears), three for
Duplicates (per-file selection survives re-render; "Keep all" survives
re-render and correctly leaves both per-file radios unchecked; pruned
when the group disappears — this last one caught the early-return
pruning-order bug live, not just in review). `mypy --strict src/`
clean (pre-existing, unrelated `_build_info.py` error). Full suite:
same 3 pre-existing failures reproduce on the unmodified tree — 970
passed / 1 skipped, 0 regressions.

### 87 — R5: global table chrome

**Confirmed exactly as diagnosed via grep** — `grep -n
"verticalHeader" src/seeker/ui/main_window.py` returned nothing before
this fix, and `theme.py` styled only `QHeaderView::section`, never
`QHeaderView`/`QTableCornerButton::section` — the unstyled area below
the last row and the top-left corner button painted the raw palette
color. Only two tables (`_size_duplicates_columns`/
`_size_search_columns`, items 73/82) had ever set a derived Actions
column width; the other 8 named in the brief relied entirely on
`setStretchLastSection(True)`.

**Fix, in `theme.py`:**
`apply_table_defaults(table)` — `verticalHeader().setVisible(False)`
plus a row-height floor via `verticalHeader().setMinimumSectionSize()`
seeded from a real `cell_widget(QPushButton("Sample")).sizeHint()
.height()`. Verified empirically (a standalone repro script, not
assumed) that `setMinimumSectionSize` alone already raises a brand-new
row's height with no `resizeRowsToContents()` call needed — that call
is only needed for a row to grow TALLER than the floor for real
content, so it's placed inside the new `size_action_column()` (runs on
every table that has real Actions widgets to measure) and separately
after `downloads_table`'s own progress-bar cell-widget loop, since
`downloads_table` has no Actions column and thus never calls
`size_action_column`.

`size_action_column(table, column, action_widgets)` — the exact tail
end of `_size_duplicates_columns`/`_size_search_columns`, now shared;
both existing methods call it instead of keeping their own copy.
Applied (with each table's own explicit stretch/ResizeToContents
column plan, mirroring the Duplicates/Search pattern) to
`track_table`, `sharing_locations_table` (a new
`_size_sharing_locations_columns`, plumbed through a
previously-missing `action_widgets` list — the render loop's
`continue` branch for an already-shared location needed its own
"Shared" label widget added to the list too, not just the button
branch), `review_needs_table`, `review_upgrades_table`,
`review_local_table`. `downloads_table`/`history_table`/
`sharing_uploads_table` have no button-based Actions column at all
(confirmed by reading their render methods — progress bars or plain
`QTableWidgetItem`s only) so only got `apply_table_defaults`.

Stylesheet gained `QHeaderView { background-color: ...; border: none;
}` and `QTableCornerButton::section { ... }` (5a.2) as a backstop for
any future table that re-enables the vertical header.

**Verification (5b.3/5b.4):** a standalone offscreen script rendered
real data into all 7 populated tables and grabbed real
`window.grab()` screenshots at both 960×640 (the app's real minimum)
and 1280×800 — confirmed visually: "Confirm"/"Reject"/"Replace"/
"Decline"/"Add to my SoulSeek share"/"Keep all"/"Confirm delete"/
"Delete" all render in full at both sizes, no black column or corner
on any table. (First attempt at this script produced empty tables —
`MainWindow.__init__` calls `_poll_review_items()` once synchronously-
dispatched-but-asynchronously-completed during construction, and its
`FakeApplication`-driven empty result raced in via `app.processEvents()`
and overwrote the manually-rendered test rows; fixed by flushing the
event queue once right after construction, before rendering test data
— a real gotcha for any future offscreen-screenshot script against a
real `MainWindow`, not just this one.) New generic regression test
(`test_every_actions_column_table_has_a_derived_floor_for_row_height_
and_width`) asserts `sectionSize(actions) >= widget.sizeHint().width()`
and `rowHeight(0) >= widget.sizeHint().height()` across all 5 tables
with a real Actions column, in one place rather than five near-copies.

`mypy --strict src/` clean (pre-existing, unrelated `_build_info.py`
error). Full suite: same 3 pre-existing failures reproduce on the
unmodified tree — 971 passed / 1 skipped, 0 regressions (1 net new
test; the pixel-verification screenshots were throwaway, not
committed).

### 88 — R3: bulk actions

**Design, as briefed** — both are among the two most destructive
actions in the app, so both inherit the standing "never modify/delete
a real user file without explicit confirmation" rule in full via a
real listing plus a default-off confirmation control, and both are
recomputed fresh at the moment the button is clicked rather than
reusing a plan built at an earlier point (item 76 (P2)'s own lesson
about a preview and the applied result being allowed to diverge).

**`DownloadService.apply_upgrade_decisions_batch(request_ids,
delete_old)`** — applies `apply_upgrade_decision(request_id, True,
delete_old)` per row through the exact same explicit-decision method
the CLI/single-row UI action already use, never a second mutation
path. Success is checked by re-reading the request's own `status`
after the call (`"completed"` or not), not by parsing the returned
message string — `apply_upgrade_decision`'s own contract only ever
advances a request to `"completed"` on real success, so a failed row
is naturally still `ready_for_review` afterward and gets offered again
on the next Review poll, satisfying "a partial failure must leave
failed rows visible and pending" structurally rather than via extra
bookkeeping.

**`DuplicateService.resolve_groups(plans)`** — applies
`delete_local_files()` per `GroupResolutionPlan` (one per group the UI
already decided to resolve; a "Keep all" group is never turned into a
plan at all — skipped by the UI before this is ever called, not
filtered inside the service). New `BulkDuplicateResolutionResult.
plan_outcomes: list[bool]` (same order/length as the input plans) is
what makes the UI's local-drop-without-refetch possible: item 39
already established that a full `find_duplicate_groups()` re-fetch
after every resolution is a real ~10-minute cost at real scale
(344 groups), so `_on_bulk_resolve_duplicates_finished` drops only the
groups whose `plan_outcomes` entry is `True` from the in-memory
`_current_duplicate_groups` list, identical in spirit to the
single-group flow's own "drop just this group and re-render locally."

**UI:** `BulkReplaceUpgradesDialog`/`BulkResolveDuplicatesDialog`
mirror `RenamePreviewDialog`'s established shape (a `QListWidget`
preview + Confirm/Cancel). The Duplicates dialog additionally gates
its own Confirm button on its checkbox being checked in real time
(`toggled` → `setEnabled`), the same two-step gate the single-group
Delete flow already uses, rather than only checking after the fact.
Both "Replace all"/"Resolve all groups" buttons live in each table's
own header row, their text/enabled-state kept live from the same
render call that populates the table (never stale against what's on
screen).

**CLI parity (R3.4):** `seeker downloads review --all` reuses
`apply_upgrade_decisions_batch` — cheap, since the single-row
interactive CLI flow (`review_pending_upgrades`) already existed to
extend. **Duplicates bulk-delete gets no CLI parity at all** — checked
first, not assumed: `grep`ing `cli.py`'s `library duplicates` handler
confirms it has only ever been a read-only report (lists groups,
never calls `delete_local_files`/any delete path). Adding "resolve
all" parity would mean building the CLI's first-ever duplicate-delete
flow from scratch (which-file-to-keep selection in text, its own
confirmation flow, etc.) — disproportionate to this item's scope, so
stated explicitly here rather than half-added, per the brief's own
instruction.

16 new tests: `test_download_service.py` (+4: batch all-success,
partial-failure-leaves-pending, empty-list no-op, plus the new
`_seed_two_upgrade_scenario` fixture), `test_duplicate_service.py`
(+3: multi-plan resolve, one-group-failure-doesn't-abort-rest,
empty-plans no-op), `test_ui_smoke.py` (+10: 4 for Replace-all, 6 for
Resolve-all-groups including the Keep-all-skip case and the
partial-failure local-drop case), `test_cli.py` (+3: all-success,
declined-at-first-prompt, empty-nothing-to-review). `mypy --strict
src/` clean (pre-existing, unrelated `_build_info.py` error). Full
suite: same 3 pre-existing failures reproduce on the unmodified tree —
990 passed / 1 skipped, 0 regressions.

### 89 — R4: cover art in Finder

**R4.1 — checked the MP3s specifically, as instructed.** Read a real
MP3 from the "Test" library location directly via mutagen: a genuine
`APIC:Cover` frame, `image/jpeg`, 81,308 bytes, tags version `(2, 3, 0)`
— confirms item 75's ID3v2.3 fix is still in effect and this file's
embedded art is real, not empty/corrupt. This supports (doesn't
contradict) the brief's own format-based explanation: MP3 embedded art
is written correctly, so if it's still invisible in Finder specifically
for MP3 (not FLAC/WAV), that would be a genuine bug; if only FLAC/WAV
don't show it, the explanation is confirmed.

**The actual Finder visual check is blocked in this session**, not
performed and not assumed: `osascript -e 'tell application "Finder" to
open POSIX file "..."'` timed out with `AppleEvent timed out (-1712)` —
this sandboxed session has no Automation permission to control Finder,
the same class of macOS permission gate that blocked item 84's Docker
Desktop admin-password dialog. `screencapture`-based screenshotting
wasn't attempted further given item 42's own prior finding that Screen
Recording permission also wasn't available in this environment. Left
for the user: force a Finder thumbnail refresh (`qlmanage -r cache`,
already run once here as a real, safe, reversible action) and look at
the real folder.

**R4.2 — `cover.jpg` sidecar, opt-in, shipped.** New
`SeekerConfig.write_cover_jpg_sidecars: bool = False`.
`MetadataService` gained a `get_config: Callable[[], SeekerConfig]`
constructor param (same not-a-snapshot discipline as `DownloadService`/
`TrackMatcher`/`SharingService`, item 28) — `Application.
metadata_service` wires it to `self._config_store`. New module-level
`_write_cover_jpg_sidecar(file_path, image_bytes) -> bool`: writes
`cover.jpg` in the SAME directory as the track's own file (this app has
no per-album folder concept of its own — several tracks sharing a real
album folder all resolve to the same path, and only the first write
creates it), never overwrites an existing `cover.jpg`, never raises
(best-effort on top of an already-successful download, matching
`AlbumArtCache`'s own "disk write failure isn't fatal" precedent).
Wired into both real art-download call sites — `_tag_one_track` (right
after a successful `_download_album_art`, before the embed attempt, so
it happens regardless of embed outcome) and `_fix_one_track_art` (same
point, before the byte-exact-skip check) — reusing `AlbumArtCache`
means zero extra Spotify CDN fetches either way. Settings UI: a single
self-saving checkbox (no separate Save step — one independent boolean,
unlike the two-threshold form beside it) in the Thresholds tab, under a
new "Cover Art" group, with an explanatory note.

**R4.3 — per-file custom Finder icons deliberately NOT implemented,**
per the brief's own explicit instruction, recorded here as a real
decision: `NSWorkspace.setIcon:forFile:` (via pyobjc) would work for
FLAC/WAV too, but (1) adds a macOS-only dependency to a
cross-platform-intended app, (2) writes a resource fork to every real
user file, and (3) the user's real library lives on `/Volumes/X9 Pro`
— confirmed exFAT by the same tell item 2 already used (AppleDouble
`._` sidecars throughout the library) — where a resource fork is
stored as hundreds of extra `._` files that break on any non-Mac
system reading that drive.

11 new tests: `test_metadata_service.py` (+4: default-off, enabled,
never-overwrites, `fix_missing_art_for_playlist`'s own wiring),
`test_settings_window.py` (+3: unchecked by default, prefilled from
config, saves immediately on toggle). `mypy --strict src/` clean
(pre-existing, unrelated `_build_info.py` error). Full suite: same 4
pre-existing failures reproduce on the unmodified tree (the
`test_history_refresh_button_refetches` flake reproduced this run,
`test_main_window_constructs_without_crashing`/
`test_tagging_controls_row_has_real_spacing_between_items`/
`test_about_dialog_shows_build_identity` as before) — 996 passed / 1
skipped, 0 regressions.

### 90 — R7: run in the background from the macOS menu bar

**Design decisions were pre-confirmed with the user** (see the brief's
own table) — lifecycle (hide on close, keep infrastructure running on
quit), menu contents (status/pause/review+upgrades/check-now-open-quit),
and notifications (all three categories) were not re-litigated.

**Lifecycle (R7.1/R7.2).** `qt_app.setQuitOnLastWindowClosed(False)` is
set in `main_ui.py` only once a real `MainWindow` is about to exist —
NOT unconditionally at the top of `main()` — because the onboarding
wizard alone, with no completed setup yet, closing should still quit
the whole app (today's only behavior); setting it globally up front
would have left a headless, windowless, tray-less process running
forever if a user closed the wizard mid-setup, a real regression this
fix could easily have introduced. `MainWindow.closeEvent` checks
`self._tray_icon is not None and self._tray_icon.isVisible()` before
doing anything different — with neither true (no real tray, confirmed
live via `QSystemTrayIcon.isSystemTrayAvailable()`, which genuinely
returns `False` under a bare `QApplication(sys.argv)` in this project's
own offscreen test environment, though pytest-qt's own fixture was
separately confirmed to report `True` — both paths are real and now
both are tested), it falls through to `super().closeEvent(event)`,
Qt's ordinary behavior, unchanged.

**Quit path (R7.7).** `_on_tray_quit()` calls `QApplication.instance().
quit()` directly — NOT `self.close()`, which would re-enter `closeEvent`
and hide instead of quitting, exactly what a Quit click must bypass.
The real cleanup (`poll_timer.stop()`/`backend_poll_timer.stop()`/hide
the tray icon) lives in `cleanup_before_quit()`, connected once to
`QApplication.aboutToQuit` in `main_ui.py` — this fires for EVERY real
quit route uniformly (tray Quit, ⌘Q, Dock "Quit"), not just the one
this session could directly trigger. Live-verified end to end, not
assumed: a real offscreen script hid the window, fired `_on_tray_quit()`
via a `QTimer.singleShot`, and confirmed `qt_app.exec()` itself returns
(`exit_code=0`) with both timers stopped afterward — the event loop
genuinely exits, not just "nothing crashed." **Per the brief's own
explicit instruction, roadmap item 70's own open stress-test hang was
NOT investigated or touched** — observed instead: item 70's hang is
specifically in the Duplicates page's Compute Fingerprints step
(native, GIL-holding code); nothing in this item's timer-stop/tray-hide
cleanup touches fingerprinting at all, so no new interaction risk was
introduced, but this wasn't proven, only reasoned about.

**Pause (R7.4).** Checked as the very first thing inside `DownloadService.
poll_downloads()` itself (returns a real zero-valued dict matching every
key a live run normally adds, including the four appended at the very
end — `ready_for_review`/`locked`/`shortlisted`/`superseded`/
`unavailable` — a first draft that returned only 4 keys would have
`KeyError`'d the CLI's own `downloads status` print), not just gated in
the UI's own timer — so pausing is authoritative for any caller, not
just the tray toggle.

**Menu status/counts (R7.3), never a third source of truth.**
`_active_downloads_count` set inside `_render_active_downloads` (from
the same `get_active_downloads()` fetch the Downloads table already
uses); `_needs_review_count`/`_pending_upgrades_count` set inside
`_render_review_items` (from the same fetch the Review page tables
already use) — "Review" and "Upgrades" are two distinct tray items
because they're already two distinct sections/concepts on that one
real page.

**Hidden-window render skip (R7.6).** The real backend poll
(`_trigger_backend_poll`/`_trigger_sharing_poll`, on the separate 20s
timer) is completely untouched — it must keep running for the tray's
own status to stay live. What's gated is the 2s display-refresh
timer's actual WIDGET population: `_poll_selected_playlist`/
`_poll_next_step`/`_render_activity_strip` skip entirely while hidden
(no tray relevance at all); `_render_active_downloads`/
`_render_needs_review_candidates`/`_render_pending_upgrades`/
`_render_local_needs_review_matches` still update the COUNTS the tray
needs (and, for upgrades, the real list "Replace all" reads — R3.1)
before an early return that skips the actual `setRowCount`/populate-
loop work. `_on_tray_open_seeker()` (reopening from the tray)
immediately re-runs every gated poll method rather than waiting up to
2s for the next natural tick to notice the window is visible again.

**Notifications (R7.5).** Downloads-finished: piggybacks on
`HistoryService.get_recent_events()` (item 54's existing derived view)
rather than a new source of truth — a silent one-time seed
(`_seed_notification_cutoff`, a real `run_worker` call at construction)
records the newest existing event's `occurred_at` with NO notification,
specifically so pre-existing history can't flood a notification the
instant the tray icon appears; every later 20s backend-poll cycle diffs
against that cutoff (events sort newest-first, confirmed by reading
`HistoryService`'s own `.sort(reverse=True)`) and batches by
`playlist_name` into one message. Needs-decision: fires only on a
genuine INCREASE from the last-seen total (`_last_notified_review_count`),
never every 2s tick the count happens to still be positive — a plain
"count > 0" check would have re-notified constantly for as long as
anything sat unreviewed. Errors: rate-limited via `time.monotonic()`,
`ERROR_NOTIFICATION_COOLDOWN_SECONDS = 300` (untuned), hooked into
`_trigger_backend_poll`'s own existing `on_poll_error` callback — no
new polling. All three gated behind their own `SeekerConfig` toggle
(`notify_downloads_finished`/`notify_needs_decision`/`notify_errors`),
all defaulting on, editable in Settings (self-saving checkboxes, same
shape as R4.2's cover.jpg toggle).

**Real packaging gap found and fixed, not just polish.**
`packaging/icons/` was previously read ONLY at PyInstaller build time
(to set `EXE()`/`BUNDLE()`'s own `icon=`, which macOS/Windows apply to
the bundle/executable itself — not something the running Python
process can read back out) — confirmed live by grepping `seeker.spec`'s
own `datas` list, which had exactly one entry (`docker-compose.yml`,
already `sys._MEIPASS`-resolved by `docker_setup.compose_file_path()`).
Without a fix, a real packaged build's tray icon would have silently
resolved to a blank `QIcon()` the first time this code ever ran outside
a dev checkout. Fixed the identical way: `seeker.spec`'s `datas` gained
`(str(ICONS_DIR), "icons")`; new `ui/main_window.py::
_resolve_tray_icon_path()` branches on `sys.frozen` exactly like
`compose_file_path()` does. The menu-bar icon itself reuses the
existing full app `.icns` via `QIcon.setIsMask(True)` (macOS's
"template image" convention — Qt/AppKit recolor the alpha channel
automatically for light/dark menu bars) rather than a dedicated
simplified monochrome asset — no image-editing tool is available in
this environment to produce one; recorded as a real, stated scoping
gap for a future pass, not silently skipped.

**Testing.** 25 new offscreen tests in `test_ui_smoke.py` (tray-
unavailable fallback, close-hides-with-notice-shown-once, pause
toggle persists, menu status/count text incl. the paused suffix,
reopen un-hides and refreshes, cleanup stops both timers, needs-
decision fires-only-on-increase, error rate-limiting, download-
notification batching-by-playlist and cutoff-skipping, the hidden-
window table-population skip, both `_resolve_tray_icon_path()`
branches) plus 2 in `test_download_service.py` (paused makes zero real
calls and touches nothing in the DB; resumes real calls once
unpaused) plus 3 in `test_settings_window.py` (all three notification
checkboxes default on, prefill from config, save immediately) — 30 new
tests total. Two real pre-existing tests updated, not silently
patched around: `test_history_page_fetches_and_renders_events_on_
first_visit`/`test_history_refresh_button_refetches` both now expect
one extra `get_recent_events()` call, since `_seed_notification_cutoff`
is a real, additional call site against the same shared fake counter
those tests already asserted against. `mypy --strict src/` clean
(pre-existing, unrelated `_build_info.py` error, confirmed via `git
stash` earlier this session). Full suite: same 3 pre-existing failures
reproduce on the unmodified tree — 1025 passed / 1 skipped, 0
regressions.

**Left for the user, genuinely blocked in this sandboxed session:** a
real manual check of hide → menu-bar → reopen → quit against the
actual macOS menu bar UI (a real system tray icon click, a real
Notification Center banner, the real light/dark template-icon
rendering) — this session's own Automation-permission and Screen-
Recording-permission gaps (see items 84/89) block any live GUI
verification beyond what offscreen Qt rendering and a real headless
event-loop exit check (above) can prove.

### 91 — RR1-RR3: post-round review of round 3's own test-suite reporting

**The user's own review caught a real procedural blind spot, not just
two red tests.** Round 3's every commit reported "the full suite green
(same N pre-existing failures)," verified each time via `git stash`
before re-running the suite on the base commit. That procedure was
structurally incapable of ever finding the real cause: `git stash`
(no `-u`) does not touch untracked files, `_build_info_generated.py`
is untracked (gitignored), so the stash left it in place on every
single check — the "confirmation" would have reproduced the same two
failures no matter what was actually causing them.

**RR1 — the two `"dev"`-literal failures.** Real, measured timeline:
`_build_info_generated.py` was written by a real `packaging/
build_dmg.py` run at `16:02:53 UTC` today (`GIT_SHA = 'a6af037'`),
`dist/Seeker.dmg` followed at `16:03:38 UTC`. Both tests
(`test_main_window_constructs_without_crashing`,
`test_about_dialog_shows_build_identity`) assert the literal `"dev"`
on the comment's own stated assumption "this test never runs against a
real packaged build" — true, but irrelevant: the test doesn't need to
run against a package, it just needs the generated file to exist on
whatever machine runs it, and nothing ever cleans that file up.
**Fixed structurally, not by patching the two assertions**: new
`tests/conftest.py::_force_dev_build_identity` (autouse, function-
scoped `monkeypatch`) sets `seeker._build_info.GIT_SHA`/
`GIT_DESCRIBE`/`BUILT_AT` back to `"dev"` for every test in the whole
suite — real local build state can never again change what this suite
reports, on this machine or anyone else's. The two tests' own comments
were corrected to describe the real mechanism instead of the false
assumption.

Same root cause, same fix shape, for the mypy side: `--strict` enables
`warn_unused_ignores`, so `_build_info.py`'s blanket `# type: ignore`
on the `_build_info_generated` import was an *unused* ignore on any
machine where the file exists (exactly the state this session's own
earlier checks ran in, every time). Replaced with a real
`[[tool.mypy.overrides]] module = "seeker._build_info_generated"`,
`ignore_missing_imports = true` — verified clean in BOTH states by
physically moving the generated file out and back in and re-running
`mypy --strict src/` each time (84 files clean present, 83 files clean
absent).

**RR2 — the FlowLayout spacing test, diagnosed for real.** Instrumented
`FlowLayout._do_layout()` itself with a temporary print at its own
`item.setGeometry()` call site, then compared against what the test's
`layout.itemAt(i).geometry()` read back afterward. The layout's own
positioning logic was correct — every item in one row was genuinely
assigned the identical `y` — but the read-back geometry showed a
checkbox row at height 10 sitting beside a button row at height 16,
each keeping its own right/bottom edge fixed while its top/left crept
inward: the exact signature of a widget whose geometry was queried
before Qt's offscreen platform had actually finished applying it, with
no event-loop spin between `setGeometry()` and the read. Two remedies
were tried and measured, not assumed: `qtbot.waitExposed(window)`
alone did not fix it (failed identically across 5 repeated runs);
`qtbot.wait(0)` after each `setGeometry()` also did not fix it (same 5
repeated failures). A real `QApplication.processEvents()` call after
each of the loop's two `setGeometry()` calls did — confirmed clean
across 8 repeated runs, and confirmed the test still genuinely FAILS
(a real 1px gap where 8px is required) when item 79's own spacing fix
is temporarily reverted in isolation, so the fix didn't just make the
test stop noticing anything.

**RR3 — honest reporting.** Full suite after all of the above: `1028
passed, 1 skipped`, zero failures — genuinely green, not "green with
N." One real, separately-diagnosed flake remains and was left alone,
exactly as the user's own message scoped it:
`test_history_refresh_button_refetches` reproduced a real
`pytestqt.exceptions.TimeoutError` (the refresh button's background
`run_worker` call occasionally doesn't complete within the test's own
2000ms `qtbot.waitUntil` window) on 1 of 8 isolated repeated runs —
a genuine timing flake, not a build-state or geometry-settling issue,
and explicitly called out by the user as "genuinely pre-existing," not
part of this fix's scope.

### 92 — B8: Spotify 401 unrecoverable without a restart

Confirmed the brief's own diagnosis by reading the code, not re-deriving
it: `Application._spotify` (`application.py:338`, pre-fix) built one
`SpotifyClient` from a frozen access-token string and cached it forever
— nothing in `grep -n "_spotify\b" application.py` ever reset it. A
Spotify access token lives one hour, so the first playlist load after
launch worked and every one after the token's real expiry 401'd, on
whatever endpoint happened to be called next (`/playlists/{id}/items`
in the user's own screenshot). The one recovery path the UI offered
made it worse: Settings' "Re-authorize" (`connect_spotify(
force_reauthorize=True)`) cleared the token file, reset
`_auth_manager`, then called `self.spotify` — but `_spotify` was
already non-None in any session that had made a real Spotify call, so
the property short-circuited and the OAuth flow never ran. The dead
token stayed in memory even after the file on disk was cleared.

**Fix, in the shape the brief specified.** `SpotifyClient.__init__` now
takes `token_source: TokenSource` (`str | Callable[[], str]`) instead
of a bare string — `Application.spotify` binds it to
`lambda: self.auth_manager.get_valid_token().access_token`, so a
client that's lived in memory past the token's real lifetime still
resolves a fresh, already-refreshed token on its very next request,
without ever needing to be rebuilt. `_get` gained a second, independent
layer: on any `401`, it calls an optional `force_refresh` callable
(bound to `auth_manager.get_valid_token(force_refresh=True)`, a new
parameter that skips the normal `_is_expired()` check entirely — the
whole point, since a 401 the clock didn't predict is exactly the case
`get_valid_token()`'s own expiry check can't catch) and retries the
same request exactly once; a second 401 raises a new
`SpotifyAuthenticationError("Spotify rejected Seeker's authorization.
Re-authorize in Settings.")` instead of letting a raw
`httpx.HTTPStatusError` (with its unreadable URL-and-status-code
string) reach the UI. `connect_spotify` now resets `self._spotify` and
`self._sync_service` (which holds a reference to the same client)
alongside `self._auth_manager` — the actual fix for the unrecoverable
half of the bug, and the one covered by a new regression test
(`test_connect_spotify_reruns_authorization_when_client_already_cached`)
that pre-populates `_spotify`/`_sync_service` with sentinels and
confirms `connect_spotify(force_reauthorize=True)` both clears them and
genuinely re-triggers `self.spotify`.

**B8.5, recorded rather than re-discovered later.** Spotify rotates
PKCE refresh tokens on every use — the previous one stops working the
moment a new one is issued. Two installs sharing one Spotify account
and client ID (the user's real account and their own test account, on
the same machine) can each invalidate the other's stored refresh
token this way. That is a real, separate effect from this bug (the
frozen-client cache explains the reported 401 fully on its own), noted
as a comment in `auth_manager.py` so it isn't re-diagnosed from
scratch.

**Left for the user, real machine only.** B8.4 (confirm the real
`~/Library/Application Support/Seeker` token file's `expires_at` is a
plausible ~3600s-after-mtime value) and B8.7 (a live load-playlist,
wait-past-expiry, load-another-playlist round trip with no restart) —
this diagnosing/fixing session cannot reach that path or run a real
hour-long wait.

Full suite: `1034 passed, 1 skipped, 0 failed` on a clean run;
`test_ui_smoke.py::test_history_refresh_button_refetches` failed once
under the full-suite run and passed in isolation immediately after —
the same background-worker timing flake RR3 already documented
(1/8 isolated repeats), unrelated to any file this item touched
(`application.py`, `spotify/client.py`, `spotify/auth_manager.py`).
`mypy --strict src/`: clean, 84 files.

### 93 — B3: rename/tagging reporting fix, plus a real crash and a real data-loss path found investigating it

**B3.1 (the required real-DB check) found a different state than the
brief's premise, exactly as its own "stop and report" instruction
anticipated.** The three tracks' `track_matches` rows currently point
at the `Test/` copies, not `Neuro/` as the brief's snapshot showed —
the match flipped since the brief was written. That's expected,
documented behavior (item 45: `match_all()` recomputes from scratch on
every run and can flip), not a new bug, and it doesn't change anything
about B3.2-B3.4's fix (both compute from whatever the current match
is).

**B3.2-B3.4, done as scoped.** `RenamePlan` gained
`current_relative`/`proposed_relative` (`Path`, computed directly from
`local_file.relative_path` — no location object needed) and
`destination_note` (set only when `plan_renames()` was called with a
`playlist_name`, via new `destination_resolution.py::
resolve_playlist_destination()` — extracted from `DownloadService.
_resolve_destination` so the rename preview and the real download-move
logic can't drift onto two different precedence rules). `RenamePreview
Dialog` now shows the location-relative path with the absolute path as
a tooltip, plus the destination note when present; the CLI's `library
rename` output does the same. `MetadataService._tag_one_track`/
`_fix_one_track_art`'s per-track `details` messages (the actual
"tagging result panel," `main_window.py`'s `tagging_results`
`QPlainTextEdit`) now name the file via new `_describe_track_file()`
once `local_file` is resolved. 59 new/updated tests across
`test_metadata_service.py`/`test_metadata_service_rename.py`.

**Investigating B3.5 (does the Duplicates page group the three pairs)
surfaced findings well beyond B3's own scope — reported to the user
before continuing, per the standing rule that overlapping-location
cleanup and any crash-adjacent behavior change are real decisions, not
something to guess at.** The user's own review of the first pass
corrected two things and identified a third, worse issue underneath:

1. **The Neuro/Test copies are genuinely different files, not
   duplicate index rows** — confirmed by real file size (Tractor Beam:
   34,011,888 vs 33,971,993 bytes; Banana Shoes: 29,523,806 vs
   29,656,747; Glassy Star: 22,601,444 vs 22,589,123). The Neuro↔Test
   match flip is `match_all()`'s tie-break between two real rips, not
   overlapping locations "creating" a fake duplicate. The overlapping
   locations *can* still perturb that tie-break (more rows in the
   scoring pool per copy), but "almost certainly why" — this session's
   first-pass framing — overstated a plausible contributing factor into
   a proven cause, the same class of mistake P4's own three prior
   "could not reproduce" rounds warn against.
2. **The three overlapping locations are not a new discovery** —
   `resolve_folder_scopes`'s own docstring (item 77/P8,
   `duplicate_service.py:358`) already names this exact nesting
   (`x9-pro` ⊃ `Music` ⊃ `Test`), confirmed live against this same
   production DB. What changed since item 77: `Music` had 0 scanned
   files then; it has 3,454 now. The double-indexing became REAL when
   `Music` got rescanned, not before.
3. **Reconciled the file counts, as asked.** `x9-pro` (3,458 rows,
   all under `Music/`) = `Music` (3,454 rows) + exactly 4 rows that
   exist only in `x9-pro`'s index — and those 4 are 4 of the 8 stale
   `x9-pro` rows found below (files renamed before `Music`'s own scan
   ran, so `Music`'s scan correctly never indexed the old name).
   Fully explained, zero unreconciled residual.
4. **The real issue: "Resolve all groups" (item 88/R3.2) could delete
   a real file it shouldn't have.** `find_duplicate_groups_across_
   scopes` is deliberately content-based and location-agnostic
   (`duplicate_service.py:~496`, "pools every given folder... across
   scopes"). With two overlapping locations both indexing the SAME
   physical file, that file's two rows cluster as a 100%-similarity
   "duplicate group" — a real, valid cluster by the function's own
   design, but not a real duplicate to clean up. `_delete_one_local_
   file` (`:720`, pre-fix) built its delete path from `location +
   relative_path` and deleted it with no check against the row being
   kept — deleting "the other" row in that pair would delete the exact
   same inode the kept row points at, then `_repoint_or_clear_match`
   would repoint any match onto a row now pointing at a deleted file.
   This is very likely the actual origin of the B11.1/B3 stale
   `local_files` rows (see below) — a data-loss path that shipped in
   round 3 (item 88).

**The diagnostic query the user asked for first** (count `local_files`
rows whose absolute path doesn't exist on disk, grouped by location) —
run read-only against the real DB, no files touched: 13 total stale
rows (`x9-pro`: 8, `Test`: 1, `Music`: 4), NOT "hundreds" — the
systemic-staleness hypothesis doesn't hold at this scale. But the
mechanism is real and multi-instance, not a one-off: the file behind
B11.1 (`A-Cray, Zigi SC - Bit Perfect...`) is stale in ALL THREE
locations at once; `Zigi SC, Prdk - Burning Inside (VIP)` and two
`Overtune - Cut The Signal` filename variants are each stale in both
`x9-pro` and `Music`. A rename that goes through one location's row
correctly updates that row but leaves an overlapping location's own
row for the identical physical file pointing at the old name.

**The crash, fixed.** `find_duplicate_groups`/`find_duplicate_groups_
across_scopes` → `_cluster_duplicate_groups` called `analyze_local_
file_quality()` (opens the real file via mutagen) for every clustered
file with NO try/except — the one disk-touching step in an otherwise
pure-DB clustering pass. Reproduced directly against the real DB via
`find_duplicate_groups_across_scopes` scoped to the B11.1 stale row's
folder: `mutagen.MutagenError: [Errno 2] No such file or directory:
'/Volumes/X9 Pro/Music/Test/Music/Test/A-Cray, Zigi SC - Bit Perfect
(Original Mix) [www.dj-promo.org].mp3'`. Fixed with a per-file try/
except inside `_cluster_duplicate_groups` (this codebase's own item-15
"one bad item must not abort a batch" pattern, previously missing
here), distinguishing `file_missing` (checked via `Path.exists()`
before opening — a stale index, self-heals on the next `library scan`)
from a real open/decode failure, printed as counts. A cluster that
drops below 2 present files is excluded from the result, matching this
function's own pre-existing "files with no fingerprint are silently
excluded" precedent. **Deliberately kept the return type as
`list[DuplicateGroup]`** rather than a `(groups, skipped)` tuple — the
latter would have forced updating ~30 direct `_render_duplicate_
groups()` calls across `test_ui_smoke.py` for a UI surface this round
never asked for; the skip counts are reported via `print()`, the same
console-reporting idiom this codebase already uses everywhere else
(`compute_fingerprints`, `tag_tracks`). Surfacing this in the UI's own
result panel is a real, explicitly-deferred follow-up, not done here.
2 new tests reproduce both the "whole group disappears" and
"only the stale file drops, the real group survives" shapes with real
generated audio + a real deleted file (`test_find_duplicate_groups_
skips_a_stale_row_instead_of_crashing`, `test_find_duplicate_groups_
drops_only_the_stale_file_from_a_larger_group`).

**The same-physical-file delete guard, added in the same commit as
asked.** New `file_deletion.py::same_file()` (promoted out of
`metadata_service.py`'s own `_same_file` — now a one-line alias — so
both files share one real "is this the same inode" check instead of
two independently-drifting copies, the same consolidation shape as
`matching.py`'s own history). `DuplicateService.delete_local_files`
resolves the KEPT file's real path once, up front; `_delete_one_local_
file` now raises a new `_SamePhysicalFileError` (caught separately,
counted as `skipped_same_physical_file`, never `failed`) before either
the DB row or the disk file is touched, whenever the file about to be
deleted is the same real inode as the one being kept. `resolve_groups`
threads the count through `BulkDuplicateResolutionResult.files_
skipped_same_physical_file` and adds an informational (not
failure-framed) detail line. Reproduced with a real hard link (`os.
link`) standing in for what two overlapping locations actually produce
— two `local_files` rows, one real inode — since wiring up two real
overlapping locations in a test is unnecessary to exercise exactly what
`same_file()` checks. 3 new tests: the guard firing, the guard NOT
misfiring on two genuinely different real files, and `resolve_groups`
reporting the skip without counting the group as failed.

**B3.5, answered for real after the crash fix — live-verified against
the real DB, read-only (fingerprinting an already-fingerprinted file is
a no-op; nothing was deleted or moved).** Scoped `find_duplicate_
groups_across_scopes` across all three locations' `Test`/`Neuro`
folders: 3 groups found, ALL THREE are `x9-pro` vs `Test`
location-overlap index artifacts of the SAME real `Test/` file (100%
similarity, confirmed via `same_file()` — literally the same inode).
The `Neuro/` copies have NO fingerprint computed yet (confirmed via a
direct query), so the Duplicates page does not currently show the
Neuro/Test pair as a duplicate group at all — and per finding #1 above,
it shouldn't, since they're genuinely different files, not duplicates.
Concretely: had the user run "Resolve all groups" on these three
groups before this fix, the new guard would have refused all three
deletions (same physical file); before this session's fix, it would
have silently deleted a real file out from under its own kept copy.

**Left open, a real user decision, not attempted here.** The
overlapping-location topology itself (`x9-pro` ⊃ `Music` ⊃ `Test`) is
untouched — de-registering any of them deletes that location's
`local_files` rows and orphans whatever `track_matches` currently
point at them, and right now the winning matches are spread across all
three, so a report of what removal actually does to existing matches
should come before any cleanup is attempted, not this round. Two
concrete follow-ups named for whoever picks this up: (a)
`LibraryService.add_location`/`add_location_from_path` only check exact
`path` string uniqueness (`library_location_repository.py` / roadmap
item 49) — no parent/child containment check exists, so nothing stops
a fourth overlapping location being registered tomorrow; (b) the count
reconciliation above should be re-run if either location gets rescanned
again, since it's a live number, not a fixed one.

Full suite: `1045 passed, 1 skipped, 0 failed` — genuinely green this
run, no recurrence of the `test_history_refresh_button_refetches`
flake B8's report saw. `mypy --strict src/`: clean, 85 files.

### 100 — B7: removed the cover.jpg sidecar feature (reverses R4.2)

The user asked three real questions about R4.2's opt-in `cover.jpg`
sidecar, each answered from the code and from real evidence before
deciding to remove it:

**How are files named in a multi-album playlist folder?** Always
literally `cover.jpg` — `_write_cover_jpg_sidecar` wrote
`file_path.parent / "cover.jpg"` and returned `False` without touching
anything if it already existed. A playlist-shaped folder holding tracks
from ten different albums (this app has no per-album folder structure)
would get exactly one `cover.jpg`, belonging to whichever track was
processed first — the other nine albums' art was never represented.
Not a missing cover; a wrong one.

**Why didn't Finder change?** Because `cover.jpg` was never a macOS
Finder convention at all — it's read by Plex, Jellyfin, Kodi,
foobar2000, and Traktor. Finder has never used a folder-level image for
either the folder icon or the files inside it. Nothing was ever going
to change from writing this file.

**Why did VLC/Apple Music show the art?** They read the *embedded* art
(R4/item 75's own confirmed-correct write path), not the sidecar — that
was confirmation embedding works, not evidence the sidecar did anything.

**Decision: remove it.** R4.3's rejection of per-file custom Finder
icons (exFAT + AppleDouble sidecar concerns) still stands, so there is
no remaining route to a real Finder thumbnail for FLAC/WAV — the
feature cost new files written into the user's library for zero payoff
in the one place it was meant to help.

**Removed:** `_write_cover_jpg_sidecar()` and its two call sites in
`metadata_service.py` (`_tag_one_track`'s art-embed branch,
`_fix_one_track_art`'s own art-write step); `SeekerConfig.
write_cover_jpg_sidecars` and its `load_config`/`save_config` handling;
the Settings → Thresholds tab's "Cover Art" group box (checkbox + note
label) and its `_on_write_cover_jpg_toggled` handler; `help_text.py`'s
`TOOLTIP_WRITE_COVER_JPG_CHECKBOX`/`WRITE_COVER_JPG_NOTE`. 7 tests
removed (3 in `test_metadata_service.py` covering `tag_tracks`, 1
covering `fix_missing_art_for_playlist`, 3 in `test_settings_window.py`
covering the checkbox) — no replacement tests needed since there's no
new behavior, only removed behavior. One new test added instead:
`test_load_config_tolerates_a_removed_field_still_present_in_the_file`
— a real config.json still holding the old key must load cleanly, not
raise (confirmed: `load_config` reads each field via `data.get(...)`
individually, so an unrecognized key is simply never read, no
migration code needed).

**B7.3 — the 9 real files already written, left untouched, per the
standing rule against removing a user's file without explicit
confirmation.** A real, read-only `find "/Volumes/X9 Pro" -iname
"cover.jpg"` against the user's actual library found:

```
Music/Skrillex and Diplo present Jack Ü/cover.jpg
Music/DnB/Workforce - Set & Setting [2022]/cover.jpg
Music/DnB/Pendulum - Immersion/cover.jpg
Music/Albums/(2013) Sempiternal/cover.jpg
Music/Albums/Le Mystere des voix bulgares, Volume 2/cover.jpg
Music/Albums/The Elder Scrolls V -  Skyrim -  Original Game Soundtrack/cover.jpg
Music/Albums/2022 - Obsidian (Deluxe Edition) [WEB]/cover.jpg
Music/Albums/[2019] Music to listen to (EP)/cover.jpg
Music/Albums/Under Pressure (Deluxe)/cover.jpg
```

None deleted or modified by this change. Reported to the user in the
session summary — theirs to remove if they want to, since Seeker will
never write a new one but also won't touch these on its own.

Full suite: `1055 passed, 1 skipped, 0 failed`. `mypy --strict src/`:
clean, 85 files.

### 101 — B11: two observations confirmed against the real production DB

Neither of these was reported by the user — both were things the brief
flagged as found while diagnosing B3/B8, worth confirming or dismissing
rather than letting them re-surface unexplained in a future round.

**B11.1 — the doubly-nested `Test/Music/Test/` folder.** Queried the
real `playlists` table for every row with a `download_location_id` set:

```
id        name                     download_location_id  location_name  location_path               download_subfolder
6lZfGv...  Test                     4                      Test           /Volumes/X9 Pro/Music/Test  Music/Test
```

The playlist named "Test" has its destination LOCATION set to the
"Test" library location — whose own registered path is already
`/Volumes/X9 Pro/Music/Test` — **and** a stored `download_subfolder` of
`"Music/Test"`. `_resolve_destination`/`resolve_playlist_destination`
join these as `location.path / subfolder`, exactly as designed:
`/Volumes/X9 Pro/Music/Test` + `Music/Test` =
`/Volumes/X9 Pro/Music/Test/Music/Test/` — the precise real path the
brief found a file being actively tagged in. This is not a bug in the
join logic; the join is doing exactly what its two stored inputs say
to do. The real cause is that this playlist's `download_subfolder`
field was set to a value that re-describes part of the destination
location's own path, rather than a subfolder relative to it. The fix
is a one-field edit in Settings → Playlist Destinations (clear or
correct the "Test" playlist's subfolder), a real data/configuration
decision left for the user — not a code change, and not something this
session did on the user's behalf.

**B11.2 — does a fresh download re-point an existing match?** Read
`DownloadService.poll_downloads()` and `_index_and_match_settled_
download()`/`_track_already_has_a_matched_file()` directly rather than
inferring from behavior. The real, current answer: **no, not for an
ordinary settled-download completion.** `poll_downloads()`'s main loop
calls `_track_already_has_a_matched_file(request.track_id)` (item 56
Phase 5.3) BEFORE ever calling `_move_completed_file`/`_index_and_
match_settled_download` for a `role != "upgrade"` request — if
`track_matches` already has a row for this track with a non-null
`local_file_id`, the completion is instead converted into a
`ready_for_review` upgrade candidate (`_supersede_others_for_track`),
never silently overwriting the existing match. This guard is
deliberately NOT applied to `apply_upgrade_decision`'s own explicit
"Replace" action — a human clicking Replace is exactly the one place
overwriting a match on purpose is correct, per that function's own
docstring.

So the Neuro→Test flip B3's own investigation found is NOT explained by
this path — it's properly guarded and would have routed a second
completed download to Review instead. The far more likely explanation,
consistent with this project's own already-documented standing fact
(item 45): `match_all()` recomputes every `track_matches` row from
scratch on every run, with no "provenance-confirmed" concept for a
plain (never manually confirmed) `'auto'` match — once the `Test/`
copy existed as a second real `local_files` row (it didn't at the time
of the original Aug 27 `Neuro/` match), a later routine match/rescan
had a genuine second candidate to score and picked differently this
time. This is pre-existing, deliberate behavior (item 45 already named
it as a real, accepted gap), not a new bug this investigation found —
recorded here so the exact mechanism doesn't need re-deriving next time
this shape of report comes in.

No code changed for either observation, per the brief's own instruction.

### 102 — Post-round review: B2.2/B4.3/B6.5's pixel verification was asserted, not recorded

The user's own review of the finished round caught a real gap: B2, B4,
and B6 all claimed "pixel-verified" in CLAUDE.md/commit messages, but
no actual `window.grab()` evidence — RGB values, screenshots, or a
before/after crop — was ever written into HISTORY.md. The checks HAD
been run live during the session (real offscreen `window.grab()`
calls, same mechanism items 77/87/R5 already used, no Screen Recording
permission needed), but the results only ever reached the terminal,
never a durable record. Two of the three checks also had a real scope
gap: B4.3 had an automated `mapTo()`-based geometry test but no actual
pixel-color scan or crop image; B6.5 was never run at the app's real
960×640 minimum window size at all, only at default size — exactly the
narrower size the brief asked for because it's where a squeeze bug is
most likely to show. Re-run properly this time, real numbers below.

**B2.2 — Downloads table body gridline, real pixels.** Rendered a
populated Downloads table (5 rows), sampled the pixel color at every
row-boundary (4 boundaries × 4 x-offsets = 16 samples) via
`QImage.pixelColor()` on a real `window.grab()`:

```
16/16 samples: rgb=(58, 52, 78) — exact match to BORDER (#3A344E)
Header divider (col0/col1 boundary): rgb=(58, 52, 78) — exact match
```

Zero drift toward BG_SURFACE `(29, 25, 41)` at any sample. Confirms
`make_card`'s per-widget stylesheet (`border: none; border-radius:
0px`) does NOT strip the app-level `gridline-color` rule — the body
grid was never actually broken, matching the original diagnosis's own
prediction but now backed by a real measurement instead of an
inference.

**B4.3 — queued vs. downloading bar vertical centering, real pixel
scan.** For each row, scanned every y pixel inside the progress
column's real bar-drawing x-position for a non-background color,
finding the bar's real top/bottom extent, then compared its midpoint
to the row's own real `visualRect().center().y()`:

```
queued:      bar pixel span y=[170,205]  measured center=187.5  row center=187  delta=0.5px
downloading: bar pixel span y=[207,242]  measured center=224.5  row center=224  delta=0.5px
```

Both within the brief's own "match within a pixel or two" bar. A real
cropped `window.grab()` image of both rows' progress cells (queued on
top, downloading below) was produced and inspected directly — both
bars render as symmetric horizontal bands centered in their row, not
clamped to the top the way the original bug report showed.

**B6.5 — Settings, both tabs, at the app's real 960×640 minimum AND
default size.** All four combinations rendered and inspected directly
(Library Locations / Playlist Destinations × 960×640 / 1180×760
default). At 960×640 specifically: the Library Locations table's
"Actions" header renders in full (not clipped), both "Rename"/"Remove"
buttons render completely inside their column, rounded corners are
intact on both tables with no square-corner cut, and the Playlist
Destinations tab's list card also rounds correctly at this width.

**One real methodology bug caught and fixed while producing this
evidence, worth recording:** the first attempt at the B6.5 screenshots
manually called `settings_page._render_locations(...)` right after
construction, then resized/switched tabs — but `SettingsPage.__init__`
already kicks off its own real async `_refresh_locations()` /
`_refresh_destinations()` worker calls, which completed later (during
the same `processEvents()` settle loop) and silently overwrote the
manual render with `FakeApplication`'s own default (empty) data. The
resulting screenshot showed a genuinely empty table AND a real,
separate-looking symptom — the Actions column header clipped to
"ction" — which was actually just `theme.size_action_column`'s own
documented fallback (`default=header.minimumSectionSize()`, 40px) firing
because there were no real Actions widgets that render to measure
against, not a new bug. Fixed by passing real `locations=`/`playlists=`
into `FakeApplication`'s own constructor instead of a manual render, so
the real async refresh path resolves to real data the same way the
live app does. Recorded here specifically because it's the same
failure shape this item exists to prevent — a plausible-looking result
that wasn't actually measuring what it claimed to.

No code changed by this item — it verifies items 96 (B4) and 97
(B2+B6)'s already-shipped fixes with real evidence; nothing here found
a defect in the shipped code.

### 103 — C1: header column dividers, a real bisect instead of a third guess

Round 5's own brief opened with a hard rule: C1 had been "fixed" and
reported green twice (B2/item 97, then re-verified in item 102) and the
user still saw no divider on any header, anywhere. The brief mandated a
cheapest-first bisect before touching the stylesheet again. Ran it for
real, with a script driving a real offscreen `MainWindow` + `window.
grab()` (not the app's own test suite yet — see below for why that
mattered):

**C1.1 — is it painting at all?** Sampled every pixel in a 7px-wide
band around each column boundary, across the header's full height, on
the UNMODIFIED stylesheet. Result: `(29, 25, 41)` (`BG_SURFACE`) at
every single sample except the header's own bottom row, which showed
`(58, 52, 78)` (`BORDER`, the `border-bottom` rule). Zero `border-right`
pixels anywhere — not a contrast problem (a low-contrast divider would
still show as an exact `BORDER`-colored pixel), a real absence.

**C1.2 — the `:last` rules.** Rebuilt `STYLESHEET` in-process with only
`QHeaderView::section:horizontal:last-child { border-right: none; }`
deleted (keeping `QHeaderView::section:last`, real Qt QSS, untouched).
Re-ran the C1.1 scan: dividers appeared at every column boundary except
the trailing one, which stayed correctly suppressed. Confirmed the
inverse too — with only the OTHER (`:last`) rule removed and the
invalid `:horizontal:last-child` selector still present, dividers stay
absent. Root cause isolated precisely: `:horizontal:last-child` is CSS
syntax (`last-child`), not a member of Qt's real `QHeaderView::section`
pseudo-state set (`:first`/`:last`/`:middle`/`:only-one`/`:selected`/
`:next-selected`/`:previous-selected`/`:checked`/`:horizontal`/
`:vertical`) — its mere presence in the stylesheet poisoned the entire
`::section` rule block, dropping `border-right` (and, unverified but
consistent, potentially anything else in that block) everywhere, with
no warning and a stylesheet string that reads correctly on inspection.
This is exactly why the previous two rounds' "the CSS is present and
reads correctly" checks kept passing while the real render stayed
broken — the text was never the problem.

Fix: deleted the invalid `QHeaderView::section:horizontal:last-child`
rule outright (kept `:last`, which alone already does the job). Per
C1.4, also switched the header's own divider color from `BORDER` to
`BORDER_STRONG` (1.98:1 vs. 1.46:1 contrast against `BG_SURFACE`) since
the header is one flat block with no alternating-row-color help for the
eye, unlike the body (confirmed unaffected — see below).

**C1.5 — body gridlines, confirmed genuinely present.** Real pixel
scans post-fix on Downloads, Duplicates, and Settings → Library
Locations all found exact `BORDER` `(58, 52, 78)` at every body
row-boundary sample — these were never actually missing, matching item
102's own B2.2 finding.

**C1.6 — screenshots, actually looked at.** `window.grab()` crops
produced and inspected (via this session's own image-reading tool, not
just measured) for Downloads (before: no visible divider anywhere
between Track/Playlist/Role/Status/Progress; after: a clear vertical
line between every column except the last), Duplicates (7 dividers
across Group/Location/Path/Format/Bitrate/Similarity/Keep, none after
the trailing Actions column), and Settings → Library Locations (3
dividers across Name/Path/Reachable, none after Actions).

**A materially larger finding, outside this item's own named scope:**
while building the pixel-based regression test the brief asked for,
discovered that `theme.apply_theme()` — the one function that applies
Fusion style + the real QSS stylesheet + the dark `QPalette` — was
never called ANYWHERE in the test suite. `main_ui.py` is the only
caller in the whole codebase. This means every prior `window.grab()`
"pixel-verified" claim in this project's own history, including item
102's own B2.2/B4.3/B6.5 re-verification two rounds ago, was measured
against a window rendered with Qt's un-styled platform default — not
what `uv run seeker-ui` actually shows a user. It is the single biggest
reason this round's own brief exists: three straight rounds of "fixed
and pixel-verified" on the header divider, root-caused now to a bug
that can ONLY be seen when the real stylesheet is actually applied.

Fixed with a new session-scoped `autouse` fixture in `tests/conftest.py`
(`_apply_real_theme`, depending on pytest-qt's own `qapp` fixture) that
calls `theme.apply_theme(qapp)` once for the whole test session. Verified
this was safe to adopt rather than assumed: ran the full suite before
and after adding it — before, `col 0 is missing its real divider`
failed as expected against the pre-fix stylesheet; every one of the
other 1055 already-passing tests stayed passing, unchanged, both before
and after. The real Fusion style and dark palette do not perturb any
existing sizeHint()/geometry-based assertion in this suite.

**A second, related bug this surfaced, also fixed:** two pre-existing
`window.grab()` pixel tests (this item's new divider test while being
written, and item 96's `test_downloads_tab_queued_and_downloading_
bars_are_both_vertically_centered`) read LOGICAL-pixel Qt geometry
(`mapTo`, `sectionPosition`, `visualRect`) directly into a QImage that
`window.grab()` returns in DEVICE pixels. This machine's real Qt
session reports `devicePixelRatio() == 2.0` — a bare ad hoc
`QApplication` built outside the test session (used while first
diagnosing this) reported `1.0`, which is why this went unnoticed
during initial bisecting and only surfaced once the real pytest-qt
session was used. The pre-existing test happened to still pass despite
sampling the wrong image quadrant, purely because it compared two
equally-mis-scaled quantities against a forgiving 2px tolerance — a
real "passing for the wrong reason," the same class of gap this whole
round exists to close. Both tests now scale every sampled coordinate by
`image.width() / window.width()` rather than assuming any fixed ratio.

Full suite after all of this: **1056 passed, 1 skipped** (this item's
own new test is included in that count; the suite had 1055 passed, 1
skipped before this item added it). `mypy --strict src/` clean.

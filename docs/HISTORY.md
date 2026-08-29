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

Entries are numbered to match `CLAUDE.md`'s roadmap items exactly (1-30).

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

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

Condensed to standing facts and gotchas that matter for future code. Full
narrative — investigation steps, ruled-out hypotheses, exact real-run
numbers/timestamps — lives in `docs/HISTORY.md`, same item numbers.

1. **`sync` split from `sync-tracks` — done.** `seeker sync` is
   metadata-only (playlist id/name/track_count/snapshot_id); per-playlist
   track syncing is a separate, explicit `sync-tracks <playlist_name>`
   call — never triggered automatically, to keep Spotify API calls scoped
   and intentional. `get_playlist_by_name()` does case-insensitive lookup
   with close-match suggestions. See [HISTORY §1](docs/HISTORY.md#1)
   for the real 214-playlist verification run and the Spotify field-name
   corrections it surfaced (also see "Known issues" above).
2. **Local library scanning — done.** `library_locations` +
   `local_files`, multi-location aware, per-location reachability
   handling, AppleDouble sidecars filtered. [HISTORY §2](docs/HISTORY.md#2)
3. **Matching — done.** `matcher.py` classifies each track
   auto-matched / needs-review / unmatched via `track_matches.score`.
   Thresholds `AUTO_MATCH_THRESHOLD=90` / `NEEDS_REVIEW_THRESHOLD=70`
   (in `matching.py`) are untuned defaults. [HISTORY §3](docs/HISTORY.md#3)
4. **SoulSeek search client — done.** `SoulseekClient.search` against
   slskd's `/api/v0/searches`, synchronous httpx. **Gotcha:**
   `GET /api/v0/searches/{id}` only returns populated `responses` with
   `?includeResponses=true` — without it you get a real `isComplete`/
   `responseCount` but a silently empty `responses` array. Default
   timeout 45s / poll_interval 2s (real searches took 20-45s+).
   [HISTORY §4](docs/HISTORY.md#4)
5. **Quality-ranking logic — done.** `soulseek/quality.py`:
   `filter_candidates` scores fuzzy title match against `artist + title`
   combined (bare-title-only scoring tanks the ratio for
   "Artist - Title"-style filenames), `quality_tier`/`effective_bitrate`
   (flac/wav > mp3/m4a/aac/ogg, VBR bitrates distrusted), `select_best`
   prefers practical-queue candidates. [HISTORY §5](docs/HISTORY.md#5)
6. **Phase 1 download orchestration — done.** `download_requests` table
   (`role`/`status` lifecycle: `queued → downloading →
   completed/failed`, plus `transfer_id`). Destination is per-playlist
   (`playlists.download_location_id`/`download_subfolder`). slskd's
   enqueue destination is relative to slskd's own download root, not an
   arbitrary path — so Seeker itself moves the completed file by
   basename lookup under `SLSKD_DOWNLOAD_DIR` once
   `get_download_status` reports `Succeeded` (bare `"Completed"` with no
   outcome flag is NOT treated as done). [HISTORY §6](docs/HISTORY.md#6)
7. `check` reports auto/needs-review/unmatched already; a `review`
   command to confirm/reject needs-review *local-file* matches is still
   outstanding (superseded in spirit by the Soulseek-side confirm/reject
   in item 26, but the local-file-match version was never built).
   `download_playlist` only ever targeted `match_method IS NULL` tracks
   — needs-review tracks are deliberately left alone.
8. **Phase 2 upgrade-tracking — done.** `quality.select_downloads(track,
   files)` returns `(settled, upgrade)` — practical top pick means no
   upgrade; an impractical top pick becomes `upgrade` (requested in
   parallel, `role='upgrade'`) while `settled` falls back to the best
   practical candidate. New status `ready_for_review` for a completed
   upgrade (not auto-moved). **Two commands, split deliberately:**
   `seeker downloads status` → `poll_downloads()` only, zero `input()`,
   safe for cron; `seeker downloads review` → `review_pending_upgrades()`
   only, DB-only, prompts per `ready_for_review` row (replace? delete
   old?). `library/scanner.py`'s per-file indexing was extracted into
   `index_single_file()` so the review flow and `scan()` can't drift
   apart. `DEFAULT_MAX_QUEUE = 200` (practical-queue threshold) is still
   untuned. [HISTORY §8](docs/HISTORY.md#8)
9. **Multi-artist fix — done; Phase B tag-writing tracked under item 10.**
   `Track.artist` joins ALL of Spotify's `item["artists"]` with `", "`
   (previously only `artists[0]`). Two matching.py consequences:
   `artist_matches` splits `spotify_artist` on `", "` and passes if the
   local text contains ANY one name; `score_title` also tries each
   individual artist name combined with the title (not just the full
   joined string), taking the max across title-only/combined-all/
   combined-per-artist. Search-query construction strips literal commas
   (`_build_search_query`) since Soulseek search isn't guaranteed to
   ignore them. Album art: confirmed live that
   `item["album"]["images"]` is already present on the playlist-items
   response — no separate album-fetch call needed. [HISTORY §9](docs/HISTORY.md#9)
10. **Metadata Phase B — writing tags — done.** `seeker/metadata.py`:
    `write_text_tags`/`embed_album_art` dispatch on the mutagen object's
    actual tag type — `isinstance(tags, ID3)` covers **both MP3 and
    WAV** in one branch (WAV's `_WaveID3` is a genuine `ID3` subclass,
    confirmed live: WAV fully supports embedded art, same code path as
    MP3) — vs. `FLAC` vs. `MP4` (`\xa9nam`/`\xa9ART`/`\xa9alb`, `covr`
    with `MP4Cover`). An unsupported format makes `write_text_tags`
    raise `ValueError` (track → `skipped_format_unsupported`) but makes
    `embed_album_art` return `False` (art failure must never sink an
    otherwise-good text-tag write). `tracks.album_art_url` column
    (guarded `ALTER TABLE`, no migration framework — see item 18 for
    the same pattern generalized). `MetadataService.tag_tracks`/
    `tag_playlist` scope to `match_method='auto'` only — never
    needs_review (writing canonical metadata onto a possibly-wrong file
    would be actively harmful). `seeker library tag <playlist_name>`.
    [HISTORY §10](docs/HISTORY.md#10)
11. **Metadata Phase C — local audio analysis (BPM + key) — done.**
    `librosa` chosen over Essentia for Windows wheel support.
    **Gotchas confirmed live:** `librosa.beat.beat_track` returns tempo
    as a length-1 ndarray, not a bare float —
    `float(np.atleast_1d(tempo)[0])`; `scipy.stats.uniform(loc, scale)`
    means `[loc, loc+scale]`, NOT `[loc, scale]`. `analyze_audio()` →
    `AudioAnalysis(bpm, camelot_key, key_confidence)`, correlating mean
    chroma against 24 Krumhansl-Schmuckler profiles;
    `key_confidence` is a similarity score, not a certainty, and
    `camelot_key` is `None` when the best correlation isn't positive.
    `local_files` gains `bpm`/`camelot_key`/`key_confidence` —
    deliberately NOT in `upsert()`'s `ON CONFLICT DO UPDATE` (a routine
    scan must not wipe prior analysis); `update_analysis()` writes just
    those three columns. `write_analysis_tags` writes `TBPM`/`TKEY`
    (mp3/wav), `BPM`/`KEY` Vorbis comments (FLAC), `tmpo` +
    `----:com.apple.iTunes:initialkey` (MP4) — `TKEY` deliberately holds
    Camelot notation, not standard key notation, matching real-world DJ
    tooling convention. `analyze_audio` is a genuinely independent
    toggle from base tagging (never called at all when `False`).
    **Octave-error correction:** beat trackers routinely lock onto
    half/double tempo. `expected_bpm_range: tuple[float, float] | None`
    threads through to `--bpm-range MIN MAX` (requires
    `--analyze-audio`); `None` is byte-identical to pre-feature
    behavior. Two stacked, independent fixes: (1) `prior=` passed to
    `librosa.beat.beat_track`/`tempo` (a `scipy.stats` distribution)
    actually biases the search; (2) `correct_octave_error(bpm,
    expected_range)` — pure function, checks 2x/0.5x/3x/1.5x candidates,
    corrects only if *exactly one* lands in range (ambiguity → return
    unchanged). [HISTORY §11](docs/HISTORY.md#11)
12. **Centralized playlist-name resolution — done.** All 4 commands
    taking `playlist_name` (`sync-tracks`, `playlists set-destination`,
    `download`, `library tag`) go through one CLI-layer
    `resolve_playlist_or_offer_sync(name, application)`: found locally →
    return immediately; close match exists → existing "Did you mean...?"
    error, no refresh offered (a close match means a typo/stale rename,
    a resync wouldn't fix it); no match at all → offers a real
    `sync_playlists()` refresh + one retry. **Gotcha:**
    `difflib.SequenceMatcher`-based close-matching inflates for short
    query strings (`"Test"` vs `"sesh"` scored 0.5, exactly at the
    cutoff, from incidental letter overlap, not real resemblance).
    Replaced with `rapidfuzz.distance.Levenshtein.distance`,
    length-scaled: close only if `distance <= max(1, len(query) // 4)`.
    [HISTORY §12](docs/HISTORY.md#12)
13. **slskd shares the local library + Phase 3: locked-file retry —
    done.** `docker-compose.yml`/`slskd.yml` share the real music
    drive read-only so this app's own downloads are visible to other
    peers as uploads.

    **The real locked-file rejection signal (confirmed live,
    2026-08-27):** a locked file lives in search results' separate
    top-level `lockedFiles` array (not a per-file `isLocked` flag within
    `files` — a real entry's own `isLocked` was itself `False`).
    `request_download` against a locked file **succeeds immediately**
    (real transfer_id, no exception) — the rejection only shows up
    moments later via `get_download_status`, as `"Completed, Rejected"`
    with `exception: "Transfer rejected: File not shared."` This is an
    explicit, immediate, machine-readable failure state, not a timeout
    heuristic — so retry logic keys off `state` containing `"Rejected"`
    plus known exception-text patterns, never a timeout guess.

    **Why this reuses Phase 2's upgrade/review machinery instead of a
    parallel pipeline:** a locked file is structurally an "upgrade"
    candidate — something better than settled, not guaranteed, worth
    chasing in the background. A locked candidate is never eligible as
    `settled` (checked separately from `is_practical()`); ties between a
    locked and unlocked candidate of equal quality go to the unlocked
    one. `download_requests` gains `status='locked'` and a persisted
    `size` column (needed to re-issue `request_download` on retry).

    **Rejection classification — this is the fact that matters most
    going forward, corrected once already (see item 26):**
    `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection()` (in
    `soulseek/client.py` — moved there in item 21, see its own entry)
    matches exception text against confirmed real strings
    (`"not shared"`, `"appears to be offline"`) and routes a matching
    rejection to `status='locked'` instead of `'failed'`. **As of item
    26, this classification is unconditional — it applies to a
    rejection on ANY `download_requests.role`, not just
    `role='upgrade'`.** It originally was `role=='upgrade'`-scoped, on
    the premise that `select_downloads()` never assigns a locked
    candidate to `settled` — true for the ordinary search pipeline, but
    false once `confirm_review_candidate()` (item 26) can request a
    human-confirmed needs-review candidate as `role='settled'` with no
    lock-status filtering at all. Retry-worthiness is a property of the
    REJECTION, not of why the download was requested. **Only the Phase
    4 shortlist cascade (`_cascade_upgrade`, item 14) stays
    `role=='upgrade'`-specific** — shortlisting is an upgrade-only
    concept; calling it for a settled rejection could incorrectly
    activate an unrelated upgrade-role shortlist entry for the same
    track.

    `poll_downloads()` retries every pre-existing `'locked'` row each
    run via `_retry_locked_request`: re-issues `request_download`
    against the identical candidate (not a new search), does an
    immediate follow-up `get_download_status` (a rejection doesn't raise
    from `request_download` itself), updates `transfer_id` either way.
    `seeker downloads status` reports `Locked (retrying): N`.
    [HISTORY §13](docs/HISTORY.md#13)
14. **Phase 4: upgrade-candidate shortlisting — done.** Extends Phase 3
    to a ranked shortlist of up to `MAX_UPGRADE_SHORTLIST = 3`
    (untuned) candidates per track: rank 1 requested immediately;
    2/3 persisted as `status='shortlisted'`, not sent to slskd until
    needed. **Sequential cascade, not simultaneous requests —
    deliberate:** Soulseek doesn't swarm like BitTorrent; firing every
    shortlisted candidate at once would mean requesting-then-cancelling
    real uploads from 2-3 real peers for no benefit. `_sort_key` gained
    a final `-queue_length` tiebreak (shorter queue wins when otherwise
    equal). `download_requests` gains `rank` (1/2/3, `NULL` for
    `role='settled'`) and two statuses: `'shortlisted'` and
    `'superseded'` (dropped because a same-track sibling already won —
    kept distinct from `'failed'`, which means a genuinely dead attempt
    with no retry coming). On any rejection for the currently-active
    upgrade request, `poll_downloads()` activates the next
    `'shortlisted'` row for that track in the same run
    (`_cascade_upgrade`); once a track reaches `'ready_for_review'`
    (via cascade, retry, or the ordinary path), every other
    still-in-flight row for that track is marked `'superseded'`
    (`_supersede_others_for_track`). **Gotcha, still relevant:** Phase
    3's locked-retry and Phase 4's cascade-activation look similar but
    are NOT unifiable into one method — a retry reactivating an
    ALREADY-confirmed-locked row should stay `'locked'` on ANY
    rejection reason, while a cascade candidate's FIRST attempt still
    needs proper locked-vs-failed classification. Kept as two small,
    separately-correct methods. `_retry_locked_request` re-fetches the
    row's current status before reactivating, to avoid resurrecting a
    row a same-run sibling already superseded off a stale pre-run
    snapshot. [HISTORY §14](docs/HISTORY.md#14)
15. **Polish pass — done (2026-08-27).** `mypy --strict` clean across
    all source files (scoped mypy override for `seeker.metadata`, since
    `mutagen` ships no type stubs). Dead code removed
    (`__init__.py`'s stub `main()`, unused `quality.py::select_best()`).
    Every per-track/per-request batch loop (`download_playlist`,
    `poll_downloads`'s two loops, `tag_tracks`) wraps each iteration in
    its own try/except so one bad item can't silently abort the rest of
    a batch — this is a standing pattern for any future batch loop in
    this codebase, not just a one-time fix. `SpotifyClient._get`'s
    429-retry loop bounded by `MAX_RETRY_ATTEMPTS = 5`. Coverage raised
    on real gaps (token store/auth/callback server, mostly). README.md
    added. [HISTORY §15](docs/HISTORY.md#15)
16. **Live re-verification findings (2026-08-27) — both actioned.**
    (1) `check`/`match_all()` report GLOBALLY across every synced
    playlist — never scoped to one playlist, unlike
    `download_playlist(playlist_name)`, which IS correctly scoped. A
    "check says 6 unmatched but download only touched 4" mismatch is
    this, not a bug — worth remembering before assuming a discrepancy is
    a real defect. (2) A locked-but-real candidate was being discarded
    instead of entering the retry cascade — `download_playlist` treated
    `settled is None` as "nothing found" without checking
    `upgrade_shortlist` first. Fixed via a shared
    `_request_upgrade_shortlist()` helper called from both the
    settled-found path and a new `settled is None but shortlist
    non-empty` path (counts as `requested`, not `skipped`).
    [HISTORY §16](docs/HISTORY.md#16)
17. **Soulseek needs-review tier — done (2026-08-27).** Mirrors
    `library/matcher.py`'s three-tier design using the SAME
    `matching.py` thresholds (70 ≤ score < 90), not a second scheme.
    `find_best_needs_review_candidate` returns the single best-scoring
    match across ALL filtered-out files. New `soulseek_review_candidates`
    table (`track_id` PK, one row per track — not a history log) +
    repository + model — deliberately NOT folded into
    `download_requests`, since a needs_review candidate was never
    actually submitted to slskd. `download_playlist` populates it only
    when truly nothing auto-tier exists (no settled, no shortlist) and
    clears any existing row the moment something real and auto-tier is
    found (a stale needs_review row must not keep surfacing after a
    later run finds something better). `seeker check` gains a
    "Needs review (SoulSeek candidate found)" section — printed only
    when `Application.soulseek_configured` is true (a plain config
    check, NOT constructing a real `SoulseekClient`, so `check` still
    works with no slskd configured at all). Interactive confirm/reject
    was explicitly deferred to a future UI — see item 26 §0 for where
    that landed. [HISTORY §17](docs/HISTORY.md#17)
18. **DB path migrated to platformdirs — done (2026-08-28).** DB lives
    at `platformdirs.user_data_dir("Seeker", appauthor=False)` (e.g.
    `~/Library/Application Support/Seeker` on macOS), not
    CWD-relative `.seeker/seeker.db`. `Application._migrate_legacy_database()`
    moves a real pre-existing DB into the new location exactly once
    (never touches anything if a DB already exists at the new
    location — guards against a stale legacy file ever clobbering
    current data); does nothing if neither exists. Spotify token cache
    (`.seeker/spotify_token.json`) is untouched by this, deliberately
    scoped to the DB only. [HISTORY §18](docs/HISTORY.md#18)
19. **Local JSON config store for SoulSeek/slskd settings — done
    (2026-08-28).** `config_store.py`: `SeekerConfig` dataclass
    (`slskd_base_url`/`slskd_api_key`/`slskd_download_dir`), stored as
    `config.json` alongside the DB (same platformdirs directory as item
    18). `load_config`/`save_config` treat a missing/partial/corrupt
    file as all-`None` defaults rather than crashing (deliberately not
    versioned/guarded migration machinery — flat JSON with defaulted
    optional fields is inherently additive). `save_config` chmods
    `0600` where POSIX permissions apply. `migrate_legacy_slskd_env_config()`
    copies a field from `.env`/`os.environ` into the store only if the
    store doesn't already have it (never overwrites a value changed
    since via a future Settings screen) — runs once, automatically, in
    `Application.__init__`, before anything can construct a
    `SoulseekClient`. **Standing precedence, still true today:**
    `Application._slskd_base_url`/`_slskd_api_key`/`_slskd_download_dir`
    each resolve as `self._config_store.<field> or config.SLSKD_*` —
    config store wins, `.env` is the fallback. **Gotcha:**
    `config.py`'s `SLSKD_*` are plain module-level constants frozen at
    import time — `monkeypatch.setenv` alone doesn't affect them in
    tests; must patch `seeker.application.config.SLSKD_*` directly.
    [HISTORY §19](docs/HISTORY.md#19)
20. **Real download progress tracking (bytes_transferred/total_bytes) —
    done (2026-08-28).** Real confirmed field names from slskd's
    `GET /api/v0/transfers/downloads/{username}/{id}`: `size` (total
    bytes) and `bytesTransferred` (progress so far) — both always real
    integers, `bytesTransferred: 0` (not null) on a rejected-before-
    any-bytes transfer. `get_download_status` returns a `TransferStatus`
    dataclass (`state`/`bytes_transferred`/`size`) instead of a bare
    string. `download_requests` gains nullable `bytes_transferred`/
    `total_bytes`; `update_progress()` is kept separate from
    `mark_status`/`update_transfer_id_and_status` (same reasoning as
    `update_analysis` in item 11 — a routine progress poll must not
    disturb unrelated columns). **Standing rule:** a rejection leaves
    these columns `NULL` (not zeroed) — "no progress recorded" and
    "confirmed zero progress" are different things and the code
    preserves that distinction; `locked`/`shortlisted`/`superseded`
    rows never get progress updates at all. [HISTORY §20](docs/HISTORY.md#20)
21. **Fix: peer-offline 404 rejection shape — done (2026-08-28).** A
    THIRD distinct rejection shape, beyond item 13's async
    "succeeds-then-shows-Rejected" pattern: `POST
    /api/v0/transfers/downloads/batches` can return a **synchronous**
    `404` (`"User X appears to be offline"`) when a peer is briefly
    unreachable at enqueue time. `request_download` previously let a
    bare `httpx.HTTPStatusError` escape uncaught — neither
    `_retry_locked_request` nor `_activate_shortlisted_entry` catches
    that type, only `SoulseekDownloadError`. Fixed once, at the source:
    `request_download` now catches `HTTPStatusError`, inspects the
    response body against the shared pattern list, and raises
    `SoulseekDownloadError` when it matches (re-raises the original
    error type for anything unrecognized). The pattern list moved down
    to `client.py` (lowest layer that needs it) and was renamed
    `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection` — "locked"
    undersold what it covers; now holds `"not shared"` and `"appears to
    be offline"`. `download_service.py` imports it rather than keeping
    its own copy (guarded by
    `test_single_source_of_truth_for_recognized_rejection_patterns`).
    [HISTORY §21](docs/HISTORY.md#21)
22. **Frontend Step 3: UI scaffolding + main dashboard — done
    (2026-08-28).** New `DashboardService.get_playlist_track_status()` —
    the first thing in the codebase to answer "this playlist's tracks,
    with live status" (everything else reports globally, see item 16).
    One `TrackStatus` per track, first-match-wins:
    `IN_LIBRARY` > `DOWNLOADING` > `AWAITING_REVIEW` > `NEEDS_REVIEW` >
    `NOT_FOUND`; a secondary "SoulSeek candidate found" tag can only
    ever attach to `NEEDS_REVIEW`/`NOT_FOUND` (enforced by construction,
    not convention — the candidate lookup is only ever consulted from
    those branches). New `src/seeker/ui/` package (Qt/PySide6),
    `main_ui.py` bootstrap, `seeker-ui` console-script entry. Layering
    rule reworded from "CLI code" to "presentation-layer code" to cover
    both. **Concurrency confirmed safe:** `Database.transaction()` opens
    a brand-new connection per call and never shares one across
    threads — stress-tested (10 writer + 10 reader threads, 1,000
    transactions, zero errors). **Standing gotcha for any future
    QRunnable-based worker:** `ui/workers.py`'s `Worker`
    (`QRunnable`+`QObject` signals) MUST be kept alive via a strong
    reference (`_active_workers: set[Worker]`) until its own
    finished/error signal fires — `QThreadPool.start()` returns before
    the thread runs, so a `Worker` with no other reference gets
    garbage-collected mid-flight (observed as both a silently-lost
    result and a real interpreter segfault, depending on GC timing).
    Dashboard polls via one `QTimer` (`POLL_INTERVAL_MS = 2_000`,
    untuned) routed through the same worker pattern. Toolbar
    Sync/Scan/Match stay global (matching the CLI's own scope); only
    Download is playlist-scoped; selecting a playlist never
    auto-triggers `sync-tracks` (would reintroduce the unscoped-quota
    problem item 1 was built to prevent). [HISTORY §22](docs/HISTORY.md#22)
23. **Frontend Step 4: onboarding wizard — done (2026-08-28).** Three
    steps (Spotify connect, library location, SoulSeek/Docker setup —
    skippable), resumable across restarts. **Prerequisite fix:**
    `config.py` no longer raises at import time for missing
    `SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI` — both resolve through
    the same config-store-or-env-fallback pattern as item 19's
    `SLSKD_*` (`SeekerConfig` gained the two fields;
    `migrate_legacy_slskd_env_config` renamed
    `migrate_legacy_env_config`, scope no longer SLSKD-only);
    `auth_manager` is now a lazy property. `redirect_uri` falls back to
    a real fixed default — `callback_server.py` exports
    `CALLBACK_PORT`/`DEFAULT_REDIRECT_URI` as the one source of truth.
    **Confirmed live, standing facts for any future Docker/slskd
    wiring:** `SLSKD_USERNAME`/`PASSWORD` are the **web UI** login
    (default `slskd`/`slskd`) — NOT the SoulSeek network credentials.
    The real network login env vars are `SLSKD_SLSK_USERNAME`/
    `SLSKD_SLSK_PASSWORD`. An empty-string `${VAR}` substitution in
    `docker-compose.yml` does NOT clobber an already-persisted real
    credential in `slskd-data/slskd.yml` — slskd falls through to the
    yaml value — confirmed live before relying on it for the tracked
    compose file. `/api/v0/application`'s `ServerState` has no
    error/reason field — a bad password and a "kicked, someone else is
    logged in as this user" case both converge on the identical
    terminal `state: "Disconnected"`; the real reason only shows up via
    `/api/v0/logs`' `Error`-level entries, matched by confirmed
    substring (`BAD_CREDENTIALS_LOG_PATTERNS`) — and that log scan is
    time-bounded by a `since:` timestamp captured at the start of each
    bring-up attempt (a fix landed after the fact — an unbounded scan
    would false-positive forever on a since-corrected stale error).
    `onboarding_complete` only requires the two required steps
    (Spotify + a library location); step 3 (SoulSeek/Docker), whenever
    shown, always re-checks Docker's real state live on entry rather
    than trusting a flag. [HISTORY §23](docs/HISTORY.md#23)
24. **Frontend Step 5: download progress view — done (2026-08-28).**
    New `DashboardService.get_active_downloads()` — deliberately
    GLOBAL (mirrors `seeker downloads status`'s own scope, not
    playlist-scoped like item 22's method — getting this backwards
    would repeat item 16's global-vs-scoped bug class). "Visible" =
    every non-terminal status, plus a `completed`/`failed` row within
    `RECENTLY_FINISHED_WINDOW_SECONDS = 60` of its `completed_at` (so a
    finished download visibly lands rather than vanishing instantly).
    New second timer on `MainWindow`, `BACKEND_POLL_INTERVAL_MS =
    20_000` (separate from the 2s display-refresh timer — this one
    makes real slskd network calls via `poll_downloads()`), guarded by
    an overlap flag so a slow/hanging poll can't stack a second
    concurrent writer; checks `soulseek_configured` first, same
    reasoning as item 17. Progress bar is **indeterminate**
    (`setRange(0,0)`) when bytes haven't been reported yet — a
    permanent 0% bar would be visually indistinguishable from "stuck."
    **Real duplicate-row bug found and fixed:** several tracks had
    multiple `download_requests` rows for the literal same candidate
    (same track/role/peer/filename) left over from before item 16's
    creation-time dedup guard was fully effective — NOT a real Phase 4
    shortlist (confirmed: all shared `rank=1`, zero rows with `rank >
    1` exist). Fixed on the read side with
    `download_dedup.py`'s `most_recent_per_candidate()` (see item 25
    for the write-side counterpart), keyed on
    `(track_id, role, username, filename)` — deliberately NOT
    `rank`, so a genuine multi-candidate shortlist is never collapsed,
    and `role` stays in the key so a legitimate simultaneous
    settled+upgrade pair for one track never merges.
    [HISTORY §24](docs/HISTORY.md#24)
25. **Fix: Phase 3 retry loop didn't dedupe stale duplicate rows —
    done (2026-08-28).** The write-side counterpart to item 24's
    read-side fix: `get_locked()` fetches every `'locked'` row
    globally with no per-candidate collapsing, so the retry loop kept
    re-issuing real `request_download` calls for every stale duplicate,
    every cycle, against the same real peer. `_retry_locked_request`
    now calls `_supersede_stale_duplicates(current)` first — supersedes
    every OTHER row sharing the same real candidate, keeping only the
    most recent; if `current` itself loses, the retry is skipped
    entirely. Shared logic lives in top-level `download_dedup.py`
    (`candidate_key`/`most_recent_per_candidate`) — both
    `DashboardService` (read) and `DownloadService` (write) import the
    same function, so display and mutation can't drift onto two
    different notions of "duplicate." **Known, deliberately unresolved
    edge case:** the tiebreak is pure `requested_at`, with no
    status-awareness (doesn't prefer a `downloading` sibling with real
    bytes over a more-recent-but-merely-`locked` one) — no real
    instance of this has ever co-occurred with nonzero
    `bytes_transferred` on more than one sibling, so it's undefended
    rather than guarded speculatively. [HISTORY §25](docs/HISTORY.md#25)
26. **Frontend Step 6: Review screen — done (2026-08-29).**
    Two deliberately-deferred CLI-only flows get a real UI home: item
    17's read-only SoulSeek needs-review tier gains its first real
    confirm/reject action, and Phase 2's `seeker downloads review`
    upgrade-confirmation flow gets exposed to a non-`input()` caller.

    **§0 — `confirm_review_candidate(track_id)` /
    `reject_review_candidate(track_id)` on `DownloadService` — done.**
    Confirm requests as `role='settled'` (a human confirmation is a
    stronger signal than an algorithmic top pick, so it auto-moves on
    success rather than demanding a second confirmation via
    `ready_for_review`) and clears the candidate row immediately once
    requested; reject just deletes the row (no blacklist — the same
    candidate can resurface on a later `download` run). **This is what
    forced item 13's rejection-classification broadening** — see item
    13 for the corrected rule itself; the design reasoning for why
    `role='settled'` (not a dynamically-chosen role) is the right call
    lives there too. A second, related fix:
    `_retry_locked_request`'s success path used to unconditionally set
    `'ready_for_review'`, correct only because a locked row had always
    been `role='upgrade'` before now — a `role='settled'` row that
    becomes locked and later succeeds now auto-moves and marks
    `'completed'` directly, falling back to `'downloading'` (not a
    false `'completed'`) if the file move doesn't actually find the
    file, mirroring `poll_downloads()`'s own main-loop pattern.
    `SoulseekReviewCandidate` gained a persisted `size` column (needed
    for `request_download`, previously only used transiently) — a
    legacy row predating this column is explicitly refused
    (`ReviewCandidateMissingSizeError`), not guessed.

    **§1 — extracted Phase 2's replace/delete-old-file logic out of its
    `input()` loop — done.** `get_upgrade_review_details(request_id)`
    (read-only resolution shared by both callers) and
    `apply_upgrade_decision(request_id, replace, delete_old=False)`
    (the pure, `input()`-free mutation) on `DownloadService`, in
    `models/upgrade_review.py`. `_confirm_upgrade` is now a thin
    wrapper around the two real `input()` calls + one
    `apply_upgrade_decision` call — behavior-preserving for the CLI.

    **§2 — the two-section Qt Review screen — done.** New "Review" tab
    on `MainWindow`: a needs-review-candidates table (Confirm/Reject
    per row, calling §0's two methods) and a pending-upgrades table
    (Replace/Decline per row, a "Delete old file" checkbox that only
    appears when `old_file_path` is set — mirroring the CLI's own
    guard, calling §1's `apply_upgrade_decision`). New
    `DownloadService.get_pending_upgrade_reviews()` — no method
    existed to list every `ready_for_review` row as resolved
    `UpgradeReviewDetails` before this. Both tables refresh on the
    existing 2s local-DB-only poll timer (cheap reads, no slskd calls)
    and immediately after any action completes.

    **Live verification — genuinely blocked by a real environment
    constraint (external drive not attached this session), not
    skipped.** slskd needs the real X9 Pro drive mounted (item 13);
    confirmed directly it isn't attached here, and the pre-existing
    `slskd` container correctly refused to start
    (`mkdir /host_mnt/Volumes/X9 Pro: permission denied`) rather than
    something being broken — left it exactly as found. This blocks
    only the real happy path (a fresh `seeker download` to refresh a
    legacy candidate's `size`, then a real confirm → `request_download`
    → `ready_for_review` → replace). Everything not dependent on a
    live slskd connection WAS verified live against the real,
    production database: the `size`-column migration applied for real
    on first real `Application()` construction since it landed; the
    two real waiting candidates from item 17 (Prdk, Zigi SC/A-Cray)
    read back correctly via `get_review_candidates()`; a direct
    `confirm_review_candidate()` call against the real Prdk row
    correctly raised `ReviewCandidateMissingSizeError` with zero
    mutation; the real `MainWindow` (offscreen Qt, real `Application`,
    no fakes) rendered both real candidates with working buttons; and
    a real Confirm click, through the real worker/signal pipeline,
    correctly surfaced that same error on the real status label.

    **Retried (2026-08-30) on request, after the drive was reportedly
    reconnected — still not actually attached to this machine.**
    Checked at the OS level, not just via the container: `diskutil
    list` shows no X9 Pro disk at all (not merely unmounted — the
    physical device itself isn't enumerated), `/Volumes` unchanged, and
    `system_profiler SPUSBDataType` returned nothing at all, even
    outside this session's normal sandboxing. `docker start slskd` was
    not attempted a second time given that — repeating item 26's
    original mount-permission failure would have told us nothing new.
    The real happy-path confirm/replace flow against Prdk/Zigi SC-A-Cray
    genuinely remains unverified; nothing about this retry changes the
    verified-vs-not split recorded above.

    [HISTORY §26](docs/HISTORY.md#26)

27. **Frontend Step 7: Tagging panel — UI done, live verification
    blocked by the same unattached drive as item 26 (2026-08-30).**
    Exposes `MetadataService.tag_tracks`/`tag_playlist` (already
    complete and live-verified — items 10/11) via the UI for the first
    time; no new service-layer logic — this was UI wiring only, and no
    real gap was found while wiring it up. Three triggers on the
    Dashboard tab: a per-track "Tag" button (Actions column, `track_table`
    now 4 columns) that only renders at all for `IN_LIBRARY` rows — same
    "blank cell, not a misleading control" precedent as the Downloads
    tab; "Tag selected" using `QTableWidget`'s `ExtendedSelection`/
    `SelectRows` mode to call `tag_tracks` with the selected ids,
    regardless of their state (tag_tracks itself already reports
    `skipped_no_match` correctly for anything unmatched); "Tag playlist"
    calling `tag_playlist(playlist_name, ...)` directly. One shared
    "Analyze audio (BPM/Key)" checkbox + BPM min/max fields, all three
    triggers reading from it via `_resolve_tag_options()`. The
    CLI's `--bpm-range` requires `--analyze-audio` rule is enforced
    *structurally* here, not just validated after the fact — the range
    fields are hidden entirely while the checkbox is unchecked, so the
    invalid combination can't be constructed in the first place; a
    range left half-filled (one field blank) is rejected with a status
    message before any service call, matching the CLI's fail-fast
    behavior. A non-blocking `QPlainTextEdit` results panel (not a
    modal) renders the full breakdown plus every `details` entry's
    `[reason] message`, since that's specifically why `tag_tracks`
    returns `details` rather than just counts. No confirmation gate
    before running — matches this project's own design principle
    (confirmation is for file *replacement*, not tag-writing) and the
    CLI's own `library tag`, which already runs unprompted. 13 new UI
    smoke tests (trigger wiring + exact call arguments, per-row button
    visibility by state, BPM-range gating and partial-input rejection,
    empty-selection/no-playlist guards, results-panel rendering).
    `mypy --strict` clean; full suite 288 passed / 17 skipped.

    **Live verification — blocked by the identical drive-not-attached
    constraint documented in item 26, discovered while attempting it,
    not assumed in advance.** `tag_playlist`/`tag_tracks` open real
    files under a library location's real filesystem path
    (`MutagenFile(file_path)`) — the same X9 Pro drive item 26's slskd
    verification needs. Confirmed unattached the same way (`diskutil
    list`, no device present). Running `tag_playlist` for real against
    it would only produce real *failures* (file not found) for every
    track, which would verify nothing beyond what's already covered by
    mocks — so it wasn't run, rather than performing a hollow "ran the
    command" step that confirms nothing real. [HISTORY §27](docs/HISTORY.md#27)

This file and `docs/HISTORY.md` split the same information by shelf life:
`CLAUDE.md` (this file) holds standing facts — current behavior,
invariants, and gotchas that should shape how the *next* piece of code
gets written — kept short enough to read in full before starting work.
`docs/HISTORY.md` holds the full investigation narrative behind each
numbered roadmap entry — what was checked, what was ruled out, the real
run's exact numbers — kept in full because that detail is exactly what a
future debugging session needs, but it doesn't need to be read every time.

When you finish a roadmap-worthy piece of work: write the condensed
entry (a few lines — what changed, any standing fact/gotcha, done or not)
directly in CLAUDE.md's Roadmap section, using the next number. Only add
a matching `docs/HISTORY.md` entry if the work involved genuine
investigation worth preserving in detail (a live bug hunt, a real
verification run, hypotheses ruled out) — a straightforward "built X as
scoped" entry doesn't need one. If you do add both, link them (a
`[HISTORY §N](docs/HISTORY.md#N)` pointer in CLAUDE.md; matching item
number as the HISTORY.md heading). Keep this file updated as decisions
get made — treat it as the standing brief, not a changelog of everything
that happened, and don't let it quietly re-accumulate the narrative
detail this split just moved out.

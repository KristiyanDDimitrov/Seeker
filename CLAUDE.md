# seeker

Personal DJ music library management assistant. Syncs Spotify playlists to a
local SQLite cache (to minimize API calls against Spotify's rate/quota
limits), matches cached tracks against a scanned local library, and — for
whatever's missing — searches SoulSeek (via a self-hosted `slskd` daemon)
to identify and download the highest-quality available file for each
track, then tags matched files with Spotify's canonical metadata. Ships
both a CLI (`seeker`) and a desktop GUI (`seeker-ui`, PySide6) over the
same service layer — see README.md for the full command/screen reference.

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
│   ├── metadata_service.py   # tag_tracks/tag_playlist — writes Spotify
│                              #   metadata + art onto matched local files
│   └── duplicate_service.py  # fingerprint-based duplicate clustering +
│                              #   the group-resolution delete action (item 40)
├── ui/                        # seeker-ui (PySide6) — presentation layer,
│                              #   same layering rule as cli.py
│   ├── main_window.py         # dashboard (tagging panel) + Downloads/
│                              #   Review/Duplicates tabs, all on the same
│                              #   QTimer-driven poll pattern
│   ├── wizard.py               # onboarding: Spotify / library / SoulSeek
│   ├── settings_window.py      # locations, destinations, connection
│                              #   management, editable thresholds
│   ├── library_location_picker.py  # folder-picker, shared by wizard +
│                              #   Settings — see roadmap item 28 §1
│   ├── download_eta.py         # per-download speed/ETA tracker (item 33)
│   ├── help_text.py            # centralized tooltips/subtitles/About copy
│                              #   (item 34), incl. SUPPORT_LINKS (item 35)
│   └── workers.py              # QThreadPool Worker + run_worker() — every
│                              #   long-running UI action goes through this
├── models/{playlist,track,track_match,local_file,library_location,
│           soulseek_file,download_request,soulseek_review_candidate,
│           active_download,track_status,upgrade_review}.py
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
├── audio_fingerprint.py       # project-owned libchromaprint ctypes binding
│                              #   — compute_fingerprint/similarity_from_
│                              #   decoded, used by duplicate_service.py
│                              #   (item 39)
├── audio_formats.py         # AUDIO_EXTENSIONS, shared by scanner + quality
├── dashboard_service.py       # DashboardService — playlist-scoped track
│                              #   status + global active-downloads listing;
│                              #   the one thing ui/ needed that no
│                              #   existing service provided (item 22)
├── config_store.py            # SeekerConfig — the UI-editable JSON store
│                              #   (config.json); .env/config.py is now
│                              #   only the fallback when a field is unset
├── docker_setup.py            # Docker/slskd detection, bring-up,
│                              #   health checks — shared by wizard.py and
│                              #   settings_window.py
├── download_dedup.py          # candidate_key/most_recent_per_candidate —
│                              #   shared by DownloadService (write) and
│                              #   DashboardService (read), see item 25
├── file_deletion.py           # shared safe-file-delete primitive —
│                              #   DownloadService (upgrade replace) and
│                              #   DuplicateService (item 40) both use it
├── config.py                  # .env-sourced fallback values
├── application.py
├── cli.py
├── main.py                    # `seeker` entry point
└── main_ui.py                 # `seeker-ui` entry point
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
uv run seeker-ui       # run the GUI (PySide6) — onboarding wizard on first launch
uv run pytest         # run tests
uv run mypy --strict src/  # type check — must stay clean
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
- [x] Fixed: a real, reproducible deadlock in `ui/workers.py`'s
      cross-thread signal handling under heavy, rapid, concurrent
      `run_worker()` use — previously recorded here as "mitigated, not
      fixed" (found live while building roadmap item 5's Duplicates
      tab). Root cause: Qt's own connect()/disconnect()/emit()
      bookkeeping is guarded by a striped pool of mutexes keyed by
      object address, and the original design created a fresh
      `WorkerSignals` QObject and called connect()/disconnect() on it
      for every single task — enough distinct addresses cycling
      through that pool, concurrently with ordinary Qt widget
      construction (which does its own internal connect() calls we
      don't control), to deadlock a worker thread mid-`.emit()`
      (holding a mutex-pool slot, waiting on the GIL) against the main
      thread mid-`connect()` (holding the GIL, waiting for that same
      slot). Fixed for real (not just mitigated) by replacing the
      per-task QObject+connect()/disconnect() cycle with one shared,
      permanently-connected dispatcher — connected exactly once, at
      import time, never disconnected — so the only Qt connection-list
      operation happening on a hot path is `.emit()` on a single fixed
      address, not a constantly-growing population of them. A first
      attempt (a `threading.RLock` around the same calls) was tried,
      confirmed live to reduce but NOT eliminate the hang (Qt's own
      internal widget-construction connects aren't ours to wrap in a
      Python lock), and abandoned in favor of the dispatcher per the
      task's own explicit "verify live, switch approach if the
      surgical fix doesn't hold up" instruction. The redesign itself
      introduced one new real bug along the way — a genuine, repeatable
      segfault from `QThreadPool`'s default `autoDelete()` freeing a
      `Worker` the instant `run()` returns, racing the queued signal
      that still needed to pass that same `worker` reference to the
      main thread — fixed with `self.setAutoDelete(False)`. Proven via
      a real regression test (`tests/test_workers_deadlock_regression.py`,
      50 subprocess trials with a hard wall-clock timeout each): 43/50
      hung on the pre-fix design, 0/50 (and 0/20 at ~4x the stress
      level) on the fixed one.

      **Follow-up (2026-08-30) closing two loose ends in the above,
      done.** (1) A citation correction: docs/HISTORY.md's own item 39
      addendum cited QTBUG-93259 as supporting evidence for "no general
      upstream solution exists"; re-verified against Qt's own tracker
      and that citation was wrong (QTBUG-93259 is a `BlockingQueued
      Connection`-at-shutdown deadlock, a different mechanism) — dropped
      rather than replaced with a weak substitute; PYSIDE-1657 remains
      the accurate citation. (2) `setAutoDelete(False)` needed a real
      native-leak check, not just a deadlock re-run — `gc.get_objects()`
      only sees Python wrappers, not whether the native C++ QRunnable
      was actually freed. Using `shiboken6.Shiboken.getAllValidWrappers
      ()`/`ownedByPython()` (real native-side introspection) confirmed
      a genuine leak: one native `Worker` object per completed task,
      unboundedly, invisible to the Python-only check. **The fix needed
      two more iterations, each one caught by live re-verification, not
      assumed correct on the first attempt:** passing `self` through the
      dispatcher signal (so a handler could delete it) reintroduced the
      exact autoDelete-style crash even with `setAutoDelete(False)` —
      fixed by having `Worker` carry a plain `task_id` int instead,
      never `self`, across the signal. Confirming that alone was
      insufficient too: a task_id-only signal with `autoDelete` back at
      its *default* (`True`) still segfaulted reproducibly (5/5) in a
      real pytest-qt teardown sequence — bisected live to prove
      `setAutoDelete(False)` is independently required regardless of
      what crosses the signal (tearing down a Python-subclassed
      QRunnable from the worker thread the instant `run()` returns is
      itself unsafe here). And a synchronous `shiboken6.Shiboken.delete
      ()` call inside the dispatcher's own signal handler — even with a
      `task_id`-only signal and the worker obtained via a plain dict
      lookup, never the signal payload — reintroduced the same crash
      class again; deferring that same delete one event-loop tick via
      `QTimer.singleShot(0, ...)` was the combination confirmed live
      (5/5 clean) to fix it. Re-verified clean via native-object counts
      (flat 0 across 20 cycles × 200 workers, vs. unbounded growth
      before) and RSS (+0.7MB total, allocator noise, not a leak), the
      full deadlock regression test, and 3 consecutive full-suite runs
      (455 passed / 1 skipped each). A related, independently real bug
      surfaced during this investigation and was fixed alongside it:
      `test_backend_poll_runs_poll_downloads_off_the_main_thread` was
      waiting on a flag set *inside* the background function itself
      rather than on the main-thread completion callback, letting the
      test end (and its window get torn down) before the queued signal
      was actually delivered — fixed to wait on the same main-thread
      flag `test_backend_poll_overlap_guard_skips_concurrent_tick`
      already correctly used. Call-site audit re-confirmed: all 34
      `run_worker()` calls across `ui/*.py` still route through the one
      shared dispatcher, no leftover ad hoc `connect()`. [HISTORY
      §39](docs/HISTORY.md#39)

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
   (flac/wav > mp3/m4a/aac/ogg, VBR bitrates distrusted) feed candidate
   selection, which prefers practical-queue candidates (the original
   `select_best` from this item was itself unused dead code, removed in
   item 15; `select_downloads`, added in item 8, is the real, current
   selection entry point). [HISTORY §5](docs/HISTORY.md#5)
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
    was deliberately left CWD-relative at the time (`.seeker/
    spotify_token.json`, out of scope for this item) — **this was a
    real bug, fixed in item 43**, not a stable design choice; the token
    cache now lives alongside the DB via the same mechanism.
    [HISTORY §18](docs/HISTORY.md#18)
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
26. **Frontend Step 6: Review screen — done (2026-08-29).** Two
    deliberately-deferred CLI-only flows get a real UI home: item 17's
    read-only SoulSeek needs-review tier gains its first real
    confirm/reject action (`confirm_review_candidate`/
    `reject_review_candidate` on `DownloadService` — confirm requests
    as `role='settled'`, not a dynamically-chosen role, since a human
    confirmation is a stronger signal than an algorithmic top pick;
    this is what forced item 13's rejection-classification broadening
    to be unconditional rather than `role=='upgrade'`-scoped; reject
    just deletes the row, no blacklist, so the same candidate can
    resurface on a later `download` run), and Phase 2's
    `seeker downloads review` upgrade-confirmation flow gets
    exposed to a non-`input()` caller via
    `get_upgrade_review_details`/`apply_upgrade_decision`. New Review
    tab on `MainWindow` (needs-review table + pending-upgrades table),
    both on the existing 2s local-DB-only poll timer.
    `SoulseekReviewCandidate` gained a persisted `size` column; a
    legacy row predating it is explicitly refused
    (`ReviewCandidateMissingSizeError`), not guessed.

    **Live verification status:** Confirm was exercised for real
    (offscreen Qt, real `Application`, real DB) once the X9 Pro
    drive/slskd became reachable. Reject and Phase 2 Replace/Decline
    remain genuinely unexercised by a real click — a real
    data-availability gap (no candidate/`ready_for_review` row existed
    to click through), not a skipped step; recorded honestly rather
    than worked around. Mocked-UI-level tests (11) cover all four
    actions' wiring regardless. [HISTORY §26](docs/HISTORY.md#26)

27. **Frontend Step 7: Tagging panel — done, live-verified for real
    (2026-08-30).**
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

    **Live verification — done for real (2026-08-30), once the X9 Pro
    drive was reachable again.** Needed a genuinely untagged, real
    `IN_LIBRARY` track — every previously-tagged track from item 10's
    original real run was already tagged, which would only exercise
    the `skipped_already_tagged` path, not a real write. Found one by
    completing real, in-progress work rather than manufacturing
    anything: `Kamäleon - Quadrat` had a real completed download
    sitting unindexed (item 20/24's own documented deliberate design —
    a settled download doesn't auto-reindex into `local_files`). A
    real `seeker library scan` + `seeker library match` picked it up
    and auto-matched it (score 100), landing it as a genuine, real,
    never-tagged `IN_LIBRARY` row. Launched the real `MainWindow`
    (offscreen Qt, real `Application`, no fakes), selected the real
    `240KM/H` playlist, and clicked the real per-track "Tag" button on
    that row. The results panel reported `Tagged: 1` with zero skips/
    failures — read the real file directly off the real drive
    afterward, not just trusted the panel: `TIT2`/`TPE1`/`TALB` =
    `"Quadrat"`/`"Kamäleon"`/`"Quadrat"`, exactly matching the real
    `tracks` row, plus a real embedded `APIC:Cover` JPEG (real SOI/APP0
    signature). `local_files.tagged_at` was set for real in the DB
    too. Full, genuine confirmation that the reported result matches
    the file's actual tags. [HISTORY §27](docs/HISTORY.md#27)

28. **Frontend Step 8: Settings — done (2026-08-30).** New
    `SettingsWindow` (toolbar button on `MainWindow`), four tabs: §1
    library locations (list/add/remove, no confirmation on Remove —
    matches the CLI's own `library remove`, which has none; folder-
    picker extracted to `ui/library_location_picker.py`, shared with
    the wizard); §2 playlist destinations
    (`DownloadService.set_destination`); §3 Spotify/SoulSeek
    connection management, extracted onto `Application` itself
    (`connect_spotify`, `persist_soulseek_config`) so both the wizard
    and Settings call the same code; §4 editable
    auto-match/needs-review thresholds (the one genuine refactor, not
    just wiring).

    **Standing facts for future work touching this area:**
    `Application.download_service` passes `soulseek_client` as
    `SoulseekClient | None` — SoulSeek is optional/skippable in the
    wizard, so `DownloadService` methods that don't need it
    (`set_destination`, `get_review_candidates`,
    `get_pending_upgrade_reviews`) must never force its construction;
    only a `soulseek` property raises, lazily, when a method that
    genuinely needs it is called. `connect_spotify(client_id,
    force_reauthorize=False)` — `force_reauthorize=True` calls the new
    `TokenStore.clear()` so "Re-authorize" isn't a no-op against an
    already-valid cached token. `persist_soulseek_config` resets both
    `_soulseek_client` and `_download_service` to `None` so stale
    credentials/clients don't survive a mid-session credential change.
    `matching.py`'s `AUTO_MATCH_THRESHOLD`/`NEEDS_REVIEW_THRESHOLD`
    stay hardcoded and config-unaware; `TrackMatcher`/`DownloadService`
    instead take `get_config: Callable[[], SeekerConfig] | None` (a
    **callable**, not a snapshot value — both are cached singletons for
    the app's lifetime, so a plain value would go stale) and resolve
    `config.threshold or default` fresh on every `match_all()`/
    `download_playlist()` call — a Settings change takes effect
    immediately, no restart.

    **Live-verified for real (2026-08-30):** "Test connection" against
    the real running `slskd` container; a real threshold change via
    Settings immediately moved the two real reference candidates from
    item 17 (Prdk, Zigi SC/A-Cray) out of `soulseek_review_candidates`
    into real requested downloads on the very next `seeker download`
    run, same session, no restart. `mypy --strict` clean; full suite
    352 passed. [HISTORY §28](docs/HISTORY.md#28)

29. **UI polish pass — done (2026-08-30).** Mirrors backend item 15's
    six-area structure exactly, applied to everything built across Steps
    3-8 (`ui/`, `main_ui.py`, `config_store.py`, `download_dedup.py`,
    `dashboard_service.py`, the threshold-resolution wiring,
    `Application`'s connection-management methods). An audit, not a
    rewrite — most areas came back clean; two real bugs and several
    real coverage gaps were found and fixed, same seriousness as item
    15's own findings.

    **Dead code — checked, none found.** `wizard.py`'s
    `connect_spotify()`/`persist_soulseek_config()` extraction (item
    28 §3) left thin callers behind, not unused duplicates — confirmed
    by reading both call sites directly. No leftover single-panel
    scaffolding from Step 3→5's `QTabWidget` restructure. No stray
    debug prints or scratch scripts leaked into shipped files from the
    heavy live-verification sessions across Steps 5-8 — checked via
    `git ls-files` for anything scratch-shaped and `grep` for `print(`
    outside the one legitimate, already-documented migration
    notification in `config_store.py`. `ruff check --select
    F401,F811,F841` across `src/`/`tests/` found two genuinely unused
    imports (leftover from earlier drafts this session, not shipped
    logic) — removed.

    **`mypy --strict` — already clean, confirmed fresh (cache cleared,
    re-run).** The specific PySide6 `Signal`/`Slot` stub-coverage
    concern flagged going in — checked directly rather than assumed
    either way: the entire `ui/` package has exactly one `type:
    ignore` in it (`main_ui.py`, a dynamic `QApplication` attribute
    assignment, unrelated to Signal/Slot at all), and `workers.py`
    (the one module with real custom `Signal`/`Slot` definitions)
    type-checks clean in isolation with zero ignores. PySide6's
    bundled stubs are sufficient for this codebase's actual usage — no
    scoped override needed, unlike `mutagen`'s real gap in item 15.

    **Docstrings — the six specific items called out were all already
    documented**, checked one at a time rather than assumed: the
    2s/20s two-timer split and why (`main_window.py`), the overlap
    guard, the threshold-inversion constraint and what it protects
    (`settings_window.py`), the `role='settled'` decision plus the
    broadened lock-classification fix it depended on
    (`download_service.py::confirm_review_candidate`), the
    `get_config` callable-not-snapshot reasoning (`matcher.py`,
    mirrored in `download_service.py`), and `DownloadService.soulseek`'s
    lazy-property fix. All six already carry the "why," a direct
    result of this project's habit of writing that reasoning down at
    the time each decision was made rather than after the fact.

    **Error-handling audit — two real bugs found, not just the one
    hypothesized going in.**
    1. The specific failure mode flagged as "likely to matter most" —
       does an uncaught exception inside a QTimer poll tick crash the
       app or silently stop the timer — was traced for real, not
       assumed: a script driving a real `QTimer` through 5 real ticks,
       each raising inside its render callback, confirmed the app
       neither crashes nor stops firing; PySide6's own default
       exception hook prints a traceback and the timer schedule is
       unaffected either way. The ORIGINAL hypothesis was wrong — but
       tracing it surfaced a real, different gap: `ui/workers.py`'s
       `run_worker()` never caught an exception raised inside a
       caller's own `on_finished`/`on_error` callback (as opposed to
       the fetch function itself, which was already wrapped) — nothing
       in this codebase's OWN code guarded against a render bug, only
       PySide6's implicit default handler did, an unverified safety
       net rather than an intentional one. Fixed by wrapping both
       callback invocations in `handle_finished`/`handle_error`,
       printing a clear, attributable error and surfacing it to
       `status_label` when the caller provided one — protects every
       current and future `run_worker` caller from one shared fix,
       matching this project's "shared thing lives at the lowest
       layer that needs it" precedent.
    2. Found investigating the first: a genuine `ResourceWarning:
       unclosed database` surfaced during a coverage run.
       `Database.initialize()` used `with self.connect() as
       connection:` — sqlite3's own context-manager protocol only
       manages commit/rollback, NOT closing the connection (unlike
       `transaction()`'s explicit `finally: connection.close()`)  —
       so every real `Application()` launch, and every test building
       a fresh `Database`, leaked one real connection, relying on GC
       to eventually finalize it. Fixed to match `transaction()`'s own
       pattern exactly.

       Also checked, per the brief: every wizard step making a real
       network call (Docker health polling, OAuth) already has a real,
       user-visible failure path — `check_slskd_health`/
       `detect_docker_state` both swallow their own real exceptions
       into a status enum rather than raising, so they never depended
       on `run_worker`'s error path at all; the OAuth/bring-up flows
       already pass `status_label` and surface failures correctly. No
       gap found there.

    **Coverage audit — real gaps closed, not a percentage chase.**
    `ui/wizard.py` (63% → 93%): every prior test only checked which
    step the wizard resumes at, never a real button click — the
    Connect/Choose-Folder/Bring-Up/health-result action handlers had
    zero coverage, a genuine gap given Settings' equivalent actions
    were already tested this same way. Added direct tests for all of
    it: Connect Spotify (calls `connect_spotify`, advances), Choose
    Library Folder (registers the real location, advances, triggers
    the Docker check), SoulSeek bring-up's three guards
    (username/password, Docker-not-running, no-library-location) and
    its real `docker compose` failure path (stderr surfaces to the
    status label), the health-poll HEALTHY/BAD_CREDENTIALS/timeout
    outcomes, and the three real `_render_docker_state` branches
    (NOT_INSTALLED / INSTALLED_NOT_RUNNING on darwin / RUNNING) plus
    `_on_launch_docker_clicked`'s success/failure paths. Remaining gap
    (93%) is genuinely thin: clipboard glue, Linux/Windows-only
    branches unreachable on this darwin test machine, and a couple of
    lines that appear uncovered only because `pytest-cov` doesn't
    reliably instrument code executed on a real `QThreadPool`
    background thread (the code itself IS exercised — the test
    asserting its real, correct output passes — coverage.py just
    can't see inside that thread without extra configuration this
    project doesn't otherwise need).

    `Application.onboarding_complete` — real, consequential routing
    logic (`main_ui.py` uses it to decide wizard vs. dashboard) that
    had NEVER been asserted for its actual true/false correctness in
    any test; the one existing exercise (`test_lazy_spotify_config.py`)
    only confirms it doesn't raise, and runs in a subprocess coverage.py
    can't see into anyway. Added direct tests for all four real
    combinations (neither done, Spotify-only, library-only, both —
    confirming SoulSeek is genuinely excluded from the condition, not
    just asserted in a comment).

    `docker_setup.py::bring_up_slskd` — no test anywhere exercised its
    real body; every wizard/Settings test mocks it out entirely (there
    being no reasonable way to unit-test a real `docker compose up`).
    Added a direct test mocking only `subprocess.run`, confirming the
    real env-var dict and command list it constructs — a genuine
    regression risk given item 13's own history of getting the
    SoulSeek-network-vs-web-UI env var names wrong once already.

    **Explicitly judged not worth closing further**, same discipline
    as item 15's own equivalent section: `application.py`'s remaining
    lazy-init one-line getters (`track_matcher`, `metadata_service`,
    `dashboard_service` property bodies) — item 15's own precedent
    applies unchanged, testing them would mostly re-assert `if
    self._x is None: self._x = X(...)`. `main_window.py`'s remaining
    gaps are near-identical "no selection, show a message" guards
    already established and tested for other actions in the same file
    (the tagging panel's own no-selection tests), plus `_on_settings_clicked`'s
    trivial window-open wiring (already smoke-tested for existence).
    `settings_window.py`/`download_service.py`/`matcher.py`'s residual
    gaps are the equivalent shape.

    **Dependency audit — confirmed clean, nothing to fix.**
    `pyside6>=6.11.2`/`pytest-qt>=4.5.0` are both declared with real,
    currently-installed version floors (confirmed against `pytest`'s
    own reported versions at collection time). Every external import
    across `ui/`, `main_ui.py`, `dashboard_service.py`,
    `config_store.py`, `download_dedup.py`, `docker_setup.py` resolves
    to `PySide6`, `httpx`, or `platformdirs` — all three already
    explicit `dependencies` entries. No scipy-style undeclared
    transitive dependency found.

    **README rewritten for both interfaces.** Previously CLI-only —
    no mention of `seeker-ui`, the onboarding wizard, or Settings
    anywhere. Now: a new "Two interfaces, one service layer" section
    up front (the wizard replaces the old manual `.env`/slskd-web-UI
    setup entirely, though that manual path still works and is kept
    documented as the CLI-only alternative); the Architecture
    diagram/prose already said "presentation layer" (item 22's own
    fix) but the file-layout tree completely omitted `ui/`,
    `main_ui.py`, `dashboard_service.py`, `config_store.py`,
    `docker_setup.py`, `download_dedup.py` — added, with the same
    one-line-purpose comments the rest of the tree already uses; the
    Commands table gained a short "GUI equivalents" preamble; the
    file-replacement confirmation design-principle bullet updated to
    name both interfaces' actual controls, not just the CLI's prompts.

    **`CLAUDE.md` spot-check — one real, significant staleness found
    and fixed.** The opening description still said the app "will
    eventually match cached tracks against a SoulSeek search" — false
    for a very long time (roadmap items 4-17 built and live-verified
    that entire pipeline) — rewritten to describe the real, current
    system including both interfaces. The "Current layout" tree had
    the exact "earlier, now-superseded shape" problem flagged as the
    likely candidate — it predated Step 3 entirely and never gained a
    single line for anything built since (`ui/`, `main_ui.py`,
    `dashboard_service.py`, `config_store.py`, `docker_setup.py`,
    `download_dedup.py` all missing) — brought current. The
    Architecture section's own diagram/prose were already correct
    (fixed once already, in item 22) — confirmed rather than assumed
    stale just because the layout tree nearby was.

    Tests: `run_worker`'s new defensive wrapping (5 new tests — no
    propagation with/without a `status_label`, `on_error` callback
    exceptions, registry cleanup still happens on a callback failure);
    `Database.initialize()`'s connection-closing (1 new test, spying
    on the real connection via a wrapped `connect()` rather than
    trying to monkeypatch sqlite3's immutable C type directly); 15 new
    `wizard.py` tests; 4 new `onboarding_complete` tests; 1 new
    `bring_up_slskd` test. `mypy --strict` clean; full suite 377
    passed. [HISTORY §29](docs/HISTORY.md#29)

30. **Standalone-app packaging (PyInstaller) — done, macOS
    live-verified, Windows/Linux written-not-verified (2026-08-29).**
    `packaging/seeker.spec` + `packaging/entrypoint.py` (a thin
    `from seeker.main_ui import main; main()` — needed because
    `main_ui.py` itself, like `main.py`, has no `__main__` guard; it's
    invoked via `[project.scripts]`, which PyInstaller can't target
    directly). One-folder mode (`COLLECT`, plus `BUNDLE()` for a real
    macOS `.app`, gated on `sys.platform == "darwin"` — the rest of the
    spec is already cross-platform). Docker is deliberately NOT
    bundled — the wizard's existing detection/bring-up flow is
    unchanged and still expects a real, separate Docker install.

    **§0 de-risk, done first as scoped — genuinely a non-issue.**
    `librosa`/`numba`/`llvmlite`/`soundfile` freeze cleanly with ZERO
    custom hidden-import/`collect-all` directives — confirmed live by
    building a minimal frozen binary that actually called
    `analyze_audio()` against a real WAV and got byte-identical
    BPM/key/confidence output to the unfrozen run.
    `pyinstaller-hooks-contrib` (added as a dev dependency alongside
    `pyinstaller` itself) already ships hooks for all four that
    PyInstaller auto-discovers with no spec-file configuration at all
    — explicit `--collect-all` for these was tried first and confirmed
    **worse**, not just unnecessary (pulled in numba's own test suite).
    **One-folder over one-file — verified, not assumed, per the task's
    own instruction to check rather than take it as given:** the same
    spike built both; one-folder's second run dropped from ~3.5s to
    ~1.0s (numba's JIT cache persists in the stable directory),
    one-file stayed ~21s cold / ~18s warm every single run (a
    self-extracting temp dir means the JIT cache never persists) —
    15-20x slower for a single-file-distribution property this app
    doesn't need.

    **§1 resource-path audit — one real, exactly-predicted gap found
    and fixed.** `ui/wizard.py`'s `COMPOSE_FILE_PATH = Path("docker-
    compose.yml")` (imported into `settings_window.py` too) was a bare
    CWD-relative path — the "run `docker compose up` from the project
    root" convention already documented there, but with no repo root
    to be relative to once frozen. Fixed by moving path resolution
    into `docker_setup.py::compose_file_path()` — same home as
    `slskd_data_dir()` and the identical reasoning (`slskd_data_dir()`
    was itself moved there in item 28 §3 so wizard.py and
    settings_window.py never need to duplicate or cross-import a
    UI-module constant). Branches on `sys.frozen`: unset (every normal
    `uv run seeker-ui` dev run) → unchanged `Path("docker-compose.yml")`,
    byte-identical to before; set (PyInstaller's bootloader sets it) →
    resolves against `sys._MEIPASS`, the extracted/bundled resource
    root PyInstaller sets in every frozen build. `docker-compose.yml`
    is bundled via the spec's one `datas` entry, placed at the bundle
    root to keep the lookup a flat one-level join on both sides.
    Confirmed live in the actual built `.app`: the file lands at both
    `Contents/Resources/docker-compose.yml` and
    `Contents/Frameworks/docker-compose.yml` (PyInstaller's own
    onedir→`.app` reorganization splits data/binaries across both
    directories; which one `sys._MEIPASS` actually resolves to on
    macOS didn't need pinning down further since the file exists at
    both). Checked for other bundled-resource path assumptions
    project-wide (templates, `.env`-adjacent config) — none exist;
    `docker-compose.yml` was genuinely the only one.

    **§2 spec file — done**, see above; nothing beyond the datas entry
    and default `Analysis`/`EXE`/`COLLECT`/`BUNDLE` calls was needed.
    Confirmed directly (not assumed from PyInstaller's import-analysis
    behavior) that the built app carries zero `pytest`/`mypy`/`ruff`
    files.

    **§3 macOS build + live verification — done for real, all five
    original checks passing against the actual frozen binary, not just
    "doesn't crash."** First pass (`open dist/Seeker.app`, the same
    path a user takes) confirmed the process itself is healthy: stayed
    alive well past Qt/Cocoa's fail-fast window, `lsof` showed every
    real dependency (PySide6/Qt, numpy, scipy, rapidfuzz) loaded its
    actual compiled library, the real macOS unified log showed a
    genuine AppKit window-init sequence with zero Python tracebacks.
    That alone left a real gap, though — "boots cleanly" isn't "the
    app works" — and this session's shell has no Screen Recording or
    Accessibility permission grant, so `screencapture`/`System Events`
    couldn't screenshot or click through it.

    **Closed for real with the same mechanism this project's own Step
    5 live verification already used successfully: Qt's `offscreen`
    platform plugin (`QT_QPA_PLATFORM=offscreen`)** — a Qt-level
    headless mode, not macOS UI automation, so it needed neither Screen
    Recording nor Accessibility. Built a second, throwaway frozen
    binary (`SeekerVerify`, same `Analysis` config as the real
    `packaging/seeker.spec` — same `pathex`, same bundled
    `docker-compose.yml`, zero hidden-import overrides — just a
    different entrypoint script; not committed, a diagnostic tool only)
    that constructs the real `QApplication`/`Application`/
    `OnboardingWizard`/`MainWindow`/`SettingsWindow` objects directly
    and drives them via real Python method calls (`.click()`,
    `.setText()`, calling the same private handlers this project's own
    `test_wizard.py` already calls directly when a button isn't stored
    as a `self` attribute) — exactly this project's own established
    "offscreen Qt, real `Application`, no fakes" pattern (see items
    22/26/27/28), just run inside a genuinely frozen bundle
    (`sys.frozen=True`, a real `sys._MEIPASS`) instead of the dev venv.

    All five original checks, run for real against the frozen binary,
    **16/16 PASS**: (1) a fresh, isolated `Application` (isolated
    `platformdirs` data dir + isolated CWD so `.env`/the real token
    file are never touched) opens the wizard at the Spotify step; (2)
    entering a client ID and clicking Connect genuinely builds a real
    PKCE authorization URL (real `client_id`/`code_challenge`/
    `response_type=code`) and calls the real `webbrowser.open()` with
    it — only `wait_for_callback()` (the piece needing an actual human
    completing a real browser round-trip) is stubbed, same scope this
    project's own `_authorize()` has always had in tests; (3) against
    the REAL production `Application` (real DB, real Spotify tokens,
    real X9 Pro library), clicking Sync/Scan/Match in sequence all
    completed for real — Sync fetched real playlist metadata (215
    playlists), Scan found a real library change, Match reclassified
    real tracks (Auto: 9, Unmatched: 4), confirmed against `seeker
    check` afterward showing the identical, consistent state; (4)
    "Set up later" on a fresh wizard (Spotify configured + a library
    location added, matching this project's own existing skip-test
    precedent) completes onboarding — and surfaced a genuine, correct
    behavioral fact worth recording: `onboarding_complete` is already
    `True` the moment Spotify+library are done, *before* step 3 is
    even reached, since `onboarding_complete`'s own definition
    deliberately excludes SoulSeek/Docker (an initial version of this
    check asserted the opposite and was wrong, not the app — fixed
    once the real property's own logic was checked properly); (5) a
    real `SettingsWindow` against the real `Application` shows the
    real `config.json`'s Spotify Client ID and the real registered
    library location, both compared directly against what's on disk.
    Zero Python tracebacks in the frozen run's output. The real
    production DB was intentionally exercised for real (Sync/Scan/
    Match, matching how items 22/26-28 already verify live against
    production) — confirmed healthy and consistent afterward via
    `seeker check`, not just assumed.

    **§4 Windows/Linux — written, explicitly documented as
    unverified**, no real machine available here. The spec needed no
    platform-specific logic beyond the `darwin`-gated `BUNDLE()` call,
    since `EXE`/`COLLECT` already target the host platform correctly.

    **§5 code signing/notarization — correctly out of scope**, hook
    points (`codesign_identity=`/`entitlements_file=` on `EXE(...)`)
    left as documented no-ops in the spec's own docstring.

    Tests: `compose_file_path()`'s two branches (unset `sys.frozen` →
    unchanged `Path("docker-compose.yml")`; set → resolves against a
    fake `sys._MEIPASS`) in `test_docker_setup.py` — the one place
    this task's own "needs a real test confirming dev-mode behavior is
    unchanged" instruction applied, since everything else in this task
    was build tooling, not application logic. `mypy --strict` clean
    throughout. Full suite hit 17 failures mid-task, all
    `/Volumes/X9 Pro` `PermissionError`s from a transient sandbox gap
    in this specific session (the mount showed attached via `diskutil
    list` but a plain `ls` against it still returned `Operation not
    permitted`) — unrelated to anything this task touched, and it
    cleared on its own before the task finished: the final full run
    came back **379 passed, 0 failed**.
    [HISTORY §30](docs/HISTORY.md#30)

31. **`.dmg` installer (2026-08-29) — done, macOS live-verified,
    including the one new risk a `.dmg` introduces that item 30's own
    verification couldn't reach: a relocated launch.**
    `packaging/dmg_settings.py` wraps `seeker.spec`'s built `.app` into
    a standard drag-to-`/Applications` `.dmg` — the app and an
    `/Applications` symlink side by side, sized window, no clutter.
    `packaging/build_dmg.py` chains both steps
    (`pyinstaller`→`dmgbuild`) into one command.

    **Tool choice: `dmgbuild` (pure Python) over `create-dmg` (external
    shell tool)** — keeps packaging entirely inside this project's
    `uv`-managed dependency convention rather than introducing a
    second kind of build dependency. Its real settings-file API
    (`files`/`symlinks`/`icon_locations`/`window_rect`/`background`/
    `icon`/`badge_icon`, a plain `exec()`'d Python script with
    `defines` injected from `-D key=value` CLI flags) was verified
    against dmgbuild 1.6.7's actual current docs
    (dmgbuild.readthedocs.io's settings/example pages) and its
    installed package's own `core.py`, not written from a remembered
    shape — `core.py`'s real `options` dict is the actual source of
    truth for every key name used.

    **No custom `.icns` exists for this app** — a known, accepted
    cosmetic gap for this pass, not attempted; both the volume and the
    app fall through to the generic default icon rather than
    erroring. Background-image polish similarly skipped — optional,
    not required for a working drag-to-install volume.

    **Verification — the genuinely new thing this task could catch
    that item 30's own live-verification couldn't.** A same-location
    `.app` launch (item 30's own pass) can never exercise whether
    anything assumed a fixed relative path to the *build directory* —
    only a real relocation can. Built the real `.dmg`, mounted it for
    real (`hdiutil attach`), actually copied the `.app` out to
    `/Applications` (a genuinely different location, not a stand-in
    for the build dir), and reran item 30's own
    `QT_QPA_PLATFORM=offscreen` verification harness (a second,
    throwaway diagnostic build reusing the identical `Analysis`
    config, now also `BUNDLE()`-wrapped into a `.app` and put through
    the identical real `.dmg`→mount→copy→relocate path as the real
    app, launched from `/Applications` itself) against the relocated
    copy. **17/17 checks passed** — including one new, explicit check
    added specifically for this task:
    `docker_setup.py::compose_file_path()`'s `sys._MEIPASS`-based
    resolution correctly found the bundled `docker-compose.yml` at its
    real, post-relocation path
    (`/Applications/SeekerVerify.app/Contents/Frameworks/docker-compose.yml`),
    confirming this resolves relative to wherever the running binary
    actually lives rather than anything baked in at build time — the
    exact risk this task exists to catch, genuinely checked rather
    than assumed correct-by-construction. All five of item 30's
    original functional checks (wizard opens fresh, Spotify OAuth
    builds a real authorization URL, Sync/Scan/Match all complete
    against the real production app, "skip Docker" completes
    onboarding, Settings reflects real config) passed again too,
    launched from the relocated location. Test copies were removed
    from `/Applications` and all scratch build artifacts cleaned up
    after verification — nothing left installed or lying around; the
    real production DB was confirmed still healthy and consistent
    afterward via `seeker check`, matching the state before this task
    started. [HISTORY §31](docs/HISTORY.md#31)

32. **Broad end-to-end stress test (2026-08-29) — done; two real,
    previously-undetected resource leaks found and fixed, both
    confirmed via a live repro before and after the fix, not
    inferred.** Different in kind from every prior verification in
    this project — not one feature proven and moved on from, but the
    whole real pipeline driven together, overlapping and sustained,
    specifically hunting for bugs that only show up under combined,
    extended real usage.

    **§0 audits, done first — one came back clean, one surfaced the
    two real bugs.** Audited every `Database`/`httpx`/file-handle/
    `HTTPServer` usage in the codebase for the resource-leak pattern
    already found once in `Database.initialize()` (item 29) — clean:
    every DB call site goes through the properly-closing
    `Database.transaction()`, never raw `.connect()`; every HTTP call
    is a stateless `httpx.get`/`.post()` (no persistent `httpx.Client`
    anywhere to leak); every file write is `Path.write_text()`/
    `.read_text()` or mutagen's own self-managed file handles (no raw
    `open()` calls in application code at all); `wait_for_callback()`
    already calls `server_close()`. Also audited every `.connect()` in
    `ui/*.py` (~35 signal connections, every `QTimer.timeout` included)
    for a `run_worker` bypass — also clean: every call that touches
    `self.application.*` is routed through `run_worker`, confirmed
    call site by call site rather than sampled.

    **Bug 1 — `SettingsWindow`/`OnboardingWizard`/`MainWindow` never
    actually get destroyed on `close()`.** A parentless top-level
    `QMainWindow`'s `close()` only *hides* it by default in Qt — real,
    ordinary usage (open Settings, close it, reopen it) leaked ~2MB of
    real RSS per cycle, confirmed via an isolated repro (40 real
    open/close cycles, explicit `gc.collect()` between each,
    `gc.get_objects()` count climbing linearly and non-negotiably —
    genuinely unreachable-but-uncollected, not just slow GC timing).
    Fixed with `Qt.WidgetAttribute.WA_DeleteOnClose` on all three
    top-level windows, which makes `close()` actually schedule real
    deletion.

    **Bug 2 — a reference cycle in `run_worker` invisible to Python's
    own cyclic GC.** `handle_finished`/`handle_error` both close over
    `worker` itself (to call `_active_workers.discard(worker)`) and
    are connected to `worker.signals.finished`/`.error` — `worker` →
    `worker.signals` → [Qt connection] → the handler → `worker` again.
    The Qt/shiboken side of a signal connection isn't visible to
    Python's cycle tracer, so this leak was real and permanent, not
    just uncollected garbage — confirmed by the same repro (with
    `WA_DeleteOnClose` alone still in place): `gc.get_objects()`
    stopped climbing per-cycle by ~87% but a real, still-linear ~285
    objects/cycle residual remained, and a direct type-count scan
    found every single `Worker`/`WorkerSignals`/`SettingsWindow`
    instance ever constructed still alive.

    **The fix for Bug 2 needed a second iteration — its first attempt
    caused a real, reproducible segfault, caught by the full suite,
    not the isolated repro.** Manually calling
    `worker.signals.finished.disconnect()` from inside
    `handle_finished` itself — the handler that signal's own emission
    had just invoked — crashed the full test suite consistently, every
    run, deep in Qt's own event processing during a later, unrelated
    test's teardown. Mutating a signal's connection list while that
    same signal is mid-emission is undefined behavior in Qt's C++
    layer; Python-level try/except can't protect against it. Confirmed
    this was genuinely the cause (not `WA_DeleteOnClose`, the other
    same-session change) by reverting each independently against the
    full suite. Real fix: `Qt.ConnectionType.SingleShotConnection` on
    both `connect()` calls (Qt safely disconnects its own connection
    internally, immediately after that one emission finishes — no
    Python-side mid-emission mutation at all), plus an explicit manual
    disconnect of only the *other*, non-firing signal in each handler
    (safe, since that one was never mid-emission).

    **Combined fix, confirmed clean:** the same 40-cycle repro now
    shows `gc.get_objects()` completely flat (identical count across
    every checkpoint from cycle 5 through cycle 35) and zero live
    `Worker`/`WorkerSignals`/`SettingsWindow`/`QThreadPool` instances
    after a `gc.collect()` — a complete fix, not a reduction. Full test
    suite (379 passed, 1 skipped) run three times in a row with no
    crash, after previously crashing on every run with the unsafe
    manual-disconnect version.

    **The real, sustained stress run (2026-08-29, 302 real seconds,
    against production data) — the harness itself, not just the two
    bugs above.** Real `Application`/`MainWindow` under
    `QT_QPA_PLATFORM=offscreen` (the same mechanism proven in the
    packaging task's own retry): fired Sync/Scan/Match overlapping,
    not sequentially, and they settled cleanly (215 real playlists
    synced, one real library change found, tracks reclassified — Auto:
    9, Unmatched: 4); fired 3 concurrent download operations across two
    playlists (bypassing `MainWindow`'s single-selection download
    button via direct `download_playlist()` calls through the same
    real `run_worker`/`QThreadPool` mechanism, plus one real UI button
    click) — a real service-layer dedup guard correctly reported
    "Already in progress ... skipping" for all 4 real tracks already
    mid-download rather than double-submitting; interleaved 20 real
    Settings open/close cycles with playlist-selection switching while
    background work (the real 20s backend-poll timer) kept running;
    changed `auto_match_threshold`/`needs_review_threshold` mid-session
    via the real Settings save button and confirmed the SAME
    already-constructed `TrackMatcher` picked it up on its very next
    `match_all()` call with no restart (matches item 28 §4's own
    precedent, now proven under a busier, more realistic session), then
    restored the original values in a `finally` block, confirmed by an
    independent reload. Real resource numbers over the full run: RSS
    218.1MB → 276.4MB (nearly all of it — ~53MB — in the first 2
    seconds of real object construction and the overlapping sync/scan/
    match burst; only ~4.5MB more across the remaining 270 seconds and
    18 interleaved cycles, ≈0.25MB/cycle, matching the isolated repro's
    own small legitimate residual); open file descriptors 6 → 21
    (stable, no growth across the interleaved cycles); threads 5 → 9
    (stable, fluctuating, never climbing); `active_workers` at 0 at the
    end (every worker drained). Real production DB/config confirmed
    unchanged afterward — `seeker check` reported the identical
    breakdown before and after, and the real `config.json` thresholds
    were confirmed restored to their real pre-existing values (70.0/
    60.0, the same values item 28's own live verification set).

    **Durable regression guard, not a one-off script.**
    `tests/test_stress_e2e.py` — opt-in only
    (`SEEKER_RUN_STRESS_TEST=1`; duration overridable via
    `SEEKER_STRESS_DURATION_SECONDS`, default 300s), skipped in the
    normal fast suite the same way the X9-Pro-drive tests are, plus an
    explicit opt-in gate on top since — unlike that skip — the
    infrastructure being present isn't enough reason to run something
    this slow and consequential by default. Asserts bounded RSS/fd/
    thread growth against generous-but-real ceilings and that
    `active_workers` is empty at the end — this specific assertion is
    what would have caught both bugs above proactively. `psutil` added
    as a dev dependency for real process-level sampling (RSS, open fd
    count, thread count) — cross-platform, not shelling out to `ps`/
    `lsof`.
    [HISTORY §32](docs/HISTORY.md#32)

33. **Download ETA (per-download speed/ETA estimate) — done
    (2026-08-29).** `ui/download_eta.py::DownloadEtaTracker` — purely
    in-memory, keyed by `download_requests.id`, no schema/service-layer
    changes at all. Confirmed directly, not assumed: `Application
    .dashboard_service` is a cached singleton for the app's whole
    lifetime, the identical pattern `track_matcher` already relies on
    (item 28 §4) — see `test_dashboard_service_is_a_cached_singleton
    _across_app_lifetime`. Samples are recorded only on `MainWindow`'s
    20s `BACKEND_POLL_INTERVAL_MS` cycle — `_trigger_backend_poll`'s
    on_finished chains a fresh `get_active_downloads()` fetch into
    `_record_eta_samples` — never on the 2s display-refresh tick, which
    would just re-diff against the same DB row `poll_downloads()`
    hasn't touched since the last real network poll. Speed = delta
    bytes / delta t between the last two samples for a given request
    id; "Calculating…" until a second sample exists or the latest
    delta is non-positive; "Stalled" once `STALL_SAMPLE_COUNT = 3`
    (untuned, flagged in a code comment) consecutive samples report
    identical bytes — deliberately more than one flat sample before
    calling it a stall, since one flat interval alone isn't proof yet.
    History is capped at 3 samples per id and evicted the moment an id
    drops out of `get_active_downloads()` (completed/failed/superseded)
    — this project has hunted the unbounded-growth version of this
    exact leak class before, for real Qt objects (items 29/32), so the
    same discipline applies here even though this is plain Python state.
    ETA only ever renders once a download's progress bar is
    determinate — the pre-existing indeterminate-bar behavior is
    untouched — shown in a small container widget next to the bar in
    the Downloads tab (the cell widget there is no longer always a bare
    `QProgressBar`; tests updated to look up the nested bar/label).

34. **Contextual help in the UI — done (2026-08-29).** Presentation-only,
    no service-layer changes. `ui/help_text.py` centralizes every piece
    of UI copy as named constants — tooltips, tab subtitles, and the
    new About dialog's text — so a control shared between two windows
    (`library_location_picker.py`'s folder-picker flow, used by both
    the wizard and Settings) has exactly one copy to edit, the same
    "shared thing lives in exactly one place" discipline `matching.py`'s
    consolidation already established for logic. Inventoried every
    clickable control across `ui/*.py` directly (grepped every
    `QPushButton(`/`QCheckBox(`/`QLineEdit(`/`clicked.connect`/
    `toggled.connect` call site, not assumed from memory) — every one
    of them, including per-row buttons built inside a render loop
    (`_build_track_actions`, `_build_needs_review_actions`,
    `_build_upgrade_actions`, the wizard's dynamically-relabeled
    `docker_action_button`), now has `setToolTip()`.

    A short, persistent (not hover-dependent) one-line subtitle sits
    under each of `MainWindow`'s three tab headers (Dashboard,
    Downloads, Review) and under `SettingsWindow`'s own header, above
    its four internal tabs — required restructuring the Dashboard and
    Downloads tabs' central widgets from a single top-level layout into
    a `QVBoxLayout` wrapping [subtitle, existing content], since neither
    had a natural place for one before. `MainWindow` gained a real
    `QMenuBar` (`self.menuBar()` — a `QMainWindow` always has one
    available even before anything's added to it) with a `Help` menu
    and an "About Seeker" action, opening a new `AboutDialog` (in
    `ui/main_window.py`, alongside the window that owns the menu) —
    its version line reads `importlib.metadata.version("seeker")`
    rather than a second hardcoded literal that could drift from
    `pyproject.toml`, falling back to no version line at all if package
    metadata isn't available (e.g. a frozen PyInstaller build with no
    installed dist-info).

35. **Support-the-creator links — done (2026-08-29).** **`SUPPORT_LINKS`
    in `ui/help_text.py` holds two deliberately obvious placeholders
    (`"TODO: paste real Revolut link"` / `"TODO: paste real PayPal
    link"`), not fabricated-looking real URLs — replace both before this
    ships to anyone.** Presentation-only: both `AboutDialog` (item 34)
    and a new wizard "you're all set" page call `webbrowser.open()`
    directly, the identical mechanism the Spotify OAuth flow already
    uses — no SDK, no embedded payment UI, no runtime API call.

    The wizard had no final screen at all before this (it closed and
    called `on_complete()` the instant Spotify+library, or SoulSeek/
    skip, finished) — confirmed live by reading `wizard.py` rather than
    assumed, and confirmed with the user before inventing one, per the
    task's own explicit instruction. Added a fourth stack page
    (`_build_done_page`, index 3, never an `_initial_step()` resume
    target — reaching it always requires finishing the same session's
    flow first) shown via a new `_advance_to_done_page()` in place of
    the old `_advance_to_dashboard()`'s immediate close+`on_complete()`;
    a real "Go to Dashboard" button (`self.continue_button`) now does
    that close+`on_complete()` call itself (`_finish()`). Both existing
    call sites (`_handle_health_result`'s HEALTHY branch,
    `_on_skip_soulseek_clicked`) now land on this page instead of
    closing immediately — two existing tests asserting `on_complete`
    fired right after skip/health-success were updated to assert
    landing on the done page first, then click Continue. No mention on
    the daily-use Dashboard/Downloads/Review screens, as scoped.

36. **Packaging polish (2026-08-29) — macOS done and re-verified,
    Windows written-but-unverified, Linux deliberately deprioritized.**

    **macOS.** The task's own ask — "add ad-hoc self-signing as a build
    step if it genuinely reduces friction" — turned out to already be
    true and required zero code changes: PyInstaller's `BUNDLE()`/`EXE()`
    steps ad-hoc-sign (`codesign -s -`) both the frozen executable and
    the whole `.app` bundle by default whenever no real
    `codesign_identity` is given (`osxutils.sign_binary()`'s own
    default), confirmed live against a real fresh build — `codesign
    -dvvv dist/Seeker.app` shows `flags=0x2(adhoc)`/`Signature=adhoc`,
    `codesign --verify --deep --strict` exits 0. `spctl --assess` still
    correctly reports "rejected" (ad-hoc signing isn't notarization —
    Gatekeeper still warns on another machine's first launch), so the
    real, still-needed friction point is the right-click → Open
    workaround, not the absence of any signature at all — `seeker.spec`
    and README previously described the build as plain "unsigned,"
    which undersold what's actually happening; both corrected to say
    "ad-hoc signed, not notarized."

    Added `packaging/Read Me First.txt` (bundled into the `.dmg`
    alongside `Seeker.app`, via `dmg_settings.py`'s `files`/
    `icon_locations` — window resized taller, `((100,100),(640,400))`,
    to fit the third icon) spelling out that right-click → Open
    workaround for someone hitting it for the first time. Rebuilt and
    live-verified the real `.dmg`: mounted it (`hdiutil attach`),
    confirmed `Seeker.app`, the `Applications` symlink, and `Read Me
    First.txt` (with the exact intended text) all present on the real
    volume.

    Icon: skipped entirely, as scoped — no `.icns` generated
    speculatively; the existing generic-icon fallback is untouched.

    **Windows — written, explicitly unverified (no real Windows machine
    in this environment).** `packaging/seeker.iss` (Inno Setup script)
    + `packaging/build_windows_installer.py` (chaining wrapper) mirror
    `dmg_settings.py`/`build_dmg.py`'s exact structural pattern: wraps
    `seeker.spec`'s same PyInstaller onedir output (`dist/Seeker/`)
    into a real `SeekerSetup.exe` with Start Menu/Desktop shortcuts and
    a standard uninstall entry. Inno Setup itself (specifically its
    command-line compiler, `ISCC.exe`) is a real, separate Windows-only
    tool — not a `uv`-managed dependency, the same relationship this
    project already has with Docker for slskd. `AppId` is a fixed,
    generated-once GUID (`08479AF0-7643-4688-B183-4E3A3431DE4D`) so a
    future reinstall/upgrade replaces in place — never regenerate it.
    No `.ico` exists yet (same deferred-icon gap as macOS); no Windows
    code-signing certificate configured (SmartScreen will likely flag
    the unsigned `Setup.exe` — same paid-prerequisite gap as Apple
    notarization). **Real verification on an actual Windows machine is
    still outstanding** — don't treat this as proven just because the
    same structural pattern already works on macOS.

    **Linux — not scoped, tracked as a real future direction only** —
    see item 37 below (Linux AppImage/`.deb` packaging), not attempted
    here. [HISTORY §36](docs/HISTORY.md#36)

37. Linux packaging (AppImage or `.deb`) is a real, deliberately
    deprioritized future option — not scoped or attempted as part of
    item 36. Direction, not urgent.

38. **Duplicate/quality detector via fingerprinting — Phase 0 spike
    done (2026-08-29); no production code yet, as scoped.** Verified
    live against this machine and 3 real file pairs from the real
    library, and found several real, load-bearing corrections to the
    plan as originally briefed:

    **The assumed import path (`pyacoustid.chromaprint.Fingerprinter`)
    doesn't exist — checked, not assumed.** `pip install pyacoustid`
    installs two separate top-level modules, `acoustid.py` (the
    AcoustID *web-service* client — HTTP lookup/submit against
    api.acoustid.org, which this project doesn't want at all, per
    "prefer local execution over external services") and `chromaprint.py`
    (a real ctypes binding to libchromaprint, MIT-licensed per its own
    header, bundled in the same sdist) — imported as bare `import
    chromaprint`, never as an `acoustid` submodule. **A real, separate
    PyPI package literally named `chromaprint` exists and is a
    same-name COLLISION with something unrelated (a colored-terminal-
    output library)** — confirmed live by installing it and inspecting
    its contents; never add `chromaprint` as a direct dependency name.

    **Real macOS gotcha, confirmed live:** the bundled binding's loader
    does a bare `ctypes.CDLL("libchromaprint.1.dylib")` with no path —
    on this Apple Silicon Homebrew install, that fails
    (`ImportError: couldn't find libchromaprint`) unless
    `DYLD_FALLBACK_LIBRARY_PATH` includes `/opt/homebrew/lib`, since
    dyld's default fallback search path doesn't include Homebrew's
    prefix. This also raises at *import* time, not call time — a real
    problem for an app that must still start cleanly when the library
    isn't installed. Conclusion: don't depend on `pyacoustid`'s bundled
    `chromaprint.py` as-is. A future `seeker/audio_fingerprint.py`
    should adapt its small, real C-API surface (`chromaprint_new/free/
    start/feed/finish/get_fingerprint/decode_fingerprint/dealloc` —
    confirmed complete by reading the real binding's source) into
    Seeker's own module with (a) an explicit candidate-path search list
    per platform (Homebrew arm64/intel, Linux system paths, Windows DLL,
    a `sys._MEIPASS` branch for a frozen build — mirroring
    `docker_setup.py::compose_file_path()`'s own established pattern)
    instead of a bare-name lookup, and (b) the "not installed" case
    raised lazily, only when fingerprinting is actually invoked — the
    same lazy-property discipline `Application.soulseek_client`/
    `DownloadService.soulseek` already established (item 28).

    **License, checked before deciding to bundle:** the C library
    itself is LGPL-2.1-or-later (confirmed via `brew info chromaprint`
    and its bundled `LICENSE.md`). Loading it dynamically via `ctypes`
    (never statically linking it into a compiled extension) is the
    correct, low-risk way to stay LGPL-compliant while bundling the
    real `.dylib`/`.so` alongside a closed-source app — this is already
    the approach being taken, not an extra step to add.

    **Real clustering numbers, from 3 real file pairs in the real
    library (not synthetic data):** same-format real MP3 duplicates
    (`FISHER (OZ) - Losing It (Extended)`, 2 of 5 real copies found
    across different Beatport-chart folders) scored **99.98%**
    Hamming-distance similarity; a real cross-format duplicate pair
    (`Bootie Brown, Tame Impala, Gorillaz - New Gold ...`, real FLAC
    vs. a real lossy MP3 re-encode of the same track) scored **99.87%**
    — confirming Chromaprint survives a real lossy transcode, which
    matters since this library genuinely has both. An unrelated real
    track pair (negative control) scored **57.81%** — a wide, clear
    separation from the ~99.9% duplicate band, validating
    Hamming-distance clustering as the right approach before writing
    any production clustering code. Decoding used `soundfile.read(path,
    dtype="int16", always_2d=True)` (not the fpcalc subprocess path, as
    the task specified) fed to `Fingerprinter.feed()` in ~1-second
    chunks (confirming the streaming contract, not just one big feed
    call) — real MP3 and FLAC decoding both worked via `soundfile`
    1.2.2/libsndfile 1.2.2, already an existing transitive dependency
    (via `librosa`) with zero new Python dependency needed for decode.

    **`libchromaprint` needed a real, non-trivial local install** —
    `brew install chromaprint` pulled in `ffmpeg` and several codec
    libraries (~90MB total) as real dependencies. A future CLI/UI
    should check for the library's availability and degrade
    gracefully (skip/warn) rather than crash, the same
    "checked-before-use, not eagerly constructed" pattern
    `soulseek_configured` already established — fingerprinting is
    inherently an optional feature a real install may not have set up.

    **Not yet built, deliberately, per the task's own phasing:** the
    schema migration (`local_files.fingerprint`/`fingerprint_duration`/
    `fingerprint_computed_at`), `seeker/audio_fingerprint.py` itself,
    the location-scoped clustering/quality-scoring service, CLI
    commands, and the UI tab are all still ahead — this entry covers
    Phase 0 only. [HISTORY §38](docs/HISTORY.md#38)

39. **Duplicate/quality detector via audio fingerprinting — Phase 1
    done and live-verified (2026-08-29): fingerprint computation +
    read-only clustering/scoring, CLI and UI, exactly per the task's
    own build order. The delete/replace action is NOT built yet —
    deliberately deferred to a later phase.**

    **Schema.** `local_files` gains nullable `fingerprint` (TEXT,
    base64 chromaprint output), `fingerprint_duration` (REAL),
    `fingerprint_computed_at` (TEXT) — added to `SCHEMA` and via a
    guarded `_add_column_if_missing` in `connection.py`, following item
    11's exact pattern (excluded from `upsert()`'s `ON CONFLICT DO
    UPDATE`, written only via a separate `LocalFileRepository
    .update_fingerprint()`). **Verified live against the real,
    non-empty production DB** (3,218 real `local_files` rows) — columns
    added cleanly, zero data loss, confirmed via `seeker check`
    reporting the identical breakdown before and after.

    **`seeker/audio_fingerprint.py` — a project-owned ctypes binding,
    not a dependency on `pyacoustid`'s bundled one.** Phase 0's spike
    (item 38) found real reasons not to reuse the third-party binding
    as-is (import-time crash on a missing library; a bare-name
    `ctypes.CDLL` lookup that doesn't find a real Homebrew install on
    Apple Silicon). This module adapts the same small, real C API
    (`chromaprint_new/free/start/feed/finish/get_fingerprint/
    decode_fingerprint/dealloc`) with: an explicit candidate-path
    search (Homebrew arm64/intel, a `sys._MEIPASS` branch for a future
    frozen build, then a bare-name fallback) instead of a bare lookup;
    a lazy, call-time-only failure (`FingerprintingUnavailableError`,
    never raised at import) plus a cheap `is_available()` check mirror-
    ing `Application.soulseek_configured`'s own "checked before use"
    precedent; `compute_fingerprint(path)` streaming real PCM via
    `soundfile` in ~1-second chunks (not the fpcalc subprocess path);
    and `similarity_from_decoded(a, b)` — a **pure**, ctypes-free
    Hamming-distance function operating on already-decoded `uint32`
    arrays, factored out specifically so clustering logic can be unit-
    tested with synthetic vectors with no real audio or library needed,
    per the task's own testing guidance. `decode_fingerprint()` is
    public (not a private helper) for exactly this reason too — see
    the caching note below. A vectorized numpy popcount
    (`_popcount_uint32`, a 256-entry byte lookup table) replaces a
    naive per-subfingerprint Python loop — matters at real scale (a
    fingerprint is ~10,000 `uint32` values).

    **`soulseek/quality.py` extended, not duplicated.** New
    `quality_tier_for_format(extension)` factors the existing lossless/
    lossy tiering out of the `SoulseekFile`-specific `quality_tier()`
    (which now just delegates to it) so local-file duplicate ranking
    reuses the identical scale instead of a third copy — the same
    drift lesson `matching.py`'s own consolidation already taught this
    codebase. New `analyze_local_file_quality(path)` reads real bitrate/
    bit-depth/sample-rate via `mutagen.File(path).info` (confirmed live
    that mutagen reports a real, correct bitrate for uncompressed WAV
    PCM too — `sample_rate * bit_depth * channels`, not just for lossy
    formats, correcting a wrong assumption an early test draft made),
    a real clipping-ratio heuristic (`CLIPPING_AMPLITUDE_THRESHOLD =
    0.999`, explicitly flagged untuned) via `soundfile`, and optional
    integrated-loudness (LUFS) via `pyloudnorm` — confirmed live that
    digital silence returns a real, mathematically-correct `-inf`
    rather than raising, which needed an explicit `math.isfinite()`
    check to turn into a clean `None` (not a meaningful value to show).

    **`library/duplicate_service.py` — the location-scoped service.**
    `compute_fingerprints(location_name, force=False)` mirrors
    `MetadataService.tag_tracks`'s exact shape (per-item try/except so
    one bad file can't abort a batch; skip-already-done + `force`).
    `find_duplicate_groups(location_name)` clusters via union-find over
    `DUPLICATE_SIMILARITY_THRESHOLD = 0.95` (untuned, but justified by
    item 38's real spike numbers: real duplicates scored 99.87-99.98%,
    an unrelated real pair ~58% — a wide margin either side of 0.95).
    Never persisted as its own table — computed fresh from cached
    fingerprints on every call, so a moved/rescanned file can't leave a
    stale group behind. `LibraryLocationNotFoundError` is a real,
    distinct class from `soulseek/download_service.py`'s
    identically-named one — kept separate rather than cross-imported
    across unrelated service modules, the same precedent this
    codebase's three separate `PlaylistNotFoundError` classes already
    set (aliased at the `cli.py` import site).

    **A real, live-verification-driven performance fix, done before
    calling this "live-verified" rather than after.** The first real
    run against the production library's ~3,142 successfully-
    fingerprinted files took **several minutes and multiple GB of RAM**
    for `find_duplicate_groups` alone — traced to `hamming_similarity`
    re-decoding both fingerprints (a real ctypes call plus a numpy
    array copy) on **every single pairwise comparison**, when a file
    is compared against many others. Fixed by decoding each file's
    fingerprint exactly once (`decode_fingerprint`, now public) into a
    cache reused across every comparison — this is the real reason
    `similarity_from_decoded` is a public, separate function from
    `hamming_similarity`. A second, independent fix: even with cheap
    per-pair comparisons, a genuine `O(n^2)` **iteration** (~4.9M pairs
    for n=3,142) still cost real, measurable minutes of pure Python-
    loop overhead — fixed by sorting files by `duration_ms` first and
    sliding a bounded window (break once two files, in duration order,
    exceed `DURATION_TOLERANCE_MS`), rather than checking-then-skipping
    every pair. Files with no reported `duration_ms` (expected to be
    rare/none in practice) still fall back to an unoptimized full sweep,
    matching the original, un-windowed semantics for that edge case
    exactly. **Final real run, fully re-verified after both fixes:**
    `seeker library fingerprint x9-pro` — 3,142 of 3,218 real files
    fingerprinted successfully (76 real failures, see below);
    `seeker library duplicates x9-pro` — completed in **9m59s real
    wall-clock time**, found **344 real duplicate groups**. Read the
    real output, not just the count: correctly clustered same-track
    re-downloads across different monthly chart folders (near/exactly
    100% similarity) genuinely by audio content despite completely
    different filenames — including one pair with different
    collaborator-credit ordering in the filename entirely
    (`"Emmanuel Jal, Nyaruach, Benjy, LevyM - Guaja..."` vs.
    `"LevyM, Benjy, Emmanuel Jal, Nyaruach, N-You-Up - Guaja..."`, 99.0%
    similarity) — and correctly identified the user's own WIP mix
    revisions of original productions as genuinely similar-but-distinct
    (`"Acid 6db Gain.wav"` vs. `"Acid Pre-Limiter.wav"`, 95.3% — a real,
    meaningfully lower score than the near-100% exact-duplicate pairs,
    exactly the discriminative behavior this is supposed to have) and a
    real, previously-unnoticed accidental duplicate across two
    unrelated folders (a `wetransfer_...` import folder and
    `Sinthesis/YBBY`, 100.0%). **Honest, current characteristic, not
    hidden:** ~10 minutes for ~3,100 files is real and acceptable for
    an occasional, explicitly-triggered scan, not instant — a future
    session could reduce it further (e.g. bucketing/parallelizing the
    comparison), but this was not pursued further once real,
    documented, non-blocking performance was reached.

    **Real, confirmed decode failures — 76 of 3,218 files, correctly
    isolated by the existing per-file try/except, not a design gap.**
    Two real causes, checked directly rather than assumed: (1) several
    "File does not exist" failures on files with accented filenames
    turned out to be genuinely 0-byte files on disk (confirmed via
    `ls -la` before assuming a Unicode-normalization bug — there wasn't
    one); (2) ~70 "bad data offset"/"unspecified internal error"
    failures on real, valid, playable MP3s (confirmed via `file`) are a
    real, known `libsndfile`/`soundfile` limitation — its MP3 decoder
    is less permissive than `mpg123`/`ffmpeg` about non-standard ID3/
    VBR framing. Not fixed in this phase (a future revision could add
    an `ffmpeg`/`mpg123` fallback for files `soundfile` can't open) —
    recorded honestly as a real, current gap instead.

    **CLI — `seeker library fingerprint <location> [--force]` /
    `seeker library duplicates <location>`.** Both raise
    `LibraryLocationNotFoundError`/`FingerprintingUnavailableError`
    up through `cli.run()`'s existing top-level exception handling
    (`sys.exit(1)`) rather than swallowing them locally, matching how
    every other playlist/location-not-found error in this file already
    propagates.

    **UI — a new, read-only "Duplicates" tab in `MainWindow`.** A
    location combo (scoped to one location, never all of them — the
    UI counterpart to the CLI's own scoping), "Compute fingerprints"/
    "Find duplicates" buttons, and a results table. **A real,
    significant concurrency bug was found while wiring this up, and
    later fixed for real (not just mitigated) in a dedicated follow-on
    task — see the "Known issues" entry above and
    [HISTORY §39](docs/HISTORY.md#39) for the full investigation**: the
    location combo loads lazily on first real tab-switch
    (`_on_tab_changed`), not eagerly during `MainWindow.__init__`,
    since the eager version was what originally triggered the
    deadlock — this lazy-loading choice stays in place even after the
    underlying `ui/workers.py` bug was fixed, since it's also just a
    better fit for the UI (a real user reaches this tab far less often
    than every window construction). No Replace/Decline actions exist yet on this
    tab — intentionally read-only, matching the task's own build order.
    UI verification is mock-level (mirrors this project's own "real
    backend + thorough mocked UI wiring" split used elsewhere, e.g.
    item 27) rather than a redundant real offscreen-Qt click-through —
    the real ~10-minute computation was already verified once via the
    CLI above; running the identical computation a second time through
    the UI would cost another ~10 minutes for no new information.

    **Not yet built, deliberately:** the delete/replace action and its
    double-confirm UX (mirroring the Review tab's own Replace/Decline +
    "Delete old file" pattern), and the README "one filesystem-
    destructive action" line update that ships alongside it — both
    explicitly out of scope until a future phase, per the task's own
    stated build order. [HISTORY §39](docs/HISTORY.md#39)

40. **Duplicate/quality detector — Phase 2: the delete action — done
    (2026-08-30).** Closes out item 39's deliberately-deferred scope:
    resolving a duplicate group by keeping one copy and deleting the
    rest, both the DB row and the real file. No schema change needed —
    `find_duplicate_groups` is already computed fresh from cached
    fingerprints on every call (item 39's own design), so a deleted
    duplicate simply stops appearing next time; no "resolved" flag.

    **Standing fact for any future code touching `local_files`
    deletion:** delete the DB row FIRST, then the file on disk.
    Confirmed directly (not assumed) that `library/scanner.py`'s own
    `delete_missing()` already self-heals the DB-row-first failure mode
    (an interrupted-before-file-delete orphan just gets rediscovered as
    "new" on the next `library scan`) — the reverse order would instead
    leave a row pointing at a nonexistent file in the window before
    that same scan, which a matcher/tagger could act on and fail
    against. `local_files.delete_by_id`'s cascade onto
    `track_matches.local_file_id` (`ON DELETE SET NULL`) was verified
    with a real FK-cascade test, not assumed from the schema text.

    **Follow-up (2026-08-30), a real gap closed before this could be
    called done: the cascade alone left a track's status wrong, not
    just null.** `ON DELETE SET NULL` only clears `local_file_id` — it
    leaves `match_method`/`score` untouched, so a track that was
    `match_method='auto'` stayed `'auto'` with `local_file_id=NULL`.
    Checked what that combination does downstream rather than assuming
    it was harmless: `DashboardService._compute_status` requires BOTH
    `match_method == "auto"` AND a resolvable `local_file_id` for
    `IN_LIBRARY`, so the track falsely showed `NOT_FOUND` even though
    the group's other (often better-quality) copy was sitting right
    there — undercutting the whole point of resolving a duplicate.
    Checked the specific re-download risk too, not just the display
    bug: `TrackRepository.get_unmatched_for_playlist` (what
    `download_playlist` actually schedules against) filters on
    `match_method IS NULL`, which stayed FALSE for this row — so
    `download_playlist` would NOT re-fetch it either, meaning the real
    failure mode was a track stuck in limbo (shown missing, never
    re-searched), not the app going and re-downloading a copy it
    already has. Still a real bug, fixed properly: `delete_local_files`
    now takes an optional `keep_local_file_id`; when given, any
    `track_matches` row pointing at a file being deleted is re-pointed
    to the surviving file instead of falling to the cascade (via
    `TrackMatchRepository.upsert()` — the same reusable primitive
    `match_all()`/`apply_upgrade_decision` already use for this, no new
    "repoint" helper needed; a new `get_by_local_file_id` read method
    was added since none existed for that lookup direction).
    `match_method`/`score` are preserved as-is on repoint (not
    re-evaluated) since the underlying audio is fingerprint-confirmed
    near-identical; only `matched_at` refreshes. The UI passes the
    checked radio's file id through. Verified with a real end-to-end
    test seeding a real match, deleting the matched file with the other
    kept, and confirming the match follows it with its original
    `match_method`/`score` intact.

    **Reused, not duplicated:** `apply_upgrade_decision`'s inlined
    "delete this file, catch OSError, report a message" tail was
    extracted into shared `seeker/file_deletion.py::delete_file()` (same
    "shared thing lives in exactly one place" precedent as
    `matching.py`/`download_dedup.py`); both it and the new
    `DuplicateService.delete_local_files(local_file_ids)` call it now.
    `delete_local_files` has no notion of "groups" itself — the caller
    decides which ids to delete.

    **UI reuses the Review tab's exact double-confirm shape, not a new
    one:** a "Keep" radio per file (grouped per group via
    `QButtonGroup`, pre-selected to Phase 1's best-quality pick but
    changeable) and a "Confirm delete" checkbox + "Delete" button on
    each group's first row only (blank elsewhere, item 27's own
    precedent). Routed through `run_worker()` exactly like every other
    background action — item 39's final state was re-read before
    writing this, and nothing here reintroduces any of its four closed
    hazards (the delete itself is one synchronous service call inside
    the worker function, no bespoke `QRunnable`/signal design).

    No new CLI command — out of the task's own stated scope (the UI
    flow specifically); `library duplicates` stays read-only.

    **A second real problem, found by checking against the real result
    scale rather than a small synthetic one: refreshing after every
    single-group resolution via a `find_duplicate_groups()` re-fetch
    was genuinely broken at real scale.** That call recomputes an
    entire location's clustering from scratch every time, by design
    (never persisted, so a moved/rescanned file can't leave a stale
    group behind) — item 39's own live-verification already recorded
    the real cost of that: ~10 minutes over a real ~3,100-file/
    344-group library. Re-running it after each of 344 one-at-a-time
    resolutions would have made the feature practically unusable at the
    exact scale it exists to help with. Fixed by dropping just the
    resolved group from the in-memory list the tab already holds and
    re-rendering locally — zero additional service calls — rather than
    reaching for a persisted "resolved" flag (which would reopen the
    staleness problem the fresh-recompute design deliberately avoids).
    A partial failure (some files in the group failed to delete) keeps
    the group visible instead of assuming it's resolved, since its real
    DB/disk state may not actually match that.

    `mypy --strict` clean; full suite 470 passed / 1 skipped, run 3x.
    [HISTORY §40](docs/HISTORY.md#40)

41. **Bounded verification pass (2026-08-30) — one real bug found and
    fixed in `ui/workers.py`, the stress test extended to cover the
    Duplicates tab, several stale docs cross-references fixed.**

    **Support link.** The real Revolut link
    (`https://revolut.me/kddimitrov`) replaced item 35's placeholder in
    `help_text.SUPPORT_LINKS`. PayPal's is still a deliberate
    placeholder — not ready yet, tracked separately.

    **Stress test extended to cover the duplicate detector — done, and
    it caught a real bug on the first live run.** `test_stress_e2e.py`
    predated items 38-40 entirely; it never exercised fingerprinting/
    clustering/delete worker traffic overlapping with Sync/Scan/Match/
    Download. Extended to register a small, disposable library location
    (two byte-identical synthetic WAVs, not a single byte of the real
    X9 Pro library — `find_duplicate_groups()` recomputes a whole
    location's clustering from scratch every call and costs ~10 real
    minutes over the real ~3,100-file production library per item 39,
    which would defeat the point of a fast, repeatable regression
    guard), then fires Compute fingerprints/Find duplicates alongside
    the existing sync/scan/match flurry and exercises a real Delete
    click (checkbox + button) against the scratch group during the
    interleaved loop.

    **Real bug, found on the first live run, not reasoned about in the
    abstract:** the run failed on `active_workers == 0` (1 worker still
    registered after 300s+), and printed an uncaught
    `RuntimeError: Signal source has been deleted` from
    `ui/workers.py::Worker.run()`'s `_dispatcher.task_finished.emit(...)`
    call, during process teardown. Root cause, confirmed via an isolated
    repro (a `QThreadPool` worker mid-sleep while
    `shiboken6.Shiboken.delete(_dispatcher)` was called from the main
    thread): a straggling background worker — here, the 20s backend-poll
    timer's `poll_downloads()` retrying a real `locked` download row
    against slskd, which returned a real 500 from `/transfers/downloads/
    batches` — can still be genuinely in flight when the app (or, in a
    real quit, the interpreter) starts tearing down `_dispatcher`; when
    the worker thread finally finishes and calls `.emit()`, the
    dispatcher's native QObject is already gone. Not a leak in the
    classic item-29/32 sense (the worker DOES eventually finish) — a
    real shutdown-safety gap: nothing bounded how long a worker could
    run, and nothing protected a late `.emit()` against a torn-down
    dispatcher. Reachable in real usage too, not just this test: a user
    quitting `seeker-ui` while a backend poll's slskd calls are still in
    flight hits the identical race.

    Fixed with the smallest change that closes it: `Worker.run()` now
    checks `shiboken6.Shiboken.isValid(_dispatcher)` immediately before
    each `.emit()` call and silently drops the result if it's gone —
    nobody is listening once the dispatcher is torn down regardless of
    why, and dropping the result is strictly safer than letting a
    background thread raise into whatever Qt/CPython is doing mid-
    shutdown (exactly the class of race this file's own pre-existing
    docstring already documents turning into a real segfault once
    before). Re-verified live against the same isolated repro: no more
    exception, no more traceback, the worker's result is just dropped.
    The stress test itself also got a real, matching fix — a bounded
    (60s) drain wait for `active_workers == 0` before `main_window
    .close()`, so a legitimately-slow-but-real network round trip gets
    a fair chance to land before the leak-check assertion runs, rather
    than the test crying wolf on ordinary network latency. A worker that
    genuinely never completes still fails the assertion after the wait.

    **Re-run clean after both fixes, real numbers, not just pass/fail:**
    311s real duration, RSS 259.4MB → 398.0MB (Δ+138.7MB, under the
    250MB ceiling — higher than item 32's own +58.1MB baseline, almost
    entirely from the initial construction/sync/scan/match/duplicates
    burst in the first ~2.5s; the remaining ~300s/20 interleaved cycles
    added only ~9MB total, ≈0.45MB/cycle, the same legitimate-residual
    order of magnitude item 32 established, not a growing leak), fds
    6 → 27 (Δ+21, under 40), threads 5 → 14 (Δ+9, under 40),
    `active_workers` at 0 at the end. Duplicates lifecycle genuinely
    overlapped with the rest, not run sequentially: fingerprinting (2
    files) and the group delete (`Deleted: 1, Failed: 0`) both completed
    within the first 2.4s, while sync/scan/match and 3 concurrent
    downloads were still in flight. The same real slskd 500 kept
    recurring on later backend-poll cycles throughout the run (an
    external, environmental condition — a genuinely flaky real peer/
    file, unrelated to this fix) without ever again leaving a stray
    active worker at the end, confirming the fix holds under repeat
    exposure to the same failure, not just once. Scratch location and
    files removed in `finally` every time, confirmed via the real
    "Removed library location" log line. Full fast suite (470 passed /
    1 skipped) and `mypy --strict` stay clean. [HISTORY §41](docs/HISTORY.md#41)

    **Documentation consistency pass — several real staleness issues
    found and fixed, not manufactured.** Two roadmap items (28, 29) had
    matching detailed `docs/HISTORY.md` sections but, unlike every other
    item, no `[HISTORY §N]` cross-reference link — added both; same gap
    found and fixed for item 36. Item 5's own text described `select_
    best` as the live candidate-selection function — genuinely stale:
    item 15 later removed it as unused dead code, and item 8's
    `select_downloads` is the real, current entry point — corrected
    in place. Both this file's and README's "current layout" file trees
    were missing three real files added since they were last updated
    (`audio_fingerprint.py`, `library/duplicate_service.py`,
    `file_deletion.py`, from items 38-40) plus two from items 33/34
    (`ui/download_eta.py`, `ui/help_text.py`) — brought current in both
    files. Checked, not just assumed: every numeric constant this file
    cites (`AUTO_MATCH_THRESHOLD`, `DEFAULT_MAX_QUEUE`,
    `MAX_UPGRADE_SHORTLIST`, `POLL_INTERVAL_MS`/`BACKEND_POLL_
    INTERVAL_MS`, `STALL_SAMPLE_COUNT`, `CLIPPING_AMPLITUDE_THRESHOLD`,
    `DUPLICATE_SIMILARITY_THRESHOLD`), every CLI command/flag name, the
    Spotify field-name/endpoint history, the `SLSKD_*` env var names,
    and the packaging `AppId` GUID all still match the real code —
    confirmed via direct `grep` against source, not assumed correct
    because they'd been correct before. One real code-side gap surfaced
    incidentally while cross-checking item 29's own "no undeclared
    transitive dependency" audit against the newer duplicate-detector
    files: `numpy` is imported directly by `audio_fingerprint.py` and
    `duplicate_service.py` (items 38/39) but was never added to
    `pyproject.toml`'s `dependencies` — present only transitively via
    `librosa`/`scipy`/`soundfile`. Added explicitly (`numpy>=2.5.2`,
    the real installed version), matching this project's own established
    floor-pinning convention.

    **Follow-up (2026-08-30), closing two loose ends this item's own
    `ui/workers.py` fix left open, plus the code comment it never got
    around to.** The `Shiboken.isValid(_dispatcher)` check this item
    added before the dispatcher emit was itself check-then-act, not
    atomic — proven, not just suspected: a deterministic repro
    (`tests/_workers_teardown_race_repro.py`) that forces
    `_dispatcher`'s deletion into the exact gap between that check
    returning True and the following `.emit()` call escaped an
    uncaught `RuntimeError` in **50/50 forced trials** against this
    item's shipped code — the same discipline item 39's own aborted
    `threading.RLock` attempt should have gotten the first time
    ("reduces the frequency" isn't "fixed"). Root cause confirmed live
    too, not assumed: calling `.emit()` on a signal whose source
    QObject was already deleted always raises this same clean,
    catchable `RuntimeError` — never a segfault or partial state, even
    when the deletion lands synchronously immediately beforehand — so
    the actual safe boundary is wrapping the `.emit()` call itself, not
    a preceding validity check. Fixed with `ui/workers.py::
    _emit_or_drop()`, which both dispatcher-emit call sites in
    `Worker.run()` now go through; re-running the same forced repro
    against the fix: **0/50 escapes** (both the "dispatcher already
    dead for `run()`'s entire duration" case and, for future-proofing,
    the "check-then-act gap" case, which no longer even applies since
    `run()` doesn't call `isValid` in that path anymore — the repro
    reports whether that hook fired at all, so a future regression
    reintroducing a check-then-act shape would be caught honestly
    rather than the test silently passing for the wrong reason).

    Second loose end: whether the deferred native-delete
    (`QTimer.singleShot(0, ...)`) could ever get scheduled twice for
    the same worker. Confirmed structurally impossible, not just
    tested — `_handle_task_finished`/`_handle_task_error` both
    `_callbacks.pop(task_id, None)` before scheduling it, and
    `Worker.run()`'s own try/except/else emits at most one of the two
    dispatcher signals per task, so at most one handler invocation ever
    sees a non-`None` entry for a given `task_id` to begin with. Now
    factored into a single `_schedule_native_delete()` helper (both
    handlers call it instead of inlining `QTimer.singleShot(...)`
    directly) whose docstring carries this guarantee plus the
    previously-undocumented-at-the-call-site explanation of why plain
    `QThreadPool` autoDelete and a synchronous delete from inside the
    signal handler both failed — the comment item 40 asked for and
    this file never confirmed landed, now in place specifically so a
    future contributor can't "simplify" it back into either shape
    without reading why not.

    `mypy --strict` clean; full suite 471 passed / 1 skipped (the one
    skip is `test_stress_e2e.py`'s own opt-in gate, unrelated to
    Docker/the X9 Pro drive — no Docker-conditional skip exists
    anywhere in the fast suite right now).

42. **Custom app icon wired in and live-verified (2026-08-30) — closes
    the "no custom .icns/.ico" gaps items 30/31/36 all flagged as
    accepted-but-cosmetic.** `packaging/icons/seeker_icon.icns`/
    `seeker_icon.ico` now wired into all four places that were
    previously `None`/unset/generic-default: `seeker.spec`'s
    `BUNDLE()` (macOS `.app`/Dock/Finder icon) and `EXE()` (picks
    `.ico` on `win32`, `.icns` on `darwin`, `None` on Linux — `EXE`'s
    icon param is only actually consumed on Windows/macOS); `dmg_
    settings.py`'s `icon` setting (the `.dmg` volume icon — resolved
    the same cwd-relative way `readme` already was, since dmgbuild
    `exec()`'s the settings file with no `__file__` in scope, which a
    first attempt using `__file__` learned the hard way); and
    `seeker.iss`'s `SetupIconFile` (installer/uninstaller exe) plus a
    `seeker_icon.ico` copy installed to `{app}` so the Start Menu/
    Desktop `[Icons]` entries have a real on-disk `IconFilename` to
    point at.

    **Live-verified for real on macOS, not assumed from the diff.**
    Rebuilt `Seeker.app` and `Seeker.dmg` for real. Screen-recording
    permission is still absent in this environment (same gap item 30
    hit), so verification went through `NSWorkspace.iconForFile:`/
    `NSRunningApplication.icon` via `osascript` instead — the exact
    APIs Finder and the Dock themselves call to render an icon, not a
    proxy for them. Confirmed: the bundled `.icns` inside `Seeker.app`
    byte-matches the source file and `Info.plist`'s `CFBundleIconFile`
    points at it; `NSWorkspace.iconForFile:` on the built `.app`
    renders the real custom icon; the real `.dmg`, mounted for real,
    carries a `.VolumeIcon.icns` that byte-matches the source with the
    Finder custom-icon flag set on the volume; and `NSRunningApplication
    .icon` for the actually-launched, actually-running `Seeker` process
    renders the same real custom icon — the literal thing the Dock
    displays for a running app. All three surfaces (Finder, `.dmg`
    volume, Dock) confirmed live.

    **Windows stays written-but-unverified, as scoped** — no real
    Windows machine in this environment; the `.iss`/`.spec` Windows
    branches are correct by construction (mirroring the already-
    verified macOS wiring) but not run for real, same standing caveat
    as item 36. [HISTORY §42](docs/HISTORY.md#42)

43. **Fix: Spotify token cache was still CWD-relative — done
    (2026-08-31).** Item 18 migrated the DB to platformdirs but left
    the Spotify token cache CWD-relative, assuming it was out of
    scope — a real bug, since a double-clicked `.app` gets CWD = `/`
    (the read-only Signed System Volume) from macOS, unlike `uv run
    seeker-ui`'s writable project-root CWD, so saving the token after
    a real OAuth completion failed with `[Errno 30] Read-only file
    system: '.seeker'`. Fixed exactly mirroring item 18's own
    DB-migration shape: `_resolve_spotify_token_path()` resolves into
    the same per-user `platformdirs` directory, computed once per
    `Application()` instance (`self._spotify_token_path`, not a module
    constant) and migrated via a new `_migrate_legacy_spotify_token()`
    sharing `_migrate_legacy_database`'s guard logic (factored into
    `_migrate_legacy_file()`) — deliberately **not** `sys.frozen`-gated,
    since the token cache has no reason to stay CWD-relative in dev
    mode either. Live-verified two ways, not just by test: a real
    Finder-equivalent launch (`open -W` against a diagnostic `.app`,
    confirmed `cwd='/'`) completed the save without error, and this
    dev machine's own real pre-existing legacy token was migrated and
    successfully refreshed against Spotify's real token endpoint on a
    real `uv run python` startup. [HISTORY §43](docs/HISTORY.md#43)

44. **Fix: Docker detection was PATH-dependent and broke under a real
    double-clicked `.app` — done (2026-08-31).** The wizard's Docker
    step reported "not installed" and Settings' SoulSeek setup raised
    `[Errno 2] No such file or directory: 'docker'` even with Docker
    Desktop genuinely installed and running — a GUI launch gets
    launchd's bare default PATH (`/usr/bin:/bin:/usr/sbin:/sbin`,
    confirmed live via a real ephemeral LaunchAgent probe), which
    excludes both `/usr/local/bin` (Docker Desktop's own CLI symlink)
    and `/opt/homebrew/bin` (Apple Silicon Homebrew) — the same "works
    via `uv run`, breaks via a real double-click" shape as item 43,
    just for PATH instead of CWD. Fixed once at the shared layer:
    `docker_setup.py::ensure_full_path_environment()` merges
    `/usr/libexec/path_helper -s`'s output (what a real login shell
    resolves via `/etc/paths`+`/etc/paths.d/*`) plus explicit
    `/opt/homebrew/bin`/`/usr/local/bin` fallbacks into
    `os.environ["PATH"]`, called once at the top of
    `Application.__init__` — every `docker_setup.py` subprocess call
    already inherits `os.environ` (`env=None` or
    `{**os.environ, ...}`), so this fixes every current and future
    Docker call site with no per-call-site change. Deliberately
    best-effort: any failure of the `path_helper` probe itself falls
    back to the explicit dirs rather than raising, since this runs
    unconditionally at every `Application()` construction.
    Live-verified, not just by test: a real launchd-spawned process
    (an ephemeral LaunchAgent, since this sandbox's `open` was
    confirmed to NOT reproduce a genuine minimal-PATH launch — see
    HISTORY) started with the real minimal PATH, and after
    `Application()` ran, `detect_docker_state()` — the exact function
    both real UI surfaces call — correctly reported `RUNNING`,
    matching this machine's actual Docker Desktop state.
    [HISTORY §44](docs/HISTORY.md#44)

45. **Fix: a completed settled download never entered the library —
    done, live-verified (2026-08-31).** `poll_downloads()`'s ordinary
    settled-completion branch called `_move_completed_file()` and
    stopped — it never called `scanner.index_single_file()` or wrote a
    `track_matches` row the way the upgrade-confirmation path
    (`apply_upgrade_decision`) always has. A completed download stayed
    `NOT_FOUND` on the Dashboard forever (`DashboardService
    ._compute_status` requires both `match_method='auto'` AND a
    resolvable `local_file_id`) and stayed invisible to `Match`
    (`match_all()` only ever considers `local_files` rows that already
    exist) — and `get_unmatched_for_playlist` (filters on
    `match_method IS NULL`) would have let a second `download` run
    genuinely re-search and re-request a file already on disk, since
    item 16's creation-time dedup guard (`get_active_for_track`) only
    covers ACTIVE requests, not `completed` ones.

    Fixed by adding `DownloadService._index_and_match_settled_download()`
    — mirrors `apply_upgrade_decision`'s own index+match tail exactly,
    called from both places `poll_downloads()` reaches a real settled
    completion (the main pending loop, and `_retry_locked_request`'s
    completed branch for a human-confirmed needs-review candidate that
    turned out locked). `match_method='auto'` is set unconditionally —
    provenance (this exact file was searched, filtered, and downloaded
    FOR this exact track) is a stronger signal than fuzzy matching, the
    same reasoning item 26 used for `confirm_review_candidate`. Unlike
    `apply_upgrade_decision`'s hardcoded `score=100.0` sentinel, the
    real score is computed via `library/matcher.py`'s existing
    `find_best_match(track, [local_file])` (a list of one — no new
    scoring function needed) and stored as-is, so a genuinely bad
    pairing stays visible in the data. Wrapped in its own try/except
    per the standing per-item batch rule — an indexing failure can't
    undo the already-set `completed` status or abort the rest of the
    poll; counted separately as `indexed`/`index_failed` in the
    returned counts dict.

    **A second real, independent bug was found live while verifying
    this fix end-to-end, and fixed in the same pass, since it was
    directly blocking verification:** `_move_completed_file` located
    the downloaded file via `Path(slskd_download_dir).rglob(basename)`
    — `rglob()` treats its argument as a glob PATTERN, not a literal
    name. Real Soulseek filenames routinely contain `[` `]` (release
    tags like `[www.dj-promo.org]`, `[FLAC]`), which `fnmatch`
    interprets as a character class — the lookup silently returns an
    empty list (no exception, no warning) and the file is never moved,
    staying stuck `downloading` forever. Fixed with `glob.escape()`
    around the basename.

    **Live-verified against real production data, both bugs together**
    (2026-08-31): a real in-flight `download_requests` row (id 16,
    track "Bit Perfect" by Zigi SC/A-Cray) had genuinely finished
    transferring on slskd's side (`bytesTransferred == size`,
    `state: "Completed, Succeeded"` confirmed directly via slskd's own
    API) but was stuck `downloading` in the DB — exactly the glob bug
    above, on a filename containing `[www.dj-promo.org]`. After both
    fixes, a real `seeker downloads status` run: moved the real file to
    its real destination; created a real `local_files` row (id 3241,
    real tags read via mutagen — `tag_artist="A-Cray, Zigi SC"`,
    `duration_ms=306259`); created a real `track_matches` row
    (`match_method='auto'`, `score=63.64`, genuinely below
    `AUTO_MATCH_THRESHOLD=70` and left visible rather than hidden, per
    the design above); `DashboardService.get_playlist_track_status`
    confirmed `IN_LIBRARY` for the track; `get_unmatched_for_playlist`
    confirmed the track no longer appears. A UI follow-on was added
    too — `MainWindow._trigger_backend_poll`'s `on_finished` now also
    calls `_poll_selected_playlist()`, so the Dashboard's track table
    refreshes immediately after a real backend poll instead of waiting
    up to 2s for the next display tick; covered by a new Qt test
    (`test_backend_poll_refreshes_selected_playlist_track_table`).

    **No legacy backfill was actually needed.** Queried the real
    production DB for any other `role='settled', status='completed'`
    row with no `track_matches` row before writing any code, per the
    task's own instruction to reproduce against real data first —
    found none; every one of the 5 real completed rows already had a
    match (recovered manually in a prior session, per item 27's own
    documented Kamäleon fix). A real `seeker library scan` +
    `seeker library match` afterward recovered one unrelated,
    genuinely-organic match (`Breach` by Balron, Audio, auto/100.0 — a
    file already on the real drive, unconnected to any tracked
    download) and, as an interesting but out-of-scope-to-fix side
    effect, demoted the just-fixed Bit Perfect match from `auto` back
    to `needs_review` at the identical score (63.6, below the 70
    threshold) — `match_all()` recomputes every `track_matches` row
    uniformly from scratch on every run with no notion of "provenance-
    confirmed," a pre-existing property that applies equally to item
    26's human-confirmed matches, not something this fix introduced or
    was asked to change. [HISTORY §45](docs/HISTORY.md#45)

46. **Tagged tracks stop asking to be tagged — done (2026-08-31).**
    `TrackStatus` gains `tagged_at: str | None` (ISO string, matching
    this codebase's existing str-not-datetime convention for every
    other stored timestamp — `matched_at`/`completed_at`/`LocalFile
    .tagged_at` itself — deliberately NOT the `datetime` type an
    earlier draft of this task specified, to stay consistent), resolved
    in `DashboardService._compute_status` from the matched
    `local_files` row. Dashboard Actions column:
    `IN_LIBRARY`+untagged → the existing "Tag" button;
    `IN_LIBRARY`+tagged → a muted "Tagged" label with a tooltip
    showing the local date/time; anything else → blank, unchanged.
    Right-click on a tagged row offers "Re-tag" (does nothing for an
    untagged or not-in-library row).

    **The backend `force` flag and CLI `--force` for `library tag`
    turned out to already exist**, built in an earlier, uncommitted
    session with no corresponding roadmap entry — confirmed by reading
    `metadata_service.py`/`cli.py` directly before writing anything,
    not assumed. Only the UI side (a "Re-tag already tagged files"
    checkbox on the tagging panel, wired through `_resolve_tag_options`
    into all three existing triggers, plus the per-row "Re-tag" menu
    action which always forces regardless of the checkbox) and
    `TrackStatus.tagged_at`/the Actions-column display were new.

    New `ui/formatting.py` — `format_timestamp`/`format_file_size`/
    `format_speed`/`format_duration_seconds`, shared by this, a future
    History page, and the Downloads ETA. `download_eta.py`'s own
    `format_eta_seconds` was moved in (re-exported under its old name
    for backward compatibility) rather than kept as a second copy —
    there was no pre-existing byte-size/speed formatter anywhere in
    `ui/` to move (checked directly: the Downloads tab's progress bars
    only ever used raw byte counts as a `QProgressBar` range/value, no
    text formatting at all). **Real, confirmed fact used to write the
    timestamp conversion correctly:** every stored timestamp in this
    codebase (`tagged_at`/`matched_at`/`completed_at`) is written via
    `datetime.now(timezone.utc).isoformat()` — timezone-AWARE UTC, not
    naive — so `format_timestamp` uses `.astimezone()` (correct for an
    aware value) rather than assuming a naive-UTC value that would need
    a manual UTC-offset attach first; verified directly against the
    write sites before writing the formatter, not assumed either way.

47. **Design system (dark theme + InlineNotice) — done, live-rendered
    and checked, not just written (2026-08-31).** New `ui/theme.py`
    (color/spacing/radius tokens, `apply_theme(app)` — Fusion style +
    matching QPalette + one global QSS stylesheet, called once from
    `main_ui.py` before any window is constructed) and `ui/notice.py`
    (`InlineNotice` — a persistent, dismissible banner). Layout
    conventions (24/20 page margins, action-row ordering) documented as
    a docstring in `theme.py`; applying them to every existing page is
    Phase 4's job, not done yet outside the two screens touched here
    (Dashboard, `AboutDialog`).

    **Root cause of "an error disappears before you've had time to
    read it," found live, not hypothesized-and-guessed:**
    `ui/workers.py::run_worker()` clears its target `status_label` to
    `""` unconditionally at the START of every call, before the
    background task runs. `MainWindow._poll_selected_playlist()` —
    which passes `status_label=self.status_label` — runs on both the 2s
    `poll_timer` tick AND after every real backend poll (item 45's own
    new hook), completely independent of whatever the user was just
    shown. So any validation error or selection-guard message written
    to that one shared label had at most ~2 seconds, often far less,
    before the very next poll tick silently wiped it — a structural
    bug, not a timing one. Fixed by routing the Dashboard's actionable
    messages (BPM-range validation, "select a track/playlist first")
    through a new `self.dashboard_notice: InlineNotice`, which lives
    outside `run_worker`'s `status_label` plumbing entirely.
    `status_label` remains for genuinely disposable progress text
    ("Tagging 3 selected track(s)...") that nobody needs to still see
    a few seconds later. **Not yet swept everywhere** — one other real
    instance of the identical bug class was spotted but left alone in
    this pass (`_on_upgrade_decision_finished`'s Review-tab success
    message, also written to the same shared `status_label`); a full
    sweep of every remaining `status_label` call site for this same
    class belongs to the broader Phase 3/4 rollout, not claimed done
    here.

    **Three more real, live-found Qt/QSS bugs, each confirmed via a
    bisected minimal repro before being fixed — this is exactly why
    the task's own "render real screens and look at the PNGs" rule
    exists, not a formality:**
    1. `QTableWidget::item { padding: ...; }` in the stylesheet
       corrupts the paint of any `QPushButton` living inside a cell
       *widget* (`setCellWidget` — used throughout this app's Actions/
       Progress columns) into garbled, ghosted text. Real, reproducible
       Qt/Fusion bug, bisected down to this exact rule via a minimal
       standalone repro (confirmed clean with every other theme rule
       present, corrupted the instant this one rule was added back).
       Fixed by dropping it from `QTableWidget` (kept on `QListWidget`,
       confirmed safe there since nothing in this app puts a widget
       inside a `QListWidget` item) — a code comment in `theme.py`
       documents why, so a future "just add cell padding back" doesn't
       silently reintroduce this.
    2. `InlineNotice(QWidget)`'s own per-instance `setStyleSheet()` call
       (the colored border/background) silently did nothing — a plain
       `QWidget` subclass doesn't paint its own stylesheet background/
       border by default in Qt unless `Qt.WidgetAttribute
       .WA_StyledBackground` is set. Fixed with that one attribute.
    3. `InlineNotice`'s dismiss button (`setFixedWidth(28)`) rendered
       with completely invisible text — the global `QPushButton` rule's
       own horizontal padding (`6px 14px` = 28px of padding alone)
       consumed the entire fixed width, leaving zero space for the
       glyph. Fixed by dropping the fixed width (sized by its own
       `sizeHint` like every other themed button) and using a plain
       ASCII "X" instead of a Unicode "✕"/"×" glyph, avoiding any
       dependency on multiplication-sign coverage in whatever font a
       given platform falls back to.

    **Screenshots, real widgets, real theme applied (scratch, not
    committed):** Dashboard with a mix of all four track states plus a
    live error `InlineNotice`; `AboutDialog` (a real dialog with one
    primary "Close" button, left-aligned per the layout convention);
    Downloads tab with a determinate 50%-complete progress bar and an
    indeterminate queued one. All three inspected directly before
    calling this done — the corrupted-button and invisible-dismiss-text
    bugs above were both found this way, not by reading the QSS and
    assuming it was fine.

    New tests: `tests/test_notice.py` (6, `InlineNotice`'s show/hide/
    dismiss/action-wiring behavior) and a regression test
    (`test_dashboard_notice_survives_the_2s_poll_that_used_to_wipe_it`)
    that calls `_poll_selected_playlist()` directly and asserts the
    notice is untouched — the real mechanism that used to wipe it, not
    a timer/sleep-based approximation. No automated test exists for the
    two remaining Qt/QSS rendering bugs (`WA_StyledBackground`, the
    `QTableWidget::item` cell-widget corruption — a pixel-level visual
    assertion isn't practical in this fast suite); the durable guard
    there is the code comment in `theme.py` plus this entry — see the
    follow-up below for why the progress-bar bug's own guard didn't
    stay in that same "code-comment only" category. `mypy --strict`
    clean; full suite 510 passed / 1 skipped. [HISTORY
    §47](docs/HISTORY.md#47)

    **Follow-up (2026-08-31), three requested fixes before Phase 4,
    all confirmed live.** (1) Widened the surface/border contrast steps
    (`BG_APP #100E15`, `BG_SIDEBAR #15121D`, `BG_SURFACE #1D1929`,
    `BG_SURFACE_2 #29243A`, `BORDER #3A344E`, `BORDER_STRONG #4E4768`
    — text/accent/status colors unchanged) so default buttons read as
    clickable against both a page background and a table-cell
    background. (2) **Queued/indeterminate progress bar investigated
    for real root cause, not just reskinned.** The code was already
    correct — `_build_progress_widget` genuinely calls
    `bar.setRange(0, 0)` for a queued/no-bytes-yet row, Qt's real
    native indeterminate mode. Confirmed via a bisected minimal repro
    that the actual cause was the stylesheet: Qt's native indeterminate
    mode paints an animated, moving diagonal-striped pattern by
    default, but the INSTANT any `QProgressBar::chunk` rule matches a
    bar — regardless of what properties it sets — Qt switches that
    sub-control to the QSS box-model painter for every state of that
    bar, indeterminate included, which has no concept of the native
    busy animation and paints a static solid rect instead (confirmed:
    a bare `QProgressBar { ... }` container rule with zero `::chunk`
    rule preserves the real animated stripe perfectly; adding any
    `::chunk` rule back, even one with no `background-color` at all,
    replaces it with a static block). There is no `:indeterminate`
    pseudo-state in Qt's QSS to scope a rule around this. Fixed by
    removing `QProgressBar::chunk` from the global stylesheet entirely
    and adding `theme.style_determinate_progress_bar(bar)` — a
    per-instance `setStyleSheet()` call applied ONLY at the two real
    call sites once a bar is confirmed determinate (`main_window.py`'s
    Downloads-tab and Dashboard per-track progress cells), never to an
    indeterminate one. Now covered by real tests, not just a code
    comment: `test_downloads_tab_progress_bar_indeterminate_with_no_
    bytes_yet` asserts `bar.styleSheet() == ""`,
    `test_downloads_tab_progress_bar_determinate_with_real_bytes` and
    the new `test_dashboard_downloading_progress_bar_gets_the_accent_
    chunk_style` assert `"chunk" in bar.styleSheet()` — a regression
    that started applying the accent fill unconditionally (the exact
    shape of the original bug) would now fail a fast test, not just
    require a human to re-render and notice. (3) Re-rendered
    `phase3_dashboard.png` and `phase3_downloads.png` (same scratch
    paths as before, same scenes) and inspected both directly: the
    queued row now shows the real animated stripe pattern, clearly
    distinct from the downloading row's solid 50% fill; button borders
    read as clearly clickable in both the toolbar (page-level) and the
    Dashboard's Actions-column context. `mypy --strict` clean; full
    suite 511 passed / 1 skipped.

48. **Shell restructure: sidebar instead of tabs — done, all six pages
    rendered and inspected (2026-08-31).** `MainWindow`'s `QTabWidget`
    replaced with a fixed-`SIDEBAR_WIDTH=200` sidebar (`BG_SIDEBAR`,
    the "Seeker" wordmark, then Dashboard/Downloads/Review/Duplicates/
    History as checkable nav buttons in one exclusive `QButtonGroup`,
    a stretch, then Help/Settings pinned at the bottom) driving a
    `QStackedWidget`. Each existing tab body became a page via one
    shared `_build_page(title, subtitle, content)` helper — title +
    the existing `help_text.py` subtitle above the content, identical
    `24/20` page margins and `12px` spacing everywhere, per Phase 3's
    own documented layout convention (this is the first place that
    convention is actually enforced by code rather than copied by
    hand). `_show_page(key)` sets the stack index and the matching nav
    button's checked state; `_register_page`/`self._page_indices: dict
    [str, int]` replace the old bare tab-index bookkeeping.
    `_on_tab_changed`/`_duplicates_tab_index` renamed
    `_on_page_changed`/`_duplicates_page_index` — same lazy-load-on-
    first-real-visit logic, unchanged (`QStackedWidget.currentChanged`
    is the identical signal shape `QTabWidget` gave it). Window default
    `1180×760`, minimum `960×640`.

    **Settings deliberately stays a dialog, not a page — a scope
    decision, not an oversight.** The task's own framing ("existing
    tab bodies become pages — this is a shell change, not a rewrite of
    each screen's contents") only covers what was already a tab body;
    `SettingsWindow` was never one — it was already a separate modal
    `QDialog` opened from the toolbar. Converting its own internal
    4-tab structure into stacked shell pages would be exactly the kind
    of screen-content rewrite the task explicitly scoped out. It's now
    a plain, non-checkable button relocated to the sidebar's bottom
    section (next to Help, per the task's own placement), not a member
    of the exclusive nav `QButtonGroup` — clicking it opens the
    unchanged dialog; nothing about "which page is active" needs to
    track it.

    **History and Help are real nav slots now, placeholder content —
    a deliberate, documented choice, not scope creep.** Both future
    pages (History is item 10 of the larger brief this shell serves,
    Help is item 11) get a real sidebar entry and a real
    `QStackedWidget` page now, each with its own real
    title/subtitle (`help_text.HISTORY_PAGE_SUBTITLE`/
    `HELP_PAGE_SUBTITLE`) and a one-line "coming in a future update"
    placeholder body — so the sidebar's final shape is correct today,
    and a later phase only needs to replace the placeholder content,
    never touch navigation wiring. The existing Help menu → About
    Seeker action in the real `QMenuBar` is untouched and unrelated —
    kept per the task's own "keep the real QMenuBar" instruction.

    **Nav badges** (`_update_nav_badge`) read counts already computed
    by the existing 2s poll — `_render_active_downloads`
    (`len(downloads)`) and `_render_review_items`
    (`len(candidates) + len(upgrades)`) — no new poll added. Text-based
    (`"Downloads  (2)"`, plain `"Downloads"` at zero — never `"(0)"`),
    not a separate sibling badge widget, so each nav item stays one
    real `QButtonGroup` member with no composite-row plumbing.

    **Nav item styling reuses Phase 3's own established gotchas
    correctly, not by luck.** `QPushButton` is already painted through
    Qt's style system (confirmed in Phase 3: unlike a plain `QWidget`,
    it needs no `WA_StyledBackground`), so a checkable, flat
    `QPushButton` with a `navItem="true"` property is sufficient — the
    `[navItem="true"]:checked` QSS rule (`ACCENT_SUBTLE` fill + 3px
    `ACCENT` left border) needed no new workaround. The sidebar panel
    itself, a plain `QWidget`, DOES need
    `WA_StyledBackground` for its own `#sidebarPanel` background rule —
    applied from the start this time, not found the hard way again.

    **All six pages rendered offscreen and inspected directly** (per
    the task's own "grab a PNG of every page and look at it"
    instruction) — scratch, not committed. Confirmed live: the active
    nav item's accent left-border/fill, the wordmark, badge text
    (`"Downloads  (2)"` with real seeded data), Settings' distinct
    (non-flat, bordered) look versus the flat nav buttons, and default
    window sizing (`1180×760`, confirmed via `window.size()`).

    New tests: default/minimum window size, Dashboard-is-default-
    active-page, `_show_page` switches both the stack and the checked
    nav button, the nav group's exclusivity and that Settings is
    genuinely excluded from it, live badge counts (including the
    zero-count "no badge, not `(0)`" case), and that History/Help pages
    exist with their own real subtitles. Existing Duplicates-tab-
    lazy-load tests updated to the new `_show_page`/`_page_indices`/
    `_on_page_changed` shape rather than deleted. The opt-in stress
    test's own duplicates-tab-switch line updated to `_show_page`
    too (not exercised in this pass — real-drive-gated, per its own
    documented opt-in scope). `mypy --strict` clean; full suite 517
    passed / 1 skipped.

49. **Library locations: pick the folder first, name it later — done
    (2026-08-31).** `LibraryService.add_location_from_path(path)` (new,
    the UI's real entry point) derives the name from the picked
    folder's own basename, auto-suffixing on a name collision ("Music",
    "Music (2)", checked via a bounded loop —
    `MAX_NAME_SUFFIX_ATTEMPTS=50`, untuned, purely a sanity ceiling
    against a real bug, not a real-world limit) and raising
    `LibraryLocationPathAlreadyRegisteredError` (carries the real
    existing `LibraryLocation`) if the path is already registered,
    checked with a new repository `get_by_path()` before ever
    attempting the insert — `library_locations.path` was already
    schema-`UNIQUE` (confirmed by reading `schema.py` directly, not
    assumed), so this check turns what would otherwise be a raw
    `IntegrityError` into a real, named "already registered as X"
    message. `add_location(name, path)` (the CLI's own explicit-name
    entry point) is unchanged. New `LibraryService.rename_location(id,
    name)` → repository `update_name()`, which converts a name-
    collision `IntegrityError` into the identical clean `RuntimeError`
    shape `add()` already used.

    `library_location_picker.py` (already shared between the wizard
    and Settings) dropped its `name` parameter entirely — both callers
    now go through the identical no-name flow, so the wizard's own
    onboarding location is named after its folder too, not the
    previous hardcoded `"Library"` literal. Settings' Locations tab:
    the name `QLineEdit` is gone; "Choose Folder && Add" is now a
    single "Add location…" button; each row gained a "Rename" action
    (a `QInputDialog.getText` prompt, not a heavier inline-edit widget
    — matches the task's own "a small Rename affordance" framing) next
    to the existing "Remove"; a new `self.locations_notice: InlineNotice`
    surfaces the "already registered as X" and rename-collision errors
    persistently, per the task's own explicit ask — everything else
    (Add/Remove progress) stays on the existing transient
    `locations_status_label`, since Settings has no poll timer for
    Phase 3's vanishing-message bug to apply to here.

    Rendered and inspected directly (scratch, not committed): confirmed
    the single Add button, the Rename/Remove pair per row, and a real
    `InlineNotice` correctly naming the pre-existing location on a
    duplicate-path attempt — caught via a properly-isolated pytest
    fixture render after an earlier, broken ad hoc verification script
    (a stub monkeypatch that no-op'd `chdir`/`setattr`) briefly wrote a
    real row into the live production database; found immediately via
    a direct `sqlite3` check against the real DB file, confirmed the
    stray row had zero linked `local_files`/destination references,
    and removed it through the real `LibraryService.remove_location()`
    — verified clean afterward. Recorded here rather than glossed over.

    `mypy --strict` clean; full suite 527 passed / 1 skipped.

50. **Kill the "no configured destination" dead end — done, live-
    rendered (2026-08-31).** `SeekerConfig` gains
    `default_download_location_id: int | None` and
    `default_download_subfolder_per_playlist: bool = True`. **Real
    gotcha, not just additive-by-design:** `config_store.py`'s own
    "flat additive JSON" design only means a MISSING key can't crash a
    load — `load_config()` still lists every field explicitly via
    `data.get(...)`, so the two new fields had to be added there by
    hand or they'd silently reset to their dataclass defaults on every
    load, discarding a real saved value. Fixed; covered by a round-trip
    test and a missing-key-uses-defaults test.

    New `DownloadService._resolve_destination(playlist)` — a
    playlist-specific `download_location_id`/`download_subfolder`
    always wins; otherwise falls back to the configured default, with
    the playlist's own name (sanitized) as the subfolder when the
    toggle is on. Resolved through `_get_config()` fresh on every call,
    not a snapshot — this project's standing rule, so a Settings
    change takes effect with no restart. New public
    `get_resolved_destination(playlist_name)` (read-only wrapper) is
    what the UI checks before ever calling `download_playlist()`.

    **A real, load-bearing gotcha found and fixed while wiring the
    fallback into the actual file-move step, not just the upfront
    guard:** `PlaylistRepository.get_by_track_id()` — the query
    `_move_completed_file()` uses to find a completed download's
    destination — filtered `WHERE p.download_location_id IS NOT NULL`.
    Left as-is, a track whose only playlist relied on the NEW default
    fallback would never even be returned by this query, so the file
    would silently never move — the exact "stuck, no visible error"
    shape item 45 already hunted once for a different reason. Filter
    removed (confirmed it has exactly one real caller); the caller now
    iterates every returned playlist and takes the first one
    `_resolve_destination()` can actually resolve, rather than
    blindly trusting `playlists[0]`.

    New top-level `seeker/filename_sanitize.py::sanitize_path_component()`
    — no prior sanitizer existed anywhere in this codebase (checked
    first). Replaces path separators (both `/` and `\`), Windows-
    reserved punctuation, and control characters with `-`; strips
    trailing dots/spaces (a real, confirmed Windows folder-creation
    failure mode, not cosmetic); falls back to `"Untitled"` if nothing
    usable survives. Tested against real playlist names pulled live
    from this project's own production database, not synthetic ones —
    `"240KM/H"`, `"Node: Reloaded"`, `"Lotus // Trap"`.

    **UI-first error audit (§2), the full list found and fixed —
    two, both real, both reachable from the GUI:** (1)
    `NoDestinationConfiguredError`'s message (`download_playlist`) said
    "Run 'seeker playlists set-destination' first" — shared by the CLI
    and the UI. Made interface-neutral; the CLI now appends its own
    command-line guidance in its own exception handler instead of
    baking it into the shared message. (2)
    `ReviewCandidateMissingSizeError` (`confirm_review_candidate`,
    Review tab's Confirm action — CLI never calls this method at all,
    confirmed by grep) said "re-run 'seeker download'"; rewritten to
    reference the Dashboard's Download button instead. A full grep
    across `src/seeker/` for `.env`/shell-command-shaped strings found
    nothing else real — the rest were code comments or CLI-only
    `print()`s, which are correctly allowed to reference commands.

    **No dead end (§3):** `DestinationDialog` (new, in `main_window.py`
    next to `AboutDialog`) — location combo (prefilled: the configured
    default, else the only location if there's exactly one), subfolder
    field (prefilled with the raw, unsanitized playlist name —
    sanitizing happens later, at actual move time, not display time),
    "Remember this for this playlist" (checked). Confirming ALWAYS
    persists somewhere real — never a one-time, unpersisted choice —
    because `_resolve_destination()` is re-evaluated later, on a
    separate poll cycle, when the file actually completes; nothing
    durable would be left for it to find otherwise. Checked → calls
    the existing `set_destination()` (playlist-specific). Unchecked →
    calls new `Application.persist_default_destination()` (the
    app-wide default) — the only other real destination concept that
    exists; deliberately always persists
    `subfolder_per_playlist=True` in that branch (the field was shown
    prefilled with the playlist's own name, so "per playlist" is the
    honest reading of what was displayed, even if the text was hand-
    edited for this one confirmation — a known, accepted simplification
    of that edge case, not silently dropped).

    **Settings → Destinations (§4):** new "Default Destination"
    `QGroupBox`, genuinely above the per-playlist overrides (not beside
    them) — location combo + subfolder-per-playlist checkbox + a
    primary "Save default destination" button, prefilled from the real
    current config on tab load.

    **Wizard (§5):** right after the library folder is picked, two
    checkboxes — "Download new tracks into this folder" / "in a
    subfolder per playlist" — both checked by default, the second
    hidden while the first is unchecked (same show/hide-on-toggle
    convention as the Dashboard's own BPM-range fields). Confirming
    persists the default destination via the same
    `persist_default_destination()` Settings uses — one real
    mechanism, not two. A genuinely first-time user can no longer
    reach the dead end at all.

    Rendered and inspected directly (scratch, not committed):
    `DestinationDialog` with a real slash-containing playlist name
    ("240KM/H") shown correctly as display text (only sanitized at
    actual filesystem-move time); Settings' Destinations tab with the
    new default group visibly above the per-playlist section; the
    wizard's library step with both checkboxes.

    **A second real, live-found interaction, caught while writing this
    phase's own tests, not a production bug:** a test called the real
    `Application.persist_default_destination()` after directly setting
    `application._config_store` in memory (a fake-Spotify-token test
    convenience already established in `test_settings_window.py`).
    `persist_default_destination()` (like the pre-existing
    `persist_soulseek_config()`) reloads from disk first
    (`load_config()`) before applying its own change — correct and
    safe in real usage, since every `_config_store` mutation already
    goes through `save_config()` immediately, so disk and memory never
    actually drift apart outside a test harness — but it silently
    discarded the test's in-memory-only fake token, breaking a later,
    unrelated `sync_service` access in the same test with a real
    `SPOTIFY_CLIENT_ID is not configured` error that looked at first
    like a UI bug. Traced with real debug prints (not guessed) to the
    disk-reload line specifically. Fixed the TEST (set
    `_config_store` directly via `replace()`, matching how the fake
    token was set up in the first place) rather than changing
    production code that was never actually wrong.

    `mypy --strict` clean; full suite 567 passed / 1 skipped.

51. **Visual guidance: Dashboard "next step" CTA — done, all four
    states live-rendered (2026-08-31).** New `main_window.py` module-
    level `_NextStepFacts`/`_NextStep`/`_decide_next_step()` — a pure
    function (no Qt) deciding which single CTA to show from the
    task's own condition table, tested directly with 11 synthetic-
    fact tests (`tests/test_next_step.py`), no `MainWindow` needed.
    Every fact it branches on comes from a real service/Application
    call, gathered in one background-thread `_fetch_next_step_facts()`
    per the task's own "which CTA to render is presentation logic and
    stays in ui/, but every fact comes from a service method" split.
    Two facts had no existing service method and needed one added:
    `Application.spotify_configured` already existed (reused, same
    signal `onboarding_complete` already trusts); new
    `LibraryService.has_scanned_library()` did not.

    **`has_scanned_library()` is a real, disclosed approximation, not
    a precise fact — no schema change was in scope for this task, and
    `library_locations` has no `last_scanned_at` column.** True once
    any `local_files` row exists anywhere (new
    `LocalFileRepository.exists_any()` — a cheap `SELECT 1 ... LIMIT 1`
    existence check, not `get_all()`, given this project's real
    production library is 3,000+ rows). Known, accepted limitation
    documented at the source: a real scan of a location with
    genuinely zero matching audio files is indistinguishable from
    "never scanned" by this proxy.

    Rendered via a new `InlineNotice` (`self.next_step_notice`, above
    `dashboard_notice` — guidance and errors never overwrite each
    other) with its existing action-button support; `None` from
    `_decide_next_step` (no playlist selected, everything global
    already satisfied) dismisses it rather than showing an empty
    strip. Recomputed on playlist selection and the existing 2s
    `poll_timer` tick — no new timer.

    **Empty states, a real structural change, not just new copy.**
    `track_table` and a new centred `_track_empty_panel` (one message
    label + an optional action button, no bare grid) now live in a
    `QStackedWidget` (`track_area_stack`), swapped explicitly rather
    than the old "leave the table showing whatever it last held"
    behavior. Three real, distinct states, not two: no playlist
    selected at all (`_render_no_playlist_selected()` — new; the old
    code simply returned early here and touched nothing, so this was a
    genuine gap, not just unstyled) shows guidance with no button —
    there's nothing to click but the list itself; a selected playlist
    with no synced tracks yet shows the same panel with a real "Load
    tracks" button (the old `empty_state_label`/loose `sync_tracks_
    button` pair, now properly centered instead of stacked inline
    above the table); anything else shows the real table.

    **Renamed the cryptic global buttons and relocated them off the
    old app-wide `QToolBar` entirely** (removed — nothing else used
    it) — Sync → "Refresh playlists", Scan → "Rescan library folders",
    Match → "Re-match library", onto the Dashboard page itself as a
    secondary action row right after the CTA strip, per the task's own
    placement. Download (playlist-scoped, the one exception — not
    renamed, matching the CLI's own item-22 scope split) sits in the
    same row. Global scope itself is unchanged — still all
    playlists/locations/tracks regardless of what's selected.

    All four real CTA states (Spotify not connected; missing tracks
    with SoulSeek configured, showing a real "2 tracks missing from
    'Test'" / "Download 2 missing tracks"; the quiet green "You're all
    set for 'Test'" success line with no button; no playlist selected)
    plus both empty-table states rendered offscreen and inspected
    directly before committing — scratch, not committed.

    `mypy --strict` clean; full suite 588 passed / 1 skipped.

    **Follow-up (2026-08-31), three real gaps found by re-inspecting
    the item's own screenshots rather than assuming them clean, all
    fixed in the same pass.** (1) The action row's own "Download
    selected playlist" and the CTA's own "Download N missing tracks"
    were genuinely the same action, not just visually similar —
    confirmed by reading `get_unmatched_for_playlist`'s query
    directly (`match_method IS NULL`, which already excludes needs-
    review tracks from BOTH paths), so there was never a real scope
    difference to preserve between them. Fixed by hiding
    `download_button` specifically while the CTA's own current action
    is `"download"` (`step.action != "download"` in
    `_render_next_step`), shown again the instant the CTA moves on to
    anything else — not a second, artificially-different scope
    invented just to justify two buttons. (2) All four action-row
    buttons rendered enabled regardless of whether their action could
    do anything — same `_render_next_step` call now also sets
    `.setEnabled(...)` on all four from the identical facts bundle
    already being computed for the CTA itself (no second fetch):
    Download needs a selected playlist; Sync needs
    `spotify_configured`; Scan needs `has_library_location`; Match
    needs both `has_cached_playlists` and `has_library_location`.
    Disabled rather than hidden, so the row's width doesn't jump
    around as facts change. (3) Existing dialog-flow UI tests raced
    against this new disabled-by-default initial state (the very
    first `_poll_next_step()` call, before any playlist is selected,
    now genuinely disables `download_button`) — fixed at the shared
    `_select_first_playlist()` test helper (wait for
    `download_button.isEnabled()`, not just the selection itself),
    rather than patching each affected test individually. Re-rendered
    both screens that originally showed the problems and confirmed
    directly: exactly one Download CTA visible in the missing-tracks
    scene; all four action-row buttons visibly muted/disabled in the
    Spotify-not-connected scene. `mypy --strict` clean; full suite 595
    passed / 1 skipped.

52. **Wizard: say why the SoulSeek login failed — done, live-verified
    against real slskd (2026-08-31).** The protocol genuinely can't
    distinguish "wrong password on my own account" from "that
    username belongs to someone else" (confirmed live — see below) —
    Step 3's credential form gains a radio pair, "I already have a
    SoulSeek account" (default) / "Create a new SoulSeek account",
    with a line explaining SoulSeek has no separate signup. On
    `BAD_CREDENTIALS`, the copy branches on which radio is checked:
    existing-account mode keeps the username/password and says to
    check the password (case-sensitive); new-account mode clears and
    focuses the username field with a "already taken" message. The
    real raw log detail is never dropped — moved to the status label's
    tooltip (the task's own documented alternative to a "Details"
    expander) in every branch, cleared at the start of each new
    attempt so a stale one can't linger into a later result. Username
    validated before attempting (non-empty, no leading/trailing
    whitespace) — real SoulSeek character constraints weren't cheaply
    confirmable, so nothing beyond that was guessed at, per the task's
    own instruction.

    **A real third state, confirmed live via two genuinely disposable
    throwaway slskd containers — never the real production one —
    exactly the diagnostic-instance discipline this project already
    used for packaging verification (items 30/31).** `check_slskd_
    health` gains `SlskdHealthStatus.KICKED` and its own
    `KICKED_LOG_PATTERNS`, both new. Confirmed real, distinct log text
    — genuinely disjoint from the existing bad-credentials patterns:
    `"Disconnected from the Soulseek server: another client logged in
    using the same username"` (preceded by an Information-level
    `"Kicked from server."`). Real production slskd confirmed
    completely undisturbed throughout (checked directly before and
    after) — the throwaway container was the one that got kicked, not
    the other way around. Wizard shows "Another client is already
    logged in with this username," the real detail behind the
    tooltip as with the other branches.

    **A second, independent real finding from the same live session,
    directly informing how the "bad password" test itself had to be
    designed — see HISTORY §52 for the full narrative:** a brand-new,
    never-before-used username does not produce a rejection at all —
    it silently creates a new account and logs in successfully, live-
    confirming CLAUDE.md's own already-documented "no separate
    signup" fact from a different angle. A genuine bad-credentials
    rejection therefore requires the REAL, already-registered
    username with a wrong password — not just any made-up one.

    Timeout branch's copy now says what to check (Docker still
    running, credentials correct, working internet connection) rather
    than just that it timed out. New tests: one per
    `_handle_health_result` mode (existing-account bad-credentials,
    new-account bad-credentials, kicked — mirroring the existing
    HEALTHY/timeout coverage's own shape), the whitespace-username
    rejection, and the radio pair's default state. All four real
    wizard states (default, both bad-credentials modes, kicked)
    rendered offscreen and inspected directly — scratch, not
    committed.

    `mypy --strict` clean; full suite 600 passed / 1 skipped.
    [HISTORY §52](docs/HISTORY.md#52)

53. **Downloads: aggregate remaining-time header — done (2026-09-01).**
    `DownloadEtaTracker.aggregate(downloads: list[tuple[int, int |
    None]])` — `(request_id, total_bytes)` pairs for every currently
    active download on the Downloads page — returns a new `AggregateEta`
    dataclass. Only downloads with >= 2 samples, a positive latest
    delta, and a known `total_bytes` contribute
    (`eta = sum(remaining bytes over contributors) / sum(their current
    speeds)`); everything else (genuinely queued/no samples yet, still
    calculating, stalled, or a `total_bytes` that's still unknown) is
    counted but excluded from the sum. `_classify()` factors the same
    three-way state `describe()` already computed for one download
    (Calculating/Stalled/Contributing) out into a reusable per-request
    helper, so `aggregate()` classifies every active download the same
    way `describe()` classifies one, instead of a second, drifting copy
    of the same logic.

    `format_aggregate_header()` (pure, no Qt) renders the Downloads
    page's header line: `"About {eta} remaining · {N} transferring ·
    {M} queued (no estimate)"`, dropping the third clause entirely when
    `M == 0`. With zero contributors it reads `"Waiting for transfers to
    start"` normally, or `"All active transfers stalled"` specifically
    when every non-contributing download is STALLED (not just
    "hasn't started yet") — `AggregateEta.all_non_contributors_stalled`
    tracks this explicitly rather than inferring it from counts alone.
    **Standing fact:** the non-contributing bucket is always labelled
    "queued" in the header regardless of a download's real DB `status`
    — a `downloading` row with zero bytes yet or a stalled one reads
    identically to the user either way ("not currently making progress
    I can estimate"), which is the only thing this header communicates;
    splitting it further wouldn't be actionable. `AGGREGATE_ETA_TOOLTIP`
    explains the queued-transfers exclusion (Soulseek queue waits aren't
    predictable — folding them in would make the number look more
    precise than it is), matching item 33's own aggregate-affecting
    design principle.

    Wired into `MainWindow` as a new `downloads_eta_label` above the
    Downloads table, rendered from `_render_active_downloads` on the
    existing 2s poll (no new timer) — collapses to an empty string
    (not a reserved-but-blank strip) whenever there are zero active
    downloads, matching item 27's "blank cell, not a misleading control"
    precedent.

    **Recon (per the task's own explicit "recon only, do not build on
    it" scope) — done, real finding, not inferred:** a real, live
    `GET /api/v0/transfers/downloads/{username}/{id}` against a
    genuinely queued transfer (`state: "Queued, Remotely"`) confirmed
    `placeInQueue` IS declared in slskd's own real
    `slskd.Transfers.Transfer` schema (confirmed via the live
    `/swagger/v0/swagger.json`) — but is absent from the actual
    response body entirely for this real queued transfer, not present
    as `null` (grepped the raw JSON directly). slskd's serializer omits
    null properties, so the field exists in the type but this real
    transfer's own queue position isn't currently known/reported by
    slskd itself. Confirms, with a concrete technical reason rather
    than just restating the existing tooltip claim, why nothing reads
    this field yet — a future revision could poll for it and treat a
    still-null value as "unknown," but that's a decision for later, not
    made here.

    `mypy --strict` clean; full suite 614 passed / 1 skipped.
    [HISTORY §53](docs/HISTORY.md#53)

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

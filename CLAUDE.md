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
│   ├── main_window.py         # sidebar (Dashboard/Downloads/Review/
│                              #   Duplicates/History/Help) + QStackedWidget
│                              #   pages, all on the same QTimer-driven poll
│                              #   pattern (item 48)
│   ├── wizard.py               # onboarding: Spotify / library / SoulSeek
│   ├── settings_window.py      # locations, destinations, connection
│                              #   management, editable thresholds
│   ├── library_location_picker.py  # folder-picker, shared by wizard +
│                              #   Settings — see roadmap item 28 §1
│   ├── download_eta.py         # per-download speed/ETA tracker (item 33),
│                              #   aggregate() header (item 53)
│   ├── formatting.py           # format_timestamp/file_size/speed/duration
│                              #   — shared by History, tagged-at, ETA
│   ├── theme.py                # dark theme tokens + apply_theme() (item 47)
│   ├── notice.py               # InlineNotice — persistent banner (item 47)
│   ├── help_text.py            # centralized tooltips/subtitles/About copy
│                              #   (item 34), incl. SUPPORT_LINKS (item 35)
│   └── workers.py              # QThreadPool Worker + run_worker() — every
│                              #   long-running UI action goes through this
├── models/{playlist,track,track_match,local_file,library_location,
│           soulseek_file,download_request,soulseek_review_candidate,
│           active_download,track_status,upgrade_review,history_event}.py
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
├── history_service.py         # HistoryService.get_recent_events() —
│                              #   derived-only view over download_requests/
│                              #   local_files, no new table (item 54)
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

- [x] Fixed: `cli.py::handle_playlists` instantiated `PlaylistRepository`
      directly instead of going through `Application`. Now goes through
      `application.sync_service`/`application.download_service`
      exclusively, matching every other CLI handler.
      [HISTORY](docs/HISTORY.md#cli-bypassed-application-for-playlist-listing)
- [x] Fixed: `SpotifyClient._get`'s 429-retry loop had no max-attempt
      ceiling. Bounded by `MAX_RETRY_ATTEMPTS = 5` (part of the polish
      pass, item 15). [HISTORY §15](docs/HISTORY.md#15)
- [x] Fixed: `check` command was a stub — now reports the full
      auto-matched/needs-review/unmatched breakdown. See roadmap item 7.
      [HISTORY §7](docs/HISTORY.md#7)
- [x] Fixed: `library/matcher.py` and `soulseek/quality.py` each had
      their own copy of the artist/title fuzzy-matching logic, and the
      two copies drifted apart twice (same root cause as item 2's
      scanner/quality `AUDIO_EXTENSIONS` split). Consolidated into
      `seeker/matching.py` (`artist_matches`, `score_title`,
      `resolve_text_source`, `normalize_filename_text`,
      `AUTO_MATCH_THRESHOLD`, `NEEDS_REVIEW_THRESHOLD`) — both call
      sites now share the same tag-or-filename-stem fallback and the
      same combined-vs-title-only max-scoring logic. Any future
      artist/title matching code belongs in `matching.py`, never a
      third copy.
      [HISTORY](docs/HISTORY.md#matcher-and-quality-fuzzy-matching-logic-drifted-apart-twice)
- [x] Fixed: `download_requests` table now tracks in-flight/completed
      SoulSeek downloads (see roadmap item 6). [HISTORY §6](docs/HISTORY.md#6)
- [x] Fixed: `SpotifyClient.get_current_user_playlists` reads
      `playlist["items"]["total"]`, not `playlist["tracks"]["total"]`
      (live `/me/playlists` responses never contain a `tracks` key).
      [HISTORY](docs/HISTORY.md#spotify-field-name-history-get_current_user_playlists)
- [x] Fixed: `SpotifyClient.get_playlist_tracks` reads each entry's
      payload from `entry["item"]`, not `entry["track"]` — Spotify's
      Feb 2026 API migration moved the endpoint to
      `/playlists/{id}/items` and repurposed the old `"track"` key as a
      boolean type-discriminator inside `item` (`item["track"]`,
      alongside `item["type"] == "track"`). An explicit
      `track_data.get("type") != "track"` filter skips non-track
      entries (e.g. podcast episodes).
      [HISTORY](docs/HISTORY.md#spotify-field-name-and-endpoint-history-get_playlist_tracks)
- [x] Fixed: a real, reproducible deadlock in `ui/workers.py`'s
      cross-thread signal handling under heavy, rapid, concurrent
      `run_worker()` use. Root cause: a fresh `WorkerSignals` QObject
      per task meant connect()/disconnect() cycled through Qt's
      mutex-pool on every call, colliding with ordinary widget
      construction. Fixed with one shared, permanently-connected
      dispatcher (connected once at import time, never disconnected) so
      the only hot-path Qt connection-list operation is `.emit()` on a
      single fixed address. Standing pattern: any future QRunnable-based
      worker must not create/connect/disconnect a fresh QObject per
      task. `self.setAutoDelete(False)` plus a `task_id`-only signal
      (never `self`) plus a `QTimer.singleShot(0, ...)`-deferred native
      delete are all independently required — see HISTORY for why each
      shortcut segfaulted. [HISTORY §39](docs/HISTORY.md#39)

## Roadmap (direction, not urgent)

Condensed to standing facts and gotchas that matter for future code. Full
narrative — investigation steps, ruled-out hypotheses, exact real-run
numbers/timestamps — lives in `docs/HISTORY.md`, same item numbers. A
roadmap entry over ~8 lines belongs in HISTORY.md only, with a link —
compress it here before moving on to the next item.

1. **`sync` split from `sync-tracks` — done.** `seeker sync` is
   metadata-only (playlist id/name/track_count/snapshot_id); per-playlist
   track syncing is a separate, explicit `sync-tracks <playlist_name>`
   call — never triggered automatically, to keep Spotify API calls scoped
   and intentional. `get_playlist_by_name()` does case-insensitive lookup
   with close-match suggestions. [HISTORY §1](docs/HISTORY.md#1)
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
   selection, which prefers practical-queue candidates. `select_downloads`
   (item 8) is the current selection entry point.
   [HISTORY §5](docs/HISTORY.md#5)
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
   — needs-review tracks are deliberately left alone. [HISTORY §7](docs/HISTORY.md#7)
8. **Phase 2 upgrade-tracking — done.** `quality.select_downloads(track,
   files)` returns `(settled, upgrade)` — practical top pick means no
   upgrade; an impractical top pick becomes `upgrade` (requested in
   parallel, `role='upgrade'`) while `settled` falls back to the best
   practical candidate. New status `ready_for_review` for a completed
   upgrade (not auto-moved). Two commands, split deliberately:
   `seeker downloads status` → `poll_downloads()` only, safe for cron;
   `seeker downloads review` → `review_pending_upgrades()`, prompts per
   `ready_for_review` row. `DEFAULT_MAX_QUEUE = 200` is untuned.
   [HISTORY §8](docs/HISTORY.md#8)
9. **Multi-artist fix — done.** `Track.artist` joins ALL of Spotify's
   `item["artists"]` with `", "` (previously only `artists[0]`).
   `artist_matches` splits on `", "` and passes on ANY one name match;
   `score_title` also tries each individual artist name combined with
   the title, taking the max across title-only/combined-all/
   combined-per-artist. Search-query construction strips literal commas.
   Album art: `item["album"]["images"]` is already on the
   playlist-items response — no separate album-fetch call needed.
   [HISTORY §9](docs/HISTORY.md#9)
10. **Metadata Phase B — writing tags — done.** `seeker/metadata.py`:
    `write_text_tags`/`embed_album_art` dispatch on the mutagen object's
    actual tag type — `isinstance(tags, ID3)` covers **both MP3 and
    WAV** in one branch (WAV's `_WaveID3` is a genuine `ID3` subclass) —
    vs. `FLAC` vs. `MP4`. An unsupported format makes `write_text_tags`
    raise `ValueError` but makes `embed_album_art` return `False` (art
    failure must never sink an otherwise-good text-tag write).
    `MetadataService.tag_tracks`/`tag_playlist` scope to
    `match_method='auto'` only — never needs_review.
    [HISTORY §10](docs/HISTORY.md#10)
11. **Metadata Phase C — local audio analysis (BPM + key) — done.**
    `librosa` chosen over Essentia for Windows wheel support. Gotchas:
    `librosa.beat.beat_track` returns tempo as a length-1 ndarray, not a
    bare float; `scipy.stats.uniform(loc, scale)` means
    `[loc, loc+scale]`, not `[loc, scale]`. `analyze_audio()` →
    `AudioAnalysis(bpm, camelot_key, key_confidence)` via 24
    Krumhansl-Schmuckler profile correlation; `camelot_key` is `None`
    when the best correlation isn't positive. `local_files`'
    `bpm`/`camelot_key`/`key_confidence` are deliberately excluded from
    `upsert()`'s `ON CONFLICT DO UPDATE` (a routine scan must not wipe
    prior analysis). `TKEY` deliberately holds Camelot notation, not
    standard key notation. `correct_octave_error` corrects a beat
    tracker locking onto half/double tempo only when exactly one of
    2x/0.5x/3x/1.5x candidates lands in `expected_bpm_range` (ambiguity
    → unchanged). [HISTORY §11](docs/HISTORY.md#11)
12. **Centralized playlist-name resolution — done.** All 4 commands
    taking `playlist_name` go through one CLI-layer
    `resolve_playlist_or_offer_sync(name, application)`: found locally →
    return immediately; close match → "Did you mean...?", no refresh
    offered; no match at all → offers a real `sync_playlists()` refresh
    + one retry. **Gotcha:** close-matching uses
    `rapidfuzz.distance.Levenshtein.distance`, length-scaled
    (`distance <= max(1, len(query) // 4)`) — `difflib.SequenceMatcher`
    inflated for short query strings. [HISTORY §12](docs/HISTORY.md#12)
13. **slskd shares the local library + Phase 3: locked-file retry —
    done.** `docker-compose.yml`/`slskd.yml` share the real music drive
    read-only so this app's own downloads are visible to other peers as
    uploads. A locked file lives in search results' separate
    `lockedFiles` array; `request_download` against one **succeeds
    immediately** and the rejection only shows up later via
    `get_download_status` as `"Completed, Rejected"` with a known
    exception-text pattern. **Standing fact:**
    `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection()` (in
    `soulseek/client.py`) is unconditional as of item 26 — it applies to
    a rejection on ANY `download_requests.role`, not just
    `role='upgrade'`, since `confirm_review_candidate()` can request a
    human-confirmed candidate as `role='settled'` with no lock-status
    filtering. Only the Phase 4 shortlist cascade stays
    `role=='upgrade'`-specific. `poll_downloads()` retries every
    `'locked'` row each run via `_retry_locked_request`.
    [HISTORY §13](docs/HISTORY.md#13)
14. **Phase 4: upgrade-candidate shortlisting — done.** Ranked shortlist
    of up to `MAX_UPGRADE_SHORTLIST = 3` candidates per track: rank 1
    requested immediately; 2/3 persisted as `status='shortlisted'`, not
    sent to slskd until needed — sequential cascade, not simultaneous
    requests (Soulseek doesn't swarm; firing multiple would mean
    requesting-then-cancelling real peer uploads for no benefit). On any
    rejection for the active upgrade request, `poll_downloads()`
    activates the next `'shortlisted'` row (`_cascade_upgrade`); once a
    track reaches `'ready_for_review'`, every other in-flight row for it
    is marked `'superseded'`. **Gotcha:** locked-retry and
    cascade-activation are NOT unifiable into one method — a retry
    reactivating an already-confirmed-locked row must stay `'locked'` on
    ANY rejection reason, while a cascade candidate's first attempt still
    needs proper locked-vs-failed classification.
    [HISTORY §14](docs/HISTORY.md#14)
15. **Polish pass — done.** `mypy --strict` clean across all source
    files (scoped override for `seeker.metadata`, since `mutagen` ships
    no type stubs). **Standing pattern:** every per-track/per-request
    batch loop wraps each iteration in its own try/except so one bad
    item can't silently abort the rest of a batch — applies to any
    future batch loop in this codebase. `SpotifyClient._get`'s
    429-retry loop bounded by `MAX_RETRY_ATTEMPTS = 5`.
    [HISTORY §15](docs/HISTORY.md#15)
16. **Live re-verification findings — both actioned.** (1)
    `check`/`match_all()` report GLOBALLY across every synced playlist —
    never scoped to one playlist, unlike `download_playlist(playlist_name)`,
    which IS scoped. A "check says 6 unmatched but download only
    touched 4" mismatch is this, not a bug. (2) A locked-but-real
    candidate was being discarded instead of entering the retry cascade
    — fixed via a shared `_request_upgrade_shortlist()` helper called
    from both the settled-found path and a `settled is None but
    shortlist non-empty` path. [HISTORY §16](docs/HISTORY.md#16)
17. **Soulseek needs-review tier — done.** Mirrors `library/matcher.py`'s
    three-tier design using the SAME `matching.py` thresholds (70 ≤
    score < 90). New `soulseek_review_candidates` table (`track_id` PK,
    one row per track), deliberately NOT folded into `download_requests`
    since a needs_review candidate was never submitted to slskd.
    `download_playlist` populates it only when nothing auto-tier exists
    and clears it the moment something better is found. `seeker check`'s
    "Needs review" section gates on `Application.soulseek_configured`
    (a plain config check, not constructing a real `SoulseekClient`).
    [HISTORY §17](docs/HISTORY.md#17)
18. **DB path migrated to platformdirs — done.** DB lives at
    `platformdirs.user_data_dir("Seeker", appauthor=False)`, not
    CWD-relative. `Application._migrate_legacy_database()` moves a real
    pre-existing DB into the new location exactly once, never touching
    anything if a DB already exists there. (Spotify token cache was
    left CWD-relative at the time — that was a real bug, fixed in item
    43, not a deliberate choice.) [HISTORY §18](docs/HISTORY.md#18)
19. **Local JSON config store for SoulSeek/slskd settings — done.**
    `config_store.py`: `SeekerConfig` dataclass, stored as `config.json`
    alongside the DB. **Standing precedence:**
    `Application._slskd_base_url`/etc. each resolve as
    `self._config_store.<field> or config.SLSKD_*` — config store wins,
    `.env` is the fallback. `migrate_legacy_slskd_env_config()` copies a
    field from `.env` only if the store doesn't already have it (never
    overwrites a later Settings change). **Gotcha:** `config.py`'s
    `SLSKD_*` are module-level constants frozen at import time —
    `monkeypatch.setenv` alone doesn't affect them in tests; must patch
    `seeker.application.config.SLSKD_*` directly.
    [HISTORY §19](docs/HISTORY.md#19)
20. **Real download progress tracking — done.** `get_download_status`
    returns a `TransferStatus` dataclass (`state`/`bytes_transferred`/
    `size`) from slskd's real `size`/`bytesTransferred` fields.
    `update_progress()` is kept separate from `mark_status` (a routine
    progress poll must not disturb unrelated columns). **Standing
    rule:** a rejection leaves `bytes_transferred`/`total_bytes` `NULL`
    (not zeroed) — "no progress recorded" and "confirmed zero progress"
    are different things. [HISTORY §20](docs/HISTORY.md#20)
21. **Fix: peer-offline 404 rejection shape — done.** A THIRD distinct
    rejection shape: `POST /api/v0/transfers/downloads/batches` can
    return a **synchronous** 404 (`"appears to be offline"`) at enqueue
    time. `request_download` now catches `HTTPStatusError`, inspects the
    body against the shared pattern list, and raises
    `SoulseekDownloadError` when it matches.
    `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection` live in
    `client.py` (lowest layer that needs them); `download_service.py`
    imports rather than duplicates. [HISTORY §21](docs/HISTORY.md#21)
22. **Frontend Step 3: UI scaffolding + main dashboard — done.** New
    `DashboardService.get_playlist_track_status()` — the first
    playlist-scoped live-status method (everything else reports
    globally, item 16). One `TrackStatus` per track, first-match-wins:
    `IN_LIBRARY` > `DOWNLOADING` > `AWAITING_REVIEW` > `NEEDS_REVIEW` >
    `NOT_FOUND`. `Database.transaction()` opens a new connection per
    call, safe across threads. **Standing gotcha:** `ui/workers.py`'s
    `Worker` MUST be kept alive via a strong reference
    (`_active_workers: set[Worker]`) until its own finished/error signal
    fires, or `QThreadPool.start()` returning before the thread runs
    means GC can collect it mid-flight. Toolbar Sync/Scan/Match stay
    global; only Download is playlist-scoped; selecting a playlist never
    auto-triggers `sync-tracks`. [HISTORY §22](docs/HISTORY.md#22)
23. **Frontend Step 4: onboarding wizard — done.** Three steps (Spotify
    connect, library location, SoulSeek/Docker — skippable), resumable
    across restarts. `config.py` no longer raises at import time for
    missing Spotify config — resolves through the config-store-or-env
    pattern like item 19. **Standing facts:** `SLSKD_USERNAME`/
    `PASSWORD` are the web UI login, NOT the SoulSeek network
    credentials — those are `SLSKD_SLSK_USERNAME`/`SLSKD_SLSK_PASSWORD`.
    `/api/v0/application`'s `ServerState` has no error/reason field — a
    bad password and a "kicked" case both show `state: "Disconnected"`;
    the real reason only shows via `/api/v0/logs`, time-bounded by a
    `since:` timestamp per bring-up attempt. `onboarding_complete` only
    requires Spotify + a library location; SoulSeek/Docker is optional.
    [HISTORY §23](docs/HISTORY.md#23)
24. **Frontend Step 5: download progress view — done.** New
    `DashboardService.get_active_downloads()` — deliberately GLOBAL
    (mirrors `seeker downloads status`, not playlist-scoped). "Visible"
    = every non-terminal status, plus a `completed`/`failed` row within
    `RECENTLY_FINISHED_WINDOW_SECONDS = 60`. Second timer,
    `BACKEND_POLL_INTERVAL_MS = 20_000` (makes real slskd calls),
    guarded by an overlap flag. Progress bar is indeterminate
    (`setRange(0,0)`) when bytes haven't been reported yet.
    `download_dedup.py`'s `most_recent_per_candidate()` collapses stale
    duplicate rows on read, keyed on `(track_id, role, username,
    filename)` — deliberately not `rank`. [HISTORY §24](docs/HISTORY.md#24)
25. **Fix: Phase 3 retry loop didn't dedupe stale duplicate rows —
    done.** Write-side counterpart to item 24: `_retry_locked_request`
    now calls `_supersede_stale_duplicates(current)` first. Shared logic
    in top-level `download_dedup.py` — both `DashboardService` (read)
    and `DownloadService` (write) import the same function so display
    and mutation can't drift onto two notions of "duplicate." Known
    unresolved edge case: the tiebreak is pure `requested_at`, with no
    status-awareness. [HISTORY §25](docs/HISTORY.md#25)
26. **Frontend Step 6: Review screen — done.** `confirm_review_candidate`/
    `reject_review_candidate` on `DownloadService` — confirm requests as
    `role='settled'` (a human confirmation is a stronger signal than an
    algorithmic top pick; this is what forced item 13's rejection
    classification to become unconditional); reject just deletes the
    row, no blacklist. Phase 2's upgrade-confirmation flow exposed via
    `get_upgrade_review_details`/`apply_upgrade_decision`. New Review
    tab (needs-review + pending-upgrades tables) on the existing 2s
    poll. [HISTORY §26](docs/HISTORY.md#26)
27. **Frontend Step 7: Tagging panel — done, live-verified.** Exposes
    `MetadataService.tag_tracks`/`tag_playlist` via three triggers:
    per-track "Tag" button (only for `IN_LIBRARY` rows), "Tag selected",
    "Tag playlist." The CLI's `--bpm-range` requires `--analyze-audio`
    rule is enforced *structurally* — the range fields are hidden
    entirely while the checkbox is unchecked, not just validated after
    the fact. No confirmation gate before running (matches this
    project's principle that confirmation is for file *replacement*,
    not tag-writing). [HISTORY §27](docs/HISTORY.md#27)
28. **Frontend Step 8: Settings — done.** `SettingsWindow`, four tabs:
    library locations, playlist destinations, Spotify/SoulSeek
    connection management (`connect_spotify`/`persist_soulseek_config`
    on `Application`, shared by wizard and Settings), editable
    auto-match/needs-review thresholds. **Standing facts:**
    `DownloadService` takes `soulseek_client: SoulseekClient | None` —
    methods that don't need it must never force its construction; only
    the `soulseek` property raises, lazily. `matching.py`'s thresholds
    stay hardcoded; `TrackMatcher`/`DownloadService` instead take
    `get_config: Callable[[], SeekerConfig] | None` — a **callable**,
    not a snapshot, so a Settings change takes effect immediately, no
    restart. [HISTORY §28](docs/HISTORY.md#28)
29. **UI polish pass — done.** Mirrors item 15's audit structure across
    everything built in Steps 3-8. Two real bugs found: (1)
    `run_worker()` never caught an exception raised inside a caller's
    own `on_finished`/`on_error` callback — fixed by wrapping both,
    surfacing to `status_label` when provided. (2)
    `Database.initialize()` used `with self.connect() as connection:` —
    sqlite3's context manager only manages commit/rollback, not closing
    — leaked one connection per `Application()`/test. Fixed to match
    `transaction()`'s explicit `finally: connection.close()`.
    [HISTORY §29](docs/HISTORY.md#29)
30. **Standalone-app packaging (PyInstaller) — done, macOS
    live-verified, Windows/Linux written-not-verified.**
    `packaging/seeker.spec` + `packaging/entrypoint.py`. One-folder mode
    over one-file — verified, not assumed: one-folder's second run is
    ~1.0s (numba's JIT cache persists) vs. one-file's ~18-21s every run
    (self-extracting temp dir never persists the cache). Docker is
    deliberately NOT bundled. `docker_setup.py::compose_file_path()`
    branches on `sys.frozen`: unset → unchanged CWD-relative path; set →
    resolves against `sys._MEIPASS`. Same pattern any future
    bundled-resource lookup should follow. [HISTORY §30](docs/HISTORY.md#30)
31. **`.dmg` installer — done, macOS live-verified.**
    `packaging/dmg_settings.py` (via `dmgbuild`, pure Python — kept
    packaging inside `uv`) wraps the `.app` into a drag-to-`/Applications`
    `.dmg`. Verified specifically for the risk item 30 couldn't reach: a
    *relocated* launch (copied out to `/Applications`, not run from the
    build dir) — `compose_file_path()`'s `sys._MEIPASS` resolution
    correctly found the bundled file at its real post-relocation path.
    No custom `.icns` yet at this point (closed in item 42).
    [HISTORY §31](docs/HISTORY.md#31)
32. **Broad end-to-end stress test — done; two real resource leaks
    found and fixed.** (1) A parentless top-level `QMainWindow`'s
    `close()` only *hides* it by default in Qt — leaked ~2MB RSS per
    open/close cycle. Fixed with `Qt.WidgetAttribute.WA_DeleteOnClose`
    on all three top-level windows. (2) A reference cycle in
    `run_worker` (`handler` closes over `worker`, connected to
    `worker.signals`) invisible to Python's cyclic GC since the Qt/
    shiboken side of a signal connection isn't visible to the tracer.
    Fixed with `Qt.ConnectionType.SingleShotConnection` on both
    `connect()` calls (a manual `disconnect()` from inside its own
    handler mid-emission caused a real segfault — undefined behavior in
    Qt's C++ layer). `tests/test_stress_e2e.py` (opt-in,
    `SEEKER_RUN_STRESS_TEST=1`) asserts bounded RSS/fd/thread growth and
    empty `active_workers` at the end. [HISTORY §32](docs/HISTORY.md#32)
33. **Download ETA (per-download speed/ETA estimate) — done.**
    `ui/download_eta.py::DownloadEtaTracker` — in-memory, keyed by
    `download_requests.id`. Samples recorded only on the 20s
    `BACKEND_POLL_INTERVAL_MS` cycle, never the 2s display tick (which
    would re-diff against an unpolled DB row). "Stalled" once
    `STALL_SAMPLE_COUNT = 3` consecutive samples report identical
    bytes. History capped at 3 samples per id, evicted the moment an id
    drops out of `get_active_downloads()`. [HISTORY §33](docs/HISTORY.md#33)
34. **Contextual help in the UI — done.** `ui/help_text.py` centralizes
    every tooltip/subtitle/About-dialog string as named constants — one
    copy to edit for any control shared between windows. `MainWindow`
    gained a real `QMenuBar` → Help → About Seeker, whose version line
    reads `importlib.metadata.version("seeker")` rather than a
    hardcoded literal. [HISTORY §34](docs/HISTORY.md#34)
35. **Support-the-creator links — done.** `SUPPORT_LINKS` in
    `ui/help_text.py`; both `AboutDialog` and a new wizard "you're all
    set" page call `webbrowser.open()` directly, same mechanism as the
    Spotify OAuth flow. The wizard previously had no final screen at
    all — added a fourth stack page (`_build_done_page`) with a real
    "Go to Dashboard" button. [HISTORY §35](docs/HISTORY.md#35)
36. **Packaging polish — macOS done and re-verified, Windows
    written-but-unverified, Linux deprioritized.** PyInstaller's
    `BUNDLE()`/`EXE()` already ad-hoc-sign by default with no
    `codesign_identity` given — `seeker.spec`/README corrected from
    "unsigned" to "ad-hoc signed, not notarized" (Gatekeeper still
    warns; the right-click → Open workaround is the real remaining
    friction). Added `packaging/Read Me First.txt` to the `.dmg`
    explaining that workaround. `packaging/seeker.iss` (Inno Setup)
    mirrors the `.dmg` build's structural pattern for a
    `SeekerSetup.exe` — `AppId` is a fixed, generated-once GUID, never
    regenerate it. [HISTORY §36](docs/HISTORY.md#36)
37. Linux packaging (AppImage or `.deb`) is a real, deliberately
    deprioritized future option — not scoped or attempted as part of
    item 36. Direction, not urgent.
38. **Duplicate/quality detector via fingerprinting — Phase 0 spike
    done; no production code yet.** `pyacoustid`'s bundled
    `chromaprint.py` binding isn't usable as-is: it does a bare
    `ctypes.CDLL("libchromaprint.1.dylib")` lookup that fails on Apple
    Silicon Homebrew without `DYLD_FALLBACK_LIBRARY_PATH`, and raises at
    *import* time rather than call time. A future project-owned binding
    needs an explicit candidate-path search plus a lazy, call-time-only
    failure. The library itself is LGPL-2.1 — load dynamically via
    ctypes, never link statically. Real spike numbers: same-track
    duplicates scored 99.87-99.98% Hamming similarity; an unrelated pair
    scored 57.81% — wide separation validating a Hamming-distance
    clustering threshold. [HISTORY §38](docs/HISTORY.md#38)
39. **Duplicate/quality detector via audio fingerprinting — Phase 1
    done: fingerprint computation + read-only clustering, CLI and UI.
    Delete/replace deferred to Phase 2 (item 40).** `local_files` gains
    nullable `fingerprint`/`fingerprint_duration`/`fingerprint_computed_at`,
    excluded from `upsert()`'s `ON CONFLICT DO UPDATE` like item 11's
    analysis columns. `seeker/audio_fingerprint.py` — a project-owned
    ctypes binding (not `pyacoustid`'s), with an explicit candidate-path
    search and a lazy `FingerprintingUnavailableError` mirroring
    `soulseek_configured`'s checked-before-use pattern.
    `find_duplicate_groups(location_name)` clusters via union-find over
    `DUPLICATE_SIMILARITY_THRESHOLD = 0.95`, computed fresh from cached
    fingerprints every call (never persisted, so a moved/rescanned file
    can't leave a stale group). **Performance, load-bearing:** decode
    each fingerprint exactly once into a cache reused across every
    comparison (`decode_fingerprint`/`similarity_from_decoded`, kept
    public/separate for this reason), and sort by `duration_ms` with a
    bounded sliding window instead of a full O(n²) sweep — real run:
    ~10 min / 344 groups over ~3,100 files. `soundfile`'s MP3 decoder
    fails on ~2% of real files (non-standard framing) — caught by the
    existing per-file try/except, not fixed. UI Duplicates tab loads its
    location combo lazily on first tab-switch (this predates and is
    unrelated to the workers.py deadlock fix, but stayed lazy anyway —
    a better fit regardless). [HISTORY §39](docs/HISTORY.md#39)
40. **Duplicate/quality detector — Phase 2: the delete action — done.**
    Resolves a duplicate group by keeping one copy and deleting the
    rest (DB row + real file). **Standing fact for any future
    `local_files` deletion:** delete the DB row FIRST, then the file on
    disk — `scanner.py`'s `delete_missing()` already self-heals an
    interrupted-before-file-delete orphan on the next scan; the reverse
    order leaves a row pointing at a nonexistent file that a
    matcher/tagger could act on and fail against. `delete_local_files`
    takes an optional `keep_local_file_id` — any `track_matches` row
    pointing at a file being deleted is re-pointed to the surviving file
    (via the existing `TrackMatchRepository.upsert()`) rather than left
    to the FK cascade's `ON DELETE SET NULL`, which alone left a track's
    `match_method` stale (`'auto'` with `local_file_id=NULL`) and stuck
    it in limbo. Shared `seeker/file_deletion.py::delete_file()`.
    Resolving a group refreshes the UI's in-memory list locally rather
    than re-calling `find_duplicate_groups()` (a full ~10-minute
    location-wide recompute) — critical at real scale (344 groups).
    [HISTORY §40](docs/HISTORY.md#40)
41. **Bounded verification pass — one real bug found and fixed in
    `ui/workers.py`.** A straggling background worker (e.g. a 20s
    backend-poll retry still in flight) could call `.emit()` on the
    shared dispatcher after it was torn down mid-shutdown, raising
    `RuntimeError: Signal source has been deleted`. Fixed with
    `ui/workers.py::_emit_or_drop()`, wrapping both dispatcher-emit call
    sites — dropping a late result is strictly safer than letting a
    background thread raise into shutdown. (A first attempt,
    check-then-`isValid()`-then-emit, was itself check-then-act, not
    atomic — a forced repro escaped it 50/50 trials; wrapping the
    `.emit()` call itself is the only safe boundary, confirmed 0/50
    after.) Stress test extended to cover the Duplicates tab.
    [HISTORY §41](docs/HISTORY.md#41)
42. **Custom app icon wired in and live-verified — macOS done, Windows
    written-but-unverified.** `packaging/icons/seeker_icon.icns`/`.ico`
    wired into `seeker.spec`'s `BUNDLE()`/`EXE()`, `dmg_settings.py`'s
    `icon`, and `seeker.iss`'s `SetupIconFile`. Live-verified via
    `NSWorkspace.iconForFile:`/`NSRunningApplication.icon` (no Screen
    Recording permission available) across Finder, the `.dmg` volume,
    and the Dock. [HISTORY §42](docs/HISTORY.md#42)
43. **Fix: Spotify token cache was still CWD-relative — done.** Item 18
    migrated the DB to platformdirs but left the token cache
    CWD-relative — a double-clicked `.app` gets CWD `/` (the read-only
    Signed System Volume) on macOS, so saving a token after OAuth failed
    with a read-only-filesystem error. Fixed exactly mirroring item 18's
    migration shape (`_resolve_spotify_token_path()`,
    `_migrate_legacy_spotify_token()`), deliberately **not**
    `sys.frozen`-gated. [HISTORY §43](docs/HISTORY.md#43)
44. **Fix: Docker detection was PATH-dependent and broke under a real
    double-clicked `.app` — done.** A GUI launch gets launchd's bare
    default PATH (`/usr/bin:/bin:/usr/sbin:/sbin`), excluding both
    `/usr/local/bin` (Docker Desktop's CLI symlink) and
    `/opt/homebrew/bin` — same "works via `uv run`, breaks via a real
    double-click" shape as item 43, for PATH instead of CWD. Fixed once
    via `docker_setup.py::ensure_full_path_environment()`, called at the
    top of `Application.__init__`, merging `path_helper`'s output plus
    explicit fallbacks into `os.environ["PATH"]` — every
    `docker_setup.py` subprocess call already inherits `os.environ`, so
    this fixes every call site with no per-call-site change.
    [HISTORY §44](docs/HISTORY.md#44)
45. **Fix: a completed settled download never entered the library —
    done, live-verified.** `poll_downloads()`'s settled-completion
    branch called `_move_completed_file()` and stopped — never indexed
    the file or wrote a `track_matches` row (unlike the upgrade path).
    Fixed with `DownloadService._index_and_match_settled_download()`,
    mirroring `apply_upgrade_decision`'s index+match tail, called from
    both places `poll_downloads()` reaches a settled completion.
    `match_method='auto'` is set unconditionally (provenance outweighs
    fuzzy-match confidence — same reasoning as item 26), but the real
    computed score is stored (not a `100.0` sentinel), so a bad pairing
    stays visible. **Independent second bug, found live:**
    `_move_completed_file` used `Path(...).rglob(basename)` — `rglob`
    treats its argument as a glob PATTERN; real Soulseek filenames
    routinely contain `[...]` release tags, which `fnmatch` interprets
    as a character class, silently matching nothing. Fixed with
    `glob.escape(basename)`. **Standing fact:** `match_all()` recomputes
    every `track_matches` row from scratch on every run with no
    "provenance-confirmed" concept — a later re-match can demote a
    provenance-matched or human-confirmed row back to `needs_review`;
    this is pre-existing behavior, not something either fix changed.
    [HISTORY §45](docs/HISTORY.md#45)
46. **Tagged tracks stop asking to be tagged — done.** `TrackStatus`
    gains `tagged_at: str | None`. Dashboard Actions column:
    untagged+`IN_LIBRARY` → "Tag" button; tagged+`IN_LIBRARY` → muted
    "Tagged" label with a tooltip; right-click offers "Re-tag." New
    `ui/formatting.py` (`format_timestamp`/`format_file_size`/
    `format_speed`/`format_duration_seconds`) — every stored timestamp
    in this codebase is written timezone-AWARE UTC
    (`datetime.now(timezone.utc).isoformat()`), so `format_timestamp`
    uses `.astimezone()`, not a manual naive-UTC offset attach.
    [HISTORY §46](docs/HISTORY.md#46)
47. **Design system (dark theme + InlineNotice) — done, live-rendered
    and checked.** New `ui/theme.py` (`apply_theme(app)` — Fusion style
    + QPalette + one global QSS stylesheet) and `ui/notice.py`
    (`InlineNotice`, a persistent dismissible banner). **Root cause of
    "an error disappears before you've had time to read it":**
    `run_worker()` clears its target `status_label` to `""`
    unconditionally at the start of every call — the Dashboard's 2s poll
    tick and every backend-poll completion both use the same shared
    label, wiping any validation error within ~2s regardless of what the
    user was just shown. Fixed by routing Dashboard's actionable
    messages through `InlineNotice` instead, which lives outside
    `run_worker`'s `status_label` plumbing entirely; `status_label`
    stays for genuinely disposable progress text. **Not yet swept
    everywhere** — the Review tab's `status_label` has the identical bug
    class, left alone in this pass. **Three live-found Qt/QSS bugs, each
    bisected via a minimal repro:** (1) `QTableWidget::item { padding }`
    corrupts any `QPushButton` living inside a cell widget
    (`setCellWidget`) into garbled text — dropped from `QTableWidget`
    (kept safe on `QListWidget`). (2) A plain `QWidget` subclass (like
    `InlineNotice`) doesn't paint its own stylesheet background/border
    without `Qt.WidgetAttribute.WA_StyledBackground`. (3)
    **`QProgressBar::chunk` matching a bar AT ALL — regardless of what
    it sets — switches that sub-control from Qt's native painter
    (including Fusion's animated indeterminate stripe) to the QSS
    box-model painter for every state of the bar, including
    indeterminate, which has no busy-animation concept and just paints a
    static rect.** There is no `:indeterminate` QSS pseudo-state to
    scope around this. Fixed by removing `QProgressBar::chunk` from the
    global stylesheet entirely and adding
    `theme.style_determinate_progress_bar(bar)` — a per-instance
    `setStyleSheet()` applied ONLY once a bar is confirmed determinate,
    never to an indeterminate one; a queued/no-bytes-yet row keeps Qt's
    real native animation. Covered by
    `test_downloads_tab_progress_bar_indeterminate_with_no_bytes_yet`
    (asserts `bar.styleSheet() == ""`) and the determinate counterpart
    (asserts `"chunk" in bar.styleSheet()`) — a regression reintroducing
    the bug now fails a fast test, not just a human re-render.
    [HISTORY §47](docs/HISTORY.md#47)
48. **Shell restructure: sidebar instead of tabs — done, all six pages
    rendered and inspected.** `MainWindow`'s `QTabWidget` replaced with
    a fixed-width sidebar (`_build_page(title, subtitle, content)`
    shared helper, `24/20` page margins everywhere) driving a
    `QStackedWidget`. `_show_page(key)`/`_page_indices` replace bare
    tab-index bookkeeping; `QStackedWidget.currentChanged` gives the
    same lazy-load-on-first-visit signal shape `QTabWidget` did.
    Settings deliberately stays a separate dialog, not a shell page (it
    was never a tab body). History/Help get real nav slots with
    placeholder content now, so a later phase only replaces content, not
    navigation wiring. Nav badges read counts already computed by the
    existing 2s poll — no new poll. A checkable flat `QPushButton` needs
    no `WA_StyledBackground`; the sidebar panel `QWidget` does.
    [HISTORY §48](docs/HISTORY.md#48)
49. **Library locations: pick the folder first, name it later — done.**
    `LibraryService.add_location_from_path(path)` derives the name from
    the folder's basename, auto-suffixing on collision
    (`MAX_NAME_SUFFIX_ATTEMPTS=50`), and raises
    `LibraryLocationPathAlreadyRegisteredError` (checked via a new
    `get_by_path()` before insert) rather than a raw `IntegrityError`.
    `library_location_picker.py` (shared by wizard + Settings) dropped
    its `name` parameter entirely. New `rename_location(id, name)`.
    [HISTORY §49](docs/HISTORY.md#49)
50. **Kill the "no configured destination" dead end — done,
    live-rendered.** `SeekerConfig` gains a default download location +
    subfolder-per-playlist toggle. `DownloadService._resolve_destination(
    playlist)` — playlist-specific setting always wins, else falls back
    to the configured default, resolved fresh via `_get_config()` on
    every call (Settings change takes effect with no restart). **Real
    gotcha caught wiring the fallback into the actual move step:**
    `PlaylistRepository.get_by_track_id()` filtered
    `WHERE p.download_location_id IS NOT NULL` — left as-is, a track
    relying only on the new default would never be returned by this
    query, so its file would silently never move (the same "stuck, no
    visible error" shape item 45 hunted). Filter removed; the caller now
    resolves the first playlist that actually works. New
    `seeker/filename_sanitize.py::sanitize_path_component()` — no prior
    sanitizer existed in this codebase. `DestinationDialog` (new UI)
    means Download can never dead-end for a first-time user; confirming
    always persists somewhere real (either the playlist-specific
    destination or the new app-wide default). [HISTORY §50](docs/HISTORY.md#50)
51. **Visual guidance: Dashboard "next step" CTA — done, all four
    states live-rendered.** `_decide_next_step()` — a pure function (no
    Qt), tested directly with synthetic facts, deciding one CTA from
    facts gathered via one background-thread `_fetch_next_step_facts()`.
    New `LibraryService.has_scanned_library()` is a disclosed
    approximation (true once any `local_files` row exists anywhere — no
    schema change was in scope, so a location scanned to genuinely zero
    matching files reads identically to "never scanned"). Empty states
    are a real structural change: `track_table` and a centred empty
    panel now live in a `QStackedWidget`, swapped explicitly instead of
    "leave the table showing whatever it last held." Global
    Sync/Scan/Match buttons renamed and moved off the old toolbar onto
    the Dashboard page itself as a secondary action row.
    **Follow-up fix:** the CTA's own "Download N missing tracks" and the
    action row's "Download selected playlist" were the literal same
    action (confirmed via `get_unmatched_for_playlist`'s query) — now
    `download_button` hides specifically while the CTA's own action is
    `"download"`. All four action-row buttons are now `.setEnabled()`d
    from the same facts bundle already computed for the CTA, not always
    enabled regardless of whether they'd do anything.
    [HISTORY §51](docs/HISTORY.md#51)
52. **Wizard: say why the SoulSeek login failed — done, live-verified
    against real slskd.** The protocol can't distinguish "wrong password
    on my own account" from "that username belongs to someone else" — a
    radio pair ("I already have an account" / "Create a new account")
    lets `BAD_CREDENTIALS` branch its copy accordingly; the real log
    detail is preserved as a tooltip in every branch, never dropped. New
    `SlskdHealthStatus.KICKED` (a third, previously-unclassified
    terminal state — two clients logging in with the same username,
    distinct log text from bad-credentials). **Standing fact, confirmed
    live via disposable throwaway containers, never the production
    one:** a brand-new, never-before-used username does NOT produce a
    rejection — it silently auto-creates an account and logs in, so a
    genuine bad-credentials test needs a real, already-registered
    username with a wrong password, not just any made-up string.
    [HISTORY §52](docs/HISTORY.md#52)
53. **Downloads: aggregate remaining-time header — done.**
    `DownloadEtaTracker.aggregate()` sums remaining bytes and speed only
    across downloads currently making measurable progress (>= 2
    samples, positive latest delta, known `total_bytes`); a queued or
    stalled download is counted but excluded from the sum, per the
    standing "don't fold in unpredictable queue waits to produce a
    rounder number" design principle also behind
    `AGGREGATE_ETA_TOOLTIP`. `format_aggregate_header()` renders "About
    {eta} remaining · {N} transferring · {M} queued (no estimate)",
    distinguishing "Waiting for transfers to start" from the more
    alarming "All active transfers stalled." **Recon finding:** slskd's
    real transfer schema declares a `placeInQueue` field, but a live
    queued transfer's response omits it entirely (not even `null`) —
    slskd doesn't currently report queue position for this transfer, a
    concrete reason (not just restated caution) behind not reading this
    field yet. [HISTORY §53](docs/HISTORY.md#53)
54. **History page — done.** `HistoryService.get_recent_events(limit)`
    derives two event kinds from existing tables only, no schema change:
    completed `download_requests` rows (deduped via the same
    `most_recent_per_candidate` rule as items 24/25) and
    `local_files.tagged_at`. Deliberately excludes failed downloads — no
    failure-reason column is persisted, so that event could never show
    an honest detail (see the Downloads page instead). `ui/formatting
    .format_timestamp` is reused as-is by both the History page and
    `seeker history [--limit N]` — confirmed live against real DB rows
    that `completed_at`/`tagged_at` are genuinely timezone-aware UTC
    (matching its docstring), so no fix was needed there. UI: When/What/
    Track/Detail table + a client-side filter combo (no re-query),
    lazy-loaded on first visit like Duplicates, manual Refresh (no poll
    timer — a look-back view, not a live one). **Standing limit, stated
    in both the page subtitle and CLI help:** this is a derived view,
    not an append-only log — an event disappears the moment the row it
    came from does (e.g. a Duplicates-tab delete removes a downloaded
    file's event too).

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
number as the HISTORY.md heading). A roadmap entry over ~8 lines belongs
in HISTORY.md only, with a link — compress it here before moving on to
the next item; this file already had to be compressed back down once
(items 39-53 quietly re-accumulated full investigation narrative before
that pass), so treat the 8-line budget as a hard ceiling, not a
suggestion. Keep this file updated as decisions get made — treat it as
the standing brief, not a changelog of everything that happened, and
don't let it quietly re-accumulate the narrative detail this split just
moved out.

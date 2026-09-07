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
│   ├── theme.py                # dark theme tokens + apply_theme() (item 47);
│                              #   make_card()/cell_widget() (item 80) — the
│                              #   only place a rounded table card or a
│                              #   setCellWidget container is built
│   ├── notice.py               # InlineNotice — persistent banner (item 47)
│   ├── flow_layout.py           # FlowLayout — reflowing control row,
│                              #   minimumSize() = widest item not the
│                              #   sum (item 72)
│   ├── help_text.py            # centralized tooltips/subtitles/About copy
│                              #   (item 34), incl. SUPPORT_LINKS (item 35)
│   └── workers.py              # QThreadPool Worker + run_worker() — every
│                              #   long-running UI action goes through this
├── models/{playlist,track,track_match,local_file,library_location,
│           soulseek_file,download_request,soulseek_review_candidate,
│           active_download,track_status,upgrade_review,history_event,
│           data_locations}.py
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
├── filename_sanitize.py       # sanitize_path_component() — used by
│                              #   default-destination resolution (item 50)
├── update_check.py            # check_for_update() — one unauthenticated
│                              #   GitHub-releases GET, user-triggered only
│                              #   (Help menu), never raises (item 55)
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
- **Lint yes, format no — `ruff format` is deliberately not adopted.**
  Roadmap item 115 (round 8, §4.2). This codebase has a consistent
  hand-written house style that `ruff format` does not produce.
  Reformatting the whole tree would produce an unreviewable diff,
  destroy `git blame` project-wide, and fight every future hand-wrapped
  comment. `ruff check` (see `[tool.ruff]` in `pyproject.toml`) is the
  enforced gate; `ruff format` is not run and should not be added
  without a deliberate, separate decision to re-litigate this.
- **Multi-line hanging indent, verified by sampling the real codebase
  (round 8, §4.8.1) rather than assumed from one example: 8 spaces for
  a compound statement header that wraps (`def`/`if`/`elif`/`while`/
  `for`/`with`/`class` — anything ending in `:` with an indented body
  next), 4 spaces for everything else (plain calls, `return`/`raise`/
  `assert`, assignments, comprehensions, literals, imports).** Sampled
  336 real multi-line calls: 336/336 use 4 spaces. Sampled 74 real
  compound headers: 71/74 use 8 spaces (3 pre-existing exceptions, not
  followed). The reason is legible once seen: a compound header's own
  body is already indented +4 from the header, so the header's
  continuation uses +8 to stay visually distinct from that body; a
  plain statement has no following body to stay distinct from, so
  ordinary +4 is unambiguous. A round-8 line-wrap pass (§4.3) got this
  wrong — applied 8-space hang uniformly, including to plain calls —
  before this was verified; corrected in §4.8.1's own edits, the
  pre-existing 4.3 diff was not swept for it (see item 115's own
  HISTORY entry for the open question of whether it should be).
  Trailing commas before a closing bracket stay the convention, and
  house comment/prose wrapping stays a ~72-column habit — see the next
  bullet for how that differs from the enforced line-length ceiling.
- **Line length: `ruff`'s enforced ceiling is 88 (`[tool.ruff]
  line-length` in `pyproject.toml`), but ~72-79 columns remains the
  house *habit* for hand-wrapped prose and comments.** Roadmap item 115
  (round 8, §4.3/§4.8.1) — 79 was tried first and reverted: the real
  violation count checking both `src/` and `tests/` (341, not the
  106 originally estimated from `src/` alone) meant sitting at 79 would
  have needed 166 purely-cosmetic hand rewraps for zero behavioural
  gain, right before Phase 6 starts moving those same files around. 88
  is a ceiling the codebase can actually sit at (near-zero real
  violations); 72-79 is still what a human should aim for by hand.
- **`assert` in `src/` narrows types/logic invariants; it never
  validates user input or an external response.** Roadmap item 115
  (round 8, §4.8.5) — ruff's `S101` is ignored project-wide on exactly
  this basis, checked against every one of the real 60 findings at the
  time (not sampled): 59 narrow an Optional/union already guaranteed
  non-None by preceding control flow (a dataclass `id: int | None`
  known-persisted by the calling code's own logic, a stdlib/library API
  contract mypy can't see statically, or a state check performed a few
  lines above), so `python -O` stripping them is always safe. A new
  `assert` that would validate something a user or an external system
  actually controls is not covered by this convention and needs a real
  `if`/`raise` instead.
- **Checking whether a test failure is "pre-existing": always `git
  stash -u`, never a bare `git stash`.** Roadmap item RR1 — a bare
  `git stash` does not stash untracked files, so it cannot see a
  defect that lives in one (e.g. a real local packaging build's
  gitignored `_build_info_generated.py` — see item 81/RR1's own
  history). A verification that can't see the file it needs to isn't
  a verification; it's structurally guaranteed to call the failure
  "pre-existing" no matter what's actually causing it.
- **The pre-existing-failure count is a tracked number, not a label.**
  Roadmap item RR3.2 — report the actual `pytest` summary line (e.g.
  "3 failed, 1022 passed") and name every failing test inline, every
  time — never "green with N pre-existing failures" as a paraphrase.
  If N changes between rounds, that is a regression to diagnose before
  moving on, never a new baseline to quietly adopt (round 3 let it
  drift from 1 documented flake to 3-4 unnamed ones without anyone
  asking why).
- **A comment asserting platform or framework behavior must cite a
  real observation or be explicitly marked unverified.** Round 6's
  D5: a comment claiming "macOS routes a left-click on a
  QSystemTrayIcon straight to its context menu already (Trigger never
  fires there...)" was written with total confidence and never
  checked — a real user's report on a real Mac proved it false. Same
  shape as round 5's C1 (`QHeaderView::section:horizontal:last-child`,
  invalid Qt QSS that silently poisoned the whole rule). An unmarked
  confident claim about a framework this project has already been
  wrong about twice is a liability, not documentation — write "found
  live"/"confirmed live" when it's real, or say "UNVERIFIED" plainly
  when it isn't yet.
- **Any `continue`/`skip` inside a sweep test must be justified in a
  comment that names what it excludes and why that exclusion cannot
  hide the bug the test exists for. If it can, the skip is the bug.**
  Round 7's E2/E3: a table-sizing sweep test skipped any table with
  "no stretch column" — computed from the SAME state the bug corrupts
  (a table that's never had a resize mode assigned reads as "no
  stretch column"), so the test `continue`d past the exact empty
  Search/Duplicates table the user photographed as broken, and passed.
  A skip condition derived from the state a bug corrupts is not a
  guard; it's a blindfold.

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
7. `check` reports auto/needs-review/unmatched already. **The local-file
   `review` command called out as outstanding here is now built — see
   item 56 Phase 2** (`seeker review` / `LibraryService.get_needs_
   review_matches`/`confirm_match`/`reject_match`, plus a Review-page UI
   section). `download_playlist` only ever targeted `match_method IS
   NULL` tracks — needs-review tracks are deliberately left alone.
   [HISTORY §7](docs/HISTORY.md#7)
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
    globally, item 16). One `TrackStatus` per track, first-match-wins —
    **updated, item 66:** `IN_LIBRARY` > `DOWNLOADING` > `AWAITING_REVIEW`
    > `RETRYING` > `NEEDS_REVIEW` > `REVIEW_CANDIDATE` > `NOT_FOUND` (5
    states grew to 7 — see item 66 for why). `Database.transaction()`
    opens a new connection per
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
47. **Design system (dark theme + InlineNotice) — done.** New
    `ui/theme.py` (`apply_theme(app)`) and `ui/notice.py`
    (`InlineNotice`, a persistent dismissible banner). **Root cause of
    "an error disappears before you've had time to read it":**
    `run_worker()` clears its target `status_label` unconditionally on
    every call — Dashboard's 2s poll tick and every backend-poll
    completion share that one label, wiping a validation error within
    ~2s regardless of what the user was just shown. Fixed by routing
    Dashboard's actionable messages through `InlineNotice` instead
    (lives outside `status_label`'s plumbing); the Review tab's
    identical bug class is NOT yet swept. **Three Qt/QSS gotchas,
    standing facts for any future styling work:** (1)
    `QTableWidget::item { padding }` corrupts a `QPushButton` living
    inside a cell widget — never add it (safe on `QListWidget`). (2) a
    plain `QWidget` subclass needs `WA_StyledBackground` to paint its
    own stylesheet background/border at all. (3) matching ANY rule
    against `QProgressBar::chunk` switches the WHOLE bar to Qt's QSS
    box-model painter, including its indeterminate state (killing
    Fusion's native animated busy stripe, with no `:indeterminate`
    pseudo-state to scope around it) — so the accent fill is applied
    per-instance only, via `theme.style_determinate_progress_bar(bar)`,
    never through a global `::chunk` rule.
    [HISTORY §47](docs/HISTORY.md#47)
48. **Shell restructure: sidebar instead of tabs — done, all six pages
    rendered and inspected.** `MainWindow`'s `QTabWidget` replaced with
    a fixed-width sidebar (`_build_page(title, subtitle, content)`
    shared helper, `24/20` page margins everywhere) driving a
    `QStackedWidget`. `_show_page(key)`/`_page_indices` replace bare
    tab-index bookkeeping; `QStackedWidget.currentChanged` gives the
    same lazy-load-on-first-visit signal shape `QTabWidget` did.
    Settings deliberately stays a separate dialog, not a shell page (it
    was never a tab body). **Reversed in item 56 Phase 3 — Settings is
    now a real shell page** (in fullscreen, a separate window read as a
    dead end with no way back). History/Help get real nav slots with
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
    `seeker history [--limit N]`. UI: When/What/Track/Detail table + a
    client-side filter combo, lazy-loaded like Duplicates, manual
    Refresh (no poll timer). **Standing limit:** a derived view, not an
    append-only log — an event disappears the moment the row it came
    from does. [HISTORY §54](docs/HISTORY.md#54)
55. **Update check + Help page + expanded About + LICENSE — done.**
    `update_check.py::check_for_update()` — one unauthenticated GET
    against `api.github.com/repos/.../releases/latest`, comparing
    `packaging.version.Version` against the installed version. **Never
    raises** — every anticipated failure gets a specific
    `UNAVAILABLE(reason)`, plus an outer catch-all for anything
    unanticipated (fires from a manual Help-menu click, must never take
    the app down). **Standing fact:** this repo currently has zero
    published releases (`GET .../releases/latest` → real `404`) and
    GitHub's unauthenticated rate limit is real and shared per source IP
    (60/hour) — stays strictly user-triggered, never a timer.

    **Help page** — real content (walkthrough/troubleshooting/data
    locations), not a placeholder. New `Application.data_locations` is
    the one place every real resolved path (DB/config/token/slskd dir)
    is assembled, reused by the page and its cross-platform "Open Data
    Folder" button (`_open_in_file_manager()`).

    **Expanded About dialog** — author/contact/GitHub link, MIT license
    line, third-party notices (license identifiers pulled from each
    installed package's own metadata, not assumed).
    `help_text.is_real_support_link()` filters `SUPPORT_LINKS` — any
    future placeholder entry should stay an obvious `"TODO: ..."` string
    so a dead button never renders before the real link lands.

    **`LICENSE`** (MIT, Copyright (c) 2026 Kristiyan Dimitrov) +
    `pyproject.toml`'s `license`/`license-files` fields.
    [HISTORY §55](docs/HISTORY.md#55)
56. **Matching correctness (Phase 1) — done, two hypotheses refuted by live
    data.** `matching.py` gained `aggressive: bool` + `evaluate_match()` —
    an unconfirmed-but-not-contradicted artist source still scores, capped
    at `ARTIST_UNCONFIRMED_SCORE_CAP`. `library/matcher.py` tries
    tag→filename→parent→grandparent dir. `scan_and_match()` chains
    scan+match in one call. Real before/after: Auto 26→27, Needs review
    2→1, all three files reaching 100.0. [HISTORY §56](docs/HISTORY.md#56)
57. **Local needs-review review flow (Phase 2) — done, closes items 7 and 45's
    demotion bug.** New `track_matches.confirmed_at`; `match_all()` skips
    any row with it set — a human-confirmed match can no longer be
    silently demoted.
    `get_needs_review_matches`/`confirm_match`/`reject_match`; `seeker
    review` CLI; Review page gains a third table section; Dashboard
    double-click jumps to it. [HISTORY §56](docs/HISTORY.md#56)
58. **Settings becomes an in-window page (Phase 3) — done, reverses item 48's
    "stays a separate dialog" decision.** `SettingsWindow` →
    `SettingsPage(QWidget)`, hosted in the sidebar's `QStackedWidget`;
    `_show_page()` fires settings-exit invalidation regardless of nav
    path. Stress-test RSS ceiling raised 250→300MB with real numbers —
    investigated (a genuine plateau, not a leak), not just relaxed; a new
    tail-plateau assertion checks that signature directly. [HISTORY §56](docs/HISTORY.md#56)
59. **Tagging: cover art, honest reporting, caching (Phase 4) — done.** FLAC
    `Picture` gained real `desc`/`width`/`height`. `_tag_one_track` now
    tracks an explicit art outcome instead of a silent `print()`; new
    `tagged_without_art` count + per-track detail. New
    `album_art_cache.py::AlbumArtCache` (platformdirs CACHE dir,
    SHA-256-keyed) — zero extra Spotify Web API quota, CDN-only. [HISTORY §56](docs/HISTORY.md#56)
60. **Download UX and the duplicate-download bug (Phase 5) — done.** New
    `get_requests_blocking_redownload()` also blocks a `completed` row —
    the real gap (item 25's guard didn't cover it).
    `_track_already_has_a_matched_file()` is a safety net at both auto-
    completion sites. `DownloadEtaTracker.evict(id)` fixes the
    "Calculating → Stalled → vanishes" bug for terminal rows. Download
    button gets manually-managed busy/reset state. [HISTORY §56](docs/HISTORY.md#56)
61. **Duplicates tab (Phase 6) — done, three real fixes and one "could not
    reproduce."** Location combo now refreshes on every page show, not
    once-ever. The reported "Actions column empty" bug was NOT
    reproducible — kept as a permanent regression test, not a fabricated
    fix. **Gotcha:** `QButtonGroup.addButton(id=-1)` doesn't set the id to
    `-1` — Qt reserves it as its own auto-assign sentinel; use `0`
    instead. New `duplicate_cleanups` table + a reclaimed-space milestone,
    hidden at zero. [HISTORY §56](docs/HISTORY.md#56)
62. **Sharing & Uploads (Phase 7) — done, live-verified end to end against
    disposable throwaway containers, never production.** New
    `sharing_service.py` (`Application.sharing_service`), `seeker sharing
    status` CLI, lazy-loaded Sharing page. `PATCH /api/v0/options` has no
    `shares` key — a share dir only changes by editing files and
    recreating the container. **Standing rule:** resolve real
    host↔container paths via `docker inspect`, never `docker-
    compose.yml`'s own fallback text. One item still outstanding across
    all seven phases: a real attended stress-test re-run — see HISTORY for
    the diagnosis + a faster repro command. [HISTORY §56](docs/HISTORY.md#56)
63. **Open, real bug found live during Phase 7's attended stress-test
    re-run (2026-08-28): `poll_downloads()`'s locked-file retry (items
    13/14/25) once fired in a genuine, bursty, faster-than-20s pattern
    against real production slskd — root cause still unknown, not
    fixed, confirmed intermittent (not reliably on-demand), and NOT
    reproduced by any of three follow-up attended runs on 2026-09-02.**
    Those three runs bracketed the incident from every angle tested:
    (1) all three real pre-existing `locked` rows present (29 calls,
    ~9.7min, steady 20.00s), (2) a from-scratch repro with ZERO locked
    rows (14 calls, steady 20.00s), (3) real DB scale (50 synthetic
    rows, 40% locked) PLUS the full concurrent-traffic combination (3
    simultaneous `download_playlist()` calls + real fingerprinting) at
    once (14 calls, steady 20.00s despite 50 real HTTP calls per cycle).
    Mere locked-row presence, zero locked rows, and heavy combined load
    are all ruled out individually and together — the real trigger
    remains unidentified. One concrete lead for next time: run (3) hit
    a real `500 Internal Server Error` on `/api/v0/transfers/downloads/
    batches` — the exact endpoint/error text of every original storm
    line — but as a one-off synchronous enqueue failure, not a cascade.
    **Process lessons:** the test orchestration tool's own timeout (not
    a user SIGINT) can end a run early — raise it for a long attended
    window; a from-scratch `MainWindow` in a fresh throwaway env
    triggers a REAL Spotify OAuth browser popup (`sync_service`'s
    eager, unguarded `self.spotify` property access) unless a fake
    cached token is seeded first. **Updated, item 66:** the diagnostic
    print is no longer unconditional — converted to `_debug_poll()`,
    gated behind `SEEKER_DEBUG_POLL=1` (kept, not deleted, since the
    real root cause is still unknown and this stays available for a
    future recurrence) — and Phase 4.3's exponential backoff/terminal
    `unavailable` state now structurally BOUNDS any future storm's
    retry rate regardless of cause (a real production storm was 300+
    retries of one row in ~18 minutes; that specific shape can no
    longer happen, even though why it happened at all remains open).
    [HISTORY §63](docs/HISTORY.md#63)
64. **Support page — done.** Real sidebar page below Help (static copy,
    built eagerly — nothing to lazy-load), donation links + non-financial
    ways to help. `_build_support_links_row()` extracted so `AboutDialog`
    and this page share one `SUPPORT_LINKS` render instead of two.
65. **Action feedback: busy buttons + a global activity strip, then a
    real destination prompt — done (Phases 2-3).** `ui/busy_actions.py`'s
    `BusyActionRegistry` (kept OUT of `ui/workers.py` — no cross-thread
    signal machinery needed) + `_run_busy_worker()` fixes buttons
    re-enabling mid-action, including a user-flagged mid-download
    `download_button.setVisible()` hide. Global activity strip + a 3rd
    `_dispatcher` signal, `task_progress`, throttled at the source.
    `_on_download_clicked` now checks `playlist.download_location_id is
    not None` rather than "anything resolvable skips the prompt" (a
    coincidental case-insensitive-filesystem folder match was passing
    as a real destination). [HISTORY §65](docs/HISTORY.md#65)
66. **Honest track statuses + a bounded retry loop, then cover art that
    actually lands — done (Phases 4-5).** `TrackStatus` 5→7 states
    (`RETRYING`/`REVIEW_CANDIDATE` — see item 22 for precedence).
    `download_requests` gained `retry_count`/`next_retry_at`, exponential
    backoff, terminal `unavailable` after 8 attempts. **Real bug found
    live against production slskd:** a real `500` on
    `/transfers/downloads/batches` (item 63's own flagged lead) escaped
    the original exception handling entirely, never advancing
    `retry_count` — the exact unbounded-retry shape this phase exists to
    fix; fixed and re-verified live. `fix_missing_art_for_playlist()`
    (art-only, byte-exact CDN check) shipped as "Fix missing cover art" +
    CLI `fix-art` — live-verified against "Test" (3/9 mismatched → 9/9
    byte-exact after). [HISTORY §66](docs/HISTORY.md#66)
67. **Rename local files to match Spotify metadata — done.**
    `seeker/filename_format.py::build_track_filename` (pure function,
    255-UTF8-byte cap on the title only) + `plan_renames`/`apply_renames`
    + preview dialog + CLI `library rename <playlist> [--apply]`.
    File-then-DB-row ordering (opposite of item 40's delete rule).
    **Real design gap found by an own test:** collisions were resolved
    at PLAN time but refused at APPLY time; apply now resolves them for
    real (numbered suffix). Live-verified as an unapplied dry-run
    against "Test" (7 real renames proposed, 0 collisions).
    [HISTORY §67](docs/HISTORY.md#67)
68. **Duplicates: folder scoping, real progress, and the Actions-column
    bug class — done.** `_DuplicatesColumn(IntEnum)` + a header-text-
    resolved test replace every literal column index — **not
    reproducible across three independent investigations**, kept as a
    permanent regression test. `DuplicateService` gained
    `resolve_folder_scopes`/`find_duplicate_groups(folders=...)`/
    `find_duplicate_groups_across_scopes` (pools folders across
    DIFFERENT locations — clustering is content-only); CLI's
    `fingerprint`/`duplicates` gained repeatable `--folder`. **Real bug
    found wiring this into the UI:** the LOCATION column and the delete
    dialog's paths both read one "current selected location" — a latent
    bug for ANY multi-location result. Fixed to resolve per file via
    `local_file.location_id`. Real run: whole-`x9-pro` clustering (3168
    files) took 10m11s, 352 real groups, vs. a folder-scoped run under a
    second. [HISTORY §68](docs/HISTORY.md#68)
69. **Fingerprint decode fallback + honest per-file failure reasons —
    done.** `compute_fingerprint()` falls back to an ffmpeg subprocess
    decode on any soundfile failure (ffmpeg-on-PATH only), re-raising
    the original error when ffmpeg is absent/also fails. **A planned
    librosa stage was refuted before writing any code:** this project's
    pinned librosa (1.0.0) dropped its audioread path — `load()` calls
    soundfile directly, identical to the primary path on every failure;
    skipped. **Real bug found via an 11-minute hang, not review:**
    ffmpeg's stderr was piped but never drained during decode, so
    sustained-corruption files overflow the 64KB pipe buffer and
    deadlock both processes — fixed with a real tempfile for stderr
    instead. New `_classify_fingerprint_failure()`
    (`file_missing`/`empty_file`/`decode_unsupported`/`error`). **Real
    numbers, all 76 production failures:** 2 empty files, 73 rescued by
    ffmpeg, 1 still fails (a `.mp3`-named DRM-protected HLS manifest,
    no real audio in it at all). **Unexplained, not pursued further:**
    the dominant failure category reproduces reading the real mounted
    path but a byte-identical local copy decodes fine via soundfile too
    — implicates libsndfile's drive I/O, not file corruption.
    [HISTORY §69](docs/HISTORY.md#69)
70. **Open, real bug found live closing out items 68-69 (2026-09-02):
    the real stress test hangs reliably at real production scale —
    reproduced 3/3 times — but did NOT reproduce in 2/2 isolated
    repros, one of them at a realistic 1,500-real-file scale. Not
    fixed, root cause not found.** Always at the exact same point: the
    tick immediately after sync/scan/match settle, waiting on the
    Duplicates page's Compute Fingerprints step. **A materially worse
    signal than item 63's own storm:** a `threading.Timer`-based
    diagnostic watchdog (dumps every thread's stack via
    `faulthandler`, no root needed — added and since reverted, see
    HISTORY) never fired even once across ~38 real minutes stuck — a
    fresh Python thread being unable to run at all points at something
    holding the GIL for the whole process, not merely a stuck Qt event
    loop (item 39's own documented class). Both isolated repro
    attempts fired Compute Fingerprints via the real
    `compute_fingerprints_button.click()` path — i.e. already through
    Phase 7.3's `reports_progress=True`/`on_progress` wiring — so the
    new progress channel itself is NOT the isolated-repro
    differentiator; whatever's real-scale-only remains unidentified
    (real Spotify sync duration and/or real production DB size/content
    are the two remaining, not-cheaply-testable suspects). **Standing
    caution, not a block:** treat Phase 7.3's fingerprint progress
    wiring as higher-risk until this is root-caused — nothing here
    says it's the cause, but nothing rules it out either, and it's the
    newest code touching the exact step where this reproduces.
    **Round 6 determination (requested by the round-6 brief): still a
    separate, still-open defect from item 105 (C3)'s own "full-suite
    stall" fix.** Different symptom (this app itself freezing mid-
    fingerprinting a real production library — no Python thread able to
    run at all — vs. item 105's `pytest` runner blocking on a queued,
    unmocked `QMessageBox.information()` popped by a later test),
    different trigger (real library scale vs. test execution order),
    different mechanism (whatever holds the GIL for the whole process
    vs. a modal dialog's own event loop waiting for a click that never
    comes under offscreen QPA). Item 105 fixed a real bug, but not this
    one — item 70 remains open with its root cause still unidentified.
    [HISTORY §70](docs/HISTORY.md#70)
71. **Fix: "You're all set" (and any next-step CTA) reappeared ~2s after
    being dismissed — done.** `InlineNotice` gained a real
    `dismissed = Signal()`, emitted from `dismiss()`.
    `MainWindow._render_next_step` (poll-driven, every 2s) now tracks a
    dismissed-step key (playlist name + step message + action) and
    skips re-showing an identical step, clearing the stored key the
    moment the computed key changes — so a genuinely different step, or
    the same step recurring later, still surfaces. Confirmed via Phase 0
    that `dashboard_notice`/`locations_notice` don't share this bug —
    both are only ever driven from action-result callbacks, never a
    poll tick. First item closed from `docs/BRIEF-2026-09-02.md`
    (P1-P6, six real user-reported bugs); Phase 0's live reproduction
    also surfaced a real, already-existing DB/disk desync in the "Test"
    library location unrelated to this fix — see item 72+ for the
    rename item that actually explains it.
72. **Fix P1: tagging controls row squeezed the playlist panel — done.**
    New `ui/flow_layout.py::FlowLayout` (the standard Qt reflowing-row
    pattern) replaces the plain `QHBoxLayout` `_build_tagging_controls`
    returned. Fixes both halves of the bug at once: a `QHBoxLayout`'s
    minimum width is the SUM of its children's minimum widths (~900-
    1000px for 9 controls); `FlowLayout.minimumSize()` returns the
    WIDEST SINGLE ITEM instead, and `heightForWidth()` reflows the row
    onto more lines as width shrinks, purely from real Qt layout math —
    no breakpoint constants. `playlist_list` also gets a real
    `setMinimumWidth()` floor (sized via `QFontMetrics` against an
    untuned "realistic long playlist name" sample string, flagged as
    such). Confirmed live: `dashboard_content.minimumSizeHint().width()`
    dropped to 445px (well under the app's 960px minimum window width).
    Skipped 1.3's optional `QSplitter` — the FlowLayout fix alone
    already resolves both symptoms structurally, and a splitter would
    touch every existing dashboard-layout test for no further gain.
73. **Fix P4: Duplicates "Actions" column showed nothing (4th report) —
    root-caused for real this time, done.** Three prior investigations
    all asked "does `cellWidget()` return a widget" — true even when
    clipped to near-zero width, which live measurement confirmed is
    exactly what happens at the app's real 960×640 minimum (real
    `visibleRegion()` was `(0,0,0,0)`) since nothing in `src/seeker/ui/`
    had ever set a column width. New `_size_duplicates_columns()` gives
    ACTIONS a `Fixed` width DERIVED from its own real `sizeHint()`
    (structurally immune to squeeze), PATH `Stretch`, everything else
    `ResizeToContents`. `_render_duplicate_groups` also now calls
    `clearSpans()` (a second, independent, confirmed defect —
    `setRowCount()` doesn't clear spans; auditing every other table for
    the same omission found a real THIRD live instance in
    `_render_sharing_uploads_table`'s no-uploads span, fixed the same
    way). Rewrote, not deleted, the item 56 §6.2 "could not reproduce"
    test to assert real geometry instead of just `isVisible()`.
    [HISTORY §73](docs/HISTORY.md#73)
74. **Fix P5: "slskd.yml has no active shares section to add to" —
    done, live-verified against a real disposable throwaway container.**
    `_insert_slskd_share_directory` now CREATES the block (appended at
    end of file) when none exists instead of refusing — confirmed live
    against a real, genuinely-fresh, never-hand-edited slskd container's
    own generated default (`tests/fixtures/slskd_generated_default.yml`,
    captured 2026-09-02): it has NO active `shares:` block at all, only
    the commented template, exactly the reported error's cause.
    `add_location_to_share` now computes BOTH new file contents before
    writing either (closes a real partial-write window — a failure used
    to leave `docker-compose.yml` mutated with nothing on the slskd.yml
    side to match), and rolls the compose file back from its own backup
    if the second write still fails. `docker_setup.py::compose_file_path()`
    now copies the bundled `docker-compose.yml` into the same stable
    per-user `slskd_data_dir()` on first use for a frozen build (once,
    guarded) instead of resolving inside the app bundle — real,
    live-confirmed problem: `is_self_managed()` compares a container's
    permanently-recorded label against this path, and a bundle path
    regenerates on every rebuild. Live E2E-verified end to end against
    a real disposable container (never the real production `slskd`
    one): real block creation, real compose volume line, real backups,
    `is_self_managed()` correctly `True`. [HISTORY §74](docs/HISTORY.md#74)
75. **Fix P6: cover art "still doesn't update" (4th report) — code done,
    awaiting the user's own visual DJ-software check.** Phase 0.4
    re-confirmed the write path is sound (4/4 real tracks byte-exact
    vs. current CDN). Both live candidates fixed: (6a)
    `format_tag_result_notice`/`_show_tag_result_notice` now say
    plainly, in every message shape (not just the all-skipped case),
    that any already-tagged-and-skipped track's art was NOT checked
    this run, and offer "Fix missing cover art" as the notice's own
    action button. (6b) new `metadata.py::save_tags()` writes
    **ID3v2.3** (`v2_version=3`) for MP3/WAV instead of mutagen's
    default v2.4 — the one thing never done in four rounds. (6.4) a WAV
    embed now reports its own honest outcome
    (`tagged_art_rarely_supported_format`/`fixed_wav_rarely_supported`)
    instead of joining the same "written" bucket as a real, visible
    MP3/FLAC/M4A embed. Live-verified with the user's explicit go-ahead:
    ran a real `--force` re-tag against the real "Test" playlist (DB
    backed up first) — both real MP3s now write ID3v2.3, all 9/9
    tracks stay byte-exact vs. the current CDN art. **Not closed yet**
    — per the brief's own standing rule, this only closes when the user
    confirms they can actually SEE the art in their real DJ software,
    which only they can check. [HISTORY §75](docs/HISTORY.md#75)
76. **Fix P2: "Rename files" leaves numbered prefixes the preview said
    would go away — done, real root cause was neither of the three
    hypothesized defects.** Phase 0.2's real live investigation found
    the actual cause: an already-existing, pre-session real DB/disk
    desync (5 files already renamed on disk via Seeker's own Rename
    feature, `local_files.relative_path` never reconciled — root cause
    of the DB write not landing not conclusively identified, see
    HISTORY §71/§76). Reconciled via a normal rescan, then fixed every
    "regardless" defect the brief named: (2.2) `plan_renames` now
    detects WITHIN-BATCH target collisions (two tracks proposing the
    same final name) at plan time, not just against the pre-existing
    filesystem. (2.3) `_apply_one_rename` now records an honest detail
    whenever the real resolved name differs from what the preview
    showed, and counts it in `collisions` (redefined to mean "actually
    differed," not "was predicted to differ" — more accurate than
    before). (2.4) `apply_renames` re-plans FRESH from the same track
    ids immediately before doing any real work and refuses (a real
    per-track failure, not a silent skip) any track whose fresh plan
    disagrees with what the user confirmed — closes the "dialog left
    open while a real download lands" window structurally, the safer
    of the brief's two offered options. (2.5) the result notice now
    names the count of files written with a different name than
    previewed, prominently, not just in the capped results panel.
    7 new tests, including one reproducing the exact real Phase 0.2
    failing shape (a stale DB row after a completed rename reads as a
    false collision — documented as understood DB/disk-drift behavior,
    not a `plan_renames` bug). [HISTORY §76](docs/HISTORY.md#76)
77. **Fix P7: Duplicates Actions column blank, 5th report — root cause
    was occlusion, not width — done.** Item 73's width fix was real but
    for a different defect. Real cause, confirmed via a live PySide6
    experiment: a blank `QWidget()` placed on every row COVERED by the
    Actions span gets resolved by Qt to the EXACT SAME geometry as the
    real span-owning widget, and — added to the viewport later — paints
    over it. The real widget's own `visibleRegion()` stays fully
    non-empty throughout, which is why every prior geometry-based test
    (including item 73's) passed anyway. **Standing fact for any future
    `setSpan`+`setCellWidget` pairing:** call `setSpan()` BEFORE
    `setCellWidget()` on the span-owning cell, and put NO widget of any
    kind on the covered cells — the span itself renders them blank; a
    "blank placeholder" widget is not just unnecessary but actively
    dangerous. Regression test must be occlusion-aware
    (`viewport().childAt(visualRect(...).center())`), not just
    existence/geometry — the property that gap explains why 4 rounds
    of introspection-only testing missed it. [HISTORY §77](docs/HISTORY.md#77)
78. **Fix P8 (Duplicates "0 files in scope") + P9 (location combo
    disabled) — done, combined into one commit on purpose.**
    `resolve_folder_scopes` now picks the MOST SPECIFIC registered
    location a folder resolves inside (longest resolved-path match),
    not the first alphabetical one — confirmed as a real, live bug via
    this session's own real production DB (a "Music" location with 0
    scanned files sorts before its own nested "Test" child, which has
    real fingerprinted files at that exact path). A genuine specificity
    tie is only reachable via two different registered path STRINGS
    resolving to the same real directory (`library_locations.path` is
    UNIQUE at the schema level, so literal duplicates can't happen) —
    broken by a new optional `preferred_location_id` param, which is
    exactly what P9's now-always-enabled location combo feeds in at
    every UI call site (captured on the GUI thread, never read from
    inside a `run_worker` background closure — reading `QComboBox`
    state off-thread is a real Qt hazard). New
    `DuplicateService.summarize_scopes()` → `ScopeSummary` names which
    location(s) a scope resolved to and flags any with zero scanned
    files, closing the "silent unexplained 0" half of the bug.
    [HISTORY §78](docs/HISTORY.md#78)
79. **Fix P12 (Qt mnemonic in "Rescan & match library") + P11 (tagging
    controls had no spacing) — done.** A bare `&` in `QPushButton`/
    `QLabel` text is a real Qt keyboard-mnemonic marker (consumed,
    renders as an underline), not a literal ampersand — `"&Help"` on
    the real menu bar is the one intentional exception in this file.
    New source-level regression test (regexes every button/label
    string literal in `main_window.py`) catches any future stray `&`
    automatically. Separately, item 72's `FlowLayout()` was
    constructed with default `h_spacing`/`v_spacing` (`-1`, falling
    through to a style-derived value that's ~0 under this app's Fusion
    styling) — fixed with explicit `theme.SPACING_SM`; **verified as a
    real defect, not cosmetic**, by reverting in isolation and
    reproducing a real measured -2px (actual overlap) gap between two
    buttons. **Standing gotcha for any future FlowLayout geometry
    test:** a `.hide()`'n item's `QWidgetItem.setGeometry()` is a real
    Qt no-op (`isEmpty()` short-circuits it) — its `.geometry()` stays
    stale/default, so exclude hidden items from any geometry-based
    assertion rather than including every item by index.
    [HISTORY §79](docs/HISTORY.md#79)
80. **Fix P10 (square-edged cell widgets break the rounded card
    corners, global) — done.** Qt's `border-radius` on a widget never
    clips that widget's children — any `setCellWidget` widget reaching
    a table's edge paints flat square corners straight over the
    table's own rounded corner, and no stylesheet rule can fix a
    paint-order/clipping problem. New `theme.make_card(inner) ->
    QFrame` is the structural fix: the frame owns the real rounded
    border/background (`QFrame#card` + `WA_StyledBackground` per item
    47's own gotcha #2); `inner` gets its own border turned off and
    sits behind a small real content margin (`SPACING_XS`) that
    physically keeps any of its edge-reaching children away from the
    frame's rounded arc. Routed through all 11 real
    `QTableWidget`/`QListWidget` instances in the app — a
    `QStackedWidget` page (`track_table`) needed a `track_table_card`
    attribute as the actual page/`setCurrentWidget` target, since
    `setCurrentWidget` requires its argument to be a widget the stack
    actually owns as a page. New `theme.cell_widget(*widgets)`
    consolidates 6 independently-drifted hand-rolled cell-widget
    container builders into one, with real spacing and a trailing
    `addStretch()` — the stretch is what stops a lone button from
    being resized to fill the WHOLE cell rect (`setCellWidget`'s own
    behavior, bypassing normal layout sizing). **Scoping call, stated
    explicitly:** the Downloads table's progress-bar cell builders
    were deliberately left bespoke (they need a real stretch FACTOR on
    the bar itself, which `cell_widget()`'s generic API doesn't
    support) — `make_card()` alone already closes their table's
    corner risk regardless of what's inside each cell.
    [HISTORY §80](docs/HISTORY.md#80)
81. **Build identity + per-account data doc + frozen compose path
    (0.1/0.2/0.3) — done.** New `src/seeker/_build_info.py` (git SHA/
    describe/UTC timestamp), regenerated by `packaging/build_dmg.py`
    immediately before every real PyInstaller build. **Superseded by
    item 83:** the first version had `build_dmg.py` overwrite this
    tracked file directly, which permanently dirtied the tree on every
    real build — see item 83 for the actual write target. Surfaced in
    the window title, About
    dialog, and Help page — "is this account running the build I
    think it is?" is now a two-second visual check, closing the real
    testing-logistics trap the previous brief's own section 0
    diagnosed (a build tested ~2 hours after the last commit looked
    identical to the pre-fix one from inside the app, though the
    underlying code was never actually different). New Help-page
    sentence states plainly that `platformdirs.user_data_dir("Seeker")`
    is per-macOS-account (item 18's own standing fact, never
    previously user-visible) — a cross-account "fix didn't work"
    report is very often a different-database report. **0.3 needed no
    code change:** `compose_file_path()`'s frozen-build canonicalization
    was already fixed by item 74 — confirmed by reading current
    source, not assumed. [HISTORY §81](docs/HISTORY.md#81)
82. **New feature: manual track search and download (P13) — done,
    live E2E download left for the user to confirm and run.** A manual
    track is a real `tracks` row (`id=manual:<uuid4>`, `album=""`,
    `duration_ms=0`, backfilled with the real duration on first index
    — see below) belonging to no playlist —
    `DownloadService.search_manual`/`download_manual` share
    `_build_search_query`/`select_downloads` with `download_playlist`
    verbatim, never a second copy; `chosen` bypasses ranking/threshold
    for an explicit per-row pick; an optional `files` param skips a
    second real 20-45s search. New "Search" sidebar page (Dashboard →
    Search → Downloads), new `seeker search <artist> <title>
    [--download]` CLI command. New public `quality.rank_candidates()`/
    `score_candidate()` wrap the exact same private ranking/scoring
    `select_downloads` already used. **Real gaps found and fixed along
    the way, not just the brief's own named risk:** (1) `_resolve_
    destination` widened to `Playlist | None` per the brief, but
    `_move_completed_file`'s OWN playlist-iteration loop never ran at
    all for a zero-playlist track — fixed with an explicit fallback,
    scoped narrowly so an ordinary playlist track's existing behavior
    is unchanged. (2) a LATER `match_all()` re-run's duration pre-
    filter would fail a real `duration_ms=0` against nearly any file
    (item 45's own demotion class, a new trigger) — fixed by
    backfilling the real duration once, from the just-downloaded file,
    manual tracks only. (3) `check`'s GLOBAL report reads every
    `tracks` row and would leak a manual track into "unmatched" — fixed
    by excluding `is_manual_track_id()` rows from that one branch.
    (4) Downloads/History both fell through to a bare "Unknown"
    playlist label (a fallback meant for a genuinely-unexpected data
    gap) for EVERY manual track — new shared `models/track.py::
    resolve_playlist_label()` says "Manual" instead, one place instead
    of three independently-drifting copies. [HISTORY §82](docs/HISTORY.md#82)

83. **Fix R1 (post-implementation review of item 81) — a real build
    permanently dirtied the tree — done.** `packaging/build_dmg.py` used
    to overwrite the TRACKED `src/seeker/_build_info.py` directly;
    `.gitignore`'s entry for that path did nothing (git never applies
    ignore rules to an already-tracked file), so every real `.dmg`
    build left the tree dirty and a careless commit could sweep a real
    SHA in over the `"dev"` fallback. Fixed by splitting the write
    target: `build_dmg.py` now writes a genuinely gitignored
    `src/seeker/_build_info_generated.py`; the tracked `_build_info.py`
    only `try/except ImportError`s it, falling back to `"dev"`, and is
    never itself written to by anything. `tests/test_build_info.py`
    guards the tracked fallback's literal source text.

84. **Fix R6: Sharing's `401 Unauthorized` on `/api/v0/application` —
    code done; live re-verification blocked in this sandboxed session,
    left for the user.** `add_location_to_share`'s container recreate
    now routes through the same `docker_setup.bring_up_slskd()` the
    wizard/Settings use (one 5-variable env contract, not two), refuses
    outright via new `SlskdCredentialsMissingError` if the config store
    is missing any of the three credentials, and `get_status`/
    `get_uploads` wrap a real 401 as new `SlskdUnauthorizedError` with
    actionable text. [HISTORY §84](docs/HISTORY.md#84)

85. **Fix R1: AIFF files were invisible to the whole app — done,
    live-verified against real production files.** `.aiff`/`.aif`/
    `.aifc` added to `AUDIO_EXTENSIONS`; `.aiff`/`.aif` (not `.aifc` —
    a container that can hold compressed audio) added to `quality.
    LOSSLESS_EXTENSIONS`. Tagging/art/duration-bitrate needed ZERO code
    changes — all confirmed live (mutagen 1.48.1): AIFF's `_IFFID3` is
    a genuine `ID3` subclass, and `AIFFInfo` already computes
    `bitrate = channels × sample_size × sample_rate` internally.
    [HISTORY §85](docs/HISTORY.md#85)

86. **Fix R2: the 2-second poll destroyed every checkbox/radio in a
    polled table — done.** Root cause was exactly as diagnosed: a
    poll-driven rebuild (`setRowCount` + fresh `QCheckBox`/
    `QRadioButton` per row) carried nothing across ticks. Fixed with
    small state maps keyed by STABLE identity, never row index —
    `_upgrade_delete_checked: set[int]` (keyed by `request_id`) and
    `_duplicates_keep_selection: dict[frozenset[int], int]` (keyed by
    a group's own member `local_file` ids, since a group has no id of
    its own) — restored on render, pruned when the row/group is gone.
    Audited every other polled table (item R2.4): no other interactive
    per-row control exists anywhere else in the app today.
    [HISTORY §86](docs/HISTORY.md#86)

87. **Fix R5: global table chrome — black columns/corners + clipped
    text in 8 more tables — done, pixel-verified.** New
    `theme.apply_table_defaults(table)` (hides the vertical header —
    5a — and floors row height at a real `cell_widget()`'s own
    `sizeHint().height()` via `verticalHeader().setMinimumSectionSize`
    — 5b.2, empirically confirmed to need no extra `resizeRowsToContents()`
    call to take effect on new rows) applied to every real
    `QTableWidget` in the app. New `theme.size_action_column(table,
    column, action_widgets)` extracted from item 73's own
    `_size_duplicates_columns`/`_size_search_columns` (both now call
    it instead of a third copy) and applied to 5 more tables with real
    Actions columns (`track_table`, `sharing_locations_table`,
    `review_needs_table`, `review_upgrades_table`,
    `review_local_table`); `downloads_table`/`history_table`/
    `sharing_uploads_table` have no Actions column (progress bars or
    plain text) so only got the row-height/vertical-header half.
    Stylesheet gained `QHeaderView`/`QTableCornerButton::section`
    rules as a belt-and-braces backstop. Verified with real offscreen
    screenshots at 960×640 and 1280×800 — every button renders in
    full, no black column/corner anywhere. [HISTORY §87](docs/HISTORY.md#87)

88. **R3: bulk actions — "Replace all" upgrades + "Resolve all groups"
    duplicates — done.** New `DownloadService.
    apply_upgrade_decisions_batch()`/`DuplicateService.resolve_groups()`
    wrap the existing single-row mutations, per-item try/except (item
    15), success checked by re-reading real state (not the message
    string). New `BulkReplaceUpgradesDialog`/`BulkResolveDuplicatesDialog`
    mirror `RenamePreviewDialog`'s shape; both built fresh at click
    time (item 76). CLI parity: `seeker downloads review --all` only —
    Duplicates bulk-delete has none (stated explicitly, not
    half-added; see HISTORY). [HISTORY §88](docs/HISTORY.md#88)

89. **R4: cover art in Finder — answer confirmed, opt-in `cover.jpg`
    sidecar shipped, per-file custom icons deliberately not built.**
    R4.1: byte-level re-confirmed (real MP3, ID3v2.3, real embedded
    JPEG) — the format explanation (macOS Finder never reads embedded
    art from FLAC/WAV, only MP3/M4A/AIFF) stands; the actual Finder
    visual check is blocked in this sandboxed session (AppleScript
    control of Finder times out with no Automation permission, same
    class of OS-permission blocker as item 84's Docker dialog) and is
    left for the user. R4.2: new opt-in `SeekerConfig.
    write_cover_jpg_sidecars` (default off, Settings → Thresholds tab)
    — `MetadataService` gained the same `get_config` callable pattern
    as `DownloadService`/`TrackMatcher`; writes `cover.jpg` next to a
    tagged track's own file (never overwrites an existing one) from
    both `tag_tracks`/`fix_missing_art_for_playlist`'s already-
    downloaded art bytes, no extra fetch. R4.3: per-file custom Finder
    icons deliberately NOT implemented — see HISTORY for the specific
    exFAT/AppleDouble reasoning. [HISTORY §89](docs/HISTORY.md#89)

90. **R7: run in the background from the macOS menu bar — done, closes
    the round-3 brief.** `QSystemTrayIcon`-guarded (`isSystemTrayAvailable()`
    — real fallback to today's quit-on-close when absent), closing the
    window hides to the tray instead (one-off first-hide notification),
    Quit is a real `QApplication.quit()` → `aboutToQuit` →
    `MainWindow.cleanup_before_quit()` path used by every quit route
    uniformly. New `SeekerConfig.downloads_paused` — checked inside
    `DownloadService.poll_downloads()` itself (not just the UI timer),
    so pause is authoritative regardless of caller. Menu status/counts
    built entirely from data the existing poll methods already fetch
    (never a third source of truth); re-render (not re-fetch) skipped
    while hidden. Batched/rate-limited notifications for downloads-
    finished, needs-decision, and errors, all per-category toggleable
    in Settings, all defaulting on. Packaging gap found and fixed along
    the way: `packaging/icons/` was never bundled as a runtime resource
    (build-time only) — would have shipped a blank tray icon; fixed the
    same `sys._MEIPASS` way `docker-compose.yml` already is.
    [HISTORY §90](docs/HISTORY.md#90)

91. **Post-round review fix (RR1-RR3) — "green with 3 pre-existing
    failures" was never actually pre-existing or unrelated; fixed for
    real, done.** Two failures were caused by item 81's own build-
    identity feature (a real local `.dmg` build leaves gitignored
    `_build_info_generated.py` behind — a bare `git stash` can't see
    it, `-u` can); fixed with a `tests/conftest.py` autouse fixture
    forcing `"dev"` for the whole suite, plus a real mypy override
    instead of a blanket `# type: ignore`. The third
    (item 79's own regression test) was a real offscreen-Qt geometry-
    settling artifact, fixed with `QApplication.processEvents()` after
    each `setGeometry()` call. Full suite now genuinely green: `1028
    passed, 1 skipped`. New standing conventions: `git stash -u` (not
    bare `git stash`) to check "pre-existing"; report the real pytest
    summary line and name every failure; a pre-existing-failure count
    that changes between rounds is a regression to diagnose, never a
    new baseline. [HISTORY §91](docs/HISTORY.md#91)

92. **Fix B8: Spotify 401 after ~1hr uptime, unrecoverable without a
    restart — done.** `Application._spotify` was a cached client built
    once from a frozen access-token *string*; nothing ever reset it, so
    every call after the token's real 1-hour lifetime 401'd forever, and
    Settings' "Re-authorize" (`connect_spotify(force_reauthorize=True)`)
    short-circuited on that same non-None cache and never actually ran
    the OAuth flow — the one recovery path in the UI was a silent no-op.
    Fixed: `SpotifyClient` now takes a `TokenSource` (`str | Callable[[],
    str]`) instead of a bare string — `Application.spotify` binds it to
    `auth_manager.get_valid_token().access_token`, so a client built
    early in a session still gets a token `get_valid_token()` has
    already refreshed. New `SpotifyClient._get` 401 handling: on a 401,
    calls an optional `force_refresh` callable (bound to
    `get_valid_token(force_refresh=True)`, which skips the normal
    expiry check) and retries **exactly once**; a second 401 raises
    `SpotifyAuthenticationError` ("Re-authorize in Settings.") instead
    of a raw `httpx.HTTPStatusError` URL string. `connect_spotify` now
    resets `self._spotify`/`self._sync_service` alongside
    `self._auth_manager`, closing the actual unrecoverable half of the
    bug. Standing fact recorded in `auth_manager.py`: Spotify rotates
    PKCE refresh tokens, so two installs sharing one account/client ID
    can invalidate each other's stored refresh token — a real,
    separate effect, not this bug. **Left for the user (real machine
    only):** confirming the real token file's `expires_at` is a
    plausible ~3600s-after-mtime value (B8.4), and a live past-expiry
    reload with no restart (B8.7).

93. **B3 — reporting fix (done); two real findings surfaced, not fixed
    (open).** Rename preview / tagging-result panel show a location-
    relative path (not basename-only) + a destination-mismatch note
    (new `destination_resolution.py`, shared with DownloadService).
    Investigating B3.5 found and fixed a real crash: duplicate
    clustering opened a stale row's file (a rename left one
    overlapping-location copy pointing at a renamed/missing file, item
    76's drift class) with no try/except; now skips it with an honest
    reason, and `delete_local_files` refuses to delete either side of a
    group whose two rows are the SAME physical file (new
    `file_deletion.py::same_file`). **Left open, a real user decision:**
    three registered locations nest inside each other (item 77) and now
    double-index ~3,450 real files — `add_location` has no containment
    check yet. [HISTORY §93](docs/HISTORY.md#93)

94. **B5 — only download real DJ formats — done.** New
    `audio_formats.py::DOWNLOADABLE_EXTENSIONS = {".mp3", ".flac",
    ".wav", ".aiff", ".aif", ".m4a"}` (asserted a subset of the wider,
    still-permissive `AUDIO_EXTENSIONS`) + shared
    `is_downloadable_extension()`, applied at all three real entry
    points: `quality._score_candidate`, `rank_candidates()` (Search
    page + CLI raw results — had no gate before), and
    `download_manual(chosen=...)` (bypasses `select_downloads`
    entirely — new `UnsupportedDownloadFormatError`, refuses loudly
    rather than a silent no-op). `.m4a` in, bare `.mp4` out (video
    collision risk); `.aac`/`.aifc`/`.ogg`/etc. all out — judgement
    calls stated in the module comment. The one real `.ogg` already in
    the library is untouched (indexing/playback unaffected).

95. **B1 — Enter submits on wizard/Settings forms — done.**
    `OnboardingWizard` is a `QMainWindow`, not a `QDialog`, so Qt's
    autoDefault machinery never applied — Enter had no keyboard path to
    any button at all before this. Wired `returnPressed` on the
    wizard's Client ID field (guarded by `connect_button.isEnabled()`,
    mirroring the click-disabled state) and SoulSeek username/password
    fields (`_on_bring_up_clicked`'s own validation already covers
    empty fields). Extended to every other single-obvious-submit-
    target field in `settings_window.py` (destination subfolder,
    Spotify client ID, SoulSeek update-credentials, both threshold
    fields) — all four self-validate identically to a click, so this
    was the same reasoning applied uniformly rather than scoped to
    just one form.

96. **B4 — the "Queued" progress bar sat at the top of its cell — done.**
    `_build_progress_widget`'s indeterminate branch returned a bare
    `QProgressBar` directly from `setCellWidget` — the global
    `QProgressBar { max-height: 14px; }` rule then clamped it to the
    top of a tall row (Qt's default for a widget smaller than its cell
    with no layout), while the other two exits (determinate here, and
    `_build_terminal_progress_widget`'s own determinate branch) already
    wrapped their bar in a centering `QHBoxLayout` container. New
    shared `_wrap_progress_bar(bar, label_text)` used by all three exits
    (`label_text=None` omits the ETA label for the indeterminate case) —
    a fourth branch can no longer reintroduce this by skipping it.
    Pixel-verified for real (item 102, after a post-round review found
    the first "pixel-verified" claim was asserted, not recorded): a
    real pixel scan of a `window.grab()` found the queued bar's real
    color-span center 0.5px from its row's center, downloading 0.5px —
    both well inside the brief's "within a pixel or two."

97. **B2 + B6 — table/card chrome: header dividers + Settings' two
    unstyled tables — done.** B2: `QHeaderView::section`'s `border:
    none` (item 47) removed the native column-header divider with no
    fallback, since any `QHeaderView::section` rule makes Qt paint the
    header entirely from that box model — added `border-right: 1px
    solid {BORDER}` (suppressed on the trailing section). Body
    gridlines were never actually lost — item 102's real pixel scan (16
    samples across every row boundary of a real `window.grab()`) found
    an exact `(58,52,78)`/`#3A344E` BORDER-color match at all 16, zero
    drift toward BG_SURFACE — `make_card`'s per-widget stylesheet
    doesn't touch `gridline-color`. B6: `settings_window.py`'s
    `locations_table` and `destinations_playlist_list` were the only
    two real `QTableWidget`/`QListWidget` in the app never routed
    through `apply_table_defaults()`/`make_card()`/`size_action_column()`
    (item 80/R5) — same black-column/square-corner/clipped-Actions
    defects, now fixed identically to every `main_window.py` table. New
    structural test walks `findChildren` on a real `MainWindow` (which
    embeds `SettingsPage`) asserting every table/list has a
    `QFrame#card` ancestor — confirmed to actually fail without the
    fix, not just pass either way, closing the "third round a shared
    fix landed in one file and not the other" gap for good.
    Pixel-verified for real (item 102) at the app's actual 960×640
    minimum window size, not just default — both Settings tabs render
    correctly at 960×640: the Actions column header renders in full
    ("Actions", not clipped), both action buttons render completely.
    [HISTORY §102](docs/HISTORY.md#102)

98. **B10 — window title showed a commit SHA — done.** Reversed item 81
    (0.1): `setWindowTitle(f"Seeker — {_build_info.GIT_SHA}")` → plain
    `"Seeker"`. Build identity's real home, Help → About Seeker, is
    untouched — `AboutDialog` already renders `GIT_SHA`/`GIT_DESCRIBE`/
    `BUILT_AT`. Updated `test_main_window_constructs_without_crashing`'s
    title assertion; left `test_about_dialog_shows_build_identity`
    exactly as RR1.1 fixed it (asserts the About dialog's own separate
    label text, unaffected by this).

99. **B9 — the macOS menu bar icon, and "Check now"'s real name —
    done.** `_resolve_tray_icon_path()` now points at a real template
    asset (`packaging/icons/seeker_menubar_Template.png`/`...@2x.png`,
    37×18/75×36, committed this round) instead of the full-colour app
    `.icns` — `setIsMask(True)` against the `.icns` discarded its
    color and stamped only the alpha channel, which is one opaque
    rounded square for the whole icon, producing the reported solid
    squircle blob. The new asset is derived, not redrawn (luminance-
    thresholded from the real 1024px icon, background circle dropped,
    cropped to the artwork's bounding box, brow strokes dilated to
    survive an 18px downscale, re-emitted as black pixels with the
    glyph in the alpha channel) — reproducible, documented inline.
    `seeker.spec` already bundles the whole `packaging/icons/`
    directory as a `datas` entry (item 90), so the new PNGs need no
    separate spec change. Tray's "Check now" (ambiguous with Help →
    "Check for updates…", a wholly different action) renamed to "Check
    downloads now" with a tooltip. **Left for the user:** the real
    macOS menu bar check (both appearances) — this sandboxed session
    has no Screen Recording permission (same gap as items 84/89/90); an
    offscreen-rendered proxy (the icon composited on light/dark
    swatches) confirms the alpha-channel glyph shape is now legible
    instead of a filled blob, but can't exercise AppKit's own real
    template auto-recolor pipeline.

100. **B7 — removed the `cover.jpg` sidecar feature — done, a
     deliberate reversal of R4.2.** Tested in the real world and didn't
     pay off: `cover.jpg` is a Plex/Jellyfin/Kodi/foobar2000/Traktor
     convention, never a macOS Finder one — nothing was ever going to
     change in Finder from it, and this app's own playlist-shaped
     folders (vs. a per-album folder assumption) meant a folder holding
     tracks from several albums got one wrong cover, not a missing one.
     Removed `_write_cover_jpg_sidecar` + both call sites,
     `SeekerConfig.write_cover_jpg_sidecars` (loader still tolerates a
     leftover key from an older config.json — tested), the Settings
     toggle, and 7 tests covering the feature. **9 real `cover.jpg`
     files already exist in the user's library from R4.2's own opt-in
     — left in place per the standing rule (no file removed without
     explicit confirmation); reported to the user, theirs to delete if
     they want.** [HISTORY §100](docs/HISTORY.md#100)

101. **B11 — two observations, both confirmed against the real DB, no
     code changed (as instructed).** B11.1: the doubly-nested
     `Test/Music/Test/` folder is a real, simple data misconfiguration,
     not a path-joining bug — playlist "Test" has
     `download_location_id` pointing at the "Test" location (whose own
     path is already `.../Music/Test`) **and** a stored
     `download_subfolder` of `"Music/Test"`, so the two legitimately
     concatenate. `_resolve_destination`'s join logic is doing exactly
     what it's supposed to with what's stored; fixing this is a
     Settings → Playlist Destinations edit (clear that playlist's
     subfolder), not a code change — left for the user. B11.2: a
     completed **settled** download does NOT silently overwrite an
     existing match — `poll_downloads()` checks `_track_already_has_a_
     matched_file()` before `_index_and_match_settled_download` ever
     runs, and routes an already-matched track's completion to
     `ready_for_review` instead (item 56 Phase 5.3, a real, existing
     guard). The Neuro→Test flip B3 found is far more likely
     `match_all()`'s own documented no-provenance-tracking behavior
     (item 45) re-scoring once a second local candidate existed, not
     this path. [HISTORY §101](docs/HISTORY.md#101)

102. **C1 — header column dividers, real root cause found via a real
     bisect (not a third guess) — done.** `QHeaderView::section:
     horizontal:last-child` (CSS syntax, not valid Qt QSS) was
     poisoning the ENTIRE `::section` rule, silently dropping
     `border-right` everywhere — a `window.grab()` pixel scan found
     zero divider-colored pixels at any boundary with it present, and
     a full divider at every boundary with only that one selector
     removed (`:last` alone, real Qt QSS, still correctly suppresses
     the trailing divider). Header dividers now use `BORDER_STRONG`
     (1.98:1 vs `BORDER`'s 1.46:1) — the header is one flat block with
     no alternating-row-color help, unlike the body gridlines, which
     were confirmed live to have never actually been missing. **Larger
     finding, beyond this item's own scope:** `theme.apply_theme()` was
     never called ANYWHERE in the test suite before this — every prior
     `window.grab()`-based "pixel-verified" claim (item 102's own
     B2.2/B4.3/B6.5) was rendered under Qt's default style/palette, not
     the real Fusion+QSS+dark-palette stack the shipped app uses. Fixed
     with a new session-scoped autouse fixture in `tests/conftest.py`;
     confirmed low-risk by running the full suite before/after — only
     this item's own brand-new test changed outcome, everything else
     already passed against the real theme. Also found and fixed a
     latent, previously-invisible bug this surfaced: two `window.grab()`
     pixel tests read logical-pixel coordinates directly into a
     device-pixel `QImage` with no `devicePixelRatio()` scaling (this
     session's real Qt reports 2.0) — both happened to still pass by
     coincidence before, for the wrong reason. [HISTORY §103](docs/HISTORY.md#103)

103. **C2 — "Action" rendered as ".ction" on every EMPTY table — done.**
     `theme.size_action_column`'s fallback for zero real action widgets
     used to be `header.minimumSectionSize()` (a generic 40px floor
     unrelated to the word "Actions"), which fired on exactly the first
     thing a new user sees on Review/Search/Duplicates: an empty table.
     New `theme.header_label_floor(table, column)` derives a real
     minimum from `QFontMetrics.horizontalAdvance()` on the header's
     own text plus the QSS's real `padding: 6px`/divider chrome —
     `size_action_column` now always includes it in the candidate max
     alongside the widest real widget, and `apply_table_defaults`
     applies the same floor to EVERY column at construction (C2.3's
     shared invariant — no column may start narrower than its own
     header needs). Screenshot-confirmed: Review's three empty tables
     all now show "Actions" in full. **A full-suite stall caught live
     via a real `lldb` attach while re-running the suite was reported
     here as an unresolved open finding — item 105 (C3) root-caused and
     fixed it for real; see there, not here.**
     [HISTORY §104](docs/HISTORY.md#104)

104. **C3 — the Dashboard's own progress bar was a second, untouched
     bug site — done.** B4/item 96 only fixed `_build_progress_widget`
     (the Downloads page); `_render_track_statuses` builds its OWN bare
     `QProgressBar` for the Dashboard track table, handed directly to
     `setCellWidget` — the identical top-clamped-bar bug in a function
     that fix never reached. Now wrapped through the SAME
     `_wrap_progress_bar` container (no ETA label — deliberate, the
     Dashboard doesn't track per-track ETA). Swept every real
     `setCellWidget(` call site in `main_window.py`/`settings_window.py`
     (15 matched lines; 2 are comments, 13 real calls) — confirmed the
     only other bare-widget cases are two harmless empty `QWidget()`
     placeholders and one bare `QRadioButton` (Duplicates' Keep column)
     that live-rendering confirmed is NOT visually broken (a radio's
     indicator paints centered regardless of cell stretch, unlike
     QPushButton/QProgressBar). New structural regression test walks
     every real table and fails on any bare `QProgressBar`/`QPushButton`
     cell widget anywhere in the app. **Also root-caused and fixed
     item 104's own "open finding":** a real, DETERMINISTIC (not
     intermittent — the earlier "self-resolves" read was from giving up
     a wait too early) full-suite stall. Three tests
     (`test_replace_all_upgrades_button_calls_batch_with_every_
     request_id` + two `test_resolve_all_duplicates_*` siblings) waited
     only for a bulk action's SERVICE call to register, not for its
     `on_finished` handler's own `QMessageBox.information()` — which
     can still be queued, unmocked, when the test returns, popping a
     real blocking modal during a LATER test with nothing to click
     under the offscreen QPA. Standing rule now: **any test that clicks
     a bulk action's confirm button must mock `QMessageBox.information`
     even when not asserting on it.** Full suite: 1060 passed, 1
     skipped, in 69.11s (no stall) — was inflated by real stall minutes
     before this fix. [HISTORY §105](docs/HISTORY.md#105)

106. **C4 — wordmark: brows over the real "ee" — done, screenshot-
     confirmed.** The eye-replacement idea (swapping the two `e`s for
     eyes) was tried and abandoned last round — an eye is ~3:1 where a
     lowercase `e` is 1:1, so the pair triple-widened and broke the
     word into "S…ker." What works instead: `packaging/icons/
     seeker_brows.svg` (two strokes traced from the real app icon,
     already committed) composited above the real "ee." New
     `ui/main_window.py::_Wordmark(QWidget)` replaces the plain
     `QLabel("Seeker")`, drawing its own text at 20px bold (up from
     16px) then compositing the brows via a SINGLE `QFontMetrics` call
     — `horizontalAdvance("S")` for the left edge,
     `horizontalAdvance("See") - horizontalAdvance("S")` for the width
     — so the brow position survives any font/size change with no
     hardcoded offset. `QSvgRenderer` has no `currentColor`, so the SVG
     renders to a `QPixmap` once at construction and is tinted via
     `QPainter` `CompositionMode_SourceIn` (`ACCENT`) — the same
     template treatment `_resolve_tray_icon_path`'s asset gets natively
     from AppKit, so one asset serves any future palette (C5 needs no
     second one). Degrades to plain text with no brows if the asset is
     missing (tested). `packaging/icons/` already ships wholesale in
     `seeker.spec` — confirmed, not assumed, no spec change needed.
     [HISTORY §106](docs/HISTORY.md#106)

107. **C5 — light and dark themes, with system-follow — done, real
     screenshot-verified across every real page in both themes.**
     `theme.py`'s module-level `STYLESHEET` f-string is now a real
     runtime-switchable architecture: frozen `Palette` dataclass
     (`DARK`/`LIGHT`), `build_stylesheet(palette)`/`build_qpalette
     (palette)`, `apply_theme(app, mode)`. The ~57 existing
     `theme.TOKEN` call sites elsewhere needed no changes — they read
     bare module-level names, reassigned on every switch by
     `_set_module_tokens()`. The 10 real per-widget `setStyleSheet()`
     calls (not the 12 the brief estimated) all converted to
     objectName/property + global-stylesheet rules (`InlineNotice` now
     uses `theme.set_variant()`, same mechanism as button variants) —
     none need `MainWindow.on_theme_changed()` code; only 3 genuinely
     baked-color sites do (the wordmark's tint + text, one Dashboard
     status color, confirmed self-healing via the 2s poll).
     `MainWindow._apply_theme_mode()` is the one entry point every
     switch routes through (sidebar toggle, Settings' new "Appearance"
     radios, the OS's own `colorSchemeChanged` — subscribed only while
     `mode == "system"`, torn down in `cleanup_before_quit`). Persisted
     via new `SeekerConfig.theme_mode` (guarded default). Toggle is a
     hand-drawn sun/moon/split-circle (`QPainter`, no assets) — a
     logo-derived glyph was tried and rejected (an isolated eye reads
     as a flat sliver, no identity). **Two real contrast bugs found via
     an actual screenshot, not the brief's own scope:** (1) the
     progress-bar percentage text (`TEXT_MUTED`) was measured at
     1.26:1 against `ACCENT` in light — a real crop showed it nearly
     invisible — fixed by switching to `TEXT` (clears 3:1 against both
     backgrounds it sits on). (2) `QPushButton[variant="primary"]`'s
     `color: {TEXT}` put near-black text on a purple button in light —
     fixed with a new `ON_ACCENT` token (white in both palettes). Also
     corrected the brief's own claimed DARK-accent-on-white contrast
     (2.9:1 claimed, 4.35:1 real, verified against textbook WCAG
     reference pairs). [HISTORY §107](docs/HISTORY.md#107)

108. **C6 — SoundCloud as a second source — deliberately deferred, not
     started.** Two real blockers found researching this, both
     disqualifying under this project's own standing principles: (1)
     registering a SoundCloud API app requires a paid Artist Pro
     subscription — with no account to test against, nothing here
     could be verified against real behavior, which this project
     treats as disqualifying rather than a detail. (2) SoundCloud
     treats every client as confidential and requires a `client_secret`
     even for a native app (unlike Spotify, where Seeker deliberately
     uses PKCE with no secret) — a distributed `.dmg` can't hold a
     secret safely, and a proxy server violates this project's
     "prefer solutions that run locally" principle. **If ever picked
     up:** the only architecture consistent with this project's
     principles is bring-your-own-credentials (the user registers
     their own app, pastes `client_id`+`client_secret` into Settings,
     same shape as the existing Spotify client ID field) — and the
     agreed UI is a source toggle at the top-right of the Dashboard,
     Spotify green vs. SoundCloud orange. No code, no schema, no stubs
     written for this.

109. **Fix D2 (round 6) — the theme toggle changed the icon but not the
     palette — done.** `_apply_theme_mode` used to call
     `theme.apply_theme()` (ending in `setColorScheme()`, which emits
     `colorSchemeChanged`) BEFORE updating `self._theme_mode`/syncing
     the system-scheme subscription — while in `"system"` mode, an
     explicit click's own `setColorScheme()` re-entered the still-
     connected handler mid-call, which silently reapplied the SYSTEM
     palette over the one being set; only the mode string/icon (set
     after) survived. Fixed by reordering (mode -> subscription ->
     apply -> persist -> toggle/settings) plus an `_applying_theme`
     re-entrancy guard. **Confirmed empirically: the offscreen QPA
     platform this whole suite runs under never actually emits
     `colorSchemeChanged` from `setColorScheme` at all** — the real
     re-entrancy path can't be forced through the real signal in a
     headless test; new tests exercise the fix directly (the applied
     stylesheet itself, plus the guard via a simulated synchronous
     signal-during-apply). [HISTORY §109](docs/HISTORY.md#109)
110. **Fix D3 (round 6) — the C2.3 header-label floor was pinning
     Stretch/ResizeToContents columns — done, but NOT confirmed to
     reproduce the reported dead-space bug in this sandboxed session.**
     `apply_table_defaults`'s floor loop ran at construction, before a
     caller ever assigns its real resize modes, and called
     `resizeSection()` on every column unconditionally — fighting
     `Stretch`/`ResizeToContents` columns once assigned. Split into
     `apply_table_defaults` (chrome only) + new
     `apply_column_floors(table)` (floor, scoped to
     `Interactive`/`Fixed` columns only, called AFTER resize modes are
     set) — audited onto all 11 tables. **Honest result:** across every
     scenario tried (normal render, pre-show render, live resize,
     with/without the old loop), `sum(sectionSize)` already matched the
     real viewport width in this offscreen harness both before and
     after — the new D3.5 regression test does not discriminate old
     vs. new code here. Kept anyway: the restructuring is correct on
     its own terms regardless of reproduction. Real-desktop screenshots
     of Search/Duplicates are the way to actually confirm this.
     [HISTORY §110](docs/HISTORY.md#110)
111. **Fix D1 (round 6) — wordmark clipped at the bottom, only the left
     brow visible — done, two independent bugs.** `sizeHint()` measured
     height with `boundingRect()` (ink, no descender) while
     `paintEvent()` positions the baseline at `ascent()` with no
     `descent()` reserved — fixed to reserve real font metrics
     (`ascent()+descent()`) and `horizontalAdvance()` for width. The
     brow pixmap's `drawPixmap` source rect used raw DEVICE-pixel
     width/height instead of `deviceIndependentSize()` — at a real 2x
     DPR this makes the source rect twice the actual image, so only the
     left brow (top-left quadrant) ever painted; fixed and extracted
     into a `@staticmethod _brow_source_rect()` for direct unit testing
     with a synthetic 2x pixmap. **Standing gotcha, third occurrence
     this project (see item 102/HISTORY §107):** this session's own
     real devicePixelRatio is 1.0, where device and device-independent
     pixels are numerically identical — a dpr-scaling bug like this
     literally cannot be forced to reproduce through a real paint+grab
     round trip here; test it with a synthetic pixmap instead. Also
     fixed the construction-time dpr fallback (2.0 -> 1.0) and added a
     `changeEvent` handler that re-renders on a real
     `DevicePixelRatioChange`. [HISTORY §111](docs/HISTORY.md#111)
112. **Fix D5 (round 6) — a menu bar left-click both opened the context
     menu and the window on macOS — done.** `_on_tray_icon_activated`
     connected `Trigger` unconditionally, guarded only by a comment
     claiming "macOS routes a left-click... straight to its context
     menu already (Trigger never fires there...)" — asserted with no
     citation and never checked; a real user's report on a real Mac
     (PySide6 6.11) proved it false. Fixed by skipping `Trigger`
     outright on `sys.platform == "darwin"`; Windows/Linux unchanged.
     **New standing convention (added to this file's Conventions
     section): a comment asserting platform/framework behavior must
     cite a real observation or say UNVERIFIED plainly** — this is the
     second time an unmarked confident claim like this turned out wrong
     (round 5's C1 was the CSS-invalid `:last-child` QSS selector).
     Swept `ui/` for similar comments per the brief's instruction (mark,
     don't fix): one real hit, `theme.py`'s C5.5 docstring claiming
     `setColorScheme()` changes the native macOS title bar — never
     actually checked on a real Mac — now marked UNVERIFIED.
113. **Fix D4 (round 6) — closing a fullscreen window left a black
     macOS Space behind — done, with a real Qt race found and fixed
     along the way.** `closeEvent` used to `hide()` a still-fullscreen
     window directly; a fullscreen window owns its own Space, which
     stays with nothing in it until the window actually leaves
     fullscreen — never triggered by `hide()` alone. Fixed to leave
     fullscreen first (`showNormal()`), deferring the real hide to
     `changeEvent`'s `WindowStateChange`. **Real race found live, not
     guessed:** calling `hide()` SYNCHRONOUSLY from inside that same
     `WindowStateChange` handling does not stick — reproduced 100%
     directly, 0% after deferring via `QTimer.singleShot(0, ...)`,
     confirmed empirically in an isolated repro before touching the
     real class. Restores the pre-fullscreen geometry on reopen,
     captured BEFORE requesting the exit (a second real, live-confirmed
     bug: reading `normalGeometry()` back from inside the deferred
     post-exit callback is itself unreliable — momentarily stale while
     the platform window settles — even though the same call from
     outside that callback already reports correctly). Checked all four
     close/quit paths per the brief's own D4.3 ask: `⌘Q`/tray Quit goes
     straight to `QApplication.quit()`, never through `closeEvent` at
     all (confirmed via its own existing docstring) — structurally
     immune regardless of fullscreen state, new test added; `⌘W` and
     the red button both ultimately call `self.close()`, the same
     `closeEvent` this item fixes. [HISTORY §113](docs/HISTORY.md#113)

114. **Round 7 (E1-E4) — fullscreen close reversed again, seven empty
     tables given real column layouts, a stylesheet cascade bug fixed,
     wordmark deleted.** **E1:** D4's own fix (item 113) only ever
     worked under offscreen QPA, which has no macOS Space/transition;
     reversed to NOT intercept `closeEvent` at all while fullscreen —
     `super().closeEvent()` runs directly on the still-fullscreen
     window, trusting AppKit's own close-while-fullscreen handling.
     **Real conflict found live, not guessed:** `WA_DeleteOnClose`
     (item 32, set for test hygiene, dormant in production since every
     OTHER close path always calls `event.ignore()` first) would have
     let Qt schedule this window's real C++ object for deletion the
     instant its close was finally allowed to complete — breaking
     "reopen from the tray" permanently the first time a user closed
     from fullscreen. **Corrected after review — cleared in
     `_build_tray_icon()`, once, the moment a real tray icon exists, not
     inside the fullscreen close branch itself:** the actual invariant
     ("a window with a live tray icon to reopen from must never be
     deleted on close") belongs where that invariant starts being true,
     so any future close path reaching this point with a tray present
     is covered automatically, not just the one branch that happened to
     need it first. **E1.4's own safety net went through two rounds of
     review, not one.** Round 1: the first version probed
     `self.isVisible()`, Qt's own bookkeeping, set synchronously by
     `hide()` itself; it could never disagree with the call that just
     ran (confirmed dead, no test had caught it), and was exactly the
     wrong witness besides — Qt's bookkeeping is what lied in the
     original bug. Rewritten to probe the real platform window
     (`windowHandle().isExposed()`, via a separately-mockable
     `_is_exposed_at_platform_level()`) on a delayed timer
     (`_HIDE_TO_TRAY_VERIFY_DELAY_MS = 400`, untuned). **Round 2 found
     that fix had two real races of its own:** (a) the delayed check had
     no way to know a legitimate reopen (`_on_tray_open_seeker`, a
     single tray-menu click) had happened in the meantime — it would see
     the platform window exposed (correctly, the user just reopened it),
     conclude the ORIGINAL hide "didn't take," and hide the window right
     back out from under the user with no explanation; fixed with a
     monotonic `_hide_request_id`, bumped by both a new hide attempt and
     `_on_tray_open_seeker`, captured at schedule time and re-checked
     when the timer fires — a stale check is now a guaranteed no-op. (b)
     the check's own "retry" (calling `hide()` again on disagreement) was
     ARMED on the fullscreen-close path too, where a check landing mid-
     animation would see the platform window still genuinely exposed
     (the transition just hasn't finished) and call `hide()` again mid-
     transition — the exact operation that produced round 6's bug,
     reintroduced by the safety net meant to catch it. Fixed two ways at
     once: the fullscreen branch no longer arms any verification at all
     (nothing is hidden BY US there — AppKit's own animation does it,
     asynchronously; `_hidden_to_tray = True` is set directly from the
     close itself), and the ordinary-hide check's own corrective action
     was dropped entirely — report-only now (log and leave
     `_hidden_to_tray` False), the strictly safer failure mode. Both
     races covered by real tests
     (`test_stale_hide_verification_does_not_rehide_a_reopened_window`,
     `test_fullscreen_close_never_arms_hide_verification`). The
     tray-hide notice (previously duplicated verbatim across the
     fullscreen branch and the ordinary hide path) is now one
     `_show_tray_hide_notice_once()`. Real desktop click-through
     (E1.1/E1.5) still outstanding — cannot be exercised under offscreen
     QPA; left for the user. **E2:** seven tables
     (`search_results_table`/`duplicates_table`/`track_table`/three
     review tables/`sharing_locations_table`) only set resize modes
     inside a render method that never runs while empty. Each gained a
     `_configure_*_columns()` (no args) called at construction from
     `_build_*` AND at the top of the existing `_size_*_columns`; the
     sweep test's own `has_a_stretch_column` skip (this round's own
     standing-convention violation, now fixed) was dropped so the
     invariant applies to every visible table unconditionally, plus a
     new structural test asserting a Stretch column/stretchLastSection
     immediately after construction. **E3:** `make_card`'s
     `inner.setStyleSheet("border: none; border-radius: 0px;")` had no
     selector — Qt parses that as a universal `* {...}` rule, silently
     stripping border/radius off every descendant widget BOX (found
     live: a determinate `QProgressBar`'s track sampled as flat
     `BG_SURFACE_2` with the rule in place, real `BORDER` with it
     removed). Fixed via `objectName("cardInner")` + a scoped
     `#cardInner` stylesheet rule; two more of the same shape
     (`cell_widget`'s container, `_ThemeToggleButton`) converted the
     same way even though neither was ever observed to cause harm, plus
     a new AST-based sweep test asserting no `setStyleSheet()` call
     anywhere in `ui/` is selector-less. New `PROGRESS_BAR_HEIGHT`/
     `PROGRESS_BAR_RADIUS` tokens make the track and fill the same pill
     shape, derived (never a literal) so they can't drift apart.
     **E4:** the custom-painted `_Wordmark` widget (items C4/D1) is
     deleted outright — replaced with a plain `QLabel#wordmark` styled
     through `build_stylesheet`, which reserves its own font ascent/
     descent internally and can't exhibit D1's clipping bug class at
     all; `retint()`/`on_theme_changed()`'s wordmark call and the brow
     SVG loading code are gone. `packaging/icons/seeker_brows.svg`
     stays committed, unreferenced, per the brief's own instruction.
     Full suite green: 1098 passed, 1 skipped (mypy --strict clean).
     [HISTORY §114](docs/HISTORY.md#114)

115. **Round 8 Phase 1 — toolchain: explicit ruff config, pytest
     config, CI — done.** `[tool.ruff]` in `pyproject.toml` makes
     `select` explicit rather than inherited (ruff 0.16.0 widened its
     own default from 59 to 413 rules mid-minor-version — an
     unconfigured linter can no longer be trusted to mean the same
     thing across a `ruff` upgrade). `ruff`/`mypy` are now
     version-bounded (`<0.17`/`<3`) since both are CI gate tools. `ruff
     format` deliberately NOT adopted (see Conventions above). New
     `[tool.pytest.ini_options]` (`--strict-markers`, `seeker.*`-scoped
     deprecation-to-error). New `.github/workflows/ci.yml`
     (macos-latest, `QT_QPA_PLATFORM=offscreen`) — verified the full
     1098-test suite (all 292 Qt widget tests included) passes headless
     with no test needing a real display, so nothing is deselected.
     `line-length = 79` applied via a purpose-built, verified rewrap
     script (not `ruff format`, which uses a 4-space hang this
     project's own 8-space convention doesn't match) — fixed 175 of the
     real 341 violations (the brief's own 106-line estimate was `src/`
     only on an older ruff); 166 remain, left for manual follow-up, not
     claimed done. One `S608` false positive given a scoped `# noqa`
     with a real justification, not a blanket suppression. [HISTORY
     §115](docs/HISTORY.md#115)

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

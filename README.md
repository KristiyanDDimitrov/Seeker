# seeker

A personal DJ music library management assistant. `seeker` keeps a local
cache of your Spotify playlists, matches those tracks against the files you
already have on disk, and — for whatever's missing — searches SoulSeek
(via a self-hosted [`slskd`](https://github.com/slskd/slskd) daemon) to
find and download the highest-quality available copy of each track.

## Why this exists

Building a DJ library by hand from Spotify playlists is repetitive and
easy to get subtly wrong: which tracks are already on disk? which ones
are actually the same track under a slightly different filename? which
download candidate is genuinely the best quality, not just the first
result? `seeker` automates that pipeline end to end — sync, match, search,
download, tag — while keeping every step auditable and reversible.

It's also a portfolio project, so code quality, structure, and test
coverage are treated as first-class goals here, not just "make it work."

## How it works

```
Spotify  ──sync──>  local SQLite cache  ──match──>  scanned local library
                                              │
                                              └─unmatched──> SoulSeek search
                                                                   │
                                                            best-candidate
                                                             download via slskd
                                                                   │
                                                          move into library +
                                                            tag with metadata
```

1. **Sync** — Spotify playlists and their tracks are pulled via the Web
   API and cached locally, so day-to-day commands don't re-hit Spotify's
   rate-limited API.
2. **Scan** — registered library locations (folders on disk) are scanned
   for audio files, reading tags for artist/title/duration.
3. **Match** — each cached Spotify track is fuzzy-matched (via
   [`rapidfuzz`](https://github.com/rapidfuzz/RapidFuzz)) against scanned
   local files and classified `auto` / `needs_review` / unmatched.
4. **Search + download** — tracks with no local match are searched on
   SoulSeek; candidates are filtered and ranked by format/bitrate/queue
   depth, and the best practical candidate (plus, if a meaningfully
   better one exists but isn't practical right now, a parallel "upgrade"
   candidate) is downloaded through `slskd`.
5. **Review + tag** — completed downloads are moved into the playlist's
   configured library location; pending quality upgrades are confirmed
   interactively before replacing an already-downloaded file; matched
   tracks can be tagged with Spotify's canonical artist/title/album/art,
   and optionally analyzed locally for BPM and (Camelot-notation) musical
   key.

## Architecture

```
CLI (cli.py)
  -> Application / services (application.py, spotify/sync_service.py, ...)
    -> Repositories (database/repositories/*)
      -> Database (database/connection.py, database/schema.py)
```

This layering is a strict, enforced rule, not just a convention: **CLI
code never imports or calls a repository directly.** Every CLI handler
goes through `Application` (or a service it exposes). The reason is
mundane but important for a project like this — the CLI is the thing
that changes most often (new flags, new output formatting), and the
repository layer is the thing where correctness matters most (raw SQL,
transactions, foreign keys). Keeping a service layer between them means
a CLI change can never accidentally skip validation, skip a transaction
boundary, or run a query that bypasses the invariants the repositories
maintain — and it means the service logic is testable without an
argparse harness in the way.

Data access is raw SQL via a repository-per-table pattern (see
`database/schema.py` and `database/repositories/*.py`), not an ORM —
a deliberate choice to keep the SQL visible and the schema (including
its foreign-key constraints, enforced for real via
`PRAGMA foreign_keys = ON`) the actual source of truth for what states
the data can be in.

### Project layout

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
│   ├── client.py           # raw Spotify Web API calls
│   ├── sync.py, sync_service.py
├── soulseek/
│   ├── client.py            # slskd REST wrapper — search, request_download,
│   │                        #   get_download_status
│   ├── quality.py           # candidate filtering + best-file selection
│   └── download_service.py  # playlist destinations, download_playlist,
│                             #   poll_downloads (status + file move)
├── library/
│   ├── scanner.py, matcher.py, service.py, metadata_service.py
├── models/{playlist,track,track_match,local_file,library_location,
│           soulseek_file,download_request}.py
├── audio_formats.py          # AUDIO_EXTENSIONS, shared by scanner + quality
├── metadata.py                # mutagen tag read/write, per audio format
├── audio_analysis.py          # BPM + Camelot key detection (librosa)
├── config.py
├── application.py
├── cli.py
└── main.py
```

## Setup

### 1. Install dependencies

This project uses [`uv`](https://docs.astral.sh/uv/) for environment and
dependency management — not `pip`/`poetry`.

```
uv sync
```

### 2. Register a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   and create an app.
2. Add a Redirect URI matching what you'll set as `SPOTIFY_REDIRECT_URI`
   below (e.g. `http://127.0.0.1:8888/callback` — must match exactly,
   including the port).
3. Note the app's Client ID (no client secret is needed — `seeker`
   authorizes via PKCE).

### 3. Configure environment variables

Create a `.env` file in the project root:

```
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback

# Only required once you use SoulSeek search/download commands.
SLSKD_BASE_URL=http://localhost:5030
SLSKD_API_KEY=your-slskd-api-key

# Host filesystem path to slskd's own configured download directory
# (see step 4) — required by `seeker downloads status` to move
# completed files into your library.
SLSKD_DOWNLOAD_DIR=./slskd-data/downloads
```

`SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI` are required at import time;
the `SLSKD_*` variables are only enforced when a command actually needs
them, so sync/scan/match/check work fine without `slskd` running.

### 4. Run slskd (SoulSeek daemon)

`seeker` talks to SoulSeek through [`slskd`](https://github.com/slskd/slskd),
a self-hosted daemon with a REST API, rather than implementing the raw
protocol itself. A `docker-compose.yml` is included:

```
docker compose up -d
```

Then open `http://localhost:5030`, finish slskd's own setup (SoulSeek
account credentials, an API key for `SLSKD_API_KEY` above, and which
local folders it shares), and confirm its configured download directory
matches `SLSKD_DOWNLOAD_DIR`.

**Note on destinations:** slskd's batch-download API only accepts a
destination *relative to slskd's own download root* — it can't target an
arbitrary path on your library drive directly. `seeker` works around
this itself: completed downloads land in slskd's download directory
first, and `seeker downloads status` locates the finished file there and
moves it into the destination configured for that playlist (see
`seeker playlists set-destination` below).

## Commands

```
uv run seeker <command>
```

| Command | What it does |
|---|---|
| `sync` | Pull all Spotify playlists (metadata only — no tracks) into the local cache. |
| `sync-tracks <playlist>` | Pull the full track list for one playlist. |
| `playlists` | List locally cached playlists. |
| `playlists set-destination <playlist> <location> [subfolder]` | Set where a playlist's downloads should be moved to once complete. |
| `library add <name> <path>` | Register a library location (a folder on disk). |
| `library list` | List registered locations and whether they're currently reachable. |
| `library remove <name>` | Unregister a location. |
| `library scan` | Scan all registered locations for audio files. |
| `library match` | Fuzzy-match cached Spotify tracks against scanned local files. |
| `library tag <playlist> [--analyze-audio] [--bpm-range MIN MAX]` | Write Spotify's artist/title/album/art onto every auto-matched track's local file; `--analyze-audio` also detects and writes BPM/Camelot key. |
| `check [--verbose]` | Report the auto-matched / needs-review / unmatched split for cached tracks. |
| `download <playlist>` | Search SoulSeek and request downloads for a playlist's still-unmatched tracks. |
| `downloads status` | Poll in-flight SoulSeek transfers and move completed ones into place. Non-interactive — safe to run from a scheduler. |
| `downloads review` | Interactively confirm or decline pending quality-upgrade replacements. |

Any command that takes a playlist name will offer to sync from Spotify if
the name isn't found locally and doesn't look like a typo of one you
already have (see `resolve_playlist_or_offer_sync` in `cli.py`).

## Design principles

A few things this codebase tries to hold to consistently, not just as
one-off decisions:

- **Transactional integrity.** Multi-step database writes happen inside
  a single `sqlite3` transaction via `Database.transaction()`, and
  foreign keys are enforced for real (`PRAGMA foreign_keys = ON`) so the
  schema's constraints — not just application code — prevent the
  database from ever holding a dangling reference.
- **One bad item must not abort a batch.** Every loop that processes
  multiple tracks or downloads (`download_playlist`, `poll_downloads`,
  `tag_tracks`, ...) wraps each item's work individually, so a single
  network blip, malformed API response, or missing file fails and is
  accounted for on its own, without silently skipping everything after
  it.
- **Verify against real data over trusting documentation.** Third-party
  API docs (Spotify, slskd) have repeatedly turned out to be wrong or
  incomplete about response shapes and behavior in ways that only showed
  up against live traffic — several fixes in this codebase's history
  exist specifically because a real run surfaced a mismatch. Where
  practical, tests and manual verification runs use real API responses
  and real files rather than only synthetic fixtures.
- **Never touch a file without confirmation when it matters.** Replacing
  an already-downloaded file with a higher-quality version is the one
  filesystem-destructive action in the pipeline, and it's the one place
  the CLI stops and asks — twice, once to confirm the replacement and
  once to confirm deleting the old file — rather than acting
  automatically.

## Running tests

```
uv run pytest              # full suite
uv run pytest --cov=seeker --cov-report=term-missing   # with coverage
uv run mypy --strict src/seeker
```

All external HTTP (Spotify, slskd) is mocked in tests — the suite never
makes real network calls. A handful of tests that exercise real audio
tag round-trips against files on an external drive are skipped
automatically when that drive isn't mounted.

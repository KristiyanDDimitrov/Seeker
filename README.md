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

## Two interfaces, one service layer

`seeker` ships both a CLI (`seeker`) and a desktop GUI (`seeker-ui`,
built with [PySide6](https://doc.qt.io/qtforpython/)) — they're two
presentation layers over the exact same `Application`/service code, not
two separate implementations. Anything the CLI can do, the GUI can do,
and vice versa; picking one over the other is purely a matter of
preference.

**`seeker-ui`** is the easier way to get started: an onboarding wizard
walks through connecting Spotify (PKCE authorization — no manual token
handling), registering a library location, and — optionally, skippable —
standing up `slskd` via Docker, collecting your SoulSeek credentials and
generating an API key for you rather than requiring you to hand-edit
`.env` or click through slskd's own web UI. Once onboarding is done (or
skipped for SoulSeek), a dashboard shows each playlist's tracks with
live status, a Downloads tab shows every in-flight transfer, a Review
tab handles confirming SoulSeek needs-review candidates and quality
upgrades, and a Settings screen (library locations, playlist
destinations, SoulSeek/Spotify connection management, and the
auto-match/needs-review classification thresholds) covers everything
you'd otherwise need `.env`/the CLI for.

```
uv run seeker-ui
```

**`seeker`** (the CLI) is the scriptable/scheduler-friendly path — see
[Commands](#commands) below — and still requires the manual `.env`
setup described under [Setup](#setup) if you never run the wizard.

## Architecture

```
Presentation layer (cli.py, ui/*)
  -> Application / services (application.py, spotify/sync_service.py, dashboard_service.py, ...)
    -> Repositories (database/repositories/*)
      -> Database (database/connection.py, database/schema.py)
```

This layering is a strict, enforced rule, not just a convention:
**presentation-layer code — CLI or GUI — never imports or calls a
repository directly.** Every CLI handler and every Qt widget goes
through `Application` (or a service it exposes). The reason is mundane
but important for a project like this — the presentation layer is the
thing that changes most often (new flags, new screens, new output
formatting), and the repository layer is the thing where correctness
matters most (raw SQL, transactions, foreign keys). Keeping a service
layer between them means a UI change can never accidentally skip
validation, skip a transaction boundary, or run a query that bypasses
the invariants the repositories maintain — and it means the service
logic is testable without an argparse harness or a Qt event loop in the
way.

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
├── ui/                        # the seeker-ui GUI (PySide6)
│   ├── main_window.py         # dashboard + Downloads/Review/tagging tabs
│   ├── wizard.py               # onboarding: Spotify, library, SoulSeek
│   ├── settings_window.py      # locations, destinations, connection, thresholds
│   ├── library_location_picker.py  # shared folder-picker (wizard + Settings)
│   └── workers.py              # QThreadPool worker wrapper every screen uses
├── models/{playlist,track,track_match,local_file,library_location,
│           soulseek_file,download_request,soulseek_review_candidate,
│           active_download,track_status,upgrade_review}.py
├── audio_formats.py          # AUDIO_EXTENSIONS, shared by scanner + quality
├── metadata.py                # mutagen tag read/write, per audio format
├── audio_analysis.py          # BPM + Camelot key detection (librosa)
├── dashboard_service.py       # playlist-scoped track status + global active downloads (used by ui/)
├── config_store.py            # SeekerConfig — the UI-editable settings store, config.json
├── docker_setup.py            # Docker/slskd detection, bring-up, health checks (wizard + Settings)
├── download_dedup.py          # shared "same real candidate" dedup rule (download service + dashboard)
├── config.py                  # .env-sourced fallback values (legacy/CLI-only path)
├── application.py
├── cli.py
├── main.py                    # `seeker` entry point
└── main_ui.py                 # `seeker-ui` entry point
```

## Setup

### 1. Install dependencies

This project uses [`uv`](https://docs.astral.sh/uv/) for environment and
dependency management — not `pip`/`poetry`.

```
uv sync
```

`seeker`'s SQLite cache lives in an OS-conventional per-user app-data
directory (via [`platformdirs`](https://github.com/tox-dev/platformdirs)),
not the project folder — e.g. `~/Library/Application Support/Seeker` on
macOS, `~/.local/share/Seeker` on Linux, `%LOCALAPPDATA%\Seeker` on
Windows. If a database from an older `.seeker/seeker.db` (relative to
wherever you ran `seeker` from) is found on first run, it's moved into
the new location automatically — nothing to do by hand.

### 2. Register a Spotify app

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   and create an app.
2. Add a Redirect URI: `http://127.0.0.1:8888/callback` (the wizard
   shows/copies this exact value for you; it must match exactly,
   including the port, whichever setup path you use below).
3. Note the app's Client ID (no client secret is needed — `seeker`
   authorizes via PKCE).

### 3. Finish setup — pick one

**Recommended: the onboarding wizard.** Run `uv run seeker-ui`. On first
launch it walks through connecting Spotify (paste the Client ID from
step 2; a real browser window opens for the PKCE authorization), then
registering a library location (a native folder picker), then —
optionally, skippable — standing up `slskd`: it starts the bundled
`docker-compose.yml` for you, collects your SoulSeek network
username/password, and generates a `SLSKD_API_KEY` itself, so there's no
`.env` file to hand-edit and no need to click through slskd's own web UI
at all. Everything it collects is written to a `config.json` in the same
per-user app-data directory as the database (see step 1) — not `.env` —
and can be changed later from the Settings screen (Connection tab:
re-authorize Spotify, update SoulSeek credentials, test the connection)
without touching either file by hand. The wizard is resumable — closing
and relaunching `seeker-ui` picks up wherever you left off.

**Manual (CLI-only, or if you'd rather hand-edit config)** — create a
`.env` file in the project root:

```
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback

# Only required once you use SoulSeek search/download commands.
SLSKD_BASE_URL=http://localhost:5030
SLSKD_API_KEY=your-slskd-api-key

# Host filesystem path to slskd's own configured download directory
# (see the next section) — required by `seeker downloads status` to
# move completed files into your library.
SLSKD_DOWNLOAD_DIR=./slskd-data/downloads
```

None of these are required just to launch `seeker`/`seeker-ui` —
`SPOTIFY_CLIENT_ID`/`SPOTIFY_REDIRECT_URI` are only enforced once
something actually needs Spotify auth (a real `sync`, or the wizard's
own connect step), and the `SLSKD_*` variables only once a command
needs SoulSeek, so `sync`/`scan`/`match`/`check` work fine with neither
set. A value already present in `config.json` (from the wizard, or
Settings) always wins over its `.env` counterpart — `.env` is purely a
fallback for values the config store doesn't have.

### 4. Run slskd (SoulSeek daemon) — only if you didn't use the wizard's SoulSeek step

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

The table below is the CLI reference. Most of it has a direct `seeker-ui`
equivalent: the Dashboard tab covers `sync`/`sync-tracks`/`scan`/`match`/
`download`/tagging for whichever playlist is selected; the Downloads tab
covers `downloads status`; the Review tab covers `downloads review` plus
confirming/rejecting SoulSeek needs-review candidates (`check`'s
"Needs review" section, with an action the CLI never had); and the
Settings screen covers `library add`/`list`/`remove`, `playlists
set-destination`, SoulSeek/Spotify connection management, and the
auto-match/needs-review thresholds (editable there; hardcoded constants
for the CLI).

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
  both interfaces stop and ask — twice, once to confirm the replacement
  and once to confirm deleting the old file (the CLI's `downloads
  review` prompts; the GUI's Review tab has a Replace/Decline button
  pair and a "Delete old file" checkbox) — rather than acting
  automatically. Writing tags onto a file, by contrast, is treated as
  non-destructive (it augments a file in place rather than replacing
  it) and runs with no confirmation in either interface.

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

UI tests use [`pytest-qt`](https://pytest-qt.readthedocs.io/) — real Qt
widgets, no display required (they run headless in CI the same way they
do locally). Consistent with the rest of the codebase's testing
philosophy: real service-layer logic (`DashboardService`, threshold
resolution, `config_store`, `download_dedup`, the connection-management
methods on `Application`) gets real, direct coverage; thin Qt glue
(widget construction, layout, button-click wiring already covered at
the level established across `ui/`) gets smoke-level coverage rather
than exhaustive testing of PySide6 itself.

## Building a standalone app

`seeker-ui` can be packaged as a self-contained desktop app (via
[PyInstaller](https://pyinstaller.org/)) that a user can double-click to
launch — no `uv`/Python install of their own required. This packages
the Python/Qt application only; **Docker is not bundled and isn't meant
to be** — the onboarding wizard's existing Docker detection/bring-up
flow is unchanged, and a real, separate Docker install is still how
`slskd` runs.

```
uv sync --group dev              # pulls in pyinstaller
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
```

Output lands in `dist/`: a one-folder build (`dist/Seeker/`) on every
platform, plus a real `.app` bundle (`dist/Seeker.app`) on macOS. Both
are self-contained — `docker-compose.yml` (the one non-Python resource
file this app needs at runtime, for the wizard/Settings' "bring up
slskd" flow) is bundled alongside the code and located via
`sys._MEIPASS` in a frozen build; `seeker/docker_setup.py::
compose_file_path()` is the one place that branches on `sys.frozen` —
everything else about a frozen run is identical to `uv run seeker-ui`.
One-folder (not one-file) is a deliberate, verified choice: `librosa`'s
`numba`-JIT'd inner loops cache to a stable on-disk location that a
one-folder build reuses across runs (confirmed live — a warm run was
~3x faster than a cold one); a one-file build re-extracts to a fresh
temp directory on every launch, so that cache never persists and every
run pays the cold-start cost (confirmed live — 15-20x slower, with no
warm-up benefit, and no actual single-file-distribution need this app
has).

**Platform support:**

| Platform | Status |
| --- | --- |
| macOS | Built and live-verified on this machine (see below) |
| Windows | Spec is written and cross-platform (only the macOS `.app` `BUNDLE()` step is platform-gated) — **not run on a real Windows machine**, no such environment available here |
| Linux | Same spec, same caveat — **not run on a real Linux machine** |

Don't treat the Windows/Linux rows as verified just because the same
`.spec` file covers them; they're the honest, written-but-unverified
state until someone runs `pyinstaller packaging/seeker.spec` for real
on those platforms.

**macOS live verification, done for real (2026-08-29):** built the
actual `.app`, launched it via `open dist/Seeker.app` (the same path a
user double-clicking it takes) against this machine's real, existing
production config/database. Confirmed real and non-fabricated: the
process stays alive well past Qt/Cocoa's typical fail-fast window (10+
seconds, steady ~180MB RSS, no crash report under
`~/Library/Logs/DiagnosticReports`); every real dependency — PySide6/Qt,
numpy, scipy, rapidfuzz — loaded its real compiled library into the
process (`lsof`); and the real macOS unified log
(`log show --predicate 'process == "Seeker"'`) shows a genuine AppKit
window-initialization sequence (light/dark `NSApp` appearance
resolution, the sequence Cocoa runs when actually preparing to render a
window) with zero Python tracebacks. **Genuinely NOT verified, a real
tooling gap in this environment, not skipped:** this session's shell
has no Screen Recording or Accessibility permission grant, so neither
`screencapture` nor `System Events` UI scripting could confirm what the
window actually rendered, and neither could drive a real click through
the wizard, Settings, or a sync/scan/match run. Someone with normal
desktop access to a built `.app` should still do that pass before
calling packaging fully done end-to-end — what's confirmed here is
"boots and runs cleanly with the real environment," not "every screen
was clicked through."

**Also confirmed:** the build only pulls in runtime dependencies — a
built app has zero `pytest`/`mypy`/`ruff` files anywhere in it (checked
directly, not assumed from PyInstaller's import-analysis behavior).

**Code signing / notarization is deliberately out of scope** — it
needs a paid Apple Developer account and credentials only the project
owner can provide. The build is unsigned; Gatekeeper will warn on
first launch on any machine other than the one that built it (expected
— not a bug to route around). The hook points for adding it later are
documented directly in `packaging/seeker.spec`: `codesign_identity=`/
`entitlements_file=` on the `EXE(...)` call, plus a real
`xcrun notarytool`/`stapler` pass against the built `.app` afterward.

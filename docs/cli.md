# The `seeker` command line

`seeker` is the scriptable front end: every command is a call into the
same services `seeker-ui` uses (see [architecture.md](architecture.md)).
Run it from a source checkout:

```
uv run seeker <command>
uv run seeker <command> --help
```

## Configuring without the wizard

`seeker-ui`'s onboarding wizard writes everything the CLI needs to
`config.json`. To use the CLI without ever opening the GUI, put the
same values in a `.env` file in the working directory (or any parent):

```
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback

# Only needed once you use SoulSeek commands.
SLSKD_BASE_URL=http://127.0.0.1:5030
SLSKD_API_KEY=your-slskd-api-key
# The host folder slskd downloads into; `downloads status` moves
# finished files out of it.
SLSKD_DOWNLOAD_DIR=./slskd-data/downloads
```

The Spotify app needs the redirect URI `http://127.0.0.1:8888/callback`,
exactly, and no client secret: Seeker authorizes with PKCE.

Nothing here is required to start: the Spotify values are checked when
something first needs Spotify, the `SLSKD_*` values when something first
needs SoulSeek, so `sync`-free commands such as `library scan` and
`check` work with neither. A value in `config.json` always wins over its
`.env` counterpart.

### Running slskd by hand

Seeker talks to SoulSeek through [`slskd`](https://github.com/slskd/slskd),
a self-hosted daemon with a REST API. The tracked `docker-compose.yml`
names no folders of its own; pass the data directory and the folder to
share (mounted read-only):

```
SLSKD_DATA_DIR=./slskd-data SLSKD_SHARE_PATH="$HOME/Music" docker compose up -d
```

Then open `http://127.0.0.1:5030`, finish slskd's own setup (your
SoulSeek login, an API key for `SLSKD_API_KEY`, what to share), and
check that its download directory matches `SLSKD_DOWNLOAD_DIR`. Set
`SLSKD_USERNAME` and `SLSKD_PASSWORD` for its web UI login rather than
keeping slskd's default.

- **The web UI is bound to this machine only**
  (`127.0.0.1:5030:5030` and `5031:5031`). Only the peer port, `50300`,
  is published on every interface, because the protocol needs it.
- **The app never runs or edits this tracked file.** It copies it once
  into its own data directory and runs that copy, under the same
  Compose project name, `seeker`, so both manage one `slskd` container.
  When Settings recreates a container started by hand, it keeps that
  container's data directory. Sharing edits only a container Seeker
  started from its own copy.
- **Finished files land in slskd's folder first.** slskd only accepts a
  destination inside its own download root, so `downloads status`
  finds each finished file there and moves it to the playlist's
  destination.

## Commands

| Command | What it does |
|---|---|
| `sync` | Pull all Spotify playlists (names and snapshots, no tracks) into the local cache. |
| `sync-tracks <playlist>` | Pull one playlist's tracks. |
| `playlists` | List cached playlists. |
| `playlists set-destination <playlist> <location> [subfolder]` | Set where a playlist's finished downloads are moved. |
| `library add <name> <path>` | Register a library location (a folder on disk). Refused inside, or around, an existing location. |
| `library list` | List locations and whether each is reachable now. |
| `library remove <name>` | Unregister a location: forget its indexed files and their matches, and clear any playlist or default destination pointing at it. Files on disk are untouched. |
| `library check` | List locations registered inside other locations (their files are indexed twice). |
| `library merge <name> <keep>` | Merge a location inside, or around, `<keep>` into it: matches, Review rejections and analysis move to the same files under `<keep>`, destinations follow the same folder, and files outside `<keep>` are forgotten. Both must be reachable. Files on disk are untouched. |
| `library scan [--match]` | Scan every location for audio files; `--match` runs a match pass straight after. |
| `library match` | Fuzzy-match cached Spotify tracks against scanned files. |
| `library tag <playlist> [--analyze-audio] [--bpm-range MIN MAX] [--force]` | Write Spotify's artist, title, album and cover art onto each auto-matched track's file. `--analyze-audio` also detects and writes BPM and Camelot key; `--bpm-range` corrects octave errors within an expected range; `--force` redoes tracks already tagged or analysed. |
| `library fix-art <playlist>` | Re-embed cover art only, for auto-matched files whose art is missing or differs from Spotify's. Narrower than `tag --force`. |
| `library rename <playlist> [--apply]` | Preview renaming auto-matched files to `Artist1, Artist2 - Title.ext`; `--apply` renames after a y/N confirmation. |
| `library fingerprint <location> [--force] [--folder PATH]` | Compute an audio fingerprint for each file in scope that lacks one. `--folder` (repeatable) limits it to folders within the location. |
| `library duplicates <location> [--folder PATH]` | Report duplicate files in scope by audio content (fingerprint first). Repeated `--folder`s are pooled. Read-only. |
| `check [playlist] [--verbose]` | Report the auto-matched, needs-review and unmatched split, for one playlist or all. `--verbose` lists each auto match with its score and file. |
| `review [playlist] [--confirm TRACK_ID \| --reject TRACK_ID]` | List needs-review local-file matches, or confirm or reject one. A rejected file is never suggested for that track again. |
| `download <playlist>` | Search SoulSeek for the playlist's unmatched tracks and request the best candidate for each. Uses the default destination when the playlist has none. |
| `search <artist> <title> [--download]` | Search SoulSeek for a track in no playlist. Lists results; `--download` requests the best one into the default destination's `Manual` subfolder. |
| `downloads status` | Poll transfers and move finished files into place. Never prompts: safe to run from a scheduler. |
| `downloads sweep` | Search SoulSeek again for every loaded playlist's missing tracks (Not found, or a request that failed or went unavailable) and request what turns up. Up to 50 searches a run, least recently searched first; no Spotify calls. Never prompts: safe to run from a scheduler. |
| `downloads cleanup [--delete]` | List the files left in slskd's download and incomplete folders that no unresolved request and no live transfer uses (anything written in the last 10 minutes is held back); `--delete` deletes them after one confirmation, keeping any that changed since the listing. Refuses a download folder that is not an slskd app directory's `downloads/`, and needs slskd running. |
| `downloads review [--all]` | Confirm or decline each finished upgrade; `--all` replaces every pending one after a single question about deleting the old files. |
| `sharing status` | Report what slskd shares, whether Seeker manages it, and each location's share state. |
| `history [--limit N]` | List recently downloaded and tagged tracks (default 50). |

Any command that takes a playlist name offers to sync from Spotify when
the name is not in the cache and is not a near-miss of one that is.

`history` is derived from the current `download_requests` and
`local_files` rows, with no log table of its own: an entry disappears
when the row behind it is removed (deleting a duplicate, for example).
Failed downloads are not listed there; `downloads status` and the
Downloads page show them, with their reason, until they are cleared.

## The CLI and the GUI

Almost every command has a `seeker-ui` screen over the same service
call:

| Commands | Screen |
|---|---|
| `sync`, `sync-tracks`, `library scan`, `library match`, `download`, `check` | Dashboard |
| `library tag`, `library fix-art`, `library rename` | Library |
| `search` | Search |
| `downloads status` | Downloads (and a 20-second background poll) |
| `downloads sweep` | Settings → General → Daily sweep runs it once a day, when turned on |
| `downloads cleanup` | Downloads → Clean up leftover files… |
| `review`, `downloads review` | Review, which also confirms or rejects SoulSeek needs-review candidates |
| `library fingerprint`, `library duplicates` | Duplicates, which can also delete the copies you don't keep |
| `sharing status` | Sharing, which can also add a location to the share |
| `history` | History |
| `library add`/`list`/`remove`/`check`/`merge`, `playlists set-destination` | Settings → Library |

Only the GUI has the app-wide default destination's editor, the match
thresholds' editor (the CLI reads the saved values), and the slskd
bring-up.

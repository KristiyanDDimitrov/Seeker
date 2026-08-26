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
CLI (cli.py)
  -> Application / services (application.py, spotify/sync_service.py)
    -> Repositories (database/repositories/*)
      -> Database (database/connection.py, database/schema.py)
```

Rule: CLI code must never import or call a repository directly. All CLI
handlers go through `Application` (or a service it exposes), the same way
`handle_sync` goes through `application.sync_service`. If a command needs
data, add/extend a method on the service layer rather than reaching past it.

## Current layout

```
src/seeker/
├── database/
│   ├── connection.py
│   ├── schema.py
│   └── repositories/{playlist,track}_repository.py
├── spotify/
│   ├── auth.py, auth_manager.py, token.py, token_store.py
│   ├── callback_server.py
│   ├── client.py          # raw Spotify Web API calls
│   ├── sync.py, sync_service.py
├── models/{playlist,track}.py
├── config.py
├── playlist_selector.py
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

- [ ] `cli.py::handle_playlists` currently instantiates `PlaylistRepository`
      directly instead of going through `Application` — violates the
      layering rule above, fix to match the `sync` command's pattern.
- [ ] `SpotifyClient._get` retry loop has no max-attempt ceiling on 429
      retries — add a bound so it can't retry forever.
- [ ] `check` command is a stub (`cli.py::run`) — should compare synced
      Spotify tracks against the local library/download state once that
      exists.
- [ ] No table yet for local files/downloads — needed before SoulSeek
      integration can track what's already downloaded vs. missing.
- [x] Fixed: `SpotifyClient.get_current_user_playlists` was reading
      `playlist["items"]["total"]` instead of `playlist["tracks"]["total"]`.
- [x] Fixed: `SpotifyClient.get_playlist_tracks` was reading
      `item.get("item")` instead of `item.get("track")`, and the endpoint
      path was corrected to `/playlists/{id}/tracks`.

## Roadmap (direction, not urgent)

1. ~~Confirm end-to-end `sync` works~~ — client bugs fixed; still blocked on
   Spotify dev quota resetting for the first real end-to-end run.
2. ~~Local library scanning~~ — done. `library_locations` +
   `local_files`, multi-location aware, per-location reachability
   handling, AppleDouble sidecar files filtered.
3. ~~Matching~~ — done. `matcher.py` classifies each track as
   auto-matched / needs-review / unmatched (`track_matches`, with a
   `score` column). Thresholds (auto ≥90, review 70–90) are untuned
   defaults — revisit once real match data exists.
4. **In progress**: SoulSeek integration via `slskd` (self-hosted, REST
   API) — see conventions above. Next steps: `SoulseekClient` (search
   only, synchronous httpx, mirroring `SpotifyClient`), verify against a
   real running instance before adding quality-ranking or download logic.
5. Quality-ranking logic for SoulSeek search results (format/bitrate
   preference) — design once real result data is seen.
6. Download orchestration — where downloads land on disk is still an open
   decision (a staging/inbox location reconciled by the next library scan
   is the leading idea, not yet confirmed) — and a `download_requests`-
   style table to track in-flight/failed downloads, so a crash mid-batch
   doesn't lose track of state, consistent with how sync/scan already
   handle partial failure.
7. `check` command already reports auto/needs-review/unmatched — a
   `review` command to confirm/reject needs-review matches is still
   outstanding.

Keep this file updated as decisions get made — treat it as the standing
brief, not a changelog of everything that happened.
# seeker — `spotify/` rules

Standing facts for Spotify and its OAuth flow, moved here from the root
`CLAUDE.md` so it stays short. Same rules as the root: present tense,
each fact linked to the HISTORY entry holding its investigation;
`docs/history/README.md` resolves any `§N`.

## Spotify / OAuth

- `SpotifyClient` takes a `TokenSource` (`str | Callable[[], str]`).
  On a 401 it calls an optional `force_refresh` and retries **exactly
  once**; a second 401 raises `SpotifyAuthenticationError`.
  Spotify rotates PKCE refresh tokens: two installs sharing a client
  ID can invalidate each other's. [§92](../../../docs/history/072-107.md#92)
- **One token refresh at a time per process:** `get_valid_token`
  refreshes under `auth_manager._TOKEN_LOCK` and re-reads the token
  inside it, or two refreshes spend the same rotating token and send
  the loser to the browser. [§146](../../../docs/history/121-150.md#146)
- Field names: playlist track entries come from `entry["item"]`, gated by
  `item["type"] == "track"` ([early
  fixes](../../../docs/history/early-fixes.md#spotify-field-name-and-endpoint-history-get_playlist_tracks));
  `get_current_user_playlists` reads `playlist["items"]["total"]`, never
  `["tracks"]["total"]` ([early
  fixes](../../../docs/history/early-fixes.md#spotify-field-name-history-get_current_user_playlists)).
- **A playlist's tracks are stale when `tracks_snapshot_id`** (the
  snapshot its cached tracks came from; NULL = never loaded) **differs
  from `snapshot_id`.** Only `sync_playlist_tracks` sets it.
  `refresh_playlists()` re-syncs stale *loaded* playlists only, to
  spare the API budget. The parser drops Spotify local files (no id);
  a repeated track keeps its first listing.
  [§141](../../../docs/history/121-150.md#141)
- `callback_server._LoopbackHTTPServer` overrides `server_bind()` to
  skip `HTTPServer`'s reverse-DNS `getfqdn()` between `bind()` and
  `listen()`; keep it. CI's callback timeouts stopped at the commit
  that added it (mechanism unexplained). [§136](../../../docs/history/121-150.md#136)
- The token cache path comes from `platformdirs`, never the cwd (a
  double-clicked `.app`'s cwd can be unwritable).
  [§43](../../../docs/history/032-046.md#43)

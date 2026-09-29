from dataclasses import dataclass

from seeker.models.track import Track


@dataclass(frozen=True)
class PlaylistItems:
    """A playlist's storable tracks, in Spotify's order.

    `local_files_skipped` counts Spotify "local file" entries: they
    have no Spotify id, so Seeker can never store or match them.
    """
    tracks: list[Track]
    local_files_skipped: int = 0


@dataclass(frozen=True)
class TrackSyncResult:
    tracks_saved: int
    local_files_skipped: int = 0
    # The same track listed more than once in one playlist is stored
    # once; this counts the extra listings dropped.
    duplicates_collapsed: int = 0
    art_urls_filled: int = 0


@dataclass(frozen=True)
class PlaylistRefreshResult:
    playlist_count: int
    # Loaded playlists whose tracks were re-synced because they changed
    # on Spotify. Never-loaded playlists are never loaded by a refresh.
    updated_playlist_names: list[str]
    local_files_skipped: int = 0

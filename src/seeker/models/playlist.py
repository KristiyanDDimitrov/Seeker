from dataclasses import dataclass


@dataclass
class Playlist:
    id: str
    name: str
    track_count: int
    snapshot_id: str | None = None
    download_location_id: int | None = None
    download_subfolder: str | None = None
    # The snapshot the cached tracks came from; None if never loaded.
    tracks_snapshot_id: str | None = None

    @property
    def tracks_are_stale(self) -> bool:
        """Loaded, and changed on Spotify since."""
        return (
            self.tracks_snapshot_id is not None
            and self.tracks_snapshot_id != self.snapshot_id
        )


@dataclass(frozen=True)
class PlaylistSummary:
    """A playlist as the Dashboard lists it. `track_count` is the
    cached tracks once loaded, else Spotify's count; `missing` (the
    tracks in `MISSING_STATES`) is None until the tracks are loaded."""
    playlist: Playlist
    track_count: int
    missing: int | None

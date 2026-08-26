import pytest

from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import PlaylistRepository
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.spotify.sync_service import SpotifySyncService


class StubSpotifyClient:
    def __init__(self, tracks: list[Track]):
        self._tracks = tracks

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        return self._tracks


def make_track(track_id: str) -> Track:
    return Track(
        id=track_id,
        title=f"Title {track_id}",
        artist="Artist",
        album="Album",
        duration_ms=1000,
    )


def test_sync_playlist_tracks_rolls_back_snapshot_id_on_mid_sync_failure(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    old_playlist = Playlist(
        id="playlist1",
        name="My Playlist",
        track_count=1,
        snapshot_id="old-snapshot",
    )

    with database.transaction() as connection:
        PlaylistRepository(database).save(old_playlist, connection)

    tracks = [make_track("track1"), make_track("track2")]
    spotify = StubSpotifyClient(tracks)
    sync_service = SpotifySyncService(spotify, database)

    original_save = sync_service.tracks.save
    calls = {"count": 0}

    def failing_save(track, connection):
        calls["count"] += 1

        if calls["count"] == 2:
            raise RuntimeError("simulated crash mid-sync")

        return original_save(track, connection)

    sync_service.tracks.save = failing_save

    new_playlist = Playlist(
        id="playlist1",
        name="My Playlist",
        track_count=2,
        snapshot_id="new-snapshot",
    )

    with pytest.raises(RuntimeError, match="simulated crash mid-sync"):
        sync_service.sync_playlist_tracks(new_playlist)

    with database.transaction() as connection:
        persisted = sync_service.playlists.get_by_id("playlist1", connection)
        remaining_tracks = connection.execute(
            "SELECT id FROM tracks"
        ).fetchall()
        remaining_playlist_tracks = connection.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ?",
            ("playlist1",),
        ).fetchall()

    assert persisted.snapshot_id == "old-snapshot"
    assert remaining_tracks == []
    assert remaining_playlist_tracks == []

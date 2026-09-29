import pytest

from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import PlaylistRepository
from seeker.models.playlist import Playlist
from seeker.models.spotify_sync import PlaylistItems
from seeker.models.track import Track
from seeker.spotify.sync_service import (
    PlaylistNotFoundError,
    SpotifySyncService,
    find_close_playlist_matches,
)


class StubSpotifyClient:
    def __init__(
        self,
        tracks: list[Track] | None = None,
        playlists: list[Playlist] | None = None,
        tracks_by_playlist: dict[str, list[Track]] | None = None,
    ):
        self._tracks = tracks or []
        self._playlists = playlists or []
        self._tracks_by_playlist = tracks_by_playlist or {}
        self.local_files_skipped = 0

    def get_current_user_playlists(self) -> list[Playlist]:
        return self._playlists

    def get_playlist_tracks(self, playlist_id: str) -> PlaylistItems:
        if self._tracks_by_playlist:
            return PlaylistItems(self._tracks_by_playlist.get(playlist_id, []))

        return PlaylistItems(self._tracks, self.local_files_skipped)


def make_track(track_id: str) -> Track:
    return Track(
        id=track_id,
        title=f"Title {track_id}",
        artist="Artist",
        album="Album",
        duration_ms=1000,
    )


def test_sync_playlist_tracks_rolls_back_snapshot_id_on_mid_sync_failure(
        tmp_path
):
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


def test_sync_playlists_never_creates_track_rows(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    spotify_playlists = [
        Playlist(
            id="playlist1",
            name="New Playlist",
            track_count=5,
            snapshot_id="snap-1",
        ),
    ]

    spotify = StubSpotifyClient(playlists=spotify_playlists)
    sync_service = SpotifySyncService(spotify, database)

    sync_service.sync_playlists()

    with database.transaction() as connection:
        tracks = connection.execute("SELECT id FROM tracks").fetchall()
        persisted = sync_service.playlists.get_by_id("playlist1", connection)

    assert tracks == []
    assert persisted is not None
    assert persisted.track_count == 5
    assert persisted.snapshot_id == "snap-1"


def test_sync_playlist_tracks_scopes_to_single_playlist(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    playlist_one = Playlist(
        id="playlist1", name="One", track_count=1, snapshot_id="s1"
    )
    playlist_two = Playlist(
        id="playlist2", name="Two", track_count=1, snapshot_id="s2"
    )

    with database.transaction() as connection:
        PlaylistRepository(database).save(playlist_one, connection)
        PlaylistRepository(database).save(playlist_two, connection)

    spotify = StubSpotifyClient(
        tracks_by_playlist={"playlist1": [make_track("track1")]},
    )
    sync_service = SpotifySyncService(spotify, database)

    target = sync_service.get_playlist_by_name("one")
    sync_service.sync_playlist_tracks(target)

    with database.transaction() as connection:
        playlist1_tracks = connection.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ?",
            ("playlist1",),
        ).fetchall()
        playlist2_tracks = connection.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ?",
            ("playlist2",),
        ).fetchall()

    assert [row["track_id"] for row in playlist1_tracks] == ["track1"]
    assert playlist2_tracks == []


def test_get_playlist_by_name_raises_with_suggestions_when_not_found(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    playlist = Playlist(
        id="playlist1", name="Deep House Essentials", track_count=1
    )

    with database.transaction() as connection:
        PlaylistRepository(database).save(playlist, connection)

    sync_service = SpotifySyncService(StubSpotifyClient(), database)

    with pytest.raises(PlaylistNotFoundError, match="Deep House Essentials"):
        sync_service.get_playlist_by_name("Deep House Essential")


def test_find_close_playlist_matches_rejects_short_string_false_positive():
    # Real bug, found live: difflib.SequenceMatcher scored "Test" vs
    # "sesh" at 0.5 (against a 0.5 cutoff) purely from short-string ratio
    # inflation, not genuine resemblance.
    assert find_close_playlist_matches("Test", ["sesh", "Chill", "Trap"]) == []


def test_find_close_playlist_matches_rejects_another_real_false_positive():
    # The other near-miss names surfaced against the same real "Test"
    # query during the same investigation.
    candidates = [
        "The Stage", "Treehouse", "Metal", "Faces", "The Most Hated",
    ]
    assert find_close_playlist_matches("Test", candidates) == []


def test_find_close_playlist_matches_catches_single_character_typo():
    matches = find_close_playlist_matches(
        "Afterlife Releasea", ["Afterlife Releases", "Chill"]
    )
    assert matches == ["Afterlife Releases"]


def test_sync_playlist_tracks_collapses_a_track_listed_twice(tmp_path):
    # Spotify lets a playlist hold the same track more than once; the
    # playlist_tracks primary key does not.
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    playlist = Playlist(
        id="playlist1", name="One", track_count=3, snapshot_id="s1"
    )
    spotify = StubSpotifyClient(
        [make_track("track1"), make_track("track2"), make_track("track1")]
    )
    sync_service = SpotifySyncService(spotify, database)

    result = sync_service.sync_playlist_tracks(playlist)

    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT track_id FROM playlist_tracks WHERE playlist_id = ?",
            ("playlist1",),
        ).fetchall()

    assert sorted(row["track_id"] for row in rows) == ["track1", "track2"]
    assert result.tracks_saved == 2
    assert result.duplicates_collapsed == 1


def test_sync_playlist_tracks_reports_skipped_local_files(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    playlist = Playlist(
        id="playlist1", name="One", track_count=3, snapshot_id="s1"
    )
    spotify = StubSpotifyClient([make_track("track1")])
    spotify.local_files_skipped = 2
    sync_service = SpotifySyncService(spotify, database)

    result = sync_service.sync_playlist_tracks(playlist)

    assert result.tracks_saved == 1
    assert result.local_files_skipped == 2
    assert result.duplicates_collapsed == 0


def _tracks_snapshot_id(database: Database, playlist_id: str) -> str | None:
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT tracks_snapshot_id FROM playlists WHERE id = ?",
            (playlist_id,),
        ).fetchone()

    return row["tracks_snapshot_id"]


def test_sync_playlist_tracks_records_the_snapshot_it_loaded(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    playlist = Playlist(
        id="playlist1", name="One", track_count=1, snapshot_id="s1"
    )
    sync_service = SpotifySyncService(
        StubSpotifyClient([make_track("track1")]), database,
    )

    sync_service.sync_playlist_tracks(playlist)

    assert _tracks_snapshot_id(database, "playlist1") == "s1"


def test_sync_playlist_tracks_leaves_tracks_snapshot_on_failure(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    playlist = Playlist(
        id="playlist1", name="One", track_count=1, snapshot_id="s1"
    )
    sync_service = SpotifySyncService(
        StubSpotifyClient([make_track("track1")]), database,
    )

    with database.transaction() as connection:
        sync_service.playlists.save(playlist, connection)

    def failing_replace(*args, **kwargs):
        raise RuntimeError("simulated crash")

    sync_service.tracks.replace_playlist_tracks = failing_replace

    with pytest.raises(RuntimeError):
        sync_service.sync_playlist_tracks(playlist)

    assert _tracks_snapshot_id(database, "playlist1") is None


def test_sync_playlists_keeps_the_loaded_tracks_snapshot(tmp_path):
    # Refreshing the playlist list records Spotify's new snapshot, but
    # the cached tracks still come from the old one.
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    loaded = Playlist(
        id="playlist1", name="One", track_count=1, snapshot_id="s1"
    )
    spotify = StubSpotifyClient(tracks=[make_track("track1")])
    sync_service = SpotifySyncService(spotify, database)
    sync_service.sync_playlist_tracks(loaded)

    spotify._playlists = [
        Playlist(id="playlist1", name="One", track_count=2, snapshot_id="s2")
    ]
    sync_service.sync_playlists()

    with database.transaction() as connection:
        row = connection.execute(
            "SELECT snapshot_id, tracks_snapshot_id FROM playlists"
        ).fetchone()

    assert tuple(row) == ("s2", "s1")

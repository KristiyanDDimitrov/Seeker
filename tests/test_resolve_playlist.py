import pytest

from seeker import cli
from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.models.playlist import Playlist
from seeker.spotify.sync_service import (
    PlaylistNotFoundError as SyncPlaylistNotFoundError,
    SpotifySyncService,
)


class StubSpotifyClient:
    def __init__(self, playlists: list[Playlist]):
        self._playlists = playlists

    def get_current_user_playlists(self) -> list[Playlist]:
        return self._playlists

    def get_playlist_tracks(self, playlist_id: str):
        return []


class FakeApplication:
    def __init__(self, sync_service: SpotifySyncService):
        self.sync_service = sync_service


def make_sync_service(
        tmp_path,
        spotify_playlists: list[Playlist],
) -> SpotifySyncService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return SpotifySyncService(StubSpotifyClient(spotify_playlists), database)


def test_resolve_playlist_found_locally_returns_immediately(
        tmp_path, monkeypatch,
):
    playlist = Playlist(
        id="p1", name="Deep House", track_count=1, snapshot_id="s1"
    )
    sync_service = make_sync_service(tmp_path, [])

    with sync_service.database.transaction() as connection:
        PlaylistRepository(sync_service.database).save(playlist, connection)

    def fail_if_called(prompt):
        raise AssertionError(
            "must not prompt or refresh when already found locally"
        )

    monkeypatch.setattr("builtins.input", fail_if_called)

    resolved = cli.resolve_playlist_or_offer_sync(
        "deep house", FakeApplication(sync_service)
    )

    assert resolved.id == "p1"


def test_resolve_playlist_offers_refresh_and_retries_when_found_after_sync(
        tmp_path, monkeypatch,
):
    # Not synced locally yet, but it does exist on "Spotify" — simulating
    # a newly created playlist.
    new_playlist = Playlist(
        id="p1", name="New Playlist", track_count=5, snapshot_id="snap1"
    )
    sync_service = make_sync_service(tmp_path, [new_playlist])

    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    resolved = cli.resolve_playlist_or_offer_sync(
        "New Playlist", FakeApplication(sync_service)
    )

    assert resolved.id == "p1"
    assert resolved.name == "New Playlist"


def test_resolve_playlist_declines_refresh_raises_original_not_found(
        tmp_path, monkeypatch,
):
    sync_service = make_sync_service(tmp_path, [])
    sync_calls = {"count": 0}

    original_sync_playlists = sync_service.sync_playlists

    def counting_sync_playlists():
        sync_calls["count"] += 1
        return original_sync_playlists()

    sync_service.sync_playlists = counting_sync_playlists

    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    with pytest.raises(SyncPlaylistNotFoundError):
        cli.resolve_playlist_or_offer_sync(
            "Nonexistent Playlist", FakeApplication(sync_service)
        )

    assert sync_calls["count"] == 0


def test_resolve_playlist_errors_after_real_refresh_when_truly_nonexistent(
        tmp_path, monkeypatch,
):
    # Nothing locally, and nothing on "Spotify" either — a genuinely
    # nonexistent playlist must still error, even after a real refresh.
    sync_service = make_sync_service(tmp_path, [])

    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    with pytest.raises(SyncPlaylistNotFoundError, match="even after"):
        cli.resolve_playlist_or_offer_sync(
            "Nonexistent Playlist", FakeApplication(sync_service)
        )


def test_resolve_playlist_does_not_offer_refresh_when_close_match_exists(
        tmp_path, monkeypatch,
):
    # A typo/stale name has a close match locally — a resync wouldn't
    # fix a typo, so no refresh should be offered at all.
    existing = Playlist(
        id="p1",
        name="Deep House Essentials",
        track_count=1,
        snapshot_id="s1",
    )
    sync_service = make_sync_service(tmp_path, [existing])

    with sync_service.database.transaction() as connection:
        PlaylistRepository(sync_service.database).save(existing, connection)

    def fail_if_called(prompt):
        raise AssertionError(
            "must not prompt for refresh when a close match exists"
        )

    monkeypatch.setattr("builtins.input", fail_if_called)

    with pytest.raises(SyncPlaylistNotFoundError, match="Did you mean"):
        cli.resolve_playlist_or_offer_sync(
            "Deep House Essential", FakeApplication(sync_service)
        )


def test_resolve_playlist_test_query_offers_refresh_not_sesh_suggestion(
        tmp_path, monkeypatch,
):
    # Regression test for the actual reported bug: "seeker sync-tracks
    # 'Test'" was silently taking the "Did you mean: sesh?" suggestion
    # branch (a difflib short-string false positive) instead of ever
    # offering a refresh. With "sesh" present locally alongside other
    # short/generic names, "Test" must now find zero close matches and
    # take the offer-refresh branch — confirmed here by asserting the
    # refresh prompt actually fires.
    local_playlists = [
        Playlist(id="p1", name="sesh", track_count=1, snapshot_id="s1"),
        Playlist(id="p2", name="Chill", track_count=1, snapshot_id="s2"),
        Playlist(id="p3", name="Trap", track_count=1, snapshot_id="s3"),
    ]
    sync_service = make_sync_service(tmp_path, [])

    with sync_service.database.transaction() as connection:
        for playlist in local_playlists:
            PlaylistRepository(sync_service.database).save(
                playlist, connection
            )

    prompted = {"called": False}

    def fake_input(prompt):
        prompted["called"] = True
        assert "Refresh from Spotify now?" in prompt
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    with pytest.raises(SyncPlaylistNotFoundError, match="found locally"):
        cli.resolve_playlist_or_offer_sync(
            "Test", FakeApplication(sync_service)
        )

    assert prompted["called"] is True

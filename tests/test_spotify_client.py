import httpx
import pytest

from seeker.spotify.client import SpotifyClient, SpotifyRateLimitedError


class FakeResponse:
    def __init__(self, data: dict):
        self._data = data
        self.status_code = 200
        self.headers = {}

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def test_get_current_user_playlists_reads_track_count_from_tracks_field(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        assert url == "https://api.spotify.com/v1/me/playlists"
        return FakeResponse(
            {
                "items": [
                    {
                        "id": "playlist1",
                        "name": "My Playlist",
                        "snapshot_id": "snap1",
                        "tracks": {"total": 42},
                    }
                ],
                "next": None,
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    playlists = SpotifyClient("token").get_current_user_playlists()

    assert len(playlists) == 1
    assert playlists[0].track_count == 42


def test_get_playlist_tracks_reads_track_field_from_correct_endpoint(monkeypatch):
    requested_urls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        requested_urls.append(url)
        return FakeResponse(
            {
                "items": [
                    {
                        "track": {
                            "id": "track1",
                            "name": "Song",
                            "artists": [{"name": "Artist"}],
                            "album": {"name": "Album"},
                            "duration_ms": 12345,
                        }
                    }
                ],
                "next": None,
            }
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    tracks = SpotifyClient("token").get_playlist_tracks("playlist1")

    assert requested_urls == ["https://api.spotify.com/v1/playlists/playlist1/tracks"]
    assert len(tracks) == 1
    assert tracks[0].id == "track1"
    assert tracks[0].title == "Song"


class FakeRateLimitedResponse:
    def __init__(self, retry_after: str | None, reason: str | None):
        self.status_code = 429
        self.headers = (
            {"Retry-After": retry_after}
            if retry_after is not None
            else {}
        )
        self._reason = reason

    def json(self):
        return {"error": {"reason": self._reason}}

    def raise_for_status(self):
        pass


def test_quota_exceeded_429_raises_with_formatted_duration(monkeypatch):
    retry_after_seconds = 3 * 3600 + 42 * 60

    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeRateLimitedResponse(
            retry_after=str(retry_after_seconds),
            reason="QUOTA_EXCEEDED",
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(SpotifyRateLimitedError) as exc_info:
        SpotifyClient("token").get_current_user_playlists()

    error = exc_info.value

    assert error.quota_exceeded is True
    assert error.retry_after_seconds == retry_after_seconds
    assert "3h 42m" in str(error)

from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore


def test_token_store_round_trips(tmp_path):
    store = TokenStore(tmp_path / "token.json")
    token = SpotifyToken(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=1234567890.0,
    )

    store.save(token)

    assert store.load() == token


def test_token_store_load_returns_none_when_file_missing(tmp_path):
    store = TokenStore(tmp_path / "does_not_exist.json")

    assert store.load() is None

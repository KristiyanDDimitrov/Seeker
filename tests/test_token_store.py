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


def test_token_store_clear_removes_existing_file(tmp_path):
    store = TokenStore(tmp_path / "token.json")
    store.save(
        SpotifyToken(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=1234567890.0,
        )
    )

    store.clear()

    assert store.load() is None
    assert not (tmp_path / "token.json").exists()


def test_token_store_clear_is_a_no_op_when_file_never_existed(tmp_path):
    # Settings' "Re-authorize" (Step 8 §3) calls clear() unconditionally
    # via force_reauthorize — a first-time connect with no token file
    # yet must not raise.
    store = TokenStore(tmp_path / "does_not_exist.json")

    store.clear()

    assert store.load() is None

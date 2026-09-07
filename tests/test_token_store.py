import stat
import sys

import pytest

from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore

skip_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX chmod semantics don't apply on Windows",
)


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


@skip_on_windows
def test_token_store_save_sets_restrictive_permissions(tmp_path):
    store = TokenStore(tmp_path / "token.json")

    store.save(
        SpotifyToken(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=1234567890.0,
        )
    )

    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600


def test_token_store_save_leaves_no_temp_file_behind(tmp_path):
    store = TokenStore(tmp_path / "token.json")

    store.save(
        SpotifyToken(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=1234567890.0,
        )
    )

    assert [p.name for p in tmp_path.iterdir()] == ["token.json"]


def test_token_store_load_returns_none_for_corrupt_json(tmp_path):
    # Roadmap item 6.2.2 — a crash mid-write (before the atomic-write
    # fix) or plain disk corruption must read as "no token," i.e. a
    # fresh authorization, not a JSONDecodeError out of
    # get_valid_token().
    path = tmp_path / "token.json"
    path.write_text("{not valid json at all")
    store = TokenStore(path)

    assert store.load() is None


def test_token_store_load_returns_none_for_incomplete_json(tmp_path):
    path = tmp_path / "token.json"
    path.write_text('{"access_token": "access-1"}')
    store = TokenStore(path)

    assert store.load() is None

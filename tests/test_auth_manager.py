import time

import httpx

from seeker.spotify.auth_manager import SpotifyAuthManager
from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore


def make_manager(tmp_path) -> SpotifyAuthManager:
    return SpotifyAuthManager(
        client_id="client-id",
        redirect_uri="http://localhost:8888/callback",
        token_path=tmp_path / "token.json",
    )


def _fail_if_called(*args, **kwargs):
    raise AssertionError("this must not be called on this branch")


def test_get_valid_token_returns_valid_token_without_refresh(
        tmp_path, monkeypatch,
):
    manager = make_manager(tmp_path)
    TokenStore(manager.token_path).save(
        SpotifyToken(
            access_token="valid-access",
            refresh_token="refresh-1",
            expires_at=time.time() + 3600,
        )
    )

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", _fail_if_called
    )
    monkeypatch.setattr(manager, "_authorize", _fail_if_called)

    token = manager.get_valid_token()

    assert token.access_token == "valid-access"


def test_get_valid_token_refreshes_expired_token(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    TokenStore(manager.token_path).save(
        SpotifyToken(
            access_token="old-access",
            refresh_token="refresh-1",
            expires_at=time.time() - 10,
        )
    )

    def fake_refresh(client_id, refresh_token):
        assert client_id == "client-id"
        assert refresh_token == "refresh-1"
        return SpotifyToken(
            access_token="new-access",
            refresh_token="refresh-2",
            expires_at=time.time() + 3600,
        )

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", fake_refresh
    )
    monkeypatch.setattr(manager, "_authorize", _fail_if_called)

    token = manager.get_valid_token()

    assert token.access_token == "new-access"
    # Persisted for next time.
    reloaded = TokenStore(manager.token_path).load()
    assert reloaded is not None
    assert reloaded.access_token == "new-access"


def test_get_valid_token_falls_back_to_fresh_login_when_refresh_fails(
        tmp_path, monkeypatch,
):
    # Documented, deliberate behavior (see CLAUDE.md / commit "Fall back
    # to a fresh login when Spotify token refresh fails").
    manager = make_manager(tmp_path)
    TokenStore(manager.token_path).save(
        SpotifyToken(
            access_token="old-access",
            refresh_token="stale-refresh",
            expires_at=time.time() - 10,
        )
    )

    def fake_refresh(client_id, refresh_token):
        request = httpx.Request("POST", "https://accounts.spotify.com/api/token")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError(
            "refresh failed", request=request, response=response
        )

    fresh_token = SpotifyToken(
        access_token="brand-new-access",
        refresh_token="brand-new-refresh",
        expires_at=time.time() + 3600,
    )

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", fake_refresh
    )
    monkeypatch.setattr(manager, "_authorize", lambda: fresh_token)

    token = manager.get_valid_token()

    assert token.access_token == "brand-new-access"


def test_get_valid_token_authorizes_when_no_token_saved(
        tmp_path, monkeypatch,
):
    manager = make_manager(tmp_path)

    fresh_token = SpotifyToken(
        access_token="first-time-access",
        refresh_token="first-time-refresh",
        expires_at=time.time() + 3600,
    )
    monkeypatch.setattr(manager, "_authorize", lambda: fresh_token)
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", _fail_if_called
    )

    token = manager.get_valid_token()

    assert token.access_token == "first-time-access"

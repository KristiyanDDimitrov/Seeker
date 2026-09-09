import time

import httpx
import pytest

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


def test_authorize_raises_actionable_error_on_callback_timeout(
        tmp_path, monkeypatch,
):
    # Round 8 §6.3.1: wait_for_callback()'s new distinct `timed_out`
    # outcome (an abandoned/closed authorization tab) must surface as a
    # clear, actionable message rather than propagating some other
    # generic failure or hanging.
    manager = make_manager(tmp_path)
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.create_callback_server", object,
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.serve_until_callback",
        lambda server: (None, None, None, True),
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.webbrowser.open", lambda url: None,
    )

    with pytest.raises(RuntimeError, match="timed out"):
        manager.get_valid_token()


def test_connect_spotify_flow_does_not_reauthorize_on_the_next_call(
        tmp_path, monkeypatch,
):
    # Round 8 §4.8.6/follow-up: application.py's connect_spotify() was
    # changed from a bare `self.spotify` access (which never actually
    # triggered OAuth at all -- SpotifyClient.__init__ only stores its
    # token_source callable, never calls it) to a direct
    # auth_manager.get_valid_token() call, which DOES eagerly run the
    # real browser/callback round-trip. This is the regression that
    # change could have introduced: does the very next get_valid_token()
    # call (the shape of what SpotifyClient's token_source lambda does
    # on the first real API call right after connect_spotify() returns)
    # silently re-authorize instead of reusing the token _authorize()
    # just persisted? Exercises the REAL _authorize()/_save_token()
    # path end to end (not mocked out, unlike the test above) -- only
    # the actual network/browser boundaries are faked.
    manager = make_manager(tmp_path)

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.generate_state",
        lambda: "fixed-state",
    )
    # Round 9 §1.2: one shared call_order list, not separate counters,
    # so this test can also assert the fix's actual ordering — the
    # callback server must be created BEFORE the browser opens, not
    # after.
    call_order: list[str] = []
    webbrowser_open_calls: list[str] = []

    def fake_webbrowser_open(url):
        call_order.append("open")
        webbrowser_open_calls.append(url)

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.webbrowser.open", fake_webbrowser_open,
    )

    def fake_create_callback_server():
        call_order.append("create")
        return object()

    def fake_serve_until_callback(server):
        call_order.append("serve")
        return ("real-code", "fixed-state", None, False)

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.create_callback_server",
        fake_create_callback_server,
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.serve_until_callback",
        fake_serve_until_callback,
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.exchange_code_for_token",
        lambda **kwargs: SpotifyToken(
            access_token="real-access-token",
            refresh_token="real-refresh-token",
            expires_at=time.time() + 3600,
        ),
    )

    first_token = manager.get_valid_token()

    assert len(webbrowser_open_calls) == 1
    assert "client_id=client-id" in webbrowser_open_calls[0]
    assert "state=fixed-state" in webbrowser_open_calls[0]
    assert call_order == ["create", "open", "serve"], (
        "the callback socket must be bound before the browser opens, "
        "not after — a returning user's redirect-with-no-consent-"
        "screen can otherwise land before anything is listening"
    )
    assert TokenStore(manager.token_path).load() is not None

    second_token = manager.get_valid_token()

    assert len(webbrowser_open_calls) == 1, (
        "a second get_valid_token() call must reuse the just-persisted "
        "token, not re-run the browser/callback authorization flow"
    )
    assert call_order.count("serve") == 1
    assert second_token.access_token == first_token.access_token


def test_get_valid_token_force_refresh_refreshes_a_still_valid_token(
        tmp_path, monkeypatch,
):
    # B8.3's own foundation: a token can be rejected (401) for a reason
    # the expiry clock doesn't know about — force_refresh=True must skip
    # the normal is_expired() check entirely, not just re-check it.
    manager = make_manager(tmp_path)
    TokenStore(manager.token_path).save(
        SpotifyToken(
            access_token="clock-says-valid",
            refresh_token="refresh-1",
            expires_at=time.time() + 3600,
        )
    )

    def fake_refresh(client_id, refresh_token):
        return SpotifyToken(
            access_token="forced-refresh-access",
            refresh_token="refresh-2",
            expires_at=time.time() + 3600,
        )

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", fake_refresh
    )
    monkeypatch.setattr(manager, "_authorize", _fail_if_called)

    token = manager.get_valid_token(force_refresh=True)

    assert token.access_token == "forced-refresh-access"

import threading
import time

import httpx
import pytest

from seeker.spotify import auth_manager
from seeker.spotify.auth_manager import SpotifyAuthManager
from seeker.spotify.callback_server import AuthorizationCancelledError
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
    monkeypatch.setattr(manager, "_authorize", lambda cancel=None: fresh_token)

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
    monkeypatch.setattr(manager, "_authorize", lambda cancel=None: fresh_token)
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", _fail_if_called
    )

    token = manager.get_valid_token()

    assert token.access_token == "first-time-access"


def test_authorize_raises_actionable_error_on_callback_timeout(
        tmp_path, monkeypatch,
):
    # Round 8 §6.3.1: serve_until_callback()'s distinct `timed_out`
    # outcome (an abandoned/closed authorization tab) must surface as a
    # clear, actionable message rather than propagating some other
    # generic failure or hanging.
    manager = make_manager(tmp_path)
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.create_callback_server",
        lambda state: object(),
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.serve_until_callback",
        lambda server, cancel=None: (None, None, None, True),
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

    def fake_create_callback_server(state):
        call_order.append("create")
        return object()

    def fake_serve_until_callback(server, cancel=None):
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


def _rotating_refresh_endpoint(first_refresh_token):
    """A fake Spotify token endpoint: each refresh rotates the refresh
    token, and the old one then fails with a 400, as the real one does."""
    state = {"current": first_refresh_token, "calls": 0}

    def fake_refresh(client_id, refresh_token):
        state["calls"] += 1
        if refresh_token != state["current"]:
            request = httpx.Request(
                "POST", "https://accounts.spotify.com/api/token",
            )
            raise httpx.HTTPStatusError(
                "invalid_grant", request=request,
                response=httpx.Response(400, request=request),
            )
        state["current"] = f"refresh-{state['calls'] + 1}"
        return SpotifyToken(
            access_token=f"access-{state['calls'] + 1}",
            refresh_token=state["current"],
            expires_at=time.time() + 3600,
        )

    return fake_refresh, state


def test_concurrent_callers_share_one_refresh_of_an_expired_token(
        tmp_path, monkeypatch,
):
    # Sync and Refresh tracks can run at once. Without a lock both
    # refresh; Spotify rotates the refresh token, so the loser's 400
    # falls back to a surprise browser authorization.
    manager = make_manager(tmp_path)
    TokenStore(manager.token_path).save(
        SpotifyToken(
            access_token="access-1",
            refresh_token="refresh-1",
            expires_at=time.time() - 10,
        )
    )
    fake_refresh, endpoint = _rotating_refresh_endpoint("refresh-1")
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.refresh_access_token", fake_refresh,
    )
    monkeypatch.setattr(manager, "_authorize", _fail_if_called)

    # Both threads must have read the expired token before either one
    # refreshes it: each thread's first load waits for the other's.
    both_loaded = threading.Barrier(2, timeout=5)
    first_load_done: set[int] = set()
    real_load = manager._load_token

    def load_after_both_threads_have_loaded():
        token = real_load()
        if threading.get_ident() not in first_load_done:
            first_load_done.add(threading.get_ident())
            both_loaded.wait()
        return token

    monkeypatch.setattr(
        manager, "_load_token", load_after_both_threads_have_loaded,
    )

    results: list[str] = []
    errors: list[BaseException] = []

    def call():
        try:
            results.append(manager.get_valid_token().access_token)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    assert endpoint["calls"] == 1
    assert results == ["access-2", "access-2"]


def test_cancelled_authorization_raises_and_releases_the_token_lock(
        tmp_path, monkeypatch,
):
    # _authorize runs inside _TOKEN_LOCK: a cancel that left it held
    # would make a concurrent sync wait out the full callback timeout.
    manager = make_manager(tmp_path)
    cancel = threading.Event()
    forwarded: list[threading.Event | None] = []

    def fake_serve_until_callback(server, cancel=None):
        forwarded.append(cancel)
        cancel.set()
        raise AuthorizationCancelledError

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.create_callback_server",
        lambda state: object(),
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.serve_until_callback",
        fake_serve_until_callback,
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.webbrowser.open", lambda url: None,
    )

    with pytest.raises(AuthorizationCancelledError):
        manager.get_valid_token(cancel=cancel)

    assert forwarded == [cancel]
    assert not auth_manager._TOKEN_LOCK.locked()


def test_a_forged_error_callback_does_not_end_the_authorization(
        tmp_path, monkeypatch,
):
    # Any web page Kris has open can fire a GET at the loopback
    # callback while Seeker waits. Without the expected state it must
    # neither end the wait nor put its text into Seeker's error.
    manager = make_manager(tmp_path)
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.generate_state", lambda: "real-state",
    )
    servers = []
    real_create = auth_manager.create_callback_server

    def create_on_an_ephemeral_port(*args, **kwargs):
        server = real_create(*args, port=0, **kwargs)
        servers.append(server)
        return server

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.create_callback_server",
        create_on_an_ephemeral_port,
    )
    forged_statuses: list[int] = []

    def browser_then_forger(url):
        port = servers[0].server_address[1]
        callback = f"http://127.0.0.1:{port}/callback"

        def requests() -> None:
            forged = httpx.get(
                callback,
                params={"error": "Visit evil.example", "state": "forged"},
                timeout=5.0,
            )
            forged_statuses.append(forged.status_code)
            httpx.get(
                callback,
                params={"code": "real-code", "state": "real-state"},
                timeout=5.0,
            )

        threading.Thread(target=requests, daemon=True).start()

    monkeypatch.setattr(
        "seeker.spotify.auth_manager.webbrowser.open", browser_then_forger,
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.exchange_code_for_token",
        lambda **kwargs: SpotifyToken(
            access_token="real-access",
            refresh_token="real-refresh",
            expires_at=time.time() + 3600,
        ),
    )

    token = manager.get_valid_token()

    assert token.access_token == "real-access"
    assert forged_statuses == [400]


def test_an_error_with_the_wrong_state_reports_the_state_not_its_text(
        tmp_path, monkeypatch,
):
    manager = make_manager(tmp_path)
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.create_callback_server",
        lambda *args: object(),
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.serve_until_callback",
        lambda server, cancel=None: (None, "forged", "Visit evil.example", False),
    )
    monkeypatch.setattr(
        "seeker.spotify.auth_manager.webbrowser.open", lambda url: None,
    )

    with pytest.raises(RuntimeError, match="state validation failed"):
        manager.get_valid_token()

import time
from urllib.parse import parse_qs, urlparse

import httpx

from seeker.spotify.auth import (
    build_authorization_url,
    exchange_code_for_token,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
    refresh_access_token,
)


def test_build_authorization_url_contains_pkce_params():
    url = build_authorization_url(
        client_id="client-1",
        redirect_uri="http://localhost:8888/callback",
        state="state-1",
        code_challenge="challenge-1",
    )

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.spotify.com"
    assert params["client_id"] == ["client-1"]
    assert params["redirect_uri"] == ["http://localhost:8888/callback"]
    assert params["state"] == ["state-1"]
    assert params["code_challenge"] == ["challenge-1"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["response_type"] == ["code"]


def test_generate_code_challenge_matches_rfc7636_test_vector():
    # RFC 7636 Appendix B's official PKCE S256 test vector — verified
    # against this implementation directly before writing the assertion.
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    expected_challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"

    assert generate_code_challenge(verifier) == expected_challenge


def test_generate_code_verifier_and_state_are_random():
    assert generate_code_verifier() != generate_code_verifier()
    assert generate_state() != generate_state()


def test_exchange_code_for_token_parses_real_response_shape(monkeypatch):
    def fake_post(url, data=None, timeout=None):
        assert url == "https://accounts.spotify.com/api/token"
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "auth-code-1"
        assert data["code_verifier"] == "verifier-1"
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    before = time.time()
    token = exchange_code_for_token(
        client_id="client-1",
        redirect_uri="http://localhost:8888/callback",
        code="auth-code-1",
        code_verifier="verifier-1",
    )

    assert token.access_token == "access-1"
    assert token.refresh_token == "refresh-1"
    assert before + 3600 <= token.expires_at <= time.time() + 3600


def test_refresh_access_token_keeps_old_refresh_token_when_not_returned(
        monkeypatch,
):
    # Real Spotify behavior: a refresh response doesn't always include a
    # new refresh_token — the old one must still be usable next time.
    def fake_post(url, data=None, timeout=None):
        return httpx.Response(
            200,
            json={"access_token": "new-access", "expires_in": 3600},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    token = refresh_access_token(
        client_id="client-1", refresh_token="old-refresh"
    )

    assert token.access_token == "new-access"
    assert token.refresh_token == "old-refresh"


def test_refresh_access_token_uses_new_refresh_token_when_returned(
        monkeypatch,
):
    def fake_post(url, data=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    token = refresh_access_token(
        client_id="client-1", refresh_token="old-refresh"
    )

    assert token.refresh_token == "new-refresh"

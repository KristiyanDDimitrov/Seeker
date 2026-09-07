import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import httpx

from seeker.spotify.token import SpotifyToken

AUTHORIZATION_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

SCOPE = "playlist-read-private"


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(96)


def generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    parameters = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": SCOPE,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }

    return f"{AUTHORIZATION_URL}?{urlencode(parameters)}"


def exchange_code_for_token(
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> SpotifyToken:
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        },
        timeout=10.0,
    )

    response.raise_for_status()

    data = response.json()

    return SpotifyToken(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=time.time() + data["expires_in"],
    )

def refresh_access_token(
    client_id: str,
    refresh_token: str,
) -> SpotifyToken:
    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
        timeout=10.0,
    )

    response.raise_for_status()

    data = response.json()

    new_refresh_token = data.get(
        "refresh_token",
        refresh_token,
    )

    return SpotifyToken(
        access_token=data["access_token"],
        refresh_token=new_refresh_token,
        expires_at=time.time() + data["expires_in"],
    )

import time
import webbrowser
from pathlib import Path

import httpx

from seeker.spotify.auth import (
    build_authorization_url,
    exchange_code_for_token,
    generate_code_challenge,
    generate_code_verifier,
    generate_state,
    refresh_access_token,
)
from seeker.spotify.callback_server import wait_for_callback
from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore


# Spotify rotates the refresh token on every PKCE refresh — the old one
# stops working the moment a new one is issued (see _save_token below).
# Two installs sharing one Spotify account and client ID (e.g. this
# app's real account plus a test account on the same machine) can each
# invalidate the other's stored refresh token this way — the symptom is
# a refresh failing and falling back to a real browser re-authorization
# for no obvious reason. That is a real, separate effect, not the B8
# 401-after-an-hour bug (which was the cached SpotifyClient never
# calling get_valid_token() again at all) — recorded here so it isn't
# re-diagnosed from scratch.
class SpotifyAuthManager:
    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        token_path: Path,
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.token_path = token_path

    def get_valid_token(self, force_refresh: bool = False) -> SpotifyToken:
        token = self._load_token()

        if token is None:
            return self._authorize()

        if force_refresh or self._is_expired(token):
            print("Spotify access token expired. Refreshing...")

            try:
                token = refresh_access_token(
                    self.client_id,
                    token.refresh_token,
                )
            except httpx.HTTPStatusError:
                print(
                    "Spotify token refresh failed. "
                    "Starting a new authorization..."
                )
                return self._authorize()

            self._save_token(token)

        return token

    def _is_expired(self, token: SpotifyToken) -> bool:
        return time.time() >= token.expires_at - 60

    def _load_token(self) -> SpotifyToken | None:
        return TokenStore(self.token_path).load()

    def _save_token(self, token: SpotifyToken) -> None:
        self.token_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        TokenStore(self.token_path).save(token)

    def _authorize(self) -> SpotifyToken:
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = generate_state()

        authorization_url = build_authorization_url(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )

        print("Opening Spotify authorization page...")
        webbrowser.open(authorization_url)

        code, returned_state, error, timed_out = wait_for_callback()

        if timed_out:
            raise RuntimeError("Authorization timed out — try again.")

        if error:
            raise RuntimeError(
                f"Spotify authorization failed: {error}"
            )

        if returned_state != state:
            raise RuntimeError(
                "Spotify state validation failed."
            )

        if not code:
            raise RuntimeError(
                "Spotify did not return an authorization code."
            )

        token = exchange_code_for_token(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            code=code,
            code_verifier=code_verifier,
        )

        self._save_token(token)

        return token

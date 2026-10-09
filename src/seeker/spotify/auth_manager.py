import logging
import threading
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
from seeker.spotify.callback_server import (
    create_callback_server,
    serve_until_callback,
)
from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore

logger = logging.getLogger(__name__)

# One lock per process, not per manager: Application builds a fresh
# SpotifyAuthManager on every connect, and all of them share one token
# file. Held across a refresh (and the browser fallback), so concurrent
# callers never spend the same rotating refresh token twice.
_TOKEN_LOCK = threading.Lock()


# Spotify rotates the refresh token on every PKCE refresh — the old one
# stops working the moment a new one is issued (see _save_token below).
# Two installs sharing one Spotify account and client ID (e.g. this
# app's real account plus a test account on the same machine) can each
# invalidate the other's stored refresh token this way — the symptom is
# a refresh failing and falling back to a real browser re-authorization
# for no obvious reason. That is a separate effect from a 401 after an
# hour (a cached SpotifyClient never calling get_valid_token() again).
# See HISTORY §92.
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

    def get_valid_token(
            self,
            force_refresh: bool = False,
            cancel: threading.Event | None = None,
    ) -> SpotifyToken:
        """`cancel` only matters when this falls back to the browser:
        setting it ends the wait for the callback with
        AuthorizationCancelledError and releases the token lock.
        """
        seen = self._load_token()

        if seen is not None and not force_refresh and not self._is_expired(
                seen,
        ):
            return seen

        with _TOKEN_LOCK:
            # Re-read under the lock: another caller may have refreshed
            # (rotating the refresh token `seen` holds) while this one
            # waited.
            token = self._load_token()

            if token is None:
                return self._authorize(cancel)

            refreshed_meanwhile = (
                seen is not None and token.access_token != seen.access_token
            )
            if refreshed_meanwhile and not self._is_expired(token):
                return token

            if force_refresh or self._is_expired(token):
                logger.info("Spotify access token expired. Refreshing...")

                try:
                    token = refresh_access_token(
                        self.client_id,
                        token.refresh_token,
                    )
                except httpx.HTTPStatusError:
                    logger.warning(
                        "Spotify token refresh failed. Starting a new "
                        "authorization..."
                    )
                    return self._authorize(cancel)

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

    def _authorize(
            self, cancel: threading.Event | None = None,
    ) -> SpotifyToken:
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        state = generate_state()

        authorization_url = build_authorization_url(
            client_id=self.client_id,
            redirect_uri=self.redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )

        # Bind the callback socket BEFORE opening the browser, not after
        # — a user who already granted access on a previous run gets
        # redirected straight back with no consent screen to slow it
        # down, and the callback can otherwise land before anything is
        # listening for it.
        server = create_callback_server(state)

        logger.info("Opening Spotify authorization page...")
        webbrowser.open(authorization_url)

        # serve_until_callback() closes `server` itself in its own
        # finally, whether this returns normally or raises.
        code, returned_state, error, timed_out = serve_until_callback(
            server, cancel=cancel,
        )

        if timed_out:
            raise RuntimeError("Authorization timed out — try again.")

        # State first: an `error` is Spotify's only if the state is.
        if returned_state != state:
            raise RuntimeError(
                "Spotify state validation failed."
            )

        if error:
            raise RuntimeError(
                f"Spotify authorization failed: {error}"
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

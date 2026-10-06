import json
from pathlib import Path

from seeker.files.atomic import write_text_locked
from seeker.spotify.token import SpotifyToken


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def save(self, token: SpotifyToken) -> None:
        # This file holds a Spotify refresh token, the long-lived
        # credential, so it is never left to the process umask (0644 on
        # a default macOS account): the same atomic-plus-locked-down
        # 0600 write config_store.py uses. See HISTORY §116.
        write_text_locked(
            self.path,
            json.dumps(
                {
                    "access_token": token.access_token,
                    "refresh_token": token.refresh_token,
                    "expires_at": token.expires_at,
                }
            ),
        )

    def load(self) -> SpotifyToken | None:
        if not self.path.exists():
            return None

        try:
            data = json.loads(self.path.read_text())
            return SpotifyToken(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=data["expires_at"],
            )
        except (OSError, json.JSONDecodeError, KeyError):
            # A corrupt/truncated token file (an older non-atomic
            # write, or simple disk corruption) must mean "no token" — i.e. a
            # fresh authorization — the same tolerance load_config()
            # already has, not a traceback out of get_valid_token().
            return None

    def clear(self) -> None:
        # Used by Settings' "Re-authorize" action: with a
        # still-valid cached token present, get_valid_token() would
        # otherwise just silently return it without ever opening the
        # browser — correct for the wizard's first-time connect (no
        # token file exists yet), but would make an already-connected
        # user's re-authorize request a no-op. Clearing the cached
        # token first forces get_valid_token()'s existing
        # token-is-None branch to run a real fresh authorization.
        self.path.unlink(missing_ok=True)

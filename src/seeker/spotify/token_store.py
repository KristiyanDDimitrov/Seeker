import json
from pathlib import Path

from seeker.spotify.token import SpotifyToken


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def save(self, token: SpotifyToken) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "access_token": token.access_token,
                    "refresh_token": token.refresh_token,
                    "expires_at": token.expires_at,
                }
            )
        )

    def load(self) -> SpotifyToken | None:
        if not self.path.exists():
            return None

        data = json.loads(self.path.read_text())

        return SpotifyToken(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
        )

    def clear(self) -> None:
        # Used by Settings' "Re-authorize" action (Step 8 §3): with a
        # still-valid cached token present, get_valid_token() would
        # otherwise just silently return it without ever opening the
        # browser — correct for the wizard's first-time connect (no
        # token file exists yet), but would make an already-connected
        # user's re-authorize request a no-op. Clearing the cached
        # token first forces get_valid_token()'s existing
        # token-is-None branch to run a real fresh authorization.
        self.path.unlink(missing_ok=True)
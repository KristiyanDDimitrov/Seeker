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
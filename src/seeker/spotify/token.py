from dataclasses import dataclass


@dataclass
class SpotifyToken:
    access_token: str
    refresh_token: str
    expires_at: float

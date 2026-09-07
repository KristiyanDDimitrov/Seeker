import json
from pathlib import Path

from seeker.atomic_file import write_text_locked
from seeker.spotify.token import SpotifyToken


class TokenStore:
    def __init__(self, path: Path):
        self.path = path

    def save(self, token: SpotifyToken) -> None:
        # Roadmap item 6.2.1/6.2.2 — this file holds a Spotify refresh
        # token, the long-lived credential; it used to land at whatever
        # the process umask gave (0644 on a default macOS account) while
        # config_store.py's own file next to it was already 0600. Same
        # atomic-plus-locked-down write config_store.py uses.
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
            # Roadmap item 6.2.2 — a corrupt/truncated token file (a
            # crash mid-write, before this class wrote atomically, or
            # simple disk corruption) must mean "no token" — i.e. a
            # fresh authorization — the same tolerance load_config()
            # already has, not a traceback out of get_valid_token().
            return None

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

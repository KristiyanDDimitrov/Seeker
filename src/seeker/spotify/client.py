import httpx
import time

from datetime import datetime, timedelta
from typing import Any, Callable, Union, cast

from seeker.models.playlist import Playlist
from seeker.models.track import Track


BASE_URL = "https://api.spotify.com/v1"

# Either a bare token string (tests, or any short-lived script use) or a
# callable resolving to a fresh token on every call — the latter is what
# Application.spotify passes in, bound to auth_manager.get_valid_token(),
# so a request made after the cached SpotifyClient has outlived the
# token's 1-hour lifetime still gets one get_valid_token() has already
# refreshed, instead of the frozen string this class used to store
# (roadmap item 92 / B8.2).
TokenSource = Union[str, Callable[[], str]]

# Bounds _get's 429-retry loop. Without this, a server that kept returning
# a short Retry-After (e.g. 1s) indefinitely would retry forever — this
# caps it at a fixed number of short waits before surfacing the same
# SpotifyRateLimitedError callers already handle for "give up" cases.
MAX_RETRY_ATTEMPTS = 5


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours and minutes:
        return f"{hours}h {minutes}m"

    if hours:
        return f"{hours}h"

    if minutes:
        return f"{minutes}m"

    return f"{seconds}s"


def _format_clock_time(when: datetime) -> str:
    hour = when.hour % 12 or 12
    period = "AM" if when.hour < 12 else "PM"

    return f"{hour}:{when.minute:02d} {period}"


class SpotifyRateLimitedError(RuntimeError):
    def __init__(
        self,
        retry_after_seconds: int | None,
        quota_exceeded: bool,
    ):
        self.retry_after_seconds = retry_after_seconds
        self.quota_exceeded = quota_exceeded

        reason = (
            "Spotify development quota exceeded."
            if quota_exceeded
            else "Spotify rate limit exceeded."
        )

        if retry_after_seconds is None:
            wait_description = (
                "an unknown amount of time "
                "(no Retry-After header returned)"
            )
        else:
            retry_at = datetime.now() + timedelta(
                seconds=retry_after_seconds
            )

            wait_description = (
                f"{_format_duration(retry_after_seconds)} "
                f"(around {_format_clock_time(retry_at)})"
            )

        super().__init__(
            f"{reason} Try again in {wait_description}."
        )


class SpotifyAuthenticationError(RuntimeError):
    """Raised when Spotify rejects the current token and a single forced
    refresh-and-retry (B8.3) still 401s — a real, permanently revoked/
    invalid token, not just an expired one get_valid_token() already
    would have refreshed."""

    def __init__(self) -> None:
        super().__init__(
            "Spotify rejected Seeker's authorization. "
            "Re-authorize in Settings."
        )


class SpotifyClient:
    def __init__(
            self,
            token_source: TokenSource,
            force_refresh: Callable[[], str] | None = None,
    ):
        self._token_source = token_source
        # Bound to auth_manager.get_valid_token(force_refresh=True) by
        # Application.spotify — bypasses the normal expiry check so a
        # 401 (token rejected for a reason the clock doesn't know about)
        # still gets a real refreshed token, not the same one retried.
        self._force_refresh = force_refresh

    def _current_token(self) -> str:
        if callable(self._token_source):
            return self._token_source()

        return self._token_source

    def _get(
            self,
            url: str,
            params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = 0
        retried_after_401 = False
        token = self._current_token()

        while True:
            response = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                },
                params=params,
                timeout=10.0,
            )

            if response.status_code == 429:
                attempts += 1

                error_data = response.json().get("error", {})
                quota_exceeded = (
                    error_data.get("reason") == "QUOTA_EXCEEDED"
                )

                retry_after_header = response.headers.get(
                    "Retry-After"
                )
                retry_after_seconds = (
                    int(retry_after_header)
                    if retry_after_header is not None
                    else None
                )

                if (
                        quota_exceeded
                        or retry_after_seconds is None
                        or retry_after_seconds > 60
                        or attempts >= MAX_RETRY_ATTEMPTS
                ):
                    raise SpotifyRateLimitedError(
                        retry_after_seconds=retry_after_seconds,
                        quota_exceeded=quota_exceeded,
                    )

                print(
                    f"Spotify rate limit reached. "
                    f"Waiting {retry_after_seconds} seconds..."
                )

                time.sleep(retry_after_seconds)
                continue

            if response.status_code == 401:
                if retried_after_401 or self._force_refresh is None:
                    raise SpotifyAuthenticationError()

                retried_after_401 = True
                token = self._force_refresh()
                continue

            response.raise_for_status()

            # httpx's .json() is untyped (arbitrary JSON) — cast at this
            # one boundary rather than letting Any leak into every caller.
            return cast(dict[str, Any], response.json())

    def _get_all_pages(
            self,
            url: str,
            params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url

        while next_url:
            data = self._get(next_url, params)

            items.extend(data.get("items", []))

            next_url = data.get("next")
            params = None

        return items

    def get_current_user_playlists(self) -> list[Playlist]:
        items = self._get_all_pages(
            f"{BASE_URL}/me/playlists",
            {"limit": 50},
        )

        return [
            Playlist(
                id=playlist["id"],
                name=playlist["name"],
                track_count=playlist["items"]["total"],
                snapshot_id=playlist.get("snapshot_id"),
            )
            for playlist in items
        ]

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        entries = self._get_all_pages(
            f"{BASE_URL}/playlists/{playlist_id}/items",
            {"limit": 50},
        )

        tracks = []

        for entry in entries:
            track_data = entry.get("item")

            if not track_data:
                continue

            if track_data.get("type") != "track":
                continue

            artists = track_data.get("artists", [])

            if not artists:
                continue

            images = track_data["album"].get("images") or []
            album_art_url = (
                max(images, key=lambda image: image.get("width") or 0)["url"]
                if images
                else None
            )

            tracks.append(
                Track(
                    id=track_data["id"],
                    title=track_data["name"],
                    artist=", ".join(a["name"] for a in artists),
                    album=track_data["album"]["name"],
                    duration_ms=track_data["duration_ms"],
                    album_art_url=album_art_url,
                )
            )

        return tracks

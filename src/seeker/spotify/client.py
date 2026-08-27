import httpx
import time

from datetime import datetime, timedelta

from seeker.models.playlist import Playlist
from seeker.models.track import Track


BASE_URL = "https://api.spotify.com/v1"


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


class SpotifyClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _get(self, url: str, params: dict | None = None) -> dict:
        while True:
            response = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                },
                params=params,
                timeout=10.0,
            )

            if response.status_code == 429:
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

            response.raise_for_status()

            return response.json()

    def _get_all_pages(
            self,
            url: str,
            params: dict | None = None,
    ) -> list[dict]:
        items = []

        while url:
            data = self._get(url, params)

            items.extend(data.get("items", []))

            url = data.get("next")
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

            # Nested album images are already in the real /items response
            # — no separate GET /v1/albums/{id} call needed. Pick the
            # largest by width rather than trusting array order.
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
                    # Spotify may credit multiple artists on one track
                    # (e.g. a remix or collab) — join all of them rather
                    # than keeping only artists[0], matching the
                    # convention already seen in real local file tags.
                    artist=", ".join(artist["name"] for artist in artists),
                    album=track_data["album"]["name"],
                    duration_ms=track_data["duration_ms"],
                    album_art_url=album_art_url,
                )
            )

        return tracks

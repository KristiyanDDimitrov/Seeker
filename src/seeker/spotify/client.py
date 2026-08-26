import httpx
import time

from seeker.models.playlist import Playlist
from seeker.models.track import Track


BASE_URL = "https://api.spotify.com/v1"


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

                if error_data.get("reason") == "QUOTA_EXCEEDED":
                    raise RuntimeError(
                        "Spotify development quota has been exceeded."
                    )

                retry_after = response.headers.get("Retry-After")

                if retry_after is None:
                    raise RuntimeError(
                        "Spotify rate limit reached, but no Retry-After "
                        "header was provided."
                    )

                wait_seconds = int(retry_after)

                print(
                    f"Spotify rate limit reached. "
                    f"Waiting {wait_seconds} seconds..."
                )

                time.sleep(wait_seconds)
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
                track_count=playlist["tracks"]["total"],
                snapshot_id=playlist.get("snapshot_id"),
            )
            for playlist in items
        ]

    def get_playlist_tracks(self, playlist_id: str) -> list[Track]:
        items = self._get_all_pages(
            f"{BASE_URL}/playlists/{playlist_id}/tracks",
            {"limit": 50},
        )

        tracks = []

        for item in items:
            track = item.get("track")

            if not track:
                continue

            artists = track.get("artists", [])

            if not artists:
                continue

            tracks.append(
                Track(
                    id=track["id"],
                    title=track["name"],
                    artist=artists[0]["name"],
                    album=track["album"]["name"],
                    duration_ms=track["duration_ms"],
                )
            )

        return tracks

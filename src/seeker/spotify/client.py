import httpx

from seeker.models.playlist import Playlist


BASE_URL = "https://api.spotify.com/v1"


class SpotifyClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def get_current_user_playlists(self) -> list[Playlist]:
        playlists = []
        url = f"{BASE_URL}/me/playlists"
        params = {"limit": 50}

        while url:
            response = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                },
                params=params,
                timeout=10.0,
            )

            response.raise_for_status()

            data = response.json()

            playlists.extend(
                Playlist(
                    id=playlist["id"],
                    name=playlist["name"],
                    track_count=playlist["items"]["total"],
                )
                for playlist in data["items"]
            )

            url = data["next"]
            params = None

        return playlists
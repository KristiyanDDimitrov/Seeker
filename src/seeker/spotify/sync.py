from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import PlaylistRepository
from seeker.database.repositories.track_repository import TrackRepository
from seeker.spotify.client import SpotifyClient


class SpotifySynchronizer:
    def __init__(
        self,
        spotify: SpotifyClient,
        database: Database,
    ):
        self.spotify = spotify
        self.playlist_repository = PlaylistRepository(database)
        self.track_repository = TrackRepository(database)

    def sync_playlist(self, playlist_id: str) -> None:
        playlists = self.spotify.get_current_user_playlists()

        playlist = next(
            (
                playlist
                for playlist in playlists
                if playlist.id == playlist_id
            ),
            None,
        )

        if playlist is None:
            raise RuntimeError(
                f"Playlist {playlist_id} was not found."
            )

        print(f"Syncing playlist: {playlist.name}")

        self.playlist_repository.save(playlist)

        tracks = self.spotify.get_playlist_tracks(
            playlist.id
        )

        for track in tracks:
            self.track_repository.save(track)

            self.track_repository.save_playlist_track(
                playlist.id,
                track.id,
            )

        print(f"Saved {len(tracks)} tracks.")
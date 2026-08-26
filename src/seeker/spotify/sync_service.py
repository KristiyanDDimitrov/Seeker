from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import PlaylistRepository
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.playlist import Playlist
from seeker.spotify.client import SpotifyClient


class SpotifySyncService:
    def __init__(
        self,
        spotify_client: SpotifyClient,
        database: Database,
    ):
        self.spotify = spotify_client
        self.database = database
        self.playlists = PlaylistRepository(database)
        self.tracks = TrackRepository(database)

    def sync_playlists(self) -> list[Playlist]:
        print("Synchronizing Spotify playlists...")

        spotify_playlists = (
            self.spotify.get_current_user_playlists()
        )

        with self.database.transaction() as connection:
            local_playlists = {
                playlist.id: playlist
                for playlist in self.playlists.get_all(connection)
            }

            spotify_playlist_ids = set()
            playlists_needing_track_sync = []

            for playlist in spotify_playlists:
                spotify_playlist_ids.add(playlist.id)

                local_playlist = local_playlists.get(
                    playlist.id
                )

                if (
                        local_playlist is not None
                        and local_playlist.snapshot_id
                        == playlist.snapshot_id
                ):
                    print(
                        f"  Unchanged: {playlist.name}"
                    )
                    continue

                print(
                    f"  Updated: {playlist.name}"
                )

                playlists_needing_track_sync.append(
                    playlist
                )

            for playlist_id in local_playlists:
                if playlist_id not in spotify_playlist_ids:
                    print(
                        f"  Removed: "
                        f"{local_playlists[playlist_id].name}"
                    )

                    self.playlists.delete(playlist_id, connection)

        print("Playlist synchronization complete.")

        return playlists_needing_track_sync

    def list_playlists(self) -> list[Playlist]:
        with self.database.transaction() as connection:
            return self.playlists.get_all(connection)

    def sync_playlist_tracks(
            self,
            playlist: Playlist,
    ) -> None:
        print(
            f"Synchronizing tracks: {playlist.name}"
        )

        tracks = self.spotify.get_playlist_tracks(
            playlist.id
        )

        with self.database.transaction() as connection:
            self.playlists.save(playlist, connection)

            for track in tracks:
                self.tracks.save(track, connection)

            self.tracks.replace_playlist_tracks(
                playlist.id,
                [track.id for track in tracks],
                connection,
            )

        print(
            f"  Saved {len(tracks)} tracks."
        )

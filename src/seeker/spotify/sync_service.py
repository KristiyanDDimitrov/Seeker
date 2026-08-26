from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import PlaylistRepository
from seeker.database.repositories.track_repository import TrackRepository
from seeker.spotify.client import SpotifyClient


class SpotifySyncService:
    def __init__(
        self,
        spotify_client: SpotifyClient,
        database: Database,
    ):
        self.spotify = spotify_client
        self.playlists = PlaylistRepository(database)
        self.tracks = TrackRepository(database)

    def sync_playlists(self) -> list[str]:
        print("Synchronizing Spotify playlists...")

        spotify_playlists = (
            self.spotify.get_current_user_playlists()
        )

        local_playlists = {
            playlist.id: playlist
            for playlist in self.playlists.get_all()
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

            self.playlists.save(playlist)

            playlists_needing_track_sync.append(
                playlist.id
            )

        for playlist_id in local_playlists:
            if playlist_id not in spotify_playlist_ids:
                print(
                    f"  Removed: "
                    f"{local_playlists[playlist_id].name}"
                )

                self.playlists.delete(playlist_id)

        print("Playlist synchronization complete.")

        return playlists_needing_track_sync

    def sync_playlist_tracks(
            self,
            playlist_id: str,
    ) -> None:
        playlist = self.playlists.get_by_id(playlist_id)

        if playlist is None:
            raise RuntimeError(
                f"Playlist {playlist_id} is not in the database."
            )

        print(
            f"Synchronizing tracks: {playlist.name}"
        )

        tracks = self.spotify.get_playlist_tracks(
            playlist.id
        )

        for track in tracks:
            self.tracks.save(track)

        self.tracks.replace_playlist_tracks(
            playlist.id,
            [track.id for track in tracks],
        )

        print(
            f"  Saved {len(tracks)} tracks."
        )
import logging
from collections.abc import Callable

from rapidfuzz.distance import Levenshtein

from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import PlaylistRepository
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.playlist import Playlist
from seeker.models.spotify_sync import PlaylistRefreshResult, TrackSyncResult
from seeker.models.track import Track
from seeker.spotify.client import SpotifyClient

logger = logging.getLogger(__name__)


class PlaylistNotFoundError(RuntimeError):
    pass


def find_close_playlist_matches(
        name: str,
        candidates: list[str],
) -> list[str]:
    # difflib.SequenceMatcher's ratio inflates for short strings — "Test"
    # vs "sesh" scored 0.5 against a 0.5 cutoff (a real false positive,
    # confirmed against real playlist data) purely from sharing a couple
    # of letters, not genuine resemblance. Absolute edit distance,
    # scaled to query length, doesn't have that failure mode.
    #
    # Untuned initial constant, same treatment as the 90/70 matcher
    # thresholds elsewhere in this codebase: roughly one edit tolerated
    # per four characters of the query, floored at 1 so even a
    # 3-character query still tolerates a single typo.
    max_distance = max(1, len(name) // 4)

    scored = sorted(
        (Levenshtein.distance(name.lower(), candidate.lower()), candidate)
        for candidate in candidates
    )

    return [
        candidate
        for distance, candidate in scored
        if distance <= max_distance
    ][:3]


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
        logger.info("Synchronizing Spotify playlists...")

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
                    logger.info("Unchanged: %s", playlist.name)
                    continue

                logger.info("Updated: %s", playlist.name)

                self.playlists.save(playlist, connection)

                playlists_needing_track_sync.append(
                    playlist
                )

            for playlist_id, local_playlist in local_playlists.items():
                if playlist_id not in spotify_playlist_ids:
                    logger.info("Removed: %s", local_playlist.name)

                    self.playlists.delete(playlist_id, connection)

        logger.info("Playlist synchronization complete.")

        return playlists_needing_track_sync

    def refresh_playlists(
            self,
            progress: Callable[[str, int, int], None] | None = None,
    ) -> PlaylistRefreshResult:
        """Refresh the playlist list, then re-sync the tracks of every
        loaded playlist that changed on Spotify.

        Staleness is read back from the database rather than taken from
        this call's own snapshot comparison, so a playlist left stale by
        an earlier failed track sync is retried too. Never-loaded
        playlists stay unloaded. A failed track sync propagates; the
        playlists not yet re-synced stay stale for the next refresh.
        """
        self.sync_playlists()

        playlists = self.list_playlists()
        stale = [playlist for playlist in playlists
                 if playlist.tracks_are_stale]
        local_files_skipped = 0

        for index, playlist in enumerate(stale):
            if progress is not None:
                progress("Updating tracks", index, len(stale))

            result = self.sync_playlist_tracks(playlist)
            local_files_skipped += result.local_files_skipped

        if progress is not None and stale:
            progress("Updating tracks", len(stale), len(stale))

        return PlaylistRefreshResult(
            playlist_count=len(playlists),
            updated_playlist_names=[playlist.name for playlist in stale],
            local_files_skipped=local_files_skipped,
        )

    def list_playlists(self) -> list[Playlist]:
        with self.database.transaction() as connection:
            return self.playlists.get_all(connection)

    def get_playlist_by_name(self, name: str) -> Playlist:
        with self.database.transaction() as connection:
            playlists = self.playlists.get_all(connection)

        for playlist in playlists:
            if playlist.name.lower() == name.lower():
                return playlist

        available_names = [playlist.name for playlist in playlists]
        close_matches = find_close_playlist_matches(name, available_names)

        if close_matches:
            detail = f"Did you mean: {', '.join(close_matches)}?"
        elif available_names:
            detail = f"Available playlists: {', '.join(available_names)}"
        else:
            detail = "No playlists have been synchronized yet."

        raise PlaylistNotFoundError(
            f"No playlist named '{name}' found locally. {detail}"
        )

    def sync_playlist_tracks(
            self,
            playlist: Playlist,
    ) -> TrackSyncResult:
        logger.info("Synchronizing tracks: %s", playlist.name)

        items = self.spotify.get_playlist_tracks(
            playlist.id
        )
        tracks = _first_occurrences(items.tracks)
        duplicates_collapsed = len(items.tracks) - len(tracks)

        with self.database.transaction() as connection:
            # Read before the save below overwrites it, so the count of
            # album art URLs this sync filled in is exact.
            previously_missing_art = {
                track.id
                for track in self.tracks.get_all_for_playlist(
                    playlist.id, connection,
                )
                if track.album_art_url is None
            }

            self.playlists.save(playlist, connection)

            for track in tracks:
                self.tracks.save(track, connection)

            self.tracks.replace_playlist_tracks(
                playlist.id,
                [track.id for track in tracks],
                connection,
            )
            self.playlists.mark_tracks_loaded(
                playlist.id, playlist.snapshot_id, connection,
            )

        art_urls_filled = sum(
            1 for track in tracks
            if track.id in previously_missing_art
            and track.album_art_url is not None
        )

        logger.info("Saved %d tracks.", len(tracks))
        if items.local_files_skipped:
            logger.info(
                "Skipped %d Spotify local file(s).",
                items.local_files_skipped,
            )
        if duplicates_collapsed:
            logger.info(
                "Collapsed %d duplicate listing(s).", duplicates_collapsed,
            )
        if art_urls_filled:
            logger.info(
                "Filled in %d missing album art URL(s).", art_urls_filled,
            )

        return TrackSyncResult(
            tracks_saved=len(tracks),
            local_files_skipped=items.local_files_skipped,
            duplicates_collapsed=duplicates_collapsed,
            art_urls_filled=art_urls_filled,
        )


def _first_occurrences(tracks: list[Track]) -> list[Track]:
    seen: set[str] = set()
    unique = []

    for track in tracks:
        if track.id in seen:
            continue

        seen.add(track.id)
        unique.append(track)

    return unique

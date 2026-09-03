from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    TERMINAL_STATUSES,
    DownloadRequestRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.download_dedup import most_recent_per_candidate
from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.models.track import resolve_playlist_label
from seeker.models.track_match import TrackMatch

# Untuned default, same convention as every other threshold in this
# codebase — how many events get returned when the caller doesn't ask
# for a specific limit.
DEFAULT_LIMIT = 50


class HistoryService:
    """Derived-only read view over existing download_requests/local_files
    rows — 'recently downloaded and tagged tracks, in one place' (the
    History page's own subtitle). No new table: nothing here is an
    append-only log. That's a real, honest limit, not an implementation
    detail — an event's continued presence depends on the row it was
    derived from still existing in the shape that produced it. Deleting
    a downloaded file via the Duplicates tab, or a track losing its
    track_matches row, makes the corresponding event silently stop
    appearing on the very next call — this reflects "what the DB
    currently knows happened," not a permanent audit trail.
    """

    def __init__(
            self,
            database: Database,
            download_request_repository: DownloadRequestRepository,
            local_file_repository: LocalFileRepository,
            track_match_repository: TrackMatchRepository,
            track_repository: TrackRepository,
            playlist_repository: PlaylistRepository,
    ):
        self.database = database
        self.download_requests = download_request_repository
        self.local_files = local_file_repository
        self.track_matches = track_match_repository
        self.tracks = track_repository
        self.playlists = playlist_repository

    def get_recent_events(self, limit: int = DEFAULT_LIMIT) -> list[HistoryEvent]:
        with self.database.transaction() as connection:
            requests = self.download_requests.get_all(connection)
            local_files = self.local_files.get_all(connection)
            track_matches_by_local_file_id: dict[int, list[TrackMatch]] = {}
            for local_file in local_files:
                if local_file.id is None:
                    continue
                track_matches_by_local_file_id[local_file.id] = (
                    self.track_matches.get_by_local_file_id(
                        local_file.id, connection,
                    )
                )
            tracks_by_id = {
                track.id: track for track in self.tracks.get_all(connection)
            }
            playlist_names_by_track_id = (
                self.playlists.get_playlist_names_by_track_id(connection)
            )

        events: list[HistoryEvent] = []

        # Same collapsing rule as DashboardService.get_active_downloads /
        # DownloadService._retry_locked_request — a stale duplicate row
        # for the exact same real candidate (left over from before item
        # 16's creation-time dedup guard was fully effective) must not
        # show up as two separate "downloaded" events for one real
        # download.
        deduplicated_requests = most_recent_per_candidate(requests).values()

        for request in deduplicated_requests:
            if request.status not in TERMINAL_STATUSES:
                continue
            if request.status != "completed" or not request.completed_at:
                continue

            track = tracks_by_id.get(request.track_id)
            if track is None:
                continue

            playlist_names = playlist_names_by_track_id.get(
                request.track_id, [],
            )

            events.append(
                HistoryEvent(
                    occurred_at=request.completed_at,
                    event_type=DOWNLOADED,
                    track_title=track.title,
                    track_artist=track.artist,
                    playlist_name=resolve_playlist_label(
                        request.track_id, playlist_names,
                    ),
                    detail=f"{request.format.upper()} from {request.username}",
                )
            )

        for local_file in local_files:
            if local_file.id is None or local_file.tagged_at is None:
                continue

            matches = track_matches_by_local_file_id.get(local_file.id, [])
            if not matches:
                continue

            track = tracks_by_id.get(matches[0].track_id)
            if track is None:
                continue

            playlist_names = playlist_names_by_track_id.get(track.id, [])

            events.append(
                HistoryEvent(
                    occurred_at=local_file.tagged_at,
                    event_type=TAGGED,
                    track_title=track.title,
                    track_artist=track.artist,
                    playlist_name=resolve_playlist_label(
                        track.id, playlist_names,
                    ),
                    detail="Tagged with Spotify metadata",
                )
            )

        events.sort(key=lambda event: event.occurred_at, reverse=True)

        return events[:limit]

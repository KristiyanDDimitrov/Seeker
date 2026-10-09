"""The daily sweep: search slskd again for the loaded playlists'
missing tracks.

Nothing else looks again at a track that came up Not found, or whose
request went unavailable; the locked-retry loop only re-asks the same
peer (HISTORY §202). The sweep never calls Spotify: it works from the
cached playlists, so it costs no API budget.
"""
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.error_text import describe_error
from seeker.models.download_result import TrackFailure, TrackSearchOutcome
from seeker.models.sweep_result import SweepResult
from seeker.soulseek.client import SlskdUnreachableError
from seeker.soulseek.download_service import DownloadService

logger = logging.getLogger(__name__)

# The most slskd searches one sweep runs. A search takes up to ~47 s
# (SoulseekClient.search's 45 s deadline plus a poll), so 50 bounds a
# sweep near 40 minutes. Untuned.
SWEEP_MAX_SEARCHES = 50

SWEEP_INTERVAL = timedelta(hours=24)


def sweep_due(now: datetime, last_sweep_at: str | None, enabled: bool) -> bool:
    """Whether the automatic sweep should run at `now` (timezone-aware).

    Due when enabled and it has never run, or SWEEP_INTERVAL has
    passed. A last_sweep_at that does not parse as an aware time, or
    lies in the future (the clock went back), counts as due: the
    sweep's own stamp then repairs it.
    """
    if not enabled:
        return False

    if last_sweep_at is None:
        return True

    try:
        last = datetime.fromisoformat(last_sweep_at)
    except ValueError:
        return True

    if last.tzinfo is None or last > now:
        return True

    return now - last >= SWEEP_INTERVAL


class SweepService:
    def __init__(
            self,
            database: Database,
            get_download_service: Callable[[], DownloadService],
            playlist_repository: PlaylistRepository,
            track_repository: TrackRepository,
            get_config: Callable[[], SeekerConfig],
            record_sweep: Callable[[str], None],
            max_searches: int = SWEEP_MAX_SEARCHES,
    ):
        self.database = database
        self._get_download_service = get_download_service
        self.playlists = playlist_repository
        self.tracks = track_repository
        self._get_config = get_config
        # Called with the finish time (UTC ISO-8601) of a sweep that
        # ran to the end; Application persists it as last_sweep_at.
        self._record_sweep = record_sweep
        self._max_searches = max_searches

    def run_sweep(self, stop: threading.Event | None = None) -> SweepResult:
        """Searches for up to `max_searches` missing tracks and requests
        what it finds, through download_playlist's own per-track step.

        A set `stop` ends the sweep before its next search, unrecorded,
        like a pause: the app sets it on quit.

        Raises SlskdUnreachableError, recording no sweep, when slskd
        stops answering: every later search would fail the same way.
        """
        if self._get_config().downloads_paused:
            logger.info("Sweep skipped: downloads are paused.")
            return SweepResult(paused=True)

        downloads = self._get_download_service()
        result = SweepResult()

        with self.database.transaction() as connection:
            playlists = [
                playlist for playlist in self.playlists.get_all(connection)
                if playlist.tracks_snapshot_id is not None
            ]

        sweepable = []

        for playlist in playlists:
            if downloads.placement.resolve_destination(playlist) is None:
                result.playlists_without_destination.append(playlist.name)
            else:
                sweepable.append(playlist.id)

        with self.database.transaction() as connection:
            tracks = self.tracks.get_unmatched_for_playlists(
                sweepable, connection,
            )

        logger.info(
            "Sweep: %d missing track(s) across %d playlist(s); "
            "searching up to %d.",
            len(tracks), len(sweepable), self._max_searches,
        )
        thresholds = downloads.current_thresholds()

        for track in tracks:
            label = f"{track.artist} - {track.title}"

            if result.searched >= self._max_searches:
                result.deferred.append(label)
                continue

            # Read fresh before every search: a pause during a long
            # sweep stops it, like the poll (HISTORY §90).
            if self._get_config().downloads_paused:
                result.paused = True
                break

            if stop is not None and stop.is_set():
                result.stopped = True
                break

            try:
                outcome = downloads.search_and_request(track, thresholds)
            except httpx.TransportError as error:
                logger.warning(
                    "Sweep stopped after %d searches: slskd is not "
                    "answering (%s).", result.searched, error,
                )
                raise SlskdUnreachableError(
                    downloads.soulseek.base_url,
                ) from error
            except Exception as error:
                result.failures.append(TrackFailure(
                    label, describe_error(error, details_hint=""),
                ))
                logger.warning("Sweep failed on %s: %s", label, error)
                continue

            if outcome == TrackSearchOutcome.REQUESTED:
                result.requested.append(label)
            elif outcome == TrackSearchOutcome.ALREADY_IN_PROGRESS:
                result.already_in_progress.append(label)
            else:
                result.still_missing.append(label)

        if result.paused or result.stopped:
            # Not recorded: the next due check starts it again, oldest
            # tracks first.
            logger.info(
                "Sweep stopped after %d searches: %s.", result.searched,
                "downloads were paused" if result.paused else "Seeker is quitting",
            )
            return result

        self._record_sweep(datetime.now(UTC).isoformat())
        logger.info(
            "Sweep finished: searched %d, requested %d, still missing %d, "
            "failed %d; %d already in progress, %d left for the next "
            "sweep, %d playlist(s) without a destination.",
            result.searched, len(result.requested),
            len(result.still_missing), len(result.failures),
            len(result.already_in_progress), len(result.deferred),
            len(result.playlists_without_destination),
        )

        return result

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from seeker.audio.formats import (
    downloadable_formats_text,
    is_downloadable_extension,
)
from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.rejection_repository import (
    RejectionRepository,
)
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.destination_resolution import (
    validate_destination_subfolder,
)
from seeker.error_text import describe_error
from seeker.errors import (
    LibraryLocationNotFoundError,
    PlaylistNotFoundError,
    SeekerError,
)
from seeker.matching import resolve_thresholds
from seeker.models.download_request import (
    FAILED_OUTCOMES,
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.download_result import (
    ManualDownloadResult,
    PlaylistDownloadResult,
    PollResult,
    TrackFailure,
    TrackSearchOutcome,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import MANUAL_TRACK_ID_PREFIX, Track
from seeker.soulseek.client import (
    SoulseekClient,
    SoulseekDownloadError,
)
from seeker.soulseek.placement import DownloadPlacement
from seeker.soulseek.poller import DownloadPoller
from seeker.soulseek.quality import select_downloads

logger = logging.getLogger(__name__)

# How long a peer's file that ran out its locked-retry budget stays out
# of a new search for the same track: asking again soon most likely
# reruns the same refusals (a locked file sits in a share its peer
# opened to some users only; UNVERIFIED how often one reopens).
# Another peer's copy is still requested. Untuned.
UNAVAILABLE_COOLDOWN = timedelta(days=30)


class NoDestinationConfiguredError(SeekerError):
    pass


class UnsupportedDownloadFormatError(SeekerError):
    """An explicit per-row Download pick (download_manual's
    chosen=) bypasses select_downloads' ranking/threshold entirely —
    including the DOWNLOADABLE_EXTENSIONS gate that normally lives
    there — so this is the final guard at request time. A refused
    click must say so loudly, not do nothing (HISTORY §94)."""

    def __init__(self, extension: str):
        super().__init__(
            f"Seeker only downloads {downloadable_formats_text()} — this one is "
            f".{extension.lower().lstrip('.')}."
        )


class DownloadNotRetryableError(SeekerError):
    """Retry was asked for a request that is gone or has not failed:
    another window cleared it, or the poll moved it on."""

    def __init__(self) -> None:
        super().__init__(
            "That download is no longer a failed one, so there is "
            "nothing to retry."
        )


def _build_search_query(artist: str, title: str) -> str:
    # artist may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla") — strip the comma for the actual search string
    # rather than sending it literally. Soulseek search matching isn't
    # guaranteed to ignore stray punctuation, so a literal "MK," glued to
    # the first name risks not matching filenames that don't happen to
    # have that exact comma placement.
    #
    # Takes plain artist/title strings, not a Track, so a manual
    # (not-from-Spotify) search shares this exact construction with
    # download_playlist rather than a second, drifting copy.
    artist_query = artist.replace(",", " ")

    return " ".join(f"{artist_query} {title}".split())


def _quality_descriptor(file: SoulseekFile) -> str:
    descriptor = file.extension

    if file.bit_rate:
        descriptor += f" {file.bit_rate}kbps"

    return descriptor


class DownloadService:
    def __init__(
        self,
        database: Database,
        soulseek_client: SoulseekClient | None,
        playlist_repository: PlaylistRepository,
        track_repository: TrackRepository,
        library_location_repository: LibraryLocationRepository,
        download_request_repository: DownloadRequestRepository,
        track_match_repository: TrackMatchRepository,
        local_file_repository: LocalFileRepository,
        soulseek_review_candidate_repository: SoulseekReviewCandidateRepository,
        slskd_download_dir: str | None,
        get_config: Callable[[], SeekerConfig] | None = None,
        rejection_repository: RejectionRepository | None = None,
    ):
        self.database = database
        # None only when SoulSeek genuinely isn't configured — Settings
        # needs to construct a real, usable DownloadService for
        # set_destination() (which never touches SoulSeek at all)
        # without a working slskd connection. A method
        # that DOES need it (download_playlist, poll_downloads, ...)
        # raises a clear error via the `soulseek` property below,
        # rather than making construction itself impossible the way
        # Application.soulseek_client's own eager raise already does
        # for anything that goes through it directly.
        self._soulseek_client = soulseek_client
        self.playlists = playlist_repository
        self.tracks = track_repository
        self.locations = library_location_repository
        self.download_requests = download_request_repository
        self.track_matches = track_match_repository
        self.local_files = local_file_repository
        self.soulseek_review_candidates = soulseek_review_candidate_repository
        self.rejections = rejection_repository or RejectionRepository()
        # See matcher.py's identical get_config comment — a callable,
        # not a snapshot, so a Settings-driven threshold change is
        # visible on the very next download_playlist() call without
        # needing DownloadService itself reconstructed.
        self._get_config = get_config or SeekerConfig
        self.placement = DownloadPlacement(
            database,
            playlist_repository,
            track_repository,
            library_location_repository,
            local_file_repository,
            track_match_repository,
            slskd_download_dir,
            self._get_config,
        )
        self.poller = DownloadPoller(
            database,
            lambda: self.soulseek,
            self.placement,
            download_request_repository,
            track_match_repository,
            self._get_config,
        )

    @property
    def soulseek(self) -> SoulseekClient:
        if self._soulseek_client is None:
            raise RuntimeError(
                "SoulSeek is not configured (SLSKD_BASE_URL/SLSKD_API_KEY)."
            )

        return self._soulseek_client

    def set_destination(
        self,
        playlist_name: str,
        location_name: str,
        subfolder: str | None = None,
    ) -> None:
        """Raises InvalidDestinationSubfolderError, saving nothing, for
        a subfolder that is unsafe or would leave the location."""
        subfolder = validate_destination_subfolder(subfolder)

        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

            location = self.locations.get_by_name(location_name, connection)

            if location is None:
                raise LibraryLocationNotFoundError(
                    f"No library location named '{location_name}' is "
                    f"registered."
                )

            # Loaded from the DB via get_by_name above, so .id is set.
            assert location.id is not None

            self.playlists.set_destination(
                playlist.id,
                location.id,
                subfolder,
                connection,
            )

        suffix = f"/{subfolder}" if subfolder else ""
        logger.info(
            "'%s' will download to '%s'%s", playlist_name, location_name,
            suffix,
        )

    def get_resolved_destination(
            self,
            playlist_name: str,
    ) -> tuple[LibraryLocation, str | None] | None:
        """Read-only — the UI's own check before ever calling
        download_playlist(): resolvable now (a playlist-specific
        destination, or the configured default) means proceed straight
        to the real download; None means show the "set a destination"
        dialog first rather than letting download_playlist() raise
        NoDestinationConfiguredError and dead-end the user. Shares
        DownloadPlacement.resolve_destination with the real move step, so this is never
        a second, drifting notion of "resolvable."
        """
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

        return self.placement.resolve_destination(playlist)

    def download_playlist(
            self, playlist_name: str,
    ) -> PlaylistDownloadResult:
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

            if self.placement.resolve_destination(playlist) is None:
                # Interface-neutral wording, deliberately — this
                # exception is shared by both the CLI and the UI (a
                # GUI-facing message must never tell someone to run a
                # shell command). The CLI's own handler appends its own
                # command-line guidance when it catches this; the UI
                # instead proactively resolves the destination via a
                # real dialog before ever calling download_playlist()
                # with none configured, so it should only ever see this
                # in a genuine race.
                raise NoDestinationConfiguredError(
                    f"'{playlist_name}' has no download destination "
                    f"configured yet."
                )

            unmatched_tracks = self.tracks.get_unmatched_for_playlist(
                playlist.id,
                connection,
            )

        # Resolved once for the whole run, not per track — thresholds
        # don't change mid-run, and re-reading config per track would
        # just be wasted work. Still re-resolved on every
        # download_playlist() call, so a Settings-driven change takes
        # effect on the next run with no restart needed.
        thresholds = self.current_thresholds()

        result = PlaylistDownloadResult(total=len(unmatched_tracks))

        for track in unmatched_tracks:
            label = f"{track.artist} - {track.title}"

            # One bad track (search timeout, malformed response, a
            # transient network error — anything) must not silently
            # abort every track after it in the batch. Every track ends
            # up in exactly one bucket: requested, skipped (no real
            # candidates), or failed (with a printed reason) — never
            # dropped without being counted anywhere.
            try:
                outcome = self.search_and_request(track, thresholds)
            except Exception as error:
                result.failures.append(TrackFailure(
                    label, describe_error(error, details_hint=""),
                ))
                logger.warning(
                    "Failed: %s - %s: %s", track.artist, track.title, error,
                )
                continue

            if outcome == TrackSearchOutcome.REQUESTED:
                result.requested += 1
                continue

            result.skipped += 1

            if outcome == TrackSearchOutcome.ALREADY_IN_PROGRESS:
                result.already_in_progress.append(label)
            elif outcome == TrackSearchOutcome.NEEDS_REVIEW:
                result.needs_review.append(label)

        return result

    def current_thresholds(self) -> tuple[float, float]:
        """The auto-match and needs-review thresholds in force now."""
        config = self._get_config()

        return resolve_thresholds(
            config.auto_match_threshold, config.needs_review_threshold,
        )

    def search_and_request(
            self,
            track: Track,
            thresholds: tuple[float, float],
    ) -> TrackSearchOutcome:
        """Searches slskd for one unmatched track and requests or
        records the best candidate. Raises whatever the search or the
        request raises; a caller running a batch decides what one
        track's failure means for the rest."""
        auto_match_threshold, needs_review_threshold = thresholds

        with self.database.transaction() as connection:
            blocking = (
                self.download_requests
                .get_requests_blocking_redownload(
                    track.id, connection,
                )
            )

        if blocking:
            # A request for this exact track is already in
            # flight (queued/downloading/locked/shortlisted/
            # ready_for_review) OR already completed —
            # re-running download_playlist must not pile on a
            # duplicate, otherwise-identical row for the same
            # candidate, and must not re-download a track
            # that's already sitting in the library
            # (HISTORY §16, §45).
            statuses = ", ".join(
                sorted({request.status for request in blocking})
            )
            logger.info(
                "Already in progress for %s - %s (%s) — skipping.",
                track.artist, track.title, statuses,
            )
            return TrackSearchOutcome.ALREADY_IN_PROGRESS

        logger.info("Searching: %s - %s", track.artist, track.title)

        # Stamped before the search, so a track whose search keeps
        # failing still moves to the back of the sweep's queue.
        with self.database.transaction() as connection:
            self.tracks.mark_searched(
                track.id, datetime.now(UTC).isoformat(), connection,
            )

        files = self._without_rejected(
            track.id,
            self.soulseek.search(
                _build_search_query(track.artist, track.title)
            ),
        )
        selection = select_downloads(
            track, files, auto_match_threshold, needs_review_threshold,
        )
        settled = selection.settled
        upgrade_shortlist = selection.upgrade_shortlist
        needs_review = selection.needs_review

        if settled is not None or upgrade_shortlist:
            # Something real and auto-tier exists for this track
            # now (downloaded, or locked but chased via the
            # upgrade cascade) — any needs_review row from an
            # earlier, worse run is stale information and must
            # not keep being surfaced by `seeker check`.
            self._clear_review_candidate(track.id)

        if settled is None:
            if upgrade_shortlist:
                # Nothing practical/unlocked, but select_downloads
                # still found a real, above-threshold candidate —
                # e.g. every filtered match is locked. Request it
                # the same way an upgrade is normally requested
                # (role='upgrade') so it lands in poll_downloads'
                # existing locked-retry cascade instead of being
                # silently discarded. Counted as requested, not
                # skipped — a real download WAS requested, just
                # not a settled one.
                logger.info(
                    "No practical candidate — requesting "
                    "locked/upgrade-only candidate(s)."
                )
                self._request_upgrade_shortlist(
                    track, upgrade_shortlist
                )
                return TrackSearchOutcome.REQUESTED

            if needs_review is not None:
                # No auto-tier candidate at all, but a real,
                # plausible one exists (70-89) — record it for
                # `seeker check` to surface, rather than letting
                # it silently vanish. Never requested from slskd
                # on its own; a human confirms manually.
                review_file, review_score, runner_up = needs_review
                self._record_review_candidate(
                    track, review_file, review_score, runner_up,
                )
                logger.info(
                    "No auto-match candidate — needs-review "
                    "candidate found (score %.1f): %s: %s",
                    review_score, review_file.username,
                    review_file.filename,
                )
                return TrackSearchOutcome.NEEDS_REVIEW

            logger.info("No candidates found.")
            return TrackSearchOutcome.NO_CANDIDATE

        self._request_and_record(track, settled, role=DownloadRole.SETTLED)
        logger.info(
            "Requested from %s: %s", settled.username,
            settled.filename,
        )

        if upgrade_shortlist:
            # The settled file is already on its way, so a peer
            # refusing the upgrade leaves the track requested, not
            # failed.
            try:
                self._request_upgrade_shortlist(track, upgrade_shortlist)
            except SoulseekDownloadError as error:
                logger.warning(
                    "Upgrade not requested for %s - %s: %s",
                    track.artist, track.title, error,
                )

        return TrackSearchOutcome.REQUESTED

    def retry_download(self, download_request_id: int) -> TrackSearchOutcome:
        """Searches again for a failed or unavailable request's track,
        rather than re-asking the peer that failed it; an unavailable
        candidate stays skipped for UNAVAILABLE_COOLDOWN. Once a new
        request is made, the retried row is dismissed: the new row
        stands for the track now. Otherwise it stays, still the user's
        to act on."""
        with self.database.transaction() as connection:
            request = self.download_requests.get_by_id(
                download_request_id, connection,
            )
            track = (
                self.tracks.get_by_id(request.track_id, connection)
                if request is not None
                else None
            )

        if (
                request is None
                or request.status not in FAILED_OUTCOMES
                or track is None
        ):
            raise DownloadNotRetryableError

        outcome = self.search_and_request(track, self.current_thresholds())

        if outcome == TrackSearchOutcome.REQUESTED:
            with self.database.transaction() as connection:
                self.download_requests.dismiss(
                    download_request_id, datetime.now(UTC).isoformat(),
                    connection,
                )

        return outcome

    def search_manual(self, artist: str, title: str) -> list[SoulseekFile]:
        """A real SoulSeek search for a track that isn't in any Spotify
        playlist, using the exact same query construction
        download_playlist uses (_build_search_query) — never a second,
        drifting copy. Read-only: no track row, no download_requests
        row, nothing persisted. A real search takes 20-45s (client.py's
        own documented real-world timing) — the caller (UI/CLI) is
        responsible for showing that it's busy.
        """
        return self.soulseek.search(_build_search_query(artist, title))

    def download_manual(
            self,
            artist: str,
            title: str,
            chosen: SoulseekFile | None = None,
            files: list[SoulseekFile] | None = None,
    ) -> ManualDownloadResult:
        """Search for and download a track that isn't in any Spotify
        playlist, reusing the same "best quality available, fall back
        until something actually downloads" behavior as a playlist
        download (select_downloads), no new ranking logic. A request
        creates a real `tracks` row (id `manual:<uuid4>`, album="",
        duration_ms=0 — see DownloadPlacement.index_and_match's own
        comment on why a placeholder duration doesn't affect the
        immediate post-download match) belonging to no playlist. No
        request, no row: a search that finds nothing or fails, or a
        first request that fails, leaves nothing behind.

        `chosen`, when given (an explicit per-row "Download"
        pick), bypasses select_downloads' ranking/threshold entirely
        and requests exactly that file as role='settled': the user's
        own explicit choice is a stronger signal than any threshold,
        the same reasoning HISTORY §26 already applies to a
        human-confirmed needs-review candidate.

        `files`, when given, skips a second real 20-45s network search
        — the UI's own results table (already populated via
        search_manual()) is reused rather than searched again for the
        headline "Download best" action. Omit it (e.g. the CLI's
        `--download`, which never has a prior search in hand) to search
        fresh.
        """
        if self.placement.resolve_destination(None) is None:
            # Checked before creating a track row or running a real
            # 20-45s search — same "no destination configured" contract
            # as download_playlist (the CLI appends its own guidance;
            # the UI reuses this exact exception to route to Settings).
            raise NoDestinationConfiguredError(
                "No download destination is configured yet."
            )

        if chosen is not None and not is_downloadable_extension(
                chosen.extension,
        ):
            # chosen bypasses select_downloads (and its own
            # DOWNLOADABLE_EXTENSIONS gate) entirely, so this is the
            # final check at request time (see UnsupportedDownloadFormatError).
            raise UnsupportedDownloadFormatError(chosen.extension)

        track = Track(
            id=f"{MANUAL_TRACK_ID_PREFIX}{uuid4()}",
            title=title,
            artist=artist,
            album="",
            duration_ms=0,
        )

        if chosen is not None:
            self._save_manual_track_and_request(
                track,
                lambda: self._request_and_record(
                    track, chosen, role=DownloadRole.SETTLED,
                ),
            )
            logger.info(
                "Requested from %s: %s", chosen.username, chosen.filename,
            )
            return ManualDownloadResult(
                track_id=track.id,
                requested=True,
                settled=True,
                username=chosen.username,
                filename=chosen.filename,
            )

        config = self._get_config()
        auto_match_threshold, needs_review_threshold = resolve_thresholds(
            config.auto_match_threshold, config.needs_review_threshold,
        )

        search_results = (
            files if files is not None
            else self.soulseek.search(_build_search_query(artist, title))
        )

        selection = select_downloads(
            track, search_results, auto_match_threshold, needs_review_threshold,
        )
        settled = selection.settled
        upgrade_shortlist = selection.upgrade_shortlist

        if settled is None and not upgrade_shortlist:
            return ManualDownloadResult(
                track_id=track.id,
                requested=False,
                settled=False,
                reason="no_candidate_found",
            )

        if settled is not None:
            self._save_manual_track_and_request(
                track,
                lambda: self._request_and_record(
                    track, settled, role=DownloadRole.SETTLED,
                ),
            )
            logger.info(
                "Requested from %s: %s", settled.username, settled.filename,
            )

            if upgrade_shortlist:
                self._request_upgrade_shortlist(track, upgrade_shortlist)

            return ManualDownloadResult(
                track_id=track.id,
                requested=True,
                settled=True,
                username=settled.username,
                filename=settled.filename,
            )

        # Nothing practical/unlocked, but select_downloads still found
        # real above-threshold candidate(s) — every one of them locked.
        # Requested the same way a locked-only playlist track is (see
        # download_playlist above): lands in poll_downloads' existing
        # locked-retry cascade instead of being silently discarded.
        logger.info(
            "No practical candidate — requesting locked/upgrade-only "
            "candidate(s)."
        )
        self._save_manual_track_and_request(
            track,
            lambda: self._request_upgrade_shortlist(track, upgrade_shortlist),
        )
        return ManualDownloadResult(
            track_id=track.id,
            requested=True,
            settled=False,
            reason="locked_only",
        )

    def _save_manual_track_and_request(
            self,
            track: Track,
            request: Callable[[], None],
    ) -> None:
        """Saves a manual track just before its first request. Only a
        request makes a manual track real, so if that request fails
        the track goes again.
        """
        with self.database.transaction() as connection:
            self.tracks.save(track, connection)

        try:
            request()
        except Exception:
            with self.database.transaction() as connection:
                self.tracks.delete_if_unrequested(track.id, connection)
            raise

    def _request_upgrade_shortlist(
            self,
            track: Track,
            upgrade_shortlist: list[SoulseekFile],
    ) -> None:
        # Shared by both call sites: the normal "settled found, plus a
        # better upgrade exists" path, and the "nothing settled, but a
        # real (possibly locked-only) candidate exists" path. Rank 1 is
        # requested immediately; the rest are persisted but not sent to
        # slskd until poll_downloads' cascade needs them.
        top = upgrade_shortlist[0]
        self._request_and_record(track, top, role=DownloadRole.UPGRADE, rank=1)
        logger.info(
            "Requested upgrade from %s: %s (rank 1)",
            top.username, top.filename,
        )

        for rank, candidate in enumerate(upgrade_shortlist[1:], start=2):
            self._record_shortlisted(track, candidate, rank=rank)
            logger.info(
                "Shortlisted upgrade candidate from %s: %s (rank %d)",
                candidate.username, candidate.filename, rank,
            )

    def _request_and_record(
            self,
            track: Track,
            file: SoulseekFile,
            role: DownloadRole,
            rank: int | None = None,
    ) -> None:
        # No destination is passed here for either role — the file lands
        # in slskd's own download dir and is moved out by seeker, whether
        # immediately (settled) or on user confirmation (upgrade).
        transfer_id = self.soulseek.request_download(
            file.username,
            file.filename,
            file.size,
        )

        with self.database.transaction() as connection:
            self.download_requests.add(
                DownloadRequest(
                    track_id=track.id,
                    username=file.username,
                    filename=file.filename,
                    format=file.extension,
                    quality_descriptor=_quality_descriptor(file),
                    role=role,
                    rank=rank,
                    transfer_id=transfer_id,
                    size=file.size,
                    requested_at=datetime.now(UTC).isoformat(),
                ),
                connection,
            )

    def _record_shortlisted(
            self,
            track: Track,
            file: SoulseekFile,
            rank: int,
    ) -> None:
        # Known and persisted, but not yet sent to slskd — request_download
        # only happens once a higher-ranked entry for this track is
        # rejected (see DownloadPoller._cascade_upgrade).
        with self.database.transaction() as connection:
            self.download_requests.add(
                DownloadRequest(
                    track_id=track.id,
                    username=file.username,
                    filename=file.filename,
                    format=file.extension,
                    quality_descriptor=_quality_descriptor(file),
                    role=DownloadRole.UPGRADE,
                    status=DownloadStatus.SHORTLISTED,
                    rank=rank,
                    size=file.size,
                    requested_at=datetime.now(UTC).isoformat(),
                ),
                connection,
            )

    def _record_review_candidate(
            self,
            track: Track,
            file: SoulseekFile,
            score: float,
            runner_up: tuple[SoulseekFile, float] | None = None,
    ) -> None:
        runner_up_file, runner_up_score = (
            runner_up if runner_up is not None else (None, None)
        )
        with self.database.transaction() as connection:
            self.soulseek_review_candidates.upsert(
                SoulseekReviewCandidate(
                    track_id=track.id,
                    username=file.username,
                    filename=file.filename,
                    score=score,
                    quality_descriptor=_quality_descriptor(file),
                    found_at=datetime.now(UTC).isoformat(),
                    size=file.size,
                    runner_up_username=(
                        runner_up_file.username
                        if runner_up_file is not None else None
                    ),
                    runner_up_filename=(
                        runner_up_file.filename
                        if runner_up_file is not None else None
                    ),
                    runner_up_score=runner_up_score,
                ),
                connection,
            )

    def _clear_review_candidate(self, track_id: str) -> None:
        with self.database.transaction() as connection:
            self.soulseek_review_candidates.delete(track_id, connection)

    def _without_rejected(
            self,
            track_id: str,
            files: list[SoulseekFile],
    ) -> list[SoulseekFile]:
        """`files` less a person's Rejects for this track, and less any
        peer's file that went unavailable for it within
        UNAVAILABLE_COOLDOWN."""
        since = (datetime.now(UTC) - UNAVAILABLE_COOLDOWN).isoformat()

        with self.database.transaction() as connection:
            excluded = self.rejections.get_rejected_soulseek_candidates(
                track_id, connection,
            ) | self.download_requests.get_unavailable_candidates_since(
                track_id, since, connection,
            )

        return [
            file for file in files
            if (file.username, file.filename) not in excluded
        ]

    def poll_downloads(self) -> PollResult:
        return self.poller.poll_downloads()

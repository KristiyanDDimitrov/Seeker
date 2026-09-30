import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from seeker.audio_formats import (
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
from seeker.download_dedup import candidate_key, most_recent_per_candidate
from seeker.error_text import describe_error
from seeker.errors import (
    LibraryLocationNotFoundError,
    PlaylistNotFoundError,
    SeekerError,
)
from seeker.matching import AUTO_MATCH_THRESHOLD, NEEDS_REVIEW_THRESHOLD
from seeker.models.download_request import (
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.download_result import (
    ManualDownloadResult,
    PlaylistDownloadResult,
    PollResult,
    TrackFailure,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import MANUAL_TRACK_ID_PREFIX, Track
from seeker.soulseek.client import (
    SlskdUnreachableError,
    SoulseekClient,
    SoulseekDownloadError,
    TransferStatus,
    is_recognized_rejection,
)
from seeker.soulseek.placement import DownloadPlacement
from seeker.soulseek.quality import select_downloads

logger = logging.getLogger(__name__)


# Bounds the locked retry loop (HISTORY §63/§66 — a real production
# storm retried one row 300+ times in ~18 minutes, root cause still
# unknown but now structurally capped regardless). All three untuned —
# real numbers to revisit once real usage data exists, same convention
# as every other threshold in this codebase.
LOCKED_RETRY_BASE_SECONDS = 60
LOCKED_RETRY_MAX_SECONDS = 3600
LOCKED_RETRY_MAX_ATTEMPTS = 8

# Soulseek.TransferStates is a [Flags] enum — slskd reports it as a
# comma-joined string (e.g. "Completed, Succeeded"). Check failure markers
# first since a transfer can be "Completed" without having succeeded.
FAILED_STATE_MARKERS = (
    "Cancelled",
    "TimedOut",
    "Errored",
    "Rejected",
    "Aborted",
)

# The label a failed transfer's reason starts with, by state flag.
# "Rejected" is absent: a rejection is the peer's decision, and
# describe_rejection() words it as one.
_FAILED_STATE_LABELS = (
    ("TimedOut", "Timed out"),
    ("Errored", "Transfer error"),
    ("Cancelled", "Cancelled"),
    ("Aborted", "Aborted"),
)

_REJECTION_PREFIX = "transfer rejected:"


def describe_rejection(text: str | None) -> str:
    """A peer's rejection as a user reads it: slskd's own words, minus
    its "Transfer rejected:" framing ("Peer rejected: file not
    shared")."""
    detail = (text or "").strip()

    if detail.lower().startswith(_REJECTION_PREFIX):
        detail = detail[len(_REJECTION_PREFIX):].strip()

    detail = detail.rstrip(".")

    if not detail:
        return "Peer rejected the transfer"

    return f"Peer rejected: {detail[0].lower()}{detail[1:]}"


def describe_transfer_failure(state: str, exception_text: str | None) -> str:
    """Why a transfer slskd reports as failed (any FAILED_STATE_MARKERS
    flag) failed, from its state and its `exception` text."""
    if "Rejected" in state:
        return describe_rejection(exception_text)

    label = next(
        (label for marker, label in _FAILED_STATE_LABELS if marker in state),
        "Transfer failed",
    )

    return f"{label}: {exception_text}" if exception_text else label


class NoDestinationConfiguredError(SeekerError):
    pass


class UnsupportedDownloadFormatError(SeekerError):
    """An explicit per-row 'Download this one' pick (download_manual's
    chosen=) bypasses select_downloads' ranking/threshold entirely —
    including the DOWNLOADABLE_EXTENSIONS gate that normally lives
    there — so this is the final guard at request time. A refused
    click must say so loudly, not do nothing (HISTORY §94)."""

    def __init__(self, extension: str):
        super().__init__(
            f"Seeker only downloads {downloadable_formats_text()} — this one is "
            f".{extension.lower().lstrip('.')}."
        )


def _in_flight_status(state: str) -> DownloadStatus:
    return (
        DownloadStatus.QUEUED if state == "Requested"
        else DownloadStatus.DOWNLOADING
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
        config = self._get_config()
        auto_match_threshold = (
            config.auto_match_threshold or AUTO_MATCH_THRESHOLD
        )
        needs_review_threshold = (
            config.needs_review_threshold or NEEDS_REVIEW_THRESHOLD
        )

        result = PlaylistDownloadResult(total=len(unmatched_tracks))

        for track in unmatched_tracks:
            # One bad track (search timeout, malformed response, a
            # transient network error — anything) must not silently
            # abort every track after it in the batch. Every track ends
            # up in exactly one bucket: requested, skipped (no real
            # candidates), or failed (with a printed reason) — never
            # dropped without being counted anywhere.
            try:
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
                    result.skipped += 1
                    result.already_in_progress.append(
                        f"{track.artist} - {track.title}"
                    )
                    continue

                logger.info("Searching: %s - %s", track.artist, track.title)

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
                        result.requested += 1
                    elif needs_review is not None:
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
                        result.skipped += 1
                        result.needs_review.append(
                            f"{track.artist} - {track.title}"
                        )
                    else:
                        logger.info("No candidates found.")
                        result.skipped += 1
                    continue

                self._request_and_record(track, settled, role=DownloadRole.SETTLED)
                logger.info(
                    "Requested from %s: %s", settled.username,
                    settled.filename,
                )
                result.requested += 1

                if upgrade_shortlist:
                    self._request_upgrade_shortlist(track, upgrade_shortlist)
            except Exception as error:
                result.failures.append(TrackFailure(
                    f"{track.artist} - {track.title}",
                    describe_error(error, details_hint=""),
                ))
                logger.warning(
                    "Failed: %s - %s: %s", track.artist, track.title, error,
                )

        return result

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

        `chosen`, when given (an explicit per-row "Download this one"
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
        auto_match_threshold = (
            config.auto_match_threshold or AUTO_MATCH_THRESHOLD
        )
        needs_review_threshold = (
            config.needs_review_threshold or NEEDS_REVIEW_THRESHOLD
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
        # rejected (see the poll_downloads cascade below).
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
        with self.database.transaction() as connection:
            rejected = self.rejections.get_rejected_soulseek_candidates(
                track_id, connection,
            )

        return [
            file for file in files
            if (file.username, file.filename) not in rejected
        ]

    def poll_downloads(self) -> PollResult:
        # A timestamped call-frequency trace for the still-open
        # locked-retry storm (HISTORY §63, §66); SEEKER_DEBUG_POLL=1
        # turns this logger's DEBUG on at startup.
        logger.debug(
            "[poll_downloads] %s called", datetime.now(UTC).isoformat(),
        )

        # Checked here, not just in the UI's own timer, so pausing is
        # authoritative regardless of caller: no real slskd network
        # call (status poll, locked-retry, upgrade cascade) happens at
        # all while paused (HISTORY §90). Read fresh via
        # self._get_config() (the same not-a-snapshot discipline every
        # other config read in this class already uses), never cached,
        # so a resume takes effect on the very next call.
        if self._get_config().downloads_paused:
            return PollResult()

        with self.database.transaction() as connection:
            pending = self.download_requests.get_pending(connection)
            locked = self.download_requests.get_locked(connection)

        logger.debug(
            "[poll_downloads] pending=%d locked=%d", len(pending), len(locked),
        )

        counts = PollResult()

        for request in pending:
            # Loaded from the DB via get_pending() above, so .id is set —
            # only a not-yet-persisted DownloadRequest has id=None, and
            # nothing here ever is one.
            assert request.id is not None

            # Same principle as download_playlist(): one bad request (a
            # network blip talking to slskd, anything) must not silently
            # stop every request after it in this run from being polled.
            try:
                if request.transfer_id is None:
                    counts.count_in_flight(request.status)
                    continue

                transfer_status = self.soulseek.get_download_status(
                    request.username,
                    request.transfer_id,
                )
                state = transfer_status.state

                if any(marker in state for marker in FAILED_STATE_MARKERS):
                    # A rejection isn't progress — progress fields stay
                    # unset here rather than zeroed, whether or not any
                    # bytes happened to move before the rejection (a
                    # rejected-before-any-bytes-moved transfer reports
                    # bytesTransferred=0, but recording that would
                    # misleadingly imply a real 0%-complete attempt
                    # rather than "never really started").
                    #
                    # Lock-pattern classification applies regardless of
                    # role: retry-worthiness is a property of the
                    # REJECTION, not of why the download was requested
                    # — a needs-review candidate confirmed as
                    # role='settled' can still be a genuinely locked
                    # file (HISTORY §26). Only the Phase 4 cascade below
                    # stays role-specific, since the shortlist/cascade
                    # mechanism is an upgrade-only concept.
                    status, reason = self._classify_failed_transfer(
                        transfer_status,
                    )
                    self._update_status(
                        request.id, status, failure_reason=reason,
                    )

                    if status == DownloadStatus.FAILED:
                        counts.failed += 1

                    if request.role == DownloadRole.UPGRADE:
                        # Try the next shortlisted candidate for this
                        # track immediately, in this same run, regardless
                        # of why this one was rejected — the exact same
                        # candidate has already failed either way, so
                        # there's no reason to wait a day before trying
                        # the next best one. Scoped to role=='upgrade'
                        # only — 'settled' has no shortlist concept, and
                        # get_next_shortlisted() isn't itself
                        # role-scoped, so calling this for a 'settled'
                        # rejection could incorrectly activate an
                        # unrelated upgrade-role shortlist entry for the
                        # same track.
                        self._cascade_upgrade(request.track_id, counts)

                    continue

                # Genuinely in progress or just succeeded — real
                # bytes-so-far/total are available either way (on a
                # completed transfer, confirmed live: bytes_transferred
                # == size). Every request reaching this point came from
                # `pending` (queued/downloading only) at the top of this
                # run, so this never fires for a locked/shortlisted/
                # superseded row.
                self._update_progress(
                    request.id,
                    transfer_status.bytes_transferred,
                    transfer_status.size,
                )

                if "Succeeded" not in state:
                    new_status = _in_flight_status(state)

                    if new_status != request.status:
                        self._update_status(request.id, new_status)

                    counts.count_in_flight(new_status)
                    continue

                if request.role == DownloadRole.UPGRADE:
                    # Leave the file in slskd's own download dir — it
                    # only moves once the user confirms the replacement
                    # below.
                    self._update_status(request.id, DownloadStatus.READY_FOR_REVIEW)
                    self._supersede_others_for_track(
                        request.track_id, request.id,
                    )
                    continue

                if self._track_already_has_a_matched_file(request.track_id):
                    # A real safety net (HISTORY §56 Phase 5.3): closes
                    # the gap the dedup guard alone can't (a candidate
                    # requested before that guard existed, or matched by
                    # some other path in the meantime). By definition
                    # this settled download is now an upgrade candidate.
                    self._update_status(request.id, DownloadStatus.READY_FOR_REVIEW)
                    self._supersede_others_for_track(
                        request.track_id, request.id,
                    )
                    continue

                move_result = self.placement.move_completed_file(request)

                if move_result is not None:
                    self._update_status(request.id, DownloadStatus.COMPLETED)
                    counts.completed += 1
                    self.placement.index_and_match(
                        request, move_result, counts,
                    )
                else:
                    counts.count_in_flight(request.status)
            except httpx.TransportError as error:
                # slskd itself is down, not this request: every later
                # request would fail the same way, and none of them
                # has failed as far as the user is concerned.
                raise SlskdUnreachableError(self.soulseek.base_url) from error
            except Exception as error:
                counts.failed += 1
                logger.warning(
                    "Failed to poll '%s': %s", request.filename, error,
                )

        # Re-issue request_download for every request that was already
        # 'locked' before this run started (not ones that just became
        # locked above, or via the cascade below — those wait for the
        # next run, matching the "daily cadence" design). Same exact
        # username+filename each time — retrying access to the same
        # candidate, not a fresh search.
        for request in locked:
            # Same principle as above — one bad retry must not stop the
            # rest of the locked shortlist from being retried this run.
            try:
                self._retry_locked_request(request, counts)
            except httpx.TransportError as error:
                raise SlskdUnreachableError(self.soulseek.base_url) from error
            except Exception as error:
                logger.warning(
                    "Failed to retry locked '%s': %s",
                    request.filename, error,
                )

        counts.ready_for_review = len(self._get_ready_for_review())
        counts.locked = len(self._get_locked())
        counts.shortlisted = len(self._get_shortlisted())
        counts.superseded = len(self._get_superseded())
        counts.unavailable = len(self._get_unavailable())

        return counts

    @staticmethod
    def _classify_failed_transfer(
            transfer: TransferStatus,
    ) -> tuple[DownloadStatus, str | None]:
        """'locked' (no reason: it is retried) for a recognized
        rejection, otherwise 'failed' with a reason a user can read."""
        if (
                "Rejected" in transfer.state
                and is_recognized_rejection(transfer.exception)
        ):
            return DownloadStatus.LOCKED, None

        return (
            DownloadStatus.FAILED,
            describe_transfer_failure(transfer.state, transfer.exception),
        )

    def _cascade_upgrade(self, track_id: str, counts: PollResult) -> None:
        # Sequential, not simultaneous: try one candidate, and only move
        # to the next once this one is confirmed unavailable — never
        # multiple in-flight requests for the same track at once. The
        # Soulseek protocol doesn't swarm-download the way BitTorrent
        # does, so firing every shortlisted candidate at once would just
        # be needless load on multiple peers for a track that only needs
        # one to succeed (HISTORY §14).
        while True:
            with self.database.transaction() as connection:
                next_entry = self.download_requests.get_next_shortlisted(
                    track_id, connection,
                )

            if next_entry is None:
                return

            # Loaded from the DB via get_next_shortlisted() above.
            assert next_entry.id is not None

            status = self._activate_shortlisted_entry(next_entry)

            if status == DownloadStatus.FAILED:
                counts.failed += 1
                continue

            if status == DownloadStatus.LOCKED:
                continue

            if status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                counts.count_in_flight(status)
                return

            if status == DownloadStatus.READY_FOR_REVIEW:
                self._supersede_others_for_track(track_id, next_entry.id)
                return

    def _activate_shortlisted_entry(
            self,
            request: DownloadRequest,
    ) -> DownloadStatus:
        # Submit a fresh request_download for a NEW candidate (never
        # tried before), so a rejection's reason still matters: it gets
        # properly classified locked-vs-failed, exactly like a
        # first-time request in the main poll_downloads loop.
        #
        # Both loaded from the DB by every real caller (_cascade_upgrade
        # fetches via get_next_shortlisted, which only returns persisted
        # rows; size is always set at creation time in
        # _request_and_record/_record_shortlisted).
        assert request.id is not None
        assert request.size is not None

        try:
            transfer_id = self.soulseek.request_download(
                request.username,
                request.filename,
                request.size,
            )
        except SoulseekDownloadError as error:
            # request_download raises this for both rejection shapes —
            # the synchronous one (e.g. peer offline, a 404 straight off
            # the enqueue POST) as well as the asynchronous one (e.g.
            # file not shared, which instead raises nothing here and
            # only shows up via the status check below) — see client.py's
            # RECOGNIZED_REJECTION_PATTERNS.
            if is_recognized_rejection(str(error)):
                self._update_status(request.id, DownloadStatus.LOCKED)
                return DownloadStatus.LOCKED

            self._update_status(
                request.id, DownloadStatus.FAILED,
                failure_reason=describe_rejection(error.reason or str(error)),
            )
            return DownloadStatus.FAILED

        # An async-shape rejection doesn't raise from request_download
        # itself (confirmed live, 2026-08-27) — it shows up almost
        # immediately via the status endpoint instead, so check right
        # away rather than waiting a full poll cycle to find out it
        # failed again. A sync-shape rejection (peer offline) never
        # reaches this point at all — it's already handled above.
        transfer = self.soulseek.get_download_status(
            request.username, transfer_id,
        )
        state = transfer.state

        reason = None

        if any(marker in state for marker in FAILED_STATE_MARKERS):
            status, reason = self._classify_failed_transfer(transfer)
        elif "Succeeded" in state:
            status = DownloadStatus.READY_FOR_REVIEW
        else:
            status = _in_flight_status(state)

        with self.database.transaction() as connection:
            self.download_requests.update_transfer_id_and_status(
                request.id, transfer_id, status, connection,
                failure_reason=reason,
            )

        return status

    def _supersede_others_for_track(
            self,
            track_id: str,
            keep_id: int,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.supersede_other_active_for_track(
                track_id, keep_id, connection,
            )

    def _track_already_has_a_matched_file(self, track_id: str) -> bool:
        """A safety net (HISTORY §56 Phase 5.3): before an automatic
        completion moves a settled download into place, check whether
        track_matches already points at a real local file for this
        track. By definition, a settled download landing after that is
        now an upgrade candidate, not a first arrival — an upgrade is
        never auto-moved, so this reuses that same rule for a settled
        download that turns out to be redundant. Deliberately NOT
        applied to apply_upgrade_decision's own replace action — a
        human explicitly clicking "Replace" is the one place
        overwriting an existing match is exactly the point, not a bug
        to prevent.
        """
        with self.database.transaction() as connection:
            existing_match = self.track_matches.get_by_track_id(
                track_id, connection,
            )

        return (
            existing_match is not None
            and existing_match.local_file_id is not None
        )

    def _retry_locked_request(
            self, request: DownloadRequest, counts: PollResult,
    ) -> None:
        # Reactivate an already-'locked' request. Unlike
        # _activate_shortlisted_entry above, a rejection's specific
        # reason doesn't matter here: this candidate is already
        # confirmed locked, so ANY rejection on the retry (any reason)
        # just means stay 'locked' and try again next run — only a real
        # success or in-progress state moves it out of the retry cycle.
        assert request.id is not None
        assert request.size is not None

        current = self._still_locked(request)

        if current is None or not self._retry_is_due(current):
            return

        if current.retry_count >= LOCKED_RETRY_MAX_ATTEMPTS:
            self._mark_retries_exhausted(request.id)
            return

        attempt = self._attempt_locked_retry(request, current.retry_count)

        if attempt is None:
            return  # Rejected again at the batch level — stays locked.

        transfer_id, state = attempt
        status = self._classify_retry_state(request, state, counts)
        self._persist_retry_outcome(
            request, transfer_id, status, current.retry_count,
        )

    def _still_locked(
            self, request: DownloadRequest,
    ) -> DownloadRequest | None:
        """The row as it stands now, or None when it should not be
        retried.

        `locked` (the list the retry loop runs over) is fetched once at
        the start of poll_downloads(), before the main loop runs — if a
        DIFFERENT entry for the same track succeeds during that loop
        and supersedes this one, this row is no longer really 'locked'
        by the time we get here. Re-check its current status first
        rather than blindly reactivating (and potentially overwriting
        'superseded' back to 'locked'/'queued') a stale snapshot.
        """
        assert request.id is not None

        with self.database.transaction() as connection:
            current = self.download_requests.get_by_id(request.id, connection)

        if current is None or current.status != DownloadStatus.LOCKED:
            return None

        if self._supersede_stale_duplicates(current):
            # A more recent row for the exact same candidate already
            # exists and just absorbed this one's spot — no point
            # issuing a real, redundant request_download for a stale
            # duplicate against the same real peer.
            return None

        return current

    @staticmethod
    def _retry_is_due(current: DownloadRequest) -> bool:
        # The retry cadence is independent of the poll cadence: a row
        # isn't due for another real attempt until its own
        # next_retry_at (exponential backoff) has passed, however often
        # poll_downloads() itself runs (HISTORY §63, §66).
        if current.next_retry_at is None:
            return True

        return datetime.now(UTC) >= datetime.fromisoformat(
            current.next_retry_at,
        )

    def _mark_retries_exhausted(self, request_id: int) -> None:
        # Exhausted every real attempt — the file exists but this peer
        # won't give it up. Terminal, distinct from 'failed' (the
        # candidate itself was real), and deliberately excluded from
        # get_requests_blocking_redownload() so a later
        # download_playlist() run can look for the same track from a
        # different peer.
        with self.database.transaction() as connection:
            self.download_requests.mark_status(
                request_id, DownloadStatus.UNAVAILABLE, connection,
                failure_reason=(
                    "Peer kept refusing after "
                    f"{LOCKED_RETRY_MAX_ATTEMPTS} attempts"
                ),
            )

    def _attempt_locked_retry(
            self, request: DownloadRequest, retry_count: int,
    ) -> tuple[str, str] | None:
        """Re-requests the same file from the same peer: its transfer id
        and slskd's state for it, or None when the peer rejected it
        at the batch level (the retry budget already advanced)."""
        assert request.size is not None

        try:
            transfer_id = self.soulseek.request_download(
                request.username,
                request.filename,
                request.size,
            )
        except SoulseekDownloadError:
            # Covers both recognized rejection shapes now that
            # request_download wraps the synchronous one too (see
            # client.py's RECOGNIZED_REJECTION_PATTERNS) — a peer that's
            # offline right now hits this branch exactly the same way a
            # file-not-shared rejection always did.
            self._advance_locked_retry(request, retry_count)
            return None
        except httpx.TransportError:
            # slskd is down; the peer was never asked, so this is not
            # an attempt against the retry budget.
            raise
        except Exception:
            # Live-caught, not theoretical: an unrecognized error
            # (client.py's own request_download deliberately re-raises
            # anything that isn't a known rejection pattern "loud")
            # must still advance the retry budget — otherwise this
            # exact failure shape retries forever with no bound.
            # Confirmed live 2026-09-02 against real production slskd,
            # a genuine `500 Internal Server Error` on
            # /api/v0/transfers/downloads/batches (HISTORY §66).
            # Re-raised unchanged so poll_downloads()'s own outer
            # per-request try/except still prints its diagnostic; this
            # is additive bookkeeping, not a change to what's reported.
            self._advance_locked_retry(request, retry_count)
            raise

        try:
            state = self.soulseek.get_download_status(
                request.username, transfer_id,
            ).state
        except httpx.TransportError:
            raise
        except Exception:
            # Same reasoning as the request_download branch above —
            # get_download_status (client.py) has no exception wrapping
            # of its own at all, so any real failure here (a timeout, a
            # non-404 HTTP error) must still count against the retry
            # budget rather than silently never advancing it.
            self._advance_locked_retry(request, retry_count)
            raise

        return transfer_id, state

    def _classify_retry_state(
            self, request: DownloadRequest, state: str, counts: PollResult,
    ) -> DownloadStatus:
        """What a retried transfer's slskd state makes of the row; a
        success is placed here, before the status is persisted."""
        if any(marker in state for marker in FAILED_STATE_MARKERS):
            return DownloadStatus.LOCKED

        if "Succeeded" not in state:
            return _in_flight_status(state)

        # role='upgrade' still needs a human's confirmation via
        # ready_for_review, exactly as before. role='settled' is only
        # reachable here at all via a human-confirmed needs-review
        # candidate that turned out to be locked
        # (find_best_needs_review_candidate never filters on lock
        # status — HISTORY §26) — that candidate was already
        # human-confirmed once, so it auto-moves into the library like
        # an ordinary settled success, not a second confirmation via
        # ready_for_review.
        if request.role == DownloadRole.UPGRADE:
            return DownloadStatus.READY_FOR_REVIEW

        if self._track_already_has_a_matched_file(request.track_id):
            # Same safety net as the main poll_downloads() loop
            # (HISTORY §56 Phase 5.3): even a role='settled' row that's
            # already human-confirmed once must not silently create a
            # second file for a track something else already matched in
            # the meantime.
            return DownloadStatus.READY_FOR_REVIEW

        # Mirror poll_downloads()'s own main-loop pattern: only persist
        # 'completed' if the file is genuinely found and moved. If not,
        # fall back to 'downloading' — the real transfer stays reported
        # as Succeeded by slskd on every future poll, so the next run's
        # main pending loop retries the move instead of this row
        # silently claiming a completion that never actually happened.
        move_result = self.placement.move_completed_file(request)

        if move_result is None:
            return DownloadStatus.DOWNLOADING

        counts.completed += 1
        # Same indexing gap as poll_downloads()'s main loop (see
        # DownloadPlacement.index_and_match's own docstring) — this
        # branch reaches 'completed' for a role='settled' row too, so it
        # needs the identical fix, not a second copy of it.
        self.placement.index_and_match(request, move_result, counts)
        return DownloadStatus.COMPLETED

    def _persist_retry_outcome(
            self,
            request: DownloadRequest,
            transfer_id: str,
            status: DownloadStatus,
            retry_count: int,
    ) -> None:
        assert request.id is not None

        with self.database.transaction() as connection:
            self.download_requests.update_transfer_id_and_status(
                request.id, transfer_id, status, connection,
            )

        if status == DownloadStatus.LOCKED:
            # Real attempt made, still locked — advance the backoff
            # schedule. Left alone (not reset) when status moves on to
            # anything else: those rows leave the retry cycle entirely,
            # so their retry_count/next_retry_at stop being consulted.
            self._advance_locked_retry(request, retry_count)

        if status == DownloadStatus.READY_FOR_REVIEW:
            self._supersede_others_for_track(request.track_id, request.id)

    def _advance_locked_retry(
            self, request: DownloadRequest, current_retry_count: int,
    ) -> None:
        # Called once per real retry attempt that ends up staying
        # 'locked' (whether rejected at the batch level or via the
        # async status check), regardless of which of the two call
        # sites made the attempt. current_retry_count is the count
        # BEFORE this attempt — used as the exponent so the first
        # attempt (0) backs off LOCKED_RETRY_BASE_SECONDS (60s, then
        # 120s, then 240s, ...).
        assert request.id is not None

        new_retry_count = current_retry_count + 1
        backoff_seconds = min(
            LOCKED_RETRY_BASE_SECONDS * (2 ** current_retry_count),
            LOCKED_RETRY_MAX_SECONDS,
        )
        next_retry_at = (
            datetime.now(UTC) + timedelta(seconds=backoff_seconds)
        ).isoformat()

        with self.database.transaction() as connection:
            self.download_requests.update_retry_state(
                request.id, new_retry_count, next_retry_at, connection,
            )

    def _supersede_stale_duplicates(self, request: DownloadRequest) -> bool:
        """Collapses stale duplicate rows for the same candidate before
        a retry re-issues a real request_download against the same
        peer — without this, the retry loop would hit slskd
        independently, every poll cycle, for every stale duplicate of
        the same candidate (confirmed live, 2026-08-28: get_locked()
        has no per-track/per-candidate collapsing of its own). Mirrors
        `download_dedup.most_recent_per_candidate`'s exact
        grouping/tiebreak rule rather than reinventing one — the same
        rule DashboardService.get_active_downloads() already uses on
        the read side, so display and mutation never drift onto two
        different notions of "duplicate."

        Returns True if `request` itself lost to a more recent sibling
        (already marked 'superseded' — the caller must not retry it).
        Returns False if `request` IS the most recent (or the only) row
        for its candidate — every OTHER sibling in the group gets
        marked 'superseded' here, so a group converges to one survivor
        within a single poll_downloads() run regardless of which row
        this method happens to be called for first.
        """
        assert request.id is not None

        with self.database.transaction() as connection:
            group = self.download_requests.get_active_candidates(
                request.track_id, request.role, request.username,
                request.filename, connection,
            )

        winner = most_recent_per_candidate(group).get(
            candidate_key(request)
        )

        if winner is not None and winner.id != request.id:
            self._update_status(request.id, DownloadStatus.SUPERSEDED)
            return True

        for sibling in group:
            if sibling.id != request.id:
                assert sibling.id is not None
                self._update_status(sibling.id, DownloadStatus.SUPERSEDED)

        return False

    def _get_ready_for_review(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_ready_for_review(connection)

    def _get_locked(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_locked(connection)

    def _get_shortlisted(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_shortlisted(connection)

    def _get_superseded(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_superseded(connection)

    def _get_unavailable(self) -> list[DownloadRequest]:
        with self.database.transaction() as connection:
            return self.download_requests.get_unavailable(connection)

    def _update_status(
            self,
            request_id: int,
            status: DownloadStatus,
            failure_reason: str | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.mark_status(
                request_id, status, connection, failure_reason=failure_reason,
            )

    def _update_progress(
            self,
            request_id: int,
            bytes_transferred: int | None,
            total_bytes: int | None,
    ) -> None:
        with self.database.transaction() as connection:
            self.download_requests.update_progress(
                request_id, bytes_transferred, total_bytes, connection,
            )

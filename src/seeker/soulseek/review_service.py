"""The Review page's decisions about downloads: SoulSeek candidates a
download run was unsure of (confirm or reject), and finished upgrades
waiting to replace a track's current file (apply or decline). Shared
by the Review page and the CLI's `check` and `downloads review`."""

import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
from seeker.errors import SeekerError
from seeker.file_deletion import delete_file, same_file
from seeker.library.scanner import index_single_file
from seeker.models.download_request import (
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.soulseek.client import SoulseekClient, derive_extension
from seeker.soulseek.placement import DownloadPlacement, SettleTarget

logger = logging.getLogger(__name__)


class ReviewCandidateNotFoundError(SeekerError):
    pass


class ReviewCandidateMissingSizeError(SeekerError):
    pass


@dataclass
class BulkUpgradeReplaceResult:
    """The real per-row outcome of a "Replace all" batch: a count for
    the UI's headline, plus one detail line per row so a partial
    failure is never just a bare number (HISTORY §88)."""
    replaced: int
    failed: int
    details: list[str]


@dataclass(frozen=True)
class _MatchedFile:
    local_file_id: int
    location: LibraryLocation
    relative_path: str

    @property
    def path(self) -> Path:
        return Path(self.location.path) / self.relative_path


class ReviewService:
    def __init__(
        self,
        database: Database,
        soulseek: Callable[[], SoulseekClient],
        placement: DownloadPlacement,
        track_repository: TrackRepository,
        library_location_repository: LibraryLocationRepository,
        download_request_repository: DownloadRequestRepository,
        track_match_repository: TrackMatchRepository,
        local_file_repository: LocalFileRepository,
        soulseek_review_candidate_repository: SoulseekReviewCandidateRepository,
        rejection_repository: RejectionRepository,
    ):
        self.database = database
        # Called only by confirm_review_candidate, the one action here
        # that talks to slskd: every listing and upgrade decision keeps
        # working while SoulSeek is not configured.
        self._soulseek = soulseek
        self.placement = placement
        self.tracks = track_repository
        self.locations = library_location_repository
        self.download_requests = download_request_repository
        self.track_matches = track_match_repository
        self.local_files = local_file_repository
        self.soulseek_review_candidates = soulseek_review_candidate_repository
        self.rejections = rejection_repository

    def get_review_candidates(
            self,
            playlist_id: str | None = None,
    ) -> list[tuple[Track, SoulseekReviewCandidate]]:
        # Read-only listing — the actual confirm/reject actions are
        # confirm_review_candidate()/reject_review_candidate() below
        # (HISTORY §26, the Review screen).
        with self.database.transaction() as connection:
            candidates = self.soulseek_review_candidates.get_all(connection)

            if playlist_id is not None:
                tracks = self.tracks.get_all_for_playlist(
                    playlist_id, connection
                )
            else:
                tracks = self.tracks.get_all(connection)

            tracks_by_id = {track.id: track for track in tracks}

        results = []

        for candidate in candidates:
            track = tracks_by_id.get(candidate.track_id)

            if track is not None:
                results.append((track, candidate))

        results.sort(key=lambda item: (item[0].artist, item[0].title))

        return results

    def confirm_review_candidate(self, track_id: str) -> None:
        # The Review screen's SoulSeek-candidate confirm action.
        # role='settled', deliberately: a human just manually confirmed
        # this specific candidate is correct, a stronger signal than an
        # algorithmic top-rank pick, so it auto-moves into the library
        # on success rather than demanding a second confirmation via
        # ready_for_review. find_best_needs_review_candidate never
        # filters on lock status, so this candidate genuinely can be
        # locked — poll_downloads()'s rejection handling classifies
        # locked-vs-failed regardless of role for exactly this reason
        # (HISTORY §26).
        with self.database.transaction() as connection:
            candidate = self.soulseek_review_candidates.get_by_track_id(
                track_id, connection,
            )

        if candidate is None:
            raise ReviewCandidateNotFoundError(
                f"No SoulSeek review candidate found for track "
                f"{track_id}."
            )

        if candidate.size is None:
            # A legacy row persisted before `size` existed on this
            # table — can't call request_download without it.
            # Downloading the track's playlist again refreshes this row
            # with a real size the normal way, rather than this method
            # guessing or defaulting one.
            raise ReviewCandidateMissingSizeError(
                f"Review candidate for track {track_id} predates size "
                f"tracking — download its playlist again (Dashboard → "
                f"select the playlist → Download) to refresh it before "
                f"confirming."
            )

        transfer_id = self._soulseek().request_download(
            candidate.username, candidate.filename, candidate.size,
        )

        with self.database.transaction() as connection:
            self.download_requests.add(
                DownloadRequest(
                    track_id=track_id,
                    username=candidate.username,
                    filename=candidate.filename,
                    format=derive_extension(candidate.filename),
                    quality_descriptor=candidate.quality_descriptor,
                    role=DownloadRole.SETTLED,
                    transfer_id=transfer_id,
                    size=candidate.size,
                    requested_at=datetime.now(UTC).isoformat(),
                ),
                connection,
            )

        # Cleared immediately once the request is made, not once it
        # completes — the same clearing trigger used elsewhere ("something
        # real now exists for this track"), so `seeker check` never
        # surfaces this candidate as still awaiting a decision once a
        # decision has, in fact, been made.
        with self.database.transaction() as connection:
            self.soulseek_review_candidates.delete(track_id, connection)

    def reject_review_candidate(self, track_id: str) -> None:
        """Removes the candidate without requesting it, and never
        suggests or requests that peer's file for this track again.
        """
        with self.database.transaction() as connection:
            candidate = self.soulseek_review_candidates.get_by_track_id(
                track_id, connection,
            )

            if candidate is not None:
                self.rejections.add_soulseek_candidate(
                    track_id,
                    candidate.username,
                    candidate.filename,
                    datetime.now(UTC).isoformat(),
                    connection,
                )

            self.soulseek_review_candidates.delete(track_id, connection)

    def get_upgrade_review_details(
            self,
            request_id: int,
    ) -> UpgradeReviewDetails | None:
        # Read-only — no input() anywhere, so both the CLI's interactive
        # loop and the Review screen's UI can build their prompts/labels
        # from the identical resolved info. None only when the request
        # or its track can no longer be found.
        with self.database.transaction() as connection:
            request = self.download_requests.get_by_id(request_id, connection)

            if request is None:
                return None

            track = self.tracks.get_by_id(request.track_id, connection)
            current_match = self.track_matches.get_by_track_id(
                request.track_id,
                connection,
            )

            current_local_file = None
            if current_match is not None and current_match.local_file_id:
                current_local_file = self.local_files.get_by_id(
                    current_match.local_file_id,
                    connection,
                )

            old_location = None
            if current_local_file is not None:
                old_location = self.locations.get_by_id(
                    current_local_file.location_id,
                    connection,
                )

        if track is None:
            return None

        current_description = (
            current_local_file.format
            if current_local_file is not None
            else "no current file"
        )

        old_file_path = None
        if current_local_file is not None and old_location is not None:
            old_file_path = str(
                Path(old_location.path) / current_local_file.relative_path
            )

        return UpgradeReviewDetails(
            request_id=request_id,
            track=track,
            quality_descriptor=request.quality_descriptor,
            current_description=current_description,
            old_file_path=old_file_path,
        )

    def get_pending_upgrade_reviews(self) -> list[UpgradeReviewDetails]:
        # The Review screen's listing call for its upgrade-confirmation
        # section — same read-only resolution get_upgrade_review_details
        # already does per-row, just fetching every ready_for_review row
        # up front rather than requiring the caller to already know a
        # request_id. A row whose details can no longer be resolved
        # (track deleted, etc.) is silently skipped rather than surfaced
        # as a broken row — the same "None means gone" contract
        # get_upgrade_review_details already documents.
        with self.database.transaction() as connection:
            requests = self.download_requests.get_ready_for_review(
                connection,
            )

        results = []

        for request in requests:
            assert request.id is not None
            details = self.get_upgrade_review_details(request.id)

            if details is not None:
                results.append(details)

        return results

    def apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool = False,
    ) -> str | None:
        """Explicit-decision version of the replace/delete-old-file
        action — pure mutation, no input() anywhere, so the CLI's
        interactive loop and a UI can call the identical logic with
        already-resolved booleans instead of blocking on stdin. Returns
        a short, human-readable status message for the caller to
        surface, or None for `replace=False` (a no-op — the row stays
        ready_for_review, offered again later, same as declining in the
        CLI).

        With `delete_old`, the upgrade takes over the track: when it
        would land on the current file's own path, it is swapped in
        atomically over that file; otherwise it lands under a
        collision-free name and the old file's row, then the file
        itself, are removed. Without `delete_old`, nothing that already
        exists is touched.
        """
        if not replace:
            return None

        with self.database.transaction() as connection:
            request = self.download_requests.get_by_id(request_id, connection)

        if request is None:
            return "Request not found."

        current = self._current_matched_file(request.track_id)
        target = self.placement.settle_target(request)

        if target is None:
            return "Could not locate the downloaded file; leaving for review."

        if (
                delete_old
                and current is not None
                and same_file(current.path, target.proposed_path)
        ):
            return self._swap_upgrade_in_place(
                request_id, request.track_id, target, current,
            )

        location, relative_path = self.placement.place_without_overwrite(target)
        new_path = Path(location.path) / relative_path

        with self.database.transaction() as connection:
            new_local_file = index_single_file(
                location,
                relative_path,
                self.local_files,
                connection,
            )
            assert new_local_file.id is not None
            self._record_upgrade(
                request_id, request.track_id, new_local_file.id, connection,
            )

        message = f"Replaced with {new_path}"

        if current is None:
            return message

        if not delete_old:
            return f"{message}\n  Leaving {current.path} in place."

        # Unreachable while placement never overwrites (the swap above
        # takes the same-path case), and kept so it stays that way: the
        # file the match now points at is never the one deleted.
        if same_file(current.path, new_path):
            return message

        # Database row first, then the file (HISTORY §40).
        with self.database.transaction() as connection:
            self.local_files.delete_by_id(current.local_file_id, connection)

        error = delete_file(current.path)

        if error is None:
            return f"{message}\n  Deleted {current.path}"

        return f"{message}\n  Could not delete {current.path}: {error}"

    def _current_matched_file(self, track_id: str) -> _MatchedFile | None:
        with self.database.transaction() as connection:
            match = self.track_matches.get_by_track_id(track_id, connection)

            if match is None or match.local_file_id is None:
                return None

            local_file = self.local_files.get_by_id(
                match.local_file_id, connection,
            )

            if local_file is None:
                return None

            location = self.locations.get_by_id(
                local_file.location_id, connection,
            )

        if location is None:
            return None

        return _MatchedFile(
            local_file_id=match.local_file_id,
            location=location,
            relative_path=local_file.relative_path,
        )

    def _swap_upgrade_in_place(
            self,
            request_id: int,
            track_id: str,
            target: SettleTarget,
            current: _MatchedFile,
    ) -> str:
        # Moved next to the old file first so the final step is one
        # same-directory rename(2): the old content is gone at the
        # instant the new content appears, and no delete follows that
        # could hit the file the match points at.
        temp_path = current.path.with_name(
            f".{current.path.name}.seeker-upgrade-tmp",
        )
        shutil.move(str(target.source), str(temp_path))
        temp_path.replace(current.path)

        logger.info("Swapped the upgrade in over %s", current.path)

        with self.database.transaction() as connection:
            refreshed = index_single_file(
                current.location,
                current.relative_path,
                self.local_files,
                connection,
            )
            assert refreshed.id is not None
            self.local_files.clear_content_derived_fields(
                refreshed.id, connection,
            )
            self._record_upgrade(
                request_id, track_id, refreshed.id, connection,
            )

        return f"Replaced {current.path} in place with the upgrade."

    def _record_upgrade(
            self,
            request_id: int,
            track_id: str,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        self.track_matches.upsert(
            TrackMatch(
                track_id=track_id,
                local_file_id=local_file_id,
                match_method="auto",
                score=100.0,
                matched_at=datetime.now(UTC).isoformat(),
            ),
            connection,
        )
        self.download_requests.mark_status(
            request_id, DownloadStatus.COMPLETED, connection,
        )

    def apply_upgrade_decisions_batch(
            self,
            request_ids: list[int],
            delete_old: bool,
    ) -> BulkUpgradeReplaceResult:
        """"Replace all" pending upgrades — see HISTORY §88 for the
        full design. Applies `apply_upgrade_decision(request_id, True,
        delete_old)` per row through the exact same explicit-decision
        method the CLI and single-row UI action already use. Per-row
        try/except so one bad row can't abort the rest; success is
        checked by re-reading the request's own status afterward, not
        by parsing the returned message string.
        """
        replaced = 0
        failed = 0
        details: list[str] = []

        for request_id in request_ids:
            review_details = self.get_upgrade_review_details(request_id)
            label = (
                f"{review_details.track.artist} - {review_details.track.title}"
                if review_details is not None
                else f"request {request_id}"
            )

            try:
                message = self.apply_upgrade_decision(
                    request_id, True, delete_old,
                )
            except Exception as error:
                failed += 1
                details.append(f"{label}: Failed — {error}")
                continue

            with self.database.transaction() as connection:
                updated_request = self.download_requests.get_by_id(
                    request_id, connection,
                )

            succeeded = (
                updated_request is not None
                and updated_request.status == DownloadStatus.COMPLETED
            )

            if succeeded:
                replaced += 1
            else:
                failed += 1

            details.append(f"{label}: {message or 'No change made.'}")

        return BulkUpgradeReplaceResult(
            replaced=replaced, failed=failed, details=details,
        )

from datetime import datetime, timezone

from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.local_file import LocalFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    TrackStatus,
)


class PlaylistNotFoundError(RuntimeError):
    pass


# "Downloading" — an active, actually-transferring request.
_DOWNLOADING_STATUSES = {"queued", "downloading"}
# "Awaiting review" — something's being chased right now (locked/
# shortlisted) or is done and waiting on a human (ready_for_review).
# Deliberately excludes completed/failed/superseded — those aren't
# "awaiting" anything.
_AWAITING_REVIEW_STATUSES = {"ready_for_review", "locked", "shortlisted"}

# Every download_requests status that still represents real, in-progress
# work toward an outcome — mirrors `seeker downloads status`'s own scope
# exactly (see download_service.py's TERMINAL_STATUSES/status state
# machine in schema.py). Deliberately excludes 'superseded' — that's
# terminal, a sibling entry already won.
ACTIVE_DOWNLOAD_STATUSES = {
    "queued", "downloading", "locked", "shortlisted", "ready_for_review",
}

# Untuned constant, same convention as every other threshold in this
# codebase — how long a completed/failed row keeps appearing in the
# active-downloads view after landing, so a download visibly "lands"
# rather than vanishing the instant poll_downloads() marks it terminal.
RECENTLY_FINISHED_WINDOW_SECONDS = 60


class DashboardService:
    def __init__(
        self,
        database: Database,
        playlist_repository: PlaylistRepository,
        track_repository: TrackRepository,
        track_match_repository: TrackMatchRepository,
        download_request_repository: DownloadRequestRepository,
        soulseek_review_candidate_repository: SoulseekReviewCandidateRepository,
        local_file_repository: LocalFileRepository,
    ):
        self.database = database
        self.playlists = playlist_repository
        self.tracks = track_repository
        self.track_matches = track_match_repository
        self.download_requests = download_request_repository
        self.soulseek_review_candidates = soulseek_review_candidate_repository
        self.local_files = local_file_repository

    def get_playlist_track_status(
            self,
            playlist_name: str,
    ) -> list[TrackStatus]:
        """Every track in one playlist, each with exactly one primary
        state (mutually exclusive, first match wins) plus an optional
        secondary tag:

        1. IN_LIBRARY — an 'auto' track_matches row resolving to a real
           local file. Takes precedence over any stale download_requests
           row left over from before the track was matched.
        2. DOWNLOADING — an active queued/downloading request.
        3. AWAITING_REVIEW — a ready_for_review request, or an active
           locked/shortlisted one (something's being chased right now).
        4. NEEDS_REVIEW — a needs_review track_matches row, no active
           download activity.
        5. NOT_FOUND — none of the above.

        Secondary tag (a soulseek_review_candidates row) can only ever
        surface on states 4/5 — by construction, not by a runtime check:
        the candidate lookup is only ever consulted from those two
        branches, so a track that happens to have both an auto match
        and a stale review-candidate row (which item 17's
        download_playlist clearing logic should never actually leave
        behind — confirmed against real data: zero such rows exist)
        would surface as IN_LIBRARY with the tag silently absent, not a
        contradictory combination. If that clearing logic ever regresses,
        this is where it would go unnoticed rather than crash — worth
        revisiting with an explicit warning if it's ever seen for real.
        """
        with self.database.transaction() as connection:
            playlist = self.playlists.get_by_name(playlist_name, connection)

            if playlist is None:
                raise PlaylistNotFoundError(
                    f"No playlist named '{playlist_name}' has been "
                    f"synced."
                )

            tracks = self.tracks.get_all_for_playlist(
                playlist.id, connection
            )
            matches = self.track_matches.get_all(connection)
            local_files_by_id = {
                local_file.id: local_file
                for local_file in self.local_files.get_all(connection)
            }
            download_requests = self.download_requests.get_all(connection)
            review_candidates = (
                self.soulseek_review_candidates.get_all(connection)
            )

        # track_ids scopes every lookup below to just this playlist's
        # own tracks — a match/request/candidate belonging to some other
        # playlist's track must never leak into this result.
        track_ids = {track.id for track in tracks}

        matches_by_track_id = {
            match.track_id: match
            for match in matches
            if match.track_id in track_ids
        }

        requests_by_track_id: dict[str, list[DownloadRequest]] = {}
        for request in download_requests:
            if request.track_id in track_ids:
                requests_by_track_id.setdefault(
                    request.track_id, []
                ).append(request)

        candidates_by_track_id = {
            candidate.track_id: candidate
            for candidate in review_candidates
            if candidate.track_id in track_ids
        }

        return [
            _compute_status(
                track,
                matches_by_track_id.get(track.id),
                requests_by_track_id.get(track.id, []),
                local_files_by_id,
                candidates_by_track_id.get(track.id),
            )
            for track in tracks
        ]

    def get_active_downloads(self) -> list[ActiveDownload]:
        """Every download_requests row still in progress, GLOBALLY across
        every playlist at once — mirrors `seeker downloads status`'s own
        scope, not the single-playlist scope of
        get_playlist_track_status() above. Getting this backwards would
        repeat the exact scoping bug class this project already found
        once (the global-vs-playlist-scoped `check`/`match_all`
        confusion, see CLAUDE.md) — so this is deliberately NOT filtered
        by playlist anywhere in this method.

        Also includes a completed/failed row for
        RECENTLY_FINISHED_WINDOW_SECONDS after its completed_at, so a
        download visibly "lands" in the view instead of disappearing the
        instant poll_downloads() marks it terminal.

        Rows representing the exact same real candidate (same track/
        role/peer/file) are collapsed to the single most-recently-
        requested one via _dedupe_repeated_candidates() — see that
        function's docstring for why this is safe: it never collapses
        Phase 4's legitimate multi-candidate shortlist (different rows
        there always have different peers/files by construction), only
        genuine repeat rows for the identical candidate.
        """
        with self.database.transaction() as connection:
            requests = self.download_requests.get_all(connection)
            tracks_by_id = {
                track.id: track for track in self.tracks.get_all(connection)
            }
            playlist_names_by_track_id = (
                self.playlists.get_playlist_names_by_track_id(connection)
            )

        now = datetime.now(timezone.utc)
        visible = [request for request in requests if _is_visible(request, now)]
        deduplicated = _dedupe_repeated_candidates(visible)

        results = []

        for request in deduplicated:
            track = tracks_by_id.get(request.track_id)

            if track is None:
                continue

            playlist_names = playlist_names_by_track_id.get(
                request.track_id, [],
            )

            results.append(
                ActiveDownload(
                    request=request,
                    track=track,
                    playlist_name=", ".join(playlist_names) or "Unknown",
                )
            )

        results.sort(key=lambda item: item.request.requested_at, reverse=True)

        return results


def _dedupe_repeated_candidates(
        requests: list[DownloadRequest],
) -> list[DownloadRequest]:
    """Collapse repeated download_requests rows that represent the exact
    same real candidate (same track/role/peer/file) down to the single
    most-recently-requested attempt.

    Confirmed live (2026-08-28, Step 5 live-verification follow-up)
    against real production data: some tracks carry multiple
    simultaneously-active rows with identical track_id/role/username/
    filename, all rank=1 — e.g. three rows for "Balron, Audio - Breach"
    (ids 5/7/9), all against the same peer 'long25' and the same
    filename, requested hours apart on 2026-08-27. Checked against
    rank/role/username/filename directly to rule out Phase 4's
    legitimate multi-candidate shortlist (rank 1 active + ranks 2/3
    shortlisted as DIFFERENT real peers/files) before concluding this —
    no rank > 1 row exists anywhere in that data, and every "duplicate"
    shares the identical candidate, which the shortlist design never
    produces (each rank is a genuinely different search result). This
    is stale data from before download_playlist()'s get_active_for_track
    guard (item 16) was fully effective, not a currently-reproducible
    bug — re-running download_playlist() against this exact live data
    correctly skipped re-requesting ("Already in progress ... —
    skipping"), confirming today's guard works. The real, actionable
    problem for THIS screen: without this dedup, the Downloads tab
    rendered three apparently-independent active downloads for what is
    really one attempt.

    Deliberately keyed WITHOUT rank — two rows are the same real
    candidate if they share track/role/peer/filename, full stop; two
    genuinely different candidates (Phase 4's rank 1/2/3 shortlist)
    always have distinct username/filename by construction (each rank
    is a different real search result), so they're never collapsed by
    this key regardless of rank.
    """
    most_recent_by_candidate: dict[tuple[str, str, str, str], DownloadRequest] = {}

    for request in requests:
        key = (
            request.track_id, request.role, request.username,
            request.filename,
        )
        current_best = most_recent_by_candidate.get(key)

        if (
                current_best is None
                or request.requested_at > current_best.requested_at
        ):
            most_recent_by_candidate[key] = request

    return list(most_recent_by_candidate.values())


def _is_visible(request: DownloadRequest, now: datetime) -> bool:
    if request.status in ACTIVE_DOWNLOAD_STATUSES:
        return True

    if request.status in ("completed", "failed") and request.completed_at:
        completed_at = datetime.fromisoformat(request.completed_at)
        elapsed = (now - completed_at).total_seconds()

        return elapsed <= RECENTLY_FINISHED_WINDOW_SECONDS

    return False


def _compute_status(
        track: Track,
        match: TrackMatch | None,
        requests: list[DownloadRequest],
        local_files_by_id: dict[int | None, LocalFile],
        candidate: SoulseekReviewCandidate | None,
) -> TrackStatus:
    if (
            match is not None
            and match.match_method == "auto"
            and match.local_file_id is not None
            and match.local_file_id in local_files_by_id
    ):
        return TrackStatus(track=track, state=IN_LIBRARY)

    downloading = next(
        (r for r in requests if r.status in _DOWNLOADING_STATUSES), None
    )
    if downloading is not None:
        return TrackStatus(
            track=track,
            state=DOWNLOADING,
            bytes_transferred=downloading.bytes_transferred,
            total_bytes=downloading.total_bytes,
        )

    if any(r.status in _AWAITING_REVIEW_STATUSES for r in requests):
        return TrackStatus(track=track, state=AWAITING_REVIEW)

    if match is not None and match.match_method == "needs_review":
        return TrackStatus(
            track=track, state=NEEDS_REVIEW, soulseek_candidate=candidate,
        )

    return TrackStatus(
        track=track, state=NOT_FOUND, soulseek_candidate=candidate,
    )

from dataclasses import dataclass

from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track


# Mutually exclusive primary states, in the exact precedence order
# DashboardService.get_playlist_track_status() checks them (first match
# wins) — see dashboard_service.py's docstring for the full contract.
IN_LIBRARY = "in_library"
DOWNLOADING = "downloading"
AWAITING_REVIEW = "awaiting_review"
NEEDS_REVIEW = "needs_review"
NOT_FOUND = "not_found"


@dataclass
class TrackStatus:
    track: Track
    # One of IN_LIBRARY/DOWNLOADING/AWAITING_REVIEW/NEEDS_REVIEW/NOT_FOUND.
    state: str
    # Secondary tag — only ever set when state is NEEDS_REVIEW or
    # NOT_FOUND (see dashboard_service.py for why this can't happen for
    # the other three states, by construction, not just by convention).
    soulseek_candidate: SoulseekReviewCandidate | None = None
    # Only meaningful when state == DOWNLOADING — the active request's
    # real, live progress (see Task 2). None/None for every other state.
    bytes_transferred: int | None = None
    total_bytes: int | None = None
    # Only meaningful when state == IN_LIBRARY — the resolved local
    # file's own tagged_at, an ISO 8601 UTC string (matching
    # LocalFile.tagged_at/TrackMatch.matched_at/DownloadRequest.
    # completed_at's existing str-not-datetime convention throughout
    # this codebase), or None if the file has never been tagged.
    tagged_at: str | None = None

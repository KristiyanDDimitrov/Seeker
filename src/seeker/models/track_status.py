from dataclasses import dataclass

from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track

# Mutually exclusive primary states, in the exact precedence order
# DashboardService.get_playlist_track_status() checks them (first match
# wins) — see dashboard_service.py's docstring for the full contract.
#
# AWAITING_REVIEW is only a completed download waiting on a human
# decision; a locked/shortlisted row still being retried in the
# background is RETRYING. Folding the two together makes a locked retry
# flicker between "Awaiting review" and "Downloading" (briefly
# in-progress before the async rejection lands) — correct information
# under the wrong label. REVIEW_CANDIDATE is a track with a
# soulseek_review_candidates row and no download_requests row: a real
# SoulSeek candidate exists, so it must never read as "Not found". See
# HISTORY §56.
IN_LIBRARY = "in_library"
DOWNLOADING = "downloading"
AWAITING_REVIEW = "awaiting_review"
RETRYING = "retrying"
NEEDS_REVIEW = "needs_review"
REVIEW_CANDIDATE = "review_candidate"
NOT_FOUND = "not_found"


@dataclass
class TrackStatus:
    track: Track
    # One of IN_LIBRARY/DOWNLOADING/AWAITING_REVIEW/RETRYING/
    # NEEDS_REVIEW/REVIEW_CANDIDATE/NOT_FOUND.
    state: str
    # Secondary tag — only ever set when state is NEEDS_REVIEW or
    # NOT_FOUND (see dashboard_service.py for why this can't happen for
    # the other states, by construction, not just by convention).
    # Kept for NEEDS_REVIEW: a track can legitimately have both a local
    # needs-review match AND a separate SoulSeek candidate; the two
    # measure different things (HISTORY §17). A NOT_FOUND with a
    # candidate attached is REVIEW_CANDIDATE's own primary state
    # instead, so a bare NOT_FOUND never carries one.
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

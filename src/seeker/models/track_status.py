from dataclasses import dataclass

from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track


# Mutually exclusive primary states, in the exact precedence order
# DashboardService.get_playlist_track_status() checks them (first match
# wins) — see dashboard_service.py's docstring for the full contract.
#
# Roadmap item 66 (Phase 4.1) — split from the original, narrower
# five-state set (item 22) into seven. The original AWAITING_REVIEW
# folded together two genuinely different situations: a real completed
# download waiting on a human decision, and a locked/shortlisted row
# still being retried in the background — which is what made the
# "Awaiting review" <-> "Downloading" flicker (a locked retry briefly
# looking in-progress before the async rejection lands, then flipping
# back — see docs/HISTORY.md item 66) read as a bug in the status
# itself rather than what it actually was: correct information, wrong
# label. RETRYING is that split out. REVIEW_CANDIDATE is the fix for
# "Not found" on a track that actually has a real SoulSeek candidate
# (item 0.2's own finding) — a soulseek_review_candidates row with no
# download_requests row at all was previously only ever a silent
# secondary tag on NOT_FOUND, easy to miss.
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
    # Roadmap item 66 (Phase 4.1) — kept for NEEDS_REVIEW (a track can
    # legitimately have both a local needs-review match AND a separate
    # SoulSeek candidate; the two measure different things, item 17's
    # own standing precedent). No longer meaningful for what used to be
    # NOT_FOUND with a candidate attached — that's REVIEW_CANDIDATE's
    # own primary state now, so a bare NOT_FOUND never carries one.
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

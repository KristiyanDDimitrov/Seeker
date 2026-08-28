from dataclasses import dataclass


@dataclass
class SoulseekReviewCandidate:
    track_id: str
    username: str
    filename: str
    score: float
    quality_descriptor: str
    found_at: str
    # Required to call request_download() when a human confirms this
    # candidate (item 26) — None only for a legacy row persisted before
    # this field existed; confirm_review_candidate refuses those until
    # download_playlist() next refreshes the row with a real size.
    size: int | None = None

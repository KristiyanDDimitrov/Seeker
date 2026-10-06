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
    # candidate — None only for a legacy row persisted before this field
    # existed; confirm_review_candidate refuses those until
    # download_playlist() next refreshes the row with a real size.
    size: int | None = None
    # The second-best-scoring candidate in the same needs_review band,
    # when one existed (see schema.py's own comment on this table). All
    # three None together, never independently.
    runner_up_username: str | None = None
    runner_up_filename: str | None = None
    runner_up_score: float | None = None

from dataclasses import dataclass


@dataclass
class TrackMatch:
    track_id: str
    matched_at: str
    local_file_id: int | None = None
    match_method: str | None = None
    score: float | None = None
    # Set only by a human confirming a needs_review local-file match —
    # a non-null value means match_all() must never recompute this row
    # from scratch, or a re-run silently demotes it. See HISTORY §56.
    confirmed_at: str | None = None

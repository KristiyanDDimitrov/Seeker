from dataclasses import dataclass


@dataclass
class TrackMatch:
    track_id: str
    matched_at: str
    local_file_id: int | None = None
    match_method: str | None = None
    score: float | None = None
    # Set only by a human confirming a needs_review local-file match
    # (roadmap item 56 Phase 2) — a non-null value means match_all()
    # must never recompute this row from scratch (item 45's pre-existing
    # demotion bug, closed by this field's existence).
    confirmed_at: str | None = None

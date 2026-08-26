from dataclasses import dataclass


@dataclass
class TrackMatch:
    track_id: str
    matched_at: str
    local_file_id: int | None = None
    match_method: str | None = None
    score: float | None = None

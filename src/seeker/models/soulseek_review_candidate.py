from dataclasses import dataclass


@dataclass
class SoulseekReviewCandidate:
    track_id: str
    username: str
    filename: str
    score: float
    quality_descriptor: str
    found_at: str

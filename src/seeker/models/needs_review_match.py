from dataclasses import dataclass


@dataclass
class NeedsReviewMatch:
    """One local-file needs_review candidate, resolved with enough
    context for a human to judge WHY it scored where it did — roadmap
    item 56 Phase 2, closing item 7's long-outstanding "review command
    for local-file matches" gap. Deliberately not just (track_id, score):
    the whole point is showing the tag values that were actually
    compared, not just the number that came out.
    """

    track_id: str
    track_artist: str
    track_title: str
    local_file_id: int
    local_file_path: str
    location_name: str
    score: float
    tag_artist: str | None
    tag_title: str | None

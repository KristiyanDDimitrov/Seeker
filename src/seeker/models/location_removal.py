from dataclasses import dataclass


@dataclass(frozen=True)
class LocationRemovalSummary:
    """What removing a library location forgets. The same counts back
    the confirmation shown before removal and the report after it.
    Files on disk are never touched.
    """
    location_name: str
    files_forgotten: int
    matches_cleared: int
    confirmed_matches_cleared: int
    playlists_affected: int
    was_default: bool

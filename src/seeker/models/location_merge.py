from dataclasses import dataclass


@dataclass(frozen=True)
class LocationMergeSummary:
    """What merging a nested location into the location kept does. The
    same counts back the confirmation shown before the merge and the
    report after it. Files on disk are never touched.

    A file is merged when the kept location indexes the same physical
    file; its matches and Review rejections move to that row, and its
    analysis fills any the kept row lacks. Every other file of the
    merged location is forgotten, as removal forgets it.
    """
    merged_name: str
    kept_name: str
    files_merged: int
    files_forgotten: int
    matches_moved: int
    matches_cleared: int
    analyses_kept: int
    playlists_moved: int
    playlists_cleared: int
    was_default: bool

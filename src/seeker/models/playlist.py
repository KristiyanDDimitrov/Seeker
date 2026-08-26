from dataclasses import dataclass


@dataclass
class Playlist:
    id: str
    name: str
    track_count: int
    snapshot_id: str | None = None
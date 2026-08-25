from dataclasses import dataclass


@dataclass
class Playlist:
    id: str
    name: str
    track_count: int
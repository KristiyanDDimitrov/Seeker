from dataclasses import dataclass


@dataclass
class Track:
    id: str
    title: str
    artist: str
    album: str
    duration_ms: int

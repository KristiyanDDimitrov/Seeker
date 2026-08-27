from dataclasses import dataclass


@dataclass
class LocalFile:
    location_id: int
    relative_path: str
    filename: str
    format: str
    size_bytes: int
    mtime: float
    scanned_at: str
    id: int | None = None
    tag_artist: str | None = None
    tag_title: str | None = None
    tag_album: str | None = None
    duration_ms: int | None = None
    bpm: float | None = None
    camelot_key: str | None = None
    key_confidence: float | None = None

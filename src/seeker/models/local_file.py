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
    tagged_at: str | None = None
    # Whether the file has an embedded picture; None until a read
    # succeeds (never read, or unreadable).
    has_art: bool | None = None
    # None when never computed, and also when the read left them out:
    # only LocalFileRepository.get_all_for_location_with_fingerprints
    # loads them.
    fingerprint: str | None = None
    fingerprint_duration: float | None = None
    fingerprint_computed_at: str | None = None

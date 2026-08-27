from dataclasses import dataclass


@dataclass
class DownloadRequest:
    track_id: str
    username: str
    filename: str
    format: str
    requested_at: str
    id: int | None = None
    quality_descriptor: str | None = None
    role: str = "settled"
    status: str = "queued"
    transfer_id: str | None = None
    size: int | None = None
    rank: int | None = None
    completed_at: str | None = None

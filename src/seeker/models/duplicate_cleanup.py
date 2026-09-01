from dataclasses import dataclass


@dataclass
class DuplicateCleanup:
    occurred_at: str
    files_deleted: int
    bytes_freed: int
    id: int | None = None
    location_id: int | None = None

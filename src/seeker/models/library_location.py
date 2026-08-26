from dataclasses import dataclass


@dataclass
class LibraryLocation:
    name: str
    path: str
    added_at: str
    id: int | None = None

from dataclasses import dataclass


@dataclass
class Playlist:
    id: str
    name: str
    track_count: int
    snapshot_id: str | None = None
    download_location_id: int | None = None
    download_subfolder: str | None = None
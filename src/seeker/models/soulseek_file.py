from dataclasses import dataclass


@dataclass
class SoulseekFile:
    username: str
    filename: str
    extension: str
    size: int
    queue_length: int
    upload_speed: int
    has_free_upload_slot: bool
    length: int | None = None
    bit_rate: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None
    is_variable_bitrate: bool | None = None
    locked: bool = False

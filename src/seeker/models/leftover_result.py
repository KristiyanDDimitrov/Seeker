from dataclasses import dataclass, field
from enum import StrEnum


class LeftoverFolder(StrEnum):
    """Which of slskd's two folders a leftover file sits in."""
    DOWNLOADS = "downloads"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class LeftoverFile:
    """A file in slskd's folders that nothing is waiting for. `size`
    and `modified_at` (the file's mtime) are what the listing saw; a
    cleanup deletes the file only while both still hold. `relative_path`
    is `path` inside slskd's app directory (`downloads/Album/x.mp3`),
    the part worth showing."""
    path: str
    folder: LeftoverFolder
    size: int
    modified_at: float
    relative_path: str


@dataclass
class LeftoverListing:
    """slskd's leftover files, largest first. `held_back` counts the
    files left out because a transfer may still be using them."""
    files: list[LeftoverFile] = field(default_factory=list)
    held_back: int = 0

    @property
    def total_bytes(self) -> int:
        return sum(file.size for file in self.files)


@dataclass(frozen=True)
class LeftoverFailure:
    file: LeftoverFile
    message: str


@dataclass
class LeftoverCleanup:
    """What one cleanup did with the files a person confirmed. `kept`
    holds the ones that changed or came into use since the listing."""
    deleted: list[LeftoverFile] = field(default_factory=list)
    kept: list[LeftoverFile] = field(default_factory=list)
    failures: list[LeftoverFailure] = field(default_factory=list)

    @property
    def freed_bytes(self) -> int:
        return sum(file.size for file in self.deleted)

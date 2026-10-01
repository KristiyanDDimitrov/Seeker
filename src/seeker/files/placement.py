"""Choosing where a file may land without destroying another one.

The one collision rule every file-placing path shares: a rename in
`library/metadata_service.py` and a finished download in
`soulseek/download_service.py`. Never write a second variant.
"""
from pathlib import Path

from seeker.files.deletion import same_file


def resolve_collision(current_path: Path, proposed_path: Path) -> Path:
    """`proposed_path` if nothing else occupies it, otherwise the first
    free `<stem> (2)<suffix>`, `(3)`, ... next to it.

    Reads the real filesystem at call time, so call it immediately
    before the move, not when planning. A path that is `current_path`
    itself (same inode, e.g. a case-only rename on case-insensitive
    APFS) is not a collision.
    """
    if not proposed_path.exists() or same_file(current_path, proposed_path):
        return proposed_path

    stem = proposed_path.stem
    suffix = proposed_path.suffix
    counter = 2

    while True:
        candidate = proposed_path.with_name(f"{stem} ({counter}){suffix}")

        if not candidate.exists() or same_file(current_path, candidate):
            return candidate

        counter += 1

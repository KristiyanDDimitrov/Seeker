"""Whether one library location sits inside another.

A location inside another indexes every file under it twice: once per
location, as two `local_files` rows for one real file.
"""
from pathlib import Path

from seeker.files.deletion import same_file
from seeker.models.library_location import LibraryLocation
from seeker.models.nested_location import NestedLocation


def same_directory(path_a: Path, path_b: Path) -> bool:
    """True for equal paths, and for two spellings of one folder on
    disk: macOS's default APFS volume is case-insensitive, so `music`
    and `Music` are the same folder there. An unreachable path (a drive
    not mounted) compares by its text alone.
    """
    return path_a == path_b or same_file(path_a, path_b)


def is_within(inner: Path, outer: Path) -> bool:
    """True when `inner` is strictly inside `outer`. Both are expected
    resolved, so a symlink has already become its target.
    """
    return any(same_directory(parent, outer) for parent in inner.parents)


def find_nested(locations: list[LibraryLocation]) -> list[NestedLocation]:
    """Every (inner, outer) pair, outermost first: for `/X`,
    `/X/Music` and `/X/Music/Test`, three pairs.
    """
    by_depth = sorted(
        locations,
        key=lambda location: (len(Path(location.path).parts), location.path),
    )

    return [
        NestedLocation(inner=inner, outer=outer)
        for outer in by_depth
        for inner in by_depth
        if inner is not outer
        and is_within(Path(inner.path), Path(outer.path))
    ]

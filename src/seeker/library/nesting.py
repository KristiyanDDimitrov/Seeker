"""Whether one library location sits inside another.

A location inside another indexes every file under it twice: once per
location, as two `local_files` rows for one real file.
"""
from dataclasses import dataclass
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


@dataclass(frozen=True)
class NestedPathMap:
    """Rewrites a path relative to one location's root as the same
    path relative to the other's, for two nested locations. `prefix`
    is the inner root relative to the outer one.
    """
    prefix: tuple[str, ...]
    source_is_inner: bool

    def map_parts(self, parts: tuple[str, ...]) -> tuple[str, ...] | None:
        """None when the path lies outside the target root."""
        if self.source_is_inner:
            return self.prefix + parts

        if parts[:len(self.prefix)] != self.prefix:
            return None

        return parts[len(self.prefix):]

    def map_relative_path(self, relative_path: str) -> str | None:
        """For a `local_files.relative_path`, in the scanner's own
        spelling (`str(path.relative_to(root))`).
        """
        parts = self.map_parts(Path(relative_path).parts)

        return str(Path(*parts)) if parts else None


def nested_path_map(source: Path, target: Path) -> NestedPathMap | None:
    """The map from `source`'s relative paths to `target`'s, or None
    when neither root is inside the other. The prefix keeps the inner
    root's own spelling of the folders between the two.
    """
    for inner, outer, source_is_inner in (
            (source, target, True),
            (target, source, False),
    ):
        for depth, parent in enumerate(inner.parents, start=1):
            if same_directory(parent, outer):
                return NestedPathMap(
                    prefix=inner.parts[-depth:],
                    source_is_inner=source_is_inner,
                )

    return None

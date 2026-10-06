from dataclasses import dataclass

from seeker.models.library_location import LibraryLocation


@dataclass(frozen=True)
class NestedLocation:
    """`inner` sits inside `outer`, so every file under `inner` is
    indexed twice: once per location.
    """
    inner: LibraryLocation
    outer: LibraryLocation

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanResult:
    """What one scan did to the `local_files` index: every file walked
    lands in exactly one of added, updated or unchanged; `removed` counts
    rows whose file was no longer found."""
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0

    def __add__(self, other: "ScanResult") -> "ScanResult":
        return ScanResult(
            added=self.added + other.added,
            updated=self.updated + other.updated,
            removed=self.removed + other.removed,
            unchanged=self.unchanged + other.unchanged,
        )


@dataclass
class MatchResult:
    """One `match_all` run: every track lands in exactly one bucket.
    A human-confirmed match counts as `auto`."""
    auto: int = 0
    needs_review: int = 0
    unmatched: int = 0

    def count(self, match_method: str | None) -> None:
        """Count one track by its `TrackMatch.match_method`."""
        if match_method == "auto":
            self.auto += 1
        elif match_method == "needs_review":
            self.needs_review += 1
        elif match_method is None:
            self.unmatched += 1
        else:
            raise ValueError(f"{match_method!r} is not a match method.")


@dataclass(frozen=True)
class ScanAndMatchResult:
    scan: ScanResult
    match: MatchResult

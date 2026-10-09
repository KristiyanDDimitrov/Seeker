from dataclasses import dataclass, field

from seeker.models.download_result import TrackFailure


@dataclass
class SweepResult:
    """One daily sweep over the loaded playlists' missing tracks.

    Each track the sweep searched lands in exactly one of `requested`,
    `still_missing` or `failures`. The rest were not searched:
    `already_in_progress` (a request is underway or done), `deferred`
    (past this sweep's search cap; the next sweep starts with them).
    Labels are "Artist - Title". `paused` means downloads were paused,
    before or during the sweep, and it stopped there; `stopped`, that
    its caller asked it to stop (Seeker quitting).
    """
    requested: list[str] = field(default_factory=list)
    # Searched, and nothing was requested: no candidate, or only one a
    # person has to review.
    still_missing: list[str] = field(default_factory=list)
    failures: list[TrackFailure] = field(default_factory=list)
    already_in_progress: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    # Loaded playlists skipped because no destination resolves.
    playlists_without_destination: list[str] = field(default_factory=list)
    paused: bool = False
    stopped: bool = False

    @property
    def searched(self) -> int:
        return (
            len(self.requested) + len(self.still_missing)
            + len(self.failures)
        )

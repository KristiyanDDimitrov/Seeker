from dataclasses import dataclass, field
from enum import StrEnum

from seeker.models.download_request import DownloadStatus


class TrackSearchOutcome(StrEnum):
    """What `DownloadService.search_and_request` did with one track.
    Only `ALREADY_IN_PROGRESS` returns without searching slskd."""

    ALREADY_IN_PROGRESS = "already_in_progress"
    REQUESTED = "requested"
    NEEDS_REVIEW = "needs_review"
    NO_CANDIDATE = "no_candidate"


class CancelOutcome(StrEnum):
    """What `DownloadService.cancel_download` did with one request."""

    CANCELLED = "cancelled"
    # slskd had already finished the transfer; the poll places it.
    ALREADY_FINISHED = "already_finished"


@dataclass(frozen=True)
class TrackFailure:
    track: str  # "Artist - Title"
    reason: str


@dataclass
class PlaylistDownloadResult:
    """What one `download_playlist` run did with a playlist's unmatched
    tracks. Every track lands in exactly one of requested, skipped or
    failures.

    `skipped` is the combined total of three different outcomes: the
    two named lists, plus tracks with no candidate at all
    (`no_candidate`). Never derive a count by subtracting from `total`.
    """
    requested: int = 0
    skipped: int = 0
    total: int = 0
    # "Artist - Title" labels.
    already_in_progress: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    failures: list[TrackFailure] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def no_candidate(self) -> int:
        return (
            self.skipped - len(self.already_in_progress)
            - len(self.needs_review)
        )


@dataclass(frozen=True)
class ManualDownloadResult:
    """The outcome of one `download_manual` call.

    `settled` means a practical candidate was requested (`username` and
    `filename` name it); `requested` without `settled` means only
    locked candidates were found and the retry cascade is chasing them.
    """
    track_id: str
    requested: bool
    settled: bool
    username: str | None = None
    filename: str | None = None
    # "no_candidate_found" or "locked_only" when not settled.
    reason: str | None = None


@dataclass
class PollResult:
    """One `poll_downloads` run: what moved this run (`queued` through
    `failed`, plus indexing of completed files), then how many rows sit
    in each waiting state afterwards (`ready_for_review` onwards)."""
    queued: int = 0
    downloading: int = 0
    completed: int = 0
    failed: int = 0
    # Completed settled downloads indexed into the library, or not.
    indexed: int = 0
    index_failed: int = 0
    ready_for_review: int = 0
    locked: int = 0
    shortlisted: int = 0
    superseded: int = 0
    unavailable: int = 0

    def count_in_flight(self, status: DownloadStatus) -> None:
        if status == DownloadStatus.QUEUED:
            self.queued += 1
        elif status == DownloadStatus.DOWNLOADING:
            self.downloading += 1
        else:
            raise ValueError(f"{status!r} is not an in-flight status.")

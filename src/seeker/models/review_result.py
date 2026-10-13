from dataclasses import dataclass, field

from seeker.models.download_result import TrackFailure


@dataclass
class ConfirmAllResult:
    """What one Review "Confirm all" did with a section's rows as shown:
    each lands in `confirmed` or `failures`, unless the batch ended
    early: `stopped` (Seeker quitting) or `outage` (slskd did not
    answer; the sentence to show), and the rows after the last one
    counted were left for review. A failed row is left for review too.
    """
    confirmed: int = 0
    failures: list[TrackFailure] = field(default_factory=list)
    stopped: bool = False
    outage: str | None = None

    @property
    def failed(self) -> int:
        return len(self.failures)

from dataclasses import dataclass, field


@dataclass
class FingerprintResult:
    """One `compute_fingerprints` run: every file in scope lands in
    exactly one count, unless `stopped`, when the files after the stop
    land in none. Each detail is `{"local_file_id", "reason",
    "message"}` for a failed file, `reason` naming the kind of failure.
    """
    computed: int = 0
    skipped_already_computed: int = 0
    failed: int = 0
    details: list[dict[str, str]] = field(default_factory=list)
    stopped: bool = False

    def __add__(self, other: "FingerprintResult") -> "FingerprintResult":
        return FingerprintResult(
            computed=self.computed + other.computed,
            skipped_already_computed=(
                self.skipped_already_computed
                + other.skipped_already_computed
            ),
            failed=self.failed + other.failed,
            details=self.details + other.details,
            stopped=self.stopped or other.stopped,
        )

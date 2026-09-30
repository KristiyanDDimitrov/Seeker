from dataclasses import dataclass, field
from typing import Literal

TagOutcome = Literal[
    "tagged",
    "tagged_without_art",
    "tagged_art_rarely_supported_format",
    "skipped_no_match",
    "skipped_format_unsupported",
    "skipped_already_tagged",
    "skipped_already_analyzed",
    "failed",
]


@dataclass
class TagResult:
    """One `tag_tracks` run, counted by outcome. The two `tagged_*` art
    counts are subsets of `tagged`. A track can add to more than one
    count: already tagged and already analysed, or a skip followed by a
    failure.

    Each detail is `{"track_id", "reason", "message"}`, for every track
    that was skipped, failed, or tagged with an art caveat.
    """
    tagged: int = 0
    # Text tags written, but no cover art: without this a CDN failure or
    # a missing album_art_url reads as plain success.
    tagged_without_art: int = 0
    # Art embedded into a WAV, which almost no DJ software reads.
    tagged_art_rarely_supported_format: int = 0
    skipped_no_match: int = 0
    skipped_format_unsupported: int = 0
    skipped_already_tagged: int = 0
    skipped_already_analyzed: int = 0
    failed: int = 0
    details: list[dict[str, str]] = field(default_factory=list)

    def record(
            self,
            track_id: str,
            outcome: TagOutcome,
            message: str | None = None,
            reason: str | None = None,
    ) -> None:
        """Count one outcome for a track. A `message` adds a detail row,
        under `reason` when given, else under `outcome`."""
        match outcome:
            case "tagged":
                self.tagged += 1
            case "tagged_without_art":
                self.tagged_without_art += 1
            case "tagged_art_rarely_supported_format":
                self.tagged_art_rarely_supported_format += 1
            case "skipped_no_match":
                self.skipped_no_match += 1
            case "skipped_format_unsupported":
                self.skipped_format_unsupported += 1
            case "skipped_already_tagged":
                self.skipped_already_tagged += 1
            case "skipped_already_analyzed":
                self.skipped_already_analyzed += 1
            case "failed":
                self.failed += 1

        if message is not None:
            self.details.append({
                "track_id": track_id,
                "reason": reason or outcome,
                "message": message,
            })


@dataclass
class FixArtResult:
    """One `fix_missing_art_for_playlist` run. Every track lands in
    exactly one count; `fixed_wav_rarely_supported` is not part of
    `fixed`. Details have the same shape as `TagResult.details`."""
    fixed: int = 0
    # Art embedded into a WAV, which almost no DJ software reads.
    fixed_wav_rarely_supported: int = 0
    already_correct: int = 0
    no_url: int = 0
    download_failed: int = 0
    embed_failed: int = 0
    format_unsupported: int = 0
    skipped_no_match: int = 0
    failed: int = 0
    details: list[dict[str, str]] = field(default_factory=list)

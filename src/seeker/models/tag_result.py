from dataclasses import dataclass, field


@dataclass
class TagResult:
    """One `tag_tracks` run. Every track lands in exactly one of
    `tagged`, the `skipped_*` counts or `failed`; the two `tagged_*`
    art counts are subsets of `tagged`.

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

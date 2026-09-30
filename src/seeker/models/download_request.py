from dataclasses import dataclass
from enum import StrEnum


class DownloadStatus(StrEnum):
    """A download request's state. Stored as the member's value, which
    it also compares equal to; `schema.py` describes each transition."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    LOCKED = "locked"
    READY_FOR_REVIEW = "ready_for_review"
    SHORTLISTED = "shortlisted"
    SUPERSEDED = "superseded"
    UNAVAILABLE = "unavailable"


class DownloadRole(StrEnum):
    # A settled request's file goes straight into the library; an
    # upgrade's waits in slskd's folder for a person to confirm it.
    SETTLED = "settled"
    UPGRADE = "upgrade"


# In slskd's queue or transferring now.
IN_FLIGHT = frozenset({DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING})

# Downloaded, waiting for a person to confirm the replacement.
AWAITING_A_HUMAN = frozenset({DownloadStatus.READY_FOR_REVIEW})

# Not transferring, but Seeker will try again on its own.
RETRYING_IN_BACKGROUND = frozenset({DownloadStatus.LOCKED, DownloadStatus.SHORTLISTED})

# Ended without a file, kept on screen until a person clears it.
FAILED_OUTCOMES = frozenset({DownloadStatus.FAILED, DownloadStatus.UNAVAILABLE})

# An end a person sees as the outcome; entering one stamps
# `completed_at`. Superseded is left out: it is an end no person sees.
STAMPS_COMPLETED_AT = FAILED_OUTCOMES | {DownloadStatus.COMPLETED}

# Not at an end yet: Seeker or a person still has something to do.
UNRESOLVED = IN_FLIGHT | RETRYING_IN_BACKGROUND | AWAITING_A_HUMAN

# Stops download_playlist() from requesting the track again: still
# being worked on, or already downloaded.
BLOCKS_REDOWNLOAD = UNRESOLVED | {DownloadStatus.COMPLETED}

# A row that will never report new transfer progress.
SHOWS_NO_FURTHER_PROGRESS = STAMPS_COMPLETED_AT | AWAITING_A_HUMAN


@dataclass
class DownloadRequest:
    track_id: str
    username: str
    filename: str
    format: str
    requested_at: str
    id: int | None = None
    quality_descriptor: str | None = None
    role: DownloadRole = DownloadRole.SETTLED
    status: DownloadStatus = DownloadStatus.QUEUED
    transfer_id: str | None = None
    size: int | None = None
    rank: int | None = None
    completed_at: str | None = None
    bytes_transferred: int | None = None
    total_bytes: int | None = None
    # Roadmap item 66 (Phase 4.3) — bounds the locked-retry loop.
    retry_count: int = 0
    next_retry_at: str | None = None
    failure_reason: str | None = None
    dismissed_at: str | None = None

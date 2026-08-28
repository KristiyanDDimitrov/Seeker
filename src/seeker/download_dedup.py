from seeker.models.download_request import DownloadRequest

# A "real candidate" is a specific peer offering a specific file for a
# specific track/role — two download_requests rows sharing all four are
# the same real download attempt, not two independent ones, regardless
# of which row happens to have been created first.
CandidateKey = tuple[str, str, str, str]


def candidate_key(request: DownloadRequest) -> CandidateKey:
    return (
        request.track_id, request.role, request.username, request.filename,
    )


def most_recent_per_candidate(
        requests: list[DownloadRequest],
) -> dict[CandidateKey, DownloadRequest]:
    """Groups requests representing the exact same real candidate (same
    track/role/peer/file) and keeps only the most-recently-requested one
    per group.

    Shared by both the read-side view
    (DashboardService.get_active_downloads, which never mutates the DB)
    and the write-side Phase 3 retry loop
    (DownloadService._retry_locked_request, which does) so both agree
    on the identical notion of "same real download attempt" — same
    consolidation reasoning already applied to matching.py and
    AUDIO_EXTENSIONS elsewhere in this codebase (see CLAUDE.md): one
    rule, not two independently-drifting copies.

    Deliberately compares only `requested_at` (a plain ISO 8601 string
    comparison — safe since every row uses the same
    datetime.now(timezone.utc).isoformat() format) with no
    status-aware tie-breaking (e.g. preferring a row that's genuinely
    `downloading` with real bytes over a merely `locked` one, even if
    the locked one happens to be more recent). No real duplicate
    observed in this project's production data has ever had nonzero
    `bytes_transferred` on more than one sibling at once, so this
    hasn't been a real problem — but a future duplicate where an OLDER
    row is genuinely mid-transfer and a NEWER stale row is merely
    `locked` would, with this rule, mark the older still-transferring
    row as the one to abandon. Worth revisiting with a status-aware
    tiebreak if that's ever seen for real, rather than guarding against
    a scenario that hasn't happened.
    """
    most_recent: dict[CandidateKey, DownloadRequest] = {}

    for request in requests:
        key = candidate_key(request)
        current_best = most_recent.get(key)

        if (
                current_best is None
                or request.requested_at > current_best.requested_at
        ):
            most_recent[key] = request

    return most_recent

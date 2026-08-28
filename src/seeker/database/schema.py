SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    track_count INTEGER NOT NULL,
    snapshot_id TEXT,
    synced_at TEXT,
    download_location_id INTEGER REFERENCES library_locations(id),
    download_subfolder TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    album_art_url TEXT
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id TEXT NOT NULL,
    track_id TEXT NOT NULL,

    PRIMARY KEY (playlist_id, track_id),

    FOREIGN KEY (playlist_id)
        REFERENCES playlists(id)
        ON DELETE CASCADE,

    FOREIGN KEY (track_id)
        REFERENCES tracks(id)
);

CREATE TABLE IF NOT EXISTS library_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS local_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    tag_artist TEXT,
    tag_title TEXT,
    tag_album TEXT,
    duration_ms INTEGER,
    scanned_at TEXT NOT NULL,
    bpm REAL,
    camelot_key TEXT,
    key_confidence REAL,
    tagged_at TEXT,

    UNIQUE (location_id, relative_path),

    FOREIGN KEY (location_id)
        REFERENCES library_locations(id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS track_matches (
    track_id TEXT NOT NULL PRIMARY KEY,
    local_file_id INTEGER,
    match_method TEXT,
    score REAL,
    matched_at TEXT NOT NULL,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
    FOREIGN KEY (local_file_id) REFERENCES local_files(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS download_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    username TEXT NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    quality_descriptor TEXT,
    role TEXT NOT NULL DEFAULT 'settled',
    -- status state machine. Eight values total:
    --   queued          in slskd's queue, not transferring yet.
    --   downloading     slskd is actively transferring it.
    --   completed       role='settled': file moved into the library —
    --                   either directly from queued/downloading, or
    --                   (item 26) via a locked role='settled' row whose
    --                   retry succeeded, auto-moved the same way, no
    --                   second confirmation. role='upgrade': the user
    --                   confirmed the replacement via `seeker downloads
    --                   review`. Terminal.
    --   failed          rejected/cancelled/errored/timed out/aborted,
    --                   for EITHER role, for any reason OTHER than the
    --                   confirmed lock pattern (see 'locked' below).
    --                   Terminal — never retried.
    --   locked          rejected specifically for being locked ("File
    --                   not shared", confirmed live) — NOT terminal,
    --                   retried automatically on every poll_downloads()
    --                   run until it succeeds, fails for a different
    --                   reason, or the track's entry is superseded.
    --                   Reached almost always via role='upgrade' (the
    --                   ordinary search pipeline never assigns a locked
    --                   candidate to 'settled' — see quality.py's
    --                   select_downloads), but role='settled' CAN also
    --                   reach it (item 26): confirm_review_candidate
    --                   requests a human-confirmed needs-review
    --                   candidate as 'settled', and that tier is never
    --                   filtered on lock status at all. On a successful
    --                   retry, role='upgrade' -> ready_for_review as
    --                   below; role='settled' -> completed directly,
    --                   the same "already confirmed once" reasoning.
    --   ready_for_review role='upgrade' only: slskd reports success,
    --                   but the file sits in slskd's own download dir
    --                   until a human confirms via `seeker downloads
    --                   review` — never auto-advances on its own.
    --   shortlisted     role='upgrade', rank 2/3 only: a known
    --                   candidate for this track, persisted at
    --                   `download_playlist()` time but never sent to
    --                   slskd — activated in place (same row,
    --                   transfer_id + status updated, not a new row)
    --                   only once every better-ranked entry for the
    --                   same track has been rejected.
    --   superseded      queued/downloading/locked/shortlisted, for a
    --                   track where a DIFFERENT entry already reached
    --                   ready_for_review first (or, item 25, an OLDER
    --                   duplicate row for the exact same real
    --                   candidate — see seeker/download_dedup.py).
    --                   Terminal — distinct from 'failed' so a
    --                   genuinely-dead attempt isn't confused with one
    --                   abandoned only because a better/newer candidate
    --                   already won.
    --
    -- Initial value: 'queued' for role='settled' and rank=1 upgrades
    -- (both requested immediately); 'shortlisted' for rank 2/3.
    --
    -- Real transitions (poll_downloads(), see download_service.py):
    --   queued/downloading -> completed/failed/ready_for_review/locked
    --     (status polled from slskd; the locked-pattern check applies
    --     to EITHER role as of item 26 — see the 'locked' bullet above.
    --     Only the Phase 4 cascade below stays role='upgrade'-specific)
    --   shortlisted -> queued/downloading/locked/failed
    --     (Phase 4 cascade: activated the instant the next-higher-ranked
    --     entry for the same track is rejected, same poll_downloads() run
    --     — role='upgrade' only; shortlisted rows are never role='settled')
    --   locked -> queued/downloading/locked/completed
    --     (Phase 3 retry: re-tried once per poll_downloads() run until
    --     it moves on or a sibling entry supersedes it first; a
    --     successful retry goes to 'completed' directly for
    --     role='settled', or 'ready_for_review' for role='upgrade')
    --   any of {queued,downloading,locked,shortlisted} -> superseded
    --     (the instant any OTHER entry for the same track reaches
    --     ready_for_review — see _supersede_others_for_track; or, item
    --     25, the instant an OLDER duplicate row for the identical
    --     candidate is seen by the Phase 3 retry loop's dedup check)
    --   ready_for_review -> completed
    --     (seeker downloads review, on user confirmation only — declining
    --     leaves it at ready_for_review, offered again next review run)
    status TEXT NOT NULL DEFAULT 'queued',
    -- slskd's own transfer UUID (from the batch-enqueue response), needed
    -- because its status endpoint is GET .../{username}/{id} — there's no
    -- documented way to look up a transfer by filename alone. Updated on
    -- each Phase 3 locked-retry attempt to the new transfer's id. NULL
    -- for a 'shortlisted' row until it's activated.
    transfer_id TEXT,
    -- File size in bytes, required to re-issue request_download on a
    -- Phase 3 locked retry, or to activate a Phase 4 shortlist entry
    -- (slskd's enqueue API requires it) — the exact same candidate, not
    -- a fresh search.
    size INTEGER,
    -- Phase 4: 1 = immediately requested, 2/3 = shortlisted (persisted,
    -- not yet sent to slskd until a higher rank is rejected). NULL for
    -- role='settled' — ranking only applies to the upgrade shortlist.
    rank INTEGER,
    requested_at TEXT NOT NULL,
    completed_at TEXT,
    -- Real progress numbers for the future progress-view screen, polled
    -- from slskd's own bytesTransferred/size fields (see
    -- soulseek/client.py's TransferStatus, confirmed live 2026-08-28).
    -- Nullable and unset until the first real progress poll; a
    -- rejected-before-any-bytes-moved request deliberately leaves these
    -- unset rather than zeroed, since a rejection isn't progress.
    bytes_transferred INTEGER,
    total_bytes INTEGER,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

-- Soulseek equivalent of track_matches' 'needs_review' tier (see
-- matching.py's AUTO_MATCH_THRESHOLD/NEEDS_REVIEW_THRESHOLD) — a real,
-- artist-matching Soulseek candidate that scored 70-89 (plausible, but
-- not confident enough to auto-download). One row per track (upserted,
-- not appended) holding only the single best-scoring such candidate.
-- Originally purely informational (surfaced read-only via `seeker
-- check`) — item 26 adds a real confirm action
-- (DownloadService.confirm_review_candidate), which needs `size` to
-- call request_download; a size-less legacy row (from before this
-- column existed) can't be confirmed until download_playlist() next
-- refreshes it. Cleared by download_playlist() the moment a later run
-- finds something better (a real auto-tier candidate, settled or
-- upgrade-shortlisted) for the same track, so a stale row can never
-- outlive the state it described.
CREATE TABLE IF NOT EXISTS soulseek_review_candidates (
    track_id TEXT NOT NULL PRIMARY KEY,
    username TEXT NOT NULL,
    filename TEXT NOT NULL,
    score REAL NOT NULL,
    quality_descriptor TEXT,
    found_at TEXT NOT NULL,
    size INTEGER,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);
"""
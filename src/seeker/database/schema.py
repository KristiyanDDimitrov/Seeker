SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    track_count INTEGER NOT NULL,
    snapshot_id TEXT,
    synced_at TEXT,
    download_location_id INTEGER REFERENCES library_locations(id),
    download_subfolder TEXT,
    -- The snapshot_id the cached playlist_tracks rows were loaded from;
    -- NULL until the playlist's tracks are first loaded.
    tracks_snapshot_id TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    album_art_url TEXT,
    -- When Seeker last searched slskd for this track (UTC ISO-8601);
    -- NULL until it has. The daily sweep searches the oldest first.
    last_searched_at TEXT
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
    -- 1/0 from the last read of the file; NULL until one succeeds.
    has_art INTEGER,
    fingerprint TEXT,
    fingerprint_duration REAL,
    fingerprint_computed_at TEXT,

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
    -- status: one of models/download_request.py's DownloadStatus
    -- values; the named status sets beside it say which group what.
    --   queued           in slskd's queue, not transferring yet.
    --   downloading      slskd is transferring it.
    --   completed        settled: the file is in the library. upgrade:
    --                    a person confirmed the replacement. Final.
    --   failed           rejected, cancelled, errored or timed out for a
    --                    reason other than a lock; failure_reason says
    --                    which. Final, never retried.
    --   locked           rejected as locked ("File not shared"). Retried
    --                    on each poll, no sooner than next_retry_at.
    --                    Mostly upgrades; a settled row gets here from a
    --                    person-confirmed needs-review candidate, which
    --                    is never filtered on lock status.
    --   ready_for_review upgrade only: downloaded, waiting in slskd's
    --                    folder for a person to confirm the replacement.
    --   shortlisted      upgrade rank 2/3: a known candidate, never sent
    --                    to slskd until every better-ranked one for the
    --                    track is rejected; then activated in place.
    --   superseded       another entry for the track reached
    --                    ready_for_review first, or this row is an older
    --                    duplicate of the same candidate
    --                    (seeker/download_dedup.py). Final, and distinct
    --                    from failed: nothing went wrong with it.
    --   unavailable      locked through LOCKED_RETRY_MAX_ATTEMPTS
    --                    retries. Final; failure_reason says why. Does
    --                    not block a later search from another peer.
    --
    -- Initial value: 'queued' for settled rows and rank-1 upgrades,
    -- 'shortlisted' for ranks 2 and 3.
    --
    -- Transitions (DownloadService.poll_downloads):
    --   queued/downloading -> completed/failed/ready_for_review/locked
    --   shortlisted -> queued/downloading/locked/failed (upgrade only)
    --   locked -> queued/downloading/locked/completed/ready_for_review/
    --             unavailable (a successful retry: completed for a
    --             settled row, ready_for_review for an upgrade)
    --   queued/downloading/locked/shortlisted -> superseded
    --   ready_for_review -> completed (a person confirms; declining
    --                       leaves it here, offered again later)
    status TEXT NOT NULL DEFAULT 'queued',
    -- slskd's own transfer UUID (from the batch-enqueue response),
    -- needed because its status endpoint is GET .../{username}/{id} —
    -- there's no documented way to look up a transfer by filename
    -- alone. Updated on each locked-retry attempt to the new transfer's
    -- id. NULL for a 'shortlisted' row until it's activated.
    transfer_id TEXT,
    -- File size in bytes, required to re-issue request_download on a
    -- locked retry, or to activate an upgrade shortlist entry (slskd's
    -- enqueue API requires it) — the exact same candidate, not a fresh
    -- search.
    size INTEGER,
    -- 1 = immediately requested, 2/3 = shortlisted (persisted, not yet
    -- sent to slskd until a higher rank is rejected). NULL for
    -- role='settled' — ranking only applies to the upgrade shortlist.
    rank INTEGER,
    requested_at TEXT NOT NULL,
    completed_at TEXT,
    -- Real progress numbers for the UI's progress bars, polled from
    -- slskd's own bytesTransferred/size fields (see
    -- soulseek/client.py's TransferStatus, confirmed live). Nullable
    -- and unset until the first real progress poll; a
    -- rejected-before-any-bytes-moved request deliberately leaves these
    -- unset rather than zeroed, since a rejection isn't progress.
    bytes_transferred INTEGER,
    total_bytes INTEGER,
    -- Bounds the locked-retry loop (HISTORY §66). NOT NULL DEFAULT 0 so
    -- a fresh row (and, via the guarded ALTER in connection.py, every
    -- pre-existing real 'locked' row) starts its backoff schedule from
    -- attempt 0. next_retry_at NULL means "no backoff in effect yet" (a
    -- row that's never been locked, or a fresh transition into 'locked'
    -- this run) — _retry_locked_request treats NULL the same as "due
    -- now."
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    -- Why a row became 'failed' or 'unavailable', in words a user can
    -- read ("Peer rejected: file not shared", "Timed out"). NULL for
    -- every other status, and for failures recorded before it existed.
    failure_reason TEXT,
    -- Set by the Downloads page's "Clear finished": hides a finished
    -- row from that page without deleting it (a manual track's request
    -- is what keeps the track, HISTORY §144).
    dismissed_at TEXT,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

-- Soulseek equivalent of track_matches' 'needs_review' tier (see
-- matching.py's AUTO_MATCH_THRESHOLD/NEEDS_REVIEW_THRESHOLD) — a real,
-- artist-matching Soulseek candidate that scored 70-89 (plausible, but
-- not confident enough to auto-download). One row per track (upserted,
-- not appended) holding only the single best-scoring such candidate.
-- Surfaced read-only by `seeker check`, and confirmable on the Review
-- page (ReviewService.confirm_review_candidate), which needs `size` to
-- call request_download; a size-less legacy row (from before this
-- column existed) can't be confirmed until download_playlist() next
-- refreshes it. Cleared by download_playlist() the moment a later run
-- finds something better (a real auto-tier candidate, settled or
-- upgrade-shortlisted) for the same track, so a stale row can never
-- outlive the state it described.
-- runner_up_*: the second-best-scoring candidate in the same
-- needs_review band, when one exists — quality.py's
-- find_best_needs_review_candidate already compares every candidate's
-- score to find the winner, so recording the runner-up it was
-- compared against costs nothing extra to compute, just to keep. NULL
-- when only one real candidate was found. Surfaced read-only on the
-- Review page so a human deciding whether to confirm the winner can
-- see what it beat, not just its own score in isolation.
CREATE TABLE IF NOT EXISTS soulseek_review_candidates (
    track_id TEXT NOT NULL PRIMARY KEY,
    username TEXT NOT NULL,
    filename TEXT NOT NULL,
    score REAL NOT NULL,
    quality_descriptor TEXT,
    found_at TEXT NOT NULL,
    size INTEGER,
    runner_up_username TEXT,
    runner_up_filename TEXT,
    runner_up_score REAL,
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

-- A purpose-built table rather than a generic key/value store: it gives
-- both the running total (SUM across every row) and a per-event history
-- the History page can surface later, whereas a KV blob would only ever
-- hold the running total and rot. One row per real duplicate-group
-- resolution (a real Delete click, confirmed and completed), not per
-- individual file.
CREATE TABLE IF NOT EXISTS duplicate_cleanups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    files_deleted INTEGER NOT NULL,
    bytes_freed INTEGER NOT NULL,
    -- Nullable: the location a cleanup happened in is worth recording
    -- when known, but not worth failing/blocking a cleanup over if it
    -- somehow isn't (mirrors this project's existing "an optional
    -- provenance field is stored best-effort" pattern rather than a
    -- NOT NULL constraint that could reject a real, valid cleanup).
    location_id INTEGER,
    FOREIGN KEY (location_id) REFERENCES library_locations(id) ON DELETE SET NULL
);

-- A human's Reject on the Review page: the matcher never suggests this
-- file for this track again, and falls through to the next best. Goes
-- with either parent.
CREATE TABLE IF NOT EXISTS rejected_local_matches (
    track_id TEXT NOT NULL,
    local_file_id INTEGER NOT NULL,
    rejected_at TEXT NOT NULL,
    PRIMARY KEY (track_id, local_file_id),
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE,
    FOREIGN KEY (local_file_id) REFERENCES local_files(id) ON DELETE CASCADE
);

-- The SoulSeek equivalent: this peer's file is never suggested or
-- requested for this track again. A peer's file has no row of its own
-- to cascade from, so only the track's delete removes it.
CREATE TABLE IF NOT EXISTS rejected_soulseek_candidates (
    track_id TEXT NOT NULL,
    username TEXT NOT NULL,
    filename TEXT NOT NULL,
    rejected_at TEXT NOT NULL,
    PRIMARY KEY (track_id, username, filename),
    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
);

-- Lookups by a foreign key or by status, including the ON DELETE SET
-- NULL a local_files delete runs against track_matches. Every column
-- here is in its table's CREATE TABLE above, so these run safely on an
-- older database before _migrate.
CREATE INDEX IF NOT EXISTS idx_track_matches_local_file_id
    ON track_matches (local_file_id);
CREATE INDEX IF NOT EXISTS idx_download_requests_track_id
    ON download_requests (track_id);
CREATE INDEX IF NOT EXISTS idx_download_requests_status_requested_at
    ON download_requests (status, requested_at);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track_id
    ON playlist_tracks (track_id);
"""

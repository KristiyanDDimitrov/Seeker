SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    track_count INTEGER NOT NULL,
    snapshot_id TEXT,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    duration_ms INTEGER NOT NULL
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
"""
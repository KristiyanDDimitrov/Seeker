import sqlite3

from seeker.database.connection import Database


def _create_pre_migration_download_requests_table(path):
    # Simulates a real, existing database from before bytes_transferred/
    # total_bytes existed — the exact download_requests shape as of the
    # last schema change before this one (see schema.py history), built
    # by hand rather than via SCHEMA (which already has the new columns)
    # so this test genuinely exercises the guarded ALTER TABLE path
    # instead of trivially passing against an already-current schema.
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE tracks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            album_art_url TEXT
        );

        CREATE TABLE download_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT NOT NULL,
            username TEXT NOT NULL,
            filename TEXT NOT NULL,
            format TEXT NOT NULL,
            quality_descriptor TEXT,
            role TEXT NOT NULL DEFAULT 'settled',
            status TEXT NOT NULL DEFAULT 'queued',
            transfer_id TEXT,
            size INTEGER,
            rank INTEGER,
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
        );
        """
    )

    # A real, pre-existing row — the thing this migration must not lose
    # or alter on any other column.
    connection.execute(
        "INSERT INTO tracks (id, title, artist, album, duration_ms) "
        "VALUES (?, ?, ?, ?, ?)",
        ("track-1", "Rhyme Dust", "MK, Dom Dolla", "Rhyme Dust", 215_000),
    )
    connection.execute(
        """
        INSERT INTO download_requests (
            track_id, username, filename, format, quality_descriptor,
            role, status, transfer_id, size, rank, requested_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "track-1",
            "real-peer",
            "Rhyme Dust.flac",
            "flac",
            "flac 1000kbps",
            "settled",
            "downloading",
            "real-transfer-id",
            52_428_800,
            None,
            "2026-08-28T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()


def test_initialize_adds_progress_columns_without_losing_existing_data(
        tmp_path,
):
    db_path = tmp_path / "seeker.db"
    _create_pre_migration_download_requests_table(db_path)

    database = Database(db_path)
    database.initialize()

    with database.transaction() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(download_requests)"
            ).fetchall()
        }
        assert "bytes_transferred" in columns
        assert "total_bytes" in columns

        row = connection.execute(
            "SELECT * FROM download_requests WHERE track_id = 'track-1'"
        ).fetchone()

    # The real pre-existing row survived untouched on every original
    # column, and the two new columns default to NULL rather than 0 or
    # some other value implying a real poll already happened.
    assert row["username"] == "real-peer"
    assert row["filename"] == "Rhyme Dust.flac"
    assert row["status"] == "downloading"
    assert row["transfer_id"] == "real-transfer-id"
    assert row["size"] == 52_428_800
    assert row["bytes_transferred"] is None
    assert row["total_bytes"] is None


def test_initialize_is_idempotent_on_an_already_migrated_database(
        tmp_path,
):
    db_path = tmp_path / "seeker.db"
    _create_pre_migration_download_requests_table(db_path)

    database = Database(db_path)
    database.initialize()
    database.initialize()  # must not error or duplicate the columns

    with database.transaction() as connection:
        columns = [
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(download_requests)"
            ).fetchall()
        ]

    assert columns.count("bytes_transferred") == 1
    assert columns.count("total_bytes") == 1

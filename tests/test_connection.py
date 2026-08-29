import sqlite3
import threading

import pytest

from seeker.dashboard_service import DashboardService
from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.download_request import DownloadRequest
from seeker.models.playlist import Playlist
from seeker.models.track import Track


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


def _create_pre_migration_local_files_table(path):
    # Simulates a real, existing database from before the fingerprint
    # columns existed (roadmap item 5's Phase 1) — built by hand rather
    # than via SCHEMA (which already has them) so this genuinely
    # exercises the guarded ALTER TABLE path.
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE library_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL UNIQUE,
            added_at TEXT NOT NULL
        );

        CREATE TABLE local_files (
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
            FOREIGN KEY (location_id) REFERENCES library_locations(id)
                ON DELETE CASCADE
        );
        """
    )

    connection.execute(
        "INSERT INTO library_locations (id, name, path, added_at) "
        "VALUES (1, 'Main', '/music', '2026-08-01T00:00:00+00:00')"
    )
    connection.execute(
        """
        INSERT INTO local_files (
            location_id, relative_path, filename, format, size_bytes,
            mtime, tag_artist, tag_title, scanned_at
        )
        VALUES (1, 'a.flac', 'a.flac', 'flac', 1000, 0.0,
                'Real Artist', 'Real Title', '2026-08-01T00:00:00+00:00')
        """
    )
    connection.commit()
    connection.close()


def test_initialize_adds_fingerprint_columns_without_losing_existing_data(
        tmp_path,
):
    db_path = tmp_path / "seeker.db"
    _create_pre_migration_local_files_table(db_path)

    database = Database(db_path)
    database.initialize()

    with database.transaction() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(local_files)"
            ).fetchall()
        }
        assert "fingerprint" in columns
        assert "fingerprint_duration" in columns
        assert "fingerprint_computed_at" in columns

        row = connection.execute(
            "SELECT * FROM local_files WHERE relative_path = 'a.flac'"
        ).fetchone()

    assert row["tag_artist"] == "Real Artist"
    assert row["tag_title"] == "Real Title"
    assert row["fingerprint"] is None
    assert row["fingerprint_duration"] is None
    assert row["fingerprint_computed_at"] is None


def test_initialize_closes_its_connection(tmp_path, monkeypatch):
    # Real bug, found via a real ResourceWarning during the UI polish
    # pass's error-handling audit: `with self.connect() as connection:`
    # only manages sqlite3's own commit/rollback transaction semantics,
    # not the connection's lifetime — it never closed the connection,
    # leaking one on every real Application() launch (and on every test
    # that builds a fresh Database), relying on GC to eventually finalize
    # it rather than closing deterministically like transaction() does.
    # sqlite3.Connection is an immutable C type — its close() method
    # can't be monkeypatched directly — so this captures the real
    # connection initialize() actually used and checks it's genuinely
    # closed afterward, the same reliable signal Python's own sqlite3
    # module uses (a closed connection raises ProgrammingError on use).
    database = Database(tmp_path / "seeker.db")
    real_connect = database.connect
    connections = []

    def spying_connect():
        connection = real_connect()
        connections.append(connection)
        return connection

    monkeypatch.setattr(database, "connect", spying_connect)

    database.initialize()

    assert len(connections) == 1

    with pytest.raises(sqlite3.ProgrammingError):
        connections[0].execute("SELECT 1")


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


def _create_pre_migration_soulseek_review_candidates_table(path):
    # Simulates a real, existing database from before `size` existed on
    # this table (item 26) — the exact shape this table has had since
    # item 17 first created it, built by hand rather than via SCHEMA
    # (which already has the new column).
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

        CREATE TABLE soulseek_review_candidates (
            track_id TEXT NOT NULL PRIMARY KEY,
            username TEXT NOT NULL,
            filename TEXT NOT NULL,
            score REAL NOT NULL,
            quality_descriptor TEXT,
            found_at TEXT NOT NULL,
            FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
        );
        """
    )

    connection.execute(
        "INSERT INTO tracks (id, title, artist, album, duration_ms) "
        "VALUES (?, ?, ?, ?, ?)",
        ("track-1", "ONE MORE NIGHT", "Prdk", "Album", 200_000),
    )
    connection.execute(
        """
        INSERT INTO soulseek_review_candidates (
            track_id, username, filename, score, quality_descriptor,
            found_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "track-1",
            "musicmasterrdjpool",
            "Prdk - One More Night (Clean) 4A 87.mp3",
            70.4,
            "mp3",
            "2026-08-27T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()


def test_initialize_adds_review_candidate_size_without_losing_existing_data(
        tmp_path,
):
    db_path = tmp_path / "seeker.db"
    _create_pre_migration_soulseek_review_candidates_table(db_path)

    database = Database(db_path)
    database.initialize()

    with database.transaction() as connection:
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(soulseek_review_candidates)"
            ).fetchall()
        }
        assert "size" in columns

        row = connection.execute(
            "SELECT * FROM soulseek_review_candidates "
            "WHERE track_id = 'track-1'"
        ).fetchone()

    # The real pre-existing row survived untouched on every original
    # column, and the new column defaults to NULL, not 0 — a size-less
    # legacy row is a distinct state (confirm_review_candidate must
    # refuse it) from a genuine zero-byte file.
    assert row["username"] == "musicmasterrdjpool"
    assert row["filename"] == "Prdk - One More Night (Clean) 4A 87.mp3"
    assert row["score"] == 70.4
    assert row["size"] is None


def test_concurrent_progress_writes_and_active_downloads_reads(tmp_path):
    # Targeted check for the Downloads screen's new combination: the
    # backend poll timer writes real progress from a background thread
    # (mirroring poll_downloads()'s update_progress calls) at the same
    # time the display-refresh timer reads via
    # DashboardService.get_active_downloads() from another thread. The
    # main dashboard's own stress test (item 22 in CLAUDE.md) already
    # established Database.transaction()'s per-call-connection pattern
    # is safe for concurrent readers/writers in general — this isn't a
    # meaningfully different access pattern (still short-lived,
    # independent connections per call), so a full re-run of that
    # broader stress test isn't needed; this confirms the specific new
    # writer+reader pair introduced by this task doesn't error or
    # corrupt state.
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    download_requests = DownloadRequestRepository(database)
    dashboard_service = DashboardService(
        database,
        PlaylistRepository(database),
        TrackRepository(database),
        TrackMatchRepository(database),
        download_requests,
        SoulseekReviewCandidateRepository(database),
        LocalFileRepository(database),
    )

    with database.transaction() as connection:
        dashboard_service.playlists.save(
            Playlist(id="p1", name="Playlist", track_count=1), connection,
        )
        dashboard_service.tracks.save(
            Track(
                id="t1", title="Title", artist="Artist", album="Album",
                duration_ms=200_000,
            ),
            connection,
        )
        dashboard_service.tracks.save_playlist_track("p1", "t1", connection)
        download_requests.add(
            DownloadRequest(
                track_id="t1",
                username="peer1",
                filename="file.flac",
                format="flac",
                status="downloading",
                transfer_id="transfer-1",
                requested_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )
        request_id = connection.execute(
            "SELECT id FROM download_requests WHERE track_id = 't1'"
        ).fetchone()[0]

    errors: list[BaseException] = []
    iterations = 50

    def writer() -> None:
        try:
            for i in range(iterations):
                with database.transaction() as connection:
                    download_requests.update_progress(
                        request_id, i, 1_000, connection,
                    )
        except BaseException as error:  # noqa: BLE001 - captured for the assertion below
            errors.append(error)

    def reader() -> None:
        try:
            for _ in range(iterations):
                dashboard_service.get_active_downloads()
        except BaseException as error:  # noqa: BLE001 - captured for the assertion below
            errors.append(error)

    threads = [
        threading.Thread(target=writer),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join(timeout=10)

    assert errors == []

    downloads = dashboard_service.get_active_downloads()
    assert len(downloads) == 1
    assert downloads[0].request.bytes_transferred == iterations - 1

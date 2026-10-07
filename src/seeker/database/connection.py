import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from seeker.database.schema import SCHEMA
from seeker.models.track import MANUAL_TRACK_ID_PREFIX


class Database:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(self.path)

        connection.row_factory = sqlite3.Row

        connection.execute("PRAGMA foreign_keys = ON")

        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        # `with self.connect() as connection:` looks equivalent but
        # isn't — sqlite3.Connection's own __enter__/__exit__ only
        # manage the transaction (commit on success, rollback on
        # exception); unlike transaction() above, it never closes the
        # connection. Without closing it, every initialize() call (once
        # per Application() launch, and once per test that builds a
        # fresh Database) leaks a connection to GC — observed as a real
        # "ResourceWarning: unclosed database".
        connection = self.connect()

        try:
            connection.executescript(SCHEMA)
            _migrate(connection)
            connection.commit()
        finally:
            connection.close()


# CREATE TABLE IF NOT EXISTS is a no-op against a pre-existing table, so a
# column added to SCHEMA after the real DB already has that table needs an
# explicit, idempotent ALTER TABLE here — there's no migration framework in
# this project yet, so this stays a set of plain guarded ALTERs rather
# than one.
def _migrate(connection: sqlite3.Connection) -> None:
    _add_column_if_missing(connection, "tracks", "album_art_url", "TEXT")
    _add_column_if_missing(connection, "local_files", "bpm", "REAL")
    _add_column_if_missing(connection, "local_files", "camelot_key", "TEXT")
    _add_column_if_missing(
        connection, "local_files", "key_confidence", "REAL"
    )
    _add_column_if_missing(connection, "download_requests", "size", "INTEGER")
    _add_column_if_missing(connection, "download_requests", "rank", "INTEGER")
    _add_column_if_missing(connection, "local_files", "tagged_at", "TEXT")
    _add_column_if_missing(
        connection, "download_requests", "bytes_transferred", "INTEGER"
    )
    _add_column_if_missing(
        connection, "download_requests", "total_bytes", "INTEGER"
    )
    _add_column_if_missing(
        connection, "soulseek_review_candidates", "size", "INTEGER"
    )
    _add_column_if_missing(connection, "local_files", "fingerprint", "TEXT")
    _add_column_if_missing(
        connection, "local_files", "fingerprint_duration", "REAL"
    )
    _add_column_if_missing(
        connection, "local_files", "fingerprint_computed_at", "TEXT"
    )
    _add_column_if_missing(
        connection, "track_matches", "confirmed_at", "TEXT"
    )
    # NULL, not 0: an existing row's file has not been read for art yet,
    # and the next scan reads it.
    _add_column_if_missing(connection, "local_files", "has_art", "INTEGER")
    # Bounds the locked-file retry loop (HISTORY §63, §66). NOT NULL
    # DEFAULT 0 so every pre-existing 'locked' row starts its backoff
    # schedule from attempt 0 on the very next poll, rather than NULL
    # breaking the `retry_count >= LOCKED_RETRY_MAX_ATTEMPTS` check.
    _add_column_if_missing(
        connection, "download_requests", "retry_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection, "download_requests", "next_retry_at", "TEXT"
    )
    _add_column_if_missing(
        connection, "download_requests", "failure_reason", "TEXT"
    )
    _add_column_if_missing(
        connection, "download_requests", "dismissed_at", "TEXT"
    )
    _add_column_if_missing(
        connection, "soulseek_review_candidates", "runner_up_username", "TEXT"
    )
    _add_column_if_missing(
        connection, "soulseek_review_candidates", "runner_up_filename", "TEXT"
    )
    _add_column_if_missing(
        connection, "soulseek_review_candidates", "runner_up_score", "REAL"
    )
    # Playlists loaded before this column existed are taken as current,
    # so the upgrade doesn't report every one of them as changed on
    # Spotify. Only on the run that adds the column: afterwards a
    # differing snapshot means real staleness.
    if _add_column_if_missing(
            connection, "playlists", "tracks_snapshot_id", "TEXT",
    ):
        connection.execute(
            """
            UPDATE playlists
            SET tracks_snapshot_id = snapshot_id
            WHERE EXISTS (
                SELECT 1 FROM playlist_tracks
                WHERE playlist_tracks.playlist_id = playlists.id
            )
            """
        )
    # A match pointing at no file is unmatched. Older builds let the
    # ON DELETE SET NULL cascade leave its method, score and
    # confirmation behind (HISTORY §139); today every local_files
    # delete resets them itself. Idempotent.
    connection.execute(
        """
        UPDATE track_matches
        SET match_method = NULL, score = NULL, confirmed_at = NULL
        WHERE local_file_id IS NULL AND match_method IS NOT NULL
        """
    )
    # Only a download request makes a manual track real. Older builds
    # saved one before searching, so a search that found nothing left
    # it behind, and a later match run could even match it. Its match
    # goes with it (ON DELETE CASCADE); the file stays. Idempotent.
    connection.execute(
        """
        DELETE FROM tracks
        WHERE id LIKE ?
            AND NOT EXISTS (
                SELECT 1 FROM download_requests
                WHERE download_requests.track_id = tracks.id
            )
        """,
        (f"{MANUAL_TRACK_ID_PREFIX}%",),
    )


def _add_column_if_missing(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        sql_type: str,
) -> bool:
    """Add the column if absent; True when it was added just now."""
    existing_columns = {
        row["name"]
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column in existing_columns:
        return False

    connection.execute(
        f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
    )
    return True

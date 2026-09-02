import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from seeker.database.schema import SCHEMA


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
        # connection. Every initialize() call (once per real
        # Application() launch, and once per test that builds a fresh
        # Database) was leaking a real connection, relying on GC to
        # eventually finalize it — confirmed live via a real
        # ResourceWarning: unclosed database, found during the UI
        # polish pass's error-handling audit, not assumed from reading
        # the diff alone.
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
    # Roadmap item 66 (Phase 4.3) — bounds the locked-file retry loop
    # (items 13/14/25/63). NOT NULL DEFAULT 0 so every pre-existing real
    # 'locked' row (there are several in production, some untouched
    # since 2026-08-27/28 — see docs/HISTORY.md item 63) starts its
    # backoff schedule from attempt 0 on the very next poll, rather than
    # NULL breaking the `retry_count >= LOCKED_RETRY_MAX_ATTEMPTS` check.
    _add_column_if_missing(
        connection, "download_requests", "retry_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection, "download_requests", "next_retry_at", "TEXT"
    )


def _add_column_if_missing(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        sql_type: str,
) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in existing_columns:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"
        )

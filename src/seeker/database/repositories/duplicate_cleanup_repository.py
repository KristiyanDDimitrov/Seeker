import sqlite3

from seeker.database.connection import Database
from seeker.models.duplicate_cleanup import DuplicateCleanup


class DuplicateCleanupRepository:
    def __init__(self, database: Database):
        self.database = database

    def add(
            self,
            cleanup: DuplicateCleanup,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT INTO duplicate_cleanups (
                occurred_at,
                files_deleted,
                bytes_freed,
                location_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                cleanup.occurred_at,
                cleanup.files_deleted,
                cleanup.bytes_freed,
                cleanup.location_id,
            ),
        )

    def get_totals(
            self,
            connection: sqlite3.Connection,
    ) -> tuple[int, int]:
        """(total_files_deleted, total_bytes_freed) across every real
        recorded cleanup — (0, 0) when none have happened yet."""
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(files_deleted), 0) AS total_files,
                COALESCE(SUM(bytes_freed), 0) AS total_bytes
            FROM duplicate_cleanups
            """
        ).fetchone()

        return int(row["total_files"]), int(row["total_bytes"])

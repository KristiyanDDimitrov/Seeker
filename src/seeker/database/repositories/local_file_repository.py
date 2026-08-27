import sqlite3

from seeker.database.connection import Database
from seeker.models.local_file import LocalFile


class LocalFileRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(
            self,
            local_file: LocalFile,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT INTO local_files (
                location_id,
                relative_path,
                filename,
                format,
                size_bytes,
                mtime,
                tag_artist,
                tag_title,
                tag_album,
                duration_ms,
                scanned_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_id, relative_path) DO UPDATE SET
                filename = excluded.filename,
                format = excluded.format,
                size_bytes = excluded.size_bytes,
                mtime = excluded.mtime,
                tag_artist = excluded.tag_artist,
                tag_title = excluded.tag_title,
                tag_album = excluded.tag_album,
                duration_ms = excluded.duration_ms,
                scanned_at = excluded.scanned_at
            """,
            (
                local_file.location_id,
                local_file.relative_path,
                local_file.filename,
                local_file.format,
                local_file.size_bytes,
                local_file.mtime,
                local_file.tag_artist,
                local_file.tag_title,
                local_file.tag_album,
                local_file.duration_ms,
                local_file.scanned_at,
            ),
        )

    def get_all(self, connection: sqlite3.Connection) -> list[LocalFile]:
        rows = connection.execute(
            """
            SELECT
                id,
                location_id,
                relative_path,
                filename,
                format,
                size_bytes,
                mtime,
                tag_artist,
                tag_title,
                tag_album,
                duration_ms,
                scanned_at
            FROM local_files
            """
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_by_id(
            self,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> LocalFile | None:
        row = connection.execute(
            """
            SELECT
                id,
                location_id,
                relative_path,
                filename,
                format,
                size_bytes,
                mtime,
                tag_artist,
                tag_title,
                tag_album,
                duration_ms,
                scanned_at
            FROM local_files
            WHERE id = ?
            """,
            (local_file_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_local_file(row)

    def get_by_location_and_relative_path(
            self,
            location_id: int,
            relative_path: str,
            connection: sqlite3.Connection,
    ) -> LocalFile | None:
        row = connection.execute(
            """
            SELECT
                id,
                location_id,
                relative_path,
                filename,
                format,
                size_bytes,
                mtime,
                tag_artist,
                tag_title,
                tag_album,
                duration_ms,
                scanned_at
            FROM local_files
            WHERE location_id = ? AND relative_path = ?
            """,
            (location_id, relative_path),
        ).fetchone()

        if row is None:
            return None

        return _row_to_local_file(row)

    def delete_missing(
            self,
            location_id: int,
            seen_relative_paths: set[str],
            connection: sqlite3.Connection,
    ) -> None:
        if not seen_relative_paths:
            connection.execute(
                "DELETE FROM local_files WHERE location_id = ?",
                (location_id,),
            )
            return

        placeholders = ", ".join("?" for _ in seen_relative_paths)

        connection.execute(
            f"""
            DELETE FROM local_files
            WHERE location_id = ?
            AND relative_path NOT IN ({placeholders})
            """,
            (location_id, *seen_relative_paths),
        )


def _row_to_local_file(row: sqlite3.Row) -> LocalFile:
    return LocalFile(
        id=row["id"],
        location_id=row["location_id"],
        relative_path=row["relative_path"],
        filename=row["filename"],
        format=row["format"],
        size_bytes=row["size_bytes"],
        mtime=row["mtime"],
        tag_artist=row["tag_artist"],
        tag_title=row["tag_title"],
        tag_album=row["tag_album"],
        duration_ms=row["duration_ms"],
        scanned_at=row["scanned_at"],
    )

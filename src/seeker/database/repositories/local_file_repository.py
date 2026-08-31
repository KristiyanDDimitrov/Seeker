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

    def update_analysis(
            self,
            local_file_id: int,
            bpm: float,
            camelot_key: str | None,
            key_confidence: float,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            UPDATE local_files
            SET bpm = ?, camelot_key = ?, key_confidence = ?
            WHERE id = ?
            """,
            (bpm, camelot_key, key_confidence, local_file_id),
        )

    def update_fingerprint(
            self,
            local_file_id: int,
            fingerprint: str,
            fingerprint_duration: float,
            fingerprint_computed_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        # Deliberately NOT part of upsert()'s ON CONFLICT DO UPDATE —
        # same reasoning as update_analysis() above (item 11's pattern):
        # a routine library scan must never wipe a previously-computed
        # fingerprint just because the file's tags/mtime were re-read.
        connection.execute(
            """
            UPDATE local_files
            SET fingerprint = ?,
                fingerprint_duration = ?,
                fingerprint_computed_at = ?
            WHERE id = ?
            """,
            (
                fingerprint,
                fingerprint_duration,
                fingerprint_computed_at,
                local_file_id,
            ),
        )

    def mark_tagged(
            self,
            local_file_id: int,
            tagged_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "UPDATE local_files SET tagged_at = ? WHERE id = ?",
            (tagged_at, local_file_id),
        )

    def exists_any(self, connection: sqlite3.Connection) -> bool:
        # A cheap existence check (roadmap item 7's Dashboard CTA needs
        # "has anything ever been scanned," not the actual rows) rather
        # than loading every local_files row via get_all() just to
        # check non-emptiness — this project's real production library
        # has 3,000+ rows (see CLAUDE.md item 39).
        row = connection.execute("SELECT 1 FROM local_files LIMIT 1").fetchone()
        return row is not None

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
                scanned_at,
                bpm,
                camelot_key,
                key_confidence,
                tagged_at,
                fingerprint,
                fingerprint_duration,
                fingerprint_computed_at
            FROM local_files
            """
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_all_for_location(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> list[LocalFile]:
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
                scanned_at,
                bpm,
                camelot_key,
                key_confidence,
                tagged_at,
                fingerprint,
                fingerprint_duration,
                fingerprint_computed_at
            FROM local_files
            WHERE location_id = ?
            """,
            (location_id,),
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
                scanned_at,
                bpm,
                camelot_key,
                key_confidence,
                tagged_at,
                fingerprint,
                fingerprint_duration,
                fingerprint_computed_at
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
                scanned_at,
                bpm,
                camelot_key,
                key_confidence,
                tagged_at,
                fingerprint,
                fingerprint_duration,
                fingerprint_computed_at
            FROM local_files
            WHERE location_id = ? AND relative_path = ?
            """,
            (location_id, relative_path),
        ).fetchone()

        if row is None:
            return None

        return _row_to_local_file(row)

    def delete_by_id(
            self,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        # track_matches.local_file_id references this via ON DELETE SET
        # NULL (see schema.py) -- a track matched to this file goes back
        # to unmatched rather than left pointing at a deleted row.
        connection.execute(
            "DELETE FROM local_files WHERE id = ?",
            (local_file_id,),
        )

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
        bpm=row["bpm"],
        camelot_key=row["camelot_key"],
        key_confidence=row["key_confidence"],
        tagged_at=row["tagged_at"],
        fingerprint=row["fingerprint"],
        fingerprint_duration=row["fingerprint_duration"],
        fingerprint_computed_at=row["fingerprint_computed_at"],
    )

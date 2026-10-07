import sqlite3
from collections.abc import Iterable

from seeker.models.local_file import LocalFile

# Ids bound per statement. SQLite's own limit is 32,766 bound parameters
# (999 before 3.32), so a big location's deletes go in chunks.
_ID_CHUNK_SIZE = 500

# Every read leaves the fingerprint columns out unless it asks for them:
# they hold ~9 KB of text a row on average, and only duplicate
# detection compares them (HISTORY §165).
_COLUMNS = """
    id, location_id, relative_path, filename, format, size_bytes, mtime,
    tag_artist, tag_title, tag_album, duration_ms, scanned_at, bpm,
    camelot_key, key_confidence, tagged_at, has_art
"""
_FINGERPRINT_COLUMNS = """
    fingerprint, fingerprint_duration, fingerprint_computed_at
"""


class LocalFileRepository:
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
                scanned_at,
                has_art
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_id, relative_path) DO UPDATE SET
                filename = excluded.filename,
                format = excluded.format,
                size_bytes = excluded.size_bytes,
                mtime = excluded.mtime,
                tag_artist = excluded.tag_artist,
                tag_title = excluded.tag_title,
                tag_album = excluded.tag_album,
                duration_ms = excluded.duration_ms,
                scanned_at = excluded.scanned_at,
                has_art = excluded.has_art
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
                local_file.has_art,
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
        # same reasoning as update_analysis() above (HISTORY §11): a
        # routine library scan must never wipe a previously-computed
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

    def update_relative_path(
            self,
            local_file_id: int,
            relative_path: str,
            filename: str,
            connection: sqlite3.Connection,
    ) -> None:
        # The DB-row side of a rename, called AFTER the real file move
        # already succeeded on disk (deliberately the opposite ordering
        # from the delete rule — see MetadataService.apply_renames' own
        # comment for why; HISTORY §40, §67). Keeps the same id, so
        # every track_matches row pointing at it survives untouched —
        # never delete-and-reinsert.
        connection.execute(
            """
            UPDATE local_files
            SET relative_path = ?, filename = ?
            WHERE id = ?
            """,
            (relative_path, filename, local_file_id),
        )

    def clear_content_derived_fields(
            self,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        # For a row whose file was replaced by different content under
        # the same path: upsert() deliberately preserves these, and
        # values measured on the old audio would describe the new one.
        connection.execute(
            """
            UPDATE local_files
            SET bpm = NULL,
                camelot_key = NULL,
                key_confidence = NULL,
                tagged_at = NULL,
                fingerprint = NULL,
                fingerprint_duration = NULL,
                fingerprint_computed_at = NULL
            WHERE id = ?
            """,
            (local_file_id,),
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

    def mark_has_art(
            self,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "UPDATE local_files SET has_art = 1 WHERE id = ?",
            (local_file_id,),
        )

    def exists_any(self, connection: sqlite3.Connection) -> bool:
        # A cheap existence check (the Dashboard's next-step guidance
        # needs "has anything ever been scanned," not the actual rows)
        # rather than loading every local_files row via get_all() just
        # to check non-emptiness — a real library has thousands of rows.
        row = connection.execute(
                "SELECT 1 FROM local_files LIMIT 1"
        ).fetchone()
        return row is not None

    def get_all(self, connection: sqlite3.Connection) -> list[LocalFile]:
        rows = connection.execute(
            f"""
            SELECT {_COLUMNS}
            FROM local_files
            """  # noqa: S608
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_tagged(self, connection: sqlite3.Connection) -> list[LocalFile]:
        rows = connection.execute(
            f"""
            SELECT {_COLUMNS}
            FROM local_files
            WHERE tagged_at IS NOT NULL
            """  # noqa: S608
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_matched_in_playlist(
            self,
            playlist_id: str,
            connection: sqlite3.Connection,
    ) -> list[LocalFile]:
        """The files the playlist's tracks are matched to."""
        rows = connection.execute(
            f"""
            SELECT {_COLUMNS}
            FROM local_files
            WHERE id IN (
                SELECT tm.local_file_id
                FROM track_matches tm
                JOIN playlist_tracks pt ON pt.track_id = tm.track_id
                WHERE pt.playlist_id = ?
            )
            """,  # noqa: S608
            (playlist_id,),
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_ids(self, connection: sqlite3.Connection) -> set[int]:
        rows = connection.execute("SELECT id FROM local_files").fetchall()

        return {row["id"] for row in rows}

    def get_all_for_location(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> list[LocalFile]:
        rows = connection.execute(
            f"""
            SELECT {_COLUMNS}
            FROM local_files
            WHERE location_id = ?
            """,  # noqa: S608
            (location_id,),
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_all_for_location_with_fingerprints(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> list[LocalFile]:
        rows = connection.execute(
            f"""
            SELECT {_COLUMNS}, {_FINGERPRINT_COLUMNS}
            FROM local_files
            WHERE location_id = ?
            """,  # noqa: S608
            (location_id,),
        ).fetchall()

        return [_row_to_local_file(row) for row in rows]

    def get_by_id(
            self,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> LocalFile | None:
        row = connection.execute(
            f"""
            SELECT {_COLUMNS}
            FROM local_files
            WHERE id = ?
            """,  # noqa: S608
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
            f"""
            SELECT {_COLUMNS}
            FROM local_files
            WHERE location_id = ? AND relative_path = ?
            """,  # noqa: S608
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
        self.delete_by_ids([local_file_id], connection)

    def delete_by_ids(
            self,
            local_file_ids: Iterable[int],
            connection: sqlite3.Connection,
    ) -> None:
        ids = list(local_file_ids)

        for start in range(0, len(ids), _ID_CHUNK_SIZE):
            chunk = tuple(ids[start:start + _ID_CHUNK_SIZE])
            # Built only from "?" and ", ", one per id; every value
            # still goes through the parameter tuple.
            where = f"id IN ({', '.join('?' for _ in chunk)})"
            _release_matches(connection, where, chunk)
            connection.execute(
                f"DELETE FROM local_files WHERE {where}",  # noqa: S608
                chunk,
            )

    def count_for_location(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> int:
        row = connection.execute(
            "SELECT COUNT(*) FROM local_files WHERE location_id = ?",
            (location_id,),
        ).fetchone()

        return int(row[0])

    def delete_all_for_location(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        _release_matches(connection, "location_id = ?", (location_id,))
        connection.execute(
            "DELETE FROM local_files WHERE location_id = ?",
            (location_id,),
        )


def _release_matches(
        connection: sqlite3.Connection,
        where: str,
        params: tuple[object, ...],
) -> None:
    """Resets every match pointing at the `local_files` rows `where`
    selects to a clean unmatched state. Call it before deleting those
    rows, in the same transaction.

    The schema's `ON DELETE SET NULL` alone only nulls `local_file_id`,
    leaving a method, score and `confirmed_at` on a row that points
    nowhere: shown missing, never downloaded, never re-matched
    (HISTORY §139).

    `where` must be a fixed SQL fragment over `local_files`' own
    columns; every value goes through `params`.
    """
    connection.execute(
        f"""
        UPDATE track_matches
        SET local_file_id = NULL,
            match_method = NULL,
            score = NULL,
            confirmed_at = NULL
        WHERE local_file_id IN (SELECT id FROM local_files WHERE {where})
        """,  # noqa: S608
        params,
    )


def _row_to_local_file(row: sqlite3.Row) -> LocalFile:
    # A Row's own `in` tests its values, not its column names.
    has_fingerprint = "fingerprint" in row.keys()  # noqa: SIM118

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
        has_art=None if row["has_art"] is None else bool(row["has_art"]),
        fingerprint=row["fingerprint"] if has_fingerprint else None,
        fingerprint_duration=(
            row["fingerprint_duration"] if has_fingerprint else None
        ),
        fingerprint_computed_at=(
            row["fingerprint_computed_at"] if has_fingerprint else None
        ),
    )

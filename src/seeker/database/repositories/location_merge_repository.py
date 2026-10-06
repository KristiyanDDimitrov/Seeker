import sqlite3
from collections.abc import Iterable

# Analysis columns that travel together: a kept file gains a group only
# when it has none of the group's values, so its own analysis is never
# overwritten or mixed with another row's.
_ANALYSIS_GROUPS = (
    ("bpm", "camelot_key", "key_confidence"),
    ("fingerprint", "fingerprint_duration", "fingerprint_computed_at"),
    ("tagged_at",),
)

# A merged row's analysis describes the file as it was when that row was
# scanned; it is carried only when both rows saw the same content.
_SAME_CONTENT = "kept.size_bytes = old.size_bytes AND kept.mtime = old.mtime"

# A pair's merged row is `old`; each query names the kept row `kept`.
_OLD_ROW_JOIN = """
    JOIN local_files AS old ON old.id = pairs.redundant_id
"""


def _carries(group: tuple[str, ...]) -> str:
    empty = " AND ".join(f"kept.{column} IS NULL" for column in group)
    present = " OR ".join(f"old.{column} IS NOT NULL" for column in group)

    return f"({empty} AND ({present}))"


class LocationMergeRepository:
    """Moves what hangs off one location's indexed files onto the rows
    another location holds for the same physical files.

    `stage` records the (merged row, kept row) pairs in a temporary
    table, which lives only as long as the connection, so every other
    call must use the connection `stage` was given.
    """

    def stage(
            self,
            pairs: Iterable[tuple[int, int]],
            merged_location_id: int,
            kept_location_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        """Records `(merged row id, kept row id)` pairs, keeping only
        those whose rows still exist in their locations: the pairs are
        computed outside the transaction, and a scan may have run since.
        """
        connection.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS merge_pairs (
                redundant_id INTEGER PRIMARY KEY,
                kept_id INTEGER NOT NULL
            )
            """
        )
        connection.execute("DELETE FROM temp.merge_pairs")
        connection.executemany(
            "INSERT INTO temp.merge_pairs (redundant_id, kept_id) "
            "VALUES (?, ?)",
            pairs,
        )
        connection.execute(
            """
            DELETE FROM temp.merge_pairs
            WHERE redundant_id NOT IN (
                SELECT id FROM local_files WHERE location_id = ?
            )
            OR kept_id NOT IN (
                SELECT id FROM local_files WHERE location_id = ?
            )
            """,
            (merged_location_id, kept_location_id),
        )

    def count_files(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT COUNT(*) FROM temp.merge_pairs"
        ).fetchone()

        return int(row[0])

    def count_matches(
            self,
            merged_location_id: int,
            connection: sqlite3.Connection,
    ) -> tuple[int, int]:
        """(matches that move, matches that are cleared) among those
        pointing at the merged location's files.
        """
        row = connection.execute(
            """
            SELECT
                COUNT(pairs.redundant_id),
                COUNT(*) - COUNT(pairs.redundant_id)
            FROM track_matches tm
            JOIN local_files lf ON lf.id = tm.local_file_id
            LEFT JOIN temp.merge_pairs pairs
                ON pairs.redundant_id = tm.local_file_id
            WHERE lf.location_id = ?
            """,
            (merged_location_id,),
        ).fetchone()

        return int(row[0]), int(row[1])

    def count_analyses(self, connection: sqlite3.Connection) -> int:
        """Kept files that gain at least one analysis group."""
        carries_any = " OR ".join(
            _carries(group) for group in _ANALYSIS_GROUPS
        )
        row = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM temp.merge_pairs pairs
            JOIN local_files AS kept ON kept.id = pairs.kept_id
            {_OLD_ROW_JOIN}
            WHERE {_SAME_CONTENT} AND ({carries_any})
            """,  # noqa: S608 - built from the constant column names above
        ).fetchone()

        return int(row[0])

    def move_matches(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE track_matches
            SET local_file_id = pairs.kept_id
            FROM temp.merge_pairs pairs
            WHERE track_matches.local_file_id = pairs.redundant_id
            """
        )

    def move_rejections(self, connection: sqlite3.Connection) -> None:
        """Copies each Review rejection to the kept row; the original
        goes when its file's row is deleted.
        """
        connection.execute(
            """
            INSERT OR IGNORE INTO rejected_local_matches (
                track_id,
                local_file_id,
                rejected_at
            )
            SELECT r.track_id, pairs.kept_id, r.rejected_at
            FROM rejected_local_matches r
            JOIN temp.merge_pairs pairs ON pairs.redundant_id = r.local_file_id
            """
        )

    def carry_analyses(self, connection: sqlite3.Connection) -> None:
        for group in _ANALYSIS_GROUPS:
            assignments = ", ".join(
                f"{column} = old.{column}" for column in group
            )
            connection.execute(
                f"""
                UPDATE local_files AS kept
                SET {assignments}
                FROM temp.merge_pairs pairs
                {_OLD_ROW_JOIN}
                WHERE kept.id = pairs.kept_id
                AND {_SAME_CONTENT}
                AND {_carries(group)}
                """,  # noqa: S608 - built from the constant column names above
            )

    def move_duplicate_cleanups(
            self,
            merged_location_id: int,
            kept_location_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "UPDATE duplicate_cleanups SET location_id = ? "
            "WHERE location_id = ?",
            (kept_location_id, merged_location_id),
        )

import sqlite3
from collections import defaultdict


class RejectionRepository:
    """What a human rejected on the Review page, for both kinds of
    suggestion: a local file for a track, and a SoulSeek peer's file
    for a track.
    """

    def add_local_match(
            self,
            track_id: str,
            local_file_id: int,
            rejected_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO rejected_local_matches (
                track_id,
                local_file_id,
                rejected_at
            )
            VALUES (?, ?, ?)
            """,
            (track_id, local_file_id, rejected_at),
        )

    def get_rejected_local_file_ids(
            self,
            connection: sqlite3.Connection,
    ) -> dict[str, set[int]]:
        """Every track's rejected local file ids, keyed by track id."""
        rejected: defaultdict[str, set[int]] = defaultdict(set)

        for row in connection.execute(
            "SELECT track_id, local_file_id FROM rejected_local_matches"
        ):
            rejected[row["track_id"]].add(row["local_file_id"])

        return dict(rejected)

    def add_soulseek_candidate(
            self,
            track_id: str,
            username: str,
            filename: str,
            rejected_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO rejected_soulseek_candidates (
                track_id,
                username,
                filename,
                rejected_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (track_id, username, filename, rejected_at),
        )

    def get_rejected_soulseek_candidates(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> set[tuple[str, str]]:
        """The (username, filename) pairs rejected for this track."""
        rows = connection.execute(
            """
            SELECT username, filename
            FROM rejected_soulseek_candidates
            WHERE track_id = ?
            """,
            (track_id,),
        ).fetchall()

        return {(row["username"], row["filename"]) for row in rows}

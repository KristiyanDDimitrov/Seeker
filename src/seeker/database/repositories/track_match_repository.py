import sqlite3

from seeker.database.connection import Database
from seeker.models.track_match import TrackMatch


class TrackMatchRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(
            self,
            track_match: TrackMatch,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT INTO track_matches (
                track_id,
                local_file_id,
                match_method,
                score,
                matched_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
                local_file_id = excluded.local_file_id,
                match_method = excluded.match_method,
                score = excluded.score,
                matched_at = excluded.matched_at
            """,
            (
                track_match.track_id,
                track_match.local_file_id,
                track_match.match_method,
                track_match.score,
                track_match.matched_at,
            ),
        )

    def get_all(self, connection: sqlite3.Connection) -> list[TrackMatch]:
        rows = connection.execute(
            """
            SELECT
                track_id,
                local_file_id,
                match_method,
                score,
                matched_at
            FROM track_matches
            """
        ).fetchall()

        return [_row_to_track_match(row) for row in rows]

    def get_by_track_id(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> TrackMatch | None:
        row = connection.execute(
            """
            SELECT
                track_id,
                local_file_id,
                match_method,
                score,
                matched_at
            FROM track_matches
            WHERE track_id = ?
            """,
            (track_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_track_match(row)


def _row_to_track_match(row: sqlite3.Row) -> TrackMatch:
    return TrackMatch(
        track_id=row["track_id"],
        local_file_id=row["local_file_id"],
        match_method=row["match_method"],
        score=row["score"],
        matched_at=row["matched_at"],
    )

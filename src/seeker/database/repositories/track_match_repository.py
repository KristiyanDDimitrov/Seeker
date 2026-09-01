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
                matched_at,
                confirmed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
                local_file_id = excluded.local_file_id,
                match_method = excluded.match_method,
                score = excluded.score,
                matched_at = excluded.matched_at,
                confirmed_at = excluded.confirmed_at
            """,
            (
                track_match.track_id,
                track_match.local_file_id,
                track_match.match_method,
                track_match.score,
                track_match.matched_at,
                track_match.confirmed_at,
            ),
        )

    def confirm(
            self,
            track_id: str,
            confirmed_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        """Stamps confirmed_at and sets match_method='auto' WITHOUT
        touching local_file_id/score/matched_at — a human confirming a
        needs_review candidate keeps the real computed score visible
        (item 45's precedent: provenance outweighs a sentinel, but a bad
        pairing must stay visible in the data), it just stops match_all()
        from recomputing this row on the next run.
        """
        connection.execute(
            """
            UPDATE track_matches
            SET match_method = 'auto', confirmed_at = ?
            WHERE track_id = ?
            """,
            (confirmed_at, track_id),
        )

    def delete(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "DELETE FROM track_matches WHERE track_id = ?",
            (track_id,),
        )

    def get_all(self, connection: sqlite3.Connection) -> list[TrackMatch]:
        rows = connection.execute(
            """
            SELECT
                track_id,
                local_file_id,
                match_method,
                score,
                matched_at,
                confirmed_at
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
                matched_at,
                confirmed_at
            FROM track_matches
            WHERE track_id = ?
            """,
            (track_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_track_match(row)

    def get_by_local_file_id(
            self,
            local_file_id: int,
            connection: sqlite3.Connection,
    ) -> list[TrackMatch]:
        # A list, not a single optional -- local_file_id isn't the
        # table's own primary key (track_id is), so nothing in the
        # schema actually prevents more than one track's match from
        # pointing at the same local file. Expected to be at most one
        # in practice, but returning a list is the honest contract
        # rather than assuming that and taking the first row.
        rows = connection.execute(
            """
            SELECT
                track_id,
                local_file_id,
                match_method,
                score,
                matched_at,
                confirmed_at
            FROM track_matches
            WHERE local_file_id = ?
            """,
            (local_file_id,),
        ).fetchall()

        return [_row_to_track_match(row) for row in rows]


def _row_to_track_match(row: sqlite3.Row) -> TrackMatch:
    return TrackMatch(
        track_id=row["track_id"],
        local_file_id=row["local_file_id"],
        match_method=row["match_method"],
        score=row["score"],
        matched_at=row["matched_at"],
        confirmed_at=row["confirmed_at"],
    )

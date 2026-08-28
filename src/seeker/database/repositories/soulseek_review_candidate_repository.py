import sqlite3

from seeker.database.connection import Database
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate


class SoulseekReviewCandidateRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(
            self,
            candidate: SoulseekReviewCandidate,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT INTO soulseek_review_candidates (
                track_id,
                username,
                filename,
                score,
                quality_descriptor,
                found_at,
                size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_id) DO UPDATE SET
                username = excluded.username,
                filename = excluded.filename,
                score = excluded.score,
                quality_descriptor = excluded.quality_descriptor,
                found_at = excluded.found_at,
                size = excluded.size
            """,
            (
                candidate.track_id,
                candidate.username,
                candidate.filename,
                candidate.score,
                candidate.quality_descriptor,
                candidate.found_at,
                candidate.size,
            ),
        )

    def get_by_track_id(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> SoulseekReviewCandidate | None:
        row = connection.execute(
            """
            SELECT
                track_id,
                username,
                filename,
                score,
                quality_descriptor,
                found_at,
                size
            FROM soulseek_review_candidates
            WHERE track_id = ?
            """,
            (track_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_candidate(row)

    def delete(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "DELETE FROM soulseek_review_candidates WHERE track_id = ?",
            (track_id,),
        )

    def get_all(
            self,
            connection: sqlite3.Connection,
    ) -> list[SoulseekReviewCandidate]:
        rows = connection.execute(
            """
            SELECT
                track_id,
                username,
                filename,
                score,
                quality_descriptor,
                found_at,
                size
            FROM soulseek_review_candidates
            ORDER BY found_at
            """
        ).fetchall()

        return [_row_to_candidate(row) for row in rows]


def _row_to_candidate(row: sqlite3.Row) -> SoulseekReviewCandidate:
    return SoulseekReviewCandidate(
        track_id=row["track_id"],
        username=row["username"],
        filename=row["filename"],
        score=row["score"],
        quality_descriptor=row["quality_descriptor"],
        found_at=row["found_at"],
        size=row["size"],
    )

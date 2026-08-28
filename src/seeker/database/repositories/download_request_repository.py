import sqlite3
from datetime import datetime, timezone

from seeker.database.connection import Database
from seeker.models.download_request import DownloadRequest


TERMINAL_STATUSES = {"completed", "failed"}


class DownloadRequestRepository:
    def __init__(self, database: Database):
        self.database = database

    def get_by_id(
            self,
            download_request_id: int,
            connection: sqlite3.Connection,
    ) -> DownloadRequest | None:
        row = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE id = ?
            """,
            (download_request_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_download_request(row)

    def add(
            self,
            download_request: DownloadRequest,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT INTO download_requests (
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                download_request.track_id,
                download_request.username,
                download_request.filename,
                download_request.format,
                download_request.quality_descriptor,
                download_request.role,
                download_request.status,
                download_request.transfer_id,
                download_request.size,
                download_request.rank,
                download_request.requested_at,
                download_request.completed_at,
            ),
        )

    def get_pending(
            self,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        rows = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE status IN ('queued', 'downloading')
            """
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_ready_for_review(
            self,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        rows = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE status = 'ready_for_review'
            ORDER BY requested_at
            """
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_locked(
            self,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        rows = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE status = 'locked'
            ORDER BY requested_at
            """
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_shortlisted(
            self,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        rows = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE status = 'shortlisted'
            ORDER BY track_id, rank
            """
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_superseded(
            self,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        rows = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE status = 'superseded'
            ORDER BY requested_at
            """
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_active_for_track(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        # "Active" = still in progress toward a real outcome — every
        # status except the three terminal end states (completed, failed,
        # superseded). Used by download_playlist() to avoid creating a
        # duplicate request for a track that's already being chased —
        # confirmed live (2026-08-27): re-running `seeker download` while
        # an earlier request for the same track was still 'locked'
        # created a second, otherwise-identical row instead of
        # recognizing the existing attempt.
        rows = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE track_id = ?
            AND status NOT IN ('completed', 'failed', 'superseded')
            """,
            (track_id,),
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_next_shortlisted(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> DownloadRequest | None:
        # Lowest surviving rank for this track — the entry the cascade
        # should activate next.
        row = connection.execute(
            """
            SELECT
                id,
                track_id,
                username,
                filename,
                format,
                quality_descriptor,
                role,
                status,
                transfer_id,
                size,
                rank,
                requested_at,
                completed_at,
                bytes_transferred,
                total_bytes
            FROM download_requests
            WHERE track_id = ? AND status = 'shortlisted'
            ORDER BY rank ASC
            LIMIT 1
            """,
            (track_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_download_request(row)

    def supersede_other_active_for_track(
            self,
            track_id: str,
            keep_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        # Called the moment one upgrade candidate for a track reaches
        # 'ready_for_review' — every other still-in-the-running entry for
        # the same track (queued/downloading/locked/shortlisted) is
        # dropped as 'superseded', not retried further. Scoped to
        # role='upgrade' defensively — settled-role rows are a separate
        # concept entirely and must never be touched here.
        connection.execute(
            """
            UPDATE download_requests
            SET status = 'superseded'
            WHERE track_id = ?
            AND id != ?
            AND role = 'upgrade'
            AND status IN ('queued', 'downloading', 'locked', 'shortlisted')
            """,
            (track_id, keep_id),
        )

    def mark_status(
            self,
            download_request_id: int,
            status: str,
            connection: sqlite3.Connection,
    ) -> None:
        completed_at = (
            datetime.now(timezone.utc).isoformat()
            if status in TERMINAL_STATUSES
            else None
        )

        connection.execute(
            """
            UPDATE download_requests
            SET status = ?, completed_at = ?
            WHERE id = ?
            """,
            (status, completed_at, download_request_id),
        )

    def update_transfer_id_and_status(
            self,
            download_request_id: int,
            transfer_id: str,
            status: str,
            connection: sqlite3.Connection,
    ) -> None:
        # Used by the Phase 3 locked-retry cycle: a new request_download
        # attempt against the same username+filename gets a new
        # transfer_id, whether the retry lands back in 'locked' or moves
        # on to 'queued'/'downloading' — either way, future status polls
        # need to target the latest attempt, not the stale one.
        completed_at = (
            datetime.now(timezone.utc).isoformat()
            if status in TERMINAL_STATUSES
            else None
        )

        connection.execute(
            """
            UPDATE download_requests
            SET transfer_id = ?, status = ?, completed_at = ?
            WHERE id = ?
            """,
            (transfer_id, status, completed_at, download_request_id),
        )

    def update_progress(
            self,
            download_request_id: int,
            bytes_transferred: int | None,
            total_bytes: int | None,
            connection: sqlite3.Connection,
    ) -> None:
        # Deliberately separate from mark_status/update_transfer_id_and_status
        # — same reasoning as update_analysis being kept out of upsert's
        # ON CONFLICT DO UPDATE: a routine progress poll must not risk
        # disturbing any unrelated column on the row.
        connection.execute(
            """
            UPDATE download_requests
            SET bytes_transferred = ?, total_bytes = ?
            WHERE id = ?
            """,
            (bytes_transferred, total_bytes, download_request_id),
        )


def _row_to_download_request(row: sqlite3.Row) -> DownloadRequest:
    return DownloadRequest(
        id=row["id"],
        track_id=row["track_id"],
        username=row["username"],
        filename=row["filename"],
        format=row["format"],
        quality_descriptor=row["quality_descriptor"],
        role=row["role"],
        status=row["status"],
        transfer_id=row["transfer_id"],
        size=row["size"],
        rank=row["rank"],
        requested_at=row["requested_at"],
        completed_at=row["completed_at"],
        bytes_transferred=row["bytes_transferred"],
        total_bytes=row["total_bytes"],
    )

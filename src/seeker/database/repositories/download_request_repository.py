import sqlite3
from collections.abc import Collection
from datetime import UTC, datetime

from seeker.models.download_request import (
    BLOCKS_REDOWNLOAD,
    FAILED_OUTCOMES,
    IN_FLIGHT,
    RETRYING_IN_BACKGROUND,
    STAMPS_COMPLETED_AT,
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)

# The statuses a locked retry treats as the same live candidate.
_RETRY_DUPLICATE_STATUSES = IN_FLIGHT | {DownloadStatus.LOCKED}

# Still in the running for a track, so a sibling reaching
# ready_for_review supersedes it.
_SUPERSEDABLE_STATUSES = IN_FLIGHT | RETRYING_IN_BACKGROUND


def _status_in(
        statuses: Collection[DownloadStatus],
) -> tuple[str, list[DownloadStatus]]:
    """`status IN (?, …)` and its parameters, in a fixed order."""
    values = sorted(statuses)

    return f"status IN ({', '.join('?' for _ in values)})", values


class DownloadRequestRepository:
    def get_all(self, connection: sqlite3.Connection) -> list[DownloadRequest]:
        # One playlist's requests: get_all_for_playlist.
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            """
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_all_for_playlist(
            self,
            playlist_id: str,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        # In id order, the order get_all() reads them in.
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE track_id IN (
                SELECT track_id FROM playlist_tracks WHERE playlist_id = ?
            )
            ORDER BY id
            """,
            (playlist_id,),
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
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
        in_flight, in_flight_params = _status_in(IN_FLIGHT)
        rows = connection.execute(
            f"""
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE {in_flight}
            """,  # noqa: S608
            in_flight_params,
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE status = ?
            ORDER BY requested_at
            """,
            (DownloadStatus.READY_FOR_REVIEW,),
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE status = ?
            ORDER BY requested_at
            """,
            (DownloadStatus.LOCKED,),
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE status = ?
            ORDER BY track_id, rank
            """,
            (DownloadStatus.SHORTLISTED,),
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE status = ?
            ORDER BY requested_at
            """,
            (DownloadStatus.SUPERSEDED,),
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_unavailable(
            self,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        # Mirrors get_superseded() exactly.
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE status = ?
            ORDER BY requested_at
            """,
            (DownloadStatus.UNAVAILABLE,),
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_unavailable_candidates_since(
            self,
            track_id: str,
            since: str,
            connection: sqlite3.Connection,
    ) -> set[tuple[str, str]]:
        """The (username, filename) pairs that went failed or
        unavailable for this track at or after `since`, an ISO-8601 UTC
        time."""
        failed, failed_params = _status_in(FAILED_OUTCOMES)
        rows = connection.execute(
            f"""
            SELECT username, filename
            FROM download_requests
            WHERE track_id = ? AND {failed} AND completed_at >= ?
            """,  # noqa: S608
            (track_id, *failed_params, since),
        ).fetchall()

        return {(row["username"], row["filename"]) for row in rows}

    def get_requests_blocking_redownload(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        """Every row that should stop download_playlist() from
        re-requesting this track: any non-terminal status (queued/
        downloading/locked/shortlisted/ready_for_review) OR a completed
        row — deliberately excludes failed/superseded/unavailable, the
        three states that genuinely mean "that attempt didn't work, a
        fresh one is fine." 'unavailable' is a locked candidate that
        exhausted its retry budget against ONE specific peer — a later
        run should be free to search again and find a different peer,
        not stay permanently blocked by a peer that never had it
        available.

        A completed row counts too, by design: if only in-progress rows
        counted, a completed request wouldn't be "active," so nothing
        would stop download_playlist() from re-searching and
        re-requesting an already-downloaded track — two
        differently-named files for one track, as happened once in the
        real DB. Keyed on track_id alone, deliberately NOT
        download_dedup.candidate_key — that key includes filename, so
        two differently-named files from two different peers would
        pass as "different candidates." See HISTORY §56.

        Known limitation, not solved here: there is currently no way to
        deliberately re-request a track that already has a completed
        row — if that becomes wanted, it needs an explicit override
        parameter on download_playlist(), not a weakening of this
        guard.
        """
        blocking, blocking_params = _status_in(BLOCKS_REDOWNLOAD)
        rows = connection.execute(
            f"""
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE track_id = ?
            AND {blocking}
            """,  # noqa: S608
            (track_id, *blocking_params),
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_active_candidates(
            self,
            track_id: str,
            role: DownloadRole,
            username: str,
            filename: str,
            connection: sqlite3.Connection,
    ) -> list[DownloadRequest]:
        # Every row for the exact same real candidate (identical
        # track/role/peer/file — see seeker.download_dedup) that's
        # currently in a live-retry-eligible state. Used by the locked
        # retry loop's dedup-before-retry check
        # (DownloadPoller._supersede_stale_duplicates) to find stale
        # sibling rows before re-issuing a real request_download for
        # one of them — without it, every duplicate row of one
        # candidate is retried independently, every poll cycle, against
        # the same real peer (observed live).
        # Deliberately scoped to queued/downloading/locked, NOT every
        # non-terminal status — shortlisted/ready_for_review rows are
        # a different mechanism with their own supersede path
        # (_supersede_others_for_track) and are never literal duplicates
        # of a locked candidate by construction (a shortlist candidate
        # is always a distinct real search result).
        live, live_params = _status_in(_RETRY_DUPLICATE_STATUSES)
        rows = connection.execute(
            f"""
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE track_id = ?
            AND role = ?
            AND username = ?
            AND filename = ?
            AND {live}
            """,  # noqa: S608
            (track_id, role, username, filename, *live_params),
        ).fetchall()

        return [_row_to_download_request(row) for row in rows]

    def get_next_shortlisted(
            self,
            track_id: str,
            role: DownloadRole,
            connection: sqlite3.Connection,
    ) -> DownloadRequest | None:
        # Lowest surviving rank for this track and role — the entry the
        # cascade should activate next. A settled failure must never
        # activate an upgrade, nor an upgrade failure a settled backup.
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
                total_bytes,
                retry_count,
                next_retry_at,
                failure_reason,
                dismissed_at
            FROM download_requests
            WHERE track_id = ? AND role = ? AND status = ?
            ORDER BY rank ASC
            LIMIT 1
            """,
            (track_id, role, DownloadStatus.SHORTLISTED),
        ).fetchone()

        if row is None:
            return None

        return _row_to_download_request(row)

    def supersede_other_active_for_track(
            self,
            track_id: str,
            keep_id: int,
            role: DownloadRole,
            connection: sqlite3.Connection,
    ) -> None:
        # Called the moment one candidate for a track wins: every other
        # still-in-the-running entry of the same role for the track
        # (queued/downloading/locked/shortlisted) is dropped as
        # 'superseded', not retried further. Never another role's: an
        # upgrade's win leaves the settled file alone, and the reverse.
        supersedable, supersedable_params = _status_in(_SUPERSEDABLE_STATUSES)
        connection.execute(
            f"""
            UPDATE download_requests
            SET status = ?
            WHERE track_id = ?
            AND id != ?
            AND role = ?
            AND {supersedable}
            """,  # noqa: S608
            (
                DownloadStatus.SUPERSEDED, track_id, keep_id, role,
                *supersedable_params,
            ),
        )

    def mark_status(
            self,
            download_request_id: int,
            status: DownloadStatus,
            connection: sqlite3.Connection,
            failure_reason: str | None = None,
    ) -> None:
        completed_at = (
            datetime.now(UTC).isoformat()
            if status in STAMPS_COMPLETED_AT
            else None
        )

        connection.execute(
            """
            UPDATE download_requests
            SET status = ?, completed_at = ?, failure_reason = ?
            WHERE id = ?
            """,
            (status, completed_at, failure_reason, download_request_id),
        )

    def dismiss_finished(
            self,
            dismissed_at: str,
            connection: sqlite3.Connection,
    ) -> int:
        finished, finished_params = _status_in(STAMPS_COMPLETED_AT)
        cursor = connection.execute(
            f"""
            UPDATE download_requests
            SET dismissed_at = ?
            WHERE {finished}
            AND dismissed_at IS NULL
            """,  # noqa: S608
            (dismissed_at, *finished_params),
        )

        return cursor.rowcount

    def dismiss(
            self,
            download_request_id: int,
            dismissed_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "UPDATE download_requests SET dismissed_at = ? WHERE id = ?",
            (dismissed_at, download_request_id),
        )

    def update_transfer_id_and_status(
            self,
            download_request_id: int,
            transfer_id: str,
            status: DownloadStatus,
            connection: sqlite3.Connection,
            failure_reason: str | None = None,
    ) -> None:
        # Used by the locked-retry cycle: a new request_download attempt
        # against the same username+filename gets a new transfer_id,
        # whether the retry lands back in 'locked' or moves on to
        # 'queued'/'downloading' — either way, future status polls need
        # to target the latest attempt, not the stale one.
        completed_at = (
            datetime.now(UTC).isoformat()
            if status in STAMPS_COMPLETED_AT
            else None
        )

        connection.execute(
            """
            UPDATE download_requests
            SET transfer_id = ?, status = ?, completed_at = ?,
                failure_reason = ?
            WHERE id = ?
            """,
            (
                transfer_id, status, completed_at, failure_reason,
                download_request_id,
            ),
        )

    def update_retry_state(
            self,
            download_request_id: int,
            retry_count: int,
            next_retry_at: str | None,
            connection: sqlite3.Connection,
    ) -> None:
        # The write side of the bounded locked-retry loop (HISTORY §66).
        # Deliberately separate from update_transfer_id_and_status
        # (called alongside it, not merged into it): retry bookkeeping
        # is orthogonal to what the actual attempt's outcome was.
        connection.execute(
            """
            UPDATE download_requests
            SET retry_count = ?, next_retry_at = ?
            WHERE id = ?
            """,
            (retry_count, next_retry_at, download_request_id),
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
        role=DownloadRole(row["role"]),
        status=DownloadStatus(row["status"]),
        transfer_id=row["transfer_id"],
        size=row["size"],
        rank=row["rank"],
        requested_at=row["requested_at"],
        completed_at=row["completed_at"],
        bytes_transferred=row["bytes_transferred"],
        total_bytes=row["total_bytes"],
        retry_count=row["retry_count"],
        next_retry_at=row["next_retry_at"],
        failure_reason=row["failure_reason"],
        dismissed_at=row["dismissed_at"],
    )

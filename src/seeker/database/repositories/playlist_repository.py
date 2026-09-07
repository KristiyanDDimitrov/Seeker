import sqlite3

from seeker.models.playlist import Playlist
from seeker.database.connection import Database
from datetime import datetime, UTC


class PlaylistRepository:
    def __init__(self, database: Database):
        self.database = database

    def save(self, playlist: Playlist, connection: sqlite3.Connection) -> None:
        synced_at = datetime.now(UTC).isoformat()

        connection.execute(
            """
            INSERT INTO playlists (
                id,
                name,
                track_count,
                snapshot_id,
                synced_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                track_count = excluded.track_count,
                snapshot_id = excluded.snapshot_id,
                synced_at = excluded.synced_at
            """,
            (
                playlist.id,
                playlist.name,
                playlist.track_count,
                playlist.snapshot_id,
                synced_at,
            ),
        )

    def get_by_id(
            self,
            playlist_id: str,
            connection: sqlite3.Connection,
    ) -> Playlist | None:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                track_count,
                snapshot_id,
                download_location_id,
                download_subfolder
            FROM playlists
            WHERE id = ?
            """,
            (playlist_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_playlist(row)

    def get_by_name(
            self,
            name: str,
            connection: sqlite3.Connection,
    ) -> Playlist | None:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                track_count,
                snapshot_id,
                download_location_id,
                download_subfolder
            FROM playlists
            WHERE name = ?
            """,
            (name,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_playlist(row)

    def get_all(self, connection: sqlite3.Connection) -> list[Playlist]:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                track_count,
                snapshot_id,
                download_location_id,
                download_subfolder
            FROM playlists
            ORDER BY name
            """
        ).fetchall()

        return [_row_to_playlist(row) for row in rows]

    def get_by_track_id(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> list[Playlist]:
        # No download_location_id filter — roadmap item 6's default-
        # destination fallback means a playlist with no
        # playlist-specific destination can still resolve one (the
        # configured default), so the caller (DownloadService's own
        # destination resolution) needs every playlist a track belongs
        # to, not just the ones already carrying an explicit override.
        # This filter used to live here; removing it without also
        # teaching the one real caller (_move_completed_file) to
        # resolve the default itself would have silently broken every
        # default-destination download exactly the way item 45's own
        # indexing gap did — checked and fixed together, not left as a
        # trap for whichever caller happened to exist first.
        rows = connection.execute(
            """
            SELECT
                p.id,
                p.name,
                p.track_count,
                p.snapshot_id,
                p.download_location_id,
                p.download_subfolder
            FROM playlists p
            JOIN playlist_tracks pt ON pt.playlist_id = p.id
            WHERE pt.track_id = ?
            ORDER BY p.name
            """,
            (track_id,),
        ).fetchall()

        return [_row_to_playlist(row) for row in rows]

    def get_playlist_names_by_track_id(
            self,
            connection: sqlite3.Connection,
    ) -> dict[str, list[str]]:
        # Whole-table join, no per-track query — used by
        # DashboardService.get_active_downloads() to build display-context
        # playlist names for the GLOBAL active-downloads view (every
        # download_requests row, across every playlist) without an N+1
        # query per row. Deliberately not filtered by
        # download_location_id (unlike get_by_track_id above, which
        # exists only to resolve a move destination) — this is purely
        # for display, so every playlist a track belongs to counts.
        rows = connection.execute(
            """
            SELECT pt.track_id, p.name
            FROM playlist_tracks pt
            JOIN playlists p ON p.id = pt.playlist_id
            ORDER BY p.name
            """
        ).fetchall()

        result: dict[str, list[str]] = {}

        for row in rows:
            result.setdefault(row["track_id"], []).append(row["name"])

        return result

    def set_destination(
            self,
            playlist_id: str,
            location_id: int,
            subfolder: str | None,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            UPDATE playlists
            SET download_location_id = ?, download_subfolder = ?
            WHERE id = ?
            """,
            (location_id, subfolder, playlist_id),
        )

    def delete(self, playlist_id: str, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM playlists
            WHERE id = ?
            """,
            (playlist_id,),
        )


def _row_to_playlist(row: sqlite3.Row) -> Playlist:
    return Playlist(
        id=row["id"],
        name=row["name"],
        track_count=row["track_count"],
        snapshot_id=row["snapshot_id"],
        download_location_id=row["download_location_id"],
        download_subfolder=row["download_subfolder"],
    )

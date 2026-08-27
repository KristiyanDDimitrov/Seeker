import sqlite3

from seeker.database.connection import Database
from seeker.models.track import Track


class TrackRepository:
    def __init__(self, database: Database):
        self.database = database

    def save(self, track: Track, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO tracks (
                id,
                title,
                artist,
                album,
                duration_ms,
                album_art_url
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                album = excluded.album,
                duration_ms = excluded.duration_ms,
                album_art_url = excluded.album_art_url
            """,
            (
                track.id,
                track.title,
                track.artist,
                track.album,
                track.duration_ms,
                track.album_art_url,
            ),
        )

    def get_by_id(
            self,
            track_id: str,
            connection: sqlite3.Connection,
    ) -> Track | None:
        row = connection.execute(
            """
            SELECT
                id,
                title,
                artist,
                album,
                duration_ms,
                album_art_url
            FROM tracks
            WHERE id = ?
            """,
            (track_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_track(row)

    def get_all(self, connection: sqlite3.Connection) -> list[Track]:
        rows = connection.execute(
            """
            SELECT
                id,
                title,
                artist,
                album,
                duration_ms,
                album_art_url
            FROM tracks
            """
        ).fetchall()

        return [_row_to_track(row) for row in rows]

    def get_unmatched_for_playlist(
            self,
            playlist_id: str,
            connection: sqlite3.Connection,
    ) -> list[Track]:
        rows = connection.execute(
            """
            SELECT
                t.id,
                t.title,
                t.artist,
                t.album,
                t.duration_ms,
                t.album_art_url
            FROM tracks t
            JOIN playlist_tracks pt ON pt.track_id = t.id
            LEFT JOIN track_matches tm ON tm.track_id = t.id
            WHERE pt.playlist_id = ?
            AND (tm.track_id IS NULL OR tm.match_method IS NULL)
            """,
            (playlist_id,),
        ).fetchall()

        return [_row_to_track(row) for row in rows]

    def get_auto_matched_for_playlist(
            self,
            playlist_id: str,
            connection: sqlite3.Connection,
    ) -> list[Track]:
        rows = connection.execute(
            """
            SELECT
                t.id,
                t.title,
                t.artist,
                t.album,
                t.duration_ms,
                t.album_art_url
            FROM tracks t
            JOIN playlist_tracks pt ON pt.track_id = t.id
            JOIN track_matches tm ON tm.track_id = t.id
            WHERE pt.playlist_id = ?
            AND tm.match_method = 'auto'
            """,
            (playlist_id,),
        ).fetchall()

        return [_row_to_track(row) for row in rows]

    def save_playlist_track(
        self,
        playlist_id: str,
        track_id: str,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO playlist_tracks (
                playlist_id,
                track_id
            )
            VALUES (?, ?)
            """,
            (
                playlist_id,
                track_id,
            ),
        )

    def replace_playlist_tracks(
            self,
            playlist_id: str,
            track_ids: list[str],
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            DELETE FROM playlist_tracks
            WHERE playlist_id = ?
            """,
            (playlist_id,),
        )

        connection.executemany(
            """
            INSERT INTO playlist_tracks (
                playlist_id,
                track_id
            )
            VALUES (?, ?)
            """,
            [
                (playlist_id, track_id)
                for track_id in track_ids
            ],
        )


def _row_to_track(row: sqlite3.Row) -> Track:
    return Track(
        id=row["id"],
        title=row["title"],
        artist=row["artist"],
        album=row["album"],
        duration_ms=row["duration_ms"],
        album_art_url=row["album_art_url"],
    )

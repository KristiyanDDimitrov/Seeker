import sqlite3

from seeker.models.track import Track


class TrackRepository:
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

    def get_all_for_playlist(
            self,
            playlist_id: str,
            connection: sqlite3.Connection,
    ) -> list[Track]:
        # Every track in the playlist, regardless of match status — used
        # to scope `seeker check`'s report to one playlist (unlike
        # get_unmatched_for_playlist/get_auto_matched_for_playlist, which
        # filter by match status too).
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
            WHERE pt.playlist_id = ?
            """,
            (playlist_id,),
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
            AND (
                tm.track_id IS NULL
                OR tm.match_method IS NULL
                OR tm.local_file_id IS NULL
            )
            """,
            (playlist_id,),
        ).fetchall()

        return [_row_to_track(row) for row in rows]

    def get_unmatched_for_playlists(
            self,
            playlist_ids: list[str],
            connection: sqlite3.Connection,
    ) -> list[Track]:
        """The unmatched tracks on any of `playlist_ids`, each once,
        least recently searched first (never searched before any)."""
        if not playlist_ids:
            return []

        placeholders = ", ".join("?" for _ in playlist_ids)
        rows = connection.execute(
            f"""
            SELECT DISTINCT
                t.id,
                t.title,
                t.artist,
                t.album,
                t.duration_ms,
                t.album_art_url,
                t.last_searched_at
            FROM tracks t
            JOIN playlist_tracks pt ON pt.track_id = t.id
            LEFT JOIN track_matches tm ON tm.track_id = t.id
            WHERE pt.playlist_id IN ({placeholders})
            AND (
                tm.track_id IS NULL
                OR tm.match_method IS NULL
                OR tm.local_file_id IS NULL
            )
            ORDER BY t.last_searched_at IS NOT NULL, t.last_searched_at, t.id
            """,  # noqa: S608 -- only "?" placeholders are interpolated
            playlist_ids,
        ).fetchall()

        return [_row_to_track(row) for row in rows]

    def mark_searched(
            self,
            track_id: str,
            searched_at: str,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "UPDATE tracks SET last_searched_at = ? WHERE id = ?",
            (searched_at, track_id),
        )

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
            AND tm.local_file_id IS NOT NULL
            """,
            (playlist_id,),
        ).fetchall()

        return [_row_to_track(row) for row in rows]

    def delete_if_unrequested(
        self,
        track_id: str,
        connection: sqlite3.Connection,
    ) -> None:
        """Deletes the track unless a download was requested for it."""
        connection.execute(
            """
            DELETE FROM tracks
            WHERE id = ?
                AND NOT EXISTS (
                    SELECT 1 FROM download_requests
                    WHERE download_requests.track_id = tracks.id
                )
            """,
            (track_id,),
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

from seeker.database.connection import Database
from seeker.models.track import Track


class TrackRepository:
    def __init__(self, database: Database):
        self.database = database

    def save(self, track: Track) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO tracks (
                    id,
                    title,
                    artist,
                    album,
                    duration_ms
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    album = excluded.album,
                    duration_ms = excluded.duration_ms
                """,
                (
                    track.id,
                    track.title,
                    track.artist,
                    track.album,
                    track.duration_ms,
                ),
            )

    def save_playlist_track(
        self,
        playlist_id: str,
        track_id: str,
    ) -> None:
        with self.database.connect() as connection:
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
    ) -> None:
        with self.database.connect() as connection:
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
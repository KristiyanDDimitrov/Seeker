from seeker.models.playlist import Playlist
from seeker.database.connection import Database
from datetime import datetime, timezone


class PlaylistRepository:
    def __init__(self, database: Database):
        self.database = database

    def save(self, playlist: Playlist) -> None:
        synced_at = datetime.now(timezone.utc).isoformat()

        with self.database.connect() as connection:
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

    def get_by_id(self, playlist_id: str) -> Playlist | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    name,
                    track_count,
                    snapshot_id
                FROM playlists
                WHERE id = ?
                """,
                (playlist_id,),
            ).fetchone()

        if row is None:
            return None

        return Playlist(
            id=row["id"],
            name=row["name"],
            track_count=row["track_count"],
            snapshot_id=row["snapshot_id"],
        )

    def get_all(self) -> list[Playlist]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    name,
                    track_count,
                    snapshot_id
                FROM playlists
                ORDER BY name
                """
            ).fetchall()

        return [
            Playlist(
                id=row["id"],
                name=row["name"],
                track_count=row["track_count"],
                snapshot_id=row["snapshot_id"],
            )
            for row in rows
        ]

    def delete(self, playlist_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                DELETE FROM playlists
                WHERE id = ?
                """,
                (playlist_id,),
            )
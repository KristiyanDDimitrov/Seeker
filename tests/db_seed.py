"""Rows tests seed directly, for states no service writes one at a time."""
import sqlite3


def add_playlist_track(
        playlist_id: str,
        track_id: str,
        connection: sqlite3.Connection,
) -> None:
    """Puts one track on a playlist. The app only ever writes a
    playlist's whole track list (`TrackRepository.replace_playlist_
    tracks`), so a test building a playlist track by track uses this.
    """
    connection.execute(
        "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id) "
        "VALUES (?, ?)",
        (playlist_id, track_id),
    )

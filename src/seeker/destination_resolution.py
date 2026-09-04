"""Playlist download-destination resolution — extracted from
DownloadService._resolve_destination (roadmap item 6/50) so a second
consumer doesn't grow its own copy of the same precedence rule. B3.4
(roadmap item 93) is exactly the situation this split exists to avoid:
the rename preview needing to know a track's *configured* destination
without a service in library/ reaching into soulseek/'s private method.

Precedence: a playlist-specific download_location_id/download_subfolder
always wins when set; otherwise the configured default destination
(item 50), resolved fresh via get_config() on every call so a Settings
change takes effect immediately, no restart — matching every other
config-backed value in this codebase. Returns None when neither
resolves to a real, still-registered location.
"""

from collections.abc import Callable
from sqlite3 import Connection

from seeker.config_store import SeekerConfig
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.filename_sanitize import sanitize_path_component
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist


def resolve_playlist_destination(
        playlist: Playlist | None,
        locations: LibraryLocationRepository,
        get_config: Callable[[], SeekerConfig],
        connection: Connection,
) -> tuple[LibraryLocation, str | None] | None:
    """playlist=None (roadmap item 82/P13.2) is a manual, not-from-
    Spotify track — always resolves via the configured default, with a
    fixed "Manual" subfolder, never a playlist-specific override or the
    per-playlist subfolder toggle (neither has meaning with no playlist).
    """
    if playlist is not None and playlist.download_location_id is not None:
        location = locations.get_by_id(
            playlist.download_location_id, connection,
        )

        if location is not None:
            return location, playlist.download_subfolder

    config = get_config()

    if config.default_download_location_id is None:
        return None

    default_location = locations.get_by_id(
        config.default_download_location_id, connection,
    )

    if default_location is None:
        return None

    if playlist is None:
        return default_location, "Manual"

    subfolder = (
        sanitize_path_component(playlist.name)
        if config.default_download_subfolder_per_playlist
        else None
    )

    return default_location, subfolder

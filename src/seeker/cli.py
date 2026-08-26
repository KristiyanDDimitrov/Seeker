import argparse

from seeker.application import Application
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seeker",
        description=(
            "Synchronize Spotify playlists and "
            "match them against a local music library."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
    )

    subparsers.add_parser(
        "sync",
        help="Synchronize Spotify data.",
    )

    subparsers.add_parser(
        "playlists",
        help="List locally stored Spotify playlists.",
    )

    subparsers.add_parser(
        "check",
        help="Check Spotify tracks against the local library.",
    )

    return parser

def handle_playlists(application: Application) -> None:
    repository = PlaylistRepository(
        application.database
    )

    playlists = repository.get_all()

    if not playlists:
        print("No Spotify playlists have been synchronized yet.")
        return

    for playlist in playlists:
        print(
            f"{playlist.name} "
            f"({playlist.track_count} tracks)"
        )

def handle_sync(application: Application) -> None:
    playlist_ids = (
        application.sync_service.sync_playlists()
    )

    for playlist_id in playlist_ids:
        application.sync_service.sync_playlist_tracks(
            playlist_id
        )

def run(
    application: Application,
    args: list[str] | None = None,
) -> None:
    parser = build_parser()
    parsed = parser.parse_args(args)

    if parsed.command is None:
        parser.print_help()
        return

    if parsed.command == "sync":
        handle_sync(application)

    elif parsed.command == "playlists":
        handle_playlists(application)

    elif parsed.command == "check":
        print(
            "Local library checking is not implemented yet."
        )
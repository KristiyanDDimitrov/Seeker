import argparse
import sys

from seeker.application import Application
from seeker.library.scanner import LibraryUnavailableError
from seeker.spotify.client import SpotifyRateLimitedError


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

    library_parser = subparsers.add_parser(
        "library",
        help="Manage local music library locations.",
    )

    library_subparsers = library_parser.add_subparsers(
        dest="library_command",
    )

    add_parser = library_subparsers.add_parser(
        "add",
        help="Register a new library location.",
    )
    add_parser.add_argument("name")
    add_parser.add_argument("path")

    library_subparsers.add_parser(
        "list",
        help="List registered library locations.",
    )

    remove_parser = library_subparsers.add_parser(
        "remove",
        help="Remove a registered library location.",
    )
    remove_parser.add_argument("name")

    library_subparsers.add_parser(
        "scan",
        help="Scan all registered library locations.",
    )

    library_subparsers.add_parser(
        "match",
        help="Match Spotify tracks against scanned local files.",
    )

    return parser

def handle_playlists(application: Application) -> None:
    playlists = application.sync_service.list_playlists()

    if not playlists:
        print("No Spotify playlists have been synchronized yet.")
        return

    for playlist in playlists:
        print(
            f"{playlist.name} "
            f"({playlist.track_count} tracks)"
        )

def handle_sync(application: Application) -> None:
    playlists = (
        application.sync_service.sync_playlists()
    )

    for playlist in playlists:
        application.sync_service.sync_playlist_tracks(
            playlist
        )

def handle_library(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.library_command == "add":
        application.library_service.add_location(
            parsed.name,
            parsed.path,
        )

    elif parsed.library_command == "list":
        locations = application.library_service.list_locations()

        if not locations:
            print("No library locations registered.")
            return

        for location, is_reachable in locations:
            status = "reachable" if is_reachable else "unreachable"

            print(
                f"{location.name}: {location.path} ({status})"
            )

    elif parsed.library_command == "remove":
        application.library_service.remove_location(
            parsed.name
        )

    elif parsed.library_command == "scan":
        application.library_service.scan_all()

    elif parsed.library_command == "match":
        application.track_matcher.match_all()

    else:
        print("Usage: seeker library {add,list,remove,scan,match} ...")

def handle_check(application: Application) -> None:
    report = application.track_matcher.generate_match_report()

    print(f"Auto-matched: {report['auto_count']}")

    needs_review = report["needs_review"]
    print(f"\nNeeds review ({len(needs_review)}):")

    for artist, title, score in needs_review:
        print(f"  {artist} - {title} (score: {score:.1f})")

    unmatched = report["unmatched"]
    print(f"\nUnmatched, needs a SoulSeek download ({len(unmatched)}):")

    for artist, title in unmatched:
        print(f"  {artist} - {title}")

def run(
    application: Application,
    args: list[str] | None = None,
) -> None:
    parser = build_parser()
    parsed = parser.parse_args(args)

    if parsed.command is None:
        parser.print_help()
        return

    try:
        if parsed.command == "sync":
            handle_sync(application)

        elif parsed.command == "playlists":
            handle_playlists(application)

        elif parsed.command == "check":
            handle_check(application)

        elif parsed.command == "library":
            handle_library(application, parsed)
    except SpotifyRateLimitedError as error:
        print(str(error))
        sys.exit(1)
    except LibraryUnavailableError as error:
        print(str(error))
        sys.exit(1)

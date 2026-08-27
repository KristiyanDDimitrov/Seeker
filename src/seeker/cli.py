import argparse
import sys

from seeker.application import Application
from seeker.library.scanner import LibraryUnavailableError
from seeker.models.playlist import Playlist
from seeker.spotify.client import SpotifyRateLimitedError
from seeker.spotify.sync_service import (
    PlaylistNotFoundError as SyncPlaylistNotFoundError,
    find_close_playlist_matches,
)


def resolve_playlist_or_offer_sync(
        name: str,
        application: Application,
) -> Playlist:
    """Shared playlist-name resolution for CLI commands that take one
    (currently just sync-tracks).

    Four real outcomes, in order:
      1. Found locally (case-insensitive) — returned immediately, no
         network call, no prompt.
      2. Not found, but a close match exists (difflib-based) — re-raises
         the original "Did you mean...?" error unchanged, WITHOUT
         offering a refresh. A close match means the name is probably a
         typo or a stale local rename, and a resync fixes neither of
         those, so offering one here would be actively misleading.
      3. Not found, no close match, user declines the refresh offer —
         re-raises the original "not found locally" error unchanged.
      4. Not found, no close match, user accepts — runs a real (but
         cheap, metadata-only) sync_playlists() and retries the lookup
         exactly once. If found now, returns it. If STILL not found,
         raises a distinct error stating the name doesn't exist on the
         account at all, rather than the generic "not found locally"
         message — the user already knows it isn't local; what they
         need to know now is that refreshing didn't help either.
    """
    try:
        return application.sync_service.get_playlist_by_name(name)
    except SyncPlaylistNotFoundError:
        local_names = [
            playlist.name
            for playlist in application.sync_service.list_playlists()
        ]
        close_matches = find_close_playlist_matches(name, local_names)

        if close_matches:
            raise

        answer = input(
            f"No playlist named '{name}' found locally — it may be "
            f"new. Refresh from Spotify now? [y/n] "
        ).strip().lower()

        if answer != "y":
            raise

        application.sync_service.sync_playlists()

        try:
            return application.sync_service.get_playlist_by_name(name)
        except SyncPlaylistNotFoundError:
            raise SyncPlaylistNotFoundError(
                f"No playlist named '{name}' found, even after "
                f"refreshing from Spotify. It doesn't exist on this "
                f"account."
            ) from None


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
        help="Synchronize Spotify playlist metadata (no tracks).",
    )

    sync_tracks_parser = subparsers.add_parser(
        "sync-tracks",
        help="Synchronize tracks for a single playlist.",
    )
    sync_tracks_parser.add_argument("playlist_name")

    subparsers.add_parser(
        "playlists",
        help="List locally stored Spotify playlists.",
    )

    check_parser = subparsers.add_parser(
        "check",
        help="Check Spotify tracks against the local library.",
    )
    check_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also list each auto-matched track with score and filename.",
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
    application.sync_service.sync_playlists()

    print()
    handle_playlists(application)


def handle_sync_tracks(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist = resolve_playlist_or_offer_sync(
        parsed.playlist_name, application
    )

    application.sync_service.sync_playlist_tracks(playlist)

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

def handle_check(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    report = application.track_matcher.generate_match_report()

    print(f"Auto-matched: {report['auto_count']}")

    if parsed.verbose:
        for artist, title, score, filename in report["auto_matched"]:
            print(f"  {artist} - {title} (score: {score:.1f}) -> {filename}")

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

        elif parsed.command == "sync-tracks":
            handle_sync_tracks(application, parsed)

        elif parsed.command == "playlists":
            handle_playlists(application)

        elif parsed.command == "check":
            handle_check(application, parsed)

        elif parsed.command == "library":
            handle_library(application, parsed)
    except SpotifyRateLimitedError as error:
        print(str(error))
        sys.exit(1)
    except LibraryUnavailableError as error:
        print(str(error))
        sys.exit(1)
    except SyncPlaylistNotFoundError as error:
        print(str(error))
        sys.exit(1)

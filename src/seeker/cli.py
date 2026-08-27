import argparse
import sys

from seeker.application import Application
from seeker.library.metadata_service import (
    PlaylistNotFoundError as MetadataPlaylistNotFoundError,
)
from seeker.library.scanner import LibraryUnavailableError
from seeker.models.playlist import Playlist
from seeker.soulseek.client import SoulseekDownloadError
from seeker.soulseek.download_service import (
    LibraryLocationNotFoundError,
    NoDestinationConfiguredError,
    PlaylistNotFoundError,
)
from seeker.spotify.client import SpotifyRateLimitedError
from seeker.spotify.sync_service import (
    PlaylistNotFoundError as SyncPlaylistNotFoundError,
    find_close_playlist_matches,
)


def resolve_playlist_or_offer_sync(
        name: str,
        application: Application,
) -> Playlist:
    """Shared playlist-name resolution for every CLI command that takes
    one (sync-tracks, playlists set-destination, download, library tag).

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

    playlists_parser = subparsers.add_parser(
        "playlists",
        help="List locally stored Spotify playlists.",
    )

    playlists_subparsers = playlists_parser.add_subparsers(
        dest="playlists_command",
    )

    set_destination_parser = playlists_subparsers.add_parser(
        "set-destination",
        help="Configure where a playlist's downloads should land.",
    )
    set_destination_parser.add_argument("playlist_name")
    set_destination_parser.add_argument("location_name")
    set_destination_parser.add_argument(
        "subfolder",
        nargs="?",
        default=None,
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

    download_parser = subparsers.add_parser(
        "download",
        help="Download a playlist's unmatched tracks via SoulSeek.",
    )
    download_parser.add_argument("playlist_name")

    downloads_parser = subparsers.add_parser(
        "downloads",
        help="Manage in-flight SoulSeek downloads.",
    )

    downloads_subparsers = downloads_parser.add_subparsers(
        dest="downloads_command",
    )

    downloads_subparsers.add_parser(
        "status",
        help=(
            "Poll pending downloads and update their status. "
            "Non-interactive — safe to automate."
        ),
    )

    downloads_subparsers.add_parser(
        "review",
        help=(
            "Interactively confirm or decline pending upgrade "
            "replacements."
        ),
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

    tag_parser = library_subparsers.add_parser(
        "tag",
        help=(
            "Write Spotify metadata (artist/title/album/art) onto every "
            "auto-matched track in a playlist."
        ),
    )
    tag_parser.add_argument("playlist_name")
    tag_parser.add_argument(
        "--analyze-audio",
        action="store_true",
        help=(
            "Also run local BPM/key analysis and write TBPM/TKEY — "
            "independent of and slower than the base metadata/art tag "
            "write."
        ),
    )
    tag_parser.add_argument(
        "--bpm-range",
        nargs=2,
        type=float,
        metavar=("MIN", "MAX"),
        default=None,
        help=(
            "Expected BPM range for octave-error correction (requires "
            "--analyze-audio), e.g. --bpm-range 160 180."
        ),
    )

    return parser

def handle_playlists(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.playlists_command == "set-destination":
        playlist = resolve_playlist_or_offer_sync(
            parsed.playlist_name, application
        )

        application.download_service.set_destination(
            playlist.name,
            parsed.location_name,
            parsed.subfolder,
        )
        return

    _print_playlists(application.sync_service.list_playlists())


def _print_playlists(playlists: list[Playlist]) -> None:
    if not playlists:
        print("No Spotify playlists have been synchronized yet.")
        return

    for playlist in playlists:
        print(
            f"{playlist.name} "
            f"({playlist.track_count} tracks)"
        )

def handle_download(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist = resolve_playlist_or_offer_sync(
        parsed.playlist_name, application
    )

    result = application.download_service.download_playlist(
        playlist.name
    )

    print(
        f"Requested {result['requested']} download(s), "
        f"skipped {result['skipped']} "
        f"(of {result['total']} unmatched tracks)."
    )

def handle_downloads(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.downloads_command == "status":
        counts = application.download_service.poll_downloads()

        print(
            f"Queued: {counts['queued']}, "
            f"Downloading: {counts['downloading']}, "
            f"Completed: {counts['completed']}, "
            f"Failed: {counts['failed']}, "
            f"Ready for review: {counts['ready_for_review']}, "
            f"Locked (retrying): {counts['locked']}, "
            f"Shortlisted (pending): {counts['shortlisted']}, "
            f"Superseded: {counts['superseded']}."
        )
        return

    if parsed.downloads_command == "review":
        application.download_service.review_pending_upgrades()
        return

    print("Usage: seeker downloads {status,review}")

def handle_sync(application: Application) -> None:
    application.sync_service.sync_playlists()

    print()
    _print_playlists(application.sync_service.list_playlists())


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

    elif parsed.library_command == "tag":
        if parsed.bpm_range and not parsed.analyze_audio:
            print("--bpm-range requires --analyze-audio.")
            return

        playlist = resolve_playlist_or_offer_sync(
            parsed.playlist_name, application
        )

        expected_bpm_range = (
            tuple(parsed.bpm_range) if parsed.bpm_range else None
        )

        result = application.metadata_service.tag_playlist(
            playlist.name,
            analyze_audio=parsed.analyze_audio,
            expected_bpm_range=expected_bpm_range,
        )

        print(
            f"Tagged: {result['tagged']}, "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Skipped (unsupported format): "
            f"{result['skipped_format_unsupported']}, "
            f"Failed: {result['failed']}."
        )

        if result["details"]:
            print("\nSkipped/failed:")

            for detail in result["details"]:
                print(f"  [{detail['reason']}] {detail['message']}")

    else:
        print(
            "Usage: seeker library {add,list,remove,scan,match,tag} ..."
        )

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
            handle_playlists(application, parsed)

        elif parsed.command == "check":
            handle_check(application, parsed)

        elif parsed.command == "library":
            handle_library(application, parsed)

        elif parsed.command == "download":
            handle_download(application, parsed)

        elif parsed.command == "downloads":
            handle_downloads(application, parsed)
    except SpotifyRateLimitedError as error:
        print(str(error))
        sys.exit(1)
    except LibraryUnavailableError as error:
        print(str(error))
        sys.exit(1)
    except (
            PlaylistNotFoundError,
            SyncPlaylistNotFoundError,
            MetadataPlaylistNotFoundError,
            NoDestinationConfiguredError,
            LibraryLocationNotFoundError,
            SoulseekDownloadError,
    ) as error:
        print(str(error))
        sys.exit(1)

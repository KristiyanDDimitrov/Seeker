import argparse
import sqlite3
import sys
from collections import Counter

import httpx

from seeker.application import Application
from seeker.error_text import describe_error
from seeker.errors import PlaylistNotFoundError, SeekerError
from seeker.formatting import format_file_size, format_timestamp
from seeker.history_service import DEFAULT_LIMIT as DEFAULT_HISTORY_LIMIT
from seeker.library.metadata_service import RenamePlan
from seeker.models.playlist import Playlist
from seeker.soulseek.download_service import NoDestinationConfiguredError
from seeker.soulseek.quality import rank_candidates
from seeker.spotify.sync_service import find_close_playlist_matches


def printable(text: str) -> str:
    """`text` without C0/C1 control characters, tab kept.

    For any string a SoulSeek peer chose (a filename, a username, an
    error quoting them) before it reaches the terminal: an ESC or CSI
    sequence in it could otherwise clear the screen, retitle the
    window or plant an OSC 8 link.
    """
    return "".join(
        char for char in text
        if char == "\t" or not (
            char < " " or "\x7f" <= char <= "\x9f"
        )
    )


def resolve_playlist_or_offer_sync(
        name: str,
        application: Application,
) -> Playlist:
    """Shared playlist-name resolution for every CLI command that takes
    one (sync-tracks, playlists set-destination, download, library tag,
    check).

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
    except PlaylistNotFoundError:
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
        except PlaylistNotFoundError:
            raise PlaylistNotFoundError(
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
    parser.set_defaults(handler=None)

    subparsers = parser.add_subparsers(
        dest="command",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronize Spotify playlist metadata (no tracks).",
    )
    sync_parser.set_defaults(handler=handle_sync)

    sync_tracks_parser = subparsers.add_parser(
        "sync-tracks",
        help="Synchronize tracks for a single playlist.",
    )
    sync_tracks_parser.set_defaults(handler=handle_sync_tracks)
    sync_tracks_parser.add_argument("playlist_name")

    playlists_parser = subparsers.add_parser(
        "playlists",
        help="List locally stored Spotify playlists.",
    )
    playlists_parser.set_defaults(handler=handle_playlists_list)

    playlists_subparsers = playlists_parser.add_subparsers(
        dest="playlists_command",
    )

    set_destination_parser = playlists_subparsers.add_parser(
        "set-destination",
        help="Configure where a playlist's downloads should land.",
    )
    set_destination_parser.set_defaults(handler=handle_playlists_set_destination)
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
    check_parser.set_defaults(handler=handle_check)
    check_parser.add_argument(
        "playlist_name",
        nargs="?",
        default=None,
        help=(
            "Scope the report to a single playlist's tracks. Omit to "
            "report across all synced playlists."
        ),
    )
    check_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Also list each auto-matched track with score and filename.",
    )

    review_parser = subparsers.add_parser(
        "review",
        help=(
            "Confirm or reject needs-review LOCAL-FILE matches (distinct "
            "from 'downloads review', which is for SoulSeek upgrade "
            "candidates)."
        ),
    )
    review_parser.set_defaults(handler=handle_review)
    review_parser.add_argument(
        "playlist_name",
        nargs="?",
        default=None,
        help=(
            "Scope the listing to a single playlist. Omit to list "
            "across all synced playlists."
        ),
    )
    review_parser.add_argument(
        "--confirm",
        metavar="TRACK_ID",
        default=None,
        help="Confirm a needs-review match as correct.",
    )
    review_parser.add_argument(
        "--reject",
        metavar="TRACK_ID",
        default=None,
        help="Reject a needs-review match; that file is never "
             "suggested for that track again.",
    )

    download_parser = subparsers.add_parser(
        "download",
        help="Download a playlist's unmatched tracks via SoulSeek.",
    )
    download_parser.set_defaults(handler=handle_download)
    download_parser.add_argument("playlist_name")

    # Roadmap item 82 (P13.6) — a track that isn't in any Spotify
    # playlist, reusing the exact same search/ranking/download path as
    # `download` (DownloadService.search_manual/download_manual) —
    # never a second copy of that logic.
    search_parser = subparsers.add_parser(
        "search",
        help=(
            "Search SoulSeek for a track that isn't in any Spotify "
            "playlist."
        ),
    )
    search_parser.set_defaults(handler=handle_search)
    search_parser.add_argument("artist")
    search_parser.add_argument("title")
    search_parser.add_argument(
        "--download",
        action="store_true",
        help=(
            "Download the best available candidate (with automatic "
            "fallback) instead of just listing search results."
        ),
    )

    downloads_parser = subparsers.add_parser(
        "downloads",
        help="Manage in-flight SoulSeek downloads.",
    )

    downloads_subparsers = downloads_parser.add_subparsers(
        dest="downloads_command",
        required=True,
    )

    downloads_status_parser = downloads_subparsers.add_parser(
        "status",
        help=(
            "Poll pending downloads and update their status. "
            "Non-interactive — safe to automate."
        ),
    )
    downloads_status_parser.set_defaults(handler=handle_downloads_status)

    downloads_review_parser = downloads_subparsers.add_parser(
        "review",
        help=(
            "Interactively confirm or decline pending upgrade "
            "replacements."
        ),
    )
    downloads_review_parser.set_defaults(handler=handle_downloads_review)
    downloads_review_parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Roadmap item R3.1/R3.4 — replace every pending upgrade at "
            "once instead of prompting per row (CLI parity for the "
            "UI's \"Replace all\"). Prompts once for whether to also "
            "delete the old files, then applies to the whole batch."
        ),
    )

    history_parser = subparsers.add_parser(
        "history",
        help=(
            "Recently downloaded and tagged tracks, derived from "
            "existing data — not a permanent log (see --help)."
        ),
    )
    history_parser.set_defaults(handler=handle_history)
    history_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            f"Max events to show (default {DEFAULT_HISTORY_LIMIT}). "
            "Derived from current download_requests/local_files rows "
            "only — an event disappears if the row it came from is "
            "later deleted (e.g. via 'library duplicates'), and "
            "download failures aren't shown at all (no failure reason "
            "is persisted to describe them honestly)."
        ),
    )

    library_parser = subparsers.add_parser(
        "library",
        help="Manage local music library locations.",
    )

    library_subparsers = library_parser.add_subparsers(
        dest="library_command",
        required=True,
    )

    add_parser = library_subparsers.add_parser(
        "add",
        help="Register a new library location.",
    )
    add_parser.set_defaults(handler=handle_library_add)
    add_parser.add_argument("name")
    add_parser.add_argument("path")

    list_parser = library_subparsers.add_parser(
        "list",
        help="List registered library locations.",
    )
    list_parser.set_defaults(handler=handle_library_list)

    remove_parser = library_subparsers.add_parser(
        "remove",
        help="Remove a registered library location.",
    )
    remove_parser.set_defaults(handler=handle_library_remove)
    remove_parser.add_argument("name")

    scan_parser = library_subparsers.add_parser(
        "scan",
        help="Scan all registered library locations.",
    )
    scan_parser.set_defaults(handler=handle_library_scan)
    scan_parser.add_argument(
        "--match",
        action="store_true",
        help=(
            "Also run a match pass immediately after scanning, in one "
            "call (roadmap item 56) — 'scan' alone stays available for "
            "scripted/cron use where a separate 'library match' call is "
            "preferred."
        ),
    )

    match_parser = library_subparsers.add_parser(
        "match",
        help="Match Spotify tracks against scanned local files.",
    )
    match_parser.set_defaults(handler=handle_library_match)

    tag_parser = library_subparsers.add_parser(
        "tag",
        help=(
            "Write Spotify metadata (artist/title/album/art) onto every "
            "auto-matched track in a playlist."
        ),
    )
    tag_parser.set_defaults(handler=handle_library_tag)
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
    tag_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bypass the already-tagged/already-analyzed skip checks and "
            "redo both for every track, e.g. after Spotify metadata "
            "changed or to redo analysis."
        ),
    )

    fix_art_parser = library_subparsers.add_parser(
        "fix-art",
        help=(
            "Re-embed cover art only (never text tags) for auto-matched "
            "tracks whose art is missing or doesn't match the real "
            "current album_art_url — a narrower, safer repair than "
            "'tag --force'."
        ),
    )
    fix_art_parser.set_defaults(handler=handle_library_fix_art)
    fix_art_parser.add_argument("playlist_name")

    fingerprint_parser = library_subparsers.add_parser(
        "fingerprint",
        help=(
            "Compute audio fingerprints for one library location's "
            "files, for later duplicate detection."
        ),
    )
    fingerprint_parser.set_defaults(handler=handle_library_fingerprint)
    fingerprint_parser.add_argument("location_name")
    fingerprint_parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute fingerprints even for files that already have one.",
    )
    fingerprint_parser.add_argument(
        "--folder",
        action="append",
        dest="folders",
        metavar="RELATIVE_PATH",
        help=(
            "Scope to one folder within this location (relative path, "
            "e.g. 'Trance'). Repeatable for multiple folders. Omit for "
            "the whole location."
        ),
    )

    duplicates_parser = library_subparsers.add_parser(
        "duplicates",
        help=(
            "Report duplicate/near-duplicate files within one library "
            "location (run 'fingerprint' on it first)."
        ),
    )
    duplicates_parser.set_defaults(handler=handle_library_duplicates)
    duplicates_parser.add_argument("location_name")
    duplicates_parser.add_argument(
        "--folder",
        action="append",
        dest="folders",
        metavar="RELATIVE_PATH",
        help=(
            "Scope to one folder within this location (relative path). "
            "Repeatable — multiple folders are pooled and compared "
            "together. Omit for the whole location."
        ),
    )

    rename_parser = library_subparsers.add_parser(
        "rename",
        help=(
            "Rename auto-matched local files to match their Spotify "
            "metadata ('Artist1, Artist2 - Title.ext'). Prints the plan "
            "and changes nothing unless --apply is given."
        ),
    )
    rename_parser.set_defaults(handler=handle_library_rename)
    rename_parser.add_argument("playlist_name")
    rename_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the renames, after a y/N confirmation.",
    )

    sharing_parser = subparsers.add_parser(
        "sharing",
        help="SoulSeek sharing status — what you're giving back.",
    )

    sharing_subparsers = sharing_parser.add_subparsers(
        dest="sharing_command",
        required=True,
    )

    sharing_status_parser = sharing_subparsers.add_parser(
        "status",
        help="Real-time slskd share status and per-location reconciliation.",
    )
    sharing_status_parser.set_defaults(handler=handle_sharing_status)

    return parser


def handle_playlists_list(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    _print_playlists(application.sync_service.list_playlists())


def handle_playlists_set_destination(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist = resolve_playlist_or_offer_sync(
        parsed.playlist_name, application
    )

    application.download_service.set_destination(
        playlist.name,
        parsed.location_name,
        parsed.subfolder,
    )


def _print_playlists(playlists: list[Playlist]) -> None:
    if not playlists:
        print("No Spotify playlists have been synchronized yet.")
        return

    for playlist in playlists:
        print(
            f"{playlist.name} "
            f"({playlist.track_count} tracks)"
        )


def _print_details(heading: str, details: list[dict[str, str]]) -> None:
    if not details:
        return

    print(f"\n{heading}")

    for detail in details:
        print(f"  [{detail['reason']}] {detail['message']}")


def _print_progress(stage: str, current: int, total: int) -> None:
    print(f"  {stage}: {current}/{total}", end="\r")


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

    # `skipped` alone folds together three different outcomes; named
    # separately so "skipped 12" never hides tracks waiting on Review.
    print(
        f"Requested {result.requested} download(s), "
        f"skipped {result.skipped} "
        f"({len(result.needs_review)} sent to review, "
        f"{len(result.already_in_progress)} already in progress, "
        f"{result.no_candidate} no candidate found), "
        f"failed {result.failed} "
        f"(of {result.total} unmatched tracks)."
    )
    if result.needs_review:
        print("  Run 'seeker review' to see the new candidates.")


def handle_search(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.download:
        _download_manual(application, parsed.artist, parsed.title)
        return

    files = application.download_service.search_manual(
        parsed.artist, parsed.title,
    )

    if not files:
        print(f"No results for '{parsed.artist} - {parsed.title}'.")
        return

    for file in rank_candidates(files):
        bitrate = f"{file.bit_rate}kbps" if file.bit_rate else "—"
        lock_note = " [locked]" if file.locked else ""
        print(
            f"  {printable(file.username)}: {printable(file.filename)} "
            f"({file.extension}, {bitrate}, "
            f"{format_file_size(file.size)}, "
            f"queue {file.queue_length}){lock_note}"
        )


def _download_manual(
        application: Application, artist: str, title: str,
) -> None:
    result = application.download_service.download_manual(artist, title)

    if not result.requested:
        print(f"No candidates found for '{artist} - {title}'.")
        return

    if result.settled:
        print(
            f"Requested from {printable(result.username or '')}: "
            f"{printable(result.filename or '')}"
        )
    else:
        print(
            "No practical candidate — requested a locked/upgrade-"
            "only candidate; check 'seeker downloads status' for "
            "progress."
        )


def handle_downloads_status(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    counts = application.download_service.poll_downloads()

    print(
        f"Queued: {counts.queued}, "
        f"Downloading: {counts.downloading}, "
        f"Completed: {counts.completed}, "
        f"Failed: {counts.failed}, "
        f"Ready for review: {counts.ready_for_review}, "
        f"Locked (retrying): {counts.locked}, "
        f"Shortlisted (pending): {counts.shortlisted}, "
        f"Superseded: {counts.superseded}, "
        f"Unavailable: {counts.unavailable}."
    )


def handle_downloads_review(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.all:
        _handle_downloads_review_all(application)
        return

    upgrades = application.review_service.get_pending_upgrade_reviews()

    if not upgrades:
        print("Nothing to review.")
        return

    for listed in upgrades:
        _confirm_upgrade(application, listed.request_id)


def _confirm_upgrade(application: Application, request_id: int) -> None:
    service = application.review_service
    # Resolved again at its own prompt: replacing an earlier row can
    # change which file is this row's current one.
    details = service.get_upgrade_review_details(request_id)

    if details is None:
        return

    answer = input(
        f"Higher quality version of {details.track.artist} - "
        f"{details.track.title} ready ({details.quality_descriptor} "
        f"vs current {details.current_description}). Replace? [y/n] "
    ).strip().lower()

    replace = answer == "y"
    delete_old = False

    if replace and details.old_file_path is not None:
        delete_answer = input(
            f"Delete old file at {details.old_file_path}? [y/n] "
        ).strip().lower()
        delete_old = delete_answer == "y"

    message = service.apply_upgrade_decision(request_id, replace, delete_old)

    if message is not None:
        print(f"  {message}")


def _handle_downloads_review_all(application: Application) -> None:
    # Roadmap item R3.1/R3.4 — CLI parity for the UI's "Replace all."
    # Same explicit-decision service method the UI uses
    # (apply_upgrade_decisions_batch), so the two never drift onto
    # different mutation logic.
    upgrades = application.review_service.get_pending_upgrade_reviews()

    if not upgrades:
        print("Nothing to review.")
        return

    print(f"{len(upgrades)} upgrade(s) ready to replace:")
    for details in upgrades:
        print(
            f"  {details.track.artist} - {details.track.title}: "
            f"{details.current_description} -> "
            f"{details.quality_descriptor or 'unknown'}"
        )

    confirmed = input(
        f"Replace all {len(upgrades)} upgrade(s)? [y/n] "
    ).strip().lower()

    if confirmed != "y":
        print("Cancelled.")
        return

    delete_old = input(
        "Also delete the old files? [y/n] "
    ).strip().lower() == "y"

    result = application.review_service.apply_upgrade_decisions_batch(
        [details.request_id for details in upgrades], delete_old,
    )

    print(f"Replaced: {result.replaced}, Failed: {result.failed}.")
    for detail in result.details:
        print(f"  {printable(detail)}")


def handle_sync(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    result = application.sync_service.refresh_playlists()

    print()
    print(f"Refreshed {result.playlist_count} playlists.")
    if result.updated_playlist_names:
        print(
            f"Updated tracks for {len(result.updated_playlist_names)} "
            f"that changed on Spotify: "
            f"{', '.join(result.updated_playlist_names)}"
        )
    if result.local_files_skipped:
        print(
            f"Skipped {result.local_files_skipped} Spotify local "
            f"file(s): Seeker can't match or download them automatically."
        )
    print()
    _print_playlists(application.sync_service.list_playlists())


def handle_sync_tracks(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist = resolve_playlist_or_offer_sync(
        parsed.playlist_name, application
    )

    result = application.sync_service.sync_playlist_tracks(playlist)

    print(f"Saved {result.tracks_saved} tracks for '{playlist.name}'.")
    if result.duplicates_collapsed:
        print(
            f"  {result.duplicates_collapsed} repeated listing(s) of the "
            f"same track stored once."
        )
    if result.local_files_skipped:
        print(
            f"  Skipped {result.local_files_skipped} Spotify local "
            f"file(s): they have no Spotify id, so Seeker can't match "
            f"or download them automatically."
        )


def handle_library_add(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    application.library_service.add_location(
        parsed.name,
        parsed.path,
    )


def handle_library_list(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    locations = application.library_service.list_locations()

    if not locations:
        print("No library locations registered.")
        return

    for location, is_reachable in locations:
        status = "reachable" if is_reachable else "unreachable"

        print(
            f"{location.name}: {location.path} ({status})"
        )


def handle_library_remove(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    summary = application.remove_location(parsed.name)
    print(f"Removed '{summary.location_name}'.")
    print(f"  Forgot {summary.files_forgotten:,} indexed files and "
          f"{summary.matches_cleared:,} matches "
          f"({summary.confirmed_matches_cleared:,} you confirmed).")

    if summary.playlists_affected:
        print(f"  {summary.playlists_affected:,} playlists downloaded "
              "here and need a new destination "
              "('seeker playlists set-destination').")

    if summary.was_default:
        print("  It was the default download location, now unset.")

    print("  Files on disk were not touched.")


def handle_library_scan(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.match:
        application.library_service.scan_and_match()
    else:
        application.library_service.scan_all()


def handle_library_match(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    application.track_matcher.match_all()


def handle_library_tag(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
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
        force=parsed.force,
    )

    print(
        f"Tagged: {result.tagged} "
        f"({result.tagged_without_art} without cover art), "
        f"Skipped (no match): {result.skipped_no_match}, "
        f"Skipped (unsupported format): "
        f"{result.skipped_format_unsupported}, "
        f"Skipped (already tagged): "
        f"{result.skipped_already_tagged}, "
        f"Skipped (already analyzed): "
        f"{result.skipped_already_analyzed}, "
        f"Failed: {result.failed}."
    )

    _print_details(
        "Details (skipped, failed, or tagged without art):",
        result.details,
    )


def handle_library_fix_art(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist = resolve_playlist_or_offer_sync(
        parsed.playlist_name, application
    )

    result = application.metadata_service.fix_missing_art_for_playlist(
        playlist.name
    )

    print(
        f"Fixed: {result.fixed}, "
        f"Already correct: {result.already_correct}, "
        f"No art URL: {result.no_url}, "
        f"Download failed: {result.download_failed}, "
        f"Embed failed: {result.embed_failed}, "
        f"Unsupported format: {result.format_unsupported}, "
        f"Skipped (no match): {result.skipped_no_match}, "
        f"Failed: {result.failed}."
    )

    _print_details("Details:", result.details)


def handle_library_rename(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist = resolve_playlist_or_offer_sync(
        parsed.playlist_name, application
    )

    plans = application.metadata_service.plan_renames(
        playlist_name=playlist.name
    )
    to_rename = _print_rename_plan(playlist.name, plans)

    if not parsed.apply:
        print("\nDry run only — pass --apply to actually rename.")
        return

    if not to_rename:
        print("\nNothing to rename.")
        return

    answer = input(
        f"\nRename {to_rename} file(s) on disk? "
        f"[y/N] "
    ).strip().lower()

    if answer != "y":
        print("Cancelled — nothing renamed.")
        return

    result = application.metadata_service.apply_renames(plans)

    print(
        f"\nRenamed: {result.renamed} "
        f"({result.collisions} with a collision), "
        f"Already correct: {result.already_correct}, "
        f"Not auto-matched: {result.skipped_not_auto_matched}, "
        f"No local file: {result.skipped_no_local_file}, "
        f"Failed: {result.failed}."
    )

    _print_details("Details:", result.details)


def _print_rename_plan(playlist_name: str, plans: list[RenamePlan]) -> int:
    """Print the plan and its tally; return how many files it renames."""
    renames = [plan for plan in plans if plan.action == "rename"]
    collisions = [plan for plan in plans if plan.action == "collision"]
    actions = Counter(plan.action for plan in plans)

    print(f"Rename plan for '{playlist_name}':\n")

    for plan in [*renames, *collisions]:
        # Loaded by plan_renames — only 'not_auto_matched'/
        # 'no_local_file'/'error' plans ever have a None path, and
        # renames/collisions are filtered to exclude those.
        assert plan.current_relative is not None
        assert plan.proposed_relative is not None
        note = " (needs a numbered suffix)" if plan.action == "collision" else ""
        print(f"  {plan.current_relative} -> {plan.proposed_relative}{note}")
        if plan.destination_note:
            print(f"    warning: {plan.destination_note}")

    print(
        f"\n{len(renames) + len(collisions)} to rename "
        f"({len(collisions)} with a collision), "
        f"{actions['already_correct']} already correct, "
        f"{actions['not_auto_matched']} not auto-matched, "
        f"{actions['no_local_file'] + actions['error']} no local file."
    )

    return len(renames) + len(collisions)


def handle_library_fingerprint(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    result = application.duplicate_service.compute_fingerprints(
        parsed.location_name, force=parsed.force,
        folders=parsed.folders, progress=_print_progress,
    )
    print()

    print(
        f"Fingerprinted: {result.computed}, "
        f"Skipped (already computed): "
        f"{result.skipped_already_computed}, "
        f"Failed: {result.failed}."
    )

    _print_details("Failed:", result.details)


def handle_library_duplicates(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    # The Duplicates page's milestone, and like it hidden at zero: an
    # empty milestone is worse than none.
    files_deleted, bytes_freed = (
        application.duplicate_service.get_cleanup_totals()
    )
    if files_deleted > 0 or bytes_freed > 0:
        print(
            f"You've reclaimed {format_file_size(bytes_freed)} "
            f"across {files_deleted} "
            f"file{'s' if files_deleted != 1 else ''}.\n"
        )

    groups = application.duplicate_service.find_duplicate_groups(
        parsed.location_name, folders=parsed.folders,
        progress=_print_progress,
    )
    print()

    if not groups:
        print(
            "No duplicates found. (Run 'library fingerprint "
            f"{parsed.location_name}' first if you haven't yet.)"
        )
        return

    print(f"Found {len(groups)} duplicate group(s):\n")

    for group in groups:
        print(f"Similarity: {group.similarity:.1%}")

        for duplicate_file in group.files:
            local_file = duplicate_file.local_file
            quality = duplicate_file.quality
            bitrate = (
                f"{quality.bitrate_kbps}kbps"
                if quality.bitrate_kbps
                else "unknown bitrate"
            )
            print(
                f"  - {local_file.relative_path} "
                f"({local_file.format}, {bitrate})"
            )

        print()


def handle_check(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    playlist_id = None

    if parsed.playlist_name:
        playlist = resolve_playlist_or_offer_sync(
            parsed.playlist_name, application
        )
        playlist_id = playlist.id
        print(f"For playlist '{playlist.name}':")
    else:
        # The scope is otherwise ambiguous — every count below is a
        # global total across every synced playlist combined, not just
        # "whichever playlist I was just looking at." Confirmed live as
        # a real, easy-to-misread gap (see CLAUDE.md).
        print("Across all synced playlists:")

    report = application.track_matcher.generate_match_report(playlist_id)

    print(f"Auto-matched: {report['auto_count']}")

    if parsed.verbose:
        for artist, title, score, filename in report["auto_matched"]:
            print(
                f"  {artist} - {title} (score: {score:.1f}) -> "
                f"{printable(filename)}"
            )

    needs_review = report["needs_review"]
    print(f"\nNeeds review ({len(needs_review)}):")

    for artist, title, score in needs_review:
        print(f"  {artist} - {title} (score: {score:.1f})")

    # Distinct from the local-matcher needs_review tier above — these are
    # tracks with NO local file match at all, but a real, plausible
    # SoulSeek candidate (70-89) found by a previous `seeker download`
    # run. Requires slskd to be configured at all (see config.py); `check`
    # must keep working without it, so this section is simply omitted
    # rather than erroring when it isn't set up.
    if application.soulseek_configured:
        soulseek_review = application.review_service.get_review_candidates(
            playlist_id
        )
        print(
            f"\nNeeds review (SoulSeek candidate found) "
            f"({len(soulseek_review)}):"
        )

        for track, candidate in soulseek_review:
            print(
                f"  {track.artist} - {track.title} "
                f"(score: {candidate.score:.1f}) -> "
                f"{printable(candidate.username)}: "
                f"{printable(candidate.filename)}"
            )

    unmatched = report["unmatched"]
    print(f"\nUnmatched, needs a SoulSeek download ({len(unmatched)}):")

    for artist, title in unmatched:
        print(f"  {artist} - {title}")


def handle_review(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.confirm:
        application.library_service.confirm_match(parsed.confirm)
        print(f"Confirmed match for track {parsed.confirm}.")
        return

    if parsed.reject:
        application.library_service.reject_match(parsed.reject)
        print(f"Rejected match for track {parsed.reject}.")
        return

    playlist_name = None

    if parsed.playlist_name:
        playlist = resolve_playlist_or_offer_sync(
            parsed.playlist_name, application
        )
        playlist_name = playlist.name
        print(f"Needs-review local-file matches for '{playlist.name}':")
    else:
        print("Needs-review local-file matches across all synced playlists:")

    matches = application.library_service.get_needs_review_matches(
        playlist_name
    )

    if not matches:
        print("  None.")
        return

    for match in matches:
        print(
            f"  [{match.track_id}] {match.track_artist} - "
            f"{match.track_title} (score: {match.score:.1f})"
        )
        print(
            f"      -> {match.location_name}: "
            f"{printable(match.local_file_path)} "
            f"(tag: {match.tag_artist!r} - {match.tag_title!r})"
        )


def handle_history(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    limit = parsed.limit if parsed.limit is not None else DEFAULT_HISTORY_LIMIT
    events = application.history_service.get_recent_events(limit=limit)

    if not events:
        print("No downloaded or tagged tracks yet.")
        return

    for event in events:
        when = format_timestamp(event.occurred_at)
        what = "Downloaded" if event.event_type == "downloaded" else "Tagged"
        print(
            f"{when}  {what:<10}  {event.track_artist} - "
            f"{event.track_title} ({event.playlist_name})  "
            f"{event.detail}"
        )


def handle_sharing_status(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if not application.soulseek_configured:
        print("SoulSeek isn't configured yet — set it up in Settings first.")
        return

    service = application.sharing_service
    status = service.get_status()

    print(
        f"Shares ready: {status.ready}, scanning: {status.scanning}, "
        f"{status.directories} directories, {status.files} files."
    )

    if service.is_self_managed():
        print("slskd is managed by Seeker's own docker-compose.yml.")
    else:
        print(
            "slskd is NOT managed by Seeker — sharing a new location "
            "requires editing its config yourself."
        )

    print()
    print("Library locations:")

    for state in service.get_reconciliation(status):
        if state.shared and state.share is not None:
            print(
                f"  {state.location.name}: shared as "
                f"{state.share.local_path} "
                f"({state.share.directories} dirs, {state.share.files} files)"
            )
        else:
            print(f"  {state.location.name}: not shared")


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse a command line, exiting on `--help`, a usage error or no
    command at all; none of those needs an `Application`."""
    parser = build_parser()
    parsed = parser.parse_args(args)

    if parsed.handler is None:
        parser.print_help()
        parser.exit()

    return parsed


def run(
    application: Application,
    args: list[str] | None = None,
) -> None:
    dispatch(application, parse_args(args))


def dispatch(
    application: Application,
    parsed: argparse.Namespace,
) -> None:
    try:
        parsed.handler(application, parsed)
    except NoDestinationConfiguredError as error:
        # The message is shared with the UI, which must never tell the
        # user to run a shell command, so the CLI adds its own guidance.
        # A manual search has no playlist to set a destination for; it
        # needs the app-wide default, which only Settings can set.
        if parsed.command == "search":
            print(f"{error} Set a default download location in Settings first.")
        else:
            print(f"{error} Run 'seeker playlists set-destination' first.")
        sys.exit(1)
    except (
            SeekerError,
            httpx.TransportError,
            sqlite3.OperationalError,
    ) as error:
        print(printable(_describe_for_cli(error)))
        sys.exit(1)


def _describe_for_cli(error: Exception) -> str:
    # The CLI has no log folder to point at, so where the UI says
    # "details are in the log" the terminal gets the details themselves.
    details = str(error).strip()

    return describe_error(
        error, details_hint=f"Details: {details}" if details else "",
    )

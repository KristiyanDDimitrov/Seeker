import argparse
import sys

from seeker.application import Application
from seeker.audio_fingerprint import FingerprintingUnavailableError
from seeker.history_service import DEFAULT_LIMIT as DEFAULT_HISTORY_LIMIT
from seeker.library.duplicate_service import (
    LibraryLocationNotFoundError as DuplicateLibraryLocationNotFoundError,
)
from seeker.library.metadata_service import (
    PlaylistNotFoundError as MetadataPlaylistNotFoundError,
)
from seeker.library.scanner import LibraryUnavailableError
from seeker.library.service import (
    PlaylistNotFoundError as LibraryReviewPlaylistNotFoundError,
)
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
# Pure-function formatter, no Qt/PySide6 dependency (see its own
# docstring) — CLI and UI share the exact same local-time conversion
# rather than the CLI growing a second copy.
from seeker.ui.formatting import format_file_size, format_timestamp


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
        help="Reject a needs-review match (no blacklist — it can "
             "resurface on a later match run).",
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

    history_parser = subparsers.add_parser(
        "history",
        help=(
            "Recently downloaded and tagged tracks, derived from "
            "existing data — not a permanent log (see --help)."
        ),
    )
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

    scan_parser = library_subparsers.add_parser(
        "scan",
        help="Scan all registered library locations.",
    )
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
    fix_art_parser.add_argument("playlist_name")

    fingerprint_parser = library_subparsers.add_parser(
        "fingerprint",
        help=(
            "Compute audio fingerprints for one library location's "
            "files, for later duplicate detection."
        ),
    )
    fingerprint_parser.add_argument("location_name")
    fingerprint_parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute fingerprints even for files that already have one.",
    )

    duplicates_parser = library_subparsers.add_parser(
        "duplicates",
        help=(
            "Report duplicate/near-duplicate files within one library "
            "location (run 'fingerprint' on it first)."
        ),
    )
    duplicates_parser.add_argument("location_name")

    rename_parser = library_subparsers.add_parser(
        "rename",
        help=(
            "Rename auto-matched local files to match their Spotify "
            "metadata ('Artist1, Artist2 - Title.ext'). Prints the plan "
            "and changes nothing unless --apply is given."
        ),
    )
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
    )

    sharing_subparsers.add_parser(
        "status",
        help="Real-time slskd share status and per-location reconciliation.",
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

    # Roadmap item 66 (Phase 4.2) — `skipped` alone folds together three
    # genuinely different outcomes (already in progress, sent to Review,
    # no candidate at all); named separately here so "skipped 12" never
    # silently means "12 of those actually need your attention on the
    # Review page." `skipped` itself stays the combined total, never
    # subtracted from `total` — see download_service.py's own comment
    # on why that shape of arithmetic is exactly what produced this bug.
    needs_review = result.get("needs_review", [])
    already_in_progress = result.get("already_in_progress", [])
    no_candidate_count = (
        result["skipped"] - len(already_in_progress) - len(needs_review)
    )

    print(
        f"Requested {result['requested']} download(s), "
        f"skipped {result['skipped']} "
        f"({len(needs_review)} sent to review, "
        f"{len(already_in_progress)} already in progress, "
        f"{no_candidate_count} no candidate found), "
        f"failed {result['failed']} "
        f"(of {result['total']} unmatched tracks)."
    )
    if needs_review:
        print("  Run 'seeker review' to see the new candidates.")

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
            f"Superseded: {counts['superseded']}, "
            f"Unavailable: {counts['unavailable']}."
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
        if parsed.match:
            application.library_service.scan_and_match()
        else:
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
            force=parsed.force,
        )

        print(
            f"Tagged: {result['tagged']} "
            f"({result['tagged_without_art']} without cover art), "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Skipped (unsupported format): "
            f"{result['skipped_format_unsupported']}, "
            f"Skipped (already tagged): "
            f"{result['skipped_already_tagged']}, "
            f"Skipped (already analyzed): "
            f"{result['skipped_already_analyzed']}, "
            f"Failed: {result['failed']}."
        )

        if result["details"]:
            print("\nDetails (skipped, failed, or tagged without art):")

            for detail in result["details"]:
                print(f"  [{detail['reason']}] {detail['message']}")

    elif parsed.library_command == "fix-art":
        playlist = resolve_playlist_or_offer_sync(
            parsed.playlist_name, application
        )

        result = application.metadata_service.fix_missing_art_for_playlist(
            playlist.name
        )

        print(
            f"Fixed: {result['fixed']}, "
            f"Already correct: {result['already_correct']}, "
            f"No art URL: {result['no_url']}, "
            f"Download failed: {result['download_failed']}, "
            f"Embed failed: {result['embed_failed']}, "
            f"Unsupported format: {result['format_unsupported']}, "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Failed: {result['failed']}."
        )

        if result["details"]:
            print("\nDetails:")

            for detail in result["details"]:
                print(f"  [{detail['reason']}] {detail['message']}")

    elif parsed.library_command == "rename":
        playlist = resolve_playlist_or_offer_sync(
            parsed.playlist_name, application
        )

        plans = application.metadata_service.plan_renames(
            playlist_name=playlist.name
        )

        renames = [plan for plan in plans if plan.action == "rename"]
        collisions = [plan for plan in plans if plan.action == "collision"]
        already_correct = sum(
            1 for plan in plans if plan.action == "already_correct"
        )
        not_auto_matched = sum(
            1 for plan in plans if plan.action == "not_auto_matched"
        )
        no_local_file = sum(
            1 for plan in plans if plan.action in ("no_local_file", "error")
        )

        print(f"Rename plan for '{playlist.name}':\n")

        for plan in [*renames, *collisions]:
            # Loaded by plan_renames — only 'not_auto_matched'/
            # 'no_local_file'/'error' plans ever have a None path, and
            # renames/collisions are filtered to exclude those.
            assert plan.current_path is not None
            assert plan.proposed_path is not None
            note = " (needs a numbered suffix)" if plan.action == "collision" else ""
            print(f"  {plan.current_path.name} -> {plan.proposed_path.name}{note}")

        print(
            f"\n{len(renames) + len(collisions)} to rename "
            f"({len(collisions)} with a collision), "
            f"{already_correct} already correct, "
            f"{not_auto_matched} not auto-matched, "
            f"{no_local_file} no local file."
        )

        if not parsed.apply:
            print("\nDry run only — pass --apply to actually rename.")
            return

        if not renames and not collisions:
            print("\nNothing to rename.")
            return

        answer = input(
            f"\nRename {len(renames) + len(collisions)} file(s) on disk? "
            f"[y/N] "
        ).strip().lower()

        if answer != "y":
            print("Cancelled — nothing renamed.")
            return

        rename_result = application.metadata_service.apply_renames(plans)

        print(
            f"\nRenamed: {rename_result.renamed} "
            f"({rename_result.collisions} with a collision), "
            f"Already correct: {rename_result.already_correct}, "
            f"Not auto-matched: {rename_result.skipped_not_auto_matched}, "
            f"No local file: {rename_result.skipped_no_local_file}, "
            f"Failed: {rename_result.failed}."
        )

        if rename_result.details:
            print("\nDetails:")

            for detail in rename_result.details:
                print(f"  [{detail['reason']}] {detail['message']}")

    elif parsed.library_command == "fingerprint":
        result = application.duplicate_service.compute_fingerprints(
            parsed.location_name, force=parsed.force,
        )

        print(
            f"Fingerprinted: {result['computed']}, "
            f"Skipped (already computed): "
            f"{result['skipped_already_computed']}, "
            f"Failed: {result['failed']}."
        )

        if result["details"]:
            print("\nFailed:")

            for detail in result["details"]:
                print(f"  [{detail['reason']}] {detail['message']}")

    elif parsed.library_command == "duplicates":
        # Roadmap item 56 Phase 6.4 — CLI parity with the Duplicates
        # page's own milestone; hidden entirely at zero, same "an empty
        # milestone is worse than no milestone" rule.
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
            parsed.location_name,
        )

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

    else:
        print(
            "Usage: seeker library "
            "{add,list,remove,scan,match,tag,fingerprint,duplicates} ..."
        )

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
            print(f"  {artist} - {title} (score: {score:.1f}) -> {filename}")

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
        soulseek_review = application.download_service.get_review_candidates(
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
                f"{candidate.username}: {candidate.filename}"
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
            f"      -> {match.location_name}: {match.local_file_path} "
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


def handle_sharing(
        application: Application,
        parsed: argparse.Namespace,
) -> None:
    if parsed.sharing_command != "status":
        print("Usage: seeker sharing status")
        return

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

    for state in service.get_reconciliation():
        if state.shared and state.share is not None:
            print(
                f"  {state.location.name}: shared as "
                f"{state.share.local_path} "
                f"({state.share.directories} dirs, {state.share.files} files)"
            )
        else:
            print(f"  {state.location.name}: not shared")


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

        elif parsed.command == "review":
            handle_review(application, parsed)

        elif parsed.command == "download":
            handle_download(application, parsed)

        elif parsed.command == "downloads":
            handle_downloads(application, parsed)

        elif parsed.command == "history":
            handle_history(application, parsed)

        elif parsed.command == "sharing":
            handle_sharing(application, parsed)
    except SpotifyRateLimitedError as error:
        print(str(error))
        sys.exit(1)
    except LibraryUnavailableError as error:
        print(str(error))
        sys.exit(1)
    except NoDestinationConfiguredError as error:
        # The exception's own message is deliberately interface-neutral
        # (shared with the UI, which must never be told to run a shell
        # command — roadmap item 6 §2) — the CLI appends its own
        # command-line guidance here instead of baking it into the
        # shared message.
        print(f"{error} Run 'seeker playlists set-destination' first.")
        sys.exit(1)
    except (
            PlaylistNotFoundError,
            SyncPlaylistNotFoundError,
            MetadataPlaylistNotFoundError,
            LibraryReviewPlaylistNotFoundError,
            LibraryLocationNotFoundError,
            SoulseekDownloadError,
            DuplicateLibraryLocationNotFoundError,
            FingerprintingUnavailableError,
    ) as error:
        print(str(error))
        sys.exit(1)

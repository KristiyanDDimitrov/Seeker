"""Centralized UI copy — tooltips, tab subtitles, and About/Help text.

Presentation-only (Task 1: contextual help), no service-layer changes.
Everything user-facing that isn't a live data value belongs here as a
named constant, not an inline string in a widget file — the same
"shared thing lives in exactly one place" discipline this project
already applies to logic (matching.py's consolidation, download_dedup.py)
applied to copy instead. This matters concretely for
`library_location_picker.py`'s folder-picker flow, which is shared
between the onboarding wizard and Settings: without this module, its
copy would need to live in two call sites and could drift the way
matching.py's two independent copies once did (see CLAUDE.md).
"""

from typing import Any

# --- Persistent tab/section subtitles (not hover-dependent) --------------
# One line under each tab's own header, aimed at someone who never reads
# the README and goes straight into the app.

DASHBOARD_TAB_SUBTITLE = (
    "Pick a playlist on the left to see each track's status, then tag "
    "or download what's missing."
)
SEARCH_TAB_SUBTITLE = (
    "Find and download a track that isn't in any Spotify playlist — "
    "the same best-quality-with-fallback search SoulSeek downloads "
    "already use."
)
DOWNLOADS_TAB_SUBTITLE = (
    "Every SoulSeek transfer currently in progress, across all "
    "playlists — updates automatically. A finished transfer stays "
    "visible here for about a minute, then moves to the History page."
)
REVIEW_TAB_SUBTITLE = (
    "Confirm or reject SoulSeek matches that weren't clean enough to "
    "auto-accept, and approve quality upgrades once they're downloaded."
)
DUPLICATES_TAB_SUBTITLE = (
    "Find duplicate or near-duplicate files within one library "
    "location, by audio content — not just matching filenames. Pick "
    "which copy to keep, then confirm deleting the rest — nothing is "
    "removed until you explicitly check the box and click Delete."
)
SETTINGS_WINDOW_SUBTITLE = (
    "Library locations, playlist destinations, Spotify/SoulSeek "
    "connections, and match-classification thresholds."
)
HISTORY_PAGE_SUBTITLE = (
    "Recently downloaded and tagged tracks, in one place. Derived from "
    "current data, not a permanent log — an event disappears if its "
    "underlying file or match is later removed, and download failures "
    "aren't shown here (see the Downloads page for those)."
)
HELP_PAGE_SUBTITLE = (
    "How Seeker works, troubleshooting, and where your data lives."
)
SHARING_TAB_SUBTITLE = (
    "What your slskd is sharing back to the SoulSeek network, and who's "
    "currently downloading from you."
)

HELP_WALKTHROUGH_BODY = (
    "<h3>How Seeker works</h3>"
    "<p><b>1. Sync</b> — Spotify playlists and their tracks are pulled "
    "via the Web API and cached locally, so day-to-day use doesn't "
    "keep re-hitting Spotify's rate-limited API.</p>"
    "<p><b>2. Scan</b> — registered library locations (folders on disk, "
    "Settings → Locations) are scanned for audio files.</p>"
    "<p><b>3. Match</b> — each cached track is fuzzy-matched against "
    "scanned files and classified in library or missing, shown per-"
    "playlist on the Dashboard.</p>"
    "<p><b>4. Search + download</b> — missing tracks are searched on "
    "SoulSeek and the best candidate is downloaded via slskd; progress "
    "shows on the Downloads page.</p>"
    "<p><b>5. Review + tag</b> — uncertain SoulSeek matches and quality "
    "upgrades wait on the Review page for a decision; matched tracks "
    "can be tagged with Spotify's canonical metadata from the "
    "Dashboard.</p>"
)

HELP_TROUBLESHOOTING_BODY = (
    "<h3>Troubleshooting</h3>"
    "<p><b>Spotify won't connect</b> — check the Client ID in Settings "
    "→ Connection, and that your browser didn't block the "
    "authorization popup.</p>"
    "<p><b>SoulSeek/Docker won't start</b> — confirm Docker Desktop is "
    "actually running, and that the SoulSeek username/password in "
    "Settings are correct (a wrong password and a duplicate-login "
    "\"kicked\" state look different in the wizard's own error text).</p>"
    "<p><b>Tracks stuck as missing</b> — has this playlist's tracks "
    "been loaded (Refresh playlists), and has your library actually "
    "been scanned and re-matched? The Dashboard's own \"next step\" "
    "banner usually names the exact missing step.</p>"
    "<p><b>A download looks stuck</b> — check the Downloads page; a "
    "queued transfer waiting on a peer looks different from one "
    "actively transferring, and SoulSeek queue wait times aren't "
    "predictable.</p>"
)

HELP_DATA_LOCATIONS_HEADING = "<h3>Where your data lives</h3>"
HELP_DATA_LOCATIONS_INTRO = (
    "Seeker keeps everything — its database, config, cached Spotify "
    "token, and SoulSeek data — in one folder on this machine. Nothing "
    "is uploaded anywhere else."
)
# Roadmap item 81 (0.2) — a real prior-round report ("fix didn't work
# on the other account") turned out to be two entirely separate
# databases, not a regression — said here explicitly so the next one
# doesn't cost a whole test round again.
HELP_DATA_LOCATIONS_PER_ACCOUNT_NOTE = (
    "This folder is per macOS user account — a different login has "
    "its own separate database, library locations, scan state, and "
    "SoulSeek data, with nothing shared between accounts. If something "
    "looks different on another account, check first whether that "
    "account has actually been set up the same way (synced, scanned, "
    "matched) — it's very often a different-database report, not a "
    "different-behavior one."
)
DATA_LOCATION_DATABASE_LABEL = "Database:"
DATA_LOCATION_CONFIG_LABEL = "Config:"
DATA_LOCATION_SPOTIFY_TOKEN_LABEL = "Spotify token:"
DATA_LOCATION_SLSKD_LABEL = "SoulSeek data:"
OPEN_DATA_FOLDER_BUTTON_TEXT = "Open Data Folder"
TOOLTIP_OPEN_DATA_FOLDER = (
    "Open the folder above in Finder/Explorer/your file manager."
)
HELP_BUILD_IDENTITY_LABEL = "Build:"


def format_build_identity(
        git_sha: str, git_describe: str, built_at: str,
) -> str:
    """Roadmap item 81 (0.1) — makes "is this account running the
    build I think it is?" a two-second visual check. `git_sha ==
    "dev"` means an unmodified `seeker/_build_info.py` — i.e. this is
    a real `uv run` dev session, not a packaged build at all.
    """
    if git_sha == "dev":
        return "dev (running from source, not a packaged build)"
    return f"{git_describe} — built {built_at}"

# --- MainWindow toolbar ---------------------------------------------------

TOOLTIP_SYNC_ALL_PLAYLISTS = (
    "Pull your Spotify playlists' names and track counts into the local "
    "cache (metadata only — no tracks yet)."
)
TOOLTIP_SCAN_ALL_LOCATIONS = (
    "Re-scan every registered library location on disk for audio files, "
    "then automatically re-match cached Spotify tracks against what was "
    "found. Supported formats: MP3, FLAC, WAV, M4A, AAC, OGG, AIFF/AIF/"
    "AIFC — AIFF support is new (roadmap item R1); files already on "
    "disk before this update need one real re-scan to be picked up."
)
TOOLTIP_MATCH_ALL_TRACKS = (
    "Fuzzy-match every cached Spotify track against your already-scanned "
    "local files, without re-scanning the disk first — e.g. after "
    "changing the match thresholds in Settings."
)
TOOLTIP_DOWNLOAD_SELECTED_PLAYLIST = (
    "Search SoulSeek and request downloads for the selected playlist's "
    "still-unmatched tracks."
)


def format_download_result_message(result: dict[str, Any]) -> str:
    """Roadmap item 66 (Phase 4.2) — the real fix for "Requested 16,
    skipped 12 (no candidates found)" when several of those 12 had in
    fact become real Review candidates: names each outcome separately
    rather than folding them into one generic "skipped" figure.
    `skipped` itself stays the combined total of all three (backward-
    compatible with anything else summing it) — never subtracted from
    `total` here, which is exactly the shape of bug that produced the
    original symptom.
    """
    requested = result["requested"]
    skipped = result["skipped"]
    already_in_progress = result.get("already_in_progress", [])
    needs_review = result.get("needs_review", [])
    no_candidate_count = skipped - len(already_in_progress) - len(needs_review)

    message = f"Requested {requested} download{'s' if requested != 1 else ''}"

    parts: list[str] = []
    if needs_review:
        parts.append(f"{len(needs_review)} sent to Review")
    if already_in_progress:
        parts.append(
            f"{len(already_in_progress)} already downloading/downloaded"
        )
    if no_candidate_count > 0:
        parts.append(f"{no_candidate_count} no candidate found")

    if parts:
        message += " — " + ", ".join(parts)

    message += ". See the Downloads page for progress."

    if needs_review:
        message += " Check the Review page for new candidates."

    return message

# --- Destination dialog (roadmap item 6 §3 — "no dead end") ---------------

DESTINATION_DIALOG_TITLE = "Set a Download Destination"
DESTINATION_DIALOG_INTRO = (
    "'{playlist}' doesn't have a download destination yet. Choose "
    "where its downloads should go, then Seeker will continue."
)
TOOLTIP_REMEMBER_DESTINATION_CHECKBOX = (
    "Checked: use this destination for '{playlist}' every time. "
    "Unchecked: make this the default for every playlist that doesn't "
    "have its own destination."
)
NO_LOCATIONS_FOR_DESTINATION_DIALOG = (
    "Add a library location in Settings before downloading."
)


def format_destination_preview(
        path: str, exists: bool, audio_file_count: int | None,
) -> str:
    """Roadmap item 65 (Phase 3.2) — the live "where will this actually
    go" preview inside DestinationDialog. `audio_file_count` is None
    when the folder exists but couldn't be read (permissions, ...) —
    shown without a count rather than a misleading zero."""
    if not exists:
        return f"Will download to: {path}  (new folder)"

    if audio_file_count is None:
        return f"Will download to: {path}"

    plural = "s" if audio_file_count != 1 else ""
    return (
        f"Will download to: {path}  (already exists, "
        f"{audio_file_count} audio file{plural} there now)"
    )
TOOLTIP_OPEN_SETTINGS = (
    "Library locations, playlist destinations, connections, and "
    "match thresholds."
)
TOOLTIP_SETTINGS_BACK = "Return to the page you were on before Settings."
TOOLTIP_SETTINGS_ABOUT = "About Seeker — version, license, support links."
TOOLTIP_SYNC_TRACKS = (
    "Pull this playlist's full track list from Spotify — never done "
    "automatically, to keep API calls intentional."
)

# --- Dashboard: tagging controls ------------------------------------------

TOOLTIP_ANALYZE_AUDIO_CHECKBOX = (
    "Also detect BPM and musical key locally and write them to the "
    "file's tags."
)
TOOLTIP_BPM_MIN = (
        "Lower bound for correcting octave errors (e.g. 128 detected as 64)."
)
TOOLTIP_BPM_MAX = (
        "Upper bound for correcting octave errors (e.g. 64 detected as 128)."
)
TOOLTIP_TAG_SELECTED = (
    "Write Spotify's artist/title/album/art onto the selected tracks' "
    "matched local files."
)
TOOLTIP_TAG_PLAYLIST = (
    "Write Spotify's artist/title/album/art onto every auto-matched "
    "track in this playlist."
)
TOOLTIP_TAG_TRACK_ROW = (
    "Write Spotify's canonical metadata onto this track's matched local "
    "file."
)
TOOLTIP_FORCE_RETAG_CHECKBOX = (
    "Redo the text/art tag write and analysis even for files already "
    "tagged — e.g. after Spotify's metadata changed."
)
TOOLTIP_FIX_MISSING_ART = (
    "Re-embed cover art only (never text tags) for this playlist's "
    "auto-matched tracks whose art is missing or doesn't match the "
    "real current Spotify art — a narrower, safer repair than "
    "re-tagging everything."
)
TOOLTIP_FILL_MISSING_ART_URLS = (
    "Re-fetch this playlist's tracks from Spotify (a real API call) to "
    "populate any missing album art URLs — needed before \"Fix missing "
    "cover art\" can do anything for a track synced before art URLs "
    "were captured."
)

# --- Rename preview dialog (roadmap item 67, Phase 6.4) --------------------

TOOLTIP_RENAME_FILES = (
    "Preview renaming this playlist's auto-matched files to match their "
    "Spotify metadata ('Artist1, Artist2 - Title.ext'). Nothing is "
    "renamed until you review the plan and confirm."
)
RENAME_PREVIEW_DIALOG_TITLE = "Rename Files to Match Metadata"
RENAME_PREVIEW_DIALOG_INTRO = (
    "Renames auto-matched files on disk to match their Spotify "
    "metadata. Nothing happens until you click Rename below."
)
RENAME_PREVIEW_NO_CHANGES = "Nothing to rename — every file already matches."
RENAME_PREVIEW_SECTION_RENAME = "Will rename:"
RENAME_PREVIEW_SECTION_COLLISION = "Will rename (needs a numbered suffix):"
RENAME_PREVIEW_SECTION_ALREADY_CORRECT = "Already correct:"
RENAME_PREVIEW_SECTION_NOT_AUTO_MATCHED = "Not auto-matched (skipped):"
RENAME_PREVIEW_SECTION_REFUSED = "Refused (no local file / error):"


def format_rename_result_message(counts: dict[str, int]) -> tuple[str, str]:
    """Roadmap item 67 (Phase 6.4) — mirrors format_fix_art_result_
    message's own shape. `counts` mirrors RenameResult's own fields.

    Roadmap item 76 (P2, 2.5) — `collisions` (as of the 2.3 fix in
    apply_renames) now literally means "the real written name differed
    from what the preview showed," not just "the plan predicted a
    suffix" — so naming it prominently here, not just in the
    easy-to-miss capped results panel, is exactly the honest reporting
    this item asks for.
    """
    renamed = counts["renamed"]
    collisions = counts["collisions"]
    failed = counts["failed"]

    message = f"Renamed {renamed} file{'s' if renamed != 1 else ''}"

    if collisions:
        plural = "s" if collisions != 1 else ""
        message += (
            f" — {collisions} file{plural} written with a DIFFERENT "
            f"name than the preview showed (see the results panel "
            f"below for exactly which)"
        )

    if failed:
        message += f", {failed} failed — see the results panel below."
        return message, "error"

    if renamed:
        return (
            message + ".", "warning" if collisions else "success",
        )

    return "Nothing was renamed.", "info"


def format_fix_art_result_message(result: dict[str, Any]) -> tuple[str, str]:
    """Roadmap item 66 (Phase 5.2) — mirrors format_tag_result_notice's
    own shape for the narrower "Fix missing cover art" action."""
    fixed = result["fixed"]
    # Roadmap item 75 (P6, 6.4) — art WAS embedded here, so this is
    # deliberately NOT folded into `failed` below.
    fixed_wav = result.get("fixed_wav_rarely_supported", 0)
    already_correct = result["already_correct"]
    no_url = result["no_url"]
    failed = (
        result["download_failed"] + result["embed_failed"]
        + result["format_unsupported"] + result["failed"]
    )

    message = f"Fixed art for {fixed} track{'s' if fixed != 1 else ''}"

    parts = []
    if fixed_wav:
        parts.append(
            f"{fixed_wav} fixed but rarely visible (WAV)"
        )
    if already_correct:
        parts.append(f"{already_correct} already correct")
    if no_url:
        parts.append(f"{no_url} missing an art URL")
    if failed:
        parts.append(f"{failed} failed")

    if parts:
        message += " — " + ", ".join(parts)

    message += "."

    if failed:
        return message + " See the results panel below for details.", "error"
    if no_url:
        return (
            message + " Re-run \"sync-tracks\" to populate missing art URLs.",
            "warning",
        )
    if fixed_wav:
        return (
            message + " WAV cover art is rarely read by real DJ "
            "software — don't rely on it being visible.",
            "warning",
        )
    if fixed:
        return message, "success"

    return message, "info"


def format_tag_result_notice(result: dict[str, Any]) -> tuple[str, str]:
    """Roadmap item 66 (Phase 5.1) — the real fix for a fully-already-
    tagged re-run producing NO prominent notice at all (only the small,
    easy-to-miss results panel): every real outcome now gets a message,
    not just tagged/without_art/failed. Returns (message, notice_kind).

    Roadmap item 75 (P6, 6a/6.2) — a real, live-confirmed second gap:
    `_tag_one_track` never even LOOKS at art for an already-tagged
    track (`skip_tag_write` short-circuits before the art step is
    reached at all) — so "already tagged" here does not mean "art is
    fine," it means "art was never checked this run." Every branch
    below that can co-occur with a nonzero `skipped_already_tagged`
    now says so explicitly, in every message shape (mixed fresh+
    already-tagged runs previously said nothing about the skipped
    ones at all) — not just the "everything was already tagged"
    all-skip case this function handled before.
    """
    tagged = result["tagged"]
    without_art = result["tagged_without_art"]
    failed = result["failed"]
    already_tagged = result.get("skipped_already_tagged", 0)

    art_not_checked_note = ""
    if already_tagged:
        possessive = (
            "track's" if already_tagged == 1 else "tracks'"
        )
        art_not_checked_note = (
            f" {already_tagged} already-tagged {possessive} cover art "
            f"was NOT checked this run — use \"Fix missing cover art\" "
            f"to check them."
        )

    message = f"Tagged {tagged} track{'s' if tagged != 1 else ''}"

    if without_art:
        message += f" — {without_art} without cover art"

    if failed:
        message += f", {failed} failed"
        message += " — see the results panel below for details."
        return message + art_not_checked_note, "error"

    if without_art:
        message += " — see the results panel below for details."
        return message + art_not_checked_note, "warning"

    if tagged:
        return message + "." + art_not_checked_note, "success"

    if already_tagged:
        plural = "s" if already_tagged != 1 else ""
        return (
            f"{already_tagged} track{plural} already tagged — nothing "
            f"to do for text tags, and their cover art was NOT checked "
            f"this run. Right-click a row for \"Re-tag,\" check "
            f"\"Re-tag already tagged files\" to overwrite, or use "
            f"\"Fix missing cover art\" to check art without a full "
            f"re-tag.",
            "info",
        )

    return (
        "Nothing was tagged — see the results panel below for details.",
        "info",
    )


# --- Review tab ------------------------------------------------------------

TOOLTIP_CONFIRM_REVIEW_CANDIDATE = (
    "Accept this SoulSeek match and request the download — a human "
    "confirmation is treated as stronger than the algorithm's own score."
)
TOOLTIP_REJECT_REVIEW_CANDIDATE = (
    "Discard this candidate. It isn't blacklisted — a later search can "
    "surface it again."
)
TOOLTIP_REPLACE_UPGRADE = (
    "Replace the file currently in your library with this "
    "higher-quality download."
)
TOOLTIP_DECLINE_UPGRADE = (
    "Keep your current file. This upgrade stays available to approve "
    "later — nothing is deleted."
)
TOOLTIP_DELETE_OLD_FILE_CHECKBOX = (
    "Also delete the file being replaced from disk, not just from the "
    "library record."
)
TOOLTIP_CONFIRM_LOCAL_MATCH = (
    "Confirm this local file is the right match. It won't be demoted or "
    "recomputed by a future re-match."
)
TOOLTIP_REJECT_LOCAL_MATCH = (
    "Discard this match. It isn't blacklisted — a later match run can "
    "surface it again."
)
TOOLTIP_DOUBLE_CLICK_TO_REVIEW = "Double-click to review this track."

# --- Duplicates tab ---------------------------------------------------------

TOOLTIP_DUPLICATES_LOCATION_COMBO = (
    "Which registered library location to scan, when scanning a whole "
    "location. Also used with \"Only these folders…\" below: if a "
    "folder sits inside more than one registered location (a nested "
    "location registered inside another), this is the tiebreak "
    "preference — the most specific match still always wins first."
)
TOOLTIP_COMPUTE_FINGERPRINTS = (
    "Compute an audio fingerprint for every file in scope that doesn't "
    "already have one. Needed once before Find Duplicates can compare "
    "files — can take a while for a large location. Only real audio "
    "files are ever scanned into the library in the first place, so "
    "non-audio files are never considered here."
)
TOOLTIP_FIND_DUPLICATES = (
    "Compare every already-fingerprinted file in scope and group the "
    "ones that are the same recording, by audio content."
)
TOOLTIP_DUPLICATES_FOLDERS_CHECKBOX = (
    "Scope to specific folders instead of a whole location — several "
    "folders are pooled and compared together, even across different "
    "registered locations. The location combo above stays available "
    "as a tiebreak preference while this is checked."
)
TOOLTIP_DUPLICATES_ADD_FOLDER = "Add a folder to the scope."
TOOLTIP_DUPLICATES_REMOVE_FOLDER = (
        "Remove the selected folder(s) from the scope."
)
DUPLICATES_FOLDER_NOT_IN_A_LOCATION = (
    "'{folder}' isn't inside any registered library location — add it "
    "as a location first, or pick a folder inside one that's already "
    "registered."
)


def format_duplicates_scope_count(summary: Any) -> str:
    """Roadmap item 68 (Phase 7.2) — shown BEFORE a real, potentially
    ~10-minute-at-real-scale operation (item 39's own real number), so
    the scope control is worth having: the user sees what it actually
    covers first.

    Roadmap item 77 (P8.3/8.4) — takes a real
    `DuplicateService.ScopeSummary` (typed `Any` here only to avoid a
    library-layer import in this presentation-only module, matching
    this file's existing pattern for `result: dict[str, Any]`
    elsewhere below) rather than a bare int: a silent "0 files in
    scope" was the actual reported bug — this now always names which
    real location(s) the folders resolved to, and says PLAINLY when
    one of them has never been scanned at all, instead of leaving that
    only discoverable by reading source code.
    """
    locations = ", ".join(summary.resolved_location_names)
    location_suffix = f" ({locations})" if locations else ""
    base = (
        f"{summary.file_count} "
        f"file{'s' if summary.file_count != 1 else ''} in scope"
        f"{location_suffix}."
    )

    if not summary.empty_locations:
        return base

    empty = ", ".join(summary.empty_locations)
    return (
        f"{base} '{empty}' has no scanned files yet — run Rescan and "
        f"match library first."
    )


_FINGERPRINT_FAILURE_REASON_LABELS = {
    "file_missing": "file missing",
    "empty_file": "0-byte file",
    "decode_unsupported": "couldn't be decoded",
    "error": "other error",
}


def format_fingerprint_result_message(result: dict[str, Any]) -> str:
    """Roadmap item 68 (Phase 8.2) — the aggregate line PLUS, when
    there's at least one failure, a real per-reason breakdown (never
    just one lumped "Failed: N") — mirrors the CLI's own per-file
    `[reason] message` detail lines (cli.py's fingerprint handler),
    just summarized rather than listed one-by-one for the UI's status
    label. Phase 8.3's own "never offer to delete" scope needs nothing
    further here — an empty_file entry can never enter a duplicate
    group in the first place (find_duplicate_groups only clusters
    already-fingerprinted files), so there's no delete action anywhere
    in this app that could ever reach one.
    """
    base = (
        f"Fingerprinted: {result['computed']}, "
        f"Skipped (already computed): "
        f"{result['skipped_already_computed']}, "
        f"Failed: {result['failed']}."
    )

    if result["failed"] == 0:
        return base

    counts: dict[str, int] = {}
    for detail in result["details"]:
        reason = detail.get("reason", "error")
        counts[reason] = counts.get(reason, 0) + 1

    breakdown = ", ".join(
        f"{count} {_FINGERPRINT_FAILURE_REASON_LABELS.get(reason, reason)}"
        for reason, count in sorted(counts.items(), key=lambda item: -item[1])
    )

    return f"{base} ({breakdown})"


TOOLTIP_KEEP_FILE_RADIO = (
    "Which copy in this group to keep. Pre-selected to the highest-"
    "quality copy, but you can pick a different one."
)
TOOLTIP_KEEP_ALL_DUPLICATES_RADIO = (
    "Keep every file in this group — sometimes the same recording in "
    "several folders is deliberate. Disables Delete for this group."
)
TOOLTIP_DELETE_DUPLICATES_CHECKBOX = (
    "Confirm you want to permanently delete every other file in this "
    "group from disk. Required before Delete does anything."
)
TOOLTIP_DELETE_DUPLICATES_BUTTON = (
    "Delete every file in this group except the one selected to keep. "
    "Only takes effect once the checkbox above is checked."
)
DELETE_DUPLICATES_CONFIRM_TITLE = "Delete duplicate files?"


def format_delete_duplicates_confirm_body(paths: list[str]) -> str:
    """The exact full paths about to be permanently deleted — roadmap
    item 56 Phase 6.3: deleting real user files warrants naming them,
    not just a bare count."""
    listed = "\n".join(f"  {path}" for path in paths)
    count = len(paths)
    plural = "s" if count != 1 else ""

    return (
        f"This will permanently delete {count} file{plural} from disk:\n\n"
        f"{listed}\n\n"
        f"This cannot be undone."
    )


# --- Roadmap item R3: bulk actions -------------------------------------------
# Both are among the two most destructive actions in the app (upgrade
# replacement can delete a real old file; duplicate resolution always
# deletes real files) — each inherits the project's standing "never
# modify/delete a real user file without explicit confirmation" rule in
# full, via a real listing of what will happen plus an explicit,
# default-off confirmation control. Neither reuses a stale plan from an
# earlier click — both are built fresh, from what's on screen right now,
# at the moment the button is clicked (item 76's own lesson).

TOOLTIP_REPLACE_ALL_UPGRADES = (
    "Replace every downloaded upgrade currently ready for review, all "
    "at once. Shows exactly what will change before anything happens."
)
BULK_REPLACE_UPGRADES_DIALOG_TITLE = "Replace All Upgrades"


def format_bulk_replace_upgrades_intro(count: int) -> str:
    plural = "s" if count != 1 else ""
    return (
        f"{count} upgrade{plural} ready to replace. Each one below will "
        f"have its current file replaced with the higher-quality "
        f"download shown."
    )


TOOLTIP_BULK_DELETE_OLD_FILES_CHECKBOX = (
    "Also delete every replaced file from disk, not just from the "
    "library record. Applies to the whole batch below — off by "
    "default."
)


def format_bulk_replace_upgrades_result(result: Any) -> str:
    """Roadmap item R3.1 — the same honest-reporting shape
    format_rename_result_message uses: a real count, plus one detail
    line per row so a partial failure is never just a bare number."""
    lines = [f"Replaced: {result.replaced}, Failed: {result.failed}."]
    lines.extend(f"  {detail}" for detail in result.details)
    return "\n".join(lines)


TOOLTIP_RESOLVE_ALL_DUPLICATES = (
    "Resolve every duplicate group currently shown, all at once. Any "
    "group set to \"Keep all\" is left untouched. Shows the exact real "
    "files that would be kept and deleted before anything happens."
)
BULK_RESOLVE_DUPLICATES_DIALOG_TITLE = "Resolve All Duplicate Groups"
BULK_RESOLVE_DUPLICATES_NO_GROUPS = (
    "Nothing to resolve — every group is set to \"Keep all,\" or there "
    "are no groups."
)


def format_bulk_resolve_duplicates_intro(
        group_count: int,
        file_count: int,
) -> str:
    group_plural = "s" if group_count != 1 else ""
    file_plural = "s" if file_count != 1 else ""
    return (
        f"{group_count} group{group_plural} will be resolved, "
        f"permanently deleting {file_count} file{file_plural} from disk. "
        f"Any group set to \"Keep all\" is skipped, not overridden."
    )


TOOLTIP_BULK_DELETE_DUPLICATES_CHECKBOX = (
    "Confirm you want to permanently delete every listed file above. "
    "Required before Resolve does anything."
)


def format_bulk_resolve_duplicates_result(result: Any) -> str:
    lines = [
        f"Resolved: {result.groups_resolved} group(s), "
        f"{result.files_deleted} file(s) deleted"
        + (
            f" ({result.files_failed} failed)."
            if result.files_failed else "."
        )
    ]
    lines.extend(f"  {detail}" for detail in result.details)
    return "\n".join(lines)


# --- Sharing page (roadmap item 62, Phase 7) --------------------------------
# SoulSeek only works because peers share files back — Seeker downloads
# from other people's shares, so this page frames what Seeker itself is
# giving back, honestly: what real mechanics affect it (locked files,
# leecher groups) and what Seeker deliberately can't promise (there's no
# protocol-level guarantee that sharing unlocks anything for you
# specifically). The goal isn't a persuasive pitch — it's "be a genuine
# sharer, see that you are, and see what you're giving back."

SHARING_FRAMING_BODY = (
    "<h3>Why this page exists</h3>"
    "<p>SoulSeek has no central library — every file available to "
    "download exists because someone chose to share it. Seeker's own "
    "downloads only work because other people are sharing.</p>"
    "<p><b>Locked files</b> — some peers only share with users who are "
    "themselves sharing enough back (a \"leecher\" restriction most "
    "clients, including slskd, can enable). A file showing as locked in "
    "a search result isn't necessarily unavailable to you forever — it "
    "depends on that peer's own sharing rules, which Seeker has no way "
    "to see in advance.</p>"
    "<p><b>Upload priority</b> — clients (again including slskd) can "
    "give queue priority to peers who share more. There's no published "
    "formula, and it varies by peer — sharing more can help, but "
    "SoulSeek's protocol makes no guarantee about it.</p>"
    "<p>This page won't promise sharing unlocks anything specific for "
    "you. It just shows, honestly, what's actually shared right now and "
    "who's actually downloading it — so you can see whether you're a "
    "genuine participant in the network you're relying on.</p>"
)

TOOLTIP_SHARING_REFRESH = (
    "Re-check slskd's real share status and who's currently downloading "
    "from you."
)
TOOLTIP_ADD_LOCATION_TO_SHARE = (
    "Share this library location's files with the SoulSeek network, "
    "read-only. Recreates the slskd container — takes a moment."
)
SHARING_ADD_CONFIRM_TITLE = "Share this location?"
SHARING_NOT_SELF_MANAGED_NOTICE = (
    "This slskd isn't one Seeker set up itself, so Seeker won't rewrite "
    "its configuration. Use the preview below as a guide to add this "
    "share yourself."
)
SHARING_UNCONFIGURED_NOTICE = (
    "Set up SoulSeek in Settings to see sharing status."
)


def format_add_to_share_confirm_body(
        location_name: str,
        location_path: str,
        container_path: str,
) -> str:
    """Names the exact folder about to be shared and where it lands
    inside the container — mirrors format_delete_duplicates_confirm_body's
    "name what's about to happen, don't just say 'are you sure'"
    convention for any action confirmation on real user data/infra."""
    return (
        f"This will share '{location_path}' (library location "
        f"'{location_name}') with the SoulSeek network, read-only, as "
        f"{container_path}.\n\n"
        f"Seeker will back up docker-compose.yml and slskd.yml first, "
        f"then recreate the slskd container. This can take a minute."
    )


TOOLTIP_UPLOADS_TABLE = (
    "Real-time transfers other SoulSeek peers are currently downloading "
    "from your shares."
)
NO_UPLOADS_LABEL = "No one is currently downloading from you."

# --- History page -----------------------------------------------------------

TOOLTIP_HISTORY_FILTER_COMBO = (
    "Show every event, or just downloads / just tagging actions."
)
TOOLTIP_HISTORY_REFRESH_BUTTON = (
    "Re-check current data for recently downloaded and tagged tracks."
)

# --- Search tab (roadmap item 82, P13) --------------------------------------

TOOLTIP_SEARCH_ARTIST = "Artist name to search for."
TOOLTIP_SEARCH_TITLE = "Track title to search for."
TOOLTIP_SEARCH_BUTTON = (
    "Search SoulSeek for this artist/title. A real search against the "
    "live network typically takes 20-45 seconds."
)
TOOLTIP_DOWNLOAD_BEST = (
    "Download the best available candidate automatically — the same "
    "quality-with-fallback logic every playlist download already uses."
)
TOOLTIP_DOWNLOAD_THIS_ONE = (
    "Download this specific file instead of the automatic best pick."
)
SEARCH_EMPTY_FIELDS_MESSAGE = "Enter both an artist and a title first."
SEARCH_NO_RESULTS_MESSAGE = "No results found."


def format_search_result_count(count: int) -> str:
    return f"Found {count} result{'s' if count != 1 else ''}."


def format_search_download_result(result: dict[str, Any]) -> str:
    """Roadmap item 82 (P13.5) — a real outcome message for both
    download_manual() branches: a settled request (username/filename
    known) and a locked-only upgrade request (nothing downloadable
    right this moment, but something real is being chased)."""
    if not result["requested"]:
        return "No candidates found."

    if result["settled"]:
        return f"Requested from {result['username']}: {result['filename']}"

    return (
        "No practical candidate — requested a locked/upgrade-only "
        "candidate. Check the Downloads page for progress."
    )


# --- Settings: Library Locations tab --------------------------------------

TOOLTIP_ADD_LOCATION = (
    "Pick a folder on disk and register it as a place Seeker scans for "
    "audio files — named after the folder itself; rename it anytime "
    "below."
)
TOOLTIP_REMOVE_LOCATION = (
    "Unregister this location. Files already matched or tagged are "
    "unaffected — nothing on disk is touched."
)
TOOLTIP_RENAME_LOCATION = "Give this location a different display name."

# --- Settings: Playlist Destinations tab ----------------------------------

TOOLTIP_DEFAULT_LOCATION_COMBO = (
    "Where downloads land for any playlist that doesn't have its own "
    "destination set below."
)
TOOLTIP_DEFAULT_SUBFOLDER_PER_PLAYLIST_CHECKBOX = (
    "Put each playlist's downloads in their own subfolder, named after "
    "the playlist, inside the location above."
)
TOOLTIP_SAVE_DEFAULT_DESTINATION = (
    "Save this as the fallback destination for every playlist without "
    "its own."
)
TOOLTIP_DESTINATION_LOCATION_COMBO = (
    "Which registered library location completed downloads for this "
    "playlist should move into."
)
TOOLTIP_DESTINATION_SUBFOLDER_FIELD = (
    "Optional subfolder inside that location, e.g. \"Techno\"."
)
TOOLTIP_SAVE_DESTINATION = (
    "Save where this playlist's completed SoulSeek downloads should "
    "land."
)

# --- Settings: Connection tab ----------------------------------------------

TOOLTIP_SPOTIFY_CLIENT_ID_FIELD = (
    "From your app on the Spotify Developer Dashboard. Not secret — "
    "PKCE authorization has no client secret."
)
TOOLTIP_REAUTHORIZE_SPOTIFY = (
    "Re-run Spotify's authorization flow, even if a cached token is "
    "still valid — opens a real browser window."
)
TOOLTIP_REVEAL_API_KEY = "Show or hide the real slskd API key."
TOOLTIP_TEST_CONNECTION = (
    "Check whether Seeker can reach slskd right now with the currently "
    "saved connection details."
)
TOOLTIP_NEW_SOULSEEK_USERNAME_FIELD = (
        "Your SoulSeek network username (not slskd's own web login)."
)
TOOLTIP_NEW_SOULSEEK_PASSWORD_FIELD = (
        "Your SoulSeek network password (not slskd's own web login)."
)
TOOLTIP_UPDATE_CREDENTIALS = (
    "Recreate the slskd container with these credentials and a freshly "
    "generated API key."
)

# --- Settings: Thresholds tab -----------------------------------------------

TOOLTIP_AUTO_MATCH_THRESHOLD_FIELD = (
    "Match score at or above which a track is auto-accepted with no "
    "review."
)
TOOLTIP_NEEDS_REVIEW_THRESHOLD_FIELD = (
    "Match score at or above which a track is surfaced for review "
    "instead of treated as no match at all."
)
TOOLTIP_SAVE_THRESHOLDS = (
    "Save. Takes effect on the very next match/download run — no "
    "restart needed."
)

# --- Roadmap item R7.5: menu-bar notification toggles -----------------------

TOOLTIP_NOTIFY_DOWNLOADS_FINISHED_CHECKBOX = (
    "Notify when downloads finish, batched into one notification per "
    "playlist rather than one per track."
)
TOOLTIP_NOTIFY_NEEDS_DECISION_CHECKBOX = (
    "Notify when a new SoulSeek candidate or upgrade needs your "
    "confirm/decline decision on the Review page."
)
TOOLTIP_NOTIFY_ERRORS_CHECKBOX = (
    "Notify when Seeker can't reach slskd. Rate-limited so a genuinely "
    "unreachable slskd doesn't notify on every poll."
)

# --- Onboarding wizard -------------------------------------------------------

TOOLTIP_OPEN_SPOTIFY_DASHBOARD = (
    "Open developer.spotify.com/dashboard in your browser to register "
    "an app and get a Client ID."
)
TOOLTIP_COPY_REDIRECT_URI = (
        "Copy the redirect URI to paste into your Spotify app's settings."
)
TOOLTIP_CLIENT_ID_FIELD = "Paste the Client ID from your Spotify app here."
TOOLTIP_CONNECT_SPOTIFY = (
    "Open a browser window to authorize Seeker against your Spotify "
    "account."
)
TOOLTIP_CHOOSE_LIBRARY_FOLDER = (
    "Pick the folder Seeker should scan for your existing audio files."
)
TOOLTIP_DOWNLOAD_INTO_LIBRARY_CHECKBOX = (
    "Make this folder the default destination for new SoulSeek "
    "downloads, so playlists without their own destination just work."
)
TOOLTIP_SUBFOLDER_PER_PLAYLIST_CHECKBOX = (
    "Give each playlist its own subfolder inside this location, named "
    "after the playlist."
)
TOOLTIP_SOULSEEK_USERNAME_FIELD = "Your SoulSeek network username (created on first login, not chosen in advance)."
TOOLTIP_SOULSEEK_PASSWORD_FIELD = "Your SoulSeek network password."
SOULSEEK_ACCOUNT_MODE_EXPLANATION = (
    "SoulSeek has no separate signup — the account below is created "
    "the first time these credentials connect, so if you're creating "
    "a new one, the username has to be one nobody has taken."
)
TOOLTIP_EXISTING_SOULSEEK_ACCOUNT_RADIO = (
    "You already have a SoulSeek username and password."
)
TOOLTIP_NEW_SOULSEEK_ACCOUNT_RADIO = (
    "This will be your first time connecting with this username — it "
    "gets created automatically if nobody else has taken it."
)
TOOLTIP_BRING_UP_SOULSEEK = (
    "Start slskd via Docker and connect it to the SoulSeek network with "
    "these credentials."
)
TOOLTIP_SKIP_SOULSEEK = (
    "Finish setup without SoulSeek — you can come back to this anytime "
    "from Settings."
)
TOOLTIP_DOWNLOAD_DOCKER = "Open Docker's download page in your browser."
TOOLTIP_LAUNCH_DOCKER = "Launch Docker Desktop so it can be used to run slskd."
TOOLTIP_CHECK_DOCKER_AGAIN = "Re-check whether Docker is running now."

# --- Shared: library location picker (wizard + Settings) --------------------
# The one control genuinely shared between two windows — kept here so
# both call sites read the identical copy rather than risk drifting the
# way matching.py's two independent copies once did.

LIBRARY_LOCATION_PICKER_DIALOG_TITLE = "Choose Music Folder"

# --- Help menu / About ---------------------------------------------------

ABOUT_MENU_TEXT = "About Seeker"

ABOUT_DIALOG_TITLE = "About Seeker"

ABOUT_DIALOG_BODY = (
    "<h3>Seeker</h3>"
    "<p>A personal DJ music library management assistant. Syncs Spotify "
    "playlists to a local cache, matches them against your existing "
    "library, and searches SoulSeek for whatever's missing.</p>"
)

ABOUT_DIALOG_AUTHOR_LINE = (
    "<p>Made by Kristiyan Dimitrov — "
    "<a href=\"mailto:kristiyanddimitrov@gmail.com\">"
    "kristiyanddimitrov@gmail.com</a> · "
    "<a href=\"https://github.com/KristiyanDDimitrov/Seeker\">"
    "GitHub</a></p>"
)

ABOUT_DIALOG_LICENSE_LINE = (
    "<p>MIT License. Copyright (c) 2026 Kristiyan Dimitrov. See the "
    "LICENSE file for the full text.</p>"
)

# Real license identifiers, confirmed directly against each installed
# package's own metadata (not assumed) — not an exhaustive legal NOTICE
# file, just an honest, correctly-sourced summary for a portfolio
# project. libchromaprint is dynamically loaded via ctypes at runtime
# (see audio_fingerprint.py/CLAUDE.md item 38-39), never statically
# linked or bundled — the correct, low-risk way to use an LGPL library
# from a closed-source app.
ABOUT_DIALOG_THIRD_PARTY_NOTICES = (
    "<p><b>Third-party notices</b><br>"
    "Built with PySide6/Qt (LGPL-3.0), librosa (ISC), mutagen "
    "(GPL-2.0-or-later), libchromaprint (LGPL-2.1-or-later, loaded "
    "dynamically at runtime), NumPy/SciPy/httpx/soundfile/"
    "python-dotenv (BSD-3-Clause), and platformdirs/rapidfuzz/"
    "pyloudnorm/packaging (MIT/Apache-2.0). Each project's own license "
    "governs its use.</p>"
)

# --- Update check (Phase 11) -------------------------------------------
# GitHub-releases-based — see update_check.py's own docstring for the
# real external-dependency caution (rate limits, "never raises").
# User-triggered only, from this one menu action.

CHECK_FOR_UPDATES_MENU_TEXT = "Check for updates…"
UPDATE_CHECK_DIALOG_TITLE = "Check for Updates"

# --- Task 3: support-the-creator links -------------------------------------
# Both real now (PayPal's went live 2026-09-01). A future new entry
# should still start as an obvious "TODO: ..." placeholder rather than
# a fabricated look-real link, so it's easy to grep for and replace —
# AboutDialog filters any TODO-prefixed value out via
# is_real_support_link() before rendering a button for it, so a real
# user never sees a button that would open a dead, non-URL string.
SUPPORT_LINKS: dict[str, str] = {
    "Revolut": "https://revolut.me/kddimitrov",
    "PayPal": "https://paypal.me/KristiyanDimitrov98",
}


def is_real_support_link(url: str) -> bool:
    return not url.startswith("TODO")


# --- Support page (roadmap item 64) ----------------------------------------
# A real sidebar page, distinct from AboutDialog's brief support-links row —
# framed the same honest, non-persuasive way SHARING_FRAMING_BODY is: a
# statement of fact, not marketing copy. Reuses SUPPORT_LINKS/
# is_real_support_link/ABOUT_DIALOG_AUTHOR_LINE/TOOLTIP_SUPPORT_LINK above
# rather than duplicating any of them.

SUPPORT_TAB_SUBTITLE = (
    "Seeker is free, with no telemetry and no paid tier. Nothing here is "
    "required."
)

SUPPORT_PAGE_FRAMING_BODY = (
    "<h3>Support Seeker</h3>"
    "<p>Seeker is free to use, has no telemetry, and has no paid tier — "
    "nothing in the app is gated behind a donation. If it's been useful "
    "to you, a donation is a thank-you, not a purchase.</p>"
)

SUPPORT_PAGE_NON_FINANCIAL_HEADING = "<h3>Other ways to help</h3>"

SUPPORT_PAGE_REPORT_BUG_BODY = (
    "<p><b>Report a bug</b> — open an issue on "
    "<a href=\"https://github.com/KristiyanDDimitrov/Seeker/issues\">"
    "GitHub</a> if something's broken or confusing.</p>"
)

SUPPORT_PAGE_SHARE_LIBRARY_BODY = (
    "<p><b>Share your library back on SoulSeek</b> — Seeker only works "
    "because other people share files; sharing yours back costs nothing "
    "and helps the network Seeker relies on.</p>"
)

SUPPORT_PAGE_GO_TO_SHARING_BUTTON_TEXT = "Go to Sharing"

TOOLTIP_SUPPORT_LINK = "Opens in your browser."

DONE_PAGE_TITLE_HTML = "<h2>You're all set</h2>"
DONE_PAGE_BODY = (
    "Seeker is ready — sync your playlists, scan your library, and "
    "start matching whenever you like."
)
DONE_PAGE_SUPPORT_PROMPT = "Enjoying Seeker?"
DONE_PAGE_CONTINUE_BUTTON_TEXT = "Go to Dashboard"

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

# --- Persistent tab/section subtitles (not hover-dependent) --------------
# One line under each tab's own header, aimed at someone who never reads
# the README and goes straight into the app.

DASHBOARD_TAB_SUBTITLE = (
    "Pick a playlist on the left to see each track's status, then tag "
    "or download what's missing."
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
DATA_LOCATION_DATABASE_LABEL = "Database:"
DATA_LOCATION_CONFIG_LABEL = "Config:"
DATA_LOCATION_SPOTIFY_TOKEN_LABEL = "Spotify token:"
DATA_LOCATION_SLSKD_LABEL = "SoulSeek data:"
OPEN_DATA_FOLDER_BUTTON_TEXT = "Open Data Folder"
TOOLTIP_OPEN_DATA_FOLDER = (
    "Open the folder above in Finder/Explorer/your file manager."
)

# --- MainWindow toolbar ---------------------------------------------------

TOOLTIP_SYNC_ALL_PLAYLISTS = (
    "Pull your Spotify playlists' names and track counts into the local "
    "cache (metadata only — no tracks yet)."
)
TOOLTIP_SCAN_ALL_LOCATIONS = (
    "Re-scan every registered library location on disk for audio files, "
    "then automatically re-match cached Spotify tracks against what was "
    "found."
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
TOOLTIP_BPM_MIN = "Lower bound for correcting octave errors (e.g. 128 detected as 64)."
TOOLTIP_BPM_MAX = "Upper bound for correcting octave errors (e.g. 64 detected as 128)."
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
    "Which registered library location to scan — duplicate detection "
    "runs on one location at a time, never merged across all of them."
)
TOOLTIP_COMPUTE_FINGERPRINTS = (
    "Compute an audio fingerprint for every file in this location that "
    "doesn't already have one. Needed once before Find Duplicates can "
    "compare files — can take a while for a large location."
)
TOOLTIP_FIND_DUPLICATES = (
    "Compare this location's already-fingerprinted files and group the "
    "ones that are the same recording, by audio content."
)
TOOLTIP_KEEP_FILE_RADIO = (
    "Which copy in this group to keep. Pre-selected to the highest-"
    "quality copy, but you can pick a different one."
)
TOOLTIP_DELETE_DUPLICATES_CHECKBOX = (
    "Confirm you want to permanently delete every other file in this "
    "group from disk. Required before Delete does anything."
)
TOOLTIP_DELETE_DUPLICATES_BUTTON = (
    "Delete every file in this group except the one selected to keep. "
    "Only takes effect once the checkbox above is checked."
)

# --- History page -----------------------------------------------------------

TOOLTIP_HISTORY_FILTER_COMBO = (
    "Show every event, or just downloads / just tagging actions."
)
TOOLTIP_HISTORY_REFRESH_BUTTON = (
    "Re-check current data for recently downloaded and tagged tracks."
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
TOOLTIP_NEW_SOULSEEK_USERNAME_FIELD = "Your SoulSeek network username (not slskd's own web login)."
TOOLTIP_NEW_SOULSEEK_PASSWORD_FIELD = "Your SoulSeek network password (not slskd's own web login)."
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

# --- Onboarding wizard -------------------------------------------------------

TOOLTIP_OPEN_SPOTIFY_DASHBOARD = (
    "Open developer.spotify.com/dashboard in your browser to register "
    "an app and get a Client ID."
)
TOOLTIP_COPY_REDIRECT_URI = "Copy the redirect URI to paste into your Spotify app's settings."
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

TOOLTIP_SUPPORT_LINK = "Opens in your browser."

DONE_PAGE_TITLE_HTML = "<h2>You're all set</h2>"
DONE_PAGE_BODY = (
    "Seeker is ready — sync your playlists, scan your library, and "
    "start matching whenever you like."
)
DONE_PAGE_SUPPORT_PROMPT = "Enjoying Seeker?"
DONE_PAGE_CONTINUE_BUTTON_TEXT = "Go to Dashboard"

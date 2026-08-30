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
    "playlists — updates automatically."
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

# --- MainWindow toolbar ---------------------------------------------------

TOOLTIP_SYNC_ALL_PLAYLISTS = (
    "Pull your Spotify playlists' names and track counts into the local "
    "cache (metadata only — no tracks yet)."
)
TOOLTIP_SCAN_ALL_LOCATIONS = (
    "Re-scan every registered library location on disk for audio files."
)
TOOLTIP_MATCH_ALL_TRACKS = (
    "Fuzzy-match every cached Spotify track against your scanned local "
    "files."
)
TOOLTIP_DOWNLOAD_SELECTED_PLAYLIST = (
    "Search SoulSeek and request downloads for the selected playlist's "
    "still-unmatched tracks."
)
TOOLTIP_OPEN_SETTINGS = (
    "Library locations, playlist destinations, connections, and "
    "match thresholds."
)
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

# --- Settings: Library Locations tab --------------------------------------

TOOLTIP_NEW_LOCATION_NAME_FIELD = "A short name for this folder, e.g. \"Main Library\"."
TOOLTIP_ADD_LOCATION = (
    "Pick a folder on disk and register it as a place Seeker scans for "
    "audio files."
)
TOOLTIP_REMOVE_LOCATION = (
    "Unregister this location. Files already matched or tagged are "
    "unaffected — nothing on disk is touched."
)

# --- Settings: Playlist Destinations tab ----------------------------------

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
TOOLTIP_SOULSEEK_USERNAME_FIELD = "Your SoulSeek network username (created on first login, not chosen in advance)."
TOOLTIP_SOULSEEK_PASSWORD_FIELD = "Your SoulSeek network password."
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

# --- Task 3: support-the-creator links -------------------------------------
# The PayPal URL isn't ready yet — deliberately marked as an obvious
# placeholder, not a fabricated look-real link. Replace it with the real
# destination before this is shipped to anyone.
SUPPORT_LINKS: dict[str, str] = {
    "Revolut": "https://revolut.me/kddimitrov",
    "PayPal": "TODO: paste real PayPal link",
}

TOOLTIP_SUPPORT_LINK = "Opens in your browser."

DONE_PAGE_TITLE_HTML = "<h2>You're all set</h2>"
DONE_PAGE_BODY = (
    "Seeker is ready — sync your playlists, scan your library, and "
    "start matching whenever you like."
)
DONE_PAGE_SUPPORT_PROMPT = "Enjoying Seeker?"
DONE_PAGE_CONTINUE_BUTTON_TEXT = "Go to Dashboard"

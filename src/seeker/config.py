"""The environment fallback for values config.json does not hold yet.

Read from `os.environ` at call time, never at import: `load_env_file()`
runs first thing in each entry point's `main()`, after this module is
already imported.
"""

import os
import sys

from dotenv import find_dotenv, load_dotenv


def load_env_file() -> None:
    """Load a `.env` from the working directory or its parents, for a
    development run (`uv run seeker`, `uv run seeker-ui` from the
    checkout). A frozen app never reads one: a `.env` near wherever
    the bundle happens to sit is not its configuration."""
    if getattr(sys, "frozen", False):
        return

    load_dotenv(find_dotenv(usecwd=True))


# Lazy at the config level, same treatment as SLSKD_* below — an
# onboarding wizard whose job is to collect SPOTIFY_CLIENT_ID can't
# function if reading it crashes first. Only enforced at the point
# Spotify auth is actually triggered (see Application.auth_manager).
def spotify_client_id() -> str | None:
    return os.getenv("SPOTIFY_CLIENT_ID")


def spotify_redirect_uri() -> str | None:
    return os.getenv("SPOTIFY_REDIRECT_URI")


# Optional at the config level — slskd is not required for sync/playlists/
# scan/match to work. Only enforced at the point soulseek_client is used.
def slskd_base_url() -> str | None:
    return os.getenv("SLSKD_BASE_URL")


def slskd_api_key() -> str | None:
    return os.getenv("SLSKD_API_KEY")


# Host filesystem path to slskd's own configured download directory (e.g.
# ./slskd-data/downloads). slskd's download-destination option only
# accepts a subfolder relative to its own download root, not an arbitrary
# path — so completed files are moved from here into a playlist's
# configured library location by `seeker downloads status`. Only enforced
# when that command needs to move a file.
def slskd_download_dir() -> str | None:
    return os.getenv("SLSKD_DOWNLOAD_DIR")


# Diagnostic: "1" logs every poll_downloads call at DEBUG, for the
# locked-retry storm investigation (HISTORY §63, §66).
def debug_poll() -> bool:
    return os.getenv("SEEKER_DEBUG_POLL") == "1"

import os

from dotenv import load_dotenv


load_dotenv()


# Lazy at the config level, same treatment as SLSKD_* below — an
# onboarding wizard whose job is to collect SPOTIFY_CLIENT_ID can't
# function if importing this module crashes first. Only enforced at the
# point Spotify auth is actually triggered (see Application.auth_manager).
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Optional at the config level — slskd is not required for sync/playlists/
# scan/match to work. Only enforced at the point soulseek_client is used.
SLSKD_BASE_URL = os.getenv("SLSKD_BASE_URL")
SLSKD_API_KEY = os.getenv("SLSKD_API_KEY")

# Host filesystem path to slskd's own configured download directory (e.g.
# ./slskd-data/downloads). slskd's download-destination option only
# accepts a subfolder relative to its own download root, not an arbitrary
# path — so completed files are moved from here into a playlist's
# configured library location by `seeker downloads status`. Only enforced
# when that command needs to move a file.
SLSKD_DOWNLOAD_DIR = os.getenv("SLSKD_DOWNLOAD_DIR")
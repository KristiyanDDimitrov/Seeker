import os

from dotenv import load_dotenv


load_dotenv()


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


if not SPOTIFY_CLIENT_ID:
    raise RuntimeError("SPOTIFY_CLIENT_ID is not configured.")

if not SPOTIFY_REDIRECT_URI:
    raise RuntimeError("SPOTIFY_REDIRECT_URI is not configured.")
import os

from dotenv import load_dotenv


load_dotenv()


SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")


if not SPOTIFY_CLIENT_ID:
    raise RuntimeError("SPOTIFY_CLIENT_ID is not configured.")

if not SPOTIFY_REDIRECT_URI:
    raise RuntimeError("SPOTIFY_REDIRECT_URI is not configured.")
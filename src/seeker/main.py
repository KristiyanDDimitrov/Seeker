import os

from dotenv import load_dotenv

from seeker.application import Application
from seeker.cli import run


def main() -> None:
    load_dotenv()

    client_id = os.getenv(
        "SPOTIFY_CLIENT_ID"
    )
    redirect_uri = os.getenv(
        "SPOTIFY_REDIRECT_URI"
    )

    if not client_id:
        raise RuntimeError(
            "SPOTIFY_CLIENT_ID is not configured."
        )

    if not redirect_uri:
        raise RuntimeError(
            "SPOTIFY_REDIRECT_URI is not configured."
        )

    application = Application(
        spotify_client_id=client_id,
        spotify_redirect_uri=redirect_uri,
    )

    run(application)
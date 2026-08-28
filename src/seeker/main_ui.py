import os
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from seeker.application import Application
from seeker.ui.main_window import MainWindow


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

    qt_app = QApplication(sys.argv)
    window = MainWindow(application)
    window.show()
    sys.exit(qt_app.exec())

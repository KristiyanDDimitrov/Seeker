import sys

from PySide6.QtWidgets import QApplication

from seeker.application import Application
from seeker.ui.main_window import MainWindow


def main() -> None:
    # Spotify/SoulSeek config is resolved lazily now (config store,
    # falling back to .env) — see Application.auth_manager. The
    # onboarding wizard is what actually collects this on a fresh
    # install; nothing here needs to pre-validate it.
    application = Application()

    qt_app = QApplication(sys.argv)
    window = MainWindow(application)
    window.show()
    sys.exit(qt_app.exec())

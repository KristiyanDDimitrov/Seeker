import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from seeker.application import Application
from seeker.ui.main_window import MainWindow
from seeker.ui.wizard import OnboardingWizard


def main() -> None:
    # Spotify/SoulSeek config is resolved lazily now (config store,
    # falling back to .env) — see Application.auth_manager. The
    # onboarding wizard is what actually collects this on a fresh
    # install; nothing here needs to pre-validate it.
    application = Application()

    qt_app = QApplication(sys.argv)

    window: QMainWindow

    if application.onboarding_complete:
        window = MainWindow(application)
    else:
        def show_dashboard() -> None:
            dashboard = MainWindow(application)
            dashboard.show()
            # Keep a reference alive past this function's return —
            # otherwise nothing holds the new window and Python would
            # garbage-collect it immediately (same class of bug as
            # ui/workers.py's _active_workers registry).
            qt_app.dashboard_window = dashboard  # type: ignore[attr-defined]

        window = OnboardingWizard(application, on_complete=show_dashboard)

    window.show()
    sys.exit(qt_app.exec())

import sys

from PySide6.QtWidgets import QApplication, QMainWindow

from seeker.application import Application
from seeker.ui.main_window import MainWindow
from seeker.ui.theme import apply_theme
from seeker.ui.wizard import OnboardingWizard


def main() -> None:
    # Spotify/SoulSeek config is resolved lazily now (config store,
    # falling back to .env) — see Application.auth_manager. The
    # onboarding wizard is what actually collects this on a fresh
    # install; nothing here needs to pre-validate it.
    application = Application()

    qt_app = QApplication(sys.argv)
    # Before any window is constructed — apply_theme() sets Fusion
    # (predictable QSS rendering on both macOS and Windows) plus the
    # dark palette/stylesheet every window relies on.
    apply_theme(qt_app)

    window: QMainWindow

    if application.onboarding_complete:
        window = MainWindow(application)
    else:
        def show_dashboard() -> None:
            dashboard = MainWindow(application)
            dashboard.show()
            # Keep a reference alive past this function's return —
            # otherwise nothing holds the new window and Python would
            # garbage-collect it immediately (same class of bug
            # ui/workers.py's _callbacks registry guards against for
            # in-flight background tasks).
            qt_app.dashboard_window = dashboard  # type: ignore[attr-defined]

        window = OnboardingWizard(application, on_complete=show_dashboard)

    window.show()
    sys.exit(qt_app.exec())

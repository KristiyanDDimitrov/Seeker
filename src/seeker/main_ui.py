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
    # palette/stylesheet every window relies on, resolved from the
    # user's persisted theme_mode (roadmap item C5; "system" default).
    apply_theme(qt_app, application.theme_mode)

    window: QMainWindow

    if application.onboarding_complete:
        # Roadmap item R7.1 — set only once a real MainWindow is about
        # to exist, never while only the onboarding wizard is up: with
        # no completed setup yet, closing the wizard quitting the whole
        # app is the correct (and previously the only) behavior — a
        # headless app left running with no window and no tray would be
        # a real regression of its own if this were set unconditionally
        # at the top of main().
        qt_app.setQuitOnLastWindowClosed(False)
        window = MainWindow(application)
        qt_app.aboutToQuit.connect(window.cleanup_before_quit)
    else:
        def show_dashboard() -> None:
            qt_app.setQuitOnLastWindowClosed(False)
            dashboard = MainWindow(application)
            qt_app.aboutToQuit.connect(dashboard.cleanup_before_quit)
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

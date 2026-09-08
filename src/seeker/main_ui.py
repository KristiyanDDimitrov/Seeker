import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication, QMainWindow

from seeker.application import Application, resolve_log_dir
from seeker.ui.main_window import MainWindow
from seeker.ui.theme import apply_theme
from seeker.ui.wizard import OnboardingWizard


def _configure_logging() -> None:
    # The GUI has no console a launched-from-Finder .app can write to
    # (§7.2.1) — a real log file is the only support story that works.
    # Same "seeker" logger tree as main.py's CLI StreamHandler, so
    # every service's logger.*() call reaches whichever of the two is
    # actually configured, with no per-call special-casing.
    log_path = resolve_log_dir() / "seeker.log"
    handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )

    logger = logging.getLogger("seeker")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main() -> None:
    _configure_logging()

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

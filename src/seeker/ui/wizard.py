import subprocess
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import platformdirs
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.config_store import load_config, resolve_config_path, save_config
from seeker.docker_setup import (
    DockerState,
    SlskdHealthCheckResult,
    SlskdHealthStatus,
    bring_up_slskd,
    check_slskd_health,
    detect_docker_state,
    generate_api_key,
)
from seeker.spotify.callback_server import DEFAULT_REDIRECT_URI
from seeker.ui.workers import run_worker

# Untuned constants, flagged same as every other threshold in this
# codebase. Poll interval matches the ~2s cadence already observed
# against real slskd elsewhere in this project (see CLAUDE.md); 60s is
# a reasonable starting timeout for a fresh `docker compose up` to
# reach a real Soulseek network login.
HEALTH_POLL_INTERVAL_MS = 2_000
HEALTH_POLL_TIMEOUT_SECONDS = 60.0

# Assumes the CLI's own documented convention: `docker compose up` is
# run from the project root (see README's setup instructions) — same
# CWD-relative assumption LEGACY_DATABASE_PATH makes elsewhere.
COMPOSE_FILE_PATH = Path("docker-compose.yml")

SLSKD_LOCAL_BASE_URL = "http://localhost:5030"


def _slskd_data_dir() -> Path:
    return Path(
        platformdirs.user_data_dir("Seeker", appauthor=False)
    ) / "slskd-data"


class OnboardingWizard(QMainWindow):
    """Three required-then-optional steps: Spotify connect, library
    location, SoulSeek/Docker setup (skippable). Resumable — each
    step's result is persisted to the config store as it completes, so
    a fresh launch starts at whichever REQUIRED step (1 or 2) is still
    incomplete rather than restarting from scratch. Step 3 is only ever
    reached within the same session as completing steps 1+2 — once
    both are done, Application.onboarding_complete is true and
    main_ui.py routes straight to the dashboard on every later launch,
    matching the task's literal completeness definition. Docker state
    is always re-checked live on entry to step 3 rather than assumed,
    so a `docker compose up` that already succeeded in a prior session
    is never blindly repeated.
    """

    def __init__(
            self,
            application: Application,
            on_complete: Callable[[], None],
    ):
        super().__init__()
        self.application = application
        self.on_complete = on_complete
        self.thread_pool = QThreadPool()

        self._library_location_path: str | None = None
        self._docker_state: DockerState | None = None
        self._slskd_api_key: str | None = None
        self._health_poll_timer: QTimer | None = None
        self._health_poll_elapsed = 0.0
        self._health_poll_started_at: datetime | None = None
        # Tracks whether docker_action_button.clicked currently has a
        # connection, so it's only ever disconnected when one genuinely
        # exists — PySide6 prints a libpyside RuntimeWarning (not a
        # raised exception) for a no-op disconnect(), which a bare
        # try/except doesn't actually suppress.
        self._docker_action_connected = False

        self.setWindowTitle("Seeker Setup")
        self.resize(520, 420)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.stack.addWidget(self._build_spotify_page())
        self.stack.addWidget(self._build_library_page())
        self.stack.addWidget(self._build_soulseek_page())

        self.stack.setCurrentIndex(self._initial_step())

        if self.stack.currentIndex() == 2:
            self._refresh_docker_state()

    def _initial_step(self) -> int:
        if not self.application.spotify_configured:
            return 0

        if not self.application.library_service.list_locations():
            return 1

        return 2

    # --- Step 1: Spotify -------------------------------------------

    def _build_spotify_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel("<h2>Connect Spotify</h2>"))
        layout.addWidget(QLabel(
            "Seeker needs a Spotify app to sync your playlists. "
            "Register one on the Spotify Developer Dashboard, then "
            "paste its Client ID below."
        ))

        dashboard_button = QPushButton("Open Spotify Developer Dashboard")
        dashboard_button.clicked.connect(
            lambda: webbrowser.open(
                "https://developer.spotify.com/dashboard"
            )
        )
        layout.addWidget(dashboard_button)

        redirect_row = QHBoxLayout()
        redirect_row.addWidget(
            QLabel(f"Redirect URI: {DEFAULT_REDIRECT_URI}")
        )
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(self._copy_redirect_uri)
        redirect_row.addWidget(copy_button)
        layout.addLayout(redirect_row)
        layout.addWidget(QLabel(
            "Add this exact Redirect URI to your Spotify app's "
            "settings — it must match exactly."
        ))

        self.client_id_field = QLineEdit()
        self.client_id_field.setPlaceholderText("Spotify Client ID")
        self.client_id_field.textChanged.connect(
            self._update_connect_button_state
        )
        layout.addWidget(self.client_id_field)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(
            self._on_connect_spotify_clicked
        )
        layout.addWidget(self.connect_button)

        self.spotify_status_label = QLabel("")
        layout.addWidget(self.spotify_status_label)

        layout.addStretch()
        return page

    def _copy_redirect_uri(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(DEFAULT_REDIRECT_URI)

    def _update_connect_button_state(self, text: str) -> None:
        self.connect_button.setEnabled(bool(text.strip()))

    def _on_connect_spotify_clicked(self) -> None:
        client_id = self.client_id_field.text().strip()

        def do_connect() -> None:
            config_path = resolve_config_path()
            current = load_config(config_path)
            updated = replace(
                current,
                spotify_client_id=client_id,
                spotify_redirect_uri=DEFAULT_REDIRECT_URI,
            )
            save_config(updated, config_path)
            self.application._config_store = updated
            self.application._auth_manager = None

            # Triggers the existing OAuth flow (auth_manager /
            # callback_server) — opens the system browser and waits
            # for the local callback. Genuinely long-running, hence
            # the worker.
            self.application.spotify

        run_worker(
            self.thread_pool,
            do_connect,
            button=self.connect_button,
            status_label=self.spotify_status_label,
            on_finished=lambda _: self._advance_from_spotify(),
        )
        self.spotify_status_label.setText(
            "Opening Spotify authorization page..."
        )

    def _advance_from_spotify(self) -> None:
        self.spotify_status_label.setText("Connected.")
        self.stack.setCurrentIndex(1)

    # --- Step 2: library location ------------------------------------

    def _build_library_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel("<h2>Choose your music library</h2>"))
        layout.addWidget(QLabel(
            "Seeker scans this folder for audio files to match "
            "against your Spotify tracks."
        ))

        self.library_path_label = QLabel("No folder selected.")
        layout.addWidget(self.library_path_label)

        choose_button = QPushButton("Choose Folder...")
        choose_button.clicked.connect(
            self._on_choose_library_folder_clicked
        )
        layout.addWidget(choose_button)

        self.library_status_label = QLabel("")
        layout.addWidget(self.library_status_label)

        layout.addStretch()
        return page

    def _on_choose_library_folder_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose Music Folder",
        )

        if not path:
            return

        self.library_path_label.setText(path)

        def do_add_location() -> str:
            location = self.application.library_service.add_location(
                "Library", path,
            )
            return location.path

        run_worker(
            self.thread_pool,
            do_add_location,
            status_label=self.library_status_label,
            on_finished=self._advance_from_library,
        )

    def _advance_from_library(self, location_path: str) -> None:
        self._library_location_path = location_path
        self.library_status_label.setText("Library registered.")
        self.stack.setCurrentIndex(2)
        self._refresh_docker_state()

    # --- Step 3: SoulSeek / Docker ------------------------------------

    def _build_soulseek_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel("<h2>Set up SoulSeek (optional)</h2>"))
        layout.addWidget(QLabel(
            "Seeker searches SoulSeek for tracks missing from your "
            "local library. This step is optional — SoulSeek-dependent "
            "actions stay disabled until it's set up, same as the CLI."
        ))

        self.docker_state_label = QLabel("Checking Docker...")
        layout.addWidget(self.docker_state_label)

        self.docker_action_button = QPushButton("")
        self.docker_action_button.hide()
        layout.addWidget(self.docker_action_button)

        layout.addWidget(QLabel("SoulSeek network account:"))

        self.soulseek_username_field = QLineEdit()
        self.soulseek_username_field.setPlaceholderText(
            "SoulSeek username"
        )
        layout.addWidget(self.soulseek_username_field)

        self.soulseek_password_field = QLineEdit()
        self.soulseek_password_field.setPlaceholderText(
            "SoulSeek password"
        )
        self.soulseek_password_field.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        layout.addWidget(self.soulseek_password_field)

        self.bring_up_button = QPushButton("Set up SoulSeek")
        self.bring_up_button.clicked.connect(self._on_bring_up_clicked)
        layout.addWidget(self.bring_up_button)

        self.soulseek_progress = QProgressBar()
        self.soulseek_progress.setRange(0, 0)
        self.soulseek_progress.hide()
        layout.addWidget(self.soulseek_progress)

        self.soulseek_status_label = QLabel("")
        layout.addWidget(self.soulseek_status_label)

        skip_button = QPushButton("Set up later")
        skip_button.clicked.connect(self._on_skip_soulseek_clicked)
        layout.addWidget(skip_button)

        layout.addStretch()
        return page

    def _refresh_docker_state(self) -> None:
        self.docker_state_label.setText("Checking Docker...")
        run_worker(
            self.thread_pool,
            detect_docker_state,
            on_finished=self._render_docker_state,
        )

    def _render_docker_state(self, state: DockerState) -> None:
        self._docker_state = state
        self._disconnect_docker_action()

        if state == DockerState.NOT_INSTALLED:
            self.docker_state_label.setText("Docker isn't installed.")
            self.docker_action_button.setText("Download Docker Desktop")
            self._connect_docker_action(
                lambda: webbrowser.open(
                    "https://www.docker.com/products/docker-desktop/"
                )
            )
            self.docker_action_button.show()
        elif state == DockerState.INSTALLED_NOT_RUNNING:
            if sys.platform in ("darwin", "win32"):
                self.docker_state_label.setText(
                    "Docker is installed but not running."
                )
                self.docker_action_button.setText("Launch Docker Desktop")
                self._connect_docker_action(self._on_launch_docker_clicked)
            else:
                # No "Desktop" app to assume on Linux — dockerd is
                # typically already running as a service if installed
                # via a package manager; guide rather than assume a
                # launch mechanism.
                self.docker_state_label.setText(
                    "Docker is installed, but the daemon isn't "
                    "running. Start it with your service manager, "
                    "e.g. 'sudo systemctl start docker', then check "
                    "again."
                )
                self.docker_action_button.setText("Check again")
                self._connect_docker_action(self._refresh_docker_state)
            self.docker_action_button.show()
        else:
            self.docker_state_label.setText("Docker is running.")
            self.docker_action_button.hide()

    def _connect_docker_action(self, slot: Callable[[], object]) -> None:
        self.docker_action_button.clicked.connect(slot)
        self._docker_action_connected = True

    def _disconnect_docker_action(self) -> None:
        if self._docker_action_connected:
            self.docker_action_button.clicked.disconnect()
            self._docker_action_connected = False

    def _on_launch_docker_clicked(self) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.run(
                    ["open", "-a", "Docker"], check=True, timeout=10,
                )
            elif sys.platform == "win32":
                subprocess.run(
                    ["cmd", "/c", "start", "", "Docker Desktop"],
                    check=True, timeout=10,
                )
            self.soulseek_status_label.setText(
                "Launching Docker Desktop... this can take a minute."
            )
        except (OSError, subprocess.SubprocessError):
            self.soulseek_status_label.setText(
                "Couldn't launch Docker Desktop automatically — open "
                "it manually, then click 'Check again'."
            )

        self.docker_action_button.setText("Check again")
        self._disconnect_docker_action()
        self._connect_docker_action(self._refresh_docker_state)

    def _on_bring_up_clicked(self) -> None:
        username = self.soulseek_username_field.text().strip()
        password = self.soulseek_password_field.text()

        if not username or not password:
            self.soulseek_status_label.setText(
                "Enter your SoulSeek network username and password."
            )
            return

        if self._docker_state != DockerState.RUNNING:
            self.soulseek_status_label.setText("Docker isn't running yet.")
            return

        if self._library_location_path is None:
            self.soulseek_status_label.setText(
                "No library location — go back and choose one first."
            )
            return

        api_key = generate_api_key()
        data_dir = _slskd_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        library_path = self._library_location_path

        def do_bring_up() -> str:
            result = bring_up_slskd(
                compose_file=str(COMPOSE_FILE_PATH),
                soulseek_username=username,
                soulseek_password=password,
                api_key=api_key,
                slskd_data_dir=str(data_dir),
                library_location_path=library_path,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"docker compose up failed: {result.stderr.strip()}"
                )

            return api_key

        run_worker(
            self.thread_pool,
            do_bring_up,
            button=self.bring_up_button,
            status_label=self.soulseek_status_label,
            on_finished=self._start_health_poll,
        )
        self.soulseek_progress.show()
        self.soulseek_status_label.setText("Starting SoulSeek...")

    def _start_health_poll(self, api_key: str) -> None:
        self._slskd_api_key = api_key
        self._health_poll_elapsed = 0.0
        # Real timestamp this specific bring-up attempt started —
        # check_slskd_health uses it to ignore any stale Error log
        # entry from an earlier attempt (e.g. a mistyped password that
        # was already corrected), so a real reconnect isn't
        # false-flagged as bad credentials forever.
        self._health_poll_started_at = datetime.now(timezone.utc)
        self.soulseek_progress.show()
        self.soulseek_status_label.setText(
            "Waiting for SoulSeek to connect..."
        )

        self._health_poll_timer = QTimer(self)
        self._health_poll_timer.setInterval(HEALTH_POLL_INTERVAL_MS)
        self._health_poll_timer.timeout.connect(
            self._poll_slskd_health_once
        )
        self._health_poll_timer.start()

    def _poll_slskd_health_once(self) -> None:
        self._health_poll_elapsed += HEALTH_POLL_INTERVAL_MS / 1000
        api_key = self._slskd_api_key
        since = self._health_poll_started_at
        assert api_key is not None
        assert since is not None

        run_worker(
            self.thread_pool,
            lambda: check_slskd_health(SLSKD_LOCAL_BASE_URL, api_key, since),
            on_finished=self._handle_health_result,
        )

    def _handle_health_result(self, result: SlskdHealthCheckResult) -> None:
        if result.status == SlskdHealthStatus.HEALTHY:
            self._stop_health_poll()
            self._persist_soulseek_config()
            self.soulseek_status_label.setText("SoulSeek is connected.")
            self._advance_to_dashboard()
            return

        if result.status == SlskdHealthStatus.BAD_CREDENTIALS:
            self._stop_health_poll()
            self.soulseek_status_label.setText(
                f"SoulSeek rejected your credentials: {result.detail}"
            )
            return

        if self._health_poll_elapsed >= HEALTH_POLL_TIMEOUT_SECONDS:
            self._stop_health_poll()
            self.soulseek_status_label.setText(
                "SoulSeek didn't finish connecting within "
                f"{HEALTH_POLL_TIMEOUT_SECONDS:.0f}s. Check your "
                "Docker setup and try again."
            )

    def _stop_health_poll(self) -> None:
        if self._health_poll_timer is not None:
            self._health_poll_timer.stop()
            self._health_poll_timer = None

        self.soulseek_progress.hide()

    def _persist_soulseek_config(self) -> None:
        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(
            current,
            slskd_base_url=SLSKD_LOCAL_BASE_URL,
            slskd_api_key=self._slskd_api_key,
            slskd_download_dir=str(_slskd_data_dir() / "downloads"),
        )
        save_config(updated, config_path)
        self.application._config_store = updated

    def _on_skip_soulseek_clicked(self) -> None:
        self._advance_to_dashboard()

    def _advance_to_dashboard(self) -> None:
        self.close()
        self.on_complete()

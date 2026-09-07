import subprocess
import sys
import webbrowser
from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.docker_setup import (
    DockerState,
    SlskdHealthCheckResult,
    SlskdHealthStatus,
    bring_up_slskd,
    check_slskd_health,
    compose_file_path,
    detect_docker_state,
    generate_api_key,
    slskd_data_dir,
)
from seeker.models.library_location import LibraryLocation
from seeker.spotify.callback_server import DEFAULT_REDIRECT_URI
from seeker.ui import help_text
from seeker.ui.library_location_picker import pick_and_add_library_location
from seeker.ui.workers import run_worker

# Untuned constants, flagged same as every other threshold in this
# codebase. Poll interval matches the ~2s cadence already observed
# against real slskd elsewhere in this project (see CLAUDE.md); 60s is
# a reasonable starting timeout for a fresh `docker compose up` to
# reach a real Soulseek network login.
HEALTH_POLL_INTERVAL_MS = 2_000
HEALTH_POLL_TIMEOUT_SECONDS = 60.0

# Roadmap item 116 (round 8, §6.1.1) — 127.0.0.1, not "localhost".
# Docker's own "127.0.0.1:5030:5030" port binding (docker-compose.yml)
# is IPv4-only; macOS resolves "localhost" to both ::1 and 127.0.0.1,
# and getaddrinfo commonly returns ::1 first, so an httpx request to
# "http://localhost:5030" could try IPv6, get connection refused, and
# only then fall back to IPv4 -- a real per-request delay this sidesteps
# deterministically rather than needing to time a before/after search on
# real hardware.
SLSKD_LOCAL_BASE_URL = "http://127.0.0.1:5030"


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
        # See SettingsWindow's identical fix (CLAUDE.md's broad
        # end-to-end stress test entry) — a parentless top-level
        # QMainWindow's close() only hides it by default, never
        # actually destroys it, unless this is set.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
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
        self.stack.addWidget(self._build_done_page())

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
        dashboard_button.setToolTip(help_text.TOOLTIP_OPEN_SPOTIFY_DASHBOARD)
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
        copy_button.setToolTip(help_text.TOOLTIP_COPY_REDIRECT_URI)
        copy_button.clicked.connect(self._copy_redirect_uri)
        redirect_row.addWidget(copy_button)
        layout.addLayout(redirect_row)
        layout.addWidget(QLabel(
            "Add this exact Redirect URI to your Spotify app's "
            "settings — it must match exactly."
        ))

        self.client_id_field = QLineEdit()
        self.client_id_field.setPlaceholderText("Spotify Client ID")
        self.client_id_field.setToolTip(help_text.TOOLTIP_CLIENT_ID_FIELD)
        self.client_id_field.textChanged.connect(
            self._update_connect_button_state
        )
        # Roadmap item 95 (B1.1) — OnboardingWizard is a QMainWindow,
        # not a QDialog, so Qt's autoDefault/default-button machinery
        # never applies here; Enter had no keyboard path to Connect at
        # all before this. Guarded the same way a click already is
        # (connect_button.isEnabled()) rather than a second, drifting
        # emptiness check — Enter on an empty field must do nothing,
        # same as clicking a disabled button would.
        self.client_id_field.returnPressed.connect(
            self._on_client_id_return_pressed
        )
        layout.addWidget(self.client_id_field)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setToolTip(help_text.TOOLTIP_CONNECT_SPOTIFY)
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

    def _on_client_id_return_pressed(self) -> None:
        if self.connect_button.isEnabled():
            self._on_connect_spotify_clicked()

    def _on_connect_spotify_clicked(self) -> None:
        client_id = self.client_id_field.text().strip()

        # connect_spotify() is genuinely long-running (opens the system
        # browser and waits for the local OAuth callback), hence the
        # worker. Shared with Settings' "Re-authorize" action (Step 8
        # §3) — see application.py.
        run_worker(
            self.thread_pool,
            lambda: self.application.connect_spotify(client_id),
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
        choose_button.setToolTip(help_text.TOOLTIP_CHOOSE_LIBRARY_FOLDER)
        choose_button.clicked.connect(
            self._on_choose_library_folder_clicked
        )
        layout.addWidget(choose_button)

        # Roadmap item 6 §5 — set up a real default destination right
        # here, so a first-time user can never reach the "no
        # destination configured" dead end at all. Both checked by
        # default: this is the common case (someone setting up Seeker
        # for the first time wants downloads to just work).
        self.download_into_library_checkbox = QCheckBox(
            "Download new tracks into this folder"
        )
        self.download_into_library_checkbox.setChecked(True)
        self.download_into_library_checkbox.setToolTip(
            help_text.TOOLTIP_DOWNLOAD_INTO_LIBRARY_CHECKBOX
        )
        self.download_into_library_checkbox.toggled.connect(
            self._on_download_into_library_toggled
        )
        layout.addWidget(self.download_into_library_checkbox)

        self.subfolder_per_playlist_checkbox = QCheckBox(
            "in a subfolder per playlist"
        )
        self.subfolder_per_playlist_checkbox.setChecked(True)
        self.subfolder_per_playlist_checkbox.setToolTip(
            help_text.TOOLTIP_SUBFOLDER_PER_PLAYLIST_CHECKBOX
        )
        layout.addWidget(self.subfolder_per_playlist_checkbox)

        self.library_status_label = QLabel("")
        layout.addWidget(self.library_status_label)

        layout.addStretch()
        return page

    def _on_download_into_library_toggled(self, checked: bool) -> None:
        self.subfolder_per_playlist_checkbox.setVisible(checked)

    def _on_choose_library_folder_clicked(self) -> None:
        pick_and_add_library_location(
            self,
            self.thread_pool,
            self.application,
            status_label=self.library_status_label,
            on_path_picked=self.library_path_label.setText,
            on_finished=self._advance_from_library,
        )

    def _advance_from_library(self, location: LibraryLocation) -> None:
        self._library_location_path = location.path
        self.library_status_label.setText("Library registered.")

        if not self.download_into_library_checkbox.isChecked():
            self._continue_past_library_step()
            return

        # Loaded from the DB via add_location_from_path, so .id is set.
        assert location.id is not None
        subfolder_per_playlist = (
            self.subfolder_per_playlist_checkbox.isChecked()
        )

        run_worker(
            self.thread_pool,
            lambda: self.application.persist_default_destination(
                location.id, subfolder_per_playlist,
            ),
            on_finished=lambda _: self._continue_past_library_step(),
        )

    def _continue_past_library_step(self) -> None:
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

        account_mode_explanation = QLabel(
            help_text.SOULSEEK_ACCOUNT_MODE_EXPLANATION
        )
        account_mode_explanation.setWordWrap(True)
        layout.addWidget(account_mode_explanation)

        # Roadmap item 8 — the protocol itself can't distinguish "wrong
        # password on my own account" from "that username belongs to
        # someone else" (both converge on the identical INVALIDPASS
        # rejection — confirmed live, see docker_setup.py's own
        # BAD_CREDENTIALS_LOG_PATTERNS comment). Asking which one the
        # user is doing is the only way to give useful copy on a
        # rejection.
        self._soulseek_account_mode_group = QButtonGroup(self)
        self.existing_account_radio = QRadioButton(
            "I already have a SoulSeek account"
        )
        self.existing_account_radio.setChecked(True)
        self.existing_account_radio.setToolTip(
            help_text.TOOLTIP_EXISTING_SOULSEEK_ACCOUNT_RADIO
        )
        self._soulseek_account_mode_group.addButton(
            self.existing_account_radio
        )
        layout.addWidget(self.existing_account_radio)

        self.new_account_radio = QRadioButton("Create a new SoulSeek account")
        self.new_account_radio.setToolTip(
            help_text.TOOLTIP_NEW_SOULSEEK_ACCOUNT_RADIO
        )
        self._soulseek_account_mode_group.addButton(self.new_account_radio)
        layout.addWidget(self.new_account_radio)

        self.soulseek_username_field = QLineEdit()
        self.soulseek_username_field.setPlaceholderText(
            "SoulSeek username"
        )
        self.soulseek_username_field.setToolTip(
            help_text.TOOLTIP_SOULSEEK_USERNAME_FIELD
        )
        # Roadmap item 95 (B1.2) — no extra guard needed here:
        # _on_bring_up_clicked already validates non-empty, whitespace,
        # Docker state, and library location, writing a real status
        # message for each — Enter from an empty field gets that same
        # message, not silence.
        self.soulseek_username_field.returnPressed.connect(
            self._on_bring_up_clicked
        )
        layout.addWidget(self.soulseek_username_field)

        self.soulseek_password_field = QLineEdit()
        self.soulseek_password_field.setPlaceholderText(
            "SoulSeek password"
        )
        self.soulseek_password_field.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.soulseek_password_field.setToolTip(
            help_text.TOOLTIP_SOULSEEK_PASSWORD_FIELD
        )
        self.soulseek_password_field.returnPressed.connect(
            self._on_bring_up_clicked
        )
        layout.addWidget(self.soulseek_password_field)

        self.bring_up_button = QPushButton("Set up SoulSeek")
        self.bring_up_button.setToolTip(help_text.TOOLTIP_BRING_UP_SOULSEEK)
        self.bring_up_button.clicked.connect(self._on_bring_up_clicked)
        layout.addWidget(self.bring_up_button)

        self.soulseek_progress = QProgressBar()
        self.soulseek_progress.setRange(0, 0)
        self.soulseek_progress.hide()
        layout.addWidget(self.soulseek_progress)

        self.soulseek_status_label = QLabel("")
        layout.addWidget(self.soulseek_status_label)

        skip_button = QPushButton("Set up later")
        skip_button.setToolTip(help_text.TOOLTIP_SKIP_SOULSEEK)
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
            self.docker_action_button.setToolTip(
                help_text.TOOLTIP_DOWNLOAD_DOCKER
            )
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
                self.docker_action_button.setToolTip(
                    help_text.TOOLTIP_LAUNCH_DOCKER
                )
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
                self.docker_action_button.setToolTip(
                    help_text.TOOLTIP_CHECK_DOCKER_AGAIN
                )
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
        self.docker_action_button.setToolTip(
            help_text.TOOLTIP_CHECK_DOCKER_AGAIN
        )
        self._disconnect_docker_action()
        self._connect_docker_action(self._refresh_docker_state)

    def _on_bring_up_clicked(self) -> None:
        raw_username = self.soulseek_username_field.text()
        password = self.soulseek_password_field.text()

        # Real SoulSeek username character constraints (allowed
        # length, allowed characters) aren't cheaply confirmable here
        # — not guessed at. Only validating what's genuinely certain:
        # non-empty, and no leading/trailing whitespace, which would
        # otherwise be silently stripped somewhere downstream and
        # leave the user unsure which literal string is "the"
        # username they registered.
        if raw_username != raw_username.strip():
            self.soulseek_status_label.setText(
                "Remove the leading or trailing spaces from your "
                "SoulSeek username."
            )
            return

        username = raw_username

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
        data_dir = slskd_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        web_username, web_password = (
            self.application.ensure_slskd_web_credentials()
        )

        library_path = self._library_location_path

        def do_bring_up() -> str:
            result = bring_up_slskd(
                compose_file=str(compose_file_path()),
                soulseek_username=username,
                soulseek_password=password,
                api_key=api_key,
                slskd_data_dir=str(data_dir),
                web_username=web_username,
                web_password=web_password,
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
        # A stale detail from an earlier attempt (e.g. the first
        # rejection this same session) must not linger into whatever
        # this new attempt ends up showing.
        self.soulseek_status_label.setToolTip("")

    def _start_health_poll(self, api_key: str) -> None:
        self._slskd_api_key = api_key
        self._health_poll_elapsed = 0.0
        # Real timestamp this specific bring-up attempt started —
        # check_slskd_health uses it to ignore any stale Error log
        # entry from an earlier attempt (e.g. a mistyped password that
        # was already corrected), so a real reconnect isn't
        # false-flagged as bad credentials forever.
        self._health_poll_started_at = datetime.now(UTC)
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
            self.soulseek_status_label.setToolTip("")
            self._advance_to_done_page()
            return

        if result.status == SlskdHealthStatus.BAD_CREDENTIALS:
            self._stop_health_poll()
            self._handle_bad_credentials(result.detail)
            return

        if result.status == SlskdHealthStatus.KICKED:
            self._stop_health_poll()
            self.soulseek_status_label.setText(
                "Another client is already logged in with this "
                "username."
            )
            self.soulseek_status_label.setToolTip(result.detail or "")
            return

        if self._health_poll_elapsed >= HEALTH_POLL_TIMEOUT_SECONDS:
            self._stop_health_poll()
            self.soulseek_status_label.setText(
                "SoulSeek didn't finish connecting within "
                f"{HEALTH_POLL_TIMEOUT_SECONDS:.0f}s. Check that Docker "
                "is still running, that your SoulSeek username and "
                "password are correct, and that this machine has a "
                "working internet connection, then try again."
            )

    def _handle_bad_credentials(self, detail: str | None) -> None:
        # The protocol itself can't distinguish these two cases (both
        # converge on the identical INVALIDPASS rejection — confirmed
        # live) — the radio pair from the credential form is the only
        # real signal available for which message applies.
        if self.new_account_radio.isChecked():
            username = self.soulseek_username_field.text()
            self.soulseek_status_label.setText(
                f"The username '{username}' is already taken on the "
                f"SoulSeek network. Pick a different one and try again."
            )
            # Keep the password (still probably the one they meant to
            # use going forward) — only the username needs to change.
            self.soulseek_username_field.clear()
            self.soulseek_username_field.setFocus()
        else:
            self.soulseek_status_label.setText(
                "SoulSeek rejected that username and password. Check "
                "the password — usernames are case-sensitive."
            )

        # Never dropped — the real log line stays available on hover,
        # regardless of which branch's copy is shown.
        self.soulseek_status_label.setToolTip(detail or "")

    def _stop_health_poll(self) -> None:
        if self._health_poll_timer is not None:
            self._health_poll_timer.stop()
            self._health_poll_timer = None

        self.soulseek_progress.hide()

    def _persist_soulseek_config(self) -> None:
        assert self._slskd_api_key is not None

        # Form fields are still populated from _on_bring_up_clicked —
        # nothing clears them between requesting the bring-up and the
        # health poll confirming it succeeded.
        self.application.persist_soulseek_config(
            SLSKD_LOCAL_BASE_URL,
            self._slskd_api_key,
            str(slskd_data_dir() / "downloads"),
            self.soulseek_username_field.text().strip(),
            self.soulseek_password_field.text(),
        )

    def _on_skip_soulseek_clicked(self) -> None:
        self._advance_to_done_page()

    def _advance_to_done_page(self) -> None:
        self.stack.setCurrentIndex(3)

    # --- Step 4: done (Task 3's support-the-creator placement) ---------

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        layout.addWidget(QLabel(help_text.DONE_PAGE_TITLE_HTML))
        layout.addWidget(QLabel(help_text.DONE_PAGE_BODY))

        # A single, low-key mention — not on any daily-use screen, per
        # Task 3's own scoping. Real URLs aren't ready yet; see
        # help_text.SUPPORT_LINKS's own placeholder-URL warning.
        support_row = QHBoxLayout()
        support_row.addWidget(QLabel(help_text.DONE_PAGE_SUPPORT_PROMPT))
        for name, url in help_text.SUPPORT_LINKS.items():
            support_button = QPushButton(f"Support on {name}")
            support_button.setToolTip(help_text.TOOLTIP_SUPPORT_LINK)
            support_button.clicked.connect(
                lambda _=False, url=url: webbrowser.open(url)
            )
            support_row.addWidget(support_button)
        layout.addLayout(support_row)

        layout.addStretch()

        self.continue_button = QPushButton(
            help_text.DONE_PAGE_CONTINUE_BUTTON_TEXT
        )
        self.continue_button.clicked.connect(self._finish)
        layout.addWidget(self.continue_button)

        return page

    def _finish(self) -> None:
        self.close()
        self.on_complete()

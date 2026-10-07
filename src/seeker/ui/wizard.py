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
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.models.library_location import LibraryLocation
from seeker.models.slskd_start import SlskdStartResult
from seeker.soulseek.docker_setup import (
    SLSKD_LOCAL_BASE_URL,
    DockerState,
    SlskdHealthCheckResult,
    SlskdHealthStatus,
    check_slskd_health,
    detect_docker_state,
)
from seeker.spotify.callback_server import DEFAULT_REDIRECT_URI
from seeker.ui import help_text, theme
from seeker.ui.library_location_picker import pick_and_add_library_location
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import build_subtitle_label
from seeker.ui.plain_text import PlainLabel, plain_tooltip
from seeker.ui.spotify_authorization import SpotifyAuthorizationWait
from seeker.ui.status_lamp import (
    CUE,
    CUE_WAITING,
    FAULT,
    PLAY,
    STANDBY,
    StatusChip,
)
from seeker.ui.step_indicator import StepIndicator
from seeker.ui.wordmark import Wordmark
from seeker.ui.workers import run_worker

# Untuned constants, flagged same as every other threshold in this
# codebase. Poll interval matches the ~2s cadence already observed
# against real slskd elsewhere in this project; 60s is a reasonable
# starting timeout for a fresh `docker compose up` to reach a real
# Soulseek network login.
HEALTH_POLL_INTERVAL_MS = 2_000
HEALTH_POLL_TIMEOUT_SECONDS = 60.0

# The wizard is one column of reading width, centred in the window.
COLUMN_MAX_WIDTH = 560
_COLUMN_TOP_MARGIN = 48
STEP_NAMES = ("Spotify", "Library", "SoulSeek (optional)")
_SOULSEEK_STEP = 2
_CHECKING_DOCKER = "Checking Docker…"
_SOULSEEK_FAILED = "SoulSeek didn't connect"


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
        # A parentless top-level QMainWindow's close() only hides it by
        # default, never actually destroys it, unless this is set
        # (HISTORY §32).
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.application = application
        self.on_complete = on_complete
        self.thread_pool = QThreadPool()

        self._library_location_path: str | None = None
        self._docker_state: DockerState | None = None
        self._slskd_started: SlskdStartResult | None = None
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
        self.resize(720, 700)

        self.step_indicator = StepIndicator(STEP_NAMES)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_spotify_page())
        self.stack.addWidget(self._build_library_page())
        self.stack.addWidget(self._build_soulseek_page())
        self.stack.addWidget(self._build_done_page())
        self.stack.currentChanged.connect(self._on_step_changed)
        self.setCentralWidget(self._build_column())

        self.stack.setCurrentIndex(self._initial_step())
        self._on_step_changed(self.stack.currentIndex())

        if self.stack.currentIndex() == 2:
            self._refresh_docker_state()

    def _build_column(self) -> QWidget:
        self.column = QWidget()
        self.column.setMaximumWidth(COLUMN_MAX_WIDTH)
        self.column.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        column_layout = QVBoxLayout(self.column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(theme.SPACING_XL)
        column_layout.addWidget(Wordmark())
        column_layout.addWidget(self.step_indicator)
        column_layout.addWidget(self.stack)

        # The stretches share only what the column's maximum leaves.
        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(
            theme.SPACING_XL, _COLUMN_TOP_MARGIN,
            theme.SPACING_XL, theme.SPACING_XL,
        )
        row.addStretch(1)
        row.addWidget(self.column, 100, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        return theme.scrollable(content)

    def _on_step_changed(self, index: int) -> None:
        self.step_indicator.set_current(index)
        # A QStackedWidget is as tall as its tallest page unless the
        # others are Ignored, and a short step should never scroll.
        for page_index in range(self.stack.count()):
            page = self.stack.widget(page_index)
            assert page is not None
            policy = (
                QSizePolicy.Policy.Preferred if page_index == index
                else QSizePolicy.Policy.Ignored
            )
            page.setSizePolicy(policy, policy)

    def _initial_step(self) -> int:
        if not self.application.spotify_configured:
            return 0

        if not self.application.library_service.list_locations():
            return 1

        return 2

    # --- Step 1: Spotify -------------------------------------------

    def _build_spotify_page(self) -> QWidget:
        page, layout = _step_page(
            "Connect Spotify",
            "Seeker syncs your playlists through a Spotify app you "
            "register once.",
        )

        dashboard_button = QPushButton("Open Spotify Developer Dashboard")
        dashboard_button.setToolTip(help_text.TOOLTIP_OPEN_SPOTIFY_DASHBOARD)
        dashboard_button.clicked.connect(
            lambda: webbrowser.open(
                "https://developer.spotify.com/dashboard"
            )
        )

        # Read-only rather than a label, so the URI can be selected as
        # well as copied.
        self.redirect_uri_field = QLineEdit(DEFAULT_REDIRECT_URI)
        self.redirect_uri_field.setReadOnly(True)
        self.redirect_uri_field.setToolTip(help_text.TOOLTIP_COPY_REDIRECT_URI)
        copy_button = QPushButton("Copy")
        copy_button.setToolTip(help_text.TOOLTIP_COPY_REDIRECT_URI)
        copy_button.clicked.connect(self._copy_redirect_uri)
        redirect_row = QHBoxLayout()
        redirect_row.addWidget(self.redirect_uri_field, 1)
        redirect_row.addWidget(copy_button)

        self.client_id_field = QLineEdit()
        self.client_id_field.setPlaceholderText("Spotify Client ID")
        self.client_id_field.setToolTip(help_text.TOOLTIP_CLIENT_ID_FIELD)
        self.client_id_field.textChanged.connect(
            self._update_connect_button_state
        )
        # OnboardingWizard is a QMainWindow, not a QDialog, so Qt's
        # autoDefault/default-button machinery never applies here; this
        # is Enter's only keyboard path to Connect (HISTORY §95).
        # Guarded the same way a click already is
        # (connect_button.isEnabled()) rather than a second, drifting
        # emptiness check — Enter on an empty field must do nothing,
        # same as clicking a disabled button would.
        self.client_id_field.returnPressed.connect(
            self._on_client_id_return_pressed
        )

        steps = QGridLayout()
        steps.setHorizontalSpacing(theme.SPACING_MD)
        steps.setVerticalSpacing(theme.SPACING_LG)
        steps.setColumnStretch(1, 1)
        instructions: tuple[tuple[str, QWidget | QLayout], ...] = (
            (
                "Create an app on the Spotify Developer Dashboard.",
                theme.action_row(dashboard_button),
            ),
            (
                "In the app's settings, add this Redirect URI. It "
                "must match exactly, port included.",
                redirect_row,
            ),
            (
                "Copy the app's Client ID and paste it here. No "
                "client secret is needed.",
                self.client_id_field,
            ),
        )
        for row, (instruction, control) in enumerate(instructions):
            number = PlainLabel(str(row + 1))
            # QLabel#stepNumber in theme.py.
            number.setObjectName("stepNumber")
            steps.addWidget(number, row, 0, Qt.AlignmentFlag.AlignTop)
            steps.addLayout(_instruction(instruction, control), row, 1)
        layout.addLayout(steps)
        layout.addSpacing(theme.SPACING_XS)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("variant", "primary")
        self.connect_button.setToolTip(help_text.TOOLTIP_CONNECT_SPOTIFY)
        self.connect_button.setEnabled(False)
        self.connect_button.clicked.connect(
            self._on_connect_spotify_clicked
        )
        layout.addLayout(theme.action_row(self.connect_button))

        self.spotify_status_label = PlainLabel("")
        self.spotify_status_label.setWordWrap(True)
        layout.addWidget(self.spotify_status_label)

        self.spotify_authorization_wait = SpotifyAuthorizationWait(
            self.application,
            self.thread_pool,
            self.connect_button,
            self.spotify_status_label,
            trigger_enabled=self._has_client_id,
        )
        layout.addWidget(self.spotify_authorization_wait)

        layout.addStretch()
        return page

    def _copy_redirect_uri(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(DEFAULT_REDIRECT_URI)

    def _has_client_id(self) -> bool:
        return bool(self.client_id_field.text().strip())

    def _update_connect_button_state(self, _text: str) -> None:
        if not self.spotify_authorization_wait.is_waiting:
            self.connect_button.setEnabled(self._has_client_id())

    def _on_client_id_return_pressed(self) -> None:
        if self.connect_button.isEnabled():
            self._on_connect_spotify_clicked()

    def _on_connect_spotify_clicked(self) -> None:
        self.spotify_authorization_wait.start(
            self.client_id_field.text().strip(),
            on_connected=self._advance_from_spotify,
        )

    def _advance_from_spotify(self) -> None:
        self.spotify_status_label.setText("Connected.")
        self.stack.setCurrentIndex(1)

    # --- Step 2: library location ------------------------------------

    def _build_library_page(self) -> QWidget:
        page, layout = _step_page(
            "Choose your music library",
            "Seeker scans this folder for audio files to match "
            "against your Spotify tracks.",
        )

        self.library_path_label = PlainLabel("No folder selected.")
        layout.addWidget(self.library_path_label)

        # Set up a real default destination right here, so a first-time
        # user can never reach the "no destination configured" dead end
        # at all. Both checked by default: this is the common case
        # (someone setting up Seeker for the first time wants downloads
        # to just work; HISTORY §50).
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
        # Indented under the option it refines.
        subfolder_row = QHBoxLayout()
        subfolder_row.addSpacing(theme.SPACING_XL)
        subfolder_row.addWidget(self.subfolder_per_playlist_checkbox)
        layout.addLayout(subfolder_row)

        # Last, because choosing the folder finishes the step: the
        # options above apply to it.
        choose_button = QPushButton("Choose Folder...")
        choose_button.setProperty("variant", "primary")
        choose_button.setToolTip(help_text.TOOLTIP_CHOOSE_LIBRARY_FOLDER)
        choose_button.clicked.connect(
            self._on_choose_library_folder_clicked
        )
        layout.addSpacing(theme.SPACING_XS)
        layout.addLayout(theme.action_row(choose_button))

        self.library_status_label = PlainLabel("")
        self.library_status_label.setWordWrap(True)
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
        page, layout = _step_page(
            "Set up SoulSeek",
            "Seeker searches SoulSeek for tracks missing from your "
            "local library. This step is optional — SoulSeek-dependent "
            "actions stay disabled until it's set up.",
        )

        self.docker_chip = StatusChip(CUE, _CHECKING_DOCKER)
        self.slskd_chip = StatusChip(STANDBY, "SoulSeek isn't set up")
        chips = QHBoxLayout()
        chips.setSpacing(theme.SPACING_SM)
        chips.addWidget(self.docker_chip)
        chips.addWidget(self.slskd_chip)
        chips.addStretch()
        layout.addLayout(chips)

        self.docker_action_button = QPushButton("")
        self.docker_action_button.hide()
        layout.addLayout(theme.action_row(self.docker_action_button))

        account_header = PlainLabel("Your SoulSeek account")
        # QLabel#sectionHeaderLabel in theme.py.
        account_header.setObjectName("sectionHeaderLabel")
        layout.addSpacing(theme.SPACING_SM)
        layout.addWidget(account_header)

        account_mode_explanation = PlainLabel(
            help_text.SOULSEEK_ACCOUNT_MODE_EXPLANATION
        )
        account_mode_explanation.setProperty("badge", "muted")
        account_mode_explanation.setWordWrap(True)
        layout.addWidget(account_mode_explanation)

        # The protocol itself can't distinguish "wrong password on my
        # own account" from "that username belongs to someone else"
        # (both converge on the identical INVALIDPASS rejection —
        # confirmed live, see soulseek/docker_setup.py's own
        # BAD_CREDENTIALS_LOG_PATTERNS comment). Asking which one the
        # user is doing is the only way to give useful copy on a
        # rejection (HISTORY §52).
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
        # No extra guard needed here: _on_bring_up_clicked already
        # validates non-empty, whitespace, Docker state, and library
        # location, writing a real status message for each — Enter from
        # an empty field gets that same message, not silence.
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
        self.bring_up_button.setProperty("variant", "primary")
        self.bring_up_button.setToolTip(help_text.TOOLTIP_BRING_UP_SOULSEEK)
        self.bring_up_button.clicked.connect(self._on_bring_up_clicked)
        skip_button = QPushButton("Set up later")
        skip_button.setToolTip(help_text.TOOLTIP_SKIP_SOULSEEK)
        skip_button.clicked.connect(self._on_skip_soulseek_clicked)
        layout.addSpacing(theme.SPACING_XS)
        layout.addLayout(theme.action_row(self.bring_up_button, skip_button))

        self.soulseek_progress = QProgressBar()
        self.soulseek_progress.setRange(0, 0)
        self.soulseek_progress.hide()
        layout.addWidget(self.soulseek_progress)

        # Progress only; every outcome goes on the notice below it.
        self.soulseek_status_label = PlainLabel("")
        self.soulseek_status_label.setWordWrap(True)
        layout.addWidget(self.soulseek_status_label)

        self.soulseek_notice = InlineNotice()
        layout.addWidget(self.soulseek_notice)

        layout.addStretch()
        return page

    def _refresh_docker_state(self) -> None:
        self.docker_chip.set_state(CUE, _CHECKING_DOCKER)
        run_worker(
            self.thread_pool,
            detect_docker_state,
            on_finished=self._render_docker_state,
        )

    def _render_docker_state(self, state: DockerState) -> None:
        self._docker_state = state
        self._disconnect_docker_action()

        if state == DockerState.NOT_INSTALLED:
            self.docker_chip.set_state(FAULT, "Docker isn't installed")
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
            self.docker_chip.set_state(CUE_WAITING, "Docker isn't running")
            if sys.platform in ("darwin", "win32"):
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
                self._show_soulseek_outcome(
                    "Start the Docker daemon with your service manager, "
                    "e.g. 'sudo systemctl start docker', then check "
                    "again.",
                    kind="warning",
                )
                self.docker_action_button.setText("Check again")
                self.docker_action_button.setToolTip(
                    help_text.TOOLTIP_CHECK_DOCKER_AGAIN
                )
                self._connect_docker_action(self._refresh_docker_state)
            self.docker_action_button.show()
        else:
            self.docker_chip.set_state(PLAY, "Docker is running")
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
            self._show_soulseek_outcome(
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
        # Only this attempt's outcome may show.
        self.soulseek_notice.dismiss()
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
            self._show_soulseek_outcome(
                "Remove the leading or trailing spaces from your "
                "SoulSeek username.",
                kind="warning",
            )
            return

        username = raw_username

        if not username or not password:
            self._show_soulseek_outcome(
                "Enter your SoulSeek network username and password.",
                kind="warning",
            )
            return

        if self._docker_state != DockerState.RUNNING:
            self._show_soulseek_outcome(
                "Docker isn't running yet.", kind="warning",
            )
            return

        if self._library_location_path is None:
            self._show_soulseek_outcome(
                "No library location — go back and choose one first.",
                kind="warning",
            )
            return

        library_path = self._library_location_path

        def do_bring_up() -> SlskdStartResult:
            # Saved only once the health poll confirms the login.
            return self.application.start_slskd(
                username, password, library_path, persist=False,
            )

        run_worker(
            self.thread_pool,
            do_bring_up,
            button=self.bring_up_button,
            on_finished=self._start_health_poll,
            on_error=self._on_bring_up_failed,
        )
        self.slskd_chip.set_state(CUE, "Starting SoulSeek…")
        self.soulseek_progress.show()
        self.soulseek_status_label.setText("Starting SoulSeek...")

    def _on_bring_up_failed(self, message: str) -> None:
        self.soulseek_progress.hide()
        self.slskd_chip.set_state(FAULT, _SOULSEEK_FAILED)
        self._show_soulseek_outcome(message)

    def _show_soulseek_outcome(
            self,
            text: str,
            kind: str = "error",
            detail: str | None = None,
    ) -> None:
        """Ends the step's progress line. `detail`, the raw log line
        behind a rejection, is never dropped: it shows on hover."""
        self.soulseek_status_label.setText("")
        self.soulseek_notice.show_message(text, kind=kind)
        self.soulseek_notice.setToolTip(plain_tooltip(detail or ""))

    def _start_health_poll(self, started: SlskdStartResult) -> None:
        self._slskd_started = started
        self._health_poll_elapsed = 0.0
        # Real timestamp this specific bring-up attempt started —
        # check_slskd_health uses it to ignore any stale Error log
        # entry from an earlier attempt (e.g. a mistyped password that
        # was already corrected), so a real reconnect isn't
        # false-flagged as bad credentials forever.
        self._health_poll_started_at = datetime.now(UTC)
        self.soulseek_progress.show()
        self.slskd_chip.set_state(CUE, "Connecting to SoulSeek…")
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
        assert self._slskd_started is not None
        api_key = self._slskd_started.api_key
        since = self._health_poll_started_at
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
            self.slskd_chip.set_state(PLAY, "SoulSeek is connected")
            self.soulseek_status_label.setText("")
            self._advance_to_done_page()
            return

        if result.status == SlskdHealthStatus.BAD_CREDENTIALS:
            self._stop_health_poll()
            self.slskd_chip.set_state(FAULT, _SOULSEEK_FAILED)
            self._handle_bad_credentials(result.detail)
            return

        if result.status == SlskdHealthStatus.KICKED:
            self._stop_health_poll()
            self.slskd_chip.set_state(FAULT, _SOULSEEK_FAILED)
            self._show_soulseek_outcome(
                "Another client is already logged in with this "
                "username.",
                detail=result.detail,
            )
            return

        if self._health_poll_elapsed >= HEALTH_POLL_TIMEOUT_SECONDS:
            self._stop_health_poll()
            self.slskd_chip.set_state(FAULT, _SOULSEEK_FAILED)
            self._show_soulseek_outcome(
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
            self._show_soulseek_outcome(
                f"The username '{username}' is already taken on the "
                f"SoulSeek network. Pick a different one and try again.",
                detail=detail,
            )
            # Keep the password (still probably the one they meant to
            # use going forward) — only the username needs to change.
            self.soulseek_username_field.clear()
            self.soulseek_username_field.setFocus()
        else:
            self._show_soulseek_outcome(
                "SoulSeek rejected that username and password. Check "
                "the password — usernames are case-sensitive.",
                detail=detail,
            )

    def _stop_health_poll(self) -> None:
        if self._health_poll_timer is not None:
            self._health_poll_timer.stop()
            self._health_poll_timer = None

        self.soulseek_progress.hide()

    def _persist_soulseek_config(self) -> None:
        started = self._slskd_started
        assert started is not None

        # Form fields are still populated from _on_bring_up_clicked —
        # nothing clears them between requesting the bring-up and the
        # health poll confirming it succeeded.
        self.application.persist_soulseek_config(
            SLSKD_LOCAL_BASE_URL,
            started.api_key,
            started.download_dir,
            self.soulseek_username_field.text().strip(),
            self.soulseek_password_field.text(),
        )

    def _on_skip_soulseek_clicked(self) -> None:
        self.step_indicator.mark_skipped(_SOULSEEK_STEP)
        self._advance_to_done_page()

    def _advance_to_done_page(self) -> None:
        self.stack.setCurrentIndex(3)

    # --- Step 4: done -----------------------------------------------

    def _build_done_page(self) -> QWidget:
        page, layout = _step_page(
            help_text.DONE_PAGE_TITLE, help_text.DONE_PAGE_BODY,
        )

        self.continue_button = QPushButton(
            help_text.DONE_PAGE_CONTINUE_BUTTON_TEXT
        )
        self.continue_button.setProperty("variant", "primary")
        self.continue_button.clicked.connect(self._finish)
        layout.addLayout(theme.action_row(self.continue_button))

        layout.addStretch()
        return page

    def _finish(self) -> None:
        self.close()
        self.on_complete()


def _step_page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    """One step's page, headed as a shell page is: its title in the
    page-title role, its subtitle muted beneath it."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACING_MD)

    header = QVBoxLayout()
    header.setSpacing(theme.SPACING_XS)
    title_label = PlainLabel(title)
    # QLabel#pageTitleLabel in theme.py.
    title_label.setObjectName("pageTitleLabel")
    header.addWidget(title_label)
    header.addWidget(build_subtitle_label(subtitle))
    layout.addLayout(header)
    layout.addSpacing(theme.SPACING_XS)
    return page, layout


def _instruction(text: str, control: QWidget | QLayout) -> QVBoxLayout:
    """One numbered step's sentence with the control it asks for."""
    layout = QVBoxLayout()
    layout.setSpacing(theme.SPACING_SM)
    label = PlainLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    if isinstance(control, QWidget):
        layout.addWidget(control)
    else:
        layout.addLayout(control)
    return layout

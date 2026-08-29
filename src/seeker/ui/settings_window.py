from dataclasses import replace
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.config_store import load_config, resolve_config_path, save_config
from seeker.docker_setup import (
    SlskdHealthCheckResult,
    SlskdHealthStatus,
    bring_up_slskd,
    check_slskd_health,
    compose_file_path,
    generate_api_key,
    slskd_data_dir,
)
from seeker.matching import AUTO_MATCH_THRESHOLD, NEEDS_REVIEW_THRESHOLD
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.ui.library_location_picker import pick_and_add_library_location
from seeker.ui.wizard import SLSKD_LOCAL_BASE_URL
from seeker.ui.workers import run_worker


# A one-off, on-demand check, not a poll loop tracking a specific
# bring-up attempt the way the wizard's health poll does — "now" as
# `since` means any already-existing bad-credential log entry is
# excluded, so a currently-broken connection reports NOT_READY rather
# than a stale BAD_CREDENTIALS diagnosis. Safe default for "is this
# working right now", not a redo of the wizard's own attempt-scoped
# diagnosis.
def _test_connection_since() -> datetime:
    return datetime.now(timezone.utc)


class SettingsWindow(QMainWindow):
    def __init__(self, application: Application):
        super().__init__()
        # Real, confirmed-live leak fix (broad end-to-end stress test,
        # see CLAUDE.md): a top-level QMainWindow with no parent isn't
        # actually destroyed by close() by default — close() only
        # hides it. Repeatedly opening and closing Settings (a
        # completely ordinary real usage pattern) leaked ~2MB of real
        # RSS per open/close cycle, confirmed via a real, isolated
        # repro (20 cycles, explicit gc.collect() between each,
        # objects tracked by gc.get_objects() still climbing —
        # genuinely unreachable-but-uncollected garbage, not just GC
        # timing). WA_DeleteOnClose makes close() actually schedule
        # real deletion (deleteLater()) of this window and everything
        # it owns — confirmed to cut the leak by ~8x in the same repro.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.application = application
        self.thread_pool = QThreadPool()
        self._locations_by_name: dict[str, LibraryLocation] = {}
        self._playlists_by_name: dict[str, Playlist] = {}
        self._api_key_visible = False

        self.setWindowTitle("Seeker Settings")
        self.resize(700, 500)

        tabs = QTabWidget()
        tabs.addTab(self._build_locations_tab(), "Library Locations")
        tabs.addTab(self._build_destinations_tab(), "Playlist Destinations")
        tabs.addTab(self._build_connection_tab(), "Connection")
        tabs.addTab(self._build_thresholds_tab(), "Thresholds")
        self.setCentralWidget(tabs)

        self._refresh_locations()
        self._refresh_destinations()
        self._refresh_connection_display()

    # --- Library locations (§1) --------------------------------------

    def _build_locations_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.locations_table = QTableWidget(0, 4)
        self.locations_table.setHorizontalHeaderLabels(
            ["Name", "Path", "Reachable", "Actions"]
        )
        self.locations_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.locations_table)

        add_row = QHBoxLayout()
        self.new_location_name_field = QLineEdit()
        self.new_location_name_field.setPlaceholderText("Location name")
        add_row.addWidget(self.new_location_name_field)

        self.add_location_button = QPushButton("Choose Folder && Add")
        self.add_location_button.clicked.connect(
            self._on_add_location_clicked
        )
        add_row.addWidget(self.add_location_button)
        layout.addLayout(add_row)

        self.locations_status_label = QLabel("")
        layout.addWidget(self.locations_status_label)

        layout.addStretch()
        return tab

    def _refresh_locations(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.list_locations,
            on_finished=self._render_locations,
        )

    def _render_locations(
            self,
            locations: list[tuple[LibraryLocation, bool]],
    ) -> None:
        self._locations_by_name = {
            location.name: location for location, _ in locations
        }

        self.locations_table.setRowCount(len(locations))

        for row, (location, reachable) in enumerate(locations):
            self.locations_table.setItem(
                row, 0, QTableWidgetItem(location.name),
            )
            self.locations_table.setItem(
                row, 1, QTableWidgetItem(location.path),
            )
            self.locations_table.setItem(
                row, 2, QTableWidgetItem("Yes" if reachable else "No"),
            )

            remove_button = QPushButton("Remove")
            name = location.name
            remove_button.clicked.connect(
                lambda _=False, name=name: self._on_remove_location_clicked(
                    name
                )
            )
            self.locations_table.setCellWidget(row, 3, remove_button)

    def _on_add_location_clicked(self) -> None:
        name = self.new_location_name_field.text().strip()

        if not name:
            self.locations_status_label.setText(
                "Enter a name for this location first."
            )
            return

        pick_and_add_library_location(
            self,
            self.thread_pool,
            self.application,
            name,
            button=self.add_location_button,
            status_label=self.locations_status_label,
            on_finished=lambda _: self._on_location_added(),
        )

    def _on_location_added(self) -> None:
        self.new_location_name_field.clear()
        self._refresh_locations()
        # A new location changes what's available to pick as a
        # playlist destination too.
        self._refresh_destinations()

    def _on_remove_location_clicked(self, name: str) -> None:
        # No confirmation prompt — matches `seeker library remove`,
        # which has none either (checked before building this; adding
        # one here would be a heavier gate than the CLI's own
        # established design calls for).
        run_worker(
            self.thread_pool,
            lambda: self.application.library_service.remove_location(name),
            status_label=self.locations_status_label,
            on_finished=lambda _: self._on_location_added(),
        )

    # --- Playlist destinations (§2) -----------------------------------

    def _build_destinations_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)

        self.destinations_playlist_list = QListWidget()
        self.destinations_playlist_list.currentItemChanged.connect(
            self._on_destination_playlist_selected
        )
        layout.addWidget(self.destinations_playlist_list, 1)

        right = QVBoxLayout()

        form = QFormLayout()
        self.destination_location_combo = QComboBox()
        form.addRow("Library location:", self.destination_location_combo)

        self.destination_subfolder_field = QLineEdit()
        self.destination_subfolder_field.setPlaceholderText(
            "Optional subfolder"
        )
        form.addRow("Subfolder:", self.destination_subfolder_field)
        right.addLayout(form)

        self.save_destination_button = QPushButton("Save destination")
        self.save_destination_button.clicked.connect(
            self._on_save_destination_clicked
        )
        right.addWidget(self.save_destination_button)

        self.destinations_status_label = QLabel("")
        right.addWidget(self.destinations_status_label)

        right.addStretch()
        layout.addLayout(right, 1)

        return tab

    def _refresh_destinations(self) -> None:
        def fetch() -> tuple[
            list[Playlist], list[tuple[LibraryLocation, bool]]
        ]:
            return (
                self.application.sync_service.list_playlists(),
                self.application.library_service.list_locations(),
            )

        run_worker(
            self.thread_pool,
            fetch,
            on_finished=self._render_destinations,
        )

    def _render_destinations(
            self,
            data: tuple[list[Playlist], list[tuple[LibraryLocation, bool]]],
    ) -> None:
        playlists, locations = data
        self._playlists_by_name = {
            playlist.name: playlist for playlist in playlists
        }

        self.destination_location_combo.clear()
        self.destination_location_combo.addItem("(none)", None)
        for location, _ in locations:
            self.destination_location_combo.addItem(
                location.name, location.name
            )

        self.destinations_playlist_list.clear()
        for playlist in playlists:
            self.destinations_playlist_list.addItem(playlist.name)

    def _on_destination_playlist_selected(
            self,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return

        playlist = self._playlists_by_name.get(current.text())

        if playlist is None:
            return

        location = None
        if playlist.download_location_id is not None:
            location = next(
                (
                    loc
                    for loc in self._locations_by_name.values()
                    if loc.id == playlist.download_location_id
                ),
                None,
            )

        combo_index = (
            self.destination_location_combo.findData(location.name)
            if location is not None
            else 0
        )
        self.destination_location_combo.setCurrentIndex(max(combo_index, 0))
        self.destination_subfolder_field.setText(
            playlist.download_subfolder or ""
        )

    def _on_save_destination_clicked(self) -> None:
        current_item = self.destinations_playlist_list.currentItem()

        if current_item is None:
            self.destinations_status_label.setText(
                "Select a playlist first."
            )
            return

        location_name = self.destination_location_combo.currentData()

        if location_name is None:
            self.destinations_status_label.setText(
                "Select a library location first."
            )
            return

        playlist_name = current_item.text()
        subfolder = self.destination_subfolder_field.text().strip() or None

        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.set_destination(
                playlist_name, location_name, subfolder,
            ),
            button=self.save_destination_button,
            status_label=self.destinations_status_label,
            on_finished=lambda _: self.destinations_status_label.setText(
                "Destination saved."
            ),
        )

    # --- Connection management (§3) ------------------------------------

    def _build_connection_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        spotify_group = QGroupBox("Spotify")
        spotify_form = QFormLayout(spotify_group)

        self.spotify_client_id_field = QLineEdit()
        # Not actually secret — PKCE has no client secret component —
        # fine to display and edit in plain text.
        spotify_form.addRow("Client ID:", self.spotify_client_id_field)

        self.reauthorize_spotify_button = QPushButton("Re-authorize")
        self.reauthorize_spotify_button.clicked.connect(
            self._on_reauthorize_spotify_clicked
        )
        spotify_form.addRow("", self.reauthorize_spotify_button)

        self.spotify_status_label = QLabel("")
        spotify_form.addRow("", self.spotify_status_label)

        layout.addWidget(spotify_group)

        soulseek_group = QGroupBox("SoulSeek")
        soulseek_form = QFormLayout(soulseek_group)

        self.soulseek_username_display = QLabel("Not configured")
        soulseek_form.addRow("Username:", self.soulseek_username_display)

        self.soulseek_password_display = QLabel("Not configured")
        soulseek_form.addRow("Password:", self.soulseek_password_display)

        api_key_row = QHBoxLayout()
        self.soulseek_api_key_display = QLabel("Not configured")
        api_key_row.addWidget(self.soulseek_api_key_display)
        self.reveal_api_key_button = QPushButton("Show")
        self.reveal_api_key_button.clicked.connect(
            self._on_toggle_api_key_visibility
        )
        api_key_row.addWidget(self.reveal_api_key_button)
        soulseek_form.addRow("API key:", api_key_row)

        self.test_connection_button = QPushButton("Test connection")
        self.test_connection_button.clicked.connect(
            self._on_test_connection_clicked
        )
        soulseek_form.addRow("", self.test_connection_button)

        self.test_connection_status_label = QLabel("")
        soulseek_form.addRow("", self.test_connection_status_label)

        soulseek_form.addRow(QLabel("Update credentials:"))

        self.new_soulseek_username_field = QLineEdit()
        self.new_soulseek_username_field.setPlaceholderText(
            "SoulSeek username"
        )
        soulseek_form.addRow(
            "New username:", self.new_soulseek_username_field
        )

        self.new_soulseek_password_field = QLineEdit()
        self.new_soulseek_password_field.setPlaceholderText(
            "SoulSeek password"
        )
        self.new_soulseek_password_field.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        soulseek_form.addRow(
            "New password:", self.new_soulseek_password_field
        )

        self.update_credentials_button = QPushButton(
            "Update SoulSeek credentials"
        )
        self.update_credentials_button.clicked.connect(
            self._on_update_credentials_clicked
        )
        soulseek_form.addRow("", self.update_credentials_button)

        self.update_credentials_status_label = QLabel("")
        soulseek_form.addRow("", self.update_credentials_status_label)

        layout.addWidget(soulseek_group)
        layout.addStretch()
        return tab

    def _refresh_connection_display(self) -> None:
        config = self.application._config_store

        self.spotify_client_id_field.setText(config.spotify_client_id or "")

        self.soulseek_username_display.setText(
            config.slskd_username or "Not configured"
        )
        self.soulseek_password_display.setText(
            "••••••••" if config.slskd_password else "Not configured"
        )
        self._render_api_key_display()

    def _render_api_key_display(self) -> None:
        config = self.application._config_store

        if not config.slskd_api_key:
            self.soulseek_api_key_display.setText("Not configured")
            self.reveal_api_key_button.hide()
            return

        self.reveal_api_key_button.show()

        if self._api_key_visible:
            self.soulseek_api_key_display.setText(config.slskd_api_key)
            self.reveal_api_key_button.setText("Hide")
        else:
            self.soulseek_api_key_display.setText("••••••••")
            self.reveal_api_key_button.setText("Show")

    def _on_toggle_api_key_visibility(self) -> None:
        self._api_key_visible = not self._api_key_visible
        self._render_api_key_display()

    def _on_reauthorize_spotify_clicked(self) -> None:
        client_id = self.spotify_client_id_field.text().strip()

        if not client_id:
            self.spotify_status_label.setText("Enter a Client ID first.")
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.connect_spotify(
                client_id, force_reauthorize=True,
            ),
            button=self.reauthorize_spotify_button,
            status_label=self.spotify_status_label,
            on_finished=lambda _: self.spotify_status_label.setText(
                "Re-authorized."
            ),
        )

    def _on_test_connection_clicked(self) -> None:
        base_url = self.application._slskd_base_url
        api_key = self.application._slskd_api_key

        if not base_url or not api_key:
            self.test_connection_status_label.setText(
                "SoulSeek isn't configured yet."
            )
            return

        run_worker(
            self.thread_pool,
            lambda: check_slskd_health(
                base_url, api_key, _test_connection_since(),
            ),
            button=self.test_connection_button,
            on_finished=self._render_test_connection_result,
        )

    def _render_test_connection_result(
            self,
            result: SlskdHealthCheckResult,
    ) -> None:
        if result.status == SlskdHealthStatus.HEALTHY:
            self.test_connection_status_label.setText("Connected.")
        elif result.status == SlskdHealthStatus.BAD_CREDENTIALS:
            self.test_connection_status_label.setText(
                f"Rejected: {result.detail}"
            )
        else:
            self.test_connection_status_label.setText(
                "Not connected right now."
            )

    def _on_update_credentials_clicked(self) -> None:
        username = self.new_soulseek_username_field.text().strip()
        password = self.new_soulseek_password_field.text()

        if not username or not password:
            self.update_credentials_status_label.setText(
                "Enter both a username and password."
            )
            return

        locations = list(self._locations_by_name.values())

        if not locations:
            self.update_credentials_status_label.setText(
                "Register a library location before setting up SoulSeek."
            )
            return

        # Reuses whichever location is already shared with slskd —
        # same single-location assumption the onboarding wizard itself
        # makes; this project doesn't yet support choosing a different
        # share path from Settings.
        library_location_path = locations[0].path

        api_key = generate_api_key()
        data_dir = slskd_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)

        def do_update() -> None:
            result = bring_up_slskd(
                compose_file=str(compose_file_path()),
                soulseek_username=username,
                soulseek_password=password,
                api_key=api_key,
                slskd_data_dir=str(data_dir),
                library_location_path=library_location_path,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"docker compose up failed: {result.stderr.strip()}"
                )

            self.application.persist_soulseek_config(
                SLSKD_LOCAL_BASE_URL,
                api_key,
                str(data_dir / "downloads"),
                username,
                password,
            )

        run_worker(
            self.thread_pool,
            do_update,
            button=self.update_credentials_button,
            status_label=self.update_credentials_status_label,
            on_finished=lambda _: self._on_credentials_updated(),
        )
        self.update_credentials_status_label.setText(
            "Recreating SoulSeek container..."
        )

    def _on_credentials_updated(self) -> None:
        self.new_soulseek_username_field.clear()
        self.new_soulseek_password_field.clear()
        self._refresh_connection_display()
        self.update_credentials_status_label.setText(
            "Credentials updated. Container recreated with new "
            "credentials — use Test connection to confirm."
        )

    # --- Thresholds (§4) -------------------------------------------

    def _build_thresholds_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel(
            "Controls when a matched track is auto-accepted vs. "
            "surfaced for review vs. treated as no match at all."
        ))

        form = QFormLayout()

        self.auto_match_threshold_field = QLineEdit()
        form.addRow(
            "Auto-match threshold:", self.auto_match_threshold_field
        )

        self.needs_review_threshold_field = QLineEdit()
        form.addRow(
            "Needs-review threshold:", self.needs_review_threshold_field
        )

        layout.addLayout(form)

        self.save_thresholds_button = QPushButton("Save thresholds")
        self.save_thresholds_button.clicked.connect(
            self._on_save_thresholds_clicked
        )
        layout.addWidget(self.save_thresholds_button)

        self.thresholds_status_label = QLabel("")
        layout.addWidget(self.thresholds_status_label)

        layout.addStretch()

        self._load_threshold_fields()

        return tab

    def _load_threshold_fields(self) -> None:
        config = self.application._config_store

        auto_threshold = config.auto_match_threshold or AUTO_MATCH_THRESHOLD
        needs_review_threshold = (
            config.needs_review_threshold or NEEDS_REVIEW_THRESHOLD
        )

        self.auto_match_threshold_field.setText(str(auto_threshold))
        self.needs_review_threshold_field.setText(
            str(needs_review_threshold)
        )

    def _on_save_thresholds_clicked(self) -> None:
        auto_text = self.auto_match_threshold_field.text().strip()
        needs_review_text = self.needs_review_threshold_field.text().strip()

        try:
            auto_threshold = float(auto_text)
            needs_review_threshold = float(needs_review_text)
        except ValueError:
            self.thresholds_status_label.setText(
                "Both thresholds must be numbers."
            )
            return

        # A real logic bug, not just a UX nicety — an inverted or
        # collapsed band would silently change how every future match
        # gets classified (see matching.py's own threshold-ordering
        # comment).
        if needs_review_threshold >= auto_threshold:
            self.thresholds_status_label.setText(
                "The needs-review threshold must be less than the "
                "auto-match threshold."
            )
            return

        config_path = resolve_config_path()
        current = load_config(config_path)
        updated = replace(
            current,
            auto_match_threshold=auto_threshold,
            needs_review_threshold=needs_review_threshold,
        )
        save_config(updated, config_path)
        self.application._config_store = updated

        self.thresholds_status_label.setText(
            "Saved. Takes effect on the next match/download run."
        )

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
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
    SlskdWebLoginStatus,
    bring_up_slskd,
    check_slskd_health,
    check_slskd_web_login,
    compose_file_path,
    generate_api_key,
    is_non_loopback_http_url,
    slskd_data_dir,
)
from seeker.matching import AUTO_MATCH_THRESHOLD, NEEDS_REVIEW_THRESHOLD
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.ui import help_text, theme
from seeker.ui.library_location_picker import pick_and_add_library_location
from seeker.ui.notice import InlineNotice
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
    return datetime.now(UTC)


SETTINGS_TAB_LOCATIONS = "Library Locations"
SETTINGS_TAB_DESTINATIONS = "Playlist Destinations"
SETTINGS_TAB_CONNECTION = "Connection"
SETTINGS_TAB_THRESHOLDS = "Thresholds"


class SettingsPage(QWidget):
    """An in-window Settings page (roadmap item 56 Phase 3) — was a
    separate top-level `SettingsWindow(QMainWindow)` (item 48's
    deliberate choice at the time). Reversed here: in fullscreen, a
    second window reads as a dead end with no way back to the shell.
    Hosted in MainWindow's own QStackedWidget like every other page, via
    `_build_page()` — its own subtitle label (below) is gone in favor of
    that helper's, which fixed a real misprinted-looking header (item
    56 Phase 3 §3.2: the fix IS routing through `_build_page`'s standard
    margins, not a one-off tweak). No `WA_DeleteOnClose` handling
    needed any more — this widget is never a top-level window, so the
    leak that attribute existed to fix (item 32) doesn't apply here.
    """

    def __init__(
            self,
            application: Application,
            initial_tab: str | None = None,
            on_about_requested: Callable[[], None] | None = None,
            on_theme_mode_changed: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.application = application
        self.thread_pool = QThreadPool()
        self._locations_by_name: dict[str, LibraryLocation] = {}
        self._playlists_by_name: dict[str, Playlist] = {}
        self._api_key_visible = False
        self._web_password_visible = False
        # S1.2 — whether the generated slskd web UI login is actually
        # the one the container will accept right now (it may not be:
        # slskd won't let SLSKD_USERNAME/PASSWORD override a login the
        # user had already customised). None until the background
        # check in _refresh_web_login_status() completes.
        self._web_login_status: SlskdWebLoginStatus | None = None
        # Roadmap item C5.12 (round 5) — MainWindow's own
        # _apply_theme_mode, so the sidebar toggle and this tab's radio
        # group stay in sync in both directions. None only in tests
        # that construct SettingsPage standalone.
        self._on_theme_mode_changed = on_theme_mode_changed
        # A callable rather than importing AboutDialog directly —
        # AboutDialog lives in main_window.py, which already imports
        # FROM this module (SETTINGS_TAB_*), so importing it back here
        # would be circular. MainWindow wires this to its own
        # _on_about_clicked (roadmap item 56 Phase 3 §3.4) — reusing the
        # exact same dialog/copy, not a second one.
        self._on_about_requested = on_about_requested

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_locations_tab(), SETTINGS_TAB_LOCATIONS)
        self.tabs.addTab(
            self._build_destinations_tab(), SETTINGS_TAB_DESTINATIONS,
        )
        self.tabs.addTab(self._build_connection_tab(), SETTINGS_TAB_CONNECTION)
        self.tabs.addTab(self._build_thresholds_tab(), SETTINGS_TAB_THRESHOLDS)
        layout.addWidget(self.tabs)

        about_row = QHBoxLayout()
        self.about_button = QPushButton("About Seeker")
        self.about_button.setToolTip(help_text.TOOLTIP_SETTINGS_ABOUT)
        self.about_button.clicked.connect(self._on_about_clicked)
        about_row.addWidget(self.about_button)
        about_row.addStretch()
        layout.addLayout(about_row)

        if initial_tab is not None:
            self.select_tab(initial_tab)

        self._refresh_locations()
        self._refresh_destinations()
        self._refresh_connection_display()

    def _on_about_clicked(self) -> None:
        if self._on_about_requested is not None:
            self._on_about_requested()

    def select_tab(self, tab_name: str) -> None:
        """Switches to the named tab — used both at construction time
        (initial_tab above) and after construction, since this page is
        now built once and persists for the app's lifetime rather than
        being recreated on every open (item 56 Phase 3: the wizard's
        "Connect Spotify"/"Add library location" shortcuts and the
        Dashboard CTA's settings_connection/settings_locations actions
        all need to land on a specific tab of the SAME long-lived page).
        """
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == tab_name:
                self.tabs.setCurrentIndex(index)
                return

    # --- Library locations (§1) --------------------------------------

    def _build_locations_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Persistent, dismissible — for the one real error this tab can
        # produce that's worth more than a transient status line: "this
        # path is already registered as X" (roadmap item 5 §4).
        self.locations_notice = InlineNotice()
        layout.addWidget(self.locations_notice)

        self.locations_table = QTableWidget(0, 4)
        self.locations_table.setHorizontalHeaderLabels(
            ["Name", "Path", "Reachable", "Actions"]
        )
        # Roadmap item 97 (B6) — this file's own two tables/lists never
        # went through the shared table-chrome helpers every real
        # QTableWidget/QListWidget in main_window.py already does (item
        # 80/R5): visible row-number header, square top-left corner
        # cutting into the card's own rounded arc, Qt-default row
        # heights, and (this table specifically) an underived Actions
        # column width. size_action_column (called from _render_
        # locations, after real Actions widgets exist to measure) needs
        # setStretchLastSection(False) first — it overrides any
        # per-column resize mode on the last section otherwise.
        theme.apply_table_defaults(self.locations_table)
        header = self.locations_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        # Roadmap item D3 (round 6) — after resize modes, not before;
        # see `theme.apply_column_floors`'s own docstring.
        theme.apply_column_floors(self.locations_table)
        layout.addWidget(theme.make_card(self.locations_table))

        add_row = QHBoxLayout()
        # No name field — the location is registered immediately under
        # the picked folder's own basename (auto-suffixed on a name
        # collision) and is renameable afterward via the table's own
        # Rename action (roadmap item 5 §1).
        self.add_location_button = QPushButton("Add location…")
        self.add_location_button.setToolTip(help_text.TOOLTIP_ADD_LOCATION)
        self.add_location_button.clicked.connect(
            self._on_add_location_clicked
        )
        add_row.addWidget(self.add_location_button)
        add_row.addStretch()
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
        action_widgets: list[QWidget] = []

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

            # Loaded from the DB via list_locations() above, so .id is
            # always set for a real row.
            assert location.id is not None
            location_id = location.id
            current_name = location.name

            rename_button = QPushButton("Rename")
            rename_button.setToolTip(help_text.TOOLTIP_RENAME_LOCATION)
            rename_button.clicked.connect(
                lambda _=False, location_id=location_id,
                current_name=current_name:
                    self._on_rename_location_clicked(
                        location_id, current_name,
                    )
            )

            remove_button = QPushButton("Remove")
            remove_button.setToolTip(help_text.TOOLTIP_REMOVE_LOCATION)
            name = location.name
            remove_button.clicked.connect(
                lambda _=False, name=name: self._on_remove_location_clicked(
                    name
                )
            )

            actions = theme.cell_widget(rename_button, remove_button)
            action_widgets.append(actions)
            self.locations_table.setCellWidget(row, 3, actions)

        # Roadmap item 97 (B6.3) — derived from this render's own real
        # Actions widgets, same as every other table with this column
        # (theme.size_action_column's own docstring).
        theme.size_action_column(self.locations_table, 3, action_widgets)

    def _on_add_location_clicked(self) -> None:
        self.locations_notice.dismiss()

        pick_and_add_library_location(
            self,
            self.thread_pool,
            self.application,
            button=self.add_location_button,
            on_finished=lambda _: self._on_location_added(),
            on_error=lambda message: self.locations_notice.show_message(
                message, kind="error",
            ),
        )

    def _on_rename_location_clicked(
            self, location_id: int, current_name: str,
    ) -> None:
        new_name, accepted = QInputDialog.getText(
            self, "Rename Location", "New name:", text=current_name,
        )
        new_name = new_name.strip()

        if not accepted or not new_name or new_name == current_name:
            return

        self.locations_notice.dismiss()

        run_worker(
            self.thread_pool,
            lambda: self.application.library_service.rename_location(
                location_id, new_name,
            ),
            on_finished=lambda _: self._on_location_added(),
            on_error=lambda message: self.locations_notice.show_message(
                message, kind="error",
            ),
        )

    def _on_location_added(self) -> None:
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
        outer = QVBoxLayout(tab)

        outer.addWidget(self._build_default_destination_group())

        content = QWidget()
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(content, 1)

        self.destinations_playlist_list = QListWidget()
        self.destinations_playlist_list.currentItemChanged.connect(
            self._on_destination_playlist_selected
        )
        # Roadmap item 97 (B6.2) — same rounded-card treatment every
        # QListWidget in main_window.py already gets (item 80).
        layout.addWidget(theme.make_card(self.destinations_playlist_list), 1)

        right = QVBoxLayout()

        form = QFormLayout()
        self.destination_location_combo = QComboBox()
        self.destination_location_combo.setToolTip(
            help_text.TOOLTIP_DESTINATION_LOCATION_COMBO
        )
        form.addRow("Library location:", self.destination_location_combo)

        self.destination_subfolder_field = QLineEdit()
        self.destination_subfolder_field.setPlaceholderText(
            "Optional subfolder"
        )
        self.destination_subfolder_field.setToolTip(
            help_text.TOOLTIP_DESTINATION_SUBFOLDER_FIELD
        )
        # Roadmap item 95 (B1.3) — one field, one obvious submit target
        # (Save destination), same reasoning/muscle-memory as B1.1/B1.2;
        # _on_save_destination_clicked already validates a playlist/
        # location are selected and writes a real status message.
        self.destination_subfolder_field.returnPressed.connect(
            self._on_save_destination_clicked
        )
        form.addRow("Subfolder:", self.destination_subfolder_field)
        right.addLayout(form)

        self.save_destination_button = QPushButton("Save destination")
        self.save_destination_button.setToolTip(
            help_text.TOOLTIP_SAVE_DESTINATION
        )
        self.save_destination_button.clicked.connect(
            self._on_save_destination_clicked
        )
        right.addWidget(self.save_destination_button)

        self.destinations_status_label = QLabel("")
        right.addWidget(self.destinations_status_label)

        right.addStretch()
        layout.addLayout(right, 1)

        return tab

    def _build_default_destination_group(self) -> QWidget:
        # Roadmap item 6 §4 — the fallback DownloadService resolves to
        # once a playlist has no destination of its own (§1); also
        # what the Dashboard's own "no dead end" dialog (§3) writes to
        # when its "Remember this for this playlist" checkbox is left
        # unchecked. Deliberately above the per-playlist overrides
        # below, not beside them — this is the first thing a real user
        # should notice on this tab, per the task's own layout ask.
        group = QGroupBox("Default Destination")
        layout = QFormLayout(group)

        self.default_location_combo = QComboBox()
        self.default_location_combo.setToolTip(
            help_text.TOOLTIP_DEFAULT_LOCATION_COMBO
        )
        layout.addRow("Library location:", self.default_location_combo)

        self.default_subfolder_per_playlist_checkbox = QCheckBox(
            "Subfolder per playlist"
        )
        self.default_subfolder_per_playlist_checkbox.setChecked(True)
        self.default_subfolder_per_playlist_checkbox.setToolTip(
            help_text.TOOLTIP_DEFAULT_SUBFOLDER_PER_PLAYLIST_CHECKBOX
        )
        layout.addRow("", self.default_subfolder_per_playlist_checkbox)

        save_row = QHBoxLayout()
        self.save_default_destination_button = QPushButton(
            "Save default destination"
        )
        self.save_default_destination_button.setProperty("variant", "primary")
        self.save_default_destination_button.setToolTip(
            help_text.TOOLTIP_SAVE_DEFAULT_DESTINATION
        )
        self.save_default_destination_button.clicked.connect(
            self._on_save_default_destination_clicked
        )
        save_row.addWidget(self.save_default_destination_button)
        save_row.addStretch()
        layout.addRow(save_row)

        self.default_destination_status_label = QLabel("")
        layout.addRow(self.default_destination_status_label)

        return group

    def _on_save_default_destination_clicked(self) -> None:
        location_id = self.default_location_combo.currentData()

        if location_id is None:
            self.default_destination_status_label.setText(
                "Select a library location first."
            )
            return

        subfolder_per_playlist = (
            self.default_subfolder_per_playlist_checkbox.isChecked()
        )

        run_worker(
            self.thread_pool,
            lambda: self.application.persist_default_destination(
                location_id, subfolder_per_playlist,
            ),
            button=self.save_default_destination_button,
            status_label=self.default_destination_status_label,
            on_finished=lambda _: self.default_destination_status_label.setText(
                "Default destination saved."
            ),
        )

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

        self.default_location_combo.clear()
        self.default_location_combo.addItem("(none)", None)
        for location, _ in locations:
            self.default_location_combo.addItem(location.name, location.id)

        config = self.application._config_store
        if config.default_download_location_id is not None:
            index = self.default_location_combo.findData(
                config.default_download_location_id
            )
            self.default_location_combo.setCurrentIndex(max(index, 0))
        self.default_subfolder_per_playlist_checkbox.setChecked(
            config.default_download_subfolder_per_playlist
        )

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

        # Roadmap item 116 (round 8, §6.6.1) — starts hidden; only shown
        # by _refresh_connection_display() when the configured slskd
        # base URL is actually plain http:// pointed off this machine.
        self.slskd_remote_warning_notice = InlineNotice()
        layout.addWidget(self.slskd_remote_warning_notice)

        spotify_group = QGroupBox("Spotify")
        spotify_form = QFormLayout(spotify_group)

        self.spotify_client_id_field = QLineEdit()
        # Not actually secret — PKCE has no client secret component —
        # fine to display and edit in plain text.
        self.spotify_client_id_field.setToolTip(
            help_text.TOOLTIP_SPOTIFY_CLIENT_ID_FIELD
        )
        # Roadmap item 95 (B1.3) — one field, one obvious submit target
        # (Re-authorize); _on_reauthorize_spotify_clicked already
        # validates non-empty and writes a real status message.
        self.spotify_client_id_field.returnPressed.connect(
            self._on_reauthorize_spotify_clicked
        )
        spotify_form.addRow("Client ID:", self.spotify_client_id_field)

        self.reauthorize_spotify_button = QPushButton("Re-authorize")
        self.reauthorize_spotify_button.setToolTip(
            help_text.TOOLTIP_REAUTHORIZE_SPOTIFY
        )
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
        self.reveal_api_key_button.setToolTip(help_text.TOOLTIP_REVEAL_API_KEY)
        self.reveal_api_key_button.clicked.connect(
            self._on_toggle_api_key_visibility
        )
        api_key_row.addWidget(self.reveal_api_key_button)
        soulseek_form.addRow("API key:", api_key_row)

        # Roadmap item 116 (round 8, §6.1.2) — surfaces the generated
        # slskd WEB UI login (distinct from the SoulSeek network login
        # above), otherwise nowhere in the app the user could ever find
        # it once bring_up_slskd stopped leaving the web UI at slskd's
        # own vendor default.
        self.slskd_web_username_display = QLabel("Not configured")
        soulseek_form.addRow(
            "Web UI username:", self.slskd_web_username_display
        )

        web_password_row = QHBoxLayout()
        self.slskd_web_password_display = QLabel("Not configured")
        web_password_row.addWidget(self.slskd_web_password_display)
        self.reveal_web_password_button = QPushButton("Show")
        self.reveal_web_password_button.setToolTip(
            "slskd's own web UI login — open its address (Sharing page) "
            "and sign in with this username/password."
        )
        self.reveal_web_password_button.clicked.connect(
            self._on_toggle_web_password_visibility
        )
        web_password_row.addWidget(self.reveal_web_password_button)
        soulseek_form.addRow("Web UI password:", web_password_row)

        self.test_connection_button = QPushButton("Test connection")
        self.test_connection_button.setToolTip(
            help_text.TOOLTIP_TEST_CONNECTION
        )
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
        self.new_soulseek_username_field.setToolTip(
            help_text.TOOLTIP_NEW_SOULSEEK_USERNAME_FIELD
        )
        # Roadmap item 95 (B1.3) — the SoulSeek credentials form the
        # brief names directly: one obvious submit target (Update
        # credentials); _on_update_credentials_clicked already
        # validates non-empty and writes a real status message.
        self.new_soulseek_username_field.returnPressed.connect(
            self._on_update_credentials_clicked
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
        self.new_soulseek_password_field.setToolTip(
            help_text.TOOLTIP_NEW_SOULSEEK_PASSWORD_FIELD
        )
        self.new_soulseek_password_field.returnPressed.connect(
            self._on_update_credentials_clicked
        )
        soulseek_form.addRow(
            "New password:", self.new_soulseek_password_field
        )

        self.update_credentials_button = QPushButton(
            "Update SoulSeek credentials"
        )
        self.update_credentials_button.setToolTip(
            help_text.TOOLTIP_UPDATE_CREDENTIALS
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
        self._render_web_password_display()
        self._render_slskd_remote_warning()
        self._refresh_web_login_status()

    def _refresh_web_login_status(self) -> None:
        """Background-check whether the persisted web UI credential is
        the one the container will actually accept right now (S1.2) —
        `ensure_slskd_web_credentials()` only ever generates and
        persists a value, it never confirms slskd took it, and slskd
        silently won't override an already-customised login. A stale
        `self._web_login_status` from a previous check is kept showing
        (not reset to None) until the new result lands, so the display
        doesn't flicker to "checking" on every tab re-open.
        """
        config = self.application._config_store
        base_url = self.application._slskd_base_url

        if (
                not base_url
                or not config.slskd_web_username
                or not config.slskd_web_password
        ):
            self._web_login_status = None
            self._render_web_password_display()
            return

        run_worker(
            self.thread_pool,
            lambda: check_slskd_web_login(
                base_url,
                config.slskd_web_username,
                config.slskd_web_password,
            ),
            on_finished=self._on_web_login_status_checked,
        )

    def _on_web_login_status_checked(
            self,
            status: SlskdWebLoginStatus,
    ) -> None:
        self._web_login_status = status
        self._render_web_password_display()

    def _render_web_password_display(self) -> None:
        config = self.application._config_store

        if not config.slskd_web_username or not config.slskd_web_password:
            self.slskd_web_username_display.setText("Not configured")
            self.slskd_web_password_display.setText("Not configured")
            self.reveal_web_password_button.hide()
            return

        # S1.2 — never show a credential that isn't the one the
        # container will actually accept: slskd won't let a generated
        # SLSKD_USERNAME/PASSWORD override a login already customised
        # before Seeker ever set it.
        if self._web_login_status == SlskdWebLoginStatus.INACTIVE:
            self.slskd_web_username_display.setText(
                "An existing web UI login is already in place — "
                "Seeker did not change it."
            )
            self.slskd_web_password_display.setText("")
            self.reveal_web_password_button.hide()
            return

        if self._web_login_status == SlskdWebLoginStatus.UNKNOWN:
            self.slskd_web_username_display.setText(
                "Not confirmed (SoulSeek isn't reachable right now)"
            )
            self.slskd_web_password_display.setText("")
            self.reveal_web_password_button.hide()
            return

        if self._web_login_status != SlskdWebLoginStatus.ACTIVE:
            # Still checking — show nothing definite rather than a
            # credential that hasn't been confirmed to work yet.
            self.slskd_web_username_display.setText("Checking…")
            self.slskd_web_password_display.setText("")
            self.reveal_web_password_button.hide()
            return

        self.slskd_web_username_display.setText(config.slskd_web_username)
        self.reveal_web_password_button.show()

        if self._web_password_visible:
            self.slskd_web_password_display.setText(config.slskd_web_password)
            self.reveal_web_password_button.setText("Hide")
        else:
            self.slskd_web_password_display.setText("••••••••")
            self.reveal_web_password_button.setText("Show")

    def _on_toggle_web_password_visibility(self) -> None:
        self._web_password_visible = not self._web_password_visible
        self._render_web_password_display()

    def _render_slskd_remote_warning(self) -> None:
        base_url = self.application._slskd_base_url

        if base_url and is_non_loopback_http_url(base_url):
            self.slskd_remote_warning_notice.show_message(
                "Your SoulSeek connection is configured for a "
                f"non-local address over plain HTTP ({base_url}). Your "
                "API key would cross the network unencrypted — use "
                "HTTPS, or keep slskd on this machine.",
                kind="warning",
            )
        else:
            self.slskd_remote_warning_notice.dismiss()

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
        web_username, web_password = (
            self.application.ensure_slskd_web_credentials()
        )

        def do_update() -> None:
            result = bring_up_slskd(
                compose_file=str(compose_file_path()),
                soulseek_username=username,
                soulseek_password=password,
                api_key=api_key,
                slskd_data_dir=str(data_dir),
                web_username=web_username,
                web_password=web_password,
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

    # --- Appearance (C5.12) -----------------------------------------

    def _build_appearance_group(self) -> QGroupBox:
        # Roadmap item C5.12 (round 5) — the authoritative three-way
        # control (the sidebar toggle is the quick, no-label version;
        # this one names every option explicitly). Kept in sync with
        # the toggle in both directions via MainWindow._apply_theme_mode
        # / sync_theme_mode below.
        group = QGroupBox("Appearance")
        layout = QVBoxLayout(group)

        self._theme_mode_group = QButtonGroup(group)
        self._theme_mode_radios: dict[str, QRadioButton] = {}
        for mode, label in (
                ("system", "Follow system"),
                ("light", "Light"),
                ("dark", "Dark"),
        ):
            radio = QRadioButton(label)
            self._theme_mode_group.addButton(radio)
            self._theme_mode_radios[mode] = radio
            radio.toggled.connect(
                lambda checked, mode=mode: (
                    self._on_theme_mode_radio_toggled(mode, checked)
                )
            )
            layout.addWidget(radio)

        # Establishes the starting selection WITHOUT firing
        # _on_theme_mode_changed — this runs during SettingsPage's own
        # __init__, before MainWindow has finished assigning
        # `self.settings_page`, so an unguarded setChecked(True) here
        # crashes on that not-yet-existing attribute (found live).
        current = self.application.theme_mode
        if current in self._theme_mode_radios:
            radio = self._theme_mode_radios[current]
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)

        return group

    def _on_theme_mode_radio_toggled(self, mode: str, checked: bool) -> None:
        if not checked:
            return
        if self._on_theme_mode_changed is not None:
            self._on_theme_mode_changed(mode)

    def sync_theme_mode(self, mode: str) -> None:
        """Called by `MainWindow._apply_theme_mode` after a switch
        triggered from ANYWHERE (the sidebar toggle, this tab's own
        radios, or the OS's `colorSchemeChanged` while mode=="system")
        so these radios never show a stale selection. Signals blocked
        while syncing — without this, setChecked(True) here would fire
        `toggled` right back into `_on_theme_mode_changed`, re-entering
        `MainWindow._apply_theme_mode` for a mode it's already applying
        (same discipline `_load_threshold_fields` already uses for its
        own checkboxes)."""
        radio = self._theme_mode_radios.get(mode)
        if radio is not None and not radio.isChecked():
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)

    # --- Thresholds (§4) -------------------------------------------

    def _build_thresholds_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(self._build_appearance_group())

        layout.addWidget(QLabel(
            "Controls when a matched track is auto-accepted vs. "
            "surfaced for review vs. treated as no match at all."
        ))

        form = QFormLayout()

        self.auto_match_threshold_field = QLineEdit()
        self.auto_match_threshold_field.setToolTip(
            help_text.TOOLTIP_AUTO_MATCH_THRESHOLD_FIELD
        )
        # Roadmap item 95 (B1.3) — one obvious submit target (Save
        # thresholds) shared by both fields in this form;
        # _on_save_thresholds_clicked already validates both are real
        # numbers in the right order and writes a real status message.
        self.auto_match_threshold_field.returnPressed.connect(
            self._on_save_thresholds_clicked
        )
        form.addRow(
            "Auto-match threshold:", self.auto_match_threshold_field
        )

        self.needs_review_threshold_field = QLineEdit()
        self.needs_review_threshold_field.setToolTip(
            help_text.TOOLTIP_NEEDS_REVIEW_THRESHOLD_FIELD
        )
        self.needs_review_threshold_field.returnPressed.connect(
            self._on_save_thresholds_clicked
        )
        form.addRow(
            "Needs-review threshold:", self.needs_review_threshold_field
        )

        layout.addLayout(form)

        self.save_thresholds_button = QPushButton("Save thresholds")
        self.save_thresholds_button.setToolTip(
            help_text.TOOLTIP_SAVE_THRESHOLDS
        )
        self.save_thresholds_button.clicked.connect(
            self._on_save_thresholds_clicked
        )
        layout.addWidget(self.save_thresholds_button)

        self.thresholds_status_label = QLabel("")
        layout.addWidget(self.thresholds_status_label)

        # Roadmap item R7.5 — per-category menu-bar notification
        # toggles, all defaulting on (config_store.py's own field
        # defaults). A single checkbox that saves itself immediately on
        # toggle, matching the "no separate save step for one boolean"
        # precedent nothing else on this tab actually sets (thresholds
        # are two related numbers that need a combined save/validation
        # step; each of these is one independent flag).
        notifications_group = QGroupBox("Menu Bar Notifications")
        notifications_layout = QVBoxLayout(notifications_group)

        self.notify_downloads_finished_checkbox = QCheckBox(
            "Downloads finished"
        )
        self.notify_downloads_finished_checkbox.setToolTip(
            help_text.TOOLTIP_NOTIFY_DOWNLOADS_FINISHED_CHECKBOX
        )
        self.notify_downloads_finished_checkbox.toggled.connect(
            lambda checked: self.application.set_notification_preference(
                "notify_downloads_finished", checked,
            )
        )
        notifications_layout.addWidget(self.notify_downloads_finished_checkbox)

        self.notify_needs_decision_checkbox = QCheckBox(
            "Items need your decision"
        )
        self.notify_needs_decision_checkbox.setToolTip(
            help_text.TOOLTIP_NOTIFY_NEEDS_DECISION_CHECKBOX
        )
        self.notify_needs_decision_checkbox.toggled.connect(
            lambda checked: self.application.set_notification_preference(
                "notify_needs_decision", checked,
            )
        )
        notifications_layout.addWidget(self.notify_needs_decision_checkbox)

        self.notify_errors_checkbox = QCheckBox("Errors")
        self.notify_errors_checkbox.setToolTip(
            help_text.TOOLTIP_NOTIFY_ERRORS_CHECKBOX
        )
        self.notify_errors_checkbox.toggled.connect(
            lambda checked: self.application.set_notification_preference(
                "notify_errors", checked,
            )
        )
        notifications_layout.addWidget(self.notify_errors_checkbox)

        layout.addWidget(notifications_group)

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

        for checkbox, value in (
                (self.notify_downloads_finished_checkbox,
                 config.notify_downloads_finished),
                (self.notify_needs_decision_checkbox,
                 config.notify_needs_decision),
                (self.notify_errors_checkbox, config.notify_errors),
        ):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)

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

from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.login_item import LoginItemStatus
from seeker.matching import AUTO_MATCH_THRESHOLD, NEEDS_REVIEW_THRESHOLD
from seeker.models.library_location import LibraryLocation
from seeker.models.location_merge import LocationMergeSummary
from seeker.models.location_removal import LocationRemovalSummary
from seeker.models.nested_location import NestedLocation
from seeker.models.playlist import Playlist
from seeker.soulseek.docker_setup import (
    SlskdHealthCheckResult,
    SlskdHealthStatus,
    SlskdWebLoginStatus,
    check_slskd_health,
    check_slskd_web_login,
    is_non_loopback_http_url,
)
from seeker.ui import help_text, plain_text, theme
from seeker.ui.library_location_picker import pick_and_add_library_location
from seeker.ui.notice import InlineNotice
from seeker.ui.plain_text import PlainLabel
from seeker.ui.spotify_authorization import SpotifyAuthorizationWait
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

# Name/Path/Reachable/Actions, see theme.ColumnLayout.
_LOCATIONS_COLUMNS = theme.ColumnLayout(stretch=(1,), fit_content=(0, 2), actions=3)


def _scrollable(tab: QWidget) -> QScrollArea:
    """`tab` in a frameless scroll area, so a tab taller than the
    window scrolls instead of squeezing its rows below their size."""
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll_area.setWidget(tab)
    return scroll_area


class SettingsPage(QWidget):
    """An in-window Settings page, not a separate top-level window: in
    fullscreen, a second window reads as a dead end with no way back to
    the shell. Hosted in MainWindow's own QStackedWidget like every
    other page, via `_build_page()`, whose standard header and margins
    it uses rather than a subtitle label of its own. Never a top-level
    window, so it needs no `WA_DeleteOnClose` handling.
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
        # Whether the generated slskd web UI login is actually the one
        # the container will accept right now (it may not be: slskd
        # won't let SLSKD_USERNAME/PASSWORD override a login the user
        # had already customised). None until the background check in
        # _refresh_web_login_status() completes.
        self._web_login_status: SlskdWebLoginStatus | None = None
        # MainWindow's own _apply_theme_mode, so the sidebar toggle and
        # this tab's radio group stay in sync in both directions. None
        # only in tests that construct SettingsPage standalone.
        self._on_theme_mode_changed = on_theme_mode_changed
        # A callable rather than importing AboutDialog directly —
        # AboutDialog lives in main_window.py, which already imports
        # FROM this module (SETTINGS_TAB_*), so importing it back here
        # would be circular. MainWindow wires this to its own
        # _on_about_clicked — reusing the exact same dialog/copy, not a
        # second one.
        self._on_about_requested = on_about_requested

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.addTab(
            _scrollable(self._build_locations_tab()), SETTINGS_TAB_LOCATIONS,
        )
        self.tabs.addTab(
            _scrollable(self._build_destinations_tab()),
            SETTINGS_TAB_DESTINATIONS,
        )
        self.tabs.addTab(
            _scrollable(self._build_connection_tab()),
            SETTINGS_TAB_CONNECTION,
        )
        self.tabs.addTab(
            _scrollable(self._build_thresholds_tab()),
            SETTINGS_TAB_THRESHOLDS,
        )
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
        built once and persists for the app's lifetime rather than being
        recreated on every open (the wizard's "Connect Spotify"/"Add
        library location" shortcuts and the Dashboard CTA's
        settings_connection/settings_locations actions all need to land
        on a specific tab of the SAME long-lived page).
        """
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == tab_name:
                self.tabs.setCurrentIndex(index)
                return

    # --- Library locations -------------------------------------------

    def _build_locations_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Persistent, dismissible — for errors worth more than a
        # transient status line: a folder already registered, or one
        # inside or around a registered location.
        self.locations_notice = InlineNotice()
        layout.addWidget(self.locations_notice)

        # Shown while a location sits inside another: the add guard
        # refuses that now, but older builds registered such pairs.
        self.nesting_notice = InlineNotice()
        layout.addWidget(self.nesting_notice)

        self.locations_table = QTableWidget(0, 4)
        self.locations_table.setHorizontalHeaderLabels(
            ["Name", "Path", "Reachable", "Actions"]
        )
        # The shared table chrome every QTableWidget gets (HISTORY §87):
        # without it, a visible row-number header, a square top-left
        # corner cutting into the card's own rounded arc, Qt-default row
        # heights, and an underived Actions column width.
        theme.apply_table_defaults(self.locations_table)
        theme.configure_columns(self.locations_table, _LOCATIONS_COLUMNS)
        layout.addWidget(theme.make_card(self.locations_table))

        add_row = QHBoxLayout()
        # No name field — the location is registered immediately under
        # the picked folder's own basename (auto-suffixed on a name
        # collision) and is renameable afterward via the table's own
        # Rename action.
        self.add_location_button = QPushButton("Add location…")
        self.add_location_button.setToolTip(help_text.TOOLTIP_ADD_LOCATION)
        self.add_location_button.clicked.connect(
            self._on_add_location_clicked
        )
        add_row.addWidget(self.add_location_button)
        add_row.addStretch()
        layout.addLayout(add_row)

        layout.addStretch()
        return tab

    def _refresh_locations(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.list_locations,
            on_finished=self._render_locations,
        )
        run_worker(
            self.thread_pool,
            self.application.library_service.find_nested_locations,
            on_finished=self._render_nesting,
        )

    def _render_nesting(self, nested: list[NestedLocation]) -> None:
        if not nested:
            self.nesting_notice.dismiss()
            return

        self.nesting_notice.show_message(
            help_text.format_nested_locations_warning(nested),
            kind="warning",
            action_text=help_text.FIX_NESTING_ACTION,
            on_action=lambda: self._on_fix_nesting_clicked(nested),
        )

    def _on_fix_nesting_clicked(self, nested: list[NestedLocation]) -> None:
        names = list(dict.fromkeys(
            name
            for pair in nested
            for name in (pair.outer.name, pair.inner.name)
        ))
        kept, accepted = QInputDialog.getItem(
            self,
            help_text.MERGE_LOCATIONS_TITLE,
            help_text.MERGE_LOCATIONS_PICK_LABEL,
            names,
            0,
            False,
        )

        if not accepted or kept not in names:
            return

        merged = locations_nested_with(nested, kept)
        self.locations_notice.dismiss()

        run_worker(
            self.thread_pool,
            lambda: [
                self.application.preview_merge_location(name, kept)
                for name in merged
            ],
            button=self.nesting_notice.action_button,
            on_finished=lambda previews: self._confirm_merge_locations(
                kept, previews,
            ),
            on_error=self._show_locations_error,
        )

    def _confirm_merge_locations(
            self,
            kept: str,
            previews: list[LocationMergeSummary],
    ) -> None:
        confirmed = plain_text.question(
            self,
            help_text.MERGE_LOCATIONS_TITLE,
            help_text.format_merge_locations_confirm_body(kept, previews),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        merged = [preview.merged_name for preview in previews]
        run_worker(
            self.thread_pool,
            lambda: [
                self.application.merge_location(name, kept)
                for name in merged
            ],
            button=self.nesting_notice.action_button,
            on_finished=lambda summaries: self._on_locations_merged(
                kept, summaries,
            ),
            on_error=self._on_merge_failed,
        )

    def _on_locations_merged(
            self,
            kept: str,
            summaries: list[LocationMergeSummary],
    ) -> None:
        self.locations_notice.show_message(
            help_text.format_merge_locations_result(kept, summaries),
        )
        self._on_location_added()

    def _on_merge_failed(self, message: str) -> None:
        # An earlier location in the list may have merged already.
        self._show_locations_error(message)
        self._on_location_added()

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

            actions = theme.cell_widget(
                rename_button, remove_button, row_label=location.name,
            )
            action_widgets.append(actions)
            self.locations_table.setCellWidget(row, 3, actions)

        # Derived from this render's own real Actions widgets, same as
        # every other table with this column (theme.size_action_column's
        # own docstring).
        theme.size_columns(self.locations_table, _LOCATIONS_COLUMNS, action_widgets)

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
        self.locations_notice.dismiss()

        run_worker(
            self.thread_pool,
            lambda: self.application.preview_remove_location(name),
            on_finished=self._confirm_remove_location,
            on_error=self._show_locations_error,
        )

    def _confirm_remove_location(self, preview: LocationRemovalSummary) -> None:
        confirmed = plain_text.question(
            self,
            help_text.REMOVE_LOCATION_CONFIRM_TITLE,
            help_text.format_remove_location_confirm_body(preview),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        name = preview.location_name
        run_worker(
            self.thread_pool,
            lambda: self.application.remove_location(name),
            on_finished=self._on_location_removed,
            on_error=self._show_locations_error,
        )

    def _on_location_removed(self, summary: LocationRemovalSummary) -> None:
        self.locations_notice.show_message(
            help_text.format_remove_location_result(summary),
        )
        self._on_location_added()

    def _show_locations_error(self, message: str) -> None:
        self.locations_notice.show_message(message, kind="error")

    # --- Playlist destinations ---------------------------------------

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
        # The same rounded-card treatment every table and list gets
        # (HISTORY §80).
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
        # One field, one obvious submit target (Save destination), so
        # Enter submits (HISTORY §95); _on_save_destination_clicked
        # already validates a playlist/location are selected and writes
        # a real status message.
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
        right.addLayout(theme.action_row(self.save_destination_button))

        self.destinations_status_label = PlainLabel("")
        right.addWidget(self.destinations_status_label)

        right.addStretch()
        layout.addLayout(right, 1)

        return tab

    def _build_default_destination_group(self) -> QWidget:
        # The fallback DownloadService resolves to once a playlist has
        # no destination of its own (HISTORY §50); also what the
        # Dashboard's own "no dead end" dialog writes to when its
        # "Remember this for this playlist" checkbox is left unchecked.
        # Deliberately above the per-playlist overrides below, not
        # beside them — this is the first thing a real user should
        # notice on this tab.
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

        self.default_destination_status_label = PlainLabel("")
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

        config = self.application.settings
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

    # --- Connection management -----------------------------------------

    def _build_connection_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Starts hidden; only shown by _refresh_connection_display()
        # when the configured slskd base URL is actually plain
        # http://pointed off this machine.
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
        # One field, one obvious submit target (Re-authorize);
        # _on_reauthorize_spotify_clicked already validates non-empty
        # and writes a real status message.
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
        spotify_form.addRow(
            "", theme.action_row(self.reauthorize_spotify_button),
        )

        self.spotify_status_label = PlainLabel("")
        spotify_form.addRow("", self.spotify_status_label)

        self.spotify_authorization_wait = SpotifyAuthorizationWait(
            self.application,
            self.thread_pool,
            self.reauthorize_spotify_button,
            self.spotify_status_label,
        )
        spotify_form.addRow("", self.spotify_authorization_wait)

        layout.addWidget(spotify_group)

        soulseek_group = QGroupBox("SoulSeek")
        soulseek_form = QFormLayout(soulseek_group)

        self.soulseek_username_display = PlainLabel("Not configured")
        soulseek_form.addRow("Username:", self.soulseek_username_display)

        self.soulseek_password_display = PlainLabel("Not configured")
        soulseek_form.addRow("Password:", self.soulseek_password_display)

        api_key_row = QHBoxLayout()
        self.soulseek_api_key_display = PlainLabel("Not configured")
        api_key_row.addWidget(self.soulseek_api_key_display)
        self.reveal_api_key_button = QPushButton("Show")
        self.reveal_api_key_button.setToolTip(help_text.TOOLTIP_REVEAL_API_KEY)
        self.reveal_api_key_button.clicked.connect(
            self._on_toggle_api_key_visibility
        )
        api_key_row.addWidget(self.reveal_api_key_button)
        soulseek_form.addRow("API key:", api_key_row)

        # Surfaces the generated slskd WEB UI login (distinct from the
        # SoulSeek network login above), otherwise nowhere in the app
        # the user could ever find it, since bring_up_slskd never leaves
        # the web UI at slskd's own vendor default (HISTORY §116).
        self.slskd_web_username_display = PlainLabel("Not configured")
        soulseek_form.addRow(
            "Web UI username:", self.slskd_web_username_display
        )

        web_password_row = QHBoxLayout()
        self.slskd_web_password_display = PlainLabel("Not configured")
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
        soulseek_form.addRow(
            "", theme.action_row(self.test_connection_button),
        )

        self.test_connection_status_label = PlainLabel("")
        soulseek_form.addRow("", self.test_connection_status_label)

        soulseek_form.addRow(PlainLabel("Update credentials:"))

        self.new_soulseek_username_field = QLineEdit()
        self.new_soulseek_username_field.setPlaceholderText(
            "SoulSeek username"
        )
        self.new_soulseek_username_field.setToolTip(
            help_text.TOOLTIP_NEW_SOULSEEK_USERNAME_FIELD
        )
        # One obvious submit target (Update credentials);
        # _on_update_credentials_clicked already validates non-empty and
        # writes a real status message.
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
        soulseek_form.addRow(
            "", theme.action_row(self.update_credentials_button),
        )

        self.update_credentials_status_label = PlainLabel("")
        soulseek_form.addRow("", self.update_credentials_status_label)

        layout.addWidget(soulseek_group)
        layout.addStretch()
        return tab

    def _refresh_connection_display(self) -> None:
        config = self.application.settings

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
        the one the container will actually accept right now —
        `ensure_slskd_web_credentials()` only ever generates and
        persists a value, it never confirms slskd took it, and slskd
        silently won't override an already-customised login. A stale
        `self._web_login_status` from a previous check is kept showing
        (not reset to None) until the new result lands, so the display
        doesn't flicker to "checking" on every tab re-open.
        """
        config = self.application.settings
        base_url = self.application.slskd_base_url

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
        config = self.application.settings

        if not config.slskd_web_username or not config.slskd_web_password:
            self.slskd_web_username_display.setText("Not configured")
            self.slskd_web_password_display.setText("Not configured")
            self.reveal_web_password_button.hide()
            return

        # Never show a credential that isn't the one the container will
        # actually accept: slskd won't let a generated
        # SLSKD_USERNAME/PASSWORD override a login already customised
        # before Seeker ever set it (HISTORY §117).
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
        base_url = self.application.slskd_base_url

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
        config = self.application.settings

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
        # Enter in the Client ID field reaches here with the button
        # disabled, so the wait's own guard is the one that counts.
        if self.spotify_authorization_wait.is_waiting:
            return

        client_id = self.spotify_client_id_field.text().strip()

        if not client_id:
            self.spotify_status_label.setText("Enter a Client ID first.")
            return

        self.spotify_authorization_wait.start(
            client_id,
            on_connected=lambda: self.spotify_status_label.setText(
                "Re-authorized."
            ),
            force_reauthorize=True,
        )

    def _on_test_connection_clicked(self) -> None:
        base_url = self.application.slskd_base_url
        api_key = self.application.slskd_api_key

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

        if not self._locations_by_name:
            self.update_credentials_status_label.setText(
                "Register a library location before setting up SoulSeek."
            )
            return

        # A credential update must never change what is shared: keep the
        # running container's share, and ask only when none is running.
        run_worker(
            self.thread_pool,
            self.application.sharing_service.current_share_path,
            button=self.update_credentials_button,
            status_label=self.update_credentials_status_label,
            on_finished=lambda share_path: self._recreate_with_credentials(
                username, password, share_path,
            ),
        )
        self.update_credentials_status_label.setText(
            "Checking which folder SoulSeek shares now..."
        )

    def _recreate_with_credentials(
            self,
            username: str,
            password: str,
            live_share_path: str | None,
    ) -> None:
        library_location_path = live_share_path

        if library_location_path is None:
            library_location_path = self._ask_which_location_to_share()

        if library_location_path is None:
            self.update_credentials_status_label.setText(
                "Cancelled — SoulSeek was not changed."
            )
            return

        def do_update() -> None:
            self.application.start_slskd(
                username, password, library_location_path, persist=True,
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

    def _ask_which_location_to_share(self) -> str | None:
        names = list(self._locations_by_name)
        name, accepted = QInputDialog.getItem(
            self,
            "Share a folder",
            "SoulSeek isn't running, so there's no current share to keep.\n"
            "Which library location should SoulSeek share (read-only)?",
            names,
            0,
            False,
        )

        if not accepted or name not in self._locations_by_name:
            return None

        return self._locations_by_name[name].path

    def _on_credentials_updated(self) -> None:
        self.new_soulseek_username_field.clear()
        self.new_soulseek_password_field.clear()
        self._refresh_connection_display()
        self.update_credentials_status_label.setText(
            "Credentials updated. Container recreated with new "
            "credentials — use Test connection to confirm."
        )

    # --- Appearance ------------------------------------------------

    def _build_appearance_group(self) -> QGroupBox:
        # The authoritative three-way control (the sidebar toggle is the
        # quick, no-label version; this one names every option
        # explicitly). Kept in sync with the toggle in both directions
        # via MainWindow._apply_theme_mode / sync_theme_mode below.
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

    # --- Thresholds ------------------------------------------------

    def _build_thresholds_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(self._build_appearance_group())

        layout.addWidget(PlainLabel(
            "Controls when a matched track is auto-accepted vs. "
            "surfaced for review vs. treated as no match at all."
        ))

        form = QFormLayout()

        self.auto_match_threshold_field = QLineEdit()
        self.auto_match_threshold_field.setToolTip(
            help_text.TOOLTIP_AUTO_MATCH_THRESHOLD_FIELD
        )
        # One obvious submit target (Save thresholds) shared by both
        # fields in this form; _on_save_thresholds_clicked already
        # validates both are real numbers in the right order and writes
        # a real status message.
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
        layout.addLayout(theme.action_row(self.save_thresholds_button))

        self.thresholds_status_label = PlainLabel("")
        layout.addWidget(self.thresholds_status_label)

        # Per-category menu-bar notification toggles, all defaulting on
        # (config_store.py's own field defaults). A single checkbox that
        # saves itself immediately on toggle, matching the "no separate
        # save step for one boolean" precedent nothing else on this tab
        # actually sets (thresholds are two related numbers that need a
        # combined save/validation step; each of these is one
        # independent flag).
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

        layout.addWidget(self._build_startup_group())

        layout.addStretch()

        self._load_threshold_fields()

        return tab

    # --- Start at login ----------------------------------------------

    def _build_startup_group(self) -> QGroupBox:
        group = QGroupBox("Startup")
        layout = QVBoxLayout(group)

        self.start_at_login_checkbox = QCheckBox("Start Seeker at login")
        self.start_at_login_checkbox.setToolTip(
            help_text.TOOLTIP_START_AT_LOGIN_CHECKBOX
        )
        self.start_at_login_checkbox.toggled.connect(
            self._on_start_at_login_toggled
        )
        layout.addWidget(self.start_at_login_checkbox)

        self.start_hidden_at_login_checkbox = QCheckBox(
            "Start hidden in the menu bar"
        )
        self.start_hidden_at_login_checkbox.setToolTip(
            help_text.TOOLTIP_START_HIDDEN_AT_LOGIN_CHECKBOX
        )
        self.start_hidden_at_login_checkbox.toggled.connect(
            lambda checked: self.application.update_settings(
                start_hidden_at_login=checked,
            )
        )
        layout.addWidget(self.start_hidden_at_login_checkbox)

        self.start_at_login_status_label = PlainLabel("")
        self.start_at_login_status_label.setProperty("badge", "muted")
        self.start_at_login_status_label.setWordWrap(True)
        layout.addWidget(self.start_at_login_status_label)

        self.refresh_login_item_state()

        return group

    def refresh_login_item_state(self) -> None:
        """Re-reads the REAL ServiceManagement status, never a mirrored
        config.json boolean (HISTORY §131) — called both at Settings'
        own construction and, by MainWindow._on_page_changed, on every
        real show of this page, so a login item the user revoked via
        System Settings stops showing as on here too without needing a
        restart."""
        if not self.application.login_item_supported:
            self.start_at_login_checkbox.setEnabled(False)
            self.start_at_login_checkbox.blockSignals(True)
            self.start_at_login_checkbox.setChecked(False)
            self.start_at_login_checkbox.blockSignals(False)
            self.start_hidden_at_login_checkbox.blockSignals(True)
            self.start_hidden_at_login_checkbox.setChecked(
                self.application.settings.start_hidden_at_login
            )
            self.start_hidden_at_login_checkbox.blockSignals(False)
            self.start_at_login_status_label.setText(
                help_text.TOOLTIP_START_AT_LOGIN_UNSUPPORTED
            )
            return

        status = self.application.login_item_status()

        self.start_at_login_checkbox.setEnabled(True)
        self.start_at_login_checkbox.blockSignals(True)
        self.start_at_login_checkbox.setChecked(
            status in (
                LoginItemStatus.ENABLED, LoginItemStatus.REQUIRES_APPROVAL,
            )
        )
        self.start_at_login_checkbox.blockSignals(False)

        self.start_hidden_at_login_checkbox.blockSignals(True)
        self.start_hidden_at_login_checkbox.setChecked(
            self.application.settings.start_hidden_at_login
        )
        self.start_hidden_at_login_checkbox.blockSignals(False)

        self.start_at_login_status_label.setText(
            "Waiting on approval in System Settings > General > Login "
            "Items."
            if status == LoginItemStatus.REQUIRES_APPROVAL else ""
        )

    def _on_start_at_login_toggled(self, checked: bool) -> None:
        self.application.set_login_item_enabled(checked)

        # Defaults "start hidden" on every time login-at-startup is
        # turned ON (an app that launches at login and throws a window
        # in your face at every boot is a worse experience than one that
        # doesn't launch at all); a no-op if it's already True. Turning
        # login OFF leaves "start hidden" exactly as it was — that
        # checkbox is a standalone preference (main_ui.py applies it on
        # every launch, not only ones the login item triggered), not
        # something this method un-sets on the OFF transition.
        if checked:
            self.application.update_settings(start_hidden_at_login=True)

        self.refresh_login_item_state()

    def _load_threshold_fields(self) -> None:
        config = self.application.settings

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

        self.application.update_settings(
            auto_match_threshold=auto_threshold,
            needs_review_threshold=needs_review_threshold,
        )

        self.thresholds_status_label.setText(
            "Saved. Takes effect on the next match/download run."
        )


def locations_nested_with(
        nested: list[NestedLocation],
        kept: str,
) -> list[str]:
    """Every location inside or around `kept`, in `nested`'s order."""
    return list(dict.fromkeys(
        other.name
        for pair in nested
        for location, other in (
            (pair.inner, pair.outer),
            (pair.outer, pair.inner),
        )
        if location.name == kept
    ))

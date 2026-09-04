from dataclasses import replace

from PySide6.QtWidgets import QFileDialog, QInputDialog, QPushButton

from seeker.application import Application
from seeker.docker_setup import SlskdHealthCheckResult, SlskdHealthStatus
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore
from seeker.ui import help_text
from seeker.ui.settings_window import SettingsPage


def _fake_user_data_dir(data_dir):
    def fake(appname, **kwargs):
        return str(data_dir)

    return fake


def make_application(tmp_path, monkeypatch) -> Application:
    monkeypatch.chdir(tmp_path)

    # This process's real .env may have real SLSKD_*/SPOTIFY_* values
    # already loaded into os.environ (config.py's load_dotenv() runs at
    # import time, against the real project .env) —
    # migrate_legacy_env_config reads os.environ live regardless of
    # monkeypatch.chdir(), so every Settings test needs a genuinely
    # unconfigured starting point unless it sets a value itself. Same
    # gap test_config_store.py's own _clear_migration_env already hit.
    for env_var in (
            "SLSKD_BASE_URL", "SLSKD_API_KEY", "SLSKD_DOWNLOAD_DIR",
            "SPOTIFY_CLIENT_ID", "SPOTIFY_REDIRECT_URI",
    ):
        monkeypatch.delenv(env_var, raising=False)

    # config.py's module-level constants are fixed at import time (real
    # .env values baked in at the start of the whole test session) —
    # clearing os.environ alone doesn't touch them; the Application
    # property-level fallback (`self._config_store.X or config.X`)
    # still reads the frozen value unless patched directly. Same gap
    # test_application.py's own tests already have to work around.
    for attr in (
            "SLSKD_BASE_URL", "SLSKD_API_KEY", "SLSKD_DOWNLOAD_DIR",
            "SPOTIFY_CLIENT_ID", "SPOTIFY_REDIRECT_URI",
    ):
        monkeypatch.setattr(f"seeker.application.config.{attr}", None)

    data_dir = tmp_path / "platformdirs-data"
    monkeypatch.setattr(
        "seeker.application.platformdirs.user_data_dir",
        _fake_user_data_dir(data_dir),
    )

    application = Application()

    # A real, still-valid cached token — SpotifySyncService.list_playlists()
    # itself never touches the network (pure DB read), but merely
    # accessing the `sync_service` property constructs SpotifyClient via
    # auth_manager.get_valid_token(), which would otherwise try a real
    # OAuth round-trip. A far-future expires_at means get_valid_token()
    # returns this cached token directly, no refresh/authorize call.
    application._spotify_token_path.parent.mkdir(parents=True, exist_ok=True)
    TokenStore(application._spotify_token_path).save(
        SpotifyToken(
            access_token="fake-access",
            refresh_token="fake-refresh",
            expires_at=9_999_999_999.0,
        )
    )
    application._config_store = replace(
        application._config_store,
        spotify_client_id="fake-client-id",
        spotify_redirect_uri="http://127.0.0.1:8888/callback",
    )

    return application


def add_location(application: Application, name: str, path) -> LibraryLocation:
    path.mkdir(parents=True, exist_ok=True)
    return application.library_service.add_location(name, str(path))


def add_playlist(application: Application, playlist: Playlist) -> None:
    with application.database.transaction() as connection:
        application.sync_service.playlists.save(playlist, connection)


# --- Task 1: contextual help --------------------------------------------
#
# The persistent subtitle itself moved out of SettingsPage and into
# MainWindow's shared _build_page() wrapper (roadmap item 56 Phase 3
# §3.2 — routing through the same helper every other page uses is what
# fixed the real misprinted-header bug) — covered by
# test_ui_smoke.py::test_settings_page_shows_its_subtitle_via_build_page
# now, not here, since SettingsPage on its own no longer renders one.


def test_settings_window_controls_have_tooltips(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    for widget in (
            window.add_location_button,
            window.destination_location_combo,
            window.destination_subfolder_field,
            window.save_destination_button,
            window.spotify_client_id_field,
            window.reauthorize_spotify_button,
            window.reveal_api_key_button,
            window.test_connection_button,
            window.new_soulseek_username_field,
            window.new_soulseek_password_field,
            window.update_credentials_button,
            window.auto_match_threshold_field,
            window.needs_review_threshold_field,
            window.save_thresholds_button,
    ):
        assert widget.toolTip() != ""


# --- Library locations (§1) -------------------------------------------

def test_locations_tab_lists_existing_locations(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )
    assert window.locations_table.item(0, 0).text() == "Main"
    assert window.locations_table.item(0, 2).text() == "Yes"


def test_add_location_uses_the_chosen_folders_own_basename_as_the_name(
        qtbot, tmp_path, monkeypatch,
):
    # No name field anywhere in this flow (roadmap item 5) — a single
    # click picks a folder and registers it immediately under its own
    # basename.
    application = make_application(tmp_path, monkeypatch)
    chosen_path = tmp_path / "Chosen"
    chosen_path.mkdir()

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(chosen_path),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.add_location_button.click()

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )
    locations = application.library_service.list_locations()
    assert [loc.name for loc, _ in locations] == ["Chosen"]
    assert locations[0][0].path == str(chosen_path)


def test_add_location_for_an_already_registered_path_shows_an_inline_notice(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    existing_path = tmp_path / "Music"
    existing = add_location(application, "Music", existing_path)

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *a, **k: str(existing_path),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.add_location_button.click()

    qtbot.waitUntil(
        lambda: not window.locations_notice.isHidden(), timeout=2000,
    )
    assert existing.name in window.locations_notice.text()
    # No duplicate row was added — still just the one real location.
    assert application.library_service.list_locations()[0][0].name == "Music"
    assert len(application.library_service.list_locations()) == 1


def test_rename_location_updates_the_table(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )
    location = application.library_service.list_locations()[0][0]

    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("My Music", True),
    )
    window._on_rename_location_clicked(location.id, "Main")

    qtbot.waitUntil(
        lambda: window.locations_table.item(0, 0).text() == "My Music",
        timeout=2000,
    )


def test_rename_location_cancelled_makes_no_call(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )
    location = application.library_service.list_locations()[0][0]

    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("Ignored", False),
    )
    window._on_rename_location_clicked(location.id, "Main")

    assert window.locations_table.item(0, 0).text() == "Main"


def test_rename_location_collision_shows_an_inline_notice(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music1")
    add_location(application, "Other", tmp_path / "music2")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 2, timeout=2000,
    )
    other = next(
        loc for loc, _ in application.library_service.list_locations()
        if loc.name == "Other"
    )

    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("Main", True),
    )
    window._on_rename_location_clicked(other.id, "Other")

    qtbot.waitUntil(
        lambda: not window.locations_notice.isHidden(), timeout=2000,
    )
    assert "Main" in window.locations_notice.text()


def test_remove_location_calls_remove_location_with_correct_name(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )

    actions = window.locations_table.cellWidget(0, 3)
    remove_button = next(
        b for b in actions.findChildren(QPushButton) if b.text() == "Remove"
    )
    remove_button.click()

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 0, timeout=2000,
    )
    assert application.library_service.list_locations() == []


# --- Playlist destinations (§2) ----------------------------------------

def test_destinations_tab_lists_playlists_and_locations(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    add_playlist(
        application, Playlist(id="p1", name="240KM/H", track_count=3),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.destinations_playlist_list.count() == 1,
        timeout=2000,
    )
    assert window.destinations_playlist_list.item(0).text() == "240KM/H"
    assert window.destination_location_combo.findText("Main") != -1


def test_default_destination_group_lists_locations(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.default_location_combo.count() > 1, timeout=2000,
    )
    assert window.default_location_combo.findText("Main") != -1
    # Checked by default, per the task's own spec.
    assert window.default_subfolder_per_playlist_checkbox.isChecked()


def test_save_default_destination_persists_to_the_real_application(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    location = add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.default_location_combo.count() > 1, timeout=2000,
    )
    combo_index = window.default_location_combo.findData(location.id)
    window.default_location_combo.setCurrentIndex(combo_index)
    window.default_subfolder_per_playlist_checkbox.setChecked(False)

    window.save_default_destination_button.click()

    qtbot.waitUntil(
        lambda: window.default_destination_status_label.text() != "",
        timeout=2000,
    )
    assert (
        application._config_store.default_download_location_id
        == location.id
    )
    assert (
        application._config_store.default_download_subfolder_per_playlist
        is False
    )


def test_save_default_destination_without_a_location_shows_message(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.save_default_destination_button.click()

    assert "location" in window.default_destination_status_label.text().lower()


def test_default_destination_prefills_existing_config_value(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    location = add_location(application, "Main", tmp_path / "music")
    # Set directly on the in-memory config rather than via
    # persist_default_destination(): that method reloads from disk
    # first (real, safe production behavior — _config_store and disk
    # are always kept in sync by every persist_* method — but
    # make_application's own fake Spotify token setup above is
    # deliberately in-memory-only/never persisted, so a disk reload
    # here would silently discard it and break sync_service access
    # later in this test).
    application._config_store = replace(
        application._config_store,
        default_download_location_id=location.id,
        default_download_subfolder_per_playlist=False,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.default_location_combo.count() > 1, timeout=2000,
    )
    assert window.default_location_combo.currentData() == location.id
    assert not window.default_subfolder_per_playlist_checkbox.isChecked()


def test_save_destination_calls_set_destination_with_selected_values(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    add_playlist(
        application, Playlist(id="p1", name="240KM/H", track_count=3),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.destinations_playlist_list.count() == 1,
        timeout=2000,
    )
    window.destinations_playlist_list.setCurrentRow(0)

    combo_index = window.destination_location_combo.findData("Main")
    window.destination_location_combo.setCurrentIndex(combo_index)
    window.destination_subfolder_field.setText("DnB")

    window.save_destination_button.click()

    qtbot.waitUntil(
        lambda: window.destinations_status_label.text() != "",
        timeout=2000,
    )

    with application.database.transaction() as connection:
        playlist = application.sync_service.playlists.get_by_name(
            "240KM/H", connection,
        )
    assert playlist.download_subfolder == "DnB"


def test_save_destination_without_selected_playlist_shows_message(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.save_destination_button.click()

    assert "playlist" in window.destinations_status_label.text().lower()


def test_destination_subfolder_return_pressed_saves_destination(
        qtbot, tmp_path, monkeypatch,
):
    # Roadmap item 95 (B1.3).
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    add_playlist(
        application, Playlist(id="p1", name="240KM/H", track_count=3),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.destinations_playlist_list.count() == 1,
        timeout=2000,
    )
    window.destinations_playlist_list.setCurrentRow(0)

    combo_index = window.destination_location_combo.findData("Main")
    window.destination_location_combo.setCurrentIndex(combo_index)
    window.destination_subfolder_field.setText("DnB")

    window.destination_subfolder_field.returnPressed.emit()

    qtbot.waitUntil(
        lambda: window.destinations_status_label.text() != "",
        timeout=2000,
    )

    with application.database.transaction() as connection:
        playlist = application.sync_service.playlists.get_by_name(
            "240KM/H", connection,
        )
    assert playlist.download_subfolder == "DnB"


# --- Connection management (§3) -----------------------------------------

def test_connection_tab_displays_current_config_values(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_username="realuser",
        slskd_password="realpass",
        slskd_api_key="real-api-key",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.spotify_client_id_field.text() == "fake-client-id"
    assert window.soulseek_username_display.text() == "realuser"
    # Password never shown in plain text, only a fixed mask.
    assert window.soulseek_password_display.text() == "••••••••"
    assert window.soulseek_api_key_display.text() == "••••••••"


def test_reveal_api_key_toggle_shows_and_hides_the_real_value(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store, slskd_api_key="real-api-key",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.reveal_api_key_button.click()
    assert window.soulseek_api_key_display.text() == "real-api-key"

    window.reveal_api_key_button.click()
    assert window.soulseek_api_key_display.text() == "••••••••"


def test_reauthorize_spotify_calls_connect_spotify_with_force_flag(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        application,
        "connect_spotify",
        lambda client_id, force_reauthorize=False: calls.append(
            (client_id, force_reauthorize)
        ),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.spotify_client_id_field.setText("new-client-id")
    window.reauthorize_spotify_button.click()

    qtbot.waitUntil(lambda: calls != [], timeout=2000)
    assert calls == [("new-client-id", True)]


def test_spotify_client_id_return_pressed_calls_connect_spotify(
        qtbot, tmp_path, monkeypatch,
):
    # Roadmap item 95 (B1.3).
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        application,
        "connect_spotify",
        lambda client_id, force_reauthorize=False: calls.append(
            (client_id, force_reauthorize)
        ),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.spotify_client_id_field.setText("new-client-id")
    window.spotify_client_id_field.returnPressed.emit()

    qtbot.waitUntil(lambda: calls != [], timeout=2000)
    assert calls == [("new-client-id", True)]


def test_test_connection_reports_healthy_result(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_base_url="http://localhost:5030",
        slskd_api_key="real-api-key",
    )

    monkeypatch.setattr(
        "seeker.ui.settings_window.check_slskd_health",
        lambda base_url, api_key, since: SlskdHealthCheckResult(
            SlskdHealthStatus.HEALTHY,
        ),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.test_connection_button.click()

    qtbot.waitUntil(
        lambda: window.test_connection_status_label.text() != "",
        timeout=2000,
    )
    assert window.test_connection_status_label.text() == "Connected."


def test_test_connection_without_config_shows_message_and_makes_no_call(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "seeker.ui.settings_window.check_slskd_health",
        lambda *a, **k: calls.append(1),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.test_connection_button.click()

    assert calls == []
    assert "configured" in window.test_connection_status_label.text().lower()


def test_update_credentials_calls_bring_up_and_persists_on_success(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    bring_up_calls = []

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_bring_up(**kwargs):
        bring_up_calls.append(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        "seeker.ui.settings_window.bring_up_slskd", fake_bring_up,
    )
    monkeypatch.setattr(
        "seeker.ui.settings_window.generate_api_key",
        lambda: "generated-key",
    )
    monkeypatch.setattr(
        "seeker.ui.settings_window.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    # _locations_by_name is populated by the async _refresh_locations()
    # call in __init__ — _on_update_credentials_clicked needs it
    # populated to resolve library_location_path.
    qtbot.waitUntil(
        lambda: window._locations_by_name != {}, timeout=2000,
    )

    window.new_soulseek_username_field.setText("realuser")
    window.new_soulseek_password_field.setText("realpass")
    window.update_credentials_button.click()

    qtbot.waitUntil(lambda: bring_up_calls != [], timeout=2000)
    assert bring_up_calls[0]["soulseek_username"] == "realuser"
    assert bring_up_calls[0]["soulseek_password"] == "realpass"
    assert bring_up_calls[0]["api_key"] == "generated-key"

    qtbot.waitUntil(
        lambda: application._config_store.slskd_username == "realuser",
        timeout=2000,
    )
    assert application._config_store.slskd_password == "realpass"
    assert application._config_store.slskd_api_key == "generated-key"


def test_soulseek_password_return_pressed_calls_update_credentials(
        qtbot, tmp_path, monkeypatch,
):
    # Roadmap item 95 (B1.3) — the SoulSeek credentials form the brief
    # names directly.
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    bring_up_calls = []

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_bring_up(**kwargs):
        bring_up_calls.append(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        "seeker.ui.settings_window.bring_up_slskd", fake_bring_up,
    )
    monkeypatch.setattr(
        "seeker.ui.settings_window.generate_api_key",
        lambda: "generated-key",
    )
    monkeypatch.setattr(
        "seeker.ui.settings_window.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._locations_by_name != {}, timeout=2000,
    )

    window.new_soulseek_username_field.setText("realuser")
    window.new_soulseek_password_field.setText("realpass")
    window.new_soulseek_password_field.returnPressed.emit()

    qtbot.waitUntil(lambda: bring_up_calls != [], timeout=2000)
    assert bring_up_calls[0]["soulseek_username"] == "realuser"
    assert bring_up_calls[0]["soulseek_password"] == "realpass"


def test_update_credentials_without_username_or_password_makes_no_call(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "seeker.ui.settings_window.bring_up_slskd",
        lambda **kwargs: calls.append(1),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.update_credentials_button.click()

    assert calls == []
    assert "username" in window.update_credentials_status_label.text().lower()


def test_update_credentials_without_a_library_location_shows_message(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "seeker.ui.settings_window.bring_up_slskd",
        lambda **kwargs: calls.append(1),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.new_soulseek_username_field.setText("realuser")
    window.new_soulseek_password_field.setText("realpass")
    window.update_credentials_button.click()

    assert calls == []
    assert "location" in window.update_credentials_status_label.text().lower()


# --- Thresholds (§4) -----------------------------------------------------

def test_thresholds_tab_prefilled_with_hardcoded_defaults_when_unset(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.auto_match_threshold_field.text() == "90.0"
    assert window.needs_review_threshold_field.text() == "70.0"


def test_thresholds_tab_prefilled_with_existing_config_value(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        auto_match_threshold=85.0,
        needs_review_threshold=60.0,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.auto_match_threshold_field.text() == "85.0"
    assert window.needs_review_threshold_field.text() == "60.0"


def test_save_thresholds_persists_valid_values(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setText("85")
    window.needs_review_threshold_field.setText("65")
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold == 85.0
    assert application._config_store.needs_review_threshold == 65.0
    assert "saved" in window.thresholds_status_label.text().lower()


def test_needs_review_threshold_return_pressed_saves_thresholds(
        qtbot, tmp_path, monkeypatch,
):
    # Roadmap item 95 (B1.3).
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setText("85")
    window.needs_review_threshold_field.setText("65")
    window.needs_review_threshold_field.returnPressed.emit()

    assert application._config_store.auto_match_threshold == 85.0
    assert application._config_store.needs_review_threshold == 65.0
    assert "saved" in window.thresholds_status_label.text().lower()


# --- Roadmap item R4.2: cover.jpg sidecar toggle --------------------------

def test_write_cover_jpg_checkbox_unchecked_by_default(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.write_cover_jpg_checkbox.isChecked() is False


def test_write_cover_jpg_checkbox_prefilled_from_existing_config(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store, write_cover_jpg_sidecars=True,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.write_cover_jpg_checkbox.isChecked() is True


def test_write_cover_jpg_checkbox_saves_immediately_on_toggle(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.write_cover_jpg_checkbox.setChecked(True)
    assert application._config_store.write_cover_jpg_sidecars is True

    window.write_cover_jpg_checkbox.setChecked(False)
    assert application._config_store.write_cover_jpg_sidecars is False


def test_save_thresholds_rejects_inverted_pair(qtbot, tmp_path, monkeypatch):
    # A real logic bug, not just a UX nicety — must be rejected before
    # ever reaching the config store.
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setText("70")
    window.needs_review_threshold_field.setText("90")
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold is None
    assert application._config_store.needs_review_threshold is None
    assert "less than" in window.thresholds_status_label.text().lower()


def test_save_thresholds_rejects_equal_pair(qtbot, tmp_path, monkeypatch):
    # Equal, not just inverted, would collapse the needs-review band to
    # nothing — also a real logic bug.
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setText("80")
    window.needs_review_threshold_field.setText("80")
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold is None


def test_save_thresholds_rejects_non_numeric_input(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setText("not a number")
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold is None
    assert "number" in window.thresholds_status_label.text().lower()


# --- Roadmap item R7.5: menu-bar notification toggles ---------------------

def test_notification_checkboxes_all_checked_by_default(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.notify_downloads_finished_checkbox.isChecked() is True
    assert window.notify_needs_decision_checkbox.isChecked() is True
    assert window.notify_errors_checkbox.isChecked() is True


def test_notification_checkboxes_prefilled_from_existing_config(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        notify_downloads_finished=False,
        notify_needs_decision=False,
        notify_errors=False,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.notify_downloads_finished_checkbox.isChecked() is False
    assert window.notify_needs_decision_checkbox.isChecked() is False
    assert window.notify_errors_checkbox.isChecked() is False


def test_notification_checkboxes_save_immediately_on_toggle(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.notify_downloads_finished_checkbox.setChecked(False)
    assert application._config_store.notify_downloads_finished is False

    window.notify_needs_decision_checkbox.setChecked(False)
    assert application._config_store.notify_needs_decision is False

    window.notify_errors_checkbox.setChecked(False)
    assert application._config_store.notify_errors is False

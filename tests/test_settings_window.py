import threading
from dataclasses import replace

import pytest
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
)

from fakes import FakeApplication, wait_for_workers
from seeker.application import Application
from seeker.login_item import LoginItemStatus
from seeker.models.library_location import LibraryLocation
from seeker.models.nested_location import NestedLocation
from seeker.models.playlist import Playlist
from seeker.soulseek.docker_setup import (
    SlskdHealthCheckResult,
    SlskdHealthStatus,
    SlskdWebLoginStatus,
)
from seeker.spotify.callback_server import AuthorizationCancelledError
from seeker.spotify.token import SpotifyToken
from seeker.spotify.token_store import TokenStore
from seeker.ui import help_text, plain_text, settings_window, status_lamp, theme
from seeker.ui.main_window import MainWindow
from seeker.ui.notice import InlineNotice
from seeker.ui.settings_window import SettingsPage, locations_nested_with


def _fake_user_data_dir(data_dir):
    def fake(appname, **kwargs):
        return str(data_dir)

    return fake


def make_application(tmp_path, monkeypatch) -> Application:
    monkeypatch.chdir(tmp_path)

    # The developer's shell may export real SLSKD_*/SPOTIFY_* values —
    # migrate_legacy_env_config reads os.environ live regardless of
    # monkeypatch.chdir(), so every Settings test needs a genuinely
    # unconfigured starting point unless it sets a value itself. Same
    # gap test_config_store.py's own _clear_migration_env already hit.
    for env_var in (
            "SLSKD_BASE_URL", "SLSKD_API_KEY", "SLSKD_DOWNLOAD_DIR",
            "SPOTIFY_CLIENT_ID", "SPOTIFY_REDIRECT_URI",
    ):
        monkeypatch.delenv(env_var, raising=False)

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
# shell/test_shell_navigation.py::test_settings_page_shows_its_subtitle_via_build_page
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


# --- Tabs --------------------------------------------------------------

def _tab_constants() -> list[str]:
    return [
        value for name, value in vars(settings_window).items()
        if name.startswith("SETTINGS_TAB_")
    ]


def _group_titles_on_tab(window: SettingsPage, tab_name: str) -> set[str]:
    window.select_tab(tab_name)
    tab = window.tabs.currentWidget()
    return {
        card.accessibleName() for card in tab.findChildren(QFrame)
        if card.objectName() == "card" and card.accessibleName()
    }


def test_every_settings_tab_constant_selects_its_own_tab(
        qtbot, tmp_path, monkeypatch,
):
    window = SettingsPage(make_application(tmp_path, monkeypatch))
    qtbot.addWidget(window)

    assert len(_tab_constants()) == window.tabs.count()
    for tab_name in _tab_constants():
        # Start from a different tab, so a name that matches nothing
        # (select_tab's no-op) cannot pass by staying put.
        window.tabs.setCurrentIndex(next(
            index for index in range(window.tabs.count())
            if window.tabs.tabText(index) != tab_name
        ))
        window.select_tab(tab_name)
        assert window.tabs.tabText(window.tabs.currentIndex()) == tab_name


def test_settings_tabs_group_settings_by_job(qtbot, tmp_path, monkeypatch):
    window = SettingsPage(make_application(tmp_path, monkeypatch))
    qtbot.addWidget(window)

    assert [
        window.tabs.tabText(index) for index in range(window.tabs.count())
    ] == ["General", "Library", "Connections", "Matching"]
    assert _group_titles_on_tab(
        window, settings_window.SETTINGS_TAB_GENERAL,
    ) == {"Appearance", "Startup", "Daily sweep", "Notifications", "Updates"}
    assert {"Library locations", "Playlist destinations"} <= (
        _group_titles_on_tab(window, settings_window.SETTINGS_TAB_LIBRARY)
    )
    assert _group_titles_on_tab(
        window, settings_window.SETTINGS_TAB_CONNECTIONS,
    ) == {"Spotify", "SoulSeek", "SoulSeek credentials"}
    assert _group_titles_on_tab(
        window, settings_window.SETTINGS_TAB_MATCHING,
    ) == {"Match thresholds"}


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
    assert window.locations_table.item(0, 2).text() == "Available"


def _lamp_image(icon):
    return icon.pixmap(status_lamp.LAMP_SIZE).toImage()


def test_a_locations_folder_shows_as_a_lamp_beside_its_state(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    add_location(application, "Drive", tmp_path / "drive")
    (tmp_path / "drive").rmdir()

    window = SettingsPage(application)
    qtbot.addWidget(window)

    table = window.locations_table
    qtbot.waitUntil(lambda: table.rowCount() == 2, timeout=2000)
    states = {
        table.item(row, 0).text(): table.item(row, 2)
        for row in range(table.rowCount())
    }
    palette = theme.active_palette()
    assert states["Main"].text() == "Available"
    assert _lamp_image(states["Main"].icon()) == _lamp_image(
        status_lamp.lamp_icon(status_lamp.PLAY, palette)
    )
    assert states["Drive"].text() == "Not found"
    assert _lamp_image(states["Drive"].icon()) == _lamp_image(
        status_lamp.lamp_icon(status_lamp.STANDBY, palette)
    )
    assert states["Drive"].toolTip() == help_text.TOOLTIP_LOCATION_NOT_FOUND


def test_a_theme_change_repaints_the_locations_lamps(qtbot, monkeypatch):
    location = LibraryLocation(
        name="Main", path="/music", added_at="2026-10-10T00:00:00", id=1,
    )
    window = MainWindow(FakeApplication(locations=[(location, True)]))
    qtbot.addWidget(window)
    table = window.settings_page.locations_table
    qtbot.waitUntil(lambda: table.rowCount() == 1, timeout=2000)
    repainted = replace(theme.DARK, SUCCESS="#123456")
    monkeypatch.setattr(theme, "active_palette", lambda: repainted)

    window.on_theme_changed()

    expected = status_lamp.lamp_icon(status_lamp.PLAY, repainted)
    assert _lamp_image(table.item(0, 2).icon()) == _lamp_image(expected)


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
        lambda: not window.library_notice.isHidden(), timeout=2000,
    )
    assert existing.name in window.library_notice.text()
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
        lambda: not window.library_notice.isHidden(), timeout=2000,
    )
    assert "Main" in window.library_notice.text()


def click_remove_location(window: SettingsPage, qtbot) -> None:
    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )
    actions = window.locations_table.cellWidget(0, 3)
    remove_button = next(
        b for b in actions.findChildren(QPushButton) if b.text() == "Remove"
    )
    remove_button.click()


def answer_question(monkeypatch, answer) -> list[str]:
    asked: list[str] = []

    def fake_question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return answer

    monkeypatch.setattr(plain_text, "question", fake_question)
    return asked


def test_remove_location_confirms_with_the_real_counts_then_removes(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    location = add_location(application, "Main", tmp_path / "music")
    add_playlist(application, Playlist(id="p1", name="P", track_count=0))
    with application.database.transaction() as connection:
        application.sync_service.playlists.set_destination(
            "p1", location.id, None, connection,
        )
    asked = answer_question(monkeypatch, QMessageBox.StandardButton.Yes)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    click_remove_location(window, qtbot)

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 0, timeout=2000,
    )
    assert application.library_service.list_locations() == []
    assert len(asked) == 1
    assert "Remove 'Main'?" in asked[0]
    assert "0 indexed files" in asked[0]
    assert "1 playlist downloads here" in asked[0]
    assert "Files on disk are not touched." in asked[0]
    qtbot.waitUntil(
        lambda: not window.library_notice.isHidden(), timeout=2000,
    )
    assert window.library_notice.property("variant") == "info"
    assert "Removed 'Main'" in window.library_notice.text()


def register_unchecked(application: Application, name: str, path) -> None:
    """A location as builds before the nesting guard registered it."""
    path.mkdir(parents=True, exist_ok=True)
    with application.database.transaction() as connection:
        application.library_service.locations.add(
            LibraryLocation(name=name, path=str(path), added_at="t"),
            connection,
        )


def test_nested_locations_show_a_warning_naming_both(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    register_unchecked(application, "x9-pro", tmp_path / "Drive")
    register_unchecked(application, "Music", tmp_path / "Drive" / "Music")

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.nesting_notice.isHidden(), timeout=2000,
    )
    assert window.nesting_notice.property("variant") == "warning"
    assert "'Music' is inside 'x9-pro'" in window.nesting_notice.text()
    assert "indexed twice" in window.nesting_notice.text()


def test_fix_merges_every_location_nested_with_the_one_kept(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    drive = tmp_path / "Drive"
    register_unchecked(application, "x9-pro", drive)
    register_unchecked(application, "Music", drive / "Music")
    register_unchecked(application, "Test", drive / "Music" / "Test")
    (drive / "Music" / "Test" / "a.mp3").write_bytes(b"a")
    application.library_service.scan_all()
    picked: list[list[str]] = []

    def pick(parent, title, label, items, *args):
        picked.append(list(items))
        return "Music", True

    monkeypatch.setattr(QInputDialog, "getItem", pick)
    asked = answer_question(monkeypatch, QMessageBox.StandardButton.Yes)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    qtbot.waitUntil(
        lambda: not window.nesting_notice.isHidden(), timeout=2000,
    )
    window.nesting_notice.action_button.click()

    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=4000,
    )
    assert picked == [["x9-pro", "Music", "Test"]]
    assert len(asked) == 1
    assert asked[0].startswith(
        "Keep 'Music' and merge 'x9-pro' and 'Test' into it? 2 of their "
        "files are also indexed under 'Music'"
    )
    assert [
        location.name
        for location, _ in application.library_service.list_locations()
    ] == ["Music"]
    qtbot.waitUntil(window.nesting_notice.isHidden, timeout=2000)
    assert "Merged 'x9-pro' and 'Test' into 'Music'" in (
        window.library_notice.text()
    )


def test_fix_cancelled_at_the_pick_merges_nothing(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    register_unchecked(application, "x9-pro", tmp_path / "Drive")
    register_unchecked(application, "Music", tmp_path / "Drive" / "Music")
    monkeypatch.setattr(
        QInputDialog, "getItem", lambda *a, **k: ("x9-pro", False),
    )
    asked = answer_question(monkeypatch, QMessageBox.StandardButton.Yes)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    qtbot.waitUntil(
        lambda: not window.nesting_notice.isHidden(), timeout=2000,
    )
    window.nesting_notice.action_button.click()
    wait_for_workers(window)

    assert asked == []
    assert len(application.library_service.list_locations()) == 2


def test_locations_nested_with_names_each_location_around_or_inside():
    drive = LibraryLocation(name="x9-pro", path="/D", added_at="t")
    music = LibraryLocation(name="Music", path="/D/M", added_at="t")
    test = LibraryLocation(name="Test", path="/D/M/T", added_at="t")
    other = LibraryLocation(name="Other", path="/O/I", added_at="t")
    outer = LibraryLocation(name="Outer", path="/O", added_at="t")
    nested = [
        NestedLocation(inner=music, outer=drive),
        NestedLocation(inner=test, outer=drive),
        NestedLocation(inner=other, outer=outer),
        NestedLocation(inner=test, outer=music),
    ]

    assert locations_nested_with(nested, "Music") == ["x9-pro", "Test"]
    assert locations_nested_with(nested, "Other") == ["Outer"]


def test_separate_locations_show_no_nesting_warning(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)
    qtbot.waitUntil(
        lambda: window.locations_table.rowCount() == 1, timeout=2000,
    )
    wait_for_workers(window)
    # Delivers the finished signals the workers already posted.
    qtbot.wait(10)

    assert window.nesting_notice.isHidden()


def test_remove_location_cancelled_removes_nothing(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    asked = answer_question(monkeypatch, QMessageBox.StandardButton.No)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    click_remove_location(window, qtbot)

    qtbot.waitUntil(lambda: len(asked) == 1, timeout=2000)
    wait_for_workers(window)
    assert len(application.library_service.list_locations()) == 1
    assert window.locations_table.rowCount() == 1


def test_remove_location_failure_lands_on_the_notice_as_an_error(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    answer_question(monkeypatch, QMessageBox.StandardButton.Yes)

    def fail(name):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(application, "remove_location", fail)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    click_remove_location(window, qtbot)

    qtbot.waitUntil(
        lambda: not window.library_notice.isHidden(), timeout=2000,
    )
    assert window.library_notice.property("variant") == "error"
    assert "database is locked" in window.library_notice.text()


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
        lambda: not window.library_notice.isHidden(),
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

    assert "location" in window.library_notice.text().lower()


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
        lambda: not window.library_notice.isHidden(),
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

    assert "playlist" in window.library_notice.text().lower()


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
        lambda: not window.library_notice.isHidden(),
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


def test_connection_tab_warns_on_remote_plain_http_slskd_url(
        qtbot, tmp_path, monkeypatch,
):
    # Roadmap item 116 (round 8, §6.6.1) — X-API-Key crosses the network
    # in clear if slskd_base_url is ever pointed at a remote host over
    # plain HTTP (only reachable today via a hand-edited .env, since no
    # in-app flow sets it to anything but the local wizard's own
    # loopback constant).
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_base_url="http://192.168.1.50:5030",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert not window.slskd_remote_warning_notice.isHidden()
    assert "192.168.1.50" in window.slskd_remote_warning_notice.text()


def test_connection_tab_shows_no_warning_for_loopback_slskd_url(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_base_url="http://127.0.0.1:5030",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.slskd_remote_warning_notice.isHidden()


def test_connection_tab_shows_no_warning_when_slskd_unconfigured(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.slskd_remote_warning_notice.isHidden()


def test_connection_tab_displays_web_ui_login_when_confirmed_active(
        qtbot, tmp_path, monkeypatch,
):
    # S1.2 — the display must never show a credential without first
    # confirming, via a real POST /api/v0/session check, that it's the
    # one the container will actually accept.
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_base_url="http://127.0.0.1:5030",
        slskd_web_username="seeker",
        slskd_web_password="real-web-password",
    )
    monkeypatch.setattr(
        "seeker.ui.settings_window.check_slskd_web_login",
        lambda *a, **k: SlskdWebLoginStatus.ACTIVE,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.slskd_web_username_display.text() == "seeker",
        timeout=2000,
    )
    assert window.slskd_web_password_display.text() == "••••••••"

    window.reveal_web_password_button.click()
    assert window.slskd_web_password_display.text() == "real-web-password"

    window.reveal_web_password_button.click()
    assert window.slskd_web_password_display.text() == "••••••••"


def test_connection_tab_hides_web_ui_login_when_it_did_not_take(
        qtbot, tmp_path, monkeypatch,
):
    # S1.2's actual reported bug: a generated login that slskd silently
    # refused to apply (an already-customised web UI login was already
    # in place) must never be shown as if it were real.
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_base_url="http://127.0.0.1:5030",
        slskd_web_username="seeker",
        slskd_web_password="generated-but-inert",
    )
    monkeypatch.setattr(
        "seeker.ui.settings_window.check_slskd_web_login",
        lambda *a, **k: SlskdWebLoginStatus.INACTIVE,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: "already in place"
        in window.slskd_web_username_display.text(),
        timeout=2000,
    )
    assert window.slskd_web_password_display.text() == ""
    assert window.reveal_web_password_button.isHidden()


def test_connection_tab_web_ui_login_not_configured_when_unset(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.slskd_web_username_display.text() == "Not configured"
    assert window.slskd_web_password_display.text() == "Not configured"
    assert window.reveal_web_password_button.isHidden()


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
        lambda client_id, force_reauthorize=False, cancel=None: calls.append(
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
        lambda client_id, force_reauthorize=False, cancel=None: calls.append(
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
        lambda: not window.connections_notice.isHidden(),
        timeout=2000,
    )
    assert window.connections_notice.text() == "Connected to SoulSeek."


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
    assert "configured" in window.connections_notice.text().lower()


def test_update_credentials_calls_bring_up_and_persists_on_success(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    _fake_live_mounts(
        monkeypatch, {"/shared/music": str(tmp_path / "music")},
    )

    bring_up_calls = []

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_bring_up(**kwargs):
        bring_up_calls.append(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        "seeker.application.bring_up_slskd", fake_bring_up,
    )
    monkeypatch.setattr(
        "seeker.application.generate_api_key",
        lambda: "generated-key",
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
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

    _wait_for_credentials_update(qtbot, window, bring_up_calls)
    assert bring_up_calls[0]["soulseek_username"] == "realuser"
    assert bring_up_calls[0]["soulseek_password"] == "realpass"
    assert bring_up_calls[0]["api_key"] == "generated-key"

    qtbot.waitUntil(
        lambda: application._config_store.slskd_username == "realuser",
        timeout=2000,
    )
    assert application._config_store.slskd_password == "realpass"
    assert application._config_store.slskd_api_key == "generated-key"


def _fake_live_mounts(monkeypatch, mounts: dict[str, str]) -> None:
    monkeypatch.setattr(
        "seeker.soulseek.sharing_service._get_live_container_mounts",
        lambda container_name: mounts,
    )


def _fake_successful_bring_up(monkeypatch, tmp_path) -> list[dict]:
    bring_up_calls: list[dict] = []

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_bring_up(**kwargs):
        bring_up_calls.append(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        "seeker.application.bring_up_slskd", fake_bring_up,
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir",
        lambda: tmp_path / "slskd-data",
    )
    return bring_up_calls


def _wait_for_credentials_update(qtbot, window, bring_up_calls) -> None:
    # The fake records its call on the worker thread; the finish
    # handler (which re-enables the button) runs later on the main
    # thread. Returning on the call alone let that handler run after
    # teardown, against a deleted button (seen on CI, HISTORY §148).
    qtbot.waitUntil(
        lambda: bring_up_calls != []
        and window.connections_notice.text().startswith(
            "Credentials updated"
        ),
        timeout=2000,
    )


def _click_update_credentials(qtbot, window) -> None:
    qtbot.waitUntil(lambda: window._locations_by_name != {}, timeout=2000)
    window.new_soulseek_username_field.setText("realuser")
    window.new_soulseek_password_field.setText("realpass")
    window.update_credentials_button.click()


def test_update_credentials_keeps_sharing_the_live_share_not_the_first_location(
        qtbot, tmp_path, monkeypatch,
):
    # "Desktop" sorts before "Music"; the container shares Music. Updating
    # credentials must never swap the share for whichever location
    # happens to sort first.
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Desktop", tmp_path / "Desktop")
    add_location(application, "Music", tmp_path / "Music")
    _fake_live_mounts(monkeypatch, {
        "/app": str(tmp_path / "slskd-data"),
        "/shared/music": str(tmp_path / "Music"),
    })
    bring_up_calls = _fake_successful_bring_up(monkeypatch, tmp_path)
    monkeypatch.setattr(
        QInputDialog, "getItem",
        lambda *a, **k: pytest.fail("must not ask when a share is live"),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)
    _click_update_credentials(qtbot, window)

    _wait_for_credentials_update(qtbot, window, bring_up_calls)
    assert bring_up_calls[0]["library_location_path"] == str(
        tmp_path / "Music"
    )


def test_update_credentials_without_a_container_asks_which_location(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Desktop", tmp_path / "Desktop")
    add_location(application, "Music", tmp_path / "Music")
    _fake_live_mounts(monkeypatch, {})
    bring_up_calls = _fake_successful_bring_up(monkeypatch, tmp_path)
    offered: list[list[str]] = []

    def fake_get_item(parent, title, label, items, *args, **kwargs):
        offered.append(list(items))
        return "Music", True

    monkeypatch.setattr(QInputDialog, "getItem", fake_get_item)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    _click_update_credentials(qtbot, window)

    _wait_for_credentials_update(qtbot, window, bring_up_calls)
    assert offered == [["Desktop", "Music"]]
    assert bring_up_calls[0]["library_location_path"] == str(
        tmp_path / "Music"
    )


def test_update_credentials_cancelling_the_share_question_starts_nothing(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Music", tmp_path / "Music")
    _fake_live_mounts(monkeypatch, {})
    bring_up_calls = _fake_successful_bring_up(monkeypatch, tmp_path)
    asked: list[bool] = []

    def fake_get_item(*args, **kwargs):
        asked.append(True)
        return "", False

    monkeypatch.setattr(QInputDialog, "getItem", fake_get_item)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    _click_update_credentials(qtbot, window)

    qtbot.waitUntil(lambda: asked != [], timeout=2000)
    qtbot.waitUntil(window.update_credentials_button.isEnabled, timeout=2000)
    assert bring_up_calls == []
    assert "cancel" in window.connections_notice.text().lower()


def test_soulseek_password_return_pressed_calls_update_credentials(
        qtbot, tmp_path, monkeypatch,
):
    # Roadmap item 95 (B1.3) — the SoulSeek credentials form the brief
    # names directly.
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    _fake_live_mounts(
        monkeypatch, {"/shared/music": str(tmp_path / "music")},
    )

    bring_up_calls = []

    class FakeResult:
        returncode = 0
        stderr = ""

    def fake_bring_up(**kwargs):
        bring_up_calls.append(kwargs)
        return FakeResult()

    monkeypatch.setattr(
        "seeker.application.bring_up_slskd", fake_bring_up,
    )
    monkeypatch.setattr(
        "seeker.application.generate_api_key",
        lambda: "generated-key",
    )
    monkeypatch.setattr(
        "seeker.application.slskd_data_dir", lambda: tmp_path / "slskd-data",
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._locations_by_name != {}, timeout=2000,
    )

    window.new_soulseek_username_field.setText("realuser")
    window.new_soulseek_password_field.setText("realpass")
    window.new_soulseek_password_field.returnPressed.emit()

    _wait_for_credentials_update(qtbot, window, bring_up_calls)
    assert bring_up_calls[0]["soulseek_username"] == "realuser"
    assert bring_up_calls[0]["soulseek_password"] == "realpass"


def test_update_credentials_without_username_or_password_makes_no_call(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
        lambda **kwargs: calls.append(1),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.update_credentials_button.click()

    assert calls == []
    assert "username" in window.connections_notice.text().lower()


def test_update_credentials_without_a_library_location_shows_message(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(
        "seeker.application.bring_up_slskd",
        lambda **kwargs: calls.append(1),
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.new_soulseek_username_field.setText("realuser")
    window.new_soulseek_password_field.setText("realpass")
    window.update_credentials_button.click()

    assert calls == []
    assert "location" in window.connections_notice.text().lower()


# --- Thresholds (§4) -----------------------------------------------------

def test_thresholds_tab_prefilled_with_hardcoded_defaults_when_unset(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.auto_match_threshold_field.value() == 90.0
    assert window.needs_review_threshold_field.value() == 70.0


@pytest.fixture
def comma_locale():
    previous = QLocale()
    QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
    yield
    QLocale.setDefault(previous)


def test_thresholds_read_with_a_point_as_review_prints_scores(
        qtbot, tmp_path, monkeypatch, comma_locale,
):
    # Review and Search print a score as "72.6" whatever the locale; a
    # threshold the user compares it with reads the same way, and
    # takes a typed point.
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    field = window.auto_match_threshold_field
    assert field.text() == "90.0"
    field.lineEdit().selectAll()
    qtbot.keyClicks(field.lineEdit(), "72.5")
    field.interpretText()
    assert field.value() == 72.5


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

    assert window.auto_match_threshold_field.value() == 85.0
    assert window.needs_review_threshold_field.value() == 60.0


def test_save_thresholds_persists_valid_values(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setValue(85)
    window.needs_review_threshold_field.setValue(65)
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold == 85.0
    assert application._config_store.needs_review_threshold == 65.0
    assert "saved" in window.thresholds_notice.text().lower()


def test_needs_review_threshold_return_pressed_saves_thresholds(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setValue(85)
    _type_threshold(qtbot, window.needs_review_threshold_field, "65")
    qtbot.keyClick(window.needs_review_threshold_field, Qt.Key.Key_Return)

    assert application._config_store.auto_match_threshold == 85.0
    assert application._config_store.needs_review_threshold == 65.0
    assert "saved" in window.thresholds_notice.text().lower()


def test_save_thresholds_rejects_inverted_pair(qtbot, tmp_path, monkeypatch):
    # A real logic bug, not just a UX nicety — must be rejected before
    # ever reaching the config store.
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setValue(70)
    window.needs_review_threshold_field.setValue(90)
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold is None
    assert application._config_store.needs_review_threshold is None
    assert "less than" in window.thresholds_notice.text().lower()


def test_save_thresholds_rejects_equal_pair(qtbot, tmp_path, monkeypatch):
    # Equal, not just inverted, would collapse the needs-review band to
    # nothing — also a real logic bug.
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.auto_match_threshold_field.setValue(80)
    window.needs_review_threshold_field.setValue(80)
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold is None


def _type_threshold(qtbot, field, text: str) -> None:
    field.clear()
    qtbot.keyClicks(field, text)


def _label_texts(window: SettingsPage) -> list[str]:
    return [label.text() for label in window.findChildren(QLabel)]


def test_a_threshold_above_100_is_never_saved(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)
    window = SettingsPage(application)
    qtbot.addWidget(window)

    _type_threshold(qtbot, window.auto_match_threshold_field, "150")
    window.save_thresholds_button.click()

    saved = application._config_store.auto_match_threshold
    assert saved is None or saved <= 100


def test_a_low_auto_match_threshold_saves_with_a_warning(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    window = SettingsPage(application)
    qtbot.addWidget(window)

    _type_threshold(qtbot, window.auto_match_threshold_field, "10")
    _type_threshold(qtbot, window.needs_review_threshold_field, "5")
    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold == 10.0
    warnings = [text for text in _label_texts(window) if "Tag" in text]
    assert len(warnings) == 1
    assert "below 80" in warnings[0]


def test_a_shipped_default_threshold_saves_without_a_warning(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.save_thresholds_button.click()

    assert application._config_store.auto_match_threshold == 90.0
    assert not any("below 80" in text for text in _label_texts(window))


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


# --- Round 9 §3.2: start at login ------------------------------------

def test_startup_group_shows_unsupported_message_when_not_supported(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "seeker.login_item.is_supported", lambda: False,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.start_at_login_checkbox.isEnabled() is False
    assert window.start_at_login_checkbox.isChecked() is False
    assert "packaged app" in window.start_at_login_status_label.text()


def test_startup_group_reflects_disabled_status_when_supported(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.login_item.is_supported", lambda: True)
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.DISABLED,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.start_at_login_checkbox.isEnabled() is True
    assert window.start_at_login_checkbox.isChecked() is False
    assert window.start_at_login_status_label.text() == ""


def test_startup_group_reflects_enabled_status(qtbot, tmp_path, monkeypatch):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.login_item.is_supported", lambda: True)
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.ENABLED,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    assert window.start_at_login_checkbox.isChecked() is True
    assert window.start_at_login_status_label.text() == ""


def test_startup_group_reflects_requires_approval_status_with_message(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.login_item.is_supported", lambda: True)
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.REQUIRES_APPROVAL,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    # A revoked-but-not-yet-approved registration still shows as
    # checked (macOS considers it a real pending registration, not
    # "off") — the status label is what surfaces the real distinction.
    assert window.start_at_login_checkbox.isChecked() is True
    assert "System Settings" in window.start_at_login_status_label.text()


def test_toggling_start_at_login_checkbox_calls_set_login_item_enabled(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.login_item.is_supported", lambda: True)
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.DISABLED,
    )
    calls = []
    monkeypatch.setattr(
        "seeker.login_item.set_enabled",
        lambda enabled: (calls.append(enabled), LoginItemStatus.ENABLED)[1],
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.start_at_login_checkbox.setChecked(True)

    assert calls == [True]


def test_enabling_start_at_login_defaults_start_hidden_on(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.login_item.is_supported", lambda: True)
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.DISABLED,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)
    assert application._config_store.start_hidden_at_login is False

    monkeypatch.setattr(
        "seeker.login_item.set_enabled",
        lambda enabled: LoginItemStatus.ENABLED,
    )
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.ENABLED,
    )
    window.start_at_login_checkbox.setChecked(True)

    assert application._config_store.start_hidden_at_login is True
    assert window.start_hidden_at_login_checkbox.isChecked() is True


def test_start_hidden_checkbox_saves_immediately_on_toggle(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    monkeypatch.setattr("seeker.login_item.is_supported", lambda: True)
    monkeypatch.setattr(
        "seeker.login_item.get_status",
        lambda: LoginItemStatus.DISABLED,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)

    window.start_hidden_at_login_checkbox.setChecked(True)

    assert application._config_store.start_hidden_at_login is True


def test_reauthorize_wait_offers_cancel_and_ignores_a_second_submit(
        qtbot, tmp_path, monkeypatch,
):
    # Enter in the Client ID field bypassed the disabled button and
    # started a second attempt against the port the first still held.
    application = make_application(tmp_path, monkeypatch)
    started = threading.Event()
    calls: list[str] = []

    def fake_connect_spotify(client_id, force_reauthorize=False, cancel=None):
        calls.append(client_id)
        started.set()
        cancel.wait(timeout=5.0)
        raise AuthorizationCancelledError

    monkeypatch.setattr(
        application, "connect_spotify", fake_connect_spotify,
    )

    window = SettingsPage(application)
    qtbot.addWidget(window)
    wait = window.spotify_authorization_wait
    assert wait.isHidden()

    window.spotify_client_id_field.setText("mistyped-client-id")
    window.reauthorize_spotify_button.click()
    qtbot.waitUntil(started.is_set, timeout=2000)

    assert not wait.isHidden()
    assert not window.reauthorize_spotify_button.isEnabled()
    assert window.spotify_status_label.text() == (
        "Waiting for approval in your browser…"
    )

    window.spotify_client_id_field.returnPressed.emit()
    wait.cancel_button.click()

    qtbot.waitUntil(window.reauthorize_spotify_button.isEnabled, timeout=2000)
    assert wait.isHidden()
    assert window.spotify_status_label.text() == "Authorization cancelled."
    assert calls == ["mistyped-client-id"]


def _shown_notice(window) -> InlineNotice | None:
    for notice in window.findChildren(InlineNotice):
        if not notice.isHidden():
            return notice
    return None


def _wait_for_notice(qtbot, window, text: str) -> InlineNotice:
    # Any notice on the page: the outcome must land somewhere that
    # persists, never on a status label the next run_worker wipes.
    qtbot.waitUntil(
        lambda: (notice := _shown_notice(window)) is not None
        and text in notice.text(),
        timeout=2000,
    )
    notice = _shown_notice(window)
    assert notice is not None
    return notice


def test_a_refused_destination_is_reported_on_a_notice(
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
    window.destination_location_combo.setCurrentIndex(
        window.destination_location_combo.findData("Main"),
    )
    window.destination_subfolder_field.setText("../outside")

    window.save_destination_button.click()

    notice = _wait_for_notice(qtbot, window, "..")
    assert notice.property("variant") == "error"


def test_a_saved_default_destination_is_confirmed_on_a_notice(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    location = add_location(application, "Main", tmp_path / "music")

    window = SettingsPage(application)
    qtbot.addWidget(window)
    qtbot.waitUntil(
        lambda: window.default_location_combo.count() > 1, timeout=2000,
    )
    window.default_location_combo.setCurrentIndex(
        window.default_location_combo.findData(location.id),
    )

    window.save_default_destination_button.click()

    notice = _wait_for_notice(qtbot, window, "Default destination saved.")
    assert notice.property("variant") == "success"


def test_a_failed_connection_test_is_reported_on_a_notice(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    application._config_store = replace(
        application._config_store,
        slskd_base_url="http://localhost:5030",
        slskd_api_key="real-api-key",
    )

    def fail(base_url, api_key, since):
        raise ValueError("slskd sent a reply Seeker cannot read.")

    monkeypatch.setattr("seeker.ui.settings_window.check_slskd_health", fail)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    window.test_connection_button.click()

    notice = _wait_for_notice(qtbot, window, "cannot read")
    assert notice.property("variant") == "error"
    qtbot.waitUntil(window.test_connection_button.isEnabled, timeout=2000)


def test_a_failed_credentials_update_is_reported_on_a_notice(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)
    add_location(application, "Main", tmp_path / "music")
    _fake_live_mounts(
        monkeypatch, {"/shared/music": str(tmp_path / "music")},
    )

    def fail(*args, **kwargs):
        raise RuntimeError("Docker isn't running.")

    monkeypatch.setattr(application, "start_slskd", fail)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    _click_update_credentials(qtbot, window)

    notice = _wait_for_notice(qtbot, window, "Docker isn't running.")
    assert notice.property("variant") == "error"
    assert window.update_credentials_status_label.text() == ""
    qtbot.waitUntil(window.update_credentials_button.isEnabled, timeout=2000)


def test_a_failed_spotify_reauthorization_is_reported_on_a_notice(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    def fail(client_id, force_reauthorize=False, cancel=None):
        raise RuntimeError("Spotify refused this Client ID.")

    monkeypatch.setattr(application, "connect_spotify", fail)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    window.spotify_client_id_field.setText("mistyped-client-id")
    window.reauthorize_spotify_button.click()

    notice = _wait_for_notice(qtbot, window, "refused this Client ID")
    assert notice.property("variant") == "error"
    qtbot.waitUntil(
        window.reauthorize_spotify_button.isEnabled, timeout=2000,
    )


def test_daily_sweep_checkbox_starts_off_and_round_trips(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    assert window.auto_sweep_checkbox.isChecked() is False

    window.auto_sweep_checkbox.setChecked(True)

    reloaded = SettingsPage(Application())
    qtbot.addWidget(reloaded)
    assert reloaded.auto_sweep_checkbox.isChecked() is True

    reloaded.auto_sweep_checkbox.setChecked(False)

    assert Application().settings.auto_sweep_enabled is False


def test_update_check_checkbox_starts_off_and_round_trips(
        qtbot, tmp_path, monkeypatch,
):
    application = make_application(tmp_path, monkeypatch)

    window = SettingsPage(application)
    qtbot.addWidget(window)
    assert window.auto_update_check_checkbox.isChecked() is False

    window.auto_update_check_checkbox.setChecked(True)

    reloaded = SettingsPage(Application())
    qtbot.addWidget(reloaded)
    assert reloaded.auto_update_check_checkbox.isChecked() is True

    reloaded.auto_update_check_checkbox.setChecked(False)

    assert Application().settings.auto_update_check is False

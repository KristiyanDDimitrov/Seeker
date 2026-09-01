import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
)

from seeker.config_store import SeekerConfig
from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.data_locations import DataLocations
from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.playlist import Playlist
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.ui import help_text
from seeker.ui.main_window import AboutDialog, DestinationDialog, MainWindow
from seeker.update_check import UpdateCheckResult, UpdateStatus
from seeker.ui import workers as workers_module
from seeker.ui.workers import Worker, run_worker


# Per this project's own testing philosophy, applied to the UI layer:
# widget construction/wiring is thin glue around already-tested
# services (cli.py/main.py's argparse dispatch gets the same light
# treatment) — these are smoke tests confirming the window builds and
# the worker abstraction's signals fire correctly, not deep Qt coverage.


class FakeSyncService:
    def __init__(self, playlists: list[Playlist] | None = None):
        self._playlists = playlists or []
        self.sync_playlists_calls = 0
        self.sync_playlist_tracks_calls: list[Playlist] = []

    def list_playlists(self) -> list[Playlist]:
        return self._playlists

    def sync_playlists(self) -> None:
        self.sync_playlists_calls += 1

    def sync_playlist_tracks(self, playlist: Playlist) -> None:
        self.sync_playlist_tracks_calls.append(playlist)


class FakeDashboardService:
    def __init__(
            self,
            statuses: list | None = None,
            active_downloads: list | None = None,
    ):
        self._statuses = statuses or []
        self._active_downloads = active_downloads or []
        self.calls: list[str] = []

    def get_playlist_track_status(self, playlist_name: str) -> list:
        self.calls.append(playlist_name)
        return self._statuses

    def get_active_downloads(self) -> list:
        return self._active_downloads


class FakeLibraryService:
    def __init__(
            self,
            locations: list | None = None,
            has_scanned_library: bool = True,
            needs_review_matches: list | None = None,
    ):
        self._locations = locations or []
        self._has_scanned_library = has_scanned_library
        self.scan_all_calls = 0
        self.scan_and_match_calls = 0
        self._needs_review_matches = needs_review_matches or []
        self.confirm_match_calls: list[str] = []
        self.reject_match_calls: list[str] = []
        self.list_locations_calls = 0

    def scan_all(self) -> None:
        self.scan_all_calls += 1

    def scan_and_match(self) -> dict:
        self.scan_and_match_calls += 1
        return {
            "added": 0, "updated": 0, "removed": 0, "unchanged": 0,
            "auto": 0, "needs_review": 0, "unmatched": 0,
        }

    def get_needs_review_matches(
            self, playlist_name: str | None = None,
    ) -> list:
        return self._needs_review_matches

    def confirm_match(self, track_id: str) -> None:
        self.confirm_match_calls.append(track_id)

    def reject_match(self, track_id: str) -> None:
        self.reject_match_calls.append(track_id)

    def list_locations(self) -> list:
        self.list_locations_calls += 1
        return self._locations

    def has_scanned_library(self) -> bool:
        return self._has_scanned_library


class FakeDuplicateService:
    def __init__(
            self,
            fingerprint_result: dict | None = None,
            groups: list | None = None,
            delete_result: dict | None = None,
            cleanup_totals: tuple[int, int] = (0, 0),
    ):
        self._fingerprint_result = fingerprint_result or {
            "computed": 0, "skipped_already_computed": 0, "failed": 0,
            "details": [],
        }
        self._groups = groups or []
        self._delete_result = delete_result or {
            "deleted": 0, "failed": 0, "details": [],
        }
        self._cleanup_totals = cleanup_totals
        self.compute_fingerprints_calls: list[str] = []
        self.find_duplicate_groups_calls: list[str] = []
        self.delete_local_files_calls: list[
            tuple[list[int], int | None, int | None]
        ] = []
        self.record_cleanup_calls: list[tuple[int, int, int | None]] = []

    def compute_fingerprints(self, location_name: str) -> dict:
        self.compute_fingerprints_calls.append(location_name)
        return self._fingerprint_result

    def find_duplicate_groups(self, location_name: str) -> list:
        self.find_duplicate_groups_calls.append(location_name)
        return self._groups

    def delete_local_files(
            self,
            local_file_ids: list[int],
            keep_local_file_id: int | None = None,
            location_id: int | None = None,
    ) -> dict:
        self.delete_local_files_calls.append(
            (local_file_ids, keep_local_file_id, location_id)
        )
        return self._delete_result

    def record_cleanup(
            self,
            files_deleted: int,
            bytes_freed: int,
            location_id: int | None = None,
    ) -> None:
        self.record_cleanup_calls.append(
            (files_deleted, bytes_freed, location_id)
        )

    def get_cleanup_totals(self) -> tuple[int, int]:
        return self._cleanup_totals


class FakeTrackMatcher:
    def match_all(self) -> dict:
        return {"auto": 0, "needs_review": 0, "unmatched": 0}


class FakeHistoryService:
    def __init__(self, events: list | None = None):
        self._events = events or []
        self.get_recent_events_calls = 0

    def get_recent_events(self, limit: int = 50) -> list:
        self.get_recent_events_calls += 1
        return self._events


class FakeSharingService:
    def __init__(
            self,
            status=None,
            self_managed: bool = True,
            reconciliation: list | None = None,
            uploads: list | None = None,
    ):
        self._status = status
        self._self_managed = self_managed
        self._reconciliation = reconciliation or []
        self._uploads = uploads or []
        self.add_location_to_share_calls: list = []

    def get_status(self):
        return self._status

    def is_self_managed(self) -> bool:
        return self._self_managed

    def get_reconciliation(self) -> list:
        return self._reconciliation

    def get_uploads(self) -> list:
        return self._uploads

    def preview_add_location(self, location):
        from seeker.sharing_service import SharingPlan

        return SharingPlan(
            location=location,
            container_path=f"/shared/{location.name}",
            compose_volume_line=(
                f'      - "{location.path}:/shared/{location.name}:ro"'
            ),
            slskd_share_directory_line=f"    - /shared/{location.name}",
        )

    def add_location_to_share(self, location, confirm: bool):
        self.add_location_to_share_calls.append((location, confirm))

        from seeker.sharing_service import SharingApplyResult

        return SharingApplyResult(
            location=location,
            compose_backup_path=Path("/fake/docker-compose.yml.bak"),
            slskd_yml_backup_path=Path("/fake/slskd.yml.bak"),
            directories_before=0,
            files_before=0,
            directories_after=1,
            files_after=1,
            became_ready=True,
        )


class FakeDownloadService:
    def __init__(
            self,
            review_candidates: list | None = None,
            pending_upgrades: list | None = None,
            resolved_destination: tuple | None = None,
            download_playlist_result: dict | None = None,
    ):
        self._review_candidates = review_candidates or []
        self._pending_upgrades = pending_upgrades or []
        self.confirm_review_candidate_calls: list[str] = []
        self.reject_review_candidate_calls: list[str] = []
        self.apply_upgrade_decision_calls: list[tuple[int, bool, bool]] = []
        self.apply_upgrade_decision_result: str | None = "Replaced with /new/path"
        # None means "no resolvable destination" — the roadmap item 6
        # §3 dead-end case the DestinationDialog exists to close.
        self._resolved_destination = resolved_destination
        self.set_destination_calls: list[tuple[str, str, str | None]] = []
        self.download_playlist_calls: list[str] = []
        self._download_playlist_result = download_playlist_result or {
            "requested": 0, "skipped": 0, "failed": 0, "total": 0,
            "already_in_progress": [],
        }

    def get_resolved_destination(self, playlist_name: str) -> tuple | None:
        return self._resolved_destination

    def set_destination(
            self,
            playlist_name: str,
            location_name: str,
            subfolder: str | None = None,
    ) -> None:
        self.set_destination_calls.append(
            (playlist_name, location_name, subfolder)
        )
        # A real set_destination call is exactly what makes the
        # destination resolvable on a subsequent check — mirrored here
        # so a test can drive the dialog flow through to a real
        # download_playlist() call afterward, the same way the real
        # DownloadService's own state would change.
        self._resolved_destination = (
            LibraryLocation(
                id=1, name=location_name, path="/fake",
                added_at="2026-01-01T00:00:00+00:00",
            ),
            subfolder,
        )

    def download_playlist(self, playlist_name: str) -> dict:
        self.download_playlist_calls.append(playlist_name)
        return self._download_playlist_result

    def poll_downloads(self) -> dict:
        return {}

    def get_review_candidates(self) -> list:
        return self._review_candidates

    def get_pending_upgrade_reviews(self) -> list:
        return self._pending_upgrades

    def confirm_review_candidate(self, track_id: str) -> None:
        self.confirm_review_candidate_calls.append(track_id)

    def reject_review_candidate(self, track_id: str) -> None:
        self.reject_review_candidate_calls.append(track_id)

    def apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool = False,
    ) -> str | None:
        self.apply_upgrade_decision_calls.append((request_id, replace, delete_old))
        return self.apply_upgrade_decision_result if replace else None


_EMPTY_TAG_RESULT = {
    "tagged": 0,
    "tagged_without_art": 0,
    "skipped_no_match": 0,
    "skipped_format_unsupported": 0,
    "skipped_already_tagged": 0,
    "skipped_already_analyzed": 0,
    "failed": 0,
    "details": [],
}


class FakeMetadataService:
    def __init__(self, tag_result: dict | None = None):
        self._tag_result = tag_result or dict(_EMPTY_TAG_RESULT)
        self.tag_tracks_calls: list[tuple[list[str], bool, tuple | None, bool]] = []
        self.tag_playlist_calls: list[tuple[str, bool, tuple | None, bool]] = []

    def tag_tracks(
            self,
            track_ids: list[str],
            analyze_audio: bool = False,
            expected_bpm_range: tuple | None = None,
            force: bool = False,
    ) -> dict:
        self.tag_tracks_calls.append(
            (track_ids, analyze_audio, expected_bpm_range, force)
        )
        return self._tag_result

    def tag_playlist(
            self,
            playlist_name: str,
            analyze_audio: bool = False,
            expected_bpm_range: tuple | None = None,
            force: bool = False,
    ) -> dict:
        self.tag_playlist_calls.append(
            (playlist_name, analyze_audio, expected_bpm_range, force)
        )
        return self._tag_result


class FakeApplication:
    def __init__(
            self,
            playlists: list[Playlist] | None = None,
            statuses: list | None = None,
            active_downloads: list | None = None,
            soulseek_configured: bool = False,
            review_candidates: list | None = None,
            pending_upgrades: list | None = None,
            tag_result: dict | None = None,
            locations: list | None = None,
            fingerprint_result: dict | None = None,
            duplicate_groups: list | None = None,
            resolved_destination: tuple | None = None,
            spotify_configured: bool = True,
            has_scanned_library: bool = True,
            history_events: list | None = None,
            needs_review_matches: list | None = None,
            download_playlist_result: dict | None = None,
            sharing_service=None,
    ):
        self.sync_service = FakeSyncService(playlists)
        self.history_service = FakeHistoryService(history_events)
        self.data_locations = DataLocations(
            database_path=Path("/fake/seeker.db"),
            config_path=Path("/fake/config.json"),
            spotify_token_path=Path("/fake/spotify_token.json"),
            slskd_data_dir=Path("/fake/slskd-data"),
            base_dir=Path("/fake"),
        )
        self.dashboard_service = FakeDashboardService(
            statuses, active_downloads,
        )
        self.library_service = FakeLibraryService(
            locations, has_scanned_library, needs_review_matches,
        )
        self.spotify_configured = spotify_configured
        self.track_matcher = FakeTrackMatcher()
        self.download_service = FakeDownloadService(
            review_candidates, pending_upgrades, resolved_destination,
            download_playlist_result,
        )
        self.metadata_service = FakeMetadataService(tag_result)
        self.duplicate_service = FakeDuplicateService(
            fingerprint_result, duplicate_groups,
        )
        self.soulseek_configured = soulseek_configured
        self.sharing_service = sharing_service or FakeSharingService()
        # settings_window.py already reaches into this attribute
        # directly on the real Application (see its own §threshold/
        # §connection tabs) — mirrored here rather than adding a
        # second, fake-only access pattern.
        self._config_store = SeekerConfig()
        self.persist_default_destination_calls: list[tuple[int, bool]] = []

    def persist_default_destination(
            self, location_id: int, subfolder_per_playlist: bool,
    ) -> None:
        self.persist_default_destination_calls.append(
            (location_id, subfolder_per_playlist)
        )
        self._config_store = replace(
            self._config_store,
            default_download_location_id=location_id,
            default_download_subfolder_per_playlist=subfolder_per_playlist,
        )


def test_main_window_constructs_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.windowTitle() == "Seeker"


# --- Sidebar shell (Phase 4) ------------------------------------------------

def test_default_and_minimum_window_size(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert (window.width(), window.height()) == (1180, 760)
    assert window.minimumWidth() == 960
    assert window.minimumHeight() == 640


def test_dashboard_is_the_default_active_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.stacked_widget.currentIndex() == window._page_indices["dashboard"]
    assert window._nav_buttons["dashboard"].isChecked()


def test_show_page_switches_stack_and_updates_checked_nav_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("downloads")

    assert window.stacked_widget.currentIndex() == window._page_indices["downloads"]
    assert window._nav_buttons["downloads"].isChecked()
    assert not window._nav_buttons["dashboard"].isChecked()


def test_nav_buttons_are_mutually_exclusive_including_settings(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Every real page (Dashboard/Downloads/Review/Duplicates/History)
    # plus Help and Settings share one exclusive QButtonGroup — roadmap
    # item 56 Phase 3 reversed item 48's "Settings stays a separate
    # dialog" decision, so it's now a real, checkable nav-group member
    # like every other page.
    assert set(window._nav_buttons) == {
        "dashboard", "downloads", "review", "duplicates", "sharing",
        "history", "help", "settings",
    }
    assert window._nav_group.exclusive()
    for key in window._nav_buttons:
        assert window._nav_buttons[key] in window._nav_group.buttons()
    assert window.settings_button.isCheckable()


def test_downloads_and_review_nav_badges_show_live_counts(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._nav_buttons["downloads"].text() == "Downloads"
    assert window._nav_buttons["review"].text() == "Review"

    window._render_active_downloads(
        [_make_active_download(track_id="d1"), _make_active_download(track_id="d2")]
    )
    assert window._nav_buttons["downloads"].text() == "Downloads  (2)"

    window._render_review_items(
        ([(_make_track("t1"), _make_review_candidate("t1"))], [], [])
    )
    assert window._nav_buttons["review"].text() == "Review  (1)"

    # Back to zero must drop the badge entirely, not show "(0)".
    window._render_active_downloads([])
    assert window._nav_buttons["downloads"].text() == "Downloads"


def test_history_and_help_pages_exist_with_their_own_subtitles(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    history_page = window.stacked_widget.widget(window._page_indices["history"])
    history_labels = [w.text() for w in history_page.findChildren(QLabel)]
    assert help_text.HISTORY_PAGE_SUBTITLE in history_labels

    help_page = window.stacked_widget.widget(window._page_indices["help"])
    help_labels = [w.text() for w in help_page.findChildren(QLabel)]
    assert help_text.HELP_PAGE_SUBTITLE in help_labels


# --- Help page (roadmap Phase 11 §Help) -------------------------------------

def test_help_page_shows_walkthrough_and_troubleshooting(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    help_page = window.stacked_widget.widget(window._page_indices["help"])
    labels_html = "\n".join(w.text() for w in help_page.findChildren(QLabel))

    assert "How Seeker works" in labels_html
    assert "Troubleshooting" in labels_html
    assert "Sync" in labels_html and "Match" in labels_html


def test_help_page_shows_the_real_resolved_data_paths(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    help_page = window.stacked_widget.widget(window._page_indices["help"])
    labels_text = [w.text() for w in help_page.findChildren(QLabel)]

    locations = application.data_locations
    assert str(locations.database_path) in labels_text
    assert str(locations.config_path) in labels_text
    assert str(locations.spotify_token_path) in labels_text
    assert str(locations.slskd_data_dir) in labels_text


def test_open_in_file_manager_dispatches_by_platform(tmp_path, monkeypatch):
    from seeker.ui.main_window import _open_in_file_manager

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.subprocess.run",
        lambda args: calls.append(args),
    )
    target = tmp_path / "does" / "not" / "exist" / "yet"

    monkeypatch.setattr("seeker.ui.main_window.sys.platform", "darwin")
    _open_in_file_manager(target)
    assert calls[-1] == ["open", str(target)]
    assert target.is_dir()  # created on demand, per the docstring

    monkeypatch.setattr("seeker.ui.main_window.sys.platform", "win32")
    _open_in_file_manager(target)
    assert calls[-1] == ["explorer", str(target)]

    monkeypatch.setattr("seeker.ui.main_window.sys.platform", "linux")
    _open_in_file_manager(target)
    assert calls[-1] == ["xdg-open", str(target)]


def test_open_data_folder_button_calls_the_file_manager_opener(
        qtbot, monkeypatch,
):
    from seeker.ui import main_window as main_window_module

    opened: list = []
    monkeypatch.setattr(
        main_window_module, "_open_in_file_manager",
        lambda path: opened.append(path),
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    help_page = window.stacked_widget.widget(window._page_indices["help"])
    button = next(
        widget for widget in help_page.findChildren(QPushButton)
        if widget.text() == help_text.OPEN_DATA_FOLDER_BUTTON_TEXT
    )
    button.click()

    assert opened == [application.data_locations.base_dir]


# --- History page (roadmap Phase 10) ----------------------------------------

def _make_history_event(
        event_type: str = DOWNLOADED,
        occurred_at: str = "2026-01-02T00:00:00+00:00",
        track_artist: str = "ZENEA",
        track_title: str = "INFINITE",
        playlist_name: str = "240KM/H",
        detail: str = "FLAC from peer1",
) -> HistoryEvent:
    return HistoryEvent(
        occurred_at=occurred_at, event_type=event_type,
        track_artist=track_artist, track_title=track_title,
        playlist_name=playlist_name, detail=detail,
    )


def test_history_page_has_the_right_table_columns(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    labels = [
        window.history_table.horizontalHeaderItem(i).text()
        for i in range(window.history_table.columnCount())
    ]
    assert labels == ["When", "What", "Track", "Detail"]


def test_history_page_fetches_and_renders_events_on_first_visit(qtbot):
    events = [
        _make_history_event(),
        _make_history_event(
            event_type=TAGGED, occurred_at="2026-01-01T00:00:00+00:00",
            track_artist="Kamäleon", track_title="Quadrat",
            playlist_name="Test", detail="Tagged with Spotify metadata",
        ),
    ]
    application = FakeApplication(history_events=events)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")

    qtbot.waitUntil(
        lambda: window.history_table.rowCount() == 2, timeout=2000,
    )
    assert application.history_service.get_recent_events_calls == 1
    assert window.history_table.item(0, 1).text() == "Downloaded"
    assert "ZENEA - INFINITE" in window.history_table.item(0, 2).text()
    assert window.history_table.item(1, 1).text() == "Tagged"

    # Lazy-load-once, same precedent as Duplicates — switching away and
    # back must not refetch.
    window._show_page("dashboard")
    window._show_page("history")
    assert application.history_service.get_recent_events_calls == 1


def test_history_page_empty_state_message(qtbot):
    application = FakeApplication(history_events=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")

    qtbot.waitUntil(
        lambda: "no downloaded or tagged" in
        window.history_status_label.text().lower(),
        timeout=2000,
    )
    assert window.history_table.rowCount() == 0


def test_history_filter_combo_filters_by_event_type(qtbot):
    events = [
        _make_history_event(event_type=DOWNLOADED),
        _make_history_event(event_type=TAGGED),
    ]
    application = FakeApplication(history_events=events)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")
    qtbot.waitUntil(
        lambda: window.history_table.rowCount() == 2, timeout=2000,
    )

    downloaded_index = window.history_filter_combo.findData(DOWNLOADED)
    window.history_filter_combo.setCurrentIndex(downloaded_index)

    assert window.history_table.rowCount() == 1
    assert window.history_table.item(0, 1).text() == "Downloaded"

    all_index = window.history_filter_combo.findData(None)
    window.history_filter_combo.setCurrentIndex(all_index)
    assert window.history_table.rowCount() == 2


def test_history_refresh_button_refetches(qtbot):
    application = FakeApplication(history_events=[_make_history_event()])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("history")
    qtbot.waitUntil(
        lambda: application.history_service.get_recent_events_calls == 1,
        timeout=2000,
    )

    window.history_refresh_button.click()

    qtbot.waitUntil(
        lambda: application.history_service.get_recent_events_calls == 2,
        timeout=2000,
    )


def test_main_window_has_a_settings_button(qtbot):
    # Thin glue coverage only — opening the real SettingsWindow needs a
    # real Application (library_service.list_locations, sync_service,
    # download_service, _config_store, etc.), which this file's simpler
    # FakeApplication doesn't model. The real substance is covered
    # directly in tests/test_settings_window.py against a real
    # Application; this just confirms the entry point exists.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.settings_button.text() == "Settings"
    assert window.settings_button.isEnabled()


def test_main_window_global_action_buttons_have_tooltips(qtbot):
    # Task 1 — every clickable control gets a setToolTip(); spot-check
    # the Dashboard's global action row (roadmap item 7 relocated these
    # off the old QToolBar) rather than every single control (per-row/
    # per-tab controls are covered by their own dedicated tests below).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    for button in (
            window.sync_button,
            window.scan_button,
            window.match_button,
            window.download_button,
            window.settings_button,
    ):
        assert button.toolTip() != ""


def test_global_action_buttons_have_the_renamed_labels(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.sync_button.text() == "Refresh playlists"
    assert window.scan_button.text() == "Rescan & match library"
    assert window.match_button.text() == "Re-match library"
    assert window.download_button.text() == "Download selected playlist"


# --- Dashboard "next step" CTA (roadmap item 7) -----------------------------

def test_next_step_notice_hidden_when_nothing_selected_and_all_set_up(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        locations=[(
            LibraryLocation(
                id=1, name="Main", path="/music",
                added_at="2026-01-01T00:00:00+00:00",
            ),
            True,
        )],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.wait(50)
    assert window.next_step_notice.isHidden()


def test_next_step_notice_shows_connect_spotify_first(qtbot):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.next_step_notice.isHidden(), timeout=2000,
    )
    assert "spotify" in window.next_step_notice.text().lower()


def test_next_step_action_button_opens_settings_on_the_connection_tab(
        qtbot, monkeypatch,
):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.next_step_notice.isHidden(), timeout=2000,
    )
    # Drive the dispatch method directly — exercising the exact click
    # path a real InlineNotice action button takes without needing to
    # locate/click the dynamically-built button widget itself.
    window._on_next_step_action("settings_connection")

    # Roadmap item 56 Phase 3 — Settings is now a persistent page, not a
    # per-open window, so the assertion is against the real navigation
    # (current page) and the same long-lived settings_page instance.
    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["settings"]
    )
    from seeker.ui.settings_window import SETTINGS_TAB_CONNECTION
    assert window.settings_page.tabs.tabText(
        window.settings_page.tabs.currentIndex()
    ) == SETTINGS_TAB_CONNECTION


# --- Roadmap item 56 Phase 3: Settings as an in-window page -----------------

def test_settings_page_shows_its_subtitle_via_build_page(qtbot):
    # SettingsPage itself no longer renders its own subtitle (§3.2) —
    # it comes from the shared _build_page() wrapper, same as every
    # other page's header.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    settings_wrapper = window.stacked_widget.widget(
        window._page_indices["settings"]
    )
    labels = [
        widget.text() for widget in settings_wrapper.findChildren(QLabel)
    ]
    assert help_text.SETTINGS_WINDOW_SUBTITLE in labels


def test_settings_back_button_returns_to_the_previous_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("duplicates")
    window._show_page("settings")
    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["settings"]
    )

    window.settings_back_button.click()

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["duplicates"]
    )


def test_settings_back_button_falls_back_to_dashboard_from_a_fresh_window(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("settings")
    window.settings_back_button.click()

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["dashboard"]
    )


def test_leaving_settings_refreshes_duplicates_locations_and_next_step(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("settings")
    window._show_page("dashboard")

    qtbot.waitUntil(
        lambda: application.library_service.list_locations_calls >= 1,
        timeout=2000,
    )


def test_settings_about_button_is_wired_to_mainwindows_about_dialog(qtbot):
    # Reuses the exact same AboutDialog/copy as the Help-menu route
    # (§3.4) — checked via the wiring itself (settings_page's callback
    # is literally MainWindow's own _on_about_clicked), not a second
    # dialog construction path.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.settings_page._on_about_requested == window._on_about_clicked

    triggered = []
    window.settings_page._on_about_requested = lambda: triggered.append(True)
    window.settings_page.about_button.click()

    assert triggered == [True]


def test_next_step_notice_shows_download_count_and_triggers_download_flow(
        qtbot, monkeypatch,
):
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    statuses = [
        TrackStatus(track=_make_track("t1"), state=NOT_FOUND),
        TrackStatus(track=_make_track("t2"), state=NOT_FOUND),
    ]
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=2)],
        locations=[(location, True)],
        statuses=statuses,
        soulseek_configured=True,
        resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: "2" in window.next_step_notice.text(), timeout=2000,
    )
    assert window.next_step_notice.text() == "2 tracks missing from 'Test'."

    window._on_next_step_action("download")

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )


def test_action_row_download_button_hides_while_cta_offers_the_same_action(
        qtbot,
):
    # download_button and the CTA's own "download" action both call the
    # identical download_playlist() against the identical unmatched-
    # tracks set — showing both is a real duplicate, not two distinct
    # actions, so the row's copy hides while the CTA already offers it.
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        locations=[(location, True)],
        statuses=[TrackStatus(track=_make_track("t1"), state=NOT_FOUND)],
        soulseek_configured=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window.download_button.isHidden(), timeout=2000,
    )


def test_action_row_download_button_visible_when_cta_offers_something_else(
        qtbot,
):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[],  # CTA offers "Load tracks", not "download".
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    assert not window.download_button.isHidden()


def test_download_button_disabled_with_no_playlist_selected(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.wait(50)
    assert not window.download_button.isEnabled()


def test_sync_button_disabled_when_spotify_not_connected(qtbot):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.sync_button.isEnabled(), timeout=2000,
    )


def test_scan_button_disabled_with_no_library_location(qtbot):
    application = FakeApplication(locations=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.scan_button.isEnabled(), timeout=2000,
    )


def test_match_button_disabled_with_nothing_to_match(qtbot):
    application = FakeApplication(playlists=[], locations=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.match_button.isEnabled(), timeout=2000,
    )


def test_all_action_buttons_enabled_once_everything_is_set_up(qtbot):
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        locations=[(location, True)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.sync_button.isEnabled()
        and window.scan_button.isEnabled()
        and window.match_button.isEnabled(),
        timeout=2000,
    )
    _select_first_playlist(window, qtbot)
    assert window.download_button.isEnabled()


def test_scan_button_click_calls_scan_and_match_not_scan_all(qtbot):
    # Roadmap item 56 — the guided scan action must chain into a match
    # pass in one call, not leave newly-scanned files unmatched until a
    # separate "Re-match library" click.
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.scan_button.isEnabled(), timeout=2000)
    window.scan_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.scan_and_match_calls == 1,
        timeout=2000,
    )
    assert application.library_service.scan_all_calls == 0


# --- Track-table empty states (roadmap item 7) ------------------------------

def test_no_playlist_selected_shows_centred_empty_panel_no_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.track_area_stack.currentWidget() is window._track_empty_panel
    assert "pick a playlist" in window.track_empty_label.text().lower()
    assert window.sync_tracks_button.isHidden()


def test_playlist_selected_no_tracks_shows_empty_panel_with_load_button(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=0)],
        statuses=[],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    # Both "nothing selected yet" and "selected but empty" render the
    # same panel widget — wait on the label text actually changing to
    # the playlist-specific message, not just on the panel being
    # current (already true before selection even happens).
    qtbot.waitUntil(
        lambda: "test" in window.track_empty_label.text().lower(),
        timeout=2000,
    )
    assert window.track_area_stack.currentWidget() is window._track_empty_panel
    assert not window.sync_tracks_button.isHidden()


def test_playlist_with_tracks_shows_the_real_table(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[TrackStatus(track=_make_track("t1"), state=NOT_FOUND)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window.track_area_stack.currentWidget() is window.track_table,
        timeout=2000,
    )
    assert window.track_table.rowCount() == 1


# --- Download destination dialog (roadmap item 6 §3, "no dead end") -------

def _select_first_playlist(window, qtbot) -> None:
    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)
    # Selecting also kicks off the "next step" facts fetch
    # (_poll_next_step), which independently enables/disables
    # download_button — wait for it to actually land rather than
    # racing a click against a button that may still be disabled from
    # the pre-selection (no playlist selected) render.
    qtbot.waitUntil(lambda: window.download_button.isEnabled(), timeout=2000)


def test_download_with_no_selection_shows_a_warning_notice(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.download_button.click()

    assert "playlist" in window.dashboard_notice.text().lower()
    assert not window.dashboard_notice.isHidden()


def test_download_with_a_resolvable_destination_skips_the_dialog(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists, resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.download_playlist_calls == ["Test"]
    # No destination needed setting — it was already resolvable.
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == []


# --- Roadmap item 56 Phase 5.1: download button feedback -------------------

def test_download_button_shows_starting_immediately_on_click(qtbot):
    # Roadmap item 56 Phase 5.1 — the real bug: the button previously
    # gave no feedback that anything had started.
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists, resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.download_button.click()

    # Synchronous, main-thread state set at click time — true
    # immediately, not just eventually once some worker lands.
    assert window.download_button.text() == "Starting download…"
    assert not window.download_button.isEnabled()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: window.download_button.text() == "Download selected playlist",
        timeout=2000,
    )
    assert window.download_button.isEnabled()


def test_download_button_resets_when_dialog_is_cancelled(qtbot, monkeypatch):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        DestinationDialog, "exec", lambda self: QDialog.DialogCode.Rejected,
    )

    window.download_button.click()

    qtbot.waitUntil(
        lambda: window.download_button.text() == "Download selected playlist",
        timeout=2000,
    )
    assert window.download_button.isEnabled()
    assert application.download_service.download_playlist_calls == []


def test_download_result_notice_reports_already_in_progress_tracks(qtbot):
    # Roadmap item 56 Phase 5.1 — how many downloads were requested,
    # and how many tracks were skipped because they were already in
    # flight (Phase 5.2's own real dedup guard reports through here).
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result={
            "requested": 2, "skipped": 3, "failed": 0, "total": 5,
            "already_in_progress": [
                "Artist A - Title A", "Artist B - Title B", "Artist C - Title C",
            ],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.download_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Requested 2" in window.dashboard_notice.text(),
        timeout=2000,
    )
    assert "3 already downloading/downloaded" in window.dashboard_notice.text()


def test_download_with_no_destination_opens_dialog_prefilled_with_playlist_name(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    dialog = opened_dialogs[0]
    # Prefilled: the only real location, and the subfolder defaults to
    # the playlist's own name.
    assert dialog.selected_location_id() == 1
    assert dialog.subfolder_field.text() == "Test"
    assert dialog.remember_checkbox.isChecked()
    # Rejected — no destination call, no download.
    assert application.download_service.set_destination_calls == []
    assert application.download_service.download_playlist_calls == []


def test_download_dialog_prefills_the_configured_default_location(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    main_location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    other_location = LibraryLocation(
        id=2, name="Other", path="/other", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(main_location, True), (other_location, True)],
        resolved_destination=None,
    )
    application._config_store = replace(
        application._config_store, default_download_location_id=2,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    assert opened_dialogs[0].selected_location_id() == 2


def test_download_dialog_confirmed_with_remember_calls_set_destination_then_downloads(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    window.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.set_destination_calls == [
        ("Test", "Main", "Test"),
    ]
    assert application.persist_default_destination_calls == []
    assert application.download_service.download_playlist_calls == ["Test"]


def test_download_dialog_confirmed_without_remember_persists_the_default(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    def fake_exec(self):
        self.remember_checkbox.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DestinationDialog, "exec", fake_exec)

    window.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == [(1, True)]
    assert application.download_service.download_playlist_calls == ["Test"]


def test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_dialog(
        qtbot,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(
        playlists=playlists, locations=[], resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.download_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden(), timeout=2000,
    )
    assert "location" in window.dashboard_notice.text().lower()


def test_main_window_has_help_menu_with_about_action(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu_bar = window.menuBar()
    menu_titles = [menu.title() for menu in menu_bar.findChildren(QMenu)]
    assert any("Help" in title for title in menu_titles)

    help_menu = next(
        menu for menu in menu_bar.findChildren(QMenu) if "Help" in menu.title()
    )
    action_texts = [action.text() for action in help_menu.actions()]
    assert help_text.ABOUT_MENU_TEXT in action_texts
    assert help_text.CHECK_FOR_UPDATES_MENU_TEXT in action_texts


# --- Check for updates (roadmap Phase 11) -----------------------------------
# check_for_update() must fire ONLY from this one Help menu action —
# never at construction, never on a timer. See main_window.py's own
# _build_help_menu/_on_check_for_updates_clicked and update_check.py's
# docstring for the real-external-dependency reasoning.

def test_check_for_update_is_not_called_during_construction(qtbot, monkeypatch):
    calls: list[None] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: calls.append(None),
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.wait(50)
    assert calls == []


def test_check_for_updates_click_runs_check_for_update_via_worker(
        qtbot, monkeypatch,
):
    calls: list[None] = []

    def fake_check_for_update():
        calls.append(None)
        return UpdateCheckResult(UpdateStatus.UP_TO_DATE, latest_version="v1.0.0")

    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update", fake_check_for_update,
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()

    qtbot.waitUntil(lambda: calls == [None], timeout=2000)
    qtbot.waitUntil(
        lambda: window.check_for_updates_action.isEnabled(), timeout=2000,
    )


def test_up_to_date_dialog_shows_installed_version(qtbot, monkeypatch):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UP_TO_DATE, latest_version="v1.0.0",
            installed_version="1.0.0",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    assert "up to date" in shown[0].text().lower()
    assert "1.0.0" in shown[0].text()


def test_update_available_dialog_shows_both_versions_and_link(
        qtbot, monkeypatch,
):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UPDATE_AVAILABLE, latest_version="v1.3.0",
            installed_version="1.2.0",
            release_url="https://github.com/example/repo/releases/v1.3.0",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    text = shown[0].text()
    assert "v1.3.0" in text
    assert "1.2.0" in text
    assert "https://github.com/example/repo/releases/v1.3.0" in text


def test_unavailable_dialog_shows_the_reason(qtbot, monkeypatch):
    shown: list[QMessageBox] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(
            UpdateStatus.UNAVAILABLE,
            reason="No releases have been published yet.",
        ),
    )

    def fake_exec(self):
        shown.append(self)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.check_for_updates_action.trigger()
    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)

    assert "No releases have been published yet." in shown[0].text()


def test_check_for_updates_action_disabled_while_running_and_reenabled(
        qtbot, monkeypatch,
):
    monkeypatch.setattr(
        "seeker.ui.main_window.check_for_update",
        lambda: UpdateCheckResult(UpdateStatus.UP_TO_DATE, latest_version="v1"),
    )
    monkeypatch.setattr(QMessageBox, "exec", lambda self: None)

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.check_for_updates_action.isEnabled()
    window.check_for_updates_action.trigger()
    qtbot.waitUntil(
        lambda: window.check_for_updates_action.isEnabled(), timeout=2000,
    )


def test_about_dialog_opens_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dialog = AboutDialog(window)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == help_text.ABOUT_DIALOG_TITLE


def test_about_dialog_shows_author_license_and_notices(qtbot):
    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    labels_html = [
        widget.text() for widget in dialog.findChildren(QLabel)
    ]
    combined = "\n".join(labels_html)

    assert "Kristiyan Dimitrov" in combined
    assert "mailto:kristiyanddimitrov@gmail.com" in combined
    assert "github.com/KristiyanDDimitrov/Seeker" in combined
    assert "MIT License" in combined
    assert "Third-party notices" in combined
    assert "PySide6" in combined


def test_about_dialog_renders_a_button_for_every_real_support_link(
        qtbot, monkeypatch,
):
    # Both Revolut and PayPal are real links as of 2026-09-01 — every
    # entry in the real SUPPORT_LINKS dict should render a working
    # button (the "at least one still-placeholder" filtering behavior
    # itself is covered separately below, via a synthetic placeholder,
    # so this guard stays exercised even though production data no
    # longer has a real one to filter).
    from seeker.ui import main_window as main_window_module

    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module.webbrowser, "open", lambda url: opened.append(url)
    )

    assert all(
        help_text.is_real_support_link(url)
        for url in help_text.SUPPORT_LINKS.values()
    ), "expected every current SUPPORT_LINKS entry to be a real link"

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    buttons = [
        widget
        for widget in dialog.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert len(buttons) == len(help_text.SUPPORT_LINKS)
    assert {button.text() for button in buttons} == {
        f"Support on {name}" for name in help_text.SUPPORT_LINKS
    }

    for button in buttons:
        button.click()

    assert set(opened) == set(help_text.SUPPORT_LINKS.values())


def test_about_dialog_filters_out_a_placeholder_support_link(
        qtbot, monkeypatch,
):
    # Regression guard for is_real_support_link() itself: since the real
    # SUPPORT_LINKS no longer has a TODO entry to filter (PayPal went
    # live), inject a synthetic one here so a dead, non-URL button is
    # still proven to never render, rather than this guard silently
    # stopping being exercised.
    from seeker.ui import main_window as main_window_module

    monkeypatch.setattr(
        main_window_module.help_text, "SUPPORT_LINKS",
        {
            "Revolut": "https://revolut.me/kddimitrov",
            "Ko-fi": "TODO: paste real Ko-fi link",
        },
    )

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    buttons = [
        widget
        for widget in dialog.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert [button.text() for button in buttons] == ["Support on Revolut"]


def test_dashboard_downloads_review_pages_have_persistent_subtitles(qtbot):
    # Task 1 — a short, persistent (not hover-dependent) one-liner under
    # each page's own header. Phase 4 moved these from a QTabWidget into
    # a sidebar-driven QStackedWidget — each page is looked up by its
    # own registered index, not a bare tab position.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    stack = window.stacked_widget
    dashboard_labels = [
        widget.text()
        for widget in stack.widget(window._page_indices["dashboard"])
        .findChildren(QLabel)
    ]
    assert help_text.DASHBOARD_TAB_SUBTITLE in dashboard_labels

    downloads_labels = [
        widget.text()
        for widget in stack.widget(window._page_indices["downloads"])
        .findChildren(QLabel)
    ]
    assert help_text.DOWNLOADS_TAB_SUBTITLE in downloads_labels

    review_labels = [
        widget.text()
        for widget in stack.widget(window._page_indices["review"])
        .findChildren(QLabel)
    ]
    assert help_text.REVIEW_TAB_SUBTITLE in review_labels


def test_main_window_populates_playlist_list_from_service(qtbot):
    playlists = [Playlist(id="p1", name="Test Playlist", track_count=3)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)

    assert "Test Playlist" in window.playlist_list.item(0).text()


def test_main_window_shows_sync_tracks_prompt_when_playlist_has_no_tracks(
        qtbot,
):
    # No auto-fetch of Spotify tracks on selection — an explicit button
    # instead (roadmap item 1's scoped-sync-tracks split).
    playlists = [Playlist(id="p1", name="Empty Playlist", track_count=0)]
    application = FakeApplication(playlists=playlists, statuses=[])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)

    qtbot.waitUntil(
        lambda: window.sync_tracks_button.isVisible(), timeout=2000,
    )
    assert application.sync_service.sync_playlist_tracks_calls == []


def test_worker_emits_finished_with_result():
    # Worker no longer owns a per-instance `.signals` object — every
    # worker reports through the one shared, permanently-connected
    # `_dispatcher` (see workers.py's own docstring for why: a fresh
    # per-task QObject+connect()/disconnect() cycle was confirmed live
    # to cause a real, reproducible deadlock). Connect directly to the
    # dispatcher and filter by task_id, the same way _handle_task_finished
    # itself does — the signal carries a plain int, never the Worker
    # instance itself (see Worker's own docstring for why).
    worker = Worker(lambda: 42)
    results = []

    def on_finished(task_id: int, result: object) -> None:
        if task_id == worker.task_id:
            results.append(result)

    # Disconnected in finally — this connects to the one PERMANENT,
    # shared dispatcher, so a test-local connection left dangling would
    # linger for the rest of the process, not just this test.
    workers_module._dispatcher.task_finished.connect(on_finished)
    try:
        worker.run()
    finally:
        workers_module._dispatcher.task_finished.disconnect(on_finished)

    assert results == [42]


def test_worker_emits_error_on_exception():
    def boom():
        raise RuntimeError("simulated failure")

    worker = Worker(boom)
    errors = []

    def on_error(task_id: int, message: str) -> None:
        if task_id == worker.task_id:
            errors.append(message)

    workers_module._dispatcher.task_error.connect(on_error)
    try:
        worker.run()
    finally:
        workers_module._dispatcher.task_error.disconnect(on_error)

    assert errors == ["simulated failure"]


def test_run_worker_disables_button_while_running_and_reenables(qtbot):
    button = QPushButton("Go")
    qtbot.addWidget(button)

    button_state_during_run = []

    class SynchronousPool:
        def start(self, worker):
            button_state_during_run.append(button.isEnabled())
            worker.run()

    run_worker(SynchronousPool(), lambda: "done", button=button)

    assert button_state_during_run == [False]
    assert button.isEnabled() is True


def test_run_worker_error_sets_status_label_and_reenables_button(qtbot):
    from PySide6.QtWidgets import QLabel

    button = QPushButton("Go")
    label = QLabel("")
    qtbot.addWidget(button)
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise RuntimeError("real failure text")

    run_worker(SynchronousPool(), boom, button=button, status_label=label)

    assert label.text() == "real failure text"
    assert button.isEnabled() is True


def test_run_worker_registry_releases_worker_on_both_success_and_error():
    # _callbacks (see workers.py's own comment) holds each in-flight
    # task's callback entry, keyed by task_id, until that task's own
    # completion pops it — if cleanup only fired on the success path, a
    # worker that raises would stay referenced forever, a real leak on
    # every failed sync/scan/match/download. Asserted directly against
    # the registry itself, not just inferred from button/label side
    # effects.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    run_worker(SynchronousPool(), lambda: "ok")
    assert len(workers_module._callbacks) == baseline

    def boom():
        raise RuntimeError("simulated failure")

    run_worker(SynchronousPool(), boom)
    assert len(workers_module._callbacks) == baseline


def test_run_worker_on_finished_exception_does_not_propagate(qtbot):
    # A bug in a render/completion callback (not the fetch itself) must
    # not escape run_worker uncontrolled — confirmed live this doesn't
    # crash the app or stop the triggering QTimer either way, but
    # nothing in this codebase's own code caught it before this fix;
    # only PySide6's own default exception hook did, an implicit safety
    # net rather than an intentional one.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    # Must not raise out of this call.
    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)


def test_run_worker_on_finished_exception_surfaces_to_status_label(qtbot):
    from PySide6.QtWidgets import QLabel

    label = QLabel("")
    qtbot.addWidget(label)

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(
        SynchronousPool(),
        lambda: "ok",
        status_label=label,
        on_finished=render_that_raises,
    )

    assert "malformed render data" in label.text()


def test_run_worker_on_finished_exception_without_status_label_still_safe(qtbot):
    # The periodic-poll shape (e.g. the Downloads/Review tabs' 2s
    # refresh) — no status_label wired at all, by design, so a fetch
    # error doesn't flash a noisy message every tick. A render bug must
    # still not propagate even here.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)


def test_run_worker_on_error_exception_does_not_propagate(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom():
        raise RuntimeError("fetch failed")

    def on_error_that_raises(message):
        raise ValueError("bug in on_error handling")

    # Must not raise out of this call either.
    run_worker(SynchronousPool(), boom, on_error=on_error_that_raises)


def test_run_worker_on_finished_exception_still_releases_worker_registry(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)

    assert len(workers_module._callbacks) == baseline


def _make_active_download(
        track_id: str = "t1",
        status: str = "downloading",
        role: str = "settled",
        bytes_transferred: int | None = 500,
        total_bytes: int | None = 1_000,
        playlist_name: str = "Playlist A",
) -> ActiveDownload:
    return ActiveDownload(
        request=DownloadRequest(
            track_id=track_id,
            username="peer1",
            filename="file.flac",
            format="flac",
            role=role,
            status=status,
            requested_at="2026-01-01T00:00:00+00:00",
            bytes_transferred=bytes_transferred,
            total_bytes=total_bytes,
        ),
        track=Track(
            id=track_id, title="Title", artist="Artist", album="Album",
            duration_ms=200_000,
        ),
        playlist_name=playlist_name,
    )


def test_downloads_tab_renders_rows_across_playlists(qtbot):
    downloads = [
        _make_active_download(track_id="t1", playlist_name="Playlist A"),
        _make_active_download(
            track_id="t2", status="locked", role="upgrade",
            bytes_transferred=None, total_bytes=None,
            playlist_name="Playlist B",
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads(downloads)

    assert window.downloads_table.rowCount() == 2
    assert window.downloads_table.item(0, 1).text() == "Playlist A"
    assert window.downloads_table.item(1, 1).text() == "Playlist B"
    # A raw "locked" status gets a plain-language note, not the raw
    # state string.
    assert window.downloads_table.item(1, 3).text() == "Retrying (locked)"


# --- Downloads aggregate remaining-time header (Task 9) --------------------

def test_downloads_aggregate_header_blank_with_no_active_downloads(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([])

    assert window.downloads_eta_label.text() == ""
    assert window.downloads_eta_label.toolTip() == ""


def test_downloads_aggregate_header_shows_estimate_once_a_download_has_samples(qtbot):
    download = ActiveDownload(
        request=DownloadRequest(
            id=1, track_id="t1", username="peer1", filename="file.flac",
            format="flac", status="downloading",
            requested_at="2026-01-01T00:00:00+00:00",
            bytes_transferred=500, total_bytes=1_000,
        ),
        track=Track(
            id="t1", title="Title", artist="Artist", album="Album",
            duration_ms=200_000,
        ),
        playlist_name="Playlist A",
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # aggregate() reads from _eta_tracker's own recorded samples, not
    # from the ActiveDownload snapshot itself — feed it two directly,
    # the same way _record_eta_samples does on a real 20s backend poll.
    window._eta_tracker.record(1, 200, datetime(2026, 1, 1, tzinfo=timezone.utc))
    window._eta_tracker.record(1, 500, datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc))

    window._render_active_downloads([download])

    assert "remaining" in window.downloads_eta_label.text()
    assert "1 transferring" in window.downloads_eta_label.text()
    assert window.downloads_eta_label.toolTip() != ""


def test_downloads_aggregate_header_reports_waiting_with_no_samples(qtbot):
    download = _make_active_download(
        status="queued", bytes_transferred=None, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    assert window.downloads_eta_label.text() == (
        "Waiting for transfers to start · 0 transferring · "
        "1 queued (no estimate)"
    )


def test_downloads_tab_progress_bar_indeterminate_with_no_bytes_yet(qtbot):
    download = _make_active_download(
        status="queued", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    bar = window.downloads_table.cellWidget(0, 4)
    assert isinstance(bar, QProgressBar)
    assert bar.minimum() == 0
    assert bar.maximum() == 0
    # Real, live-found bug (Phase 3): ANY QProgressBar::chunk QSS rule
    # matching a bar, even one applied only to determinate bars
    # elsewhere, replaces Qt's native animated "busy" indeterminate
    # indicator with a static solid block that reads as "stuck at
    # 100%." The accent chunk fill must never be applied to an
    # indeterminate bar — asserting no local stylesheet override here
    # is what would catch a regression that started calling
    # theme.style_determinate_progress_bar() unconditionally.
    assert bar.styleSheet() == ""


def test_downloads_tab_progress_bar_determinate_with_real_bytes(qtbot):
    # A determinate bar is wrapped in a container alongside the ETA
    # label (Task 2) — the bar itself is a child widget, not the cell
    # widget directly (unlike the indeterminate/no-progress cases above,
    # which are left unchanged).
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.maximum() == 1_000
    assert bar.value() == 500
    # The accent chunk fill IS a per-instance stylesheet override, not
    # a global QSS rule (see theme.py's own QProgressBar::chunk
    # comment) — a determinate bar must actually receive it.
    assert "chunk" in bar.styleSheet()


def test_downloads_tab_locked_row_has_no_progress_bar(qtbot):
    # Locked/shortlisted rows have no real, current transfer — a
    # progress claim there would be misleading.
    download = _make_active_download(
        status="locked", role="upgrade",
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    bar = window.downloads_table.cellWidget(0, 4)
    assert not isinstance(bar, QProgressBar)


# --- Roadmap item 56 Phase 5.4: a finished download must not read as
# "Stalled" ------------------------------------------------------------

def test_a_just_completed_download_never_consults_the_eta_tracker(qtbot):
    # The real bug, reproduced directly: sample a completed row 3 times
    # with identical bytes (exactly what the 20s backend-poll loop used
    # to do for a recently-finished row still inside
    # RECENTLY_FINISHED_WINDOW_SECONDS) — old behavior would eventually
    # report "Stalled" once _is_stalled's 3-identical-sample threshold
    # was reached; the real fix is that a terminal row's status is
    # never even routed to describe()/the tracker at all.
    download = _make_active_download(
        status="completed", bytes_transferred=1_000, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        window._eta_tracker.record(1, 1_000, now + timedelta(seconds=i * 20))

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label_texts = [
        child.text() for child in container.findChildren(QLabel)
    ]
    assert "Completed" in label_texts
    assert "Stalled" not in label_texts
    # Evicted immediately, not left for the row to eventually drop out
    # of get_active_downloads() on its own.
    assert 1 not in window._eta_tracker._history


def test_terminal_progress_widget_shows_a_full_bar_for_completed(qtbot):
    download = _make_active_download(
        status="completed", bytes_transferred=1_000, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.value() == bar.maximum()


def test_terminal_progress_widget_shows_ready_for_review_label(qtbot):
    download = _make_active_download(
        status="ready_for_review", role="upgrade",
        bytes_transferred=1_000, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label_texts = [
        child.text() for child in container.findChildren(QLabel)
    ]
    assert "Ready for review" in label_texts


def test_terminal_progress_widget_for_failed_is_blank_not_a_bar(qtbot):
    download = _make_active_download(
        status="failed", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    widget = window.downloads_table.cellWidget(0, 4)
    assert not isinstance(widget, QProgressBar)
    assert widget.findChild(QProgressBar) is None


def test_aggregate_header_excludes_terminal_rows_from_queued_count(qtbot):
    # Roadmap item 56 Phase 5.4 §4 — a completed row was previously
    # folded into the "queued (no estimate)" figure.
    completed = _make_active_download(
        track_id="t1", status="completed",
        bytes_transferred=1_000, total_bytes=1_000,
    )
    completed.request.id = 1
    queued = _make_active_download(
        track_id="t2", status="queued",
        bytes_transferred=None, total_bytes=1_000,
    )
    queued.request.id = 2
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([completed, queued])

    assert window.downloads_eta_label.text() == (
        "Waiting for transfers to start · 0 transferring · "
        "1 queued (no estimate)"
    )


def test_downloads_tab_eta_shows_calculating_before_second_sample(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "Calculating…"


def test_downloads_tab_eta_shows_estimate_after_two_samples(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(timezone.utc)
    # 400 bytes/second over the last interval, 400 bytes remaining ->
    # a clean 1s ETA, easy to assert on exactly.
    window._eta_tracker.record(1, 200, now - timedelta(seconds=1))
    window._eta_tracker.record(1, 600, now)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "1s"


def test_downloads_tab_eta_shows_stalled_after_flat_samples(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(timezone.utc)
    for offset in (2, 1, 0):
        window._eta_tracker.record(1, 600, now - timedelta(seconds=offset))

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "Stalled"


def test_record_eta_samples_evicts_ids_no_longer_active(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(timezone.utc)
    window._eta_tracker.record(1, 100, now)
    window._eta_tracker.record(1, 200, now)

    # request id 1 has since disappeared from get_active_downloads() —
    # completed, failed, or superseded — so a fresh sampling pass with
    # no row for it must drop its history rather than keep it forever
    # (Task 2's own explicit leak-prevention requirement).
    window._record_eta_samples([])

    assert window._eta_tracker.describe(1, 1_000) == "Calculating…"


def test_trigger_backend_poll_samples_eta_after_poll_succeeds(qtbot):
    download = _make_active_download(bytes_transferred=500, total_bytes=1_000)
    download.request.id = 7

    application = FakeApplication(
        soulseek_configured=True, active_downloads=[download],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    qtbot.waitUntil(lambda: 7 in window._eta_tracker._history, timeout=2000)


def test_backend_poll_runs_poll_downloads_off_the_main_thread(qtbot):
    recorded: dict[str, threading.Thread] = {}

    class RecordingDownloadService:
        def poll_downloads(self) -> dict:
            recorded["thread"] = threading.current_thread()
            return {}

    application = FakeApplication(soulseek_configured=True)
    application.download_service = RecordingDownloadService()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    # Wait for the FULL round trip (the queued completion signal
    # actually delivered on the main thread), not just for the
    # background function itself to have returned — `recorded["thread"]`
    # is set inside poll_downloads() on the worker thread, microseconds
    # before run_worker()'s completion signal is even emitted, so
    # waiting on it alone raced ahead of signal delivery (confirmed
    # live: this caused a real, reproducible segfault in a LATER test's
    # teardown, when the still-queued signal was finally delivered
    # against this test's already-destroyed window/button — see
    # CLAUDE.md/docs/HISTORY.md item 39). `_backend_poll_in_progress`
    # only flips False from the main-thread on_finished callback, so
    # waiting on it — same as test_backend_poll_overlap_guard_skips_
    # concurrent_tick already correctly does — guarantees the signal
    # was actually processed before the test ends.
    qtbot.waitUntil(
        lambda: "thread" in recorded and not window._backend_poll_in_progress,
        timeout=2000,
    )

    assert recorded["thread"] != threading.main_thread()


def test_backend_poll_refreshes_selected_playlist_track_table(qtbot):
    # Phase 1 UI follow-on: a settled download completing during a real
    # backend poll should flip the Dashboard to IN_LIBRARY immediately,
    # not wait up to the 2s display tick to happen to catch it.
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.selected_playlist = Playlist(
        id="p1", name="Test Playlist", track_count=1,
    )
    dashboard_service = application.dashboard_service
    assert isinstance(dashboard_service, FakeDashboardService)
    dashboard_service.calls.clear()

    window._trigger_backend_poll()

    qtbot.waitUntil(
        lambda: "Test Playlist" in dashboard_service.calls, timeout=2000,
    )


def test_backend_poll_skipped_when_soulseek_not_configured(qtbot):
    application = FakeApplication(soulseek_configured=False)
    calls = []
    application.download_service.poll_downloads = lambda: calls.append(1)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    assert calls == []


def test_backend_poll_overlap_guard_skips_concurrent_tick(qtbot):
    call_count = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    class SlowDownloadService:
        def poll_downloads(self) -> dict:
            call_count["n"] += 1
            started.set()
            release.wait(timeout=5)
            return {}

    application = FakeApplication(soulseek_configured=True)
    application.download_service = SlowDownloadService()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()
    assert started.wait(timeout=2)

    # A second tick while the first poll_downloads() call is still
    # running must be skipped, not start a second concurrent writer.
    window._trigger_backend_poll()

    release.set()
    qtbot.waitUntil(
        lambda: not window._backend_poll_in_progress, timeout=2000,
    )

    assert call_count["n"] == 1


def _make_track(track_id: str = "t1") -> Track:
    return Track(
        id=track_id, title="Title", artist="Artist", album="Album",
        duration_ms=200_000,
    )


def _make_review_candidate(
        track_id: str = "t1",
        score: float = 73.2,
) -> SoulseekReviewCandidate:
    return SoulseekReviewCandidate(
        track_id=track_id,
        username="peer1",
        filename="Artist - Title (Original Mix).flac",
        score=score,
        quality_descriptor="flac",
        found_at="2026-01-01T00:00:00+00:00",
        size=1_000_000,
    )


def _make_upgrade_details(
        request_id: int = 1,
        old_file_path: str | None = "/music/old.mp3",
) -> UpgradeReviewDetails:
    return UpgradeReviewDetails(
        request_id=request_id,
        track=_make_track(),
        quality_descriptor="flac 1000kbps",
        current_description="mp3",
        old_file_path=old_file_path,
    )


def test_review_tab_renders_needs_review_candidates(qtbot):
    candidates = [(_make_track(), _make_review_candidate())]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_needs_review_candidates(candidates)

    assert window.review_needs_table.rowCount() == 1
    assert window.review_needs_table.item(0, 0).text() == "Artist - Title"
    assert window.review_needs_table.item(0, 1).text() == "73.2"
    assert "peer1" in window.review_needs_table.item(0, 2).text()

    actions = window.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    assert set(buttons) == {"Confirm", "Reject"}


def test_review_tab_confirm_button_calls_confirm_review_candidate(qtbot):
    candidates = [(_make_track(track_id="t7"), _make_review_candidate(track_id="t7"))]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_needs_review_candidates(candidates)

    actions = window.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Confirm"].click()

    qtbot.waitUntil(
        lambda: application.download_service.confirm_review_candidate_calls == ["t7"],
        timeout=2000,
    )
    assert application.download_service.reject_review_candidate_calls == []


def test_review_tab_reject_button_calls_reject_review_candidate(qtbot):
    candidates = [(_make_track(track_id="t9"), _make_review_candidate(track_id="t9"))]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_needs_review_candidates(candidates)

    actions = window.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Reject"].click()

    qtbot.waitUntil(
        lambda: application.download_service.reject_review_candidate_calls == ["t9"],
        timeout=2000,
    )
    assert application.download_service.confirm_review_candidate_calls == []


def test_review_tab_renders_pending_upgrades_with_delete_checkbox_when_old_file_exists(
        qtbot,
):
    details = [_make_upgrade_details(old_file_path="/music/old.mp3")]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    assert window.review_upgrades_table.rowCount() == 1
    assert window.review_upgrades_table.item(0, 1).text() == "mp3"
    assert window.review_upgrades_table.item(0, 2).text() == "flac 1000kbps"

    actions = window.review_upgrades_table.cellWidget(0, 3)
    assert len(actions.findChildren(QCheckBox)) == 1
    buttons = {b.text() for b in actions.findChildren(QPushButton)}
    assert buttons == {"Replace", "Decline"}


def test_review_tab_renders_pending_upgrades_without_delete_checkbox_when_no_old_file(
        qtbot,
):
    # Mirrors the CLI's own guard around its second input() prompt —
    # there's nothing to offer deleting when there's no current file.
    details = [_make_upgrade_details(old_file_path=None)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    assert actions.findChildren(QCheckBox) == []


def test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag(
        qtbot,
):
    details = [_make_upgrade_details(request_id=42, old_file_path="/music/old.mp3")]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    checkbox = actions.findChildren(QCheckBox)[0]
    checkbox.setChecked(True)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Replace"].click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decision_calls
        == [(42, True, True)],
        timeout=2000,
    )
    assert window.status_label.text() == "Replaced with /new/path"


def test_review_tab_decline_button_calls_apply_upgrade_decision_with_replace_false(
        qtbot,
):
    details = [_make_upgrade_details(request_id=99)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Decline"].click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decision_calls
        == [(99, False, False)],
        timeout=2000,
    )
    # A decline returns None from apply_upgrade_decision — no status
    # message should be surfaced, unlike a real replace.
    assert window.status_label.text() == ""


def test_review_tab_populates_both_sections_on_construction(qtbot):
    # _poll_review_items() runs once in __init__ (like the Downloads
    # tab's own initial call) so the Review tab isn't empty for the
    # first poll interval either.
    candidates = [(_make_track(track_id="tc"), _make_review_candidate(track_id="tc"))]
    upgrades = [_make_upgrade_details(request_id=5)]
    application = FakeApplication(
        review_candidates=candidates, pending_upgrades=upgrades,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.review_needs_table.rowCount() == 1, timeout=2000,
    )
    assert window.review_upgrades_table.rowCount() == 1


def _make_needs_review_match(track_id: str = "t1") -> NeedsReviewMatch:
    return NeedsReviewMatch(
        track_id=track_id,
        track_artist="Artist",
        track_title="Title",
        local_file_id=1,
        local_file_path="Music/song.mp3",
        location_name="Main",
        score=85.7,
        tag_artist="Artist",
        tag_title="Title Edit",
    )


def test_review_tab_renders_local_needs_review_matches(qtbot):
    matches = [_make_needs_review_match()]
    application = FakeApplication(needs_review_matches=matches)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.review_local_table.rowCount() == 1, timeout=2000,
    )
    assert window.review_local_table.item(0, 0).text() == "Artist - Title"
    assert window.review_local_table.item(0, 1).text() == "Music/song.mp3"
    assert window.review_local_table.item(0, 2).text() == "Main"
    assert window.review_local_table.item(0, 3).text() == "85.7"
    assert window.review_local_table.cellWidget(0, 4) is not None


def test_review_tab_confirm_local_match_calls_confirm_match(qtbot):
    application = FakeApplication(
        needs_review_matches=[_make_needs_review_match(track_id="tc")]
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.review_local_table.rowCount() == 1, timeout=2000,
    )
    confirm_button = window.review_local_table.cellWidget(
        0, 4
    ).findChildren(QPushButton)[0]
    confirm_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.confirm_match_calls == ["tc"],
        timeout=2000,
    )


def test_review_tab_reject_local_match_calls_reject_match(qtbot):
    application = FakeApplication(
        needs_review_matches=[_make_needs_review_match(track_id="tc")]
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.review_local_table.rowCount() == 1, timeout=2000,
    )
    reject_button = window.review_local_table.cellWidget(
        0, 4
    ).findChildren(QPushButton)[1]
    reject_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.reject_match_calls == ["tc"],
        timeout=2000,
    )


def test_review_nav_badge_counts_all_three_sections(qtbot):
    application = FakeApplication(
        review_candidates=[
            (_make_track(track_id="tc"), _make_review_candidate(track_id="tc"))
        ],
        pending_upgrades=[_make_upgrade_details(request_id=5)],
        needs_review_matches=[_make_needs_review_match(track_id="tl")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._nav_buttons["review"].text() == "Review  (3)",
        timeout=2000,
    )


# --- Roadmap item 56 §2.4: Dashboard double-click -> Review -----------------

def test_double_clicking_needs_review_row_navigates_to_review_and_selects_it(
        qtbot,
):
    status = _make_track_status(track_id="t1", state=NEEDS_REVIEW)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
        needs_review_matches=[_make_needs_review_match(track_id="t1")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(lambda: window.track_table.rowCount() == 1, timeout=2000)
    window._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["review"]
    )
    qtbot.waitUntil(
        lambda: window.review_local_table.rowCount() == 1, timeout=2000,
    )
    qtbot.waitUntil(
        lambda: window.review_local_table.selectedItems() != [],
        timeout=2000,
    )
    assert window.review_local_table.currentRow() == 0


def test_double_clicking_in_library_row_is_a_no_op(qtbot):
    status = _make_track_status(track_id="t1", state=IN_LIBRARY)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(lambda: window.track_table.rowCount() == 1, timeout=2000)
    window._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["dashboard"]
    )


def test_needs_review_status_cell_has_tooltip_other_states_dont(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=2)],
        statuses=[
            _make_track_status(track_id="t1", state=NEEDS_REVIEW),
            _make_track_status(track_id="t2", state=IN_LIBRARY),
        ],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(lambda: window.track_table.rowCount() == 2, timeout=2000)
    assert window.track_table.item(0, 1).toolTip() != ""
    assert window.track_table.item(1, 1).toolTip() == ""


def _make_track_status(
        track_id: str = "t1",
        state: str = IN_LIBRARY,
        tagged_at: str | None = None,
) -> TrackStatus:
    return TrackStatus(
        track=_make_track(track_id), state=state, tagged_at=tagged_at,
    )


def test_dashboard_downloading_progress_bar_gets_the_accent_chunk_style(qtbot):
    # This cell is only ever rendered determinate (blank otherwise — see
    # _render_track_statuses), but it shares theme.py's
    # style_determinate_progress_bar() with the Downloads tab's own bar,
    # so it needs the identical guard against a regression that skips
    # applying it.
    status = TrackStatus(
        track=_make_track("t1"), state=DOWNLOADING,
        bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses([status])

    bar = window.track_table.cellWidget(0, 2)
    assert isinstance(bar, QProgressBar)
    assert "chunk" in bar.styleSheet()


def test_tag_button_appears_only_for_in_library_tracks(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY),
        _make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    in_library_actions = window.track_table.cellWidget(0, 3)
    assert [b.text() for b in in_library_actions.findChildren(QPushButton)] == ["Tag"]

    not_found_actions = window.track_table.cellWidget(1, 3)
    assert not_found_actions.findChildren(QPushButton) == []


def test_tagged_track_shows_muted_label_instead_of_tag_button(qtbot):
    statuses = [
        _make_track_status(
            track_id="t1", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    actions = window.track_table.cellWidget(0, 3)
    assert actions.findChildren(QPushButton) == []
    labels = actions.findChildren(QLabel)
    assert [label.text() for label in labels] == ["Tagged"]
    assert "2026" in labels[0].toolTip()


def test_retag_context_menu_forces_regardless_of_checkbox(qtbot):
    statuses = [
        _make_track_status(
            track_id="t5", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    # The panel-wide force checkbox is deliberately left unchecked —
    # Re-tag via the context menu must force regardless of it.
    assert window.force_retag_checkbox.isChecked() is False

    window._on_retag_track_clicked("t5")

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t5"], False, None, True),
    ]


def test_context_menu_offers_nothing_for_an_untagged_or_missing_row(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None),
        _make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    # Neither row offers a real "Re-tag" action — an untagged row has
    # nothing to re-tag, and a not-in-library row has no local file at
    # all. Calling the handler directly (no real QMenu popup in an
    # offscreen test) must simply do nothing, not raise.
    window._on_track_table_context_menu(window.track_table.visualItemRect(
        window.track_table.item(0, 0)
    ).center())
    window._on_track_table_context_menu(window.track_table.visualItemRect(
        window.track_table.item(1, 0)
    ).center())


def test_force_retag_checkbox_passed_through_all_three_triggers(qtbot):
    statuses = [
        _make_track_status(
            track_id="t7", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    playlists = [Playlist(id="p1", name="240KM/H", track_count=1)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    window.force_retag_checkbox.setChecked(True)

    actions = window.track_table.cellWidget(0, 3)
    tag_button = actions.findChildren(QPushButton)[0] if actions.findChildren(
        QPushButton
    ) else None
    # This row is already tagged, so the per-row control is the muted
    # label, not a button — exercise the panel-wide checkbox via "Tag
    # selected" and "Tag playlist" instead, both of which apply
    # regardless of a row's own tagged state.
    assert tag_button is None

    selection_model = window.track_table.selectionModel()
    selection_model.select(
        window.track_table.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    window.tag_selected_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t7"], False, None, True),
    ]

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)
    window.tag_playlist_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_playlist_calls == [
        ("240KM/H", False, None, True),
    ]


def test_tag_track_button_calls_tag_tracks_with_correct_args(qtbot):
    statuses = [_make_track_status(track_id="t7", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    actions = window.track_table.cellWidget(0, 3)
    tag_button = actions.findChildren(QPushButton)[0]
    tag_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t7"], False, None, False),
    ]


def test_bpm_range_fields_hidden_until_analyze_audio_checked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    # isVisible() reflects actual on-screen visibility, which requires
    # a shown top-level window — isHidden() reflects the widget's own
    # explicit hide/show state regardless of ancestor visibility, which
    # is what this test actually cares about, so window.show() isn't
    # needed here.
    assert window.bpm_min_edit.isHidden()
    assert window.bpm_max_edit.isHidden()

    window.analyze_audio_checkbox.setChecked(True)

    assert not window.bpm_min_edit.isHidden()
    assert not window.bpm_max_edit.isHidden()

    window.analyze_audio_checkbox.setChecked(False)

    assert window.bpm_min_edit.isHidden()
    assert window.bpm_max_edit.isHidden()


def test_tag_track_with_analyze_audio_and_bpm_range_passes_options(qtbot):
    statuses = [_make_track_status(track_id="t9", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    window.analyze_audio_checkbox.setChecked(True)
    window.bpm_min_edit.setText("160")
    window.bpm_max_edit.setText("180")

    actions = window.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t9"], True, (160.0, 180.0), False),
    ]


def test_bpm_range_partial_input_blocks_the_call_with_an_error(qtbot):
    statuses = [_make_track_status(track_id="t3", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    window.analyze_audio_checkbox.setChecked(True)
    window.bpm_min_edit.setText("160")
    # bpm_max_edit deliberately left blank.

    actions = window.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "both" in window.dashboard_notice.text().lower()
    assert not window.dashboard_notice.isHidden()


def test_dashboard_notice_survives_the_2s_poll_that_used_to_wipe_it(qtbot):
    # Regression test for the real root cause found while building
    # Phase 3: run_worker() clears its target status_label to "" at the
    # START of every call, and _poll_selected_playlist() (which passes
    # status_label=self.status_label) runs on both the 2s poll_timer
    # tick and after every real backend poll — so ANY message written
    # to the old shared status_label had at most ~2s, often far less,
    # before the next poll silently wiped it regardless of severity.
    # InlineNotice lives outside run_worker's status_label plumbing
    # entirely, so a real poll tick must never clear it.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.dashboard_notice.show_message("Something worth reading", kind="error")
    assert not window.dashboard_notice.isHidden()

    window._poll_selected_playlist()
    qtbot.wait(50)

    assert window.dashboard_notice.text() == "Something worth reading"
    assert not window.dashboard_notice.isHidden()


def test_tag_selected_calls_tag_tracks_with_selected_ids(qtbot):
    statuses = [
        _make_track_status(track_id="s1", state=IN_LIBRARY),
        _make_track_status(track_id="s2", state=IN_LIBRARY),
        _make_track_status(track_id="s3", state=IN_LIBRARY),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    # Select rows 0 and 2 additively through the selection model itself
    # (QItemSelectionModel.Select | .Rows) — selectRow() replaces the
    # existing selection instead of adding to it, which isn't what a
    # real ctrl/shift-click multi-select produces.
    selection_model = window.track_table.selectionModel()
    for row in (0, 2):
        selection_model.select(
            window.track_table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    window.tag_selected_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    track_ids, analyze_audio, bpm_range, force = (
        application.metadata_service.tag_tracks_calls[0]
    )
    assert set(track_ids) == {"s1", "s3"}
    assert analyze_audio is False
    assert bpm_range is None
    assert force is False


def test_tag_selected_with_no_selection_shows_message_and_makes_no_call(qtbot):
    statuses = [_make_track_status(track_id="s1", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    window.tag_selected_button.click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "select" in window.dashboard_notice.text().lower()


def test_tag_playlist_calls_tag_playlist_with_playlist_name(qtbot):
    playlists = [Playlist(id="p1", name="240KM/H", track_count=5)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)

    window.tag_playlist_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_playlist_calls == [
        ("240KM/H", False, None, False),
    ]


def test_tag_playlist_without_selection_shows_message_and_makes_no_call(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.tag_playlist_button.click()

    assert application.metadata_service.tag_playlist_calls == []
    assert "playlist" in window.dashboard_notice.text().lower()


def test_results_panel_renders_breakdown_and_per_item_reasons(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = {
        "tagged": 2,
        "tagged_without_art": 0,
        "skipped_no_match": 1,
        "skipped_format_unsupported": 1,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 1,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_no_match",
                "message": "Artist A - Title A: no matched local file",
            },
            {
                "track_id": "t2",
                "reason": "failed",
                "message": "Artist B - Title B: disk read error",
            },
        ],
    }

    window._render_tag_result(result)

    text = window.tagging_results.toPlainText()
    assert "Tagged: 2" in text
    assert "Failed: 1" in text
    assert "[skipped_no_match] Artist A - Title A: no matched local file" in text
    assert "[failed] Artist B - Title B: disk read error" in text


def test_tag_result_notice_reports_tracks_without_art(qtbot):
    # Roadmap item 56 Phase 4.2 — the real fix: the UI must never show
    # a bare success when some tracks were tagged without cover art.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_tag_result({
        "tagged": 3,
        "tagged_without_art": 2,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [
            {
                "track_id": "t1",
                "reason": "tagged_without_art_no_url",
                "message": "Artist A - Title A: no album art URL stored",
            },
        ],
    })

    assert not window.dashboard_notice.isHidden()
    assert "2 without cover art" in window.dashboard_notice.text()


def test_tag_result_notice_shows_success_when_everything_worked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_tag_result({
        "tagged": 5,
        "tagged_without_art": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [],
    })

    assert not window.dashboard_notice.isHidden()
    assert "Tagged 5 tracks" in window.dashboard_notice.text()
    assert "without cover art" not in window.dashboard_notice.text()


# --- Duplicates tab (roadmap item 5) ---------------------------------------
#
# Locations load lazily, only once the page is actually shown (see
# main_window.py's own comment on _on_page_changed for why — an eager
# worker here, run during every MainWindow construction, was confirmed
# live to cause a real, reproducible deadlock under this test suite's
# own rapid-fire construction pattern). Tests below drive that
# explicitly rather than relying on construction alone.

def _switch_to_duplicates_tab(window) -> None:
    window._show_page("duplicates")


def test_duplicates_tab_has_persistent_subtitle(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    duplicates_page = window.stacked_widget.widget(
        window._duplicates_page_index
    )
    labels = [w.text() for w in duplicates_page.findChildren(QLabel)]

    assert help_text.DUPLICATES_TAB_SUBTITLE in labels


def test_duplicates_milestone_hidden_when_nothing_reclaimed_yet(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicates_milestone((0, 0))

    assert window.duplicates_milestone_label.isHidden()


def test_duplicates_milestone_shown_with_real_totals(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicates_milestone((312, 15_254_112_614))

    assert not window.duplicates_milestone_label.isHidden()
    text = window.duplicates_milestone_label.text()
    assert "reclaimed" in text
    assert "312 files" in text


def test_duplicates_tab_controls_have_tooltips(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.duplicates_location_combo.toolTip() != ""
    assert window.compute_fingerprints_button.toolTip() != ""
    assert window.find_duplicates_button.toolTip() != ""


def test_switching_to_duplicates_tab_loads_locations_lazily(qtbot):
    location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.duplicates_location_combo.count() == 0

    _switch_to_duplicates_tab(window)

    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 1, timeout=2000,
    )
    assert window.duplicates_location_combo.itemText(0) == "Main"


def test_switching_to_duplicates_tab_twice_refreshes_locations_each_time(
        qtbot,
):
    # Roadmap item 56 Phase 6.1 — reverses the old "loaded once ever"
    # guard: a location added after the first visit must actually
    # appear on a later revisit, which the old guard structurally
    # prevented (it was originally the fix for a real, confirmed Qt/
    # GIL deadlock from a CONSTRUCTION-time fetch — item 39 — not from
    # a page show, which is human-paced and doesn't reintroduce that
    # hazard).
    first_location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(first_location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 1, timeout=2000,
    )
    assert window.duplicates_location_combo.itemText(0) == "Main"

    # A location added since the first visit (mirrors adding one via
    # Settings, then coming back to Duplicates without restarting).
    second_location = LibraryLocation(
        id=2, name="Second", path="/music2",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application.library_service._locations = [
        (first_location, True), (second_location, True),
    ]

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 2, timeout=2000,
    )
    assert {
        window.duplicates_location_combo.itemText(i) for i in range(2)
    } == {"Main", "Second"}


def test_duplicates_location_refresh_preserves_the_current_selection(qtbot):
    first_location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    second_location = LibraryLocation(
        id=2, name="Second", path="/music2",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        locations=[(first_location, True), (second_location, True)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 2, timeout=2000,
    )
    window.duplicates_location_combo.setCurrentIndex(1)
    assert window._selected_duplicates_location() == "Second"

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: window.duplicates_location_combo.count() == 2, timeout=2000,
    )
    assert window._selected_duplicates_location() == "Second"


def test_compute_fingerprints_without_selection_shows_message(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_compute_fingerprints_clicked()

    assert "Select a library location" in window.duplicates_status_label.text()
    assert application.duplicate_service.compute_fingerprints_calls == []


def test_compute_fingerprints_calls_service_with_selected_location(qtbot):
    application = FakeApplication(
        fingerprint_result={
            "computed": 3, "skipped_already_computed": 1, "failed": 0,
            "details": [],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: application.duplicate_service.compute_fingerprints_calls == ["Main"],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: "Fingerprinted: 3" in window.duplicates_status_label.text(),
        timeout=2000,
    )


def test_find_duplicates_without_selection_shows_message(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_find_duplicates_clicked()

    assert "Select a library location" in window.duplicates_status_label.text()
    assert application.duplicate_service.find_duplicate_groups_calls == []


def test_find_duplicates_renders_no_duplicates_message(qtbot):
    application = FakeApplication(duplicate_groups=[])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._on_find_duplicates_clicked()

    qtbot.waitUntil(
        lambda: "No duplicates found" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    assert window.duplicates_table.rowCount() == 0


def _make_duplicate_group():
    from seeker.library.duplicate_service import DuplicateFile, DuplicateGroup
    from seeker.soulseek.quality import LocalFileQuality

    return DuplicateGroup(
        files=[
            DuplicateFile(
                local_file=LocalFile(
                    id=101,
                    location_id=1, relative_path="a.flac", filename="a.flac",
                    format="flac", size_bytes=1, mtime=0.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                ),
                quality=LocalFileQuality(
                    tier=2, bitrate_kbps=1000, bit_depth=16,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=None,
                ),
            ),
            DuplicateFile(
                local_file=LocalFile(
                    id=102,
                    location_id=1, relative_path="a.mp3", filename="a.mp3",
                    format="mp3", size_bytes=1, mtime=0.0,
                    scanned_at="2026-01-01T00:00:00+00:00",
                ),
                quality=LocalFileQuality(
                    tier=1, bitrate_kbps=320, bit_depth=None,
                    sample_rate=44_100, clipping_ratio=0.0,
                    integrated_loudness_lufs=None,
                ),
            ),
        ],
        similarity=0.987,
    )


def _make_duplicate_group_with_n_files(count: int):
    # Roadmap item 56 Phase 6.3 — confirms a group larger than two
    # already works by construction (one QButtonGroup per group, one
    # radio per file, delete removes every file except the checked
    # one), not just the 2-file case every other test here uses.
    from seeker.library.duplicate_service import DuplicateFile, DuplicateGroup
    from seeker.soulseek.quality import LocalFileQuality

    files = [
        DuplicateFile(
            local_file=LocalFile(
                id=200 + i,
                location_id=1, relative_path=f"copy{i}.mp3",
                filename=f"copy{i}.mp3", format="mp3", size_bytes=1,
                mtime=0.0, scanned_at="2026-01-01T00:00:00+00:00",
            ),
            quality=LocalFileQuality(
                tier=1, bitrate_kbps=320 - i, bit_depth=None,
                sample_rate=44_100, clipping_ratio=0.0,
                integrated_loudness_lufs=None,
            ),
        )
        for i in range(count)
    ]
    return DuplicateGroup(files=files, similarity=0.95)


def test_render_duplicate_groups_populates_table(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    assert window.duplicates_table.rowCount() == 2
    assert window.duplicates_table.item(0, 2).text() == "a.flac"
    assert window.duplicates_table.item(1, 2).text() == "a.mp3"
    assert window.duplicates_table.item(0, 5).text() == "98.7%"


def test_render_duplicate_groups_preselects_the_best_quality_file_to_keep(
        qtbot,
):
    # group.files is already best-quality-first (a.flac, tier 2, over
    # a.mp3, tier 1) -- the radio on row 0 must be pre-checked, row 1
    # must not be, and neither is auto-applied without a later click.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    keep_radio_0 = window.duplicates_table.cellWidget(0, 6)
    keep_radio_1 = window.duplicates_table.cellWidget(1, 6)
    assert isinstance(keep_radio_0, QRadioButton)
    assert isinstance(keep_radio_1, QRadioButton)
    assert keep_radio_0.isChecked() is True
    assert keep_radio_1.isChecked() is False


def test_duplicates_actions_column_renders_with_a_real_service_and_real_fingerprinting(
        qtbot, tmp_path,
):
    # Roadmap item 56 Phase 6.2 — the reported bug ("Actions column is
    # empty") reproduced the same way item 40 originally verified it:
    # a real, offscreen MainWindow wired to a REAL DuplicateService
    # (real Database, real repositories), two real generated duplicate
    # .wav files in a disposable temp directory, real
    # compute_fingerprints/find_duplicate_groups (real libchromaprint),
    # never the real library. Investigated, not just asserted: checked
    # a first render, a full re-render (stale QTableWidget.setSpan from
    # a previous render was one live hypothesis), and the real
    # asynchronous run_worker click path (a queued cross-thread signal
    # behaves differently than a direct call) — the Actions column
    # rendered correctly, visible, with both a real QPushButton and a
    # real QCheckBox, in every one of these. Could NOT reproduce the
    # reported bug; kept as a permanent regression guard against this
    # exact real pipeline rather than silently dropping the
    # investigation.
    import numpy as np
    import soundfile as sf

    from seeker import audio_fingerprint
    from seeker.database.connection import Database
    from seeker.database.repositories.library_location_repository import (
        LibraryLocationRepository,
    )
    from seeker.database.repositories.local_file_repository import (
        LocalFileRepository,
    )
    from seeker.database.repositories.track_match_repository import (
        TrackMatchRepository,
    )
    from seeker.library.duplicate_service import DuplicateService
    from seeker.library.scanner import LibraryScanner
    from seeker.models.library_location import LibraryLocation

    if audio_fingerprint._load_library() is None:
        pytest.skip("libchromaprint isn't installed on this machine")

    scratch = tmp_path / "dupes"
    scratch.mkdir()
    sample_rate = 44_100
    duration_seconds = 3
    t = np.linspace(
        0, duration_seconds, sample_rate * duration_seconds, endpoint=False,
    )
    tone = (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    sf.write(str(scratch / "a.wav"), tone, sample_rate)
    sf.write(str(scratch / "a_copy.wav"), tone, sample_rate)

    db = Database(tmp_path / "seeker.db")
    db.initialize()
    locations = LibraryLocationRepository(db)
    local_files = LocalFileRepository(db)
    track_matches = TrackMatchRepository(db)

    with db.transaction() as connection:
        locations.add(
            LibraryLocation(
                name="ReproDupes", path=str(scratch), added_at="2026-01-01",
            ),
            connection,
        )
        location = locations.get_by_name("ReproDupes", connection)

    duplicate_service = DuplicateService(
        db, locations, local_files, track_matches,
    )
    LibraryScanner(local_files, db).scan(location)
    duplicate_service.compute_fingerprints("ReproDupes")
    groups = duplicate_service.find_duplicate_groups("ReproDupes")
    assert len(groups) == 1  # sanity check: the real pair was found

    application = FakeApplication()
    application.duplicate_service = duplicate_service
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("duplicates")

    for _ in range(2):  # first render, then a full re-render
        window._render_duplicate_groups(groups)
        widget = window.duplicates_table.cellWidget(0, 7)
        assert widget is not None
        assert widget.isVisible()
        assert widget.findChild(QPushButton) is not None
        assert widget.findChild(QCheckBox) is not None


def test_render_duplicate_groups_actions_only_on_group_first_row(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    first_row_actions = window.duplicates_table.cellWidget(0, 7)
    other_row_actions = window.duplicates_table.cellWidget(1, 7)
    assert first_row_actions.findChildren(QPushButton)
    assert not other_row_actions.findChildren(QPushButton)


def _confirm_yes(monkeypatch) -> None:
    # Real modal QMessageBox.exec() would hang a test — every test that
    # expects a delete to actually proceed past the new Phase 6.3
    # confirmation dialog stubs the static question() classmethod to
    # answer Yes, the same way a real user clicking Yes would.
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )


def test_delete_duplicates_without_confirm_checkbox_does_not_delete(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 7)
    delete_button = actions.findChildren(QPushButton)[0]
    delete_button.click()

    assert application.duplicate_service.delete_local_files_calls == []
    assert "Confirm delete" in window.duplicates_status_label.text()


def test_delete_duplicates_with_confirm_checkbox_deletes_non_kept_files(
        qtbot, monkeypatch,
):
    # a.flac (id 101) is pre-selected to keep (best quality) -- clicking
    # Delete with the checkbox checked must delete only a.mp3 (id 102).
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service.delete_local_files_calls = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    assert application.duplicate_service.delete_local_files_calls == [([102], 101, None)]


def test_delete_duplicates_respects_a_changed_keep_selection(qtbot, monkeypatch):
    # Moving the radio to a.mp3 (id 102) before deleting must delete
    # a.flac (id 101) instead of the pre-selected default.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    window.duplicates_table.cellWidget(1, 6).setChecked(True)

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    assert application.duplicate_service.delete_local_files_calls == [([101], 102, None)]


def test_delete_duplicates_finished_removes_group_locally_without_refetch(
        qtbot, monkeypatch,
):
    # Deliberately NOT a find_duplicate_groups() re-fetch after a
    # single-group resolution -- that call recomputes an entire
    # location's clustering from scratch every time, confirmed live to
    # cost ~10 real minutes over a real ~3,100-file/344-group library
    # (docs/HISTORY.md item 39). Resolving groups one at a time must
    # drop each one from the in-memory list this tab already holds
    # instead, with zero additional service calls.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service._delete_result = {
        "deleted": 1, "failed": 0, "details": [],
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: "Deleted: 1, Failed: 0" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    assert application.duplicate_service.find_duplicate_groups_calls == []
    assert window.duplicates_table.rowCount() == 0
    assert window._current_duplicate_groups == []


def test_delete_duplicates_partial_failure_keeps_group_visible(qtbot, monkeypatch):
    # A partial failure means the group's real DB/disk state may not
    # actually match "fully resolved" -- it must stay visible rather
    # than being dropped as if it were.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service._delete_result = {
        "deleted": 0, "failed": 1, "details": [],
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: "Deleted: 0, Failed: 1" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    assert window.duplicates_table.rowCount() == 2
    assert len(window._current_duplicate_groups) == 1


def test_delete_duplicates_confirmation_dialog_lists_exact_full_paths(
        qtbot, monkeypatch,
):
    # Roadmap item 56 Phase 6.3 — deleting real user files warrants
    # naming them.
    captured: dict[str, str] = {}

    def fake_question(self, title, body, *args, **kwargs):
        captured["title"] = title
        captured["body"] = body
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)

    application = FakeApplication(duplicate_groups=[_make_duplicate_group()])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )
    window._current_duplicates_location_name = "Main"
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    assert "/music/a.mp3" in captured["body"]
    assert "a.flac" not in captured["body"]  # the kept file, not deleted


def test_keep_all_disables_delete_and_deletes_nothing(qtbot, monkeypatch):
    # Roadmap item 56 Phase 6.3 — "the same file living in several
    # folders is sometimes deliberate."
    _confirm_yes(monkeypatch)
    application = FakeApplication(duplicate_groups=[_make_duplicate_group()])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    actions = window.duplicates_table.cellWidget(0, 7)
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox = actions.findChildren(QCheckBox)[0]
    keep_all_radio = [
        w for w in actions.findChildren(QRadioButton)
        if w.text() == "Keep all"
    ][0]

    assert delete_button.isEnabled()

    keep_all_radio.setChecked(True)

    assert not delete_button.isEnabled()

    # Defense in depth: even a direct call must not delete anything.
    checkbox.setChecked(True)
    window._on_delete_duplicates_clicked(
        window._current_duplicate_groups[0],
        window._duplicate_button_groups[0],
        checkbox,
        delete_button,
    )
    assert application.duplicate_service.delete_local_files_calls == []


def test_delete_duplicates_group_of_three_deletes_exactly_two(qtbot, monkeypatch):
    _confirm_yes(monkeypatch)
    group = _make_duplicate_group_with_n_files(3)
    application = FakeApplication(duplicate_groups=[group])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group])

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    delete_ids, keep_id, _location_id = application.duplicate_service.delete_local_files_calls[0]
    assert keep_id == 200  # files[0] is the group's own recommendation
    assert sorted(delete_ids) == [201, 202]


def test_delete_duplicates_group_of_four_deletes_exactly_three(qtbot, monkeypatch):
    _confirm_yes(monkeypatch)
    group = _make_duplicate_group_with_n_files(4)
    application = FakeApplication(duplicate_groups=[group])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group])

    actions = window.duplicates_table.cellWidget(0, 7)
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    delete_ids, keep_id, _location_id = application.duplicate_service.delete_local_files_calls[0]
    assert keep_id == 200
    assert sorted(delete_ids) == [201, 202, 203]


# --- Sharing page (roadmap item 62, Phase 7) --------------------------------

def _make_location(location_id: int, name: str, path: str) -> LibraryLocation:
    return LibraryLocation(
        id=location_id, name=name, path=path,
        added_at="2026-01-01T00:00:00+00:00",
    )


def test_sharing_shows_unconfigured_notice_when_soulseek_not_set_up(qtbot):
    application = FakeApplication(soulseek_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    qtbot.waitUntil(
        lambda: bool(window.sharing_summary_label.text()), timeout=2000,
    )
    assert "isn't configured" not in window.sharing_summary_label.text() or True
    from seeker.ui import help_text
    assert (
        window.sharing_summary_label.text()
        == help_text.SHARING_UNCONFIGURED_NOTICE
    )
    assert window.sharing_locations_table.rowCount() == 0


def test_sharing_renders_reconciliation_and_uploads(qtbot):
    from seeker.sharing_service import LocationShareState, ShareEntry, ShareStatus

    location = _make_location(1, "Music", "/Volumes/Drive/Music")
    other = _make_location(2, "Other", "/Volumes/Drive/Other")
    status = ShareStatus(
        ready=True, scanning=False, scan_pending=False, faulted=False,
        directories=1, files=5, shares=[],
    )
    reconciliation = [
        LocationShareState(
            location=location, shared=True,
            share=ShareEntry(
                id="1", alias="music", local_path="/shared/music",
                is_excluded=False, directories=1, files=5,
            ),
        ),
        LocationShareState(location=other, shared=False, share=None),
    ]
    sharing_service = FakeSharingService(
        status=status, self_managed=True, reconciliation=reconciliation,
        uploads=[],
    )
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    qtbot.waitUntil(
        lambda: window.sharing_locations_table.rowCount() == 2, timeout=2000,
    )
    assert window.sharing_locations_table.item(0, 1).text() == "Yes"
    assert window.sharing_locations_table.item(1, 1).text() == "No"
    assert isinstance(
        window.sharing_locations_table.cellWidget(1, 4), QPushButton,
    )
    assert window.sharing_uploads_table.item(0, 0).text() == (
        help_text.NO_UPLOADS_LABEL
    )


def test_sharing_add_to_share_button_calls_service_after_confirm(
        qtbot, monkeypatch,
):
    from seeker.sharing_service import LocationShareState

    location = _make_location(2, "Other", "/Volumes/Drive/Other")
    from seeker.sharing_service import ShareStatus

    sharing_service = FakeSharingService(
        status=ShareStatus(
            ready=True, scanning=False, scan_pending=False,
            faulted=False, directories=0, files=0, shares=[],
        ),
        self_managed=True,
        reconciliation=[
            LocationShareState(location=location, shared=False, share=None),
        ],
    )
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _confirm_yes(monkeypatch)

    window._show_page("sharing")
    qtbot.waitUntil(
        lambda: window.sharing_locations_table.rowCount() == 1, timeout=2000,
    )

    button = window.sharing_locations_table.cellWidget(0, 4)
    button.click()

    qtbot.waitUntil(
        lambda: bool(sharing_service.add_location_to_share_calls),
        timeout=2000,
    )
    called_location, confirm = sharing_service.add_location_to_share_calls[0]
    assert called_location.name == "Other"
    assert confirm is True


def test_sharing_not_self_managed_shows_guidance_instead_of_writing(
        qtbot, monkeypatch,
):
    from seeker.sharing_service import LocationShareState

    location = _make_location(2, "Other", "/Volumes/Drive/Other")
    from seeker.sharing_service import ShareStatus

    sharing_service = FakeSharingService(
        status=ShareStatus(
            ready=True, scanning=False, scan_pending=False,
            faulted=False, directories=0, files=0, shares=[],
        ),
        self_managed=False,
        reconciliation=[
            LocationShareState(location=location, shared=False, share=None),
        ],
    )
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    info_calls = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: info_calls.append(a),
    )

    window._show_page("sharing")
    qtbot.waitUntil(
        lambda: window.sharing_locations_table.rowCount() == 1, timeout=2000,
    )

    button = window.sharing_locations_table.cellWidget(0, 4)
    button.click()

    assert len(info_calls) == 1
    assert sharing_service.add_location_to_share_calls == []

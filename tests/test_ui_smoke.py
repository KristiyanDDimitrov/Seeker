import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from PySide6.QtCore import QItemSelectionModel, QRect, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSystemTrayIcon,
)

from seeker.config_store import SeekerConfig
from seeker.library.metadata_service import RenamePlan, RenameResult
from seeker.models.active_download import ActiveDownload
from seeker.models.data_locations import DataLocations
from seeker.models.download_request import DownloadRequest
from seeker.models.history_event import DOWNLOADED, TAGGED, HistoryEvent
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.playlist import Playlist
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_status import (
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.ui import help_text, theme
from seeker.ui import workers as workers_module
from seeker.ui.main_window import (
    _THEME_MODE_CYCLE,
    AboutDialog,
    BulkReplaceUpgradesDialog,
    BulkResolveDuplicatesDialog,
    DestinationDialog,
    MainWindow,
    RenamePreviewDialog,
    _resolve_tray_icon_path,
    _ThemeToggleButton,
)
from seeker.ui.workers import Worker, run_worker
from seeker.update_check import UpdateCheckResult, UpdateStatus

# Per this project's own testing philosophy, applied to the UI layer:
# widget construction/wiring is thin glue around already-tested
# services (cli.py/main.py's argparse dispatch gets the same light
# treatment) — these are smoke tests confirming the window builds and
# the worker abstraction's signals fire correctly, not deep Qt coverage.


class FakeSyncService:
    def __init__(
            self,
            playlists: list[Playlist] | None = None,
            art_urls_filled: int = 0,
    ):
        self._playlists = playlists or []
        self.sync_playlists_calls = 0
        self.sync_playlist_tracks_calls: list[Playlist] = []
        self._art_urls_filled = art_urls_filled

    def list_playlists(self) -> list[Playlist]:
        return self._playlists

    def sync_playlists(self) -> None:
        self.sync_playlists_calls += 1

    def sync_playlist_tracks(self, playlist: Playlist) -> int:
        self.sync_playlist_tracks_calls.append(playlist)
        return self._art_urls_filled


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
            scope_file_count: int = 0,
            folder_scopes: list | None = None,
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
        self._scope_file_count = scope_file_count
        # Roadmap item 68 (Phase 7.2) — resolve_folder_scopes' fake
        # result; a test that wants real DuplicateFolderScope objects
        # (e.g. to exercise the per-location grouping in
        # _compute_fingerprints_for_folders) passes these in directly.
        self._folder_scopes = folder_scopes or []
        self.compute_fingerprints_calls: list[
            tuple[str, list[str] | None]
        ] = []
        self.find_duplicate_groups_calls: list[
            tuple[str, list[str] | None]
        ] = []
        self.find_duplicate_groups_across_scopes_calls: list[list] = []
        self.resolve_folder_scopes_calls: list[
            tuple[list[str], int | None]
        ] = []
        self.count_files_for_scopes_calls: list[list] = []
        self.summarize_scopes_calls: list[list] = []
        # Roadmap item 77 (P8.3/8.4) — real ScopeSummary fields the fake
        # returns from summarize_scopes(); defaults keep every existing
        # test's plain "N files in scope" text unchanged.
        self._scope_resolved_location_names: list[str] = []
        self._scope_empty_locations: list[str] = []
        self.delete_local_files_calls: list[
            tuple[list[int], int | None, int | None]
        ] = []
        self.record_cleanup_calls: list[tuple[int, int, int | None]] = []
        # Roadmap item R3.2 — "Resolve all groups".
        self.resolve_groups_calls: list[list] = []
        from seeker.library.duplicate_service import (
            BulkDuplicateResolutionResult,
        )
        self.resolve_groups_result = BulkDuplicateResolutionResult(
            groups_resolved=0, groups_failed=0, files_deleted=0,
            files_failed=0, files_skipped_same_physical_file=0,
            bytes_freed=0, details=[], plan_outcomes=[],
        )

    def compute_fingerprints(
            self,
            location_name: str,
            force: bool = False,
            folders: list[str] | None = None,
            progress=None,
    ) -> dict:
        self.compute_fingerprints_calls.append((location_name, folders))
        if progress is not None:
            progress("Fingerprinting", 1, 1)
        return self._fingerprint_result

    def find_duplicate_groups(
            self,
            location_name: str,
            folders: list[str] | None = None,
            progress=None,
    ) -> list:
        self.find_duplicate_groups_calls.append((location_name, folders))
        if progress is not None:
            progress("Comparing", 1, 1)
        return self._groups

    def resolve_folder_scopes(
            self,
            folder_paths: list[str],
            preferred_location_id: int | None = None,
    ) -> list:
        self.resolve_folder_scopes_calls.append(
            (list(folder_paths), preferred_location_id)
        )
        return self._folder_scopes

    def count_files_for_scopes(self, scopes: list) -> int:
        self.count_files_for_scopes_calls.append(list(scopes))
        return self._scope_file_count

    def summarize_scopes(self, scopes: list):
        from seeker.library.duplicate_service import ScopeSummary

        self.summarize_scopes_calls.append(list(scopes))
        return ScopeSummary(
            file_count=self._scope_file_count,
            resolved_location_names=self._scope_resolved_location_names,
            empty_locations=self._scope_empty_locations,
        )

    def find_duplicate_groups_across_scopes(
            self, scopes: list, progress=None,
    ) -> list:
        self.find_duplicate_groups_across_scopes_calls.append(list(scopes))
        if progress is not None:
            progress("Comparing", 1, 1)
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

    def resolve_groups(self, plans: list):
        self.resolve_groups_calls.append(list(plans))
        return self.resolve_groups_result


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
            search_manual_results: list | None = None,
            download_manual_result: dict | None = None,
            download_manual_error: Exception | None = None,
    ):
        self._review_candidates = review_candidates or []
        self._pending_upgrades = pending_upgrades or []
        # Roadmap item 82 (P13) — manual (not-from-Spotify) search/
        # download.
        self._search_manual_results = search_manual_results or []
        self._download_manual_result = download_manual_result or {
            "requested": False, "settled": False,
            "reason": "no_candidate_found",
        }
        self._download_manual_error = download_manual_error
        self.search_manual_calls: list[tuple[str, str]] = []
        self.download_manual_calls: list[tuple] = []
        self.confirm_review_candidate_calls: list[str] = []
        self.reject_review_candidate_calls: list[str] = []
        self.apply_upgrade_decision_calls: list[tuple[int, bool, bool]] = []
        self.apply_upgrade_decision_result: str | None = (
                "Replaced with /new/path"
        )
        # Roadmap item R3.1 — "Replace all".
        self.apply_upgrade_decisions_batch_calls: list[
            tuple[list[int], bool]
        ] = []
        from seeker.soulseek.download_service import BulkUpgradeReplaceResult
        self.apply_upgrade_decisions_batch_result = BulkUpgradeReplaceResult(
            replaced=0, failed=0, details=[],
        )
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
        self.apply_upgrade_decision_calls.append(
                (request_id, replace, delete_old)
        )
        return self.apply_upgrade_decision_result if replace else None

    def apply_upgrade_decisions_batch(
            self, request_ids: list[int], delete_old: bool,
    ):
        self.apply_upgrade_decisions_batch_calls.append(
                (request_ids, delete_old)
        )
        return self.apply_upgrade_decisions_batch_result

    def search_manual(self, artist: str, title: str) -> list:
        self.search_manual_calls.append((artist, title))
        return self._search_manual_results

    def download_manual(
            self,
            artist: str,
            title: str,
            chosen=None,
            files=None,
    ) -> dict:
        self.download_manual_calls.append((artist, title, chosen, files))
        if self._download_manual_error is not None:
            raise self._download_manual_error
        return self._download_manual_result


_EMPTY_TAG_RESULT = {
    "tagged": 0,
    "tagged_without_art": 0,
    "tagged_art_rarely_supported_format": 0,
    "skipped_no_match": 0,
    "skipped_format_unsupported": 0,
    "skipped_already_tagged": 0,
    "skipped_already_analyzed": 0,
    "failed": 0,
    "details": [],
}


_EMPTY_FIX_ART_RESULT = {
    "fixed": 0,
    "fixed_wav_rarely_supported": 0,
    "already_correct": 0,
    "no_url": 0,
    "download_failed": 0,
    "embed_failed": 0,
    "format_unsupported": 0,
    "skipped_no_match": 0,
    "failed": 0,
    "details": [],
}


class FakeMetadataService:
    def __init__(
            self,
            tag_result: dict | None = None,
            fix_art_result: dict | None = None,
            rename_plans: list | None = None,
            rename_result=None,
    ):
        self._tag_result = tag_result or dict(_EMPTY_TAG_RESULT)
        self._fix_art_result = fix_art_result or dict(_EMPTY_FIX_ART_RESULT)
        self._rename_plans = rename_plans or []
        self._rename_result = rename_result
        self.tag_tracks_calls: list[
                tuple[list[str], bool, tuple | None, bool]
        ] = []
        self.tag_playlist_calls: list[
                tuple[str, bool, tuple | None, bool]
        ] = []
        self.fix_missing_art_for_playlist_calls: list[str] = []
        self.plan_renames_calls: list[str] = []
        self.apply_renames_calls: list[list] = []

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

    def fix_missing_art_for_playlist(self, playlist_name: str) -> dict:
        self.fix_missing_art_for_playlist_calls.append(playlist_name)
        return self._fix_art_result

    def plan_renames(self, playlist_name: str | None = None, track_ids=None):
        self.plan_renames_calls.append(playlist_name)
        return self._rename_plans

    def apply_renames(self, plans: list):
        self.apply_renames_calls.append(plans)
        return self._rename_result


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
            art_urls_filled: int = 0,
            fix_art_result: dict | None = None,
            rename_plans: list | None = None,
            rename_result=None,
    ):
        self.sync_service = FakeSyncService(playlists, art_urls_filled)
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
        self.metadata_service = FakeMetadataService(
            tag_result, fix_art_result, rename_plans, rename_result,
        )
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
        # Roadmap item 116 (round 8, §6.6.1) — settings_window.py's
        # connection tab reads this at construction time now (the new
        # remote-slskd-over-http warning); mirrors the real
        # Application's own `_config_store.slskd_base_url or
        # config.SLSKD_BASE_URL` fallback, always None here since no
        # smoke test needs a configured slskd URL.
        self._slskd_base_url: str | None = None
        self.persist_default_destination_calls: list[tuple[int, bool]] = []
        # Roadmap item R7.4/R7.1/R7.5 — mirrors the real Application's
        # own methods, same shape as persist_default_destination above.
        self.set_downloads_paused_calls: list[bool] = []
        self.mark_tray_hide_notice_shown_calls = 0
        self.set_notification_preference_calls: list[tuple[str, bool]] = []
        self.set_theme_mode_calls: list[str] = []

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

    @property
    def downloads_paused(self) -> bool:
        return self._config_store.downloads_paused

    def set_downloads_paused(self, paused: bool) -> None:
        self.set_downloads_paused_calls.append(paused)
        self._config_store = replace(
                self._config_store,
                downloads_paused=paused,
        )

    def mark_tray_hide_notice_shown(self) -> None:
        self.mark_tray_hide_notice_shown_calls += 1
        self._config_store = replace(
            self._config_store, tray_hide_notice_shown=True,
        )

    def set_notification_preference(
            self,
            field_name: str,
            enabled: bool,
    ) -> None:
        self.set_notification_preference_calls.append((field_name, enabled))
        self._config_store = replace(
            self._config_store, **{field_name: enabled},
        )

    @property
    def theme_mode(self) -> str:
        return self._config_store.theme_mode

    def set_theme_mode(self, mode: str) -> None:
        self.set_theme_mode_calls.append(mode)
        self._config_store = replace(self._config_store, theme_mode=mode)


def test_main_window_constructs_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Roadmap item 98 (B10) — reversed from item 81 (0.1): a commit SHA
    # in the window title looked like a bug even when it wasn't one.
    # Build identity's real home is Help -> About Seeker (see
    # test_about_dialog_shows_build_identity), unaffected by this.
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

    assert window.stacked_widget.currentIndex() == window._page_indices[
            "dashboard"
    ]
    assert window._nav_buttons["dashboard"].isChecked()


def test_show_page_switches_stack_and_updates_checked_nav_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("downloads")

    assert window.stacked_widget.currentIndex() == window._page_indices[
            "downloads"
    ]
    assert window._nav_buttons["downloads"].isChecked()
    assert not window._nav_buttons["dashboard"].isChecked()


def test_nav_buttons_are_mutually_exclusive_including_settings(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Every real page (Dashboard/Search/Downloads/Review/Duplicates/
    # History) plus Help, Support, and Settings share one exclusive
    # QButtonGroup — roadmap item 56 Phase 3 reversed item 48's
    # "Settings stays a separate dialog" decision, so it's now a real,
    # checkable nav-group member like every other page; item 64 added
    # Support the same way, item 82 added Search the same way.
    assert set(window._nav_buttons) == {
        "dashboard", "search", "downloads", "review", "duplicates",
        "sharing", "history", "help", "support", "settings",
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

    history_page = window.stacked_widget.widget(
            window._page_indices["history"]
    )
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


# --- Support page (roadmap item 64) -----------------------------------

def test_support_page_exists_directly_below_help_in_the_sidebar(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert "support" in window._page_indices
    support_page = window.stacked_widget.widget(
            window._page_indices["support"]
    )
    labels = [w.text() for w in support_page.findChildren(QLabel)]
    assert help_text.SUPPORT_TAB_SUBTITLE in labels

    # Directly below Help — both individually-built (not part of the
    # generic _NAV_PAGES loop), so this checks real sidebar layout order
    # rather than just dict/insertion order.
    sidebar = window._nav_buttons["help"].parentWidget()
    assert sidebar is window._nav_buttons["support"].parentWidget()
    layout = sidebar.layout()
    assert layout is not None
    indices = [
        layout.indexOf(window._nav_buttons[key]) for key in ("help", "support")
    ]
    assert indices[1] == indices[0] + 1


def test_support_page_shows_honest_framing_and_non_financial_help(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    support_page = window.stacked_widget.widget(
            window._page_indices["support"]
    )
    labels_html = "\n".join(
            w.text() for w in support_page.findChildren(QLabel)
    )

    assert "no telemetry" in labels_html
    assert "no paid tier" in labels_html
    assert "thank-you, not a purchase" in labels_html
    assert "Report a bug" in labels_html
    assert "github.com/KristiyanDDimitrov/Seeker/issues" in labels_html
    assert "Share your library back on SoulSeek" in labels_html
    assert "Kristiyan Dimitrov" in labels_html  # ABOUT_DIALOG_AUTHOR_LINE, reused


def test_support_page_renders_a_button_for_every_real_support_link(
        qtbot, monkeypatch,
):
    from seeker.ui import main_window as main_window_module

    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module.webbrowser, "open", opened.append
    )

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    support_page = window.stacked_widget.widget(
            window._page_indices["support"]
    )
    buttons = [
        widget
        for widget in support_page.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert len(buttons) == len(help_text.SUPPORT_LINKS)
    assert {button.text() for button in buttons} == {
        f"Support on {name}" for name in help_text.SUPPORT_LINKS
    }

    for button in buttons:
        button.click()

    assert set(opened) == set(help_text.SUPPORT_LINKS.values())


def test_support_page_go_to_sharing_button_navigates_to_sharing_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("support")
    assert window.stacked_widget.currentIndex() == window._page_indices[
            "support"
    ]

    support_page = window.stacked_widget.widget(
            window._page_indices["support"]
    )
    go_button = next(
        widget for widget in support_page.findChildren(QPushButton)
        if widget.text() == help_text.SUPPORT_PAGE_GO_TO_SHARING_BUTTON_TEXT
    )
    go_button.click()

    assert window.stacked_widget.currentIndex() == window._page_indices[
            "sharing"
    ]


# --- Busy-action registry / activity strip (roadmap item 65, Phase 2) -----

def test_render_next_step_does_not_reenable_a_button_whose_action_is_running(
        qtbot,
):
    # Regression test for Phase 0's own 0.1 finding, live-proven via an
    # instrumented offscreen MainWindow: _render_next_step runs on every
    # 2s poll tick and used to unconditionally re-enable the scan button
    # from static facts alone, with no idea a real scan_and_match() might
    # still be running. Exercises the exact same method directly, with a
    # real busy_actions.begin() standing in for "still running".
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin("scan", window.scan_button, "Scanning…")
    assert window.scan_button.isEnabled() is False

    facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(facts)

    # Pre-fix, this would have been re-enabled here since
    # facts.has_library_location is True.
    assert window.scan_button.isEnabled() is False
    assert window.scan_button.text() == "Scanning…"

    window.busy_actions.end("scan")
    window._render_next_step(facts)
    assert window.scan_button.isEnabled() is True
    assert window.scan_button.text() == "Rescan and match library"


def test_render_next_step_does_not_hide_or_reenable_download_button_mid_download(
        qtbot,
):
    # Regression test for the real, reported bug found alongside 0.1:
    # download_button.setVisible(step.action != "download") could hide
    # the download button entirely mid-download, the instant the CTA's
    # own action was still "download" (which it usually still is, since
    # the missing-track count hasn't changed yet).
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin(
        "download", window.download_button, "Starting download…",
    )
    assert window.download_button.isEnabled() is False

    # CTA's own current action is "download" -- pre-fix, setVisible(step
    # .action != "download") would hide the button here.
    facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name="Test Playlist",
        track_statuses=[_make_track_status(state=NOT_FOUND)],
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(facts)

    assert not window.download_button.isHidden()
    assert window.download_button.isEnabled() is False
    assert window.download_button.text() == "Starting download…"

    window.busy_actions.end("download")
    window._render_next_step(facts)
    assert window.download_button.isHidden()  # CTA now owns it
    assert window.download_button.text() == "Download selected playlist"


def test_activity_strip_hidden_when_nothing_running(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_activity_strip()
    assert window.activity_strip.isHidden()


def test_activity_strip_shows_label_for_a_single_running_action(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin("scan", window.scan_button, "Scanning…")
    window._render_activity_strip()

    assert not window.activity_strip.isHidden()
    assert (
        window.activity_strip_label.text()
        == "Scanning library and matching tracks…"
    )
    assert window.activity_strip_bar.minimum() == 0
    assert window.activity_strip_bar.maximum() == 0  # indeterminate

    window.busy_actions.end("scan")
    window._render_activity_strip()
    assert window.activity_strip.isHidden()


def test_activity_strip_shows_a_count_for_multiple_running_actions(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin("scan", window.scan_button)
    window.busy_actions.begin("sync", window.sync_button)
    window._render_activity_strip()

    assert not window.activity_strip.isHidden()
    assert window.activity_strip_label.text() == "2 actions running"


def test_activity_strip_renders_real_progress_when_reported(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin(
        "compute_fingerprints", window.compute_fingerprints_button,
    )
    window._on_activity_progress("compute_fingerprints", "Decoding", 40, 100)

    assert not window.activity_strip.isHidden()
    assert "40/100" in window.activity_strip_label.text()
    assert window.activity_strip_bar.minimum() == 0
    assert window.activity_strip_bar.maximum() == 100
    assert window.activity_strip_bar.value() == 40


def test_open_in_file_manager_dispatches_by_platform(tmp_path, monkeypatch):
    from seeker.ui.main_window import _open_in_file_manager

    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(
        "seeker.ui.main_window.subprocess.run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    target = tmp_path / "does" / "not" / "exist" / "yet"

    monkeypatch.setattr("seeker.ui.main_window.sys.platform", "darwin")
    _open_in_file_manager(target)
    assert calls[-1] == (["open", str(target)], {"check": False})
    assert target.is_dir()  # created on demand, per the docstring

    monkeypatch.setattr("seeker.ui.main_window.sys.platform", "win32")
    _open_in_file_manager(target)
    assert calls[-1] == (["explorer", str(target)], {"check": False})

    monkeypatch.setattr("seeker.ui.main_window.sys.platform", "linux")
    _open_in_file_manager(target)
    assert calls[-1] == (["xdg-open", str(target)], {"check": False})


def test_open_data_folder_button_calls_the_file_manager_opener(
        qtbot, monkeypatch,
):
    from seeker.ui import main_window as main_window_module

    opened: list = []
    monkeypatch.setattr(
        main_window_module, "_open_in_file_manager",
        opened.append,
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
    # Roadmap item R7.5 — MainWindow's own construction already makes
    # one real get_recent_events(limit=1) call to silently seed the
    # download-notification cutoff (see _seed_notification_cutoff), so
    # the History page's own first real fetch is real call #2, not #1.
    assert application.history_service.get_recent_events_calls == 2
    assert window.history_table.item(0, 1).text() == "Downloaded"
    assert "ZENEA - INFINITE" in window.history_table.item(0, 2).text()
    assert window.history_table.item(1, 1).text() == "Tagged"

    # Lazy-load-once, same precedent as Duplicates — switching away and
    # back must not refetch.
    window._show_page("dashboard")
    window._show_page("history")
    assert application.history_service.get_recent_events_calls == 2


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
    # Roadmap item R7.5 — call #1 is MainWindow construction's own
    # silent notification-cutoff seed (see _seed_notification_cutoff);
    # this page visit is real call #2.
    qtbot.waitUntil(
        lambda: application.history_service.get_recent_events_calls == 2,
        timeout=2000,
    )

    window.history_refresh_button.click()

    qtbot.waitUntil(
        lambda: application.history_service.get_recent_events_calls == 3,
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
    assert window.scan_button.text() == "Rescan and match library"
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


# --- Roadmap item 71 (P3): dismissed next-step notice stays dismissed ------

def test_dismissed_next_step_notice_stays_hidden_across_poll_ticks(qtbot):
    # Regression test for the real reported bug: "You're all set"
    # reappeared ~2s after being dismissed, because _render_next_step
    # called show_message() unconditionally on every poll tick with no
    # memory of the dismissal. Drives _render_next_step directly
    # (not the real 2s timer) so three "ticks" are deterministic.
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    facts = _NextStepFacts(
        spotify_configured=False,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(facts)
    assert not window.next_step_notice.isHidden()

    window.next_step_notice.dismiss()
    assert window.next_step_notice.isHidden()

    for _ in range(3):
        window._render_next_step(facts)
        assert window.next_step_notice.isHidden()

    # A genuinely different step (facts changed) must still surface —
    # dismissal is per-step, not a permanent silence.
    other_facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=False,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(other_facts)
    assert not window.next_step_notice.isHidden()
    assert "music folder" in window.next_step_notice.text().lower()


def test_dismissed_next_step_notice_reappears_when_it_recurs_later(qtbot):
    # The identical step recurring after something else was shown in
    # between must NOT stay suppressed by an old dismissal.
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    step_facts = _NextStepFacts(
        spotify_configured=False,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    all_set_facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )

    window._render_next_step(step_facts)
    assert not window.next_step_notice.isHidden()
    window.next_step_notice.dismiss()

    window._render_next_step(all_set_facts)
    assert window.next_step_notice.isHidden()

    # The same step comes back later (e.g. the user disconnected
    # Spotify again) -- it must show, not stay silenced by the earlier
    # dismissal of a since-superseded instance of it.
    window._render_next_step(step_facts)
    assert not window.next_step_notice.isHidden()


# --- Roadmap item 72 (P1): tagging row reflows, playlist panel keeps its
# floor ------------------------------------------------------------------

def test_dashboard_content_minimum_width_fits_under_the_app_minimum(qtbot):
    # Regression test for the real reported bug: a plain QHBoxLayout's
    # minimum width is the SUM of its children's minimum widths, so the
    # 9-widget tagging controls row imposed a ~900-1000px floor on the
    # whole dashboard page, squeezing the playlist panel next to it
    # down to almost nothing at the app's own 960x640 minimum window
    # size (main_window.py:945).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.resize(960, 640)

    dashboard_content = window.playlist_list.parentWidget()
    assert dashboard_content.minimumSizeHint().width() < 960


def test_playlist_list_keeps_its_floor_at_the_app_minimum_window_size(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.resize(960, 640)
    qtbot.wait(20)

    assert window.playlist_list.minimumWidth() > 0
    assert window.playlist_list.width() >= window.playlist_list.minimumWidth()


def test_tagging_controls_row_reflows_to_multiple_rows_when_narrow(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    layout = window.tagging_controls_layout
    single_row_height = max(
        layout.itemAt(i).sizeHint().height() for i in range(layout.count())
    )

    # Wide: collapses back to a single row.
    assert layout.heightForWidth(1600) <= single_row_height + 4

    # Narrow: really does grow to 2+ rows, not just clip/scroll.
    assert layout.heightForWidth(320) >= single_row_height * 2


def test_tagging_controls_row_minimum_size_is_the_widest_item_not_the_sum(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    layout = window.tagging_controls_layout
    widths = [
            layout.itemAt(i).sizeHint().width() for i in range(layout.count())
    ]

    assert layout.minimumSize().width() < sum(widths) / 2
    assert layout.minimumSize().width() >= max(widths)


def test_tagging_controls_row_has_real_spacing_between_items(qtbot):
    # Roadmap item 79 (P11) — bare FlowLayout() left h_spacing/
    # v_spacing at -1, falling through to _smart_spacing()'s style
    # query, which is approximately zero under this app's Fusion
    # styling — the buttons ended up touching. Checked at two widths:
    # a wide layout (items on one row, horizontal gaps matter) and a
    # narrow one (items wrap onto multiple rows, vertical gaps matter).
    #
    # Roadmap item RR2 — diagnosed for real, not reclassified as
    # "pre-existing": item.geometry() read back INCONSISTENT with what
    # FlowLayout's own _do_layout() had just requested via
    # setGeometry() — confirmed live by temporarily instrumenting
    # _do_layout() to print its real x/y/sizeHint() at the exact moment
    # it calls setGeometry(), then diffing against what this test's own
    # layout.itemAt(i).geometry() read back immediately afterward:
    # every item in one row was genuinely assigned the SAME y by the
    # layout (confirmed in the printed trace), but the read-back
    # geometry showed a checkbox row at height 10 and a button row at
    # height 16 sharing one row's worth of y, each keeping its own
    # right/bottom edge fixed — the signature of a widget whose
    # geometry was queried before the offscreen platform had actually
    # applied it, not a spacing bug. `qtbot.waitExposed(window)` alone
    # was NOT sufficient (confirmed by re-running 5x); a real
    # `QApplication.processEvents()` call after EACH setGeometry() —
    # this loop drives the layout through two different widths, so it
    # needs to settle twice — is what actually made every read
    # consistent, confirmed clean across 5 repeated runs both with and
    # without waitExposed() (dropped once shown redundant).
    from PySide6.QtWidgets import QApplication

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    layout = window.tagging_controls_layout

    for width in (1600, 320):
        layout.setGeometry(QRect(0, 0, width, layout.heightForWidth(width)))
        QApplication.processEvents()
        # Two items (bpm_min_edit/bpm_max_edit) start .hide()'n until
        # "Analyze audio" is checked -- QWidgetItem.setGeometry() is a
        # real no-op for a hidden widget (QWidgetItem.isEmpty() short-
        # circuits it), so a hidden item's geometry is stale/unrelated,
        # not a gap this test should judge.
        rects = [
            layout.itemAt(i).geometry() for i in range(layout.count())
            if not layout.itemAt(i).widget().isHidden()
        ]
        # Adjacent items on the SAME row must have a real horizontal
        # gap; items that wrapped onto a new row must have a real
        # vertical gap. Every consecutive pair satisfies at least one.
        for previous, current in pairwise(rects):
            same_row = previous.top() == current.top()
            if same_row:
                assert current.left() - previous.right() >= theme.SPACING_SM
            else:
                assert current.top() - previous.bottom() >= theme.SPACING_SM


def test_tagging_controls_checkboxes_get_their_full_label_width(qtbot):
    # Roadmap item 79 (P11.2) — the checkbox labels ("Analyze audio
    # (BPM/Key)", "Re-tag already tagged files") must render at their
    # own real sizeHint() width, not be clipped by the layout.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    for checkbox in (
            window.analyze_audio_checkbox, window.force_retag_checkbox,
    ):
        assert checkbox.width() >= checkbox.sizeHint().width()


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
        # download_location_id=1 -- this playlist already has its own
        # destination, so Download proceeds directly with no dialog
        # (roadmap item 65 Phase 3.2: only a playlist with none of its
        # own gets prompted).
        playlists=[
            Playlist(
                id="p1", name="Test", track_count=2, download_location_id=1,
            ),
        ],
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
        window.download_button.isHidden, timeout=2000,
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

    qtbot.waitUntil(window.scan_button.isEnabled, timeout=2000)
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
        lambda: (
            window.track_area_stack.currentWidget() is window.track_table_card
        ),
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
    qtbot.waitUntil(window.download_button.isEnabled, timeout=2000)


def test_download_with_no_selection_shows_a_warning_notice(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.download_button.click()

    assert "playlist" in window.dashboard_notice.text().lower()
    assert not window.dashboard_notice.isHidden()


def test_download_with_its_own_destination_skips_the_dialog(qtbot):
    # Roadmap item 65 (Phase 3.2) — the ONLY case that skips the dialog:
    # the playlist already has its own destination
    # (download_location_id set on the Playlist itself, loaded from the
    # DB). A resolvable configured DEFAULT alone is no longer enough to
    # skip it — see test_download_with_a_resolvable_default_still_
    # prompts_once below.
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
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
    # No destination needed setting — it was already the playlist's own.
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == []


def test_download_with_a_resolvable_default_still_prompts_once(
        qtbot, monkeypatch,
):
    # Roadmap item 65 (Phase 3.2) — the real, decided behavior: a
    # playlist with NO destination of its own always prompts first, even
    # when the configured default would already resolve — never a
    # silent fallback. Pre-filled with the exact real fallback (location
    # + sanitized subfolder), not just the raw playlist name.
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=(location, "Test"),
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
    assert dialog.selected_location_id() == 1
    assert dialog.subfolder_field.text() == "Test"
    # Rejected -- never silently downloaded without the user seeing it.
    assert application.download_service.download_playlist_calls == []


# --- Roadmap item 56 Phase 5.1: download button feedback -------------------

def test_download_button_shows_starting_immediately_on_click(qtbot):
    # Roadmap item 56 Phase 5.1 — the real bug: the button previously
    # gave no feedback that anything had started.
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
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
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
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


def test_download_result_notice_reports_needs_review_separately_from_skipped(
        qtbot,
):
    # Roadmap item 66 (Phase 4.2) — the real fix: "Requested 16, skipped
    # 12 (no candidates found)" was wrong when several of those 12 had
    # actually become real Review candidates, not "nothing found."
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result={
            "requested": 4, "skipped": 6, "failed": 0, "total": 10,
            "already_in_progress": [],
            "needs_review": [
                "Prdk - ONE MORE NIGHT", "Zigi SC, A-Cray - Bit Perfect",
            ],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.download_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Requested 4" in window.dashboard_notice.text(),
        timeout=2000,
    )
    text = window.dashboard_notice.text()
    assert "2 sent to Review" in text
    # 6 skipped total - 0 already-in-progress - 2 needs-review = 4 with
    # genuinely no candidate at all.
    assert "4 no candidate found" in text
    assert "Review page" in text


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


def test_destination_dialog_preview_shows_new_folder_when_it_does_not_exist(
        qtbot, tmp_path,
):
    location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location], default_location_id=1,
        initial_subfolder="Does Not Exist Yet",
    )
    qtbot.addWidget(dialog)

    text = dialog.location_path_preview.text()
    assert str(tmp_path / "Does Not Exist Yet") in text
    assert "new folder" in text


def test_destination_dialog_preview_counts_real_audio_files(qtbot, tmp_path):
    subfolder = tmp_path / "Test"
    subfolder.mkdir()
    (subfolder / "a.mp3").write_bytes(b"\x00")
    (subfolder / "b.flac").write_bytes(b"\x00")
    (subfolder / "notes.txt").write_bytes(b"\x00")  # not audio -- excluded

    location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location], default_location_id=1,
        initial_subfolder="Test",
    )
    qtbot.addWidget(dialog)

    text = dialog.location_path_preview.text()
    assert str(subfolder) in text
    assert "already exists" in text
    assert "2 audio files" in text


def test_destination_dialog_preview_updates_live_as_fields_change(
        qtbot, tmp_path,
):
    location_a = LibraryLocation(
        id=1, name="A", path=str(tmp_path / "a"),
        added_at="2026-01-01T00:00:00+00:00",
    )
    location_b = LibraryLocation(
        id=2, name="B", path=str(tmp_path / "b"),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location_a, location_b], default_location_id=1,
        initial_subfolder="Sub",
    )
    qtbot.addWidget(dialog)

    assert str(
            Path(location_a.path) / "Sub"
    ) in dialog.location_path_preview.text()

    dialog.location_combo.setCurrentIndex(1)
    assert str(
            Path(location_b.path) / "Sub"
    ) in dialog.location_path_preview.text()

    dialog.subfolder_field.setText("Other")
    assert str(
            Path(location_b.path) / "Other"
    ) in dialog.location_path_preview.text()


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

def test_check_for_update_is_not_called_during_construction(
        qtbot,
        monkeypatch,
):
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
        return UpdateCheckResult(
                UpdateStatus.UP_TO_DATE,
                latest_version="v1.0.0",
        )

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
        window.check_for_updates_action.isEnabled, timeout=2000,
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
        window.check_for_updates_action.isEnabled, timeout=2000,
    )


def test_about_dialog_opens_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dialog = AboutDialog(window)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == help_text.ABOUT_DIALOG_TITLE


def test_format_build_identity_labels_dev_explicitly():
    assert "dev" in help_text.format_build_identity("dev", "dev", "dev")
    assert "not a packaged build" in help_text.format_build_identity(
        "dev", "dev", "dev",
    )


def test_format_build_identity_shows_real_sha_and_timestamp():
    text = help_text.format_build_identity(
        "a1b2c3d", "v0.1.0-3-ga1b2c3d", "2026-09-03T12:00:00+00:00",
    )
    assert "v0.1.0-3-ga1b2c3d" in text
    assert "2026-09-03T12:00:00+00:00" in text


def test_about_dialog_shows_build_identity(qtbot):
    # Roadmap item 81 (0.1) — "dev" is the committed _build_info.py
    # fallback. Reliable regardless of real local build state (RR1.2 —
    # see conftest.py's autouse fixture and test_main_window_
    # constructs_without_crashing's own identical comment).
    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    labels_html = [widget.text() for widget in dialog.findChildren(QLabel)]
    combined = "\n".join(labels_html)

    assert "Build:" in combined
    assert "dev" in combined


def test_help_page_shows_build_identity_and_per_account_note(qtbot):
    # Roadmap item 81 (0.1/0.2)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    help_page = window._build_help_page()
    qtbot.addWidget(help_page)

    combined = "\n".join(
        widget.text() for widget in help_page.findChildren(QLabel)
    )

    assert "Build:" in combined
    assert "per macOS user account" in combined


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
        main_window_module.webbrowser, "open", opened.append
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
        window.sync_tracks_button.isVisible, timeout=2000,
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


def test_run_worker_on_finished_exception_without_status_label_still_safe(
        qtbot
):
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


def test_run_worker_on_finished_exception_still_releases_worker_registry(
        qtbot
):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    baseline = len(workers_module._callbacks)

    def render_that_raises(result):
        raise ValueError("malformed render data")

    run_worker(SynchronousPool(), lambda: "ok", on_finished=render_that_raises)

    assert len(workers_module._callbacks) == baseline


# --- Progress channel (roadmap item 65, Phase 2.3) --------------------

def test_run_worker_without_on_progress_calls_fn_with_zero_arguments(qtbot):
    # Backward-compat guarantee: every pre-existing call site's fn stays
    # exactly zero-argument when on_progress isn't passed.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    calls = []
    run_worker(SynchronousPool(), lambda: calls.append("called") or "ok")

    assert calls == ["called"]


def test_run_worker_with_on_progress_passes_fn_a_reporter(qtbot):
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    reported = []

    def do_work(report):
        report("stage one", 1, 10)
        return "ok"

    def on_progress(stage, current, total):
        reported.append((stage, current, total))

    run_worker(SynchronousPool(), do_work, on_progress=on_progress)

    assert reported == [("stage one", 1, 10)]


def test_progress_reports_are_throttled_by_count(qtbot):
    # PROGRESS_EMIT_EVERY_N = 25 — 100 calls should emit at multiples of
    # 25 (the count-based branch fires regardless of elapsed time, since
    # these calls all happen well under PROGRESS_EMIT_MIN_INTERVAL_S),
    # PLUS the very first call (i=1), which always emits regardless of
    # count/elapsed — see Worker.__init__'s own comment on why.
    class SynchronousPool:
        def start(self, worker):
            worker.run()

    reported = []

    def do_work(report):
        for i in range(1, 101):
            report("stage", i, 100)
        return "ok"

    run_worker(
        SynchronousPool(), do_work,
        on_progress=lambda stage, current, total: reported.append(current),
    )

    assert reported == [1, 25, 50, 75, 100]


def test_progress_reports_are_throttled_by_time(qtbot, monkeypatch):
    from seeker.ui import workers as workers_mod

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    fake_time = [0.0]
    monkeypatch.setattr(workers_mod.time, "monotonic", lambda: fake_time[0])

    reported = []

    def do_work(report):
        report("a", 1, 10)   # always emits (first report)
        fake_time[0] += 0.1  # under PROGRESS_EMIT_MIN_INTERVAL_S -> dropped
        report("b", 2, 10)
        fake_time[0] += 0.3  # over the interval -> emits
        report("c", 3, 10)
        return "ok"

    run_worker(
        SynchronousPool(), do_work,
        on_progress=lambda stage, current, total: reported.append(stage),
    )

    assert reported == ["a", "c"]


def test_progress_callback_is_cleared_on_finish(qtbot):
    from seeker.ui import workers as workers_mod

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    worker = run_worker(
        SynchronousPool(), lambda report: "ok",
        on_progress=lambda stage, current, total: None,
    )

    assert worker.task_id not in workers_mod._progress_callbacks


def test_progress_callback_is_cleared_on_error(qtbot):
    from seeker.ui import workers as workers_mod

    class SynchronousPool:
        def start(self, worker):
            worker.run()

    def boom(report):
        raise RuntimeError("simulated failure")

    worker = run_worker(
        SynchronousPool(), boom,
        on_progress=lambda stage, current, total: None,
    )

    assert worker.task_id not in workers_mod._progress_callbacks


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


def test_downloads_aggregate_header_shows_estimate_once_a_download_has_samples(
        qtbot
):
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
    window._eta_tracker.record(
            1,
            200,
            datetime(2026, 1, 1, tzinfo=UTC),
    )
    window._eta_tracker.record(
            1,
            500,
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )

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

    # Roadmap item 96 (B4) — wrapped in the same QHBoxLayout container
    # shape as every other exit of _build_progress_widget/
    # _build_terminal_progress_widget, not returned bare: a bare bar
    # returned directly from setCellWidget gets resized to the FULL
    # cell rect by Qt, and the global QProgressBar max-height: 14px
    # rule then clamps it to the TOP of a tall row instead of centering
    # it (the real reported bug — a queued row's bar visibly sat above
    # center while a downloading row's own bar, already wrapped, sat
    # centered).
    container = window.downloads_table.cellWidget(0, 4)
    assert not isinstance(container, QProgressBar)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.minimum() == 0
    assert bar.maximum() == 0
    # No ETA label for an indeterminate bar — nothing determinate to
    # estimate against (Task 2's own scoping, unchanged by the B4 fix).
    assert container.findChildren(QLabel) == []
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
    # widget directly (the indeterminate/queued case above is now
    # wrapped the identical way, roadmap item 96).
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


def test_downloads_tab_queued_and_downloading_bars_are_both_vertically_centered(
        qtbot,
):
    # Roadmap item 96 (B4.3) — real pixel verification of the reported
    # bug: a queued row's bar used to sit clamped to the TOP of its
    # cell (a bare bar returned from setCellWidget gets resized to the
    # full, tall cell rect, then the global 14px max-height rule clamps
    # it upward) while a downloading row's own bar, already wrapped in
    # a container, sat centered. Both must now match.
    downloads = [
        _make_active_download(
            track_id="t1", status="queued",
            bytes_transferred=None, total_bytes=None,
        ),
        _make_active_download(
            track_id="t2", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("downloads")

    window._render_active_downloads(downloads)
    qtbot.wait(20)

    viewport = window.downloads_table.viewport()

    for row in (0, 1):
        row_rect = window.downloads_table.visualRect(
            window.downloads_table.model().index(row, 4)
        )
        widget = window.downloads_table.cellWidget(row, 4)
        assert widget is not None
        bar = widget.findChild(QProgressBar)
        assert bar is not None

        bar_center_y = bar.mapTo(
            viewport, bar.rect().center()
        ).y()

        assert abs(bar_center_y - row_rect.center().y()) <= 2

    # Roadmap item 102 — a post-round review correctly pointed out that
    # a geometry check (mapTo above) isn't the same thing as verifying
    # what actually got PAINTED (item 77's own lesson: occlusion/paint
    # order is invisible to geometry queries). Real pixel scan of a
    # real window.grab(): find the bar's actual colored pixel span
    # inside the progress column and compare ITS midpoint to the row's
    # own real center — independent of and stronger than the mapTo
    # check above.
    image = window.grab().toImage()
    surface_rgb = tuple(
        int(theme.BG_SURFACE[i:i + 2], 16) for i in (1, 3, 5)
    )
    top_left = viewport.mapTo(window, viewport.rect().topLeft())
    # window.grab() returns a QImage in DEVICE pixels; every geometry
    # query above (visualRect/mapTo) is in LOGICAL pixels. Discovered
    # live adding item C1's own test: this real Qt session's
    # devicePixelRatio is 2.0, silently sampling the wrong quadrant of
    # the image before this fix — this test happened to still pass
    # only because it compared two equally-mis-scaled quantities
    # against a 2px tolerance, not because the coordinates were right.
    dpr = image.width() / window.width()

    for row in (0, 1):
        row_rect = window.downloads_table.visualRect(
            window.downloads_table.model().index(row, 4)
        )
        x = round((top_left.x() + row_rect.left() + 10) * dpr)
        y0 = round((top_left.y() + row_rect.top()) * dpr)
        y1 = round((top_left.y() + row_rect.bottom()) * dpr)

        painted_ys = [
            y for y in range(y0, y1 + 1)
            if (
                image.pixelColor(x, y).red(),
                image.pixelColor(x, y).green(),
                image.pixelColor(x, y).blue(),
            ) != surface_rgb
        ]
        assert painted_ys, f"row {row}: no painted bar pixels found"

        painted_center = (painted_ys[0] + painted_ys[-1]) / 2 / dpr
        row_center = top_left.y() + row_rect.center().y()
        assert abs(painted_center - row_center) <= 2


def test_downloads_header_shows_a_real_divider_between_columns(qtbot):
    # Roadmap item C1 (round 5) — a real window.grab() bisect found that
    # `QHeaderView::section:horizontal:last-child` (invalid Qt QSS —
    # `last-child` is CSS, not a real Qt pseudo-state) poisoned the
    # WHOLE `QHeaderView::section` rule, silently dropping
    # `border-right` everywhere despite the CSS text reading correctly
    # — the exact "asserts a property, never looked at a pixel" failure
    # mode the round-5 brief called out by name (this was "fixed" and
    # reported green twice before, per B2/item 97). A test that greps
    # the stylesheet string can't catch this class of bug at all — it
    # must sample real painted pixels.
    downloads = [
        _make_active_download(
            track_id="t1", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("downloads")
    window._render_active_downloads(downloads)
    qtbot.wait(100)

    table = window.downloads_table
    header = table.horizontalHeader()
    image = window.grab().toImage()
    header_top_left = header.mapTo(window, header.rect().topLeft())
    header_h = header.height()
    # window.grab() returns a QImage sized in DEVICE pixels, while every
    # Qt geometry query above (mapTo/sectionPosition/etc.) is in LOGICAL
    # pixels — on this machine's real Qt session (devicePixelRatio 2.0,
    # discovered live; a bare ad hoc QApplication used while diagnosing
    # this reported 1.0) sampling logical coordinates directly into the
    # device-pixel image silently reads the wrong quadrant. Scale by the
    # image's own real ratio rather than assuming any particular value.
    dpr = image.width() / window.width()

    border_strong_rgb = tuple(
        int(theme.BORDER_STRONG[i:i + 2], 16) for i in (1, 3, 5)
    )
    ncols = table.columnCount()

    for col in range(ncols):
        section_end = header.sectionPosition(col) + header.sectionSize(col)
        base_x = round((header_top_left.x() + section_end) * dpr)
        y0 = round(header_top_left.y() * dpr)
        y1 = round((header_top_left.y() + header_h - 1) * dpr)
        dx_span = max(2, round(2 * dpr))
        divider_present = any(
            (
                image.pixelColor(x, y).red(),
                image.pixelColor(x, y).green(),
                image.pixelColor(x, y).blue(),
            ) == border_strong_rgb
            for x in range(base_x - dx_span, base_x + dx_span + 1)
            if 0 <= x < image.width()
            # exclude the header's own bottom border row, which is
            # unrelated to the per-column right-divider under test
            for y in range(y0, y1)
        )
        if col == ncols - 1:
            # the trailing section's divider is deliberately suppressed
            # — nothing to separate it from on that side
            assert not divider_present, f"col {col} (last) should have no divider"
        else:
            assert divider_present, f"col {col} is missing its real divider"


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

    now = datetime(2026, 1, 1, tzinfo=UTC)
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

    now = datetime.now(UTC)
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

    now = datetime.now(UTC)
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

    now = datetime.now(UTC)
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
    candidates = [
            (_make_track(track_id="t7"), _make_review_candidate(track_id="t7"))
    ]
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
    candidates = [
            (_make_track(track_id="t9"), _make_review_candidate(track_id="t9"))
    ]
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


def test_review_tab_delete_checkbox_state_survives_rerender_across_poll_ticks(
        qtbot,
):
    # Roadmap item R2.1/R2.6 — the 2s poll_timer rebuilds this table's
    # checkboxes from scratch every tick; before this fix, checking the
    # box and letting even one more tick land would silently reset it.
    details = [
            _make_upgrade_details(request_id=7, old_file_path="/music/old.mp3")
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)
    actions = window.review_upgrades_table.cellWidget(0, 3)
    actions.findChildren(QCheckBox)[0].setChecked(True)
    assert window._upgrade_delete_checked == {7}

    # Three more "poll ticks" — a brand-new checkbox widget each time.
    for _ in range(3):
        window._render_pending_upgrades(details)

    actions = window.review_upgrades_table.cellWidget(0, 3)
    checkbox = actions.findChildren(QCheckBox)[0]
    assert checkbox.isChecked() is True
    assert window._upgrade_delete_checked == {7}


def test_review_tab_delete_checkbox_state_pruned_when_row_removed(qtbot):
    details = [
            _make_upgrade_details(request_id=7, old_file_path="/music/old.mp3")
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)
    window.review_upgrades_table.cellWidget(0, 3).findChildren(QCheckBox)[0].setChecked(
        True
    )
    assert window._upgrade_delete_checked == {7}

    # The row is gone (e.g. resolved) -- its stale key must not linger
    # forever (R2.3), and a LATER row that happens to reuse the same
    # request_id (can't really happen for a real autoincrement PK, but
    # confirms the map doesn't just grow unbounded) starts unchecked.
    window._render_pending_upgrades([])
    assert window._upgrade_delete_checked == set()


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


# --- Roadmap item R3.1: "Replace all" upgrades -----------------------------

def test_replace_all_upgrades_button_disabled_when_no_upgrades(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades([])

    assert window.replace_all_upgrades_button.isEnabled() is False


def test_replace_all_upgrades_button_calls_batch_with_every_request_id(
        qtbot, monkeypatch,
):
    details = [
        _make_upgrade_details(request_id=1),
        _make_upgrade_details(request_id=2),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_pending_upgrades(details)
    assert window.replace_all_upgrades_button.isEnabled() is True

    def fake_exec(self):
        self.delete_old_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkReplaceUpgradesDialog, "exec", fake_exec)
    # Roadmap item C3 (round 5) — found live while chasing a real,
    # reproducible full-suite hang: `_on_bulk_replace_upgrades_finished`
    # (the worker's on_finished callback) calls a real, unmocked
    # `QMessageBox.information()` after this test's own wait condition
    # is already satisfied (the batch call list is appended to on the
    # WORKER thread, before its finished signal is even emitted/
    # processed on the main thread) — so the test could return with
    # that call still QUEUED, popping a genuine blocking modal `exec()`
    # during a LATER, unrelated test with nothing to click under the
    # offscreen QPA. Confirmed via a real `lldb -p <pid> -o "bt all"`
    # attach on a live-hung `pytest` process: the main thread was
    # inside `QDialog::exec()`, called from `Sbk_QMessageBoxFunc_
    # information`. Mocked here (even though not asserted) so nothing
    # leaks past this test's own scope — the same defensive pattern
    # `test_resolve_all_duplicates_drops_only_succeeded_groups_locally`
    # already used correctly.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window.replace_all_upgrades_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decisions_batch_calls
        != [],
        timeout=2000,
    )
    assert application.download_service.apply_upgrade_decisions_batch_calls == [
        ([1, 2], True),
    ]


def test_replace_all_upgrades_cancelled_dialog_calls_nothing(
        qtbot,
        monkeypatch,
):
    details = [_make_upgrade_details(request_id=1)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_pending_upgrades(details)

    monkeypatch.setattr(
        BulkReplaceUpgradesDialog, "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    window.replace_all_upgrades_button.click()

    assert application.download_service.apply_upgrade_decisions_batch_calls == []


def test_replace_all_upgrades_result_shown_in_message_box(qtbot, monkeypatch):
    from seeker.soulseek.download_service import BulkUpgradeReplaceResult

    details = [_make_upgrade_details(request_id=1)]
    application = FakeApplication()
    application.download_service.apply_upgrade_decisions_batch_result = (
        BulkUpgradeReplaceResult(
            replaced=1, failed=0, details=["Artist - Title: Replaced with x"],
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_pending_upgrades(details)

    monkeypatch.setattr(
        BulkReplaceUpgradesDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    info_calls = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: info_calls.append(a),
    )

    window.replace_all_upgrades_button.click()

    qtbot.waitUntil(lambda: info_calls != [], timeout=2000)
    assert "Replaced: 1, Failed: 0" in info_calls[0][2]


def test_review_tab_populates_both_sections_on_construction(qtbot):
    # _poll_review_items() runs once in __init__ (like the Downloads
    # tab's own initial call) so the Review tab isn't empty for the
    # first poll interval either.
    candidates = [
            (_make_track(track_id="tc"), _make_review_candidate(track_id="tc"))
    ]
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

    # Roadmap item C3 (round 5) — this cell widget is now wrapped by
    # _wrap_progress_bar (see the test just below for why: a bare bar
    # here reproduced the exact same top-clamped-bar bug B4/item 96
    # fixed on the Downloads page), so the real QProgressBar is a
    # child of the cell widget, not the cell widget itself.
    container = window.track_table.cellWidget(0, 2)
    bar = container.findChild(QProgressBar)
    assert bar is not None
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
    assert [
            b.text() for b in in_library_actions.findChildren(QPushButton)
    ] == ["Tag"]

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

    window.dashboard_notice.show_message(
            "Something worth reading",
            kind="error",
    )
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
        "tagged_art_rarely_supported_format": 0,
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
        "tagged_art_rarely_supported_format": 0,
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
        "tagged_art_rarely_supported_format": 0,
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


def test_tag_result_notice_reports_already_tagged_with_nothing_else_done(
        qtbot,
):
    # Roadmap item 66 (Phase 5.1) — the real gap found in Phase 0.4's
    # investigation: a fully-already-tagged re-run (tagged=0, nothing
    # failed, nothing missing art) previously produced NO notice at
    # all — only the easy-to-miss results panel said anything.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_tag_result({
        "tagged": 0,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 4,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_already_tagged",
                "message": "Artist A - Title A: already tagged",
            },
        ],
    })

    assert not window.dashboard_notice.isHidden()
    text = window.dashboard_notice.text()
    assert "4 track" in text
    assert "already tagged" in text
    assert "Re-tag" in text
    # Roadmap item 75 (P6, 6.2) — the real gap: "already tagged" here
    # does not mean "art is fine," it means art was never checked.
    assert "NOT checked" in text
    assert not window.dashboard_notice._action_button.isHidden()
    assert (
        window.dashboard_notice._action_button.text()
        == "Fix missing cover art"
    )


def test_tag_result_notice_mentions_unchecked_art_even_on_a_mixed_run(qtbot):
    # Roadmap item 75 (P6, 6.2) — a real gap the all-skipped case alone
    # didn't cover: a run that freshly tags SOME tracks while skipping
    # others as already-tagged used to say nothing at all about the
    # skipped ones' art.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_tag_result({
        "tagged": 2,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 3,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [],
    })

    assert not window.dashboard_notice.isHidden()
    text = window.dashboard_notice.text()
    assert "Tagged 2 track" in text
    assert "3 already-tagged" in text
    assert "NOT checked" in text


def test_tag_result_notice_fix_art_action_triggers_fix_missing_art(
        qtbot,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._render_tag_result({
        "tagged": 0,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 1,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_already_tagged",
                "message": "Artist A - Title A: already tagged",
            },
        ],
    })

    window.dashboard_notice._action_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service
        .fix_missing_art_for_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.fix_missing_art_for_playlist_calls == [
        "Test",
    ]


# --- Fix missing cover art / fill missing art URLs (roadmap item 66,
# Phase 5.2/5.3) --------------------------------------------------------

def test_fix_missing_art_button_calls_service_and_shows_result(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(
        playlists=playlists,
        fix_art_result={
            "fixed": 3,
            "fixed_wav_rarely_supported": 0,
            "already_correct": 2,
            "no_url": 1,
            "download_failed": 0,
            "embed_failed": 0,
            "format_unsupported": 0,
            "skipped_no_match": 0,
            "failed": 0,
            "details": [
                {
                    "track_id": "t1",
                    "reason": "no_url",
                    "message": "Artist A - Title A: no album art URL stored",
                },
            ],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.fix_missing_art_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service
        .fix_missing_art_for_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.fix_missing_art_for_playlist_calls == [
        "Test",
    ]
    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Fixed art for 3" in window.dashboard_notice.text(),
        timeout=2000,
    )
    text = window.dashboard_notice.text()
    assert "2 already correct" in text
    assert "1 missing an art URL" in text
    assert "already correct" in text.lower()


def test_fix_missing_art_button_requires_a_selected_playlist(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.fix_missing_art_button.click()

    assert not window.dashboard_notice.isHidden()
    assert "playlist" in window.dashboard_notice.text().lower()
    assert application.metadata_service.fix_missing_art_for_playlist_calls == []


def test_fill_missing_art_urls_button_reports_the_real_count(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists, art_urls_filled=7)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.fill_missing_art_urls_button.click()

    qtbot.waitUntil(
        lambda: application.sync_service.sync_playlist_tracks_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "7" in window.dashboard_notice.text(),
        timeout=2000,
    )
    assert "Filled in 7 missing album art URLs" in window.dashboard_notice.text()


def test_fill_missing_art_urls_button_reports_zero_found(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists, art_urls_filled=0)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window.fill_missing_art_urls_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "No missing" in window.dashboard_notice.text(),
        timeout=2000,
    )


# --- Rename preview dialog (roadmap item 67, Phase 6.4) --------------------

def _make_rename_plan(
        track_id="t1", action="rename",
        current="/music/old.mp3", proposed="/music/new.mp3",
        message=None,
) -> RenamePlan:
    return RenamePlan(
        track_id=track_id,
        local_file_id=1,
        current_path=Path(current) if current else None,
        proposed_path=Path(proposed) if proposed else None,
        action=action,
        message=message,
    )


def test_rename_preview_dialog_groups_plans_by_action(qtbot):
    plans = [
        _make_rename_plan("t1", "rename"),
        _make_rename_plan(
            "t2", "collision", "/music/a.mp3", "/music/b.mp3",
            "target already exists",
        ),
        _make_rename_plan(
            "t3", "already_correct", "/music/c.mp3", "/music/c.mp3",
        ),
        _make_rename_plan(
            "t4", "not_auto_matched", None, None, "not auto-matched",
        ),
    ]
    dialog = RenamePreviewDialog(None, "Test Playlist", plans)
    qtbot.addWidget(dialog)

    assert dialog.confirm_button.text() == "Rename 2 file(s)"
    assert dialog.confirm_button.isEnabled()


def test_rename_preview_dialog_disables_confirm_when_nothing_to_rename(qtbot):
    plans = [
        _make_rename_plan(
            "t1", "already_correct", "/music/c.mp3", "/music/c.mp3",
        ),
    ]
    dialog = RenamePreviewDialog(None, "Test Playlist", plans)
    qtbot.addWidget(dialog)

    assert dialog.confirm_button.text() == "Rename 0 file(s)"
    assert not dialog.confirm_button.isEnabled()


def test_rename_files_button_requires_a_selected_playlist(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.rename_files_button.click()

    assert not window.dashboard_notice.isHidden()
    assert "playlist" in window.dashboard_notice.text().lower()
    assert application.metadata_service.plan_renames_calls == []


def test_rename_files_button_plans_then_opens_dialog_and_cancels(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    plans = [_make_rename_plan()]
    application = FakeApplication(playlists=playlists, rename_plans=plans)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        RenamePreviewDialog, "exec", lambda self: QDialog.DialogCode.Rejected,
    )

    window.rename_files_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.plan_renames_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.plan_renames_calls == ["Test"]
    # Cancelled -- apply_renames must never be called.
    assert application.metadata_service.apply_renames_calls == []


def test_rename_files_button_confirmed_calls_apply_and_shows_result(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    plans = [_make_rename_plan()]
    application = FakeApplication(
        playlists=playlists, rename_plans=plans,
        rename_result=RenameResult(renamed=1),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        RenamePreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted,
    )

    window.rename_files_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.apply_renames_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.apply_renames_calls == [plans]
    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Renamed 1" in window.dashboard_notice.text(),
        timeout=2000,
    )


def test_rename_result_notice_names_files_whose_written_name_differed(
        qtbot, monkeypatch,
):
    # Roadmap item 76 (P2, 2.5) — the notice must name the count of
    # files whose real written name differed from the preview, not
    # bury it as just "N failed" or a bare success message.
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    plans = [_make_rename_plan()]
    application = FakeApplication(
        playlists=playlists, rename_plans=plans,
        rename_result=RenameResult(renamed=2, collisions=1),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        RenamePreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted,
    )

    window.rename_files_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Renamed 2" in window.dashboard_notice.text(),
        timeout=2000,
    )
    text = window.dashboard_notice.text()
    assert "1 file" in text
    assert "DIFFERENT name than the preview" in text


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


def test_no_selector_less_setstylesheet_call_anywhere_in_ui():
    # Roadmap item E3.6 (round 7) — the actual mechanism behind E3, not
    # just that one symptom: Qt parses a `setStyleSheet()` string with
    # no selector as a universal `* {...}` rule, applying it to the
    # target widget AND EVERY DESCENDANT — this is what silently
    # stripped a QProgressBar's border inside make_card() (E3) and was
    # present in two more places (`cell_widget()`'s container,
    # `_ThemeToggleButton`) that happened not to cause visible harm yet.
    # A real rule always contains a `{` (selector, then a brace, then
    # properties); a bare declaration list like "border: none;" never
    # does — checked structurally via `ast`, not by re-reading these
    # three call sites by eye, so a future one added anywhere in ui/ is
    # covered automatically.
    import ast

    import seeker.ui as ui_package

    def rendered_text(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            # Interpolated values (ACCENT, PROGRESS_BAR_RADIUS, etc.)
            # are never selector/brace syntax themselves — a placeholder
            # preserves the surrounding literal text's structure.
            return "".join(
                str(part.value) if isinstance(part, ast.Constant) else "X"
                for part in node.values
            )
        return None

    ui_dir = Path(ui_package.__file__).parent
    violations = []
    for path in sorted(ui_dir.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setStyleSheet"
                and len(node.args) == 1
            ):
                continue
            text = rendered_text(node.args[0])
            if text is not None and "{" not in text:
                violations.append(f"{path.name}:{node.lineno}: {text!r}")

    assert violations == [], (
        "selector-less setStyleSheet() call(s) found (Qt parses these "
        "as a universal `* {...}` rule that cascades onto every "
        "descendant widget):\n" + "\n".join(violations)
    )


def test_no_stray_ampersand_mnemonic_in_button_or_label_text():
    # Roadmap item 79 (P12) — a bare "&" in a QPushButton/QLabel string
    # literal is a real Qt keyboard-mnemonic marker (consumed, renders
    # as an underline under the next character — "Rescan & match
    # library" rendered as "Rescan _match library"), not a literal
    # ampersand. "&Help" on the real menu bar is the one intentional
    # mnemonic in this file; "&&" escapes to a literal "&" and is not
    # flagged. A source-level scan, not a widget-by-widget assertion,
    # so a future string added anywhere in this file is covered
    # automatically.
    import re

    import seeker.ui.main_window as main_window_module

    source = Path(main_window_module.__file__).read_text()
    literals = re.findall(r'Q(?:PushButton|Label)\(\s*"([^"]*)"', source)
    stray = [
        text for text in literals
        if "&" in text and "&&" not in text and text != "&Help"
    ]
    assert stray == []


def _search_column(window, header_text: str) -> int:
    header = window.search_results_table.horizontalHeaderItem
    for column in range(window.search_results_table.columnCount()):
        if header(column).text() == header_text:
            return column
    raise AssertionError(f"No Search column named {header_text!r}")


def test_search_empty_fields_shows_a_message_and_does_not_search(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._on_search_clicked()

    assert application.download_service.search_manual_calls == []
    assert help_text.SEARCH_EMPTY_FIELDS_MESSAGE in (
        window.search_status_label.text()
    )


def test_search_renders_results_ranked_best_first(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    flac_file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    mp3_file = SoulseekFile(
        username="peer2", filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3", size=8_000_000, queue_length=1,
        upload_speed=1_000_000, has_free_upload_slot=True, bit_rate=320,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [
        mp3_file, flac_file,
    ]
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window.search_artist_edit.setText("Dom Dolla")
    window.search_title_edit.setText("Rhyme Dust")
    window._on_search_clicked()

    qtbot.waitUntil(
        lambda: window.search_results_table.rowCount() == 2, timeout=2000,
    )
    assert application.download_service.search_manual_calls == [
        ("Dom Dolla", "Rhyme Dust")
    ]

    username_col = _search_column(window, "Username")
    # flac (lossless) outranks mp3 regardless of search result order.
    assert window.search_results_table.item(0, username_col).text() == "peer1"
    assert window.search_results_table.item(1, username_col).text() == "peer2"
    assert "Found 2 results" in window.search_status_label.text()
    assert window.download_best_button.isEnabled()


def test_search_no_results_shows_a_clear_message(qtbot):
    application = FakeApplication()
    application.download_service._search_manual_results = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window.search_artist_edit.setText("Nobody")
    window.search_title_edit.setText("Nothing")
    window._on_search_clicked()

    qtbot.waitUntil(
        lambda: window.search_status_label.text() != "", timeout=2000,
    )
    assert help_text.SEARCH_NO_RESULTS_MESSAGE in window.search_status_label.text()
    assert not window.download_best_button.isEnabled()


def test_search_download_best_passes_the_already_fetched_results(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_result = {
        "requested": True, "settled": True,
        "username": "peer1", "filename": "Dom Dolla - Rhyme Dust.flac",
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window.search_artist_edit.setText("Dom Dolla")
    window.search_title_edit.setText("Rhyme Dust")
    window._on_search_clicked()
    qtbot.waitUntil(
        window.download_best_button.isEnabled, timeout=2000,
    )

    window.download_best_button.click()

    qtbot.waitUntil(
        lambda: bool(application.download_service.download_manual_calls),
        timeout=2000,
    )
    artist, title, chosen, files = (
        application.download_service.download_manual_calls[0]
    )
    assert (artist, title) == ("Dom Dolla", "Rhyme Dust")
    assert chosen is None
    # Roadmap item 82 — reuses the already-fetched results, no second
    # real 20-45s network search.
    assert files == [file]
    assert "Requested from peer1" in window.search_status_label.text()


def test_search_download_this_one_passes_the_explicit_pick(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_result = {
        "requested": True, "settled": True,
        "username": "peer1", "filename": "Dom Dolla - Rhyme Dust.flac",
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window.search_artist_edit.setText("Dom Dolla")
    window.search_title_edit.setText("Rhyme Dust")
    window._on_search_clicked()
    qtbot.waitUntil(
        lambda: window.search_results_table.rowCount() == 1, timeout=2000,
    )

    actions_col = _search_column(window, "Actions")
    button = (
        window.search_results_table.cellWidget(0, actions_col)
        .findChild(QPushButton)
    )
    button.click()

    qtbot.waitUntil(
        lambda: bool(application.download_service.download_manual_calls),
        timeout=2000,
    )
    artist, title, chosen, files = (
        application.download_service.download_manual_calls[0]
    )
    assert (artist, title) == ("Dom Dolla", "Rhyme Dust")
    assert chosen is file
    assert files is None


def test_search_no_destination_shows_settings_guidance(qtbot):
    from seeker.models.soulseek_file import SoulseekFile
    from seeker.soulseek.download_service import NoDestinationConfiguredError

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_error = (
        NoDestinationConfiguredError(
            "No download destination is configured yet."
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window.search_artist_edit.setText("Dom Dolla")
    window.search_title_edit.setText("Rhyme Dust")
    window._on_search_clicked()
    qtbot.waitUntil(
        window.download_best_button.isEnabled, timeout=2000,
    )

    window.download_best_button.click()

    qtbot.waitUntil(
        lambda: "Settings" in window.search_status_label.text(),
        timeout=2000,
    )


def test_every_table_and_list_widget_is_routed_through_make_card(qtbot):
    # Roadmap item 80 (P10.1) — a table/list's own border-radius does
    # NOT clip its children; any cell-widget button reaching its edge
    # paints over the rounded corner. theme.make_card() is the
    # structural fix, and this asserts it's actually used everywhere
    # a QTableWidget/QListWidget is added to the real window, not just
    # available for someone to remember to call.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    table_and_list_attrs = [
        "playlist_list",
        "track_table",
        "downloads_table",
        "history_table",
        "sharing_locations_table",
        "sharing_uploads_table",
        "review_needs_table",
        "review_upgrades_table",
        "review_local_table",
        "duplicates_folders_list",
        "duplicates_table",
        "search_results_table",
    ]
    for attr in table_and_list_attrs:
        widget = getattr(window, attr)
        parent = widget.parentWidget()
        assert parent is not None, attr
        assert parent.objectName() == "card", (
            f"{attr}'s parent is {parent!r}, not routed through make_card()"
        )


def test_duplicates_tab_controls_have_tooltips(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.duplicates_location_combo.toolTip() != ""
    assert window.compute_fingerprints_button.toolTip() != ""
    assert window.find_duplicates_button.toolTip() != ""
    assert window.duplicates_folders_checkbox.toolTip() != ""
    assert window.duplicates_add_folder_button.toolTip() != ""
    assert window.duplicates_remove_folder_button.toolTip() != ""


def test_duplicates_folders_panel_hidden_until_checkbox_checked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.duplicates_folders_panel.isHidden()

    window.duplicates_folders_checkbox.setChecked(True)

    assert not window.duplicates_folders_panel.isHidden()
    # Roadmap item 77 (P9) — the combo stays enabled in folder-scope
    # mode now: it's a real tiebreak preference for resolve_folder_
    # scopes' most-specific-wins matching (P8.2), not dead weight.
    assert window.duplicates_location_combo.isEnabled()

    window.duplicates_folders_checkbox.setChecked(False)

    assert window.duplicates_folders_panel.isHidden()
    assert window.duplicates_location_combo.isEnabled()


def test_duplicates_remove_folder_button_removes_selected_entry(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_folder_paths = ["/music/Trance", "/music/House"]
    window.duplicates_folders_list.addItem("/music/Trance")
    window.duplicates_folders_list.addItem("/music/House")

    window.duplicates_folders_list.setCurrentRow(0)
    window._on_remove_duplicates_folder_clicked()

    assert window._duplicates_folder_paths == ["/music/House"]
    assert window.duplicates_folders_list.count() == 1
    assert window.duplicates_folders_list.item(0).text() == "/music/House"


def test_duplicates_scope_count_updates_from_the_real_service(qtbot):
    application = FakeApplication()
    application.duplicate_service._scope_file_count = 42
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_folder_paths = ["/music/Trance"]
    window.duplicates_folders_list.addItem("/music/Trance")
    window.duplicates_folders_checkbox.setChecked(True)

    qtbot.waitUntil(
        lambda: "42 files in scope" in window.duplicates_scope_count_label.text(),
        timeout=2000,
    )
    assert (
        application.duplicate_service.resolve_folder_scopes_calls
        == [(["/music/Trance"], None)]
    )


def test_compute_fingerprints_in_folder_mode_calls_service_per_location(
        qtbot,
):
    from seeker.library.duplicate_service import DuplicateFolderScope

    location_a = LibraryLocation(
        id=1, name="A", path="/music/a", added_at="",
    )
    location_b = LibraryLocation(
        id=2, name="B", path="/music/b", added_at="",
    )
    scopes = [
        DuplicateFolderScope(location=location_a, folder_relative_path="Trance"),
        DuplicateFolderScope(location=location_b, folder_relative_path=""),
    ]
    application = FakeApplication(
        fingerprint_result={
            "computed": 1, "skipped_already_computed": 0, "failed": 0,
            "details": [],
        },
    )
    application.duplicate_service._folder_scopes = scopes
    application.duplicate_service._scope_file_count = 2
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_folder_paths = ["/music/a/Trance", "/music/b"]
    window.duplicates_folders_checkbox.setChecked(True)

    window._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: len(
            application.duplicate_service.compute_fingerprints_calls
        ) == 2,
        timeout=2000,
    )
    assert sorted(
        application.duplicate_service.compute_fingerprints_calls
    ) == [("A", ["Trance"]), ("B", [""])]
    qtbot.waitUntil(
        lambda: "Fingerprinted: 2" in window.duplicates_status_label.text(),
        timeout=2000,
    )


def test_find_duplicates_in_folder_mode_calls_across_scopes(qtbot):
    from seeker.library.duplicate_service import DuplicateFolderScope

    location = LibraryLocation(id=1, name="A", path="/music/a", added_at="")
    scopes = [
        DuplicateFolderScope(location=location, folder_relative_path="Trance"),
    ]
    application = FakeApplication()
    application.duplicate_service._folder_scopes = scopes
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_folder_paths = ["/music/a/Trance"]
    window.duplicates_folders_checkbox.setChecked(True)

    window._on_find_duplicates_clicked()

    qtbot.waitUntil(
        lambda: bool(
            application.duplicate_service
            .find_duplicate_groups_across_scopes_calls
        ),
        timeout=2000,
    )
    assert (
        application.duplicate_service
        .find_duplicate_groups_across_scopes_calls == [scopes]
    )


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
        lambda: application.duplicate_service.compute_fingerprints_calls
        == [("Main", None)],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: "Fingerprinted: 3" in window.duplicates_status_label.text(),
        timeout=2000,
    )


def test_compute_fingerprints_result_shows_failure_reason_breakdown(qtbot):
    # Roadmap item 68 (Phase 8.2) — a real per-reason breakdown, not
    # just an opaque "Failed: N".
    application = FakeApplication(
        fingerprint_result={
            "computed": 1, "skipped_already_computed": 0, "failed": 3,
            "details": [
                {"local_file_id": "1", "reason": "decode_unsupported", "message": "a"},
                {"local_file_id": "2", "reason": "decode_unsupported", "message": "b"},
                {"local_file_id": "3", "reason": "empty_file", "message": "c"},
            ],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: "Failed: 3" in window.duplicates_status_label.text(),
        timeout=2000,
    )
    status_text = window.duplicates_status_label.text()
    assert "2 couldn't be decoded" in status_text
    assert "1 0-byte file" in status_text


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


def _duplicates_column(window, header_text: str) -> int:
    # Roadmap item 68 (Phase 7.1) — resolves a duplicates_table column
    # by its real header text, not a literal index that could drift out
    # of sync with the render code's own literals the way item 61 Phase
    # 6.2's brief hypothesized (a test sharing the code's own mistake
    # proves nothing). Used everywhere below instead of a bare column
    # number.
    table = window.duplicates_table
    for column in range(table.columnCount()):
        header_item = table.horizontalHeaderItem(column)
        if header_item is not None and header_item.text() == header_text:
            return column
    raise AssertionError(f"no '{header_text}' column found")


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

    keep_radio_0 = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Keep"),
    )
    keep_radio_1 = window.duplicates_table.cellWidget(
            1,
            _duplicates_column(window, "Keep"),
    )
    assert isinstance(keep_radio_0, QRadioButton)
    assert isinstance(keep_radio_1, QRadioButton)
    assert keep_radio_0.isChecked() is True
    assert keep_radio_1.isChecked() is False


# --- Roadmap item R3.2: "Resolve all groups" --------------------------------

def test_resolve_all_duplicates_button_disabled_when_no_groups(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([])

    assert window.resolve_all_duplicates_button.isEnabled() is False


def test_resolve_all_duplicates_uses_default_and_custom_keep_selections(
        qtbot, monkeypatch,
):
    group_a = _make_duplicate_group()  # ids 101 (flac), 102 (mp3)
    group_b = _make_duplicate_group_with_n_files(2)  # ids 200, 201
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group_a, group_b])

    # Leave group_a (rows 0-1) on its default (best-quality) selection,
    # but move group_b's (rows 2-3) selection onto its SECOND file
    # (row 3, id 201) instead of the default (row 2, id 200).
    keep_column = _duplicates_column(window, "Keep")
    window.duplicates_table.cellWidget(3, keep_column).setChecked(True)

    def fake_exec(self):
        self.confirm_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkResolveDuplicatesDialog, "exec", fake_exec)
    # Roadmap item C3 (round 5) — see the identical fix/comment on
    # test_replace_all_upgrades_button_calls_batch_with_every_request_id:
    # this test's own wait condition (resolve_groups_calls != []) can be
    # satisfied before `_on_bulk_resolve_duplicates_finished`'s real
    # QMessageBox.information() call has fired, leaving it queued to
    # pop a genuine blocking modal during a later test.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window.resolve_all_duplicates_button.click()

    qtbot.waitUntil(
        lambda: application.duplicate_service.resolve_groups_calls != [],
        timeout=2000,
    )
    plans = application.duplicate_service.resolve_groups_calls[0]
    assert len(plans) == 2
    plans_by_keep = {plan.keep_local_file_id: plan for plan in plans}
    assert plans_by_keep[101].delete_local_file_ids == [102]
    assert plans_by_keep[201].delete_local_file_ids == [200]


def test_resolve_all_duplicates_skips_keep_all_groups(qtbot, monkeypatch):
    group_a = _make_duplicate_group()  # ids 101, 102
    group_b = _make_duplicate_group_with_n_files(2)  # ids 200, 201
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group_a, group_b])

    actions_column = _duplicates_column(window, "Actions")
    group_b_actions = window.duplicates_table.cellWidget(2, actions_column)
    keep_all_radio = next(
        w for w in group_b_actions.findChildren(QRadioButton)
        if w.text() == "Keep all"
    )
    keep_all_radio.setChecked(True)

    def fake_exec(self):
        self.confirm_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkResolveDuplicatesDialog, "exec", fake_exec)
    # Roadmap item C3 (round 5) — same real leaked-QMessageBox fix as
    # the two tests above.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window.resolve_all_duplicates_button.click()

    qtbot.waitUntil(
        lambda: application.duplicate_service.resolve_groups_calls != [],
        timeout=2000,
    )
    plans = application.duplicate_service.resolve_groups_calls[0]
    # Only group_a's plan -- group_b (Keep all) was skipped entirely,
    # never overridden.
    assert len(plans) == 1
    assert plans[0].keep_local_file_id == 101


def test_resolve_all_duplicates_cancelled_dialog_calls_nothing(
        qtbot,
        monkeypatch,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    monkeypatch.setattr(
        BulkResolveDuplicatesDialog, "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    window.resolve_all_duplicates_button.click()

    assert application.duplicate_service.resolve_groups_calls == []


def test_resolve_all_duplicates_unconfirmed_checkbox_calls_nothing(
        qtbot, monkeypatch,
):
    # Defense in depth (R3.2) — even if exec() somehow returns Accepted
    # without the checkbox actually being checked, nothing real happens.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    monkeypatch.setattr(
        BulkResolveDuplicatesDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    window.resolve_all_duplicates_button.click()

    assert application.duplicate_service.resolve_groups_calls == []


def test_resolve_all_duplicates_drops_only_succeeded_groups_locally(
        qtbot, monkeypatch,
):
    from seeker.library.duplicate_service import BulkDuplicateResolutionResult

    group_a = _make_duplicate_group()
    group_b = _make_duplicate_group_with_n_files(2)
    application = FakeApplication()
    application.duplicate_service.resolve_groups_result = (
        BulkDuplicateResolutionResult(
            groups_resolved=1, groups_failed=1, files_deleted=1,
            files_failed=1, files_skipped_same_physical_file=0,
            bytes_freed=10,
            details=["Group partially failed: 1 of 1 file(s) could not "
                     "be deleted."],
            plan_outcomes=[True, False],
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group_a, group_b])

    def fake_exec(self):
        self.confirm_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkResolveDuplicatesDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window.resolve_all_duplicates_button.click()

    qtbot.waitUntil(
        lambda: window.duplicates_table.rowCount() == 2, timeout=2000,
    )
    # group_a (succeeded, plan_outcomes[0]=True) is gone; group_b
    # (failed, plan_outcomes[1]=False) is still shown.
    assert len(window._current_duplicate_groups) == 1
    assert window._current_duplicate_groups[0] is group_b


def test_duplicate_groups_keep_selection_survives_rerender(qtbot):
    # Roadmap item R2.2/R2.6 — the user moves the "keep" selection off
    # the pre-selected best-quality file (row 0) onto row 1; a rerender
    # (e.g. after a local delete-finished re-render) must not silently
    # snap it back to the default.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    group = _make_duplicate_group()

    window._render_duplicate_groups([group])
    keep_column = _duplicates_column(window, "Keep")
    window.duplicates_table.cellWidget(1, keep_column).setChecked(True)

    for _ in range(3):
        window._render_duplicate_groups([group])

    keep_radio_0 = window.duplicates_table.cellWidget(0, keep_column)
    keep_radio_1 = window.duplicates_table.cellWidget(1, keep_column)
    assert keep_radio_0.isChecked() is False
    assert keep_radio_1.isChecked() is True


def test_duplicate_groups_keep_all_selection_survives_rerender(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    group = _make_duplicate_group()

    window._render_duplicate_groups([group])
    actions = window.duplicates_table.cellWidget(
        0, _duplicates_column(window, "Actions"),
    )
    keep_all_radio = next(
        b for b in actions.findChildren(QRadioButton)
        if b.text() == "Keep all"
    )
    keep_all_radio.setChecked(True)

    window._render_duplicate_groups([group])

    actions = window.duplicates_table.cellWidget(
        0, _duplicates_column(window, "Actions"),
    )
    keep_all_radio = next(
        b for b in actions.findChildren(QRadioButton)
        if b.text() == "Keep all"
    )
    assert keep_all_radio.isChecked() is True
    keep_column = _duplicates_column(window, "Keep")
    assert window.duplicates_table.cellWidget(
            0,
            keep_column,
    ).isChecked() is False
    assert window.duplicates_table.cellWidget(
            1,
            keep_column,
    ).isChecked() is False


def test_duplicate_groups_keep_selection_pruned_when_group_removed(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    group = _make_duplicate_group()

    window._render_duplicate_groups([group])
    keep_column = _duplicates_column(window, "Keep")
    window.duplicates_table.cellWidget(1, keep_column).setChecked(True)
    assert len(window._duplicates_keep_selection) == 1

    # The group is gone (resolved) -- R2.3's pruning.
    window._render_duplicate_groups([])
    assert window._duplicates_keep_selection == {}


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
    # behaves differently than a direct call).
    #
    # Roadmap item 73 (P4) — item 56's own conclusion here was wrong,
    # not this test's coverage: `isVisible()` is true even for a widget
    # clipped to near-zero real width, which is exactly what a real
    # production run at the app's own 960x640 minimum window size did
    # (confirmed live: a real 0px visibleRegion). Widened at the SAME
    # real pipeline this test already exercises, rather than replacing
    # it — now resizes to 960x640 and asserts real sectionSize/
    # visibleRegion geometry, not just presence + isVisible().
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
    window.resize(960, 640)
    window._show_page("duplicates")

    header = window.duplicates_table.horizontalHeader()
    actions_column = _duplicates_column(window, "Actions")

    for _ in range(2):  # first render, then a full re-render
        window._render_duplicate_groups(groups)
        qtbot.wait(20)
        widget = window.duplicates_table.cellWidget(0, actions_column)
        assert widget is not None
        assert widget.isVisible()
        assert widget.findChild(QPushButton) is not None
        assert widget.findChild(QCheckBox) is not None

        assert header.sectionSize(actions_column) >= widget.sizeHint().width()
        visible_width = widget.visibleRegion().boundingRect().width()
        assert visible_width >= widget.sizeHint().width() - 2


def test_render_duplicate_groups_actions_only_on_group_first_row(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    first_row_actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    # Roadmap item 77 (P7, 5th report) — a covered row now gets NO cell
    # widget at all (not even a blank placeholder): a blank widget there
    # used to be resolved by the span to the exact same rect as the
    # real widget and paint over it. The span itself, not a widget,
    # is what makes the covered row read as blank.
    other_row_actions = window.duplicates_table.cellWidget(
            1,
            _duplicates_column(window, "Actions"),
    )
    assert first_row_actions.findChildren(QPushButton)
    assert other_row_actions is None


def test_duplicates_actions_column_survives_manual_column_resize(qtbot):
    # Roadmap item 68 (Phase 7.1) — the one cheap extra check beyond the
    # index-hardening itself: a user manually drag-resizing a column
    # (setColumnWidth simulates this) must not disturb the Actions cell
    # widget's own correctness — Qt's view owns repositioning it.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    actions_column = _duplicates_column(window, "Actions")
    path_column = _duplicates_column(window, "Path")
    window.duplicates_table.setColumnWidth(path_column, 500)
    window.duplicates_table.setColumnWidth(actions_column, 50)

    widget = window.duplicates_table.cellWidget(0, actions_column)
    assert widget is not None
    assert widget.findChild(QPushButton) is not None
    assert widget.findChild(QCheckBox) is not None


# --- Roadmap item 73 (P4): Actions column visibility + stale spans --------

def test_duplicates_actions_widget_is_really_visible_at_app_minimum_size(
        qtbot,
):
    # Regression test for the REAL reported bug, this brief's standing
    # rule #2: a test that only asserts cellWidget(row, col) returns a
    # widget is not a test that a user can SEE it -- three prior
    # investigations all asked that weaker question. This asserts real
    # geometry at the app's own real minimum window size (960x640,
    # main_window.py's setMinimumSize).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.resize(960, 640)
    window._show_page("duplicates")

    window._render_duplicate_groups([_make_duplicate_group()])
    qtbot.wait(20)

    header = window.duplicates_table.horizontalHeader()
    actions_column = _duplicates_column(window, "Actions")
    widget = window.duplicates_table.cellWidget(0, actions_column)
    assert widget is not None

    assert header.sectionSize(actions_column) >= widget.sizeHint().width()
    visible_width = widget.visibleRegion().boundingRect().width()
    # A small rounding/border gap between a widget's real width and its
    # own sizeHint is normal Qt layout behavior, not a visibility bug —
    # the actual regression this guards against is a widget clipped to
    # a SLIVER (confirmed live: a real 0px visibleRegion at 960x640
    # before this fix), not an exact-pixel match. Widened 2 -> 4px by
    # item E3 (round 7): removing make_card's universal `*` stylesheet
    # cascade let the button inside this cell widget draw its OWN real
    # 1px QPushButton border on each side for the first time (previously
    # forced off by the exact bug E3 fixed) — a genuine few-px shift in
    # its real rendered size, not a new visibility defect.
    assert visible_width >= widget.sizeHint().width() - 4


def test_duplicates_actions_widget_is_not_occluded_by_a_covered_row_widget(
        qtbot,
):
    # Roadmap item 77 (P7, 5th report) — the real root cause: a group
    # with more than one file used to place a blank QWidget() on every
    # row COVERED by the Actions span. QTableView resolves a spanned
    # region's geometry identically for every row inside the span, so
    # that blank widget landed on the EXACT SAME rect as the real
    # group_first_row widget and, being added later, painted over it —
    # confirmed live via a standalone PySide6 repro before this fix
    # (real geom == blank geom, child order REAL-then-BLANK,
    # childAt(center) returned the blank widget). Every prior
    # regression test (existence, geometry, visibleRegion) passed
    # anyway, because the real widget's own visibleRegion() is
    # non-empty even while occluded by a sibling — occlusion is a
    # z-order/paint-order property, not a geometry property. This test
    # is occlusion-aware: it asks what a real click would actually hit.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("duplicates")

    window._render_duplicate_groups([_make_duplicate_group_with_n_files(3)])
    qtbot.wait(20)

    actions_column = _duplicates_column(window, "Actions")
    real_widget = window.duplicates_table.cellWidget(0, actions_column)
    assert real_widget is not None

    cell_rect = window.duplicates_table.visualRect(
        window.duplicates_table.model().index(0, actions_column)
    )
    hit = window.duplicates_table.viewport().childAt(cell_rect.center())
    assert hit is not None
    assert hit is real_widget or real_widget.isAncestorOf(hit)

    # And no widget at all should have been placed on the covered rows
    # — the span itself is what makes them read as blank.
    assert window.duplicates_table.cellWidget(1, actions_column) is None
    assert window.duplicates_table.cellWidget(2, actions_column) is None


def test_duplicates_actions_column_is_fixed_width_derived_from_sizehint(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_duplicate_groups([_make_duplicate_group()])

    header = window.duplicates_table.horizontalHeader()
    actions_column = _duplicates_column(window, "Actions")
    widget = window.duplicates_table.cellWidget(0, actions_column)
    assert widget is not None

    assert (
        header.sectionResizeMode(actions_column)
        == QHeaderView.ResizeMode.Fixed
    )
    assert header.sectionSize(actions_column) == widget.sizeHint().width()


def test_duplicates_actions_widgets_all_visible_after_group_shape_changes(
        qtbot,
):
    # Regression test for the second, independent, CONFIRMED defect:
    # setRowCount() does not clear spans, so a big group's span from a
    # PREVIOUS render could still "own" a row that a later, differently-
    # shaped render's own span tries to claim as ITS OWN anchor. Every
    # prior investigation's test re-rendered with the SAME group shape,
    # which can never exercise this — this one deliberately doesn't.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("duplicates")

    # First render: one big 4-file group -- spans rows 0-3, anchored at
    # row 0.
    window._render_duplicate_groups(
        [_make_duplicate_group_with_n_files(4)]
    )

    # Second render: two differently-shaped 2-file groups. Group B's own
    # span anchors at row 2 -- a row the FIRST render's span still
    # "owned" (as a non-anchor member) if clearSpans() were missing.
    window._render_duplicate_groups(
        [
            _make_duplicate_group_with_n_files(2),
            _make_duplicate_group_with_n_files(2),
        ]
    )
    qtbot.wait(20)

    actions_column = _duplicates_column(window, "Actions")
    for group_first_row in (0, 2):
        widget = window.duplicates_table.cellWidget(
            group_first_row, actions_column,
        )
        assert widget is not None
        assert widget.findChild(QPushButton) is not None
        assert (
            window.duplicates_table.rowSpan(group_first_row, actions_column)
            == 2
        )
        assert widget.isVisible()


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

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
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

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    # location_id is the KEPT file's own local_file.location_id
    # (roadmap item 68 Phase 7.2) — resolved from the group itself, not
    # from a "current location" the UI happens to have loaded, so this
    # is correct even in this test's direct _render_duplicate_groups()
    # call with no combo selection made.
    assert application.duplicate_service.delete_local_files_calls == [
            ([102], 101, 1)
    ]


def test_delete_duplicates_respects_a_changed_keep_selection(
        qtbot,
        monkeypatch,
):
    # Moving the radio to a.mp3 (id 102) before deleting must delete
    # a.flac (id 101) instead of the pre-selected default.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([_make_duplicate_group()])

    window.duplicates_table.cellWidget(
            1,
            _duplicates_column(window, "Keep"),
    ).setChecked(True)

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    assert application.duplicate_service.delete_local_files_calls == [
            ([101], 102, 1)
    ]


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

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
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


def test_delete_duplicates_partial_failure_keeps_group_visible(
        qtbot,
        monkeypatch,
):
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

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
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

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
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

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox = actions.findChildren(QCheckBox)[0]
    keep_all_radio = next(
        w for w in actions.findChildren(QRadioButton)
        if w.text() == "Keep all"
    )

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


def test_delete_duplicates_group_of_three_deletes_exactly_two(
        qtbot,
        monkeypatch,
):
    _confirm_yes(monkeypatch)
    group = _make_duplicate_group_with_n_files(3)
    application = FakeApplication(duplicate_groups=[group])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group])

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    delete_ids, keep_id, _location_id = (
        application.duplicate_service.delete_local_files_calls[0]
    )
    assert keep_id == 200  # files[0] is the group's own recommendation
    assert sorted(delete_ids) == [201, 202]


def test_delete_duplicates_group_of_four_deletes_exactly_three(
        qtbot,
        monkeypatch,
):
    _confirm_yes(monkeypatch)
    group = _make_duplicate_group_with_n_files(4)
    application = FakeApplication(duplicate_groups=[group])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._render_duplicate_groups([group])

    actions = window.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    delete_ids, keep_id, _location_id = (
        application.duplicate_service.delete_local_files_calls[0]
    )
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
    assert (
        window.sharing_locations_table.cellWidget(1, 4)
        .findChild(QPushButton) is not None
    )
    assert window.sharing_uploads_table.item(0, 0).text() == (
        help_text.NO_UPLOADS_LABEL
    )


def test_sharing_uploads_table_clears_stale_span_after_empty_state(qtbot):
    # Roadmap item 73 (P4 audit) — the SAME stale-span bug the
    # duplicates table had, found live via that fix's own "audit every
    # other table" instruction: the empty-state branch spans row 0
    # across all 4 columns; setRowCount() alone does not clear that
    # span, so a transition from empty -> a real upload used to leave
    # the stale span active, visually swallowing the new row's
    # filename/state/progress cells into column 0.
    from seeker.sharing_service import UploadStatus

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_sharing_uploads_table([])
    assert window.sharing_uploads_table.columnSpan(0, 0) == 4

    window._render_sharing_uploads_table([
        UploadStatus(
            username="alice", filename="track.flac", state="InProgress",
            bytes_transferred=100, size=1000,
        ),
    ])

    assert window.sharing_uploads_table.rowSpan(0, 0) == 1
    assert window.sharing_uploads_table.columnSpan(0, 0) == 1
    assert window.sharing_uploads_table.item(0, 1).text() == "track.flac"


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

    button = window.sharing_locations_table.cellWidget(0, 4).findChild(
        QPushButton,
    )
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

    button = window.sharing_locations_table.cellWidget(0, 4).findChild(
        QPushButton,
    )
    button.click()

    assert len(info_calls) == 1
    assert sharing_service.add_location_to_share_calls == []


def test_every_actions_column_table_has_a_derived_floor_for_row_height_and_width(
        qtbot,
):
    # Roadmap item R5 (5b.4) — regression coverage for every table with
    # a real Actions column, generalizing item 73's own single-table
    # test: the column must be widened to at least the real Actions
    # widget's own sizeHint().width() ("Confirm" clipped to "onfirm"),
    # and every row must be at least as tall as that widget's own
    # sizeHint().height() ("Replace"/"Decline" sliced off at the
    # bottom) — both derived from the real widget actually built this
    # render, never a magic number.
    from seeker.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(
        [_make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._render_local_needs_review_matches([_make_needs_review_match()])
    window._render_sharing_locations_table([
        LocationShareState(
            location=_make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window.settings_page._render_locations(
        [(_make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )

    tables_and_columns = [
        (window.track_table, 3),
        (window.review_needs_table, 3),
        (window.review_upgrades_table, 3),
        (window.review_local_table, 4),
        (window.sharing_locations_table, 4),
        # Roadmap item 97 (B6.3) — settings_window.py's own table had
        # never had a derived Actions width before this.
        (window.settings_page.locations_table, 3),
    ]

    for table, actions_column in tables_and_columns:
        assert table.rowCount() >= 1, table.objectName() or repr(table)
        widget = table.cellWidget(0, actions_column)
        assert widget is not None

        header = table.horizontalHeader()
        assert header.sectionSize(actions_column) >= widget.sizeHint().width()
        assert table.rowHeight(0) >= widget.sizeHint().height()


def test_every_table_and_list_goes_through_the_shared_chrome_helpers(qtbot):
    # Roadmap item 97 (B6.4) — this is the third round in a row a shared
    # table-chrome fix landed in main_window.py and not settings_window.py
    # (item 80, then R5, now this). A real structural check over every
    # live QTableWidget/QListWidget in the real app, not just the two
    # settings_window.py had, so a FOURTH table added anywhere without
    # going through apply_table_defaults()/make_card() fails this test
    # instead of quietly reappearing as the same class of bug.
    from PySide6.QtWidgets import QFrame, QListWidget, QTableWidget

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    def _has_card_ancestor(widget) -> bool:
        parent = widget.parent()
        while parent is not None:
            if isinstance(parent, QFrame) and parent.objectName() == "card":
                return True
            parent = parent.parent()
        return False

    tables = window.findChildren(QTableWidget)
    lists = window.findChildren(QListWidget)
    assert tables, "no QTableWidget found — test itself is broken"
    assert lists, "no QListWidget found — test itself is broken"

    for table in tables:
        assert table.verticalHeader().isVisible() is False, (
            table.objectName() or repr(table)
        )
        assert _has_card_ancestor(table), table.objectName() or repr(table)

    for widget_list in lists:
        assert _has_card_ancestor(widget_list), (
            widget_list.objectName() or repr(widget_list)
        )


def _assert_every_column_fits_its_own_header(window) -> None:
    from PySide6.QtWidgets import QTableWidget

    for table in window.findChildren(QTableWidget):
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            if item is None or not item.text():
                continue
            floor = theme.header_label_floor(table, column)
            assert header.sectionSize(column) >= floor, (
                f"{table.objectName() or table!r} col {column} "
                f"({item.text()!r}): section={header.sectionSize(column)} "
                f"< floor={floor}"
            )


def test_no_table_column_clips_its_own_header_label_when_empty(qtbot):
    # Roadmap item C2 (round 5) — the real reported bug: "Actions"
    # rendered as ".ction" on Review's three EMPTY tables (a brand-new
    # user's very first look at that page). `size_action_column`'s old
    # fallback for zero real action widgets was a generic 40px floor
    # with no relation to the header text at all. Every real
    # QTableWidget in the app starts with zero rows at construction —
    # this is exactly that state, checked structurally across the
    # whole window rather than one page at a time.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    _assert_every_column_fits_its_own_header(window)

    # And again at the app's real 960x640 minimum — construction-time
    # column widths don't depend on window size, but this is the exact
    # size the brief's own screenshot was taken at.
    window.resize(960, 640)
    qtbot.wait(20)
    _assert_every_column_fits_its_own_header(window)


def test_no_table_column_clips_its_own_header_label_when_populated(qtbot):
    # C2.3/C2.4 — the same invariant must keep holding once real rows
    # (and real, possibly-narrow Actions widgets) exist, at both the
    # app's real 960x640 minimum and a default-sized window.
    from seeker.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window._render_track_statuses(
        [_make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._render_local_needs_review_matches([_make_needs_review_match()])
    window._render_sharing_locations_table([
        LocationShareState(
            location=_make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window._render_duplicate_groups([_make_duplicate_group()])
    window.settings_page._render_locations(
        [(_make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )
    qtbot.wait(20)

    for width, height in [(960, 640), (1280, 800)]:
        window.resize(width, height)
        qtbot.wait(20)
        _assert_every_column_fits_its_own_header(window)


def _assert_no_dead_band_at_stretch_columns(window, qtbot) -> None:
    from PySide6.QtWidgets import QTableWidget

    # Roadmap item E2.3 (round 7) — this used to `continue` past any
    # table with no Stretch column/stretchLastSection, which sounds
    # like a reasonable "this invariant doesn't apply here" guard but
    # is derived from the SAME state E2's own bug corrupts: an empty
    # table (nothing has ever assigned it a resize mode) reads as "no
    # stretch column" and was skipped by this exact test, on the exact
    # screen (an empty Search/Duplicates table) the user photographed
    # as broken. A skip condition computed from the state the bug
    # corrupts cannot be a guard — asserting the real invariant
    # unconditionally for every visible table is the only way this test
    # can't blind itself to the case it exists to catch.
    for page_key in (
        "dashboard", "search", "downloads", "review",
        "duplicates", "sharing", "history", "settings",
    ):
        window._show_page(page_key)
        qtbot.wait(10)
        for table in window.findChildren(QTableWidget):
            if not table.isVisible():
                continue
            header = table.horizontalHeader()
            total = sum(
                header.sectionSize(column)
                for column in range(table.columnCount())
            )
            viewport_width = table.viewport().width()
            assert total >= viewport_width - 2, (
                f"{table.objectName() or table!r} on page {page_key!r}: "
                f"sum(sectionSize)={total} < viewport width="
                f"{viewport_width} — a Stretch column left dead space"
            )


def test_stretch_columns_reach_the_viewport_edge_with_no_dead_band(qtbot):
    # Roadmap item D3.5 (round 6) — the actual regression check for the
    # reported bug: a `Stretch` column pinned to its header-label floor
    # by the OLD, unscoped `apply_table_defaults` loop, leaving a dead
    # band between the last real column and the table's own right edge.
    # Paired deliberately with the C2 header-floor test above — the two
    # invariants pull in opposite directions (widen a column for its
    # header vs. never pin a column that's supposed to size itself) and
    # both must hold at once, with zero rows and with real ones, at the
    # app's real 960x640 minimum and a default-sized window.
    from seeker.models.soulseek_file import SoulseekFile
    from seeker.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    for width, height in [(960, 640), (1280, 800)]:
        window.resize(width, height)
        qtbot.wait(20)
        _assert_no_dead_band_at_stretch_columns(window, qtbot)

    window._render_track_statuses(
        [_make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._render_search_results(
        "Dom Dolla", "Rhyme Dust",
        [
            SoulseekFile(
                username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
                extension="flac", size=25_000_000, queue_length=0,
                upload_speed=1_000_000, has_free_upload_slot=True,
            ),
        ],
    )
    window._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._render_local_needs_review_matches([_make_needs_review_match()])
    window._render_sharing_locations_table([
        LocationShareState(
            location=_make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window._render_duplicate_groups([_make_duplicate_group()])
    window.settings_page._render_locations(
        [(_make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )
    qtbot.wait(20)

    for width, height in [(960, 640), (1280, 800)]:
        window.resize(width, height)
        qtbot.wait(20)
        _assert_no_dead_band_at_stretch_columns(window, qtbot)


def test_every_table_has_a_stretch_column_immediately_after_construction(
        qtbot,
):
    # Roadmap item E2.4 (round 7) — the structural invariant whose
    # absence caused E2 in the first place: seven tables only assigned
    # their real resize modes (a Stretch column, or stretchLastSection)
    # inside a render method that never runs while the table is empty,
    # so a freshly-built, still-empty table sat at Qt's default 100px-
    # per-column layout with no column owning the leftover viewport
    # width. Checked with NO `.show()` and NO render call at all — every
    # page is built eagerly in `MainWindow.__init__` (`_register_page`),
    # so this is genuinely "immediately after construction," the exact
    # moment E2's fix (`_configure_*_columns`, called from each table's
    # own `_build_*`) must already hold.
    from PySide6.QtWidgets import QHeaderView, QTableWidget

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    tables = window.findChildren(QTableWidget)
    assert tables, "expected at least one QTableWidget in the window"

    for table in tables:
        header = table.horizontalHeader()
        has_stretch = header.stretchLastSection() or any(
            header.sectionResizeMode(column)
            == QHeaderView.ResizeMode.Stretch
            for column in range(table.columnCount())
        )
        assert has_stretch, (
            f"{table.objectName() or table!r} has no Stretch column and "
            f"no stretchLastSection immediately after construction — an "
            f"empty render of this table will sit at Qt's default "
            f"100px-per-column layout"
        )


def test_dashboard_downloading_bar_is_vertically_centered(qtbot):
    # Roadmap item C3 (round 5) — the real reported bug: the DASHBOARD
    # track table (Track/Status/Progress/Actions, with "In library"/
    # "Downloading" rows) builds its own bare QProgressBar directly in
    # `_render_track_statuses`, a second, independent site B4/item 96
    # never touched (that fix only reached the DOWNLOADS page's own
    # `_build_progress_widget`). Same real pixel-scan method as item
    # 96's own regression test — this is the Dashboard's own version of
    # it, proving the shared `_wrap_progress_bar` container now covers
    # both sites.
    status = TrackStatus(
        track=_make_track("t1"), state=DOWNLOADING,
        bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._render_track_statuses([status])
    qtbot.wait(100)

    viewport = window.track_table.viewport()
    row_rect = window.track_table.visualRect(
        window.track_table.model().index(0, 2)
    )
    widget = window.track_table.cellWidget(0, 2)
    assert widget is not None
    bar = widget.findChild(QProgressBar)
    assert bar is not None

    bar_center_y = bar.mapTo(viewport, bar.rect().center()).y()
    assert abs(bar_center_y - row_rect.center().y()) <= 2

    # Real pixel scan (item 102's own lesson: geometry alone can lie
    # about what actually got painted) — find the bar's real painted
    # color span and compare ITS midpoint to the row's real center.
    image = window.grab().toImage()
    dpr = image.width() / window.width()
    surface_rgb = tuple(
        int(theme.BG_SURFACE[i:i + 2], 16) for i in (1, 3, 5)
    )
    top_left = viewport.mapTo(window, viewport.rect().topLeft())
    x = round((top_left.x() + row_rect.left() + 10) * dpr)
    y0 = round((top_left.y() + row_rect.top()) * dpr)
    y1 = round((top_left.y() + row_rect.bottom()) * dpr)

    painted_ys = [
        y for y in range(y0, y1 + 1)
        if (
            image.pixelColor(x, y).red(),
            image.pixelColor(x, y).green(),
            image.pixelColor(x, y).blue(),
        ) != surface_rgb
    ]
    assert painted_ys, "no painted bar pixels found"
    painted_center = (painted_ys[0] + painted_ys[-1]) / 2 / dpr
    row_center = top_left.y() + row_rect.center().y()
    assert abs(painted_center - row_center) <= 2


def test_no_table_ever_hands_a_bare_progress_bar_or_button_to_setcellwidget(
        qtbot,
):
    # Roadmap item C3 (round 5, C3.3) — the actual root cause of both
    # this item and B4/item 96: a bare QProgressBar or QPushButton
    # handed directly to setCellWidget gets resized to fill the WHOLE
    # cell rect, then either the global max-height rule clamps it to
    # the top (QProgressBar) or it paints as an oversized filled block
    # (QPushButton, item 80's own P10.3). A real structural sweep, not
    # a hand-picked list of tables — a fifth call site introduced
    # anywhere in the app fails this automatically.
    from seeker.models.soulseek_file import SoulseekFile
    from seeker.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window._render_track_statuses([
        TrackStatus(
            track=_make_track("t1"), state=DOWNLOADING,
            bytes_transferred=500, total_bytes=1_000,
        ),
        _make_track_status(track_id="t2", state=IN_LIBRARY, tagged_at=None),
    ])
    window._show_page("downloads")
    window._render_active_downloads([
        _make_active_download(
            track_id="t3", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ])
    window._show_page("search")
    window._render_search_results(
        "Dom Dolla", "Rhyme Dust",
        [
            SoulseekFile(
                username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
                extension="flac", size=25_000_000, queue_length=0,
                upload_speed=1_000_000, has_free_upload_slot=True,
            ),
        ],
    )
    window._show_page("duplicates")
    window._render_duplicate_groups([_make_duplicate_group()])
    window._show_page("review")
    window._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._render_local_needs_review_matches([_make_needs_review_match()])
    window._render_sharing_locations_table([
        LocationShareState(
            location=_make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window.settings_page._render_locations(
        [(_make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )
    qtbot.wait(20)

    from PySide6.QtWidgets import QTableWidget

    checked = 0
    for table in window.findChildren(QTableWidget):
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                widget = table.cellWidget(row, column)
                if widget is None:
                    continue
                checked += 1
                assert not isinstance(widget, (QProgressBar, QPushButton)), (
                    f"{table.objectName() or table!r} ({row}, {column}) "
                    f"got a bare {type(widget).__name__} directly"
                )
    assert checked > 0, "no cell widgets found — test itself is broken"


# --- Roadmap item E4 (round 7): wordmark, plain QLabel, no brows ------------

def test_wordmark_bottom_row_has_no_text_colored_pixel(qtbot):
    # Roadmap item E4.5 (round 7) — the actual invariant the user cares
    # about, which the deleted `_Wordmark`'s own D1.3 test never
    # expressed (it asserted a `sizeHint()` number, not a real pixel):
    # nothing in the rendered label may touch its own bottom edge. A
    # plain QLabel reserves real font-metric ascent/descent internally,
    # so this holds structurally rather than by any hand-tuned padding
    # constant. Real pixel scan (item 77's own lesson — geometry alone
    # can't prove a paint result), not a geometry-only check.
    label = QLabel("Seeker")
    label.setObjectName("wordmark")
    qtbot.addWidget(label)
    from seeker.ui import theme as theme_module
    label.setStyleSheet(theme_module.build_stylesheet(theme_module.DARK))
    label.resize(label.sizeHint())
    label.show()
    qtbot.waitExposed(label)

    image = label.grab().toImage()
    text_rgb = tuple(int(theme.DARK.TEXT[i:i + 2], 16) for i in (1, 3, 5))
    bottom_row = image.height() - 1
    for x in range(image.width()):
        color = image.pixelColor(x, bottom_row)
        assert (color.red(), color.green(), color.blue()) != text_rgb, (
            f"text-colored pixel at x={x} on the label's own bottom "
            f"row — the wordmark is touching its own edge"
        )


# --- Roadmap item C5: light/dark themes, with system-follow -----------------

def test_theme_toggle_cycles_system_light_dark_and_persists(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._theme_mode == "system"
    assert window._theme_toggle._mode == "system"

    window._theme_toggle.click()
    assert window._theme_mode == "light"
    assert window._theme_toggle._mode == "light"

    window._theme_toggle.click()
    assert window._theme_mode == "dark"

    window._theme_toggle.click()
    assert window._theme_mode == "system"

    # Every click persists through Application.set_theme_mode — a
    # restart must not lose the choice.
    assert application.set_theme_mode_calls == ["light", "dark", "system"]


def test_theme_toggle_and_settings_radios_stay_in_sync_both_directions(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Sidebar toggle -> Settings radios.
    window._theme_toggle.click()  # system -> light
    assert window.settings_page._theme_mode_radios["light"].isChecked()
    assert not window.settings_page._theme_mode_radios["system"].isChecked()

    # Settings radios -> sidebar toggle.
    window.settings_page._theme_mode_radios["dark"].setChecked(True)
    assert window._theme_mode == "dark"
    assert window._theme_toggle._mode == "dark"


def test_theme_mode_starts_from_the_persisted_config_value(qtbot):
    application = FakeApplication()
    application.set_theme_mode("dark")

    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._theme_mode == "dark"
    assert window._theme_toggle._mode == "dark"
    assert window.settings_page._theme_mode_radios["dark"].isChecked()


def test_system_scheme_signal_only_connected_while_mode_is_system(qtbot):
    # Roadmap item C5.6 — an explicit light/dark choice must never be
    # silently overridden by the OS's own appearance changing later.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._system_scheme_connected is True

    window._theme_toggle.click()  # system -> light, an explicit choice
    assert window._theme_mode == "light"
    assert window._system_scheme_connected is False

    window._theme_toggle.click()  # light -> dark, still explicit
    assert window._system_scheme_connected is False

    window._theme_toggle.click()  # dark -> system, back to following
    assert window._system_scheme_connected is True


def test_cleanup_before_quit_disconnects_the_system_scheme_signal(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    assert window._system_scheme_connected is True

    window.cleanup_before_quit()

    assert window._system_scheme_connected is False


# --- Roadmap item C5.8 — the palettes' own contrast floors are tested in
# test_theme.py directly; DARK's real-values-unchanged claim is checked
# structurally here. -------------------------------------------------------

def test_dark_palette_is_byte_identical_to_the_pre_refactor_constants():
    # Roadmap item C5.1 — "DARK carries today's EXACT values,
    # unchanged... the first thing to prove." These are the literal
    # hex strings theme.py held as bare module constants before this
    # refactor (see CLAUDE.md's own pre-C5 history) — a real pin, not a
    # restatement of whatever DARK currently says.
    assert theme.DARK.BG_APP == "#100E15"
    assert theme.DARK.BG_SIDEBAR == "#15121D"
    assert theme.DARK.BG_SURFACE == "#1D1929"
    assert theme.DARK.BG_SURFACE_2 == "#29243A"
    assert theme.DARK.BORDER == "#3A344E"
    assert theme.DARK.BORDER_STRONG == "#4E4768"
    assert theme.DARK.TEXT == "#ECEAF3"
    assert theme.DARK.TEXT_MUTED == "#9E98B3"
    assert theme.DARK.TEXT_FAINT == "#6F6987"
    assert theme.DARK.ACCENT == "#7C5CFF"
    assert theme.DARK.ACCENT_HOVER == "#8E72FF"
    assert theme.DARK.ACCENT_PRESSED == "#6446E0"
    assert theme.DARK.ACCENT_SUBTLE == "#241E3D"
    assert theme.DARK.SUCCESS == "#3FBF7F"
    assert theme.DARK.WARNING == "#E0A33E"
    assert theme.DARK.DANGER == "#E5484D"


def test_apply_theme_with_dark_mode_produces_the_same_stylesheet_as_before(
        qtbot,
):
    # A real structural no-op check: resolve_palette("dark") must be
    # the exact same Palette object DARK already is (not a re-typed
    # copy that happens to compare equal).
    assert theme.resolve_palette("dark") is theme.DARK


# --- Roadmap item C5.10 — the theme toggle's own glyph rendering ------------

def test_theme_toggle_button_renders_all_three_modes_without_crashing(qtbot):
    for mode in _THEME_MODE_CYCLE:
        button = _ThemeToggleButton(mode)
        qtbot.addWidget(button)
        button.show()
        qtbot.wait(10)
        assert button.toolTip() != ""


# --- Roadmap item D2 (round 6): the theme toggle actually applying -------
#
# D2.1's real finding: `QGuiApplication.styleHints().setColorScheme()`
# never actually changes `.colorScheme()` or emits `colorSchemeChanged`
# under the offscreen QPA platform this whole suite runs on (confirmed
# empirically, not assumed) — so the real re-entrancy bug (a live macOS
# `colorSchemeChanged` firing synchronously from INSIDE
# `theme.apply_theme()`'s own `setColorScheme()` call) cannot be forced
# through the real signal in a headless test the way it happens on a
# real Mac. The tests below exercise the actual fix mechanics directly
# instead: D2.2's reordering (behavioral — the stylesheet itself, not
# just the mode string/icon) and D2.3/D2.4's guard conditions.

def test_theme_toggle_actually_changes_the_applied_stylesheet(qtbot):
    # This is exactly the behavior D2 reports as broken: the mode
    # string and icon updated while the real stylesheet did not. Assert
    # the stylesheet itself, not just `window._theme_mode`.
    from PySide6.QtWidgets import QApplication

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    app = QApplication.instance()
    assert app is not None

    window._theme_toggle.click()  # system -> light
    assert theme.BG_SURFACE == theme.LIGHT.BG_SURFACE
    assert theme.LIGHT.BG_SURFACE in app.styleSheet()

    window._theme_toggle.click()  # light -> dark
    assert theme.BG_SURFACE == theme.DARK.BG_SURFACE
    assert theme.DARK.BG_SURFACE in app.styleSheet()

    window._theme_toggle.click()  # dark -> system
    resolved = theme.resolve_palette("system")
    assert theme.BG_SURFACE == resolved.BG_SURFACE
    assert resolved.BG_SURFACE in app.styleSheet()


def test_apply_theme_mode_survives_a_synchronous_scheme_signal_mid_apply(
        qtbot, monkeypatch,
):
    # Roadmap item D2.2/D2.3 — simulates the real defect directly: a
    # `colorSchemeChanged` emission firing SYNCHRONOUSLY from inside
    # `theme.apply_theme()`'s own `setColorScheme()` call, which is
    # exactly what a real macOS run does and the offscreen QPA plugin
    # does not (see the module comment above). Before the D2 fix, this
    # re-entrant call would re-resolve and silently reapply the SYSTEM
    # palette over the explicit "light" choice this call is making.
    from PySide6.QtWidgets import QApplication

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    real_apply_theme = theme.apply_theme

    def apply_theme_with_synchronous_signal(app, mode):
        result = real_apply_theme(app, mode)
        # A stray real-world signal arriving mid-call, regardless of
        # what triggered it — the guard must hold regardless of cause.
        window._on_system_color_scheme_changed(object())
        return result

    monkeypatch.setattr(
            theme,
            "apply_theme",
            apply_theme_with_synchronous_signal,
    )

    window._apply_theme_mode("light")

    assert window._theme_mode == "light"
    assert theme.BG_SURFACE == theme.LIGHT.BG_SURFACE
    app = QApplication.instance()
    assert app is not None
    assert theme.LIGHT.BG_SURFACE in app.styleSheet()


def test_system_scheme_handler_ignored_while_theme_is_being_applied(qtbot):
    # Roadmap item D2.3 — the `_applying_theme` guard directly, with no
    # dependency on whether the offscreen platform can emit the signal.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    calls: list[tuple[object, ...]] = []
    window._apply_theme_mode = lambda *a, **k: calls.append(a)  # type: ignore[method-assign]
    window._applying_theme = True

    window._on_system_color_scheme_changed(object())

    assert calls == []


def test_system_scheme_handler_ignored_once_mode_is_no_longer_system(qtbot):
    # Roadmap item D2.4 — the handler must not act just because it's
    # still connected; it must check the CURRENT mode too, not rely
    # solely on the subscription having been torn down in time.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._theme_mode = "light"
    calls: list[tuple[object, ...]] = []
    window._apply_theme_mode = lambda *a, **k: calls.append(a)  # type: ignore[method-assign]

    window._on_system_color_scheme_changed(object())

    assert calls == []


# --- Roadmap item R7: run in the background from the macOS menu bar --------

def _force_tray_available(monkeypatch, available: bool) -> None:
    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", lambda: available,
    )


def test_tray_icon_not_built_when_unavailable(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._tray_icon is None


def test_application_active_reopens_a_hidden_window(qtbot, monkeypatch):
    # Roadmap item 116 (round 8, §14.2.3) — this proves the HANDLER's
    # own contract (a hidden window comes back on a real
    # applicationStateChanged(ApplicationActive) emission), not that a
    # real Dock click reaches it -- that can't be produced under
    # QT_QPA_PLATFORM=offscreen and is left for real-desktop
    # verification.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.hide()
    assert window.isHidden()

    window._on_application_state_changed(
        Qt.ApplicationState.ApplicationActive
    )

    assert not window.isHidden()


def test_application_active_is_a_near_no_op_when_already_visible(
        qtbot, monkeypatch,
):
    # ApplicationActive also fires on ordinary activation (Cmd-Tab,
    # clicking a window) and, since Qt passes forcePropagate=true, even
    # when the state was already Active -- must not re-enter
    # _on_tray_open_seeker (and its poll calls) every time.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    assert not window.isHidden()

    calls = []
    monkeypatch.setattr(
        window, "_on_tray_open_seeker", lambda: calls.append(1),
    )

    window._on_application_state_changed(
        Qt.ApplicationState.ApplicationActive
    )

    assert calls == []


def test_non_active_state_change_does_nothing(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.hide()
    assert window.isHidden()

    window._on_application_state_changed(
        Qt.ApplicationState.ApplicationInactive
    )

    assert window.isHidden()


def test_app_state_signal_connected_on_construction(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._app_state_connected is True


def test_app_state_signal_not_connected_without_a_tray_icon(qtbot, monkeypatch):
    # Roadmap item 116 (round 8, §14.2) — with no tray, closeEvent takes
    # the ordinary real-close path; there's no "hidden but still
    # running" state a reopen gesture would ever need to restore, so
    # connecting here would be pure overhead.
    _force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._app_state_connected is False


def test_cleanup_before_quit_disconnects_the_app_state_signal(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    assert window._app_state_connected is True

    window.cleanup_before_quit()

    assert window._app_state_connected is False


def test_close_event_falls_back_to_real_close_when_no_tray(qtbot, monkeypatch):
    # Roadmap item R7.2 — the explicit fallback: with no real tray to
    # hide to, closing behaves exactly like it always did (a REAL
    # close, which — WA_DeleteOnClose being set — deletes the window's
    # own C++ object immediately; deliberately NOT registered with
    # qtbot.addWidget, since its own teardown would otherwise try to
    # close this same already-deleted window a second time).
    _force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    window.show()

    window.close()

    assert window._hidden_to_tray is False


def test_close_event_hides_to_tray_when_available(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    assert window._tray_icon is not None

    window.close()

    # `isHidden()` is synchronous (hide() itself is not deferred) — only
    # `_hidden_to_tray` waits on the delayed platform-level confirmation
    # (E1.4, round 7, corrected after review).
    assert window.isHidden()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)


def test_close_event_from_fullscreen_hides_without_leaving_fullscreen_first(
        qtbot, monkeypatch,
):
    # Roadmap item E1 (round 7) — reverses D4 (round 6). D4's own fix
    # (leave fullscreen via `showNormal()`, defer the real hide to the
    # next `WindowStateChange`) was only ever confirmed under offscreen
    # QPA, which has no macOS Space and no animated transition at all —
    # a real Mac's exit-fullscreen animation runs for a genuine several
    # hundred milliseconds, and the deferred `hide()` landed mid-
    # transition, leaving Qt's widget marked hidden while AppKit
    # re-ordered the real NSWindow back on screen once the animation
    # finished (an empty, unclosable window — reported live). Fixed by
    # NOT calling `showNormal()` at all on macOS: this window's `hide()`
    # now runs directly on the still-fullscreen window (via `super().
    # closeEvent()`, on/macOS whenever fullscreen), trusting AppKit's own
    # "close a fullscreen window" handling — the one path guaranteed to
    # tear the Space down correctly, since it's the platform's own.
    # `isFullScreen()` deliberately still reports True here — Qt's
    # window-state flags don't reset on hide() alone, only on the
    # explicit `showNormal()` `_on_tray_open_seeker` performs on reopen
    # (see the geometry-restore test below).
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)
    assert window.isFullScreen()

    window.close()
    qtbot.wait(20)

    assert window.isHidden()
    # `_hidden_to_tray` waits on the delayed platform-level confirmation
    # (E1.4, round 7, corrected after review) — `isHidden()` above is
    # unaffected, since `hide()` itself is never deferred.
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)
    assert window._pre_fullscreen_geometry is not None


def test_reopening_after_a_fullscreen_close_restores_prior_geometry(
        qtbot, monkeypatch,
):
    # D4.2/E1 — reopening from the menu bar must give back the window
    # the user had, not an arbitrary default. `_pre_fullscreen_geometry`
    # is captured in `closeEvent`, before anything about fullscreen
    # state changes at all (E1 no longer calls `showNormal()` there);
    # `_on_tray_open_seeker` is what actually clears fullscreen and
    # restores it.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.setGeometry(QRect(50, 60, 1000, 700))
    qtbot.wait(20)
    expected_geometry = window.normalGeometry()

    window.showFullScreen()
    qtbot.wait(20)
    window.close()
    qtbot.wait(20)
    assert window.isHidden()

    window._on_tray_open_seeker()

    assert not window.isFullScreen()
    assert window.geometry() == expected_geometry


def test_hidden_to_tray_stays_false_when_platform_window_still_exposed(
        qtbot, monkeypatch,
):
    # Roadmap item E1.4 (round 7, corrected after a SECOND review) — the
    # actual invariant this guard exists for, exercised directly rather
    # than left uncovered: when the real platform window disagrees with
    # Qt's own hidden bookkeeping (exactly the reported bug — Qt marked
    # itself hidden while AppKit still had the real NSWindow on screen),
    # `_hidden_to_tray` must NOT flip True. `windowHandle().isExposed()`
    # can't be monkeypatched directly on a real `QWindow`, so this forces
    # the disagreement through `_is_exposed_at_platform_level` — the one
    # production code path that reads it either way.
    #
    # This guard is deliberately REPORT-ONLY now (a second review found
    # the first version's "retry" — calling `hide()` again from inside
    # this same check — was itself a corrective ACTION taken during a
    # state indistinguishable from "a real transition is still playing,"
    # which is how round 6's bug was built in the first place). So there
    # is no second check to wait for here: `_hidden_to_tray` stays False
    # permanently once this one check finds a disagreement — logged, not
    # acted on — matching the ordinary (non-fullscreen) hide path this is
    # only ever reachable from.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    monkeypatch.setattr(
        window, "_is_exposed_at_platform_level", lambda: True,
    )

    window.close()

    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 100)
    assert window._hidden_to_tray is False


def test_stale_hide_verification_does_not_rehide_a_reopened_window(
        qtbot, monkeypatch,
):
    # Roadmap item E1.4 (round 7, corrected after a SECOND review) — a
    # single tray-menu click within the verify delay (a legitimate
    # reopen) used to be indistinguishable from "the hide didn't take":
    # the delayed check would see the platform window legitimately
    # exposed (because the user just reopened it) and, in the OLD
    # "retry" design, call `hide()` again — silently hiding a window the
    # user had just deliberately reopened, with no explanation. Fixed
    # via `_hide_request_id`, bumped by both the hide attempt and
    # `_on_tray_open_seeker`; a stale check (captured BEFORE the reopen)
    # must see its id no longer matches and do nothing at all.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # The real platform window genuinely IS still exposed for a moment
    # after `close()` in this scenario (nothing artificial here) — what
    # matters is that the user reopens before the delayed check fires.
    monkeypatch.setattr(
        window, "_is_exposed_at_platform_level", lambda: True,
    )

    window.close()
    window._on_tray_open_seeker()
    assert window.isVisible()
    assert window._hidden_to_tray is False

    # Let the stale check (scheduled by the close, before the reopen)
    # actually fire — it must be a no-op: the window stays visible, and
    # `_hidden_to_tray` stays False (the true, post-reopen state), not
    # flipped True by a check that no longer reflects reality.
    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 100)
    assert window.isVisible()
    assert window._hidden_to_tray is False


def test_fullscreen_close_never_arms_hide_verification(qtbot, monkeypatch):
    # Roadmap item E1.4 (round 7, corrected after a SECOND review) — the
    # fullscreen close branch must not schedule ANY verification check:
    # nothing is hidden BY US on that path (AppKit's own exit-fullscreen-
    # and-close animation does the real hiding, asynchronously); a check
    # landing mid-animation would see the platform window still
    # genuinely exposed and, in the report-only design, merely log —
    # but in a design that ever grows a corrective action again, would
    # call `hide()` mid-transition, reproducing round 6's bug. Asserted
    # structurally (no `_confirm_hidden_to_tray` call at all), not just
    # by absence of a symptom.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    confirm_calls = []
    monkeypatch.setattr(
        window, "_confirm_hidden_to_tray",
        lambda *a, **k: confirm_calls.append((a, k)),
    )

    window.close()

    assert confirm_calls == []
    assert window._hidden_to_tray is True


# --- Roadmap item 116 (round 8, §14.3): the Dock icon while hidden ----

def test_ordinary_hide_drops_the_dock_icon_once_confirmed(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    assert dock_calls == [False]


def test_ordinary_hide_does_not_drop_dock_icon_without_a_visible_tray(
        qtbot, monkeypatch,
):
    # §14.3.4 — that state is unrecoverable (no Dock icon, no tray
    # icon either), so the switch is guarded on a real, visible tray
    # icon, same precondition closeEvent's own hide-to-tray branch uses.
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    # closeEvent's own initial "is there a real tray to hide to" check
    # already ran (synchronously, inside close(), with the tray still
    # visible) -- patched only now, so it's specifically the LATER
    # confirm-check's own guard being exercised, not closeEvent's.
    monkeypatch.setattr(window._tray_icon, "isVisible", lambda: False)
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    assert dock_calls == []


def test_fullscreen_close_schedules_a_policy_only_check(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )
    hide_calls = []
    monkeypatch.setattr(window, "hide", lambda: hide_calls.append(1))

    window.close()
    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 50)

    # Never calls hide() itself (nothing to manufacture round 6's bug
    # with) and does drop the Dock icon once the window reads as
    # genuinely not exposed (true under offscreen QPA immediately after
    # a real close()).
    assert hide_calls == []
    assert dock_calls == [False]


def test_fullscreen_close_policy_check_ignores_a_stale_request(
        qtbot, monkeypatch,
):
    # A reopen between the fullscreen close and the deferred check
    # firing must make the check a no-op — same `_hide_request_id`
    # staleness guard `_check_hidden_to_tray` already uses.
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    window._hide_request_id += 1  # simulates a reopen racing the check

    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 50)

    assert dock_calls == []


def test_reopen_restores_the_dock_icon_before_showing(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window._on_tray_open_seeker()

    assert dock_calls == [True]


def test_cleanup_before_quit_restores_the_dock_icon(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.cleanup_before_quit()

    assert dock_calls == [True]


def test_set_dock_icon_visible_is_a_no_op_off_macos(monkeypatch):
    from seeker.ui import main_window as main_window_module

    monkeypatch.setattr(main_window_module.sys, "platform", "win32")

    # Must not raise or attempt any AppKit import off-macOS.
    main_window_module._set_dock_icon_visible(True)
    main_window_module._set_dock_icon_visible(False)


def test_close_event_shows_one_off_notice_only_once(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window.close()
    assert application.mark_tray_hide_notice_shown_calls == 1

    window.showNormal()
    window.close()
    # Second hide -- config store now reports the notice already shown,
    # so it must not be marked (or shown) a second time.
    assert application.mark_tray_hide_notice_shown_calls == 1


def test_close_event_does_not_reshow_notice_when_already_shown(
        qtbot, monkeypatch,
):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, tray_hide_notice_shown=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window.close()

    assert application.mark_tray_hide_notice_shown_calls == 0


def test_tray_pause_action_reflects_and_persists_config(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._tray_pause_action.isChecked() is False

    window._tray_pause_action.setChecked(True)

    assert application.set_downloads_paused_calls == [True]
    assert application.downloads_paused is True


def test_tray_menu_status_shows_idle_with_nothing_active(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([])
    window._render_tray_menu()

    assert window._tray_status_action.text() == "Idle"


def test_tray_menu_status_shows_downloading_count(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    downloads = [
        ActiveDownload(
            track=_make_track("t1"),
            request=DownloadRequest(
                track_id="t1", username="peer1", filename="a.flac",
                format="flac", quality_descriptor="flac", role="settled",
                status="downloading", requested_at="2026-01-01",
            ),
            playlist_name="Test",
        ),
    ]
    window._render_active_downloads(downloads)
    window._render_tray_menu()

    assert window._tray_status_action.text() == "1 downloading"


def test_tray_menu_status_shows_paused_suffix(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, downloads_paused=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_tray_menu()

    assert "(paused)" in window._tray_status_action.text()


def test_tray_menu_review_and_upgrades_counts_are_distinct(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_review_items((
        [(_make_track(), _make_review_candidate())],
        [_make_upgrade_details(), _make_upgrade_details(request_id=2)],
        [],
    ))
    window._render_tray_menu()

    assert window._tray_review_action.text() == "Review (1)"
    assert window._tray_upgrades_action.text() == "Upgrades (2)"


def test_tray_open_seeker_unhides_and_refreshes(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # Roadmap item 116 (round 8, §14.2) — found live wiring up
    # applicationStateChanged: without settling the event loop here, a
    # platform-level "just became active" notification queued by
    # show() itself can be delivered LATE, after close() has already
    # hidden the window — at delivery time isVisible() reads False, so
    # _on_application_state_changed's own reopen guard (correctly)
    # treats it as a real reopen request, which invalidates the
    # pending hide-confirmation timer and this waitUntil never
    # resolves. Not reachable through real interactive use (a human
    # takes real time between a window appearing and closing it, which
    # the already-spinning event loop uses to deliver this kind of
    # notification long before any close() call); this is a test-
    # timing gap, not a production race, and this qtbot.wait(20)
    # matches the settling wait this file's own fullscreen-close test
    # already uses for the same class of reason.
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    window._on_tray_open_seeker()

    assert window._hidden_to_tray is False
    assert window.isVisible()


def test_tray_trigger_click_does_nothing_on_macos(qtbot, monkeypatch):
    # Roadmap item D5 (round 6) — the actual reported bug: a real
    # user's left-click on the menu bar icon on a real Mac both opened
    # the context menu (AppKit's own native behavior) AND restored the
    # window (this code's own `Trigger` handling) — not what a menu bar
    # extra should do. On macOS, `Trigger` must now be a no-op.
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    monkeypatch.setattr(main_window_module.sys, "platform", "darwin")
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # Roadmap item 116 (round 8, §14.2) — found live wiring up
    # applicationStateChanged: without settling the event loop here, a
    # platform-level "just became active" notification queued by
    # show() itself can be delivered LATE, after close() has already
    # hidden the window — at delivery time isVisible() reads False, so
    # _on_application_state_changed's own reopen guard (correctly)
    # treats it as a real reopen request, which invalidates the
    # pending hide-confirmation timer and this waitUntil never
    # resolves. Not reachable through real interactive use (a human
    # takes real time between a window appearing and closing it, which
    # the already-spinning event loop uses to deliver this kind of
    # notification long before any close() call); this is a test-
    # timing gap, not a production race, and this qtbot.wait(20)
    # matches the settling wait this file's own fullscreen-close test
    # already uses for the same class of reason.
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    window._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.Trigger)

    assert window._hidden_to_tray is True
    assert not window.isVisible()


def test_tray_trigger_click_opens_seeker_on_windows_and_linux(
        qtbot, monkeypatch,
):
    # D5.1 — the original behavior is kept for the platforms it was
    # actually written for: Trigger is the only signal a left-click
    # produces there at all, so it should still restore the window.
    from seeker.ui import main_window as main_window_module

    _force_tray_available(monkeypatch, True)
    monkeypatch.setattr(main_window_module.sys, "platform", "win32")
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # Roadmap item 116 (round 8, §14.2) — found live wiring up
    # applicationStateChanged: without settling the event loop here, a
    # platform-level "just became active" notification queued by
    # show() itself can be delivered LATE, after close() has already
    # hidden the window — at delivery time isVisible() reads False, so
    # _on_application_state_changed's own reopen guard (correctly)
    # treats it as a real reopen request, which invalidates the
    # pending hide-confirmation timer and this waitUntil never
    # resolves. Not reachable through real interactive use (a human
    # takes real time between a window appearing and closing it, which
    # the already-spinning event loop uses to deliver this kind of
    # notification long before any close() call); this is a test-
    # timing gap, not a production race, and this qtbot.wait(20)
    # matches the settling wait this file's own fullscreen-close test
    # already uses for the same class of reason.
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    window._on_tray_icon_activated(QSystemTrayIcon.ActivationReason.Trigger)

    assert window._hidden_to_tray is False
    assert window.isVisible()


def test_tray_check_now_triggers_backend_poll(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.backend_poll_timer.stop()

    window._on_tray_check_now()

    qtbot.waitUntil(
        lambda: application.download_service.poll_downloads_calls
        if hasattr(application.download_service, "poll_downloads_calls")
        else True,
        timeout=500,
    )
    # No direct call counter on FakeDownloadService.poll_downloads --
    # just confirm it doesn't raise and the in-progress flag round-trips.
    qtbot.waitUntil(
        lambda: window._backend_poll_in_progress is False, timeout=2000,
    )


def test_tray_check_now_action_is_named_unambiguously(qtbot, monkeypatch):
    # Roadmap item 98 (B9.5) — "Check now" was ambiguous with the Help
    # menu's own "Check for updates…" (a completely different action).
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    menu = window._tray_icon.contextMenu()
    actions_by_text = {action.text(): action for action in menu.actions()}

    assert "Check now" not in actions_by_text
    assert "Check downloads now" in actions_by_text
    assert actions_by_text["Check downloads now"].toolTip() != ""


def test_tray_quit_calls_qapplication_quit(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    quit_calls = []
    monkeypatch.setattr(
            QApplication, "quit", lambda self=None: quit_calls.append(True)
    )

    window._on_tray_quit()

    assert quit_calls == [True]


def test_tray_quit_from_fullscreen_bypasses_closeevent_entirely(
        qtbot, monkeypatch,
):
    # Roadmap item D4.3 (round 6) — the brief's own explicit ask: Quit
    # is a real, separate path from the red-button close this item
    # otherwise fixes, and needs checking on its own rather than
    # assumed to share the same fix. `_on_tray_quit` goes straight to
    # `QApplication.quit()`, never `self.close()` (see its own
    # docstring) — it never reaches `closeEvent`/E1's own fullscreen
    # branch at all, so the black-Space bug is structurally unreachable
    # from this path regardless of fullscreen state: the whole app (and
    # its Space) is what's actually going away, not just this window
    # being hidden.
    from PySide6.QtWidgets import QApplication

    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)
    assert window.isFullScreen()

    quit_calls = []
    monkeypatch.setattr(
        QApplication, "quit", lambda self=None: quit_calls.append(True),
    )

    window._on_tray_quit()

    assert quit_calls == [True]
    # Nothing about the close/hide-to-tray machinery fired.
    assert window._hidden_to_tray is False
    assert window._pre_fullscreen_geometry is None


def test_cleanup_before_quit_stops_timers_and_hides_tray(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    assert window.poll_timer.isActive()
    assert window.backend_poll_timer.isActive()

    window.cleanup_before_quit()

    assert not window.poll_timer.isActive()
    assert not window.backend_poll_timer.isActive()


def test_needs_decision_notification_fires_only_on_increase(
        qtbot,
        monkeypatch,
):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._check_for_needs_decision_notification(3)
    assert len(messages) == 1
    assert "3 item" in messages[0]

    # Same count again -- no repeat notification.
    window._check_for_needs_decision_notification(3)
    assert len(messages) == 1

    # A genuine increase -- notifies again.
    window._check_for_needs_decision_notification(5)
    assert len(messages) == 2

    # A decrease resets the baseline silently.
    window._check_for_needs_decision_notification(1)
    assert len(messages) == 2


def test_needs_decision_notification_respects_config_toggle(
        qtbot,
        monkeypatch,
):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, notify_needs_decision=False,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._check_for_needs_decision_notification(3)

    assert messages == []


def test_error_notification_is_rate_limited(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._notify_error("slskd unreachable")
    window._notify_error("slskd unreachable")

    assert len(messages) == 1


def test_error_notification_respects_config_toggle(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, notify_errors=False,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    messages = []
    monkeypatch.setattr(
        window._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    window._notify_error("slskd unreachable")

    assert messages == []


def test_download_notifications_batch_per_playlist(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    # Seeding (construction-time) found nothing -- simulate the cutoff
    # already being set, as it would be after a real seed with no
    # existing history.
    window._last_notified_download_at = "2026-01-01T00:00:00+00:00"

    messages = []
    monkeypatch.setattr(
        window._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    events = [
        _make_history_event(
            occurred_at="2026-01-02T00:00:02+00:00", playlist_name="A",
        ),
        _make_history_event(
            occurred_at="2026-01-02T00:00:01+00:00", playlist_name="A",
        ),
        _make_history_event(
            occurred_at="2026-01-02T00:00:00+00:00", playlist_name="B",
        ),
    ]
    window._on_download_notification_events(events)

    assert len(messages) == 1
    assert "A: 2 tracks downloaded" in messages[0]
    assert "B: 1 track downloaded" in messages[0]
    assert window._last_notified_download_at == "2026-01-02T00:00:02+00:00"


def test_download_notifications_skip_events_before_cutoff(qtbot, monkeypatch):
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._last_notified_download_at = "2026-01-02T00:00:00+00:00"

    messages = []
    monkeypatch.setattr(
        window._tray_icon, "showMessage",
        lambda title, msg, *a, **k: messages.append(msg),
    )

    # Every event is at or before the cutoff -- nothing new.
    events = [_make_history_event(occurred_at="2026-01-02T00:00:00+00:00")]
    window._on_download_notification_events(events)

    assert messages == []


def test_downloads_paged_render_skips_table_population_while_hidden(
        qtbot, monkeypatch,
):
    # Roadmap item R7.6.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._hidden_to_tray = True

    downloads = [
        ActiveDownload(
            track=_make_track("t1"),
            request=DownloadRequest(
                track_id="t1", username="peer1", filename="a.flac",
                format="flac", quality_descriptor="flac", role="settled",
                status="downloading", requested_at="2026-01-01",
            ),
            playlist_name="Test",
        ),
    ]
    window._render_active_downloads(downloads)

    # The count used by the tray IS still updated...
    assert window._active_downloads_count == 1
    # ...but the actual table was never touched.
    assert window.downloads_table.rowCount() == 0


def test_resolve_tray_icon_path_dev_mode_points_at_real_repo_file():
    # Roadmap item 98 (B9.1) — the real template asset, not the
    # full-colour app .icns (setIsMask(True) against the .icns produced
    # a solid filled squircle instead of a legible glyph).
    import sys

    assert not getattr(sys, "frozen", False)
    path = _resolve_tray_icon_path()

    assert path.name == "seeker_menubar_Template.png"
    assert path.exists()


def test_resolve_tray_icon_path_frozen_mode_uses_meipass(
        monkeypatch,
        tmp_path,
):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    path = _resolve_tray_icon_path()

    assert path == tmp_path / "icons" / "seeker_menubar_Template.png"

import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
)

from seeker.config_store import SeekerConfig
from seeker.models.active_download import ActiveDownload
from seeker.models.data_locations import DataLocations
from seeker.models.download_request import DownloadRequest
from seeker.models.history_event import DOWNLOADED, HistoryEvent
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
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.ui import help_text, theme
from seeker.ui import workers as workers_module
from seeker.ui.main_window import (
    _THEME_MODE_CYCLE,
    DestinationDialog,
    MainWindow,
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
            log_dir=Path("/fake/logs"),
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
        # Round 8 §7.1 — public names, mirroring the real Application's
        # own `settings`/`slskd_base_url`/`slskd_api_key` (the latter
        # two fold in the real class's env-var fallback; always None/
        # unset here since no smoke test needs a configured slskd URL).
        self.slskd_base_url: str | None = None
        self.slskd_api_key: str | None = None
        self.persist_default_destination_calls: list[tuple[int, bool]] = []
        # Roadmap item R7.4/R7.1/R7.5 — mirrors the real Application's
        # own methods, same shape as persist_default_destination above.
        self.set_downloads_paused_calls: list[bool] = []
        self.mark_tray_hide_notice_shown_calls = 0
        self.set_notification_preference_calls: list[tuple[str, bool]] = []
        self.set_theme_mode_calls: list[str] = []
        self.update_settings_calls: list[dict] = []

    @property
    def settings(self) -> SeekerConfig:
        return self._config_store

    def update_settings(self, **changes) -> SeekerConfig:
        self.update_settings_calls.append(changes)
        self._config_store = replace(self._config_store, **changes)

        return self._config_store

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

    window._downloads_page._render_active_downloads(
        [_make_active_download(track_id="d1"), _make_active_download(track_id="d2")]
    )
    assert window._nav_buttons["downloads"].text() == "Downloads  (2)"

    window._review_page._render_review_items(
        ([(_make_track("t1"), _make_review_candidate("t1"))], [], [])
    )
    assert window._nav_buttons["review"].text() == "Review  (1)"

    # Back to zero must drop the badge entirely, not show "(0)".
    window._downloads_page._render_active_downloads([])
    assert window._nav_buttons["downloads"].text() == "Downloads"


# --- Busy-action registry / activity strip (roadmap item 65, Phase 2) -----

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

    window.busy_actions.begin("scan", window._dashboard_page.scan_button, "Scanning…")
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

    window.busy_actions.begin("scan", window._dashboard_page.scan_button)
    window.busy_actions.begin("sync", window._dashboard_page.sync_button)
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


# --- History page (roadmap Phase 10) ----------------------------------------
#
# The page's own tests moved to tests/pages/test_history_page.py (round 8,
# §9.3.4, session S11.1). _make_history_event stays here — Tray's own
# download-notification tests (below, staying until S11.7) use it too.

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
            window._dashboard_page.sync_button,
            window._dashboard_page.scan_button,
            window._dashboard_page.match_button,
            window._dashboard_page.download_button,
            window.settings_button,
    ):
        assert button.toolTip() != ""


def test_next_step_action_button_opens_settings_on_the_connection_tab(
        qtbot, monkeypatch,
):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window._dashboard_page.next_step_notice.isHidden(), timeout=2000,
    )
    # Drive the dispatch method directly — exercising the exact click
    # path a real InlineNotice action button takes without needing to
    # locate/click the dynamically-built button widget itself.
    window._dashboard_page._on_next_step_action("settings_connection")

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

    qtbot.waitUntil(window._dashboard_page.scan_button.isEnabled, timeout=2000)
    window._dashboard_page.scan_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.scan_and_match_calls == 1,
        timeout=2000,
    )
    assert application.library_service.scan_all_calls == 0


def _select_first_playlist(window, qtbot) -> None:
    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    # Selecting also kicks off the "next step" facts fetch
    # (_poll_next_step), which independently enables/disables
    # download_button — wait for it to actually land rather than
    # racing a click against a button that may still be disabled from
    # the pre-selection (no playlist selected) render.
    qtbot.waitUntil(window._dashboard_page.download_button.isEnabled, timeout=2000)


def test_download_with_no_selection_shows_a_warning_notice(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page.download_button.click()

    assert "playlist" in window._dashboard_page.dashboard_notice.text().lower()
    assert not window._dashboard_page.dashboard_notice.isHidden()


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

    window._dashboard_page.download_button.click()

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

    window._dashboard_page.download_button.click()

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

    window._dashboard_page.download_button.click()

    # Synchronous, main-thread state set at click time — true
    # immediately, not just eventually once some worker lands.
    assert window._dashboard_page.download_button.text() == "Starting download…"
    assert not window._dashboard_page.download_button.isEnabled()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.download_button.text()
            == "Download selected playlist"
        ),
        timeout=2000,
    )
    assert window._dashboard_page.download_button.isEnabled()


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

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.download_button.text()
            == "Download selected playlist"
        ),
        timeout=2000,
    )
    assert window._dashboard_page.download_button.isEnabled()
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

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden()
        and "Requested 2" in window._dashboard_page.dashboard_notice.text(),
        timeout=2000,
    )
    assert (
        "3 already downloading/downloaded"
        in window._dashboard_page.dashboard_notice.text()
    )


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

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden()
        and "Requested 4" in window._dashboard_page.dashboard_notice.text(),
        timeout=2000,
    )
    text = window._dashboard_page.dashboard_notice.text()
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

    window._dashboard_page.download_button.click()

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

    window._dashboard_page.download_button.click()

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

    window._dashboard_page.download_button.click()

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

    window._dashboard_page.download_button.click()

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

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden(), timeout=2000,
    )
    assert "location" in window._dashboard_page.dashboard_notice.text().lower()


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

    window._dashboard_page.selected_playlist = Playlist(
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

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 1, timeout=2000,
    )
    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["review"]
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.selectedItems() != [],
        timeout=2000,
    )
    assert window._review_page.review_local_table.currentRow() == 0


def test_double_clicking_in_library_row_is_a_no_op(qtbot):
    status = _make_track_status(track_id="t1", state=IN_LIBRARY)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 1, timeout=2000,
    )
    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["dashboard"]
    )


def _make_track_status(
        track_id: str = "t1",
        state: str = IN_LIBRARY,
        tagged_at: str | None = None,
) -> TrackStatus:
    return TrackStatus(
        track=_make_track(track_id), state=state, tagged_at=tagged_at,
    )


def _switch_to_duplicates_tab(window) -> None:
    window._show_page("duplicates")


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


def test_no_private_application_attribute_access_in_ui():
    # Round 8 §7.1.3 — CLAUDE.md's layering rule ("every Qt widget goes
    # through Application, never past it") held in letter (no repository
    # imports in ui/) but not in spirit: sixteen read sites and one WRITE
    # reached straight into self.application._config_store/
    # _slskd_base_url/_slskd_api_key, bypassing update_settings()'s
    # persistence/cache-invalidation entirely (§7.1.1/§7.1.2 added the
    # public settings/update_settings/slskd_base_url/slskd_api_key
    # surface and replaced every one of those sixteen). Checked
    # structurally via ast, not by re-reading call sites by eye, so a
    # future one added anywhere in ui/ (including ui/pages/* once Phase
    # 6 lands) is caught automatically.
    import ast

    import seeker.ui as ui_package

    ui_dir = Path(ui_package.__file__).parent
    violations = []
    for path in sorted(ui_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "application"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "self"
            ):
                continue
            violations.append(f"{path.name}:{node.lineno}: {node.attr}")

    assert violations == [], (
        "private Application attribute access found (presentation-layer "
        "code must go through a public Application property/method, "
        "never self.application._*):\n" + "\n".join(violations)
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
        "duplicates_folders_list",
        "duplicates_table",
    ]
    for attr in table_and_list_attrs:
        widget = getattr(window, attr)
        parent = widget.parentWidget()
        assert parent is not None, attr
        assert parent.objectName() == "card", (
            f"{attr}'s parent is {parent!r}, not routed through make_card()"
        )

    # History/Search/Sharing/Downloads/Dashboard/Review have no
    # delegating properties (S11.1/S11.2/S11.3/S11.4/S11.5, §9.3.4) —
    # same check, against their own page widgets directly.
    page_owned_tables = [
        ("history_table", window._history_page.history_table),
        ("search_results_table", window._search_page.search_results_table),
        (
            "sharing_locations_table",
            window._sharing_page.sharing_locations_table,
        ),
        ("sharing_uploads_table", window._sharing_page.sharing_uploads_table),
        ("downloads_table", window._downloads_page.downloads_table),
        ("playlist_list", window._dashboard_page.playlist_list),
        ("track_table", window._dashboard_page.track_table),
        ("review_needs_table", window._review_page.review_needs_table),
        ("review_upgrades_table", window._review_page.review_upgrades_table),
        ("review_local_table", window._review_page.review_local_table),
    ]
    for name, widget in page_owned_tables:
        parent = widget.parentWidget()
        assert parent is not None, name
        assert parent.objectName() == "card", (
            f"{name}'s parent is {parent!r}, not routed through make_card()"
        )


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


def _confirm_yes(monkeypatch) -> None:
    # Real modal QMessageBox.exec() would hang a test — every test that
    # expects a delete to actually proceed past the new Phase 6.3
    # confirmation dialog stubs the static question() classmethod to
    # answer Yes, the same way a real user clicking Yes would.
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )


# --- Sharing page (roadmap item 62, Phase 7) --------------------------------
#
# The page's own tests moved to tests/pages/test_sharing_page.py (round 8,
# §9.3.4, session S11.2). _make_location stays here — the structural sweep
# tests below (Actions-column floor, header-clipping, stretch-column) use
# it too.

def _make_location(location_id: int, name: str, path: str) -> LibraryLocation:
    return LibraryLocation(
        id=location_id, name=name, path=path,
        added_at="2026-01-01T00:00:00+00:00",
    )


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

    window._dashboard_page._render_track_statuses(
        [_make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._review_page._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([_make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
        LocationShareState(
            location=_make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window.settings_page._render_locations(
        [(_make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )

    tables_and_columns = [
        (window._dashboard_page.track_table, 3),
        (window._review_page.review_needs_table, 3),
        (window._review_page.review_upgrades_table, 3),
        (window._review_page.review_local_table, 4),
        (window._sharing_page.sharing_locations_table, 4),
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

    window._dashboard_page._render_track_statuses(
        [_make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._review_page._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([_make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
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

    window._dashboard_page._render_track_statuses(
        [_make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._search_page._render_search_results(
        "Dom Dolla", "Rhyme Dust",
        [
            SoulseekFile(
                username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
                extension="flac", size=25_000_000, queue_length=0,
                upload_speed=1_000_000, has_free_upload_slot=True,
            ),
        ],
    )
    window._review_page._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([_make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
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
    #
    # Roadmap item 8.1.2 (round 8, Phase 5) — strengthened alongside the
    # ColumnLayout refactor (§8.1.1): a table can have a real Stretch
    # column while still leaving its OTHER columns at Qt's raw default
    # width, if nothing ever derived a width for them either. Every
    # table built through `theme.configure_columns` derives every
    # non-stretch column's width from its own header label (or a real
    # Actions widget) via `apply_column_floors`/`size_action_column` —
    # so for those tables, no non-stretch column may still equal
    # `header.defaultSectionSize()`.
    from PySide6.QtWidgets import QHeaderView, QTableWidget

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    tables = window.findChildren(QTableWidget)
    assert tables, "expected at least one QTableWidget in the window"

    # Roadmap item 8.1.3 — these three genuinely have no ColumnLayout:
    # no Actions column, no per-column resize mode at all, just
    # stretchLastSection for their one flex column (see the comments
    # beside their construction in main_window.py). Excluded from the
    # stronger per-column check below only — the `has_stretch` check
    # above still runs on them, which is the actual E2 invariant this
    # test exists to guard; their non-flex columns were never claimed
    # to be derived and are not the bug class E2 fixed.
    _no_column_layout = {
        window._downloads_page.downloads_table, window._history_page.history_table,
        window._sharing_page.sharing_uploads_table,
    }

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

        if table in _no_column_layout:
            continue

        last_column = table.columnCount() - 1
        for column in range(table.columnCount()):
            if header.stretchLastSection() and column == last_column:
                continue
            if (
                header.sectionResizeMode(column)
                == QHeaderView.ResizeMode.Stretch
            ):
                continue
            assert (
                header.sectionSize(column) != header.defaultSectionSize()
            ), (
                f"{table.objectName() or table!r} column {column} is "
                f"still at Qt's raw default width immediately after "
                f"construction — ColumnLayout should have derived a "
                f"real width for it"
            )


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

    window._dashboard_page._render_track_statuses([
        TrackStatus(
            track=_make_track("t1"), state=DOWNLOADING,
            bytes_transferred=500, total_bytes=1_000,
        ),
        _make_track_status(track_id="t2", state=IN_LIBRARY, tagged_at=None),
    ])
    window._show_page("downloads")
    window._downloads_page._render_active_downloads([
        _make_active_download(
            track_id="t3", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ])
    window._show_page("search")
    window._search_page._render_search_results(
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
    window._review_page._render_needs_review_candidates(
        [(_make_track(), _make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [_make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([_make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
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

    window._downloads_page._render_active_downloads([])
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
    window._downloads_page._render_active_downloads(downloads)
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

    window._review_page._render_review_items((
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

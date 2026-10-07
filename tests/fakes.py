"""Fakes for `Application` and its services, plus the builders and
monkeypatch helpers more than one UI test module shares.

Every page test, the shell tests and `tools/screenshots.py`
build a `MainWindow` or a page over `FakeApplication`.
"""
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QMessageBox,
    QSystemTrayIcon,
)

from seeker.config_store import SeekerConfig
from seeker.models.active_download import ActiveDownload
from seeker.models.data_locations import DataLocations
from seeker.models.download_request import DownloadRequest
from seeker.models.download_result import (
    ManualDownloadResult,
    PlaylistDownloadResult,
    PollResult,
)
from seeker.models.fingerprint_result import FingerprintResult
from seeker.models.history_event import DOWNLOADED, HistoryEvent
from seeker.models.library_location import LibraryLocation
from seeker.models.library_result import (
    MatchResult,
    ScanAndMatchResult,
    ScanResult,
)
from seeker.models.local_file import LocalFile
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.playlist import Playlist, PlaylistSummary
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.spotify_sync import PlaylistRefreshResult, TrackSyncResult
from seeker.models.tag_result import FixArtResult, TagResult
from seeker.models.track import Track
from seeker.models.track_status import (
    IN_LIBRARY,
    MISSING_STATES,
    TrackStatus,
)
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.soulseek.sharing_service import ShareStatus
from seeker.ui import plain_text


class FakeSyncService:
    def __init__(
            self,
            playlists: list[Playlist] | None = None,
            art_urls_filled: int = 0,
    ):
        self._playlists = playlists or []
        self.sync_playlists_calls = 0
        self.sync_playlist_tracks_calls: list[Playlist] = []
        self.track_sync_result = TrackSyncResult(
            tracks_saved=0, art_urls_filled=art_urls_filled,
        )
        self.refresh_playlists_calls = 0
        self.refresh_progress: Callable[[str, int, int], None] | None = None
        self.refresh_result = PlaylistRefreshResult(
            playlist_count=len(self._playlists), updated_playlist_names=[],
        )
        self.refresh_error: Exception | None = None

    def list_playlists(self) -> list[Playlist]:
        return self._playlists

    def sync_playlists(self) -> None:
        self.sync_playlists_calls += 1

    def refresh_playlists(
            self,
            progress: Callable[[str, int, int], None] | None = None,
    ) -> PlaylistRefreshResult:
        self.refresh_playlists_calls += 1
        self.refresh_progress = progress

        if self.refresh_error is not None:
            raise self.refresh_error

        return self.refresh_result

    def sync_playlist_tracks(self, playlist: Playlist) -> TrackSyncResult:
        self.sync_playlist_tracks_calls.append(playlist)
        return self.track_sync_result


class FakeDashboardService:
    def __init__(
            self,
            statuses: list | None = None,
            active_downloads: list | None = None,
            playlists: list[Playlist] | None = None,
    ):
        self._statuses = statuses if statuses is not None else []
        self._playlists = playlists or []
        self._active_downloads = active_downloads or []
        self.calls: list[str] = []
        self.clear_finished_calls = 0

    def get_playlist_track_status(self, playlist_name: str) -> list:
        self.calls.append(playlist_name)
        return self._statuses

    def get_playlist_summaries(self) -> list[PlaylistSummary]:
        # Every loaded playlist has the same statuses here.
        return [
            PlaylistSummary(playlist, playlist.track_count, None)
            if playlist.tracks_snapshot_id is None
            else PlaylistSummary(
                playlist,
                len(self._statuses),
                sum(
                    1 for status in self._statuses
                    if status.state in MISSING_STATES
                ),
            )
            for playlist in self._playlists
        ]

    def get_active_downloads(self) -> list:
        return self._active_downloads

    def clear_finished_downloads(self) -> int:
        self.clear_finished_calls += 1
        finished = [
            download for download in self._active_downloads
            if download.request.status
            in ("completed", "failed", "unavailable")
        ]
        for download in finished:
            self._active_downloads.remove(download)
        return len(finished)


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

    def scan_and_match(self) -> ScanAndMatchResult:
        self.scan_and_match_calls += 1
        return ScanAndMatchResult(scan=ScanResult(), match=MatchResult())

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

    def find_nested_locations(self) -> list:
        return []

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
        self._fingerprint_result = fingerprint_result or FingerprintResult(
            computed=0, skipped_already_computed=0, failed=0,
            details=[],
        )
        self._groups = groups or []
        self._find_error: Exception | None = None
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
        if self._find_error is not None:
            raise self._find_error
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
    def match_all(self) -> MatchResult:
        return MatchResult()


class FakeHistoryService:
    def __init__(self, events: list | None = None):
        self._events = events or []
        self.get_recent_events_calls = 0
        # §4 (round 10) — lets a test force the exact CI-only timing
        # window deterministically instead of relying on luck: when
        # set, a call whose `limit` equals `_block_when_limit` blocks on
        # the worker thread until the test releases `_block_event`, so
        # the call counter can be observed at its target value while
        # on_finished has provably not yet run on the main thread.
        # Keyed on `limit`, not call order/number — MainWindow's own
        # startup seed call (tray.py, limit=1) and a page's real fetch
        # (default limit) are two separate QThreadPool tasks with no
        # ordering guarantee between them. Confirmed live: keying on
        # call number instead left a worker permanently blocked
        # whenever the seed call happened to land second, hanging the
        # whole process at teardown (MainWindow.thread_pool blocks its
        # own destructor on any in-flight runnable, HISTORY §125). See
        # test_history_page.py.
        self._block_event: threading.Event | None = None
        self._block_when_limit: int | None = None
        # Raised by a page's own fetch (any limit but the tray's seed).
        self._error: Exception | None = None

    def get_recent_events(self, limit: int = 50) -> list:
        self.get_recent_events_calls += 1
        if limit == self._block_when_limit:
            assert self._block_event is not None
            self._block_event.wait()
        if self._error is not None and limit != 1:
            raise self._error
        return self._events


class FakeSharingService:
    def __init__(
            self,
            status: ShareStatus | None = None,
            self_managed: bool = True,
            reconciliation: list | None = None,
            uploads: list | None = None,
    ):
        self._status = status or ShareStatus(
            ready=True, scanning=False, scan_pending=False, faulted=False,
            directories=0, files=0, shares=[],
        )
        self._self_managed = self_managed
        self._reconciliation = reconciliation or []
        self._uploads = uploads or []
        self.add_location_to_share_calls: list = []

    def get_status(self):
        return self._status

    def is_self_managed(self) -> bool:
        return self._self_managed

    def get_reconciliation(self, status) -> list:
        return self._reconciliation

    def get_uploads(self) -> list:
        return self._uploads

    def preview_add_location(self, location):
        from seeker.soulseek.sharing_service import SharingPlan

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

        from seeker.soulseek.sharing_service import SharingApplyResult

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


class FakeReviewService:
    def __init__(
            self,
            review_candidates: list | None = None,
            pending_upgrades: list | None = None,
            confirm_review_candidate_error: Exception | None = None,
    ):
        self._review_candidates = review_candidates or []
        self._pending_upgrades = pending_upgrades or []
        self._confirm_review_candidate_error = confirm_review_candidate_error
        self.confirm_review_candidate_calls: list[str] = []
        self.reject_review_candidate_calls: list[str] = []
        # Proves a re-poll (poll_review_items, called from
        # on_finished) has actually run, rather than asserting on a
        # notice's text/visibility immediately after a click, which
        # would pass whether or not anything happened yet.
        self.get_pending_upgrade_reviews_calls = 0
        self.apply_upgrade_decision_calls: list[tuple[int, bool, bool]] = []
        self.apply_upgrade_decision_result: str | None = (
                "Replaced with /new/path"
        )
        self.apply_upgrade_decisions_batch_calls: list[
            tuple[list[int], bool]
        ] = []
        from seeker.soulseek.review_service import BulkUpgradeReplaceResult
        self.apply_upgrade_decisions_batch_result = BulkUpgradeReplaceResult(
            replaced=0, failed=0, details=[],
        )

    def get_review_candidates(self) -> list:
        return self._review_candidates

    def get_pending_upgrade_reviews(self) -> list:
        self.get_pending_upgrade_reviews_calls += 1
        return self._pending_upgrades

    def confirm_review_candidate(self, track_id: str) -> None:
        if self._confirm_review_candidate_error is not None:
            raise self._confirm_review_candidate_error

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


class FakeDownloadService:
    def __init__(
            self,
            resolved_destination: tuple | None = None,
            download_playlist_result: PlaylistDownloadResult | None = None,
            search_manual_results: list | None = None,
            download_manual_result: ManualDownloadResult | None = None,
            download_manual_error: Exception | None = None,
    ):
        # Roadmap item 82 (P13) — manual (not-from-Spotify) search/
        # download.
        self._search_manual_results = search_manual_results or []
        self._download_manual_result = download_manual_result or ManualDownloadResult(
            track_id="manual:fake", requested=False, settled=False,
            reason="no_candidate_found",
        )
        self._download_manual_error = download_manual_error
        self._search_manual_error: Exception | None = None
        self.search_manual_calls: list[tuple[str, str]] = []
        self.download_manual_calls: list[tuple] = []
        # None means "no resolvable destination" — the roadmap item 6
        # §3 dead-end case the DestinationDialog exists to close.
        self._resolved_destination = resolved_destination
        self.set_destination_calls: list[tuple[str, str, str | None]] = []
        self.download_playlist_calls: list[str] = []
        self._download_playlist_result = (
            download_playlist_result or PlaylistDownloadResult()
        )

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

    def download_playlist(self, playlist_name: str) -> PlaylistDownloadResult:
        self.download_playlist_calls.append(playlist_name)
        return self._download_playlist_result

    def poll_downloads(self) -> PollResult:
        return PollResult()

    def search_manual(self, artist: str, title: str) -> list:
        self.search_manual_calls.append((artist, title))
        if self._search_manual_error is not None:
            raise self._search_manual_error
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


class FakeMetadataService:
    def __init__(
            self,
            tag_result: dict | None = None,
            fix_art_result: dict | None = None,
            rename_plans: list | None = None,
            rename_result=None,
    ):
        self._tag_result = tag_result or TagResult()
        self._fix_art_result = fix_art_result or FixArtResult()
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
            download_playlist_result: PlaylistDownloadResult | None = None,
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
            statuses, active_downloads, playlists,
        )
        self.library_service = FakeLibraryService(
            locations, has_scanned_library, needs_review_matches,
        )
        self.spotify_configured = spotify_configured
        self.track_matcher = FakeTrackMatcher()
        self.download_service = FakeDownloadService(
            resolved_destination, download_playlist_result,
        )
        self.review_service = FakeReviewService(
            review_candidates, pending_upgrades,
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
        self.restart_slskd_calls = 0
        self.restart_slskd_error: Exception | None = None
        self.set_theme_mode_calls: list[str] = []
        self.update_settings_calls: list[dict] = []
        # Round 9 §3.2 — mirrors the real Application's login_item_*
        # surface. Defaults to "unsupported," the real behavior off a
        # packaged macOS build, so existing tests that never touch this
        # see the same inert state a real dev-run Application would.
        self.login_item_supported = False
        self.set_login_item_enabled_calls: list[bool] = []

    @property
    def settings(self) -> SeekerConfig:
        return self._config_store

    def update_settings(self, **changes) -> SeekerConfig:
        self.update_settings_calls.append(changes)
        self._config_store = replace(self._config_store, **changes)

        return self._config_store

    def login_item_status(self):
        from seeker.login_item import LoginItemStatus

        return LoginItemStatus.NOT_SUPPORTED

    def set_login_item_enabled(self, enabled: bool):
        from seeker.login_item import LoginItemStatus

        self.set_login_item_enabled_calls.append(enabled)

        return LoginItemStatus.NOT_SUPPORTED

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

    def restart_slskd(self):
        self.restart_slskd_calls += 1
        if self.restart_slskd_error is not None:
            raise self.restart_slskd_error

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


def make_history_event(
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


def make_active_download(
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


def make_track(track_id: str = "t1") -> Track:
    return Track(
        id=track_id, title="Title", artist="Artist", album="Album",
        duration_ms=200_000,
    )


def make_review_candidate(
        track_id: str = "t1",
        score: float = 73.2,
        runner_up_username: str | None = None,
        runner_up_filename: str | None = None,
        runner_up_score: float | None = None,
) -> SoulseekReviewCandidate:
    return SoulseekReviewCandidate(
        track_id=track_id,
        username="peer1",
        filename="Artist - Title (Original Mix).flac",
        score=score,
        quality_descriptor="flac",
        found_at="2026-01-01T00:00:00+00:00",
        size=1_000_000,
        runner_up_username=runner_up_username,
        runner_up_filename=runner_up_filename,
        runner_up_score=runner_up_score,
    )


def make_upgrade_details(
        request_id: int = 1,
        old_file_path: str | None = "/music/old.mp3",
) -> UpgradeReviewDetails:
    return UpgradeReviewDetails(
        request_id=request_id,
        track=make_track(),
        quality_descriptor="flac 1000kbps",
        current_description="mp3",
        old_file_path=old_file_path,
    )


def make_needs_review_match(track_id: str = "t1") -> NeedsReviewMatch:
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


def make_track_status(
        track_id: str = "t1",
        state: str = IN_LIBRARY,
        tagged_at: str | None = None,
        has_art: bool | None = None,
        album_art_url: str | None = None,
) -> TrackStatus:
    track = make_track(track_id)
    track.album_art_url = album_art_url
    return TrackStatus(
        track=track, state=state, tagged_at=tagged_at, has_art=has_art,
    )


def make_duplicate_group():
    from seeker.audio.quality import LocalFileQuality
    from seeker.library.duplicate_service import DuplicateFile, DuplicateGroup

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


def confirm_yes(monkeypatch) -> None:
    # Real modal QMessageBox.exec() would hang a test — every test that
    # expects a delete to actually proceed past the new Phase 6.3
    # confirmation dialog stubs the static question() classmethod to
    # answer Yes, the same way a real user clicking Yes would.
    monkeypatch.setattr(
        plain_text, "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )


def make_location(location_id: int, name: str, path: str) -> LibraryLocation:
    return LibraryLocation(
        id=location_id, name=name, path=path,
        added_at="2026-01-01T00:00:00+00:00",
    )


def force_tray_available(monkeypatch, available: bool) -> None:
    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", lambda: available,
    )


def wait_for_workers(window) -> None:
    """Blocks until every worker the window started has returned.

    Use before asserting that a click called nothing: straight after
    the click, such an assertion passes even when a worker is about to
    make the call. Events are deliberately not processed, so a result
    dialog a wrongly started worker would open cannot block the test.
    """
    assert window.thread_pool.waitForDone(2000)

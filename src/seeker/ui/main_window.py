from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.models.active_download import ActiveDownload
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
from seeker.ui.workers import run_worker

NeedsReviewCandidates = list[tuple[Track, SoulseekReviewCandidate]]
PendingUpgrades = list[UpgradeReviewDetails]


# Untuned constant — matches the ~2s cadence already observed against
# real slskd elsewhere in this project (see CLAUDE.md); revisit once
# real usage data exists, same convention as every other threshold here.
POLL_INTERVAL_MS = 2_000

# Untuned constant — this timer makes real network calls to slskd (via
# poll_downloads()), so it deliberately runs far less often than the
# local-DB-only display refresh above. 15-30s starting range per the
# task brief; revisit once real usage data exists.
BACKEND_POLL_INTERVAL_MS = 20_000

_STATE_LABELS = {
    IN_LIBRARY: "In library",
    DOWNLOADING: "Downloading",
    AWAITING_REVIEW: "Awaiting review",
    NEEDS_REVIEW: "Needs review",
    NOT_FOUND: "Not found",
}

# Plain-language notes for statuses that aren't self-explanatory as raw
# text — a "locked" or "shortlisted" row is still actively being chased,
# just not in a way a non-technical status string conveys.
_DOWNLOAD_STATUS_LABELS = {
    "queued": "Queued",
    "downloading": "Downloading",
    "locked": "Retrying (locked)",
    "shortlisted": "Queued as backup",
    "ready_for_review": "Ready for review",
    "completed": "Completed",
    "failed": "Failed",
}

# Statuses where a progress bar means anything at all — a locked/
# shortlisted/failed row has no real, current transfer to show progress
# for (see CLAUDE.md: a rejection leaves bytes_transferred/total_bytes
# unset by design, not zeroed).
_PROGRESS_ELIGIBLE_STATUSES = {"queued", "downloading", "ready_for_review", "completed"}


def _build_progress_widget(download: ActiveDownload) -> QWidget:
    request = download.request

    if request.status not in _PROGRESS_ELIGIBLE_STATUSES:
        return QWidget()

    bar = QProgressBar()

    if request.total_bytes and request.bytes_transferred is not None:
        bar.setRange(0, request.total_bytes)
        bar.setValue(request.bytes_transferred)
    else:
        # No bytes reported yet — indeterminate ("busy") rather than a
        # 0%-forever bar that looks identical to actually being stuck.
        bar.setRange(0, 0)

    return bar


class MainWindow(QMainWindow):
    def __init__(self, application: Application):
        super().__init__()
        self.application = application
        self.thread_pool = QThreadPool()
        self.selected_playlist: Playlist | None = None
        self._backend_poll_in_progress = False
        # Maps track_table row -> TrackStatus, rebuilt on every render —
        # needed to resolve a multi-selection back to real track ids for
        # "Tag selected" (Step 7).
        self._current_track_statuses: list[TrackStatus] = []

        self.setWindowTitle("Seeker")
        self.resize(1000, 600)

        self._build_ui()
        self._load_playlists()
        self._poll_active_downloads()
        self._poll_review_items()

        # DB-polling pattern for live status: rebuild the visible model
        # each tick rather than diffing for minimal repaints — an
        # acceptable v1 simplification, matching this project's habit
        # of shipping a working real version before optimizing. Applies
        # to the Review tab too: a checkbox toggled mid-interval can get
        # reset by the next tick's rebuild, same accepted tradeoff as
        # everywhere else this pattern is used.
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll_selected_playlist)
        self.poll_timer.timeout.connect(self._poll_active_downloads)
        self.poll_timer.timeout.connect(self._poll_review_items)
        self.poll_timer.start()

        # Separate, slower timer: the only thing in this app that causes
        # poll_downloads() (real slskd network calls) to run without an
        # explicit `seeker downloads status` invocation. poll_downloads()
        # was built with exactly this kind of unattended calling in mind
        # (no input() anywhere — see CLAUDE.md's guardrail tests), so
        # this is safe to fire on a bare timer with no user interaction.
        self.backend_poll_timer = QTimer(self)
        self.backend_poll_timer.setInterval(BACKEND_POLL_INTERVAL_MS)
        self.backend_poll_timer.timeout.connect(self._trigger_backend_poll)
        self.backend_poll_timer.start()

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)

        self.playlist_list = QListWidget()
        self.playlist_list.currentItemChanged.connect(
            self._on_playlist_selected
        )
        layout.addWidget(self.playlist_list, 1)

        right = QVBoxLayout()

        self.track_table = QTableWidget(0, 4)
        self.track_table.setHorizontalHeaderLabels(
            ["Track", "Status", "Progress", "Actions"]
        )
        self.track_table.horizontalHeader().setStretchLastSection(True)
        # Multi-select needed for "Tag selected" (Step 7) — rows, not
        # cells, and extended (ctrl/shift-click) rather than the Qt
        # default of single-row selection.
        self.track_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        right.addWidget(self.track_table)

        self.empty_state_label = QLabel(
            "No cached tracks for this playlist yet."
        )
        self.empty_state_label.hide()
        right.addWidget(self.empty_state_label)

        self.sync_tracks_button = QPushButton("Sync tracks")
        self.sync_tracks_button.clicked.connect(
            self._on_sync_tracks_clicked
        )
        self.sync_tracks_button.hide()
        right.addWidget(self.sync_tracks_button)

        right.addLayout(self._build_tagging_controls())

        self.tagging_results = QPlainTextEdit()
        self.tagging_results.setReadOnly(True)
        self.tagging_results.setMaximumHeight(120)
        self.tagging_results.setPlaceholderText(
            "Tagging results will appear here."
        )
        right.addWidget(self.tagging_results)

        self.status_label = QLabel("")
        right.addWidget(self.status_label)

        layout.addLayout(right, 3)

        self.downloads_table = QTableWidget(0, 5)
        self.downloads_table.setHorizontalHeaderLabels(
            ["Track", "Playlist", "Role", "Status", "Progress"]
        )
        self.downloads_table.horizontalHeader().setStretchLastSection(True)

        review_tab = self._build_review_tab()

        tabs = QTabWidget()
        tabs.addTab(central, "Dashboard")
        tabs.addTab(self.downloads_table, "Downloads")
        tabs.addTab(review_tab, "Review")

        self.setCentralWidget(tabs)

        toolbar = QToolBar("Actions")
        self.addToolBar(toolbar)

        # Sync/Scan/Match are deliberately labeled as global actions —
        # same scope as the CLI (all playlists / all locations / all
        # cached tracks) — so selecting a playlist in the sidebar
        # doesn't imply these narrow to it. Only Download is scoped.
        self.sync_button = QPushButton("Sync all playlists")
        self.sync_button.clicked.connect(self._on_sync_clicked)
        toolbar.addWidget(self.sync_button)

        self.scan_button = QPushButton("Scan all locations")
        self.scan_button.clicked.connect(self._on_scan_clicked)
        toolbar.addWidget(self.scan_button)

        self.match_button = QPushButton("Match all tracks")
        self.match_button.clicked.connect(self._on_match_clicked)
        toolbar.addWidget(self.match_button)

        self.download_button = QPushButton("Download selected playlist")
        self.download_button.clicked.connect(self._on_download_clicked)
        toolbar.addWidget(self.download_button)

    def _build_tagging_controls(self) -> QHBoxLayout:
        # Shared by all three triggers (per-track, "Tag selected",
        # "Tag playlist") — one set of options, not three independently
        # configurable copies. --bpm-range requiring --analyze-audio
        # (the CLI's own validation) is enforced structurally here by
        # hiding the range fields entirely while the checkbox is
        # unchecked, rather than validating the combination after the
        # fact the way the CLI has to.
        controls = QHBoxLayout()

        self.analyze_audio_checkbox = QCheckBox("Analyze audio (BPM/Key)")
        self.analyze_audio_checkbox.toggled.connect(
            self._on_analyze_audio_toggled
        )
        controls.addWidget(self.analyze_audio_checkbox)

        self.bpm_min_edit = QLineEdit()
        self.bpm_min_edit.setPlaceholderText("Min BPM")
        self.bpm_min_edit.hide()
        controls.addWidget(self.bpm_min_edit)

        self.bpm_max_edit = QLineEdit()
        self.bpm_max_edit.setPlaceholderText("Max BPM")
        self.bpm_max_edit.hide()
        controls.addWidget(self.bpm_max_edit)

        self.tag_selected_button = QPushButton("Tag selected")
        self.tag_selected_button.clicked.connect(
            self._on_tag_selected_clicked
        )
        controls.addWidget(self.tag_selected_button)

        self.tag_playlist_button = QPushButton("Tag playlist")
        self.tag_playlist_button.clicked.connect(
            self._on_tag_playlist_clicked
        )
        controls.addWidget(self.tag_playlist_button)

        return controls

    def _on_analyze_audio_toggled(self, checked: bool) -> None:
        self.bpm_min_edit.setVisible(checked)
        self.bpm_max_edit.setVisible(checked)

    def _resolve_tag_options(self) -> tuple[bool, tuple[float, float] | None]:
        analyze_audio = self.analyze_audio_checkbox.isChecked()

        if not analyze_audio:
            return False, None

        min_text = self.bpm_min_edit.text().strip()
        max_text = self.bpm_max_edit.text().strip()

        if not min_text and not max_text:
            # A range is optional even with analysis on — matches the
            # CLI, where --analyze-audio alone (no --bpm-range) is
            # perfectly valid.
            return True, None

        if not min_text or not max_text:
            raise ValueError(
                "Enter both a min and max BPM, or leave both blank."
            )

        try:
            return True, (float(min_text), float(max_text))
        except ValueError:
            raise ValueError("BPM range must be numeric.")

    def _render_tag_result(self, result: dict[str, Any]) -> None:
        self.status_label.setText("")

        lines = [
            f"Tagged: {result['tagged']}, "
            f"Skipped (no match): {result['skipped_no_match']}, "
            f"Skipped (unsupported format): "
            f"{result['skipped_format_unsupported']}, "
            f"Skipped (already tagged): "
            f"{result['skipped_already_tagged']}, "
            f"Skipped (already analyzed): "
            f"{result['skipped_already_analyzed']}, "
            f"Failed: {result['failed']}."
        ]

        for detail in result["details"]:
            lines.append(f"  [{detail['reason']}] {detail['message']}")

        self.tagging_results.setPlainText("\n".join(lines))

    def _selected_track_ids(self) -> list[str]:
        rows = sorted(
            {index.row() for index in self.track_table.selectionModel().selectedRows()}
        )
        return [self._current_track_statuses[row].track.id for row in rows]

    def _build_track_actions(self, status: TrackStatus) -> QWidget:
        # No button at all outside IN_LIBRARY — tag_tracks would just
        # report skipped_no_match for anything else, so there's nothing
        # real to offer here (same "blank cell, not a misleading
        # control" precedent as the Downloads tab's progress bars).
        if status.state != IN_LIBRARY:
            return QWidget()

        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        tag_button = QPushButton("Tag")
        track_id = status.track.id
        tag_button.clicked.connect(
            lambda: self._on_tag_track_clicked(track_id, tag_button)
        )
        actions_layout.addWidget(tag_button)

        return container

    def _on_tag_track_clicked(self, track_id: str, button: QPushButton) -> None:
        try:
            analyze_audio, bpm_range = self._resolve_tag_options()
        except ValueError as error:
            self.status_label.setText(str(error))
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_tracks(
                [track_id],
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
            ),
            button=button,
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )

    def _on_tag_selected_clicked(self) -> None:
        track_ids = self._selected_track_ids()

        if not track_ids:
            self.status_label.setText("Select at least one track first.")
            return

        try:
            analyze_audio, bpm_range = self._resolve_tag_options()
        except ValueError as error:
            self.status_label.setText(str(error))
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_tracks(
                track_ids,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
            ),
            button=self.tag_selected_button,
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )
        # Analysis in particular does real, potentially slow per-track
        # work — an in-progress note beyond just the disabled button,
        # for anything wider than a single track.
        self.status_label.setText(f"Tagging {len(track_ids)} selected track(s)...")

    def _on_tag_playlist_clicked(self) -> None:
        if self.selected_playlist is None:
            self.status_label.setText("Select a playlist first.")
            return

        try:
            analyze_audio, bpm_range = self._resolve_tag_options()
        except ValueError as error:
            self.status_label.setText(str(error))
            return

        playlist_name = self.selected_playlist.name

        run_worker(
            self.thread_pool,
            lambda: self.application.metadata_service.tag_playlist(
                playlist_name,
                analyze_audio=analyze_audio,
                expected_bpm_range=bpm_range,
            ),
            button=self.tag_playlist_button,
            status_label=self.status_label,
            on_finished=self._render_tag_result,
        )
        self.status_label.setText(f"Tagging playlist '{playlist_name}'...")

    def _build_review_tab(self) -> QWidget:
        # Two independent sections, per item 26: SoulSeek needs-review
        # candidates (item 17's tier, gaining its first real
        # confirm/reject action here) and Phase 2 upgrade confirmations
        # (item 8's ready_for_review flow, previously CLI-only via
        # `seeker downloads review`). Both are driven by DownloadService
        # methods that were built explicit-decision and input()-free
        # specifically so a UI could call them directly — see CLAUDE.md
        # item 26 §0/§1.
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("SoulSeek candidates needing confirmation"))

        self.review_needs_table = QTableWidget(0, 4)
        self.review_needs_table.setHorizontalHeaderLabels(
            ["Track", "Score", "Candidate", "Actions"]
        )
        self.review_needs_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.review_needs_table)

        layout.addWidget(QLabel("Downloaded upgrades ready for review"))

        self.review_upgrades_table = QTableWidget(0, 4)
        self.review_upgrades_table.setHorizontalHeaderLabels(
            ["Track", "Current", "New quality", "Actions"]
        )
        self.review_upgrades_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.review_upgrades_table)

        return tab

    def _load_playlists(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.sync_service.list_playlists,
            status_label=self.status_label,
            on_finished=self._populate_playlists,
        )

    def _populate_playlists(self, playlists: list[Playlist]) -> None:
        self.playlist_list.clear()

        for playlist in playlists:
            item = QListWidgetItem(
                f"{playlist.name} ({playlist.track_count} tracks)"
            )
            item.setData(Qt.ItemDataRole.UserRole, playlist)
            self.playlist_list.addItem(item)

    def _on_playlist_selected(
            self,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        self.selected_playlist = (
            current.data(Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        self._poll_selected_playlist()

    def _poll_selected_playlist(self) -> None:
        if self.selected_playlist is None:
            return

        playlist_name = self.selected_playlist.name

        run_worker(
            self.thread_pool,
            lambda: self.application.dashboard_service
            .get_playlist_track_status(playlist_name),
            status_label=self.status_label,
            on_finished=self._render_track_statuses,
        )

    def _render_track_statuses(self, statuses: list[TrackStatus]) -> None:
        self._current_track_statuses = statuses

        if not statuses:
            self.track_table.setRowCount(0)
            self.empty_state_label.show()
            # Explicit, user-triggered sync only — never auto-fetched on
            # selection, since track syncing was deliberately split out
            # from playlist syncing to keep Spotify API calls scoped
            # and intentional (roadmap item 1).
            self.sync_tracks_button.show()
            return

        self.empty_state_label.hide()
        self.sync_tracks_button.hide()

        self.track_table.setRowCount(len(statuses))

        for row, status in enumerate(statuses):
            label = f"{status.track.artist} - {status.track.title}"
            self.track_table.setItem(row, 0, QTableWidgetItem(label))

            state_text = _STATE_LABELS[status.state]
            if status.soulseek_candidate is not None:
                state_text += " (SoulSeek candidate found)"
            self.track_table.setItem(row, 1, QTableWidgetItem(state_text))

            if (
                    status.state == DOWNLOADING
                    and status.total_bytes
                    and status.bytes_transferred is not None
            ):
                progress = QProgressBar()
                progress.setMaximum(status.total_bytes)
                progress.setValue(status.bytes_transferred)
                self.track_table.setCellWidget(row, 2, progress)
            else:
                self.track_table.setCellWidget(row, 2, QWidget())

            self.track_table.setCellWidget(
                row, 3, self._build_track_actions(status),
            )

    def _poll_active_downloads(self) -> None:
        # Purely observational — a cheap local DB read via
        # DashboardService.get_active_downloads(), GLOBAL across every
        # playlist (unlike _poll_selected_playlist above). No
        # confirm/reject action lives here; that's a separate future
        # Review screen.
        run_worker(
            self.thread_pool,
            self.application.dashboard_service.get_active_downloads,
            on_finished=self._render_active_downloads,
        )

    def _render_active_downloads(self, downloads: list[ActiveDownload]) -> None:
        self.downloads_table.setRowCount(len(downloads))

        for row, download in enumerate(downloads):
            track = download.track
            label = f"{track.artist} - {track.title}"
            self.downloads_table.setItem(row, 0, QTableWidgetItem(label))
            self.downloads_table.setItem(
                row, 1, QTableWidgetItem(download.playlist_name),
            )
            self.downloads_table.setItem(
                row, 2, QTableWidgetItem(download.request.role.capitalize()),
            )

            status = download.request.status
            status_text = _DOWNLOAD_STATUS_LABELS.get(status, status)
            self.downloads_table.setItem(row, 3, QTableWidgetItem(status_text))

            self.downloads_table.setCellWidget(
                row, 4, _build_progress_widget(download),
            )

    def _poll_review_items(self) -> None:
        # Both halves are cheap, local-DB-only reads (like
        # get_active_downloads above) — no real slskd network calls, so
        # this belongs on the 2s display-refresh timer, not the 20s
        # backend-poll one. Bundled into one worker call rather than two
        # so both tables update from the same consistent DB snapshot.
        def fetch() -> tuple[NeedsReviewCandidates, PendingUpgrades]:
            service = self.application.download_service
            return (service.get_review_candidates(), service.get_pending_upgrade_reviews())

        run_worker(
            self.thread_pool,
            fetch,
            on_finished=self._render_review_items,
        )

    def _render_review_items(
            self,
            data: tuple[NeedsReviewCandidates, PendingUpgrades],
    ) -> None:
        candidates, upgrades = data
        self._render_needs_review_candidates(candidates)
        self._render_pending_upgrades(upgrades)

    def _render_needs_review_candidates(
            self,
            candidates: NeedsReviewCandidates,
    ) -> None:
        self.review_needs_table.setRowCount(len(candidates))

        for row, (track, candidate) in enumerate(candidates):
            label = f"{track.artist} - {track.title}"
            self.review_needs_table.setItem(row, 0, QTableWidgetItem(label))
            self.review_needs_table.setItem(
                row, 1, QTableWidgetItem(f"{candidate.score:.1f}"),
            )

            candidate_text = f"{candidate.quality_descriptor} — {candidate.username}"
            self.review_needs_table.setItem(
                row, 2, QTableWidgetItem(candidate_text),
            )

            self.review_needs_table.setCellWidget(
                row, 3, self._build_needs_review_actions(track.id),
            )

    def _build_needs_review_actions(self, track_id: str) -> QWidget:
        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        confirm_button = QPushButton("Confirm")
        reject_button = QPushButton("Reject")

        confirm_button.clicked.connect(
            lambda: self._on_confirm_review_candidate(track_id, confirm_button)
        )
        reject_button.clicked.connect(
            lambda: self._on_reject_review_candidate(track_id, reject_button)
        )

        actions_layout.addWidget(confirm_button)
        actions_layout.addWidget(reject_button)

        return container

    def _on_confirm_review_candidate(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        # confirm_review_candidate makes a real request_download() call
        # (network) — routed through the worker pool like every other
        # long-running action, never called directly on the main thread.
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.confirm_review_candidate(
                track_id
            ),
            button=button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_review_items(),
        )

    def _on_reject_review_candidate(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.reject_review_candidate(
                track_id
            ),
            button=button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_review_items(),
        )

    def _render_pending_upgrades(self, upgrades: PendingUpgrades) -> None:
        self.review_upgrades_table.setRowCount(len(upgrades))

        for row, details in enumerate(upgrades):
            label = f"{details.track.artist} - {details.track.title}"
            self.review_upgrades_table.setItem(row, 0, QTableWidgetItem(label))
            self.review_upgrades_table.setItem(
                row, 1, QTableWidgetItem(details.current_description),
            )
            self.review_upgrades_table.setItem(
                row, 2, QTableWidgetItem(details.quality_descriptor or "—"),
            )
            self.review_upgrades_table.setCellWidget(
                row, 3, self._build_upgrade_actions(details),
            )

    def _build_upgrade_actions(self, details: UpgradeReviewDetails) -> QWidget:
        container = QWidget()
        actions_layout = QHBoxLayout(container)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        replace_button = QPushButton("Replace")
        decline_button = QPushButton("Decline")

        # The "delete old file?" control only ever appears when there's
        # a real old file to delete — mirrors the CLI's own guard around
        # its second input() prompt (get_upgrade_review_details leaves
        # old_file_path unset when there's nothing to replace).
        delete_checkbox: QCheckBox | None = None
        if details.old_file_path is not None:
            delete_checkbox = QCheckBox("Delete old file")
            actions_layout.addWidget(delete_checkbox)

        def on_replace() -> None:
            delete_old = delete_checkbox is not None and delete_checkbox.isChecked()
            self._on_apply_upgrade_decision(
                details.request_id, True, delete_old, replace_button,
            )

        def on_decline() -> None:
            # A true no-op per apply_upgrade_decision's own contract —
            # the row stays ready_for_review and is offered again next
            # poll, identical to declining the CLI's prompt.
            self._on_apply_upgrade_decision(
                details.request_id, False, False, decline_button,
            )

        replace_button.clicked.connect(on_replace)
        decline_button.clicked.connect(on_decline)

        actions_layout.addWidget(replace_button)
        actions_layout.addWidget(decline_button)

        return container

    def _on_apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool,
            button: QPushButton,
    ) -> None:
        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.apply_upgrade_decision(
                request_id, replace, delete_old,
            ),
            button=button,
            on_finished=self._on_upgrade_decision_finished,
        )

    def _on_upgrade_decision_finished(self, message: str | None) -> None:
        # apply_upgrade_decision returns None for a decline (no-op, no
        # message needed) and a short status string for a real replace —
        # run_worker's own status_label wiring only fires on error, so
        # the success message is surfaced here instead.
        if message is not None:
            self.status_label.setText(message)

        self._poll_review_items()

    def _trigger_backend_poll(self) -> None:
        if self._backend_poll_in_progress:
            # A previous poll_downloads() call (real slskd network
            # calls) is still running — a slow or hanging response must
            # not cause a second, overlapping writer to start on top of
            # it. Skip this tick; the next one will try again.
            return

        if not self.application.soulseek_configured:
            return

        self._backend_poll_in_progress = True

        def clear_in_progress(_: object) -> None:
            self._backend_poll_in_progress = False

        run_worker(
            self.thread_pool,
            self.application.download_service.poll_downloads,
            on_finished=clear_in_progress,
            on_error=clear_in_progress,
        )

    def _on_sync_clicked(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.sync_service.sync_playlists,
            button=self.sync_button,
            status_label=self.status_label,
            on_finished=lambda _: self._load_playlists(),
        )

    def _on_scan_clicked(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.scan_all,
            button=self.scan_button,
            status_label=self.status_label,
        )

    def _on_match_clicked(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.track_matcher.match_all,
            button=self.match_button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _on_download_clicked(self) -> None:
        if self.selected_playlist is None:
            self.status_label.setText("Select a playlist first.")
            return

        playlist_name = self.selected_playlist.name

        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.download_playlist(
                playlist_name
            ),
            button=self.download_button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _on_sync_tracks_clicked(self) -> None:
        if self.selected_playlist is None:
            return

        playlist = self.selected_playlist

        def do_sync() -> Any:
            self.application.sync_service.sync_playlist_tracks(playlist)

        run_worker(
            self.thread_pool,
            do_sync,
            button=self.sync_tracks_button,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

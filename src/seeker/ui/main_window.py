from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
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
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    TrackStatus,
)
from seeker.ui.workers import run_worker


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

        self.setWindowTitle("Seeker")
        self.resize(1000, 600)

        self._build_ui()
        self._load_playlists()
        self._poll_active_downloads()

        # DB-polling pattern for live status: rebuild the visible model
        # each tick rather than diffing for minimal repaints — an
        # acceptable v1 simplification, matching this project's habit
        # of shipping a working real version before optimizing.
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._poll_selected_playlist)
        self.poll_timer.timeout.connect(self._poll_active_downloads)
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

        self.track_table = QTableWidget(0, 3)
        self.track_table.setHorizontalHeaderLabels(
            ["Track", "Status", "Progress"]
        )
        self.track_table.horizontalHeader().setStretchLastSection(True)
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

        self.status_label = QLabel("")
        right.addWidget(self.status_label)

        layout.addLayout(right, 3)

        self.downloads_table = QTableWidget(0, 5)
        self.downloads_table.setHorizontalHeaderLabels(
            ["Track", "Playlist", "Role", "Status", "Progress"]
        )
        self.downloads_table.horizontalHeader().setStretchLastSection(True)

        tabs = QTabWidget()
        tabs.addTab(central, "Dashboard")
        tabs.addTab(self.downloads_table, "Downloads")

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

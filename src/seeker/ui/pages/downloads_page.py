"""The Downloads page (HISTORY §119)."""

from datetime import UTC, datetime

from PySide6.QtWidgets import (
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.ui import help_text, theme
from seeker.ui.download_eta import (
    AGGREGATE_ETA_TOOLTIP,
    DownloadEtaTracker,
    format_aggregate_header,
)
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.workers import run_worker

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
    # Exhausted its retry budget against this specific peer; distinct
    # from "Failed" so it reads as "we gave up chasing this one," not
    # "something errored" (HISTORY §66).
    "unavailable": "Unavailable (gave up retrying)",
}

# Statuses where a progress bar means anything at all — a locked/
# shortlisted row has no real, current transfer to show progress for
# (a rejection leaves bytes_transferred/total_bytes unset by design,
# not zeroed). "failed" is deliberately absent too — it gets its own
# terminal branch below, not this one.
_PROGRESS_ELIGIBLE_STATUSES = {"queued", "downloading"}

# A row in any of these will never report new progress again. Branched
# on BEFORE ever consulting the ETA tracker, which is the actual fix
# for "a finished download reads as Stalled" (HISTORY §56 Phase 5.4):
# the tracker has no concept of "this row is done," so feeding it more
# identical-bytes samples from a completed/failed/ready_for_review row
# eventually looks exactly like a genuinely stuck in-progress download
# to it. 'unavailable' is the same kind of terminal state as 'failed'.
_DOWNLOAD_TERMINAL_STATUSES = {
    "completed", "failed", "ready_for_review", "unavailable",
}


def _build_terminal_progress_widget(request: DownloadRequest) -> QWidget:
    # A fixed label, never the ETA tracker, for a row that will never
    # report new progress again (HISTORY §56 Phase 5.4). 'unavailable'
    # gets the same blank treatment as 'failed' — a full bar would
    # misleadingly read as "completed" for something that never
    # actually succeeded.
    if request.status in ("failed", "unavailable"):
        return QWidget()  # blank, not a misleading full/empty bar

    bar = QProgressBar()

    if request.total_bytes and request.bytes_transferred is not None:
        bar.setRange(0, request.total_bytes)
        bar.setValue(request.bytes_transferred)
    else:
        # A completed/ready_for_review row should always have real
        # bytes (HISTORY §20), but render a full bar rather than
        # crash/guess if a real one somehow doesn't.
        bar.setRange(0, 1)
        bar.setValue(1)

    theme.style_determinate_progress_bar(bar)

    label_text = _DOWNLOAD_STATUS_LABELS.get(request.status, request.status)

    return theme.wrap_progress_bar(bar, label_text)


def _build_progress_widget(
        download: ActiveDownload,
        eta_text: str | None,
) -> QWidget:
    request = download.request

    if request.status in _DOWNLOAD_TERMINAL_STATUSES:
        return _build_terminal_progress_widget(request)

    if request.status not in _PROGRESS_ELIGIBLE_STATUSES:
        return QWidget()

    bar = QProgressBar()

    if not (request.total_bytes and request.bytes_transferred is not None):
        # No bytes reported yet — indeterminate ("busy") rather than a
        # 0%-forever bar that looks identical to actually being stuck.
        # No ETA either: there's nothing determinate to estimate
        # against. Wrapped in the same container shape as the
        # determinate branch below, not returned bare: a bare bar gets
        # clamped to the top of the cell (HISTORY §96; see
        # theme.wrap_progress_bar's own docstring for why).
        bar.setRange(0, 0)
        return theme.wrap_progress_bar(bar, None)

    bar.setRange(0, request.total_bytes)
    bar.setValue(request.bytes_transferred)
    theme.style_determinate_progress_bar(bar)

    # ETA only ever shown once the bar is determinate (HISTORY §20).
    return theme.wrap_progress_bar(bar, eta_text or "Calculating…")


class DownloadsPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # Speed/ETA estimation for the Downloads tab (HISTORY §20).
        # Purely in-memory, scoped to this window's lifetime — see
        # ui/download_eta.py's own docstring for the sampling contract.
        self._eta_tracker = DownloadEtaTracker()
        # Counts the tray menu's own status line, built from this same
        # fetch (never a third source of truth) — read by MainWindow
        # via a delegating property, same as every other tray count
        # (HISTORY §90).
        self.active_downloads_count = 0

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        # Aggregate remaining-time header (HISTORY §53) — text only,
        # empty (no reserved-but-blank strip) whenever there's nothing
        # active to summarize; see _render_aggregate_eta.
        self.downloads_eta_label = QLabel("")
        # QLabel[badge="muted"] in theme.py.
        self.downloads_eta_label.setProperty("badge", "muted")
        layout.addWidget(self.downloads_eta_label)

        self.downloads_table = QTableWidget(0, 5)
        self.downloads_table.setHorizontalHeaderLabels(
            ["Track", "Playlist", "Role", "Status", "Progress"]
        )
        # Checked against ColumnLayout and left alone (HISTORY §118):
        # this table (and History's, Sharing's uploads table) has no
        # Actions column and no explicit per-column resize mode at all,
        # relying entirely on setStretchLastSection for its one flexible
        # column. There is no `fit_content`/`stretch`/`actions` shape
        # here for a ColumnLayout to declare — folding it in would mean
        # adding a setStretchLastSection(False) call that actively
        # fights the one line this table already uses correctly.
        self.downloads_table.horizontalHeader().setStretchLastSection(True)
        theme.apply_table_defaults(self.downloads_table)
        # This table never sets a per-column resize mode of its own
        # (relies on setStretchLastSection above for Progress), so the
        # floor call belongs right here, once, at construction;
        # `apply_column_floors` skips the stretched last column on its
        # own (HISTORY §110).
        theme.apply_column_floors(self.downloads_table)
        layout.addWidget(theme.make_card(self.downloads_table))

        page = build_page(
            "Downloads", help_text.DOWNLOADS_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _poll_active_downloads(self) -> None:
        # Purely observational — a cheap local DB read via
        # DashboardService.get_active_downloads(), GLOBAL across every
        # playlist (unlike the Dashboard's own selected-playlist poll).
        # No confirm/reject action lives here; that's a separate future
        # Review screen.
        run_worker(
            self._context.thread_pool,
            self._context.application.dashboard_service.get_active_downloads,
            on_finished=self._render_active_downloads,
        )

    def _render_active_downloads(
            self,
            downloads: list[ActiveDownload],
    ) -> None:
        # The tray menu's own status line, built from this same fetch.
        # Counted here (not deferred behind the hidden-window gate
        # below) since the whole point of the tray is a live status
        # while nothing else is visible (HISTORY §90).
        self.active_downloads_count = sum(
            1 for download in downloads
            if download.request.status == "downloading"
        )

        # Re-rendering the table (and the nav badge/ETA header, both
        # visual-only) is pure waste while nobody can see the window;
        # the real backend poll that feeds this data keeps running
        # regardless (see MainWindow's own _trigger_backend_poll,
        # untouched by this check — it lives on a separate timer)
        # (HISTORY §90).
        if self._context.is_hidden_to_tray():
            return

        self._context.update_nav_badge("downloads", len(downloads))
        self.downloads_table.setRowCount(len(downloads))
        self._render_aggregate_eta(downloads)

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

            request = download.request
            is_terminal = status in _DOWNLOAD_TERMINAL_STATUSES

            if is_terminal:
                # Evicted the moment a terminal status is seen, not
                # left to evict_except()'s once-per-poll sweep; the ETA
                # tracker is never consulted for this row at all below
                # (HISTORY §56 Phase 5.4).
                if request.id is not None:
                    self._eta_tracker.evict(request.id)
                eta_text = None
            else:
                eta_text = (
                    self._eta_tracker.describe(
                        request.id, request.total_bytes,
                    )
                    if request.id is not None and request.total_bytes
                    else None
                )

            self.downloads_table.setCellWidget(
                row, 4, _build_progress_widget(download, eta_text),
            )

        # This table's progress-bar cell widgets are real per-row
        # content, same treatment as every table with an Actions column
        # even though this one has none (HISTORY §87, §80's own
        # deliberate scoping — see _build_progress_widget/
        # _build_terminal_progress_widget's bespoke stretch factor).
        self.downloads_table.resizeRowsToContents()

    def _render_aggregate_eta(self, downloads: list[ActiveDownload]) -> None:
        # No reserved-but-blank strip when there's nothing active — the
        # empty string collapses the label to zero height, matching
        # this project's "blank, not a misleading control" precedent
        # (HISTORY §27) rather than showing "0 transferring" forever.
        if not downloads:
            self.downloads_eta_label.setText("")
            self.downloads_eta_label.setToolTip("")
            return

        # A terminal row (completed/failed/ready_for_review, still
        # visible for RECENTLY_FINISHED_WINDOW_SECONDS) has nothing left
        # to estimate; counting it here previously folded it into the
        # header's "queued (no estimate)" figure, which reads as
        # actively waiting rather than already finished (HISTORY §56
        # Phase 5.4).
        pairs = [
            (download.request.id, download.request.total_bytes)
            for download in downloads
            if download.request.id is not None
            and download.request.status not in _DOWNLOAD_TERMINAL_STATUSES
        ]
        result = self._eta_tracker.aggregate(pairs)
        self.downloads_eta_label.setText(format_aggregate_header(result))
        self.downloads_eta_label.setToolTip(AGGREGATE_ETA_TOOLTIP)

    def _sample_download_progress(self) -> None:
        # Feeds DownloadEtaTracker exactly once per real
        # poll_downloads() cycle (this method is only ever called from
        # MainWindow's own _trigger_backend_poll on_finished callback),
        # never from the 2s display-refresh tick — sampling there would
        # just re-diff against the same DB row poll_downloads() hasn't
        # touched yet.
        run_worker(
            self._context.thread_pool,
            self._context.application.dashboard_service.get_active_downloads,
            on_finished=self._record_eta_samples,
        )

    def _record_eta_samples(self, downloads: list[ActiveDownload]) -> None:
        active_request_ids = {
            download.request.id
            for download in downloads
            if download.request.id is not None
        }
        self._eta_tracker.evict_except(active_request_ids)

        now = datetime.now(UTC)
        for download in downloads:
            request = download.request
            if request.id is not None and request.bytes_transferred is not None:
                self._eta_tracker.record(
                        request.id,
                        request.bytes_transferred,
                        now,
                )

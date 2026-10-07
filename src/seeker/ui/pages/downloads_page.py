"""The Downloads page (HISTORY §119)."""

from datetime import UTC, datetime
from enum import IntEnum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import (
    FAILED_OUTCOMES,
    IN_FLIGHT,
    SHOWS_NO_FURTHER_PROGRESS,
    STAMPS_COMPLETED_AT,
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.ui import help_text, theme
from seeker.ui.download_eta import (
    AGGREGATE_ETA_TOOLTIP,
    DownloadEtaTracker,
    format_aggregate_header,
)
from seeker.ui.elided_text import BADGE_ROLE
from seeker.ui.empty_state import EmptyGlyph, EmptyState
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel, plain_tooltip
from seeker.ui.slskd_status import START_SLSKD_TEXT, start_slskd
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.widgets import TwoToneProgressBar
from seeker.ui.workers import run_worker


class _DownloadsColumn(IntEnum):
    TRACK = 0
    PLAYLIST = 1
    STATUS = 2
    PROGRESS = 3


_DOWNLOADS_COLUMN_HEADERS = ["Track", "Playlist", "Status", "Progress"]

_DOWNLOADS_COLUMNS = theme.ColumnLayout(
    stretch=(_DownloadsColumn.TRACK,),
    fit_content=(
        _DownloadsColumn.PLAYLIST, _DownloadsColumn.STATUS,
        _DownloadsColumn.PROGRESS,
    ),
)

# Plain-language notes for statuses that aren't self-explanatory as raw
# text — a "locked" or "shortlisted" row is still actively being chased,
# just not in a way a non-technical status string conveys.
_DOWNLOAD_STATUS_LABELS = {
    DownloadStatus.QUEUED: "Queued",
    DownloadStatus.DOWNLOADING: "Downloading",
    DownloadStatus.LOCKED: "Locked — retrying",
    DownloadStatus.SHORTLISTED: "Queued as backup",
    DownloadStatus.READY_FOR_REVIEW: "Ready for review",
    DownloadStatus.COMPLETED: "Completed",
    DownloadStatus.FAILED: "Failed",
    # Exhausted its retry budget against this specific peer; distinct
    # from "Failed" so it reads as "we gave up chasing this one," not
    # "something errored" (HISTORY §66).
    DownloadStatus.UNAVAILABLE: "Unavailable — stopped retrying",
}

# The words a failure's recorded reason follows in the Status cell
# ("Failed — Timed out").
_FAILURE_STATUS_LABELS = {
    DownloadStatus.FAILED: "Failed",
    DownloadStatus.UNAVAILABLE: "Unavailable",
}


def _status_text(request: DownloadRequest) -> str:
    failure_label = _FAILURE_STATUS_LABELS.get(request.status)

    if failure_label is not None and request.failure_reason:
        return f"{failure_label} — {request.failure_reason}"

    return _DOWNLOAD_STATUS_LABELS.get(request.status, request.status)


def _build_terminal_progress_widget(request: DownloadRequest) -> QWidget:
    # A fixed label, never the ETA tracker, for a row that will never
    # report new progress again (HISTORY §56). 'unavailable' gets the
    # same blank treatment as 'failed' — a full bar would misleadingly
    # read as "completed" for something that never actually succeeded.
    if request.status in FAILED_OUTCOMES:
        return QWidget()  # blank, not a misleading full/empty bar

    bar = TwoToneProgressBar()

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


def _progress_sort_key(request: DownloadRequest) -> float:
    # Mirrors _build_progress_widget's own branching so the sort order
    # matches what the bar actually shows.
    if request.status in FAILED_OUTCOMES:
        # No real transfer to rank — same "sorts below everything
        # real" sentinel as a Dashboard row with no active transfer.
        return -1.0

    if request.total_bytes and request.bytes_transferred is not None:
        return request.bytes_transferred / request.total_bytes

    if request.status in SHOWS_NO_FURTHER_PROGRESS:
        # completed/ready_for_review with no real bytes recorded
        # (HISTORY §20 says this shouldn't happen) — rendered as a
        # full bar, so it sorts as done.
        return 1.0

    # queued/downloading with no bytes reported yet — indeterminate.
    return 0.0


def _build_progress_widget(
        download: ActiveDownload,
        eta_text: str | None,
) -> QWidget:
    request = download.request

    # Branched on BEFORE ever consulting the ETA tracker, which is the
    # actual fix for "a finished download reads as Stalled"
    # (HISTORY §56): the tracker has no concept of "this row is done,"
    # so feeding it more identical-bytes samples from a finished row
    # eventually looks exactly like a genuinely stuck download to it.
    if request.status in SHOWS_NO_FURTHER_PROGRESS:
        return _build_terminal_progress_widget(request)

    # A locked/shortlisted row has no current transfer to show progress
    # for (a rejection leaves bytes_transferred/total_bytes unset by
    # design, not zeroed).
    if request.status not in IN_FLIGHT:
        return QWidget()

    bar = TwoToneProgressBar()

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

        # Persistent while the backend poll can't reach slskd; shown
        # and cleared by SlskdStatus.changed, never by this page.
        self.outage_notice = InlineNotice()
        layout.addWidget(self.outage_notice)
        # Start slskd's outcome, when started from this page.
        self.notice = InlineNotice()
        layout.addWidget(self.notice)
        self.status_label = PlainLabel("")
        layout.addWidget(self.status_label)
        self.feedback = FeedbackTarget(self.status_label, self.notice)
        self._context.slskd_status.changed.connect(self._render_outage)
        self._render_outage()

        # Aggregate remaining-time header (HISTORY §53) — text only,
        # empty (no reserved-but-blank strip) whenever there's nothing
        # active to summarize; see _render_aggregate_eta.
        self.downloads_eta_label = PlainLabel("")
        # QLabel[badge="muted"] in theme.py.
        self.downloads_eta_label.setProperty("badge", "muted")

        self.clear_finished_button = QPushButton("Clear finished")
        self.clear_finished_button.setToolTip(
            help_text.TOOLTIP_DOWNLOADS_CLEAR_FINISHED
        )
        self.clear_finished_button.setEnabled(False)
        self.clear_finished_button.clicked.connect(self._clear_finished)

        header_row = QHBoxLayout()
        header_row.addWidget(self.downloads_eta_label)
        header_row.addStretch()
        header_row.addWidget(self.clear_finished_button)
        layout.addLayout(header_row)

        self.downloads_table = QTableWidget(0, len(_DOWNLOADS_COLUMN_HEADERS))
        self.downloads_table.setHorizontalHeaderLabels(
            _DOWNLOADS_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.downloads_table)
        theme.configure_columns(self.downloads_table, _DOWNLOADS_COLUMNS)
        layout.addWidget(theme.make_card(self.downloads_table))
        self.downloads_empty_action = QPushButton(
            help_text.GO_TO_DASHBOARD_TEXT
        )
        self.downloads_empty_action.clicked.connect(
            lambda: self._context.navigate("dashboard")
        )
        self.downloads_empty = EmptyState(
            self.downloads_table, EmptyGlyph.RECORD, help_text.DOWNLOADS_EMPTY,
            action=self.downloads_empty_action,
        )

        page = build_page(
            "Downloads", help_text.DOWNLOADS_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _render_outage(self) -> None:
        message = self._context.slskd_status.unreachable_message

        if message is None:
            self.outage_notice.hide()
            return

        self.outage_notice.show_message(
            message,
            kind="warning",
            action_text=START_SLSKD_TEXT,
            on_action=lambda: start_slskd(
                self._context, self.outage_notice.action_button,
                self.feedback,
            ),
        )

    def poll_active_downloads(self) -> None:
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
            if download.request.status == DownloadStatus.DOWNLOADING
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
        self.clear_finished_button.setEnabled(
            any(
                download.request.status in STAMPS_COMPLETED_AT
                for download in downloads
            )
        )
        self._render_aggregate_eta(downloads)

        # Sorting is live on this table; disabled for the body of this
        # rebuild (see preserving_sort_order's own docstring for why)
        # and restored afterward.
        with preserving_sort_order(self.downloads_table):
            self.downloads_table.setRowCount(len(downloads))

            for row, download in enumerate(downloads):
                track = download.track
                label = f"{track.artist} - {track.title}"
                track_item = QTableWidgetItem(label)
                # Only an upgrade is marked: a plain download is what
                # every other row is.
                if download.request.role == DownloadRole.UPGRADE:
                    track_item.setData(BADGE_ROLE, help_text.UPGRADE_BADGE_TEXT)
                    track_item.setData(
                        Qt.ItemDataRole.AccessibleTextRole,
                        f"{help_text.UPGRADE_BADGE_TEXT}: {label}",
                    )
                self.downloads_table.setItem(
                    row, _DownloadsColumn.TRACK, track_item,
                )
                self.downloads_table.setItem(
                    row, _DownloadsColumn.PLAYLIST,
                    QTableWidgetItem(download.playlist_name),
                )

                request = download.request
                status = request.status
                status_item = QTableWidgetItem(_status_text(request))
                if request.failure_reason:
                    # The cell elides a long reason; the tooltip never
                    # does.
                    status_item.setToolTip(plain_tooltip(status_item.text()))
                self.downloads_table.setItem(
                    row, _DownloadsColumn.STATUS, status_item,
                )

                is_terminal = status in SHOWS_NO_FURTHER_PROGRESS

                if is_terminal:
                    # Evicted the moment a terminal status is seen, not
                    # left to evict_except()'s once-per-poll sweep; the
                    # ETA tracker is never consulted for this row at all
                    # below (HISTORY §56).
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
                    row, _DownloadsColumn.PROGRESS,
                    _build_progress_widget(download, eta_text),
                )
                self.downloads_table.setItem(
                    row, _DownloadsColumn.PROGRESS,
                    SortKeyItem("", _progress_sort_key(request)),
                )

        theme.size_columns(self.downloads_table, _DOWNLOADS_COLUMNS, [])

    def _clear_finished(self) -> None:
        # Not run_worker's button=: it re-enables the button when the
        # clear finishes, after a display-tick render may already have
        # shown the cleared list and disabled it. The render alone owns
        # this button's enabled state.
        self.clear_finished_button.setEnabled(False)
        run_worker(
            self._context.thread_pool,
            self._context.application.dashboard_service
            .clear_finished_downloads,
            on_finished=lambda _cleared: self.poll_active_downloads(),
        )

    def _render_aggregate_eta(self, downloads: list[ActiveDownload]) -> None:
        # No reserved-but-blank strip when there's nothing active — the
        # empty string collapses the label to zero height, matching
        # this project's "blank, not a misleading control" precedent
        # (HISTORY §27) rather than showing "0 transferring" forever.
        if not downloads:
            self.downloads_eta_label.setText("")
            self.downloads_eta_label.setToolTip("")
            return

        # A terminal row (a completed one still inside
        # RECENTLY_FINISHED_WINDOW_SECONDS, a failure not yet cleared,
        # ready_for_review) has nothing left to estimate; counting it
        # here previously folded it into the header's "queued (no
        # estimate)" figure, which reads as actively waiting rather than
        # already finished (HISTORY §56).
        pairs = [
            (download.request.id, download.request.total_bytes)
            for download in downloads
            if download.request.id is not None
            and download.request.status not in SHOWS_NO_FURTHER_PROGRESS
        ]
        result = self._eta_tracker.aggregate(pairs)
        self.downloads_eta_label.setText(format_aggregate_header(result))
        self.downloads_eta_label.setToolTip(AGGREGATE_ETA_TOOLTIP)

    def sample_download_progress(self) -> None:
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

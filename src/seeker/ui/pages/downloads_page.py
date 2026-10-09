"""The Downloads page (HISTORY §119)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from enum import IntEnum

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import (
    FAILED_OUTCOMES,
    PROGRESS_RANK,
    SHOWS_NO_FURTHER_PROGRESS,
    STAMPS_COMPLETED_AT,
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.download_result import TrackSearchOutcome
from seeker.ui import help_text, status_lamp, theme
from seeker.ui.download_eta import (
    AGGREGATE_ETA_TOOLTIP,
    DownloadEtaTracker,
    format_aggregate_header,
)
from seeker.ui.elided_text import (
    BADGE_ROLE,
    SECONDARY_ROLE,
    set_secondary_min_share,
)
from seeker.ui.empty_state import EmptyGlyph, EmptyState
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel, plain_tooltip
from seeker.ui.slskd_status import START_SLSKD_TEXT, start_slskd
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.workers import run_worker


class _DownloadsColumn(IntEnum):
    TRACK = 0
    PLAYLIST = 1
    STATUS = 2
    PROGRESS = 3
    ACTIONS = 4


_DOWNLOADS_COLUMN_HEADERS = [
    "Track", "Playlist", "Status", "Progress", "Actions",
]

_DOWNLOADS_COLUMNS = theme.ColumnLayout(
    stretch=(_DownloadsColumn.TRACK,),
    fit_content=(
        _DownloadsColumn.PLAYLIST, _DownloadsColumn.STATUS,
        _DownloadsColumn.PROGRESS,
    ),
    actions=_DownloadsColumn.ACTIONS,
)

# The busy_actions key of a Retry's search. One searches at a time:
# every Retry button waits while it runs.
RETRY_DOWNLOAD_KEY = "retry_download"
# The busy keys of the Actions column's buttons. The render decides
# each button's enabled state from its key, so the rendered rows carry
# them all.
_ROW_ACTION_KEYS = (RETRY_DOWNLOAD_KEY,)

# A status's label beside its lamp. The words are the Dashboard's where
# the state is the same one ("Retrying"), so a track reads alike on both
# pages.
_DOWNLOAD_STATUS_LABELS = {
    DownloadStatus.QUEUED: "Queued",
    DownloadStatus.DOWNLOADING: "Downloading",
    DownloadStatus.LOCKED: "Retrying",
    DownloadStatus.SHORTLISTED: "Queued as backup",
    DownloadStatus.READY_FOR_REVIEW: "Ready for review",
    DownloadStatus.COMPLETED: "Completed",
    DownloadStatus.FAILED: "Failed",
    DownloadStatus.UNAVAILABLE: "Unavailable",
}

# The quieter note beside a label that does not explain itself. A
# failure's own recorded reason takes its place when there is one.
_DOWNLOAD_STATUS_NOTES = {
    DownloadStatus.LOCKED: "File locked by the peer",
    # Exhausted its retry budget against this peer: "we gave up chasing
    # this one", not "something errored" (HISTORY §66).
    DownloadStatus.UNAVAILABLE: "Stopped retrying",
}


# A meter's ETA before the tracker has two samples to estimate from.
_CALCULATING = "Calculating…"


def _status_note(request: DownloadRequest) -> str | None:
    """The secondary text of a row's Status cell: a failure's reason,
    the percentage of a transfer with real bytes, or a fixed note."""
    if request.status in FAILED_OUTCOMES and request.failure_reason:
        return request.failure_reason

    if (
            request.status == DownloadStatus.DOWNLOADING
            and request.total_bytes
            and request.bytes_transferred is not None
    ):
        return (
            f"{round(100 * request.bytes_transferred / request.total_bytes)}%"
        )

    return _DOWNLOAD_STATUS_NOTES.get(request.status)


def _build_status_item(request: DownloadRequest) -> QTableWidgetItem:
    label = _DOWNLOAD_STATUS_LABELS.get(request.status, request.status)
    # Sorts by progress, not label.
    item = SortKeyItem(label, PROGRESS_RANK[request.status])
    lamp = status_lamp.DOWNLOAD_LAMPS.get(request.status)
    if lamp is not None:
        item.setIcon(status_lamp.lamp_icon(lamp, theme.active_palette()))

    note = _status_note(request)
    if note is not None:
        item.setData(SECONDARY_ROLE, note)
        # The secondary text is painted, not read: say it as well.
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{label}: {note}")
    if request.failure_reason:
        # The cell elides a long reason; the tooltip never does.
        item.setToolTip(plain_tooltip(f"{label} — {note}"))
    return item


def _has_meter(request: DownloadRequest) -> bool:
    """Whether a row's Progress cell is a determinate meter, the one
    cell a progress-only tick updates in place."""
    return (
        request.status == DownloadStatus.DOWNLOADING
        and bool(request.total_bytes)
        and request.bytes_transferred is not None
    )


# A row apart from the bytes that update in place, and whether it has a
# meter to update.
_RowLayout = tuple[ActiveDownload, bool]
# The palette the rows' lamps were drawn in, which row actions were
# running (their buttons' enabled state, by `_ROW_ACTION_KEYS`), and
# each row's layout.
_RenderedRows = tuple[
    theme.Palette, tuple[bool, ...], tuple[_RowLayout, ...],
]


def _row_layout(download: ActiveDownload) -> _RowLayout:
    request = download.request
    if request.status != DownloadStatus.DOWNLOADING:
        return download, False

    return (
        replace(
            download,
            request=replace(request, bytes_transferred=None, total_bytes=None),
        ),
        _has_meter(request),
    )


def _progress_sort_key(request: DownloadRequest) -> float:
    # How far along a row is: finished rows above transfers, transfers
    # by fraction done, failures below everything.
    if request.status in FAILED_OUTCOMES:
        # No real transfer to rank — same "sorts below everything
        # real" sentinel as a Dashboard row with no active transfer.
        return -1.0

    if request.total_bytes and request.bytes_transferred is not None:
        return request.bytes_transferred / request.total_bytes

    if request.status in SHOWS_NO_FURTHER_PROGRESS:
        # completed/ready_for_review with no real bytes recorded
        # (HISTORY §20 says this shouldn't happen): still done.
        return 1.0

    # queued/downloading with no bytes reported yet — indeterminate.
    return 0.0


def _build_progress_widget(
        download: ActiveDownload,
        eta_text: str | None,
) -> QWidget:
    request = download.request

    # Only a transfer has progress to show; every other row's lamp
    # says where it stands. A queued row waits in the peer's queue, and
    # a locked or shortlisted one has no current transfer (a rejection
    # leaves its bytes unset by design, not zeroed). Branched on before
    # the ETA tracker is ever consulted, which has no idea a row is
    # done and would read a finished one's flat bytes as "Stalled"
    # (HISTORY §56).
    if request.status != DownloadStatus.DOWNLOADING:
        return QWidget()

    bar = QProgressBar()
    bar.setFixedWidth(theme.METER_WIDTH)

    if not _has_meter(request):
        # Started, no bytes reported yet: busy, not a 0%-forever meter
        # that looks identical to being stuck. No ETA either: nothing
        # determinate to estimate against. Wrapped like the meter
        # below, not returned bare: a bare bar clamps to the top of the
        # cell (HISTORY §96).
        theme.set_busy_meter(bar)
        return theme.wrap_progress_bar(bar, None)

    # _has_meter's own conditions, for mypy.
    assert request.total_bytes and request.bytes_transferred is not None
    bar.setRange(0, request.total_bytes)
    bar.setValue(request.bytes_transferred)
    theme.style_meter(bar)

    # ETA only ever shown once the bar is determinate (HISTORY §20); the
    # percentage is the Status cell's secondary text.
    return theme.wrap_progress_bar(bar, eta_text or _CALCULATING)


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
        # What the table's rows were last built from; a tick that
        # changes only bytes updates them in place (ui/CLAUDE.md).
        self._rendered_rows: _RenderedRows | None = None
        self._rendered_downloads: list[ActiveDownload] = []
        # The Actions column's buttons, by their busy key.
        self._action_buttons: dict[str, list[QPushButton]] = {}

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

        # The progress line shares the header's row: empty, it would
        # hold a blank line of its own above the table.
        header_row = QHBoxLayout()
        header_row.addWidget(self.downloads_eta_label)
        header_row.addWidget(self.status_label)
        header_row.addStretch()
        header_row.addWidget(self.clear_finished_button)
        layout.addLayout(header_row)

        self.downloads_table = QTableWidget(0, len(_DOWNLOADS_COLUMN_HEADERS))
        self.downloads_table.setHorizontalHeaderLabels(
            _DOWNLOADS_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.downloads_table)
        theme.configure_columns(self.downloads_table, _DOWNLOADS_COLUMNS)
        self.downloads_table.setIconSize(
            QSize(status_lamp.LAMP_SIZE, status_lamp.LAMP_SIZE),
        )
        # A status reads in full; its reason or percentage gives way
        # first, whole on hover.
        set_secondary_min_share(self.downloads_table, 0.0)
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

        # The lamps bake in the palette's colours, so a theme switch
        # must rebuild even when the rows are unchanged.
        rendered: _RenderedRows = (
            theme.active_palette(),
            tuple(
                self._context.busy_actions.is_running(key)
                for key in _ROW_ACTION_KEYS
            ),
            tuple(_row_layout(download) for download in downloads),
        )
        self._rendered_downloads = downloads

        if rendered == self._rendered_rows:
            self._update_progress_in_place()
            return

        self._rebuild_rows(downloads)
        self._rendered_rows = rendered

    def _eta_text(self, request: DownloadRequest) -> str | None:
        if request.id is None or not request.total_bytes:
            return None
        return self._eta_tracker.describe(request.id, request.total_bytes)

    def _rebuild_rows(self, downloads: list[ActiveDownload]) -> None:
        # Sorting is live on this table; disabled for the body of this
        # rebuild (see preserving_sort_order's own docstring for why)
        # and restored afterward.
        action_widgets: list[QWidget] = []
        self._action_buttons = {key: [] for key in _ROW_ACTION_KEYS}
        with preserving_sort_order(self.downloads_table):
            self.downloads_table.setRowCount(len(downloads))

            for row, download in enumerate(downloads):
                track = download.track
                label = f"{track.artist} - {track.title}"
                track_item = QTableWidgetItem(label)
                # The row's anchor into _rendered_downloads, whatever
                # order a sort leaves the rows in.
                track_item.setData(Qt.ItemDataRole.UserRole, row)
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
                self.downloads_table.setItem(
                    row, _DownloadsColumn.STATUS, _build_status_item(request),
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
                    eta_text = self._eta_text(request)

                self.downloads_table.setCellWidget(
                    row, _DownloadsColumn.PROGRESS,
                    _build_progress_widget(download, eta_text),
                )
                self.downloads_table.setItem(
                    row, _DownloadsColumn.PROGRESS,
                    SortKeyItem("", _progress_sort_key(request)),
                )

                actions = self._build_actions(request, label)
                self.downloads_table.setCellWidget(
                    row, _DownloadsColumn.ACTIONS, actions,
                )
                action_widgets.append(actions)

        theme.size_columns(
            self.downloads_table, _DOWNLOADS_COLUMNS, action_widgets,
        )

    def _build_actions(self, request: DownloadRequest, label: str) -> QWidget:
        if request.status not in FAILED_OUTCOMES or request.id is None:
            return QWidget()

        request_id = request.id
        retry_button = self._action_button(
            "Retry", RETRY_DOWNLOAD_KEY,
            lambda: self._retry(request_id, label),
        )
        retry_button.setToolTip(help_text.TOOLTIP_RETRY_DOWNLOAD)
        return theme.cell_widget(retry_button, row_label=label)

    def _action_button(
            self,
            text: str,
            busy_key: str,
            on_click: Callable[[], None],
    ) -> QPushButton:
        button = QPushButton(text)
        # The render owns its enabled state, never a worker's finish
        # handler (ui/CLAUDE.md).
        button.setEnabled(not self._context.busy_actions.is_running(busy_key))
        button.clicked.connect(on_click)
        self._action_buttons[busy_key].append(button)
        return button

    def _disable_action_buttons(self, busy_key: str) -> None:
        for button in self._action_buttons.get(busy_key, []):
            button.setEnabled(False)

    def _update_progress_in_place(self) -> None:
        table = self.downloads_table
        with preserving_sort_order(table):
            for row in range(table.rowCount()):
                anchor = table.item(row, _DownloadsColumn.TRACK)
                assert anchor is not None
                request = self._rendered_downloads[
                    anchor.data(Qt.ItemDataRole.UserRole)
                ].request
                if not _has_meter(request):
                    continue
                # _has_meter's own conditions, for mypy.
                assert (
                    request.total_bytes
                    and request.bytes_transferred is not None
                )

                # The rebuild gave every meter row its meter and ETA
                # label, and an unchanged layout keeps both.
                container = table.cellWidget(row, _DownloadsColumn.PROGRESS)
                assert container is not None
                bar = container.findChild(QProgressBar)
                eta_label = container.findChild(PlainLabel)
                assert bar is not None and eta_label is not None
                bar.setMaximum(request.total_bytes)
                bar.setValue(request.bytes_transferred)
                eta_label.setText(self._eta_text(request) or _CALCULATING)

                # In place, not setItem: ~2.4 ms a call (HISTORY §166).
                # preserving_sort_order re-sorts by the new keys.
                sort_item = table.item(row, _DownloadsColumn.PROGRESS)
                assert isinstance(sort_item, SortKeyItem)
                sort_item.sort_key = _progress_sort_key(request)
                status_item = table.item(row, _DownloadsColumn.STATUS)
                assert status_item is not None
                note = _status_note(request)
                status_item.setData(SECONDARY_ROLE, note)
                status_item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    f"{status_item.text()}: {note}",
                )

    def _retry(self, request_id: int, label: str) -> None:
        # No button= for the busy worker: it would re-enable a button
        # the next rebuild has already deleted. The rendered key holds
        # the busy state, so the render after the search re-enables.
        self._disable_action_buttons(RETRY_DOWNLOAD_KEY)
        self._context.run_busy_worker(
            RETRY_DOWNLOAD_KEY, None,
            lambda: self._context.application.download_service
            .retry_download(request_id),
            on_finished=lambda outcome: self._on_retried(outcome, label),
            on_error=self._on_row_action_failed,
        )

    def _on_retried(self, outcome: TrackSearchOutcome, label: str) -> None:
        self.feedback.show_outcome(
            help_text.retry_outcome_text(outcome, label),
            kind=help_text.RETRY_OUTCOME_KIND[outcome],
        )
        self.poll_active_downloads()

    def _on_row_action_failed(self, message: str) -> None:
        self.feedback.show_error(message)
        self.poll_active_downloads()

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

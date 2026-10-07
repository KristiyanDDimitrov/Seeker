"""The Sharing page (HISTORY §119)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.library_location import LibraryLocation
from seeker.soulseek.sharing_service import (
    LocationShareState,
    ShareStatus,
    SharingApplyResult,
    UploadStatus,
)
from seeker.ui import help_text, plain_text, status_lamp, theme
from seeker.ui.disclosure import Disclosure
from seeker.ui.elided_text import SECONDARY_ROLE
from seeker.ui.empty_state import EmptyGlyph, EmptyState
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel, RichLabel, plain_tooltip
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.upload_eta import UploadEtaTracker
from seeker.ui.workers import run_worker

# The remaining tables (Sharing locations here, Track, Review's three
# tabs) never grew a column IntEnum of their own — their layouts are
# declared the same way, just against plain column indices.
_SHARING_LOCATIONS_COLUMNS = theme.ColumnLayout(
    stretch=(2,), fit_content=(0, 1, 3), actions=4, paths=(2,),
)
_SHARING_UPLOADS_COLUMNS = theme.ColumnLayout(
    stretch=(1,), fit_content=(0, 2, 3), paths=(1,),
)

# The explanation wraps at a reading measure, not the window's width.
_EXPLAINER_MEASURE_CHARS = 80

# slskd's own words for a finished upload that did not succeed.
_UPLOAD_ENDINGS = {
    "Cancelled": "Cancelled",
    "TimedOut": "Timed out",
    "Errored": "Error",
    "Rejected": "Rejected",
    "Aborted": "Aborted",
}


@dataclass(frozen=True)
class _UploadState:
    label: str
    lamp: status_lamp.Lamp | None = None
    note: str | None = None


def _upload_state(raw: str | None) -> _UploadState:
    """Seeker's word and lamp for slskd's transfer state, a flags
    string such as "Queued, Remotely" or "Completed, Succeeded". A
    state it does not know reads as slskd wrote it."""
    if not raw:
        return _UploadState("")
    flags = {flag.strip() for flag in raw.split(",")}
    if "Completed" in flags:
        if "Succeeded" in flags:
            return _UploadState("Sent", status_lamp.PLAY)
        ending = next(
            (_UPLOAD_ENDINGS[flag] for flag in flags if flag in _UPLOAD_ENDINGS),
            None,
        )
        return _UploadState("Failed", status_lamp.FAULT, ending)
    if "InProgress" in flags:
        return _UploadState("Uploading", status_lamp.CUE)
    if flags & {"Queued", "Requested", "Initializing"}:
        return _UploadState("Queued", status_lamp.CUE)
    return _UploadState(raw)


def _lamp_item(
        label: str, lamp: status_lamp.Lamp | None, note: str | None = None,
) -> QTableWidgetItem:
    item = QTableWidgetItem(label)
    if lamp is not None:
        item.setIcon(status_lamp.lamp_icon(lamp, theme.active_palette()))
    if note is not None:
        item.setData(SECONDARY_ROLE, note)
        # The secondary text is painted, not read: say it as well.
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{label}: {note}")
    return item


def _upload_key(upload: UploadStatus) -> tuple[str, str] | None:
    if upload.username is None or upload.filename is None:
        return None
    return (upload.username, upload.filename)


@dataclass
class _SharingSnapshot:
    """Everything the Sharing page (HISTORY §56) needs to
    render one background-thread fetch — bundled the same way
    _NextStepFacts bundles the Dashboard CTA's facts, so run_worker's
    single-callable contract only needs one round trip per refresh
    instead of four (status/self-managed/reconciliation/uploads)."""
    configured: bool
    status: ShareStatus | None
    self_managed: bool
    reconciliation: list[LocationShareState]
    uploads: list[UploadStatus]


class SharingPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # What Seeker is giving back to the SoulSeek network it
        # downloads from (HISTORY §56). See help_text.py's
        # SHARING_FRAMING_BODY for why this page frames things honestly
        # rather than as a persuasive pitch.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_LG)

        # A confirmation ("'X' shared — N directories, M files") goes
        # here, never on sharing_status_label, which _refresh_sharing()
        # (called right after, to pick up the new state) wipes via
        # run_worker's own status_label.setText("") at the top of every
        # call. Persistent, dismissible content belongs on an
        # InlineNotice, not the poll-cleared status label (HISTORY §120;
        # notice.py's own docstring).
        self.sharing_notice = InlineNotice()
        layout.addWidget(self.sharing_notice)

        controls = QHBoxLayout()
        self.sharing_summary_label = PlainLabel("")
        controls.addWidget(self.sharing_summary_label, 1)

        self.sharing_status_label = PlainLabel("")
        controls.addWidget(self.sharing_status_label)
        self.feedback = FeedbackTarget(
            self.sharing_status_label, self.sharing_notice,
        )

        self.sharing_refresh_button = QPushButton("Refresh")
        self.sharing_refresh_button.setToolTip(help_text.TOOLTIP_SHARING_REFRESH)
        self.sharing_refresh_button.clicked.connect(self._refresh_sharing)
        controls.addWidget(self.sharing_refresh_button)
        layout.addLayout(controls)

        locations_section = QVBoxLayout()
        locations_section.setSpacing(theme.SPACING_SM)
        locations_label = PlainLabel("Your library on SoulSeek")
        locations_label.setObjectName("sectionHeaderLabel")
        locations_section.addWidget(locations_label)

        self.sharing_locations_table = QTableWidget(0, 5)
        self.sharing_locations_table.setHorizontalHeaderLabels(
            ["Location", "Shared", "Container Path", "Files", "Action"]
        )
        theme.apply_table_defaults(self.sharing_locations_table)
        self.sharing_locations_table.setIconSize(
            QSize(status_lamp.LAMP_SIZE, status_lamp.LAMP_SIZE),
        )
        locations_section.addWidget(
            theme.make_card(self.sharing_locations_table),
        )
        layout.addLayout(locations_section, 1)
        self._configure_sharing_locations_columns()
        self.sharing_locations_empty_action = QPushButton(
            help_text.OPEN_SETTINGS_TEXT
        )
        self.sharing_locations_empty_action.clicked.connect(
            lambda: self._context.navigate("settings")
        )
        self.sharing_locations_empty = EmptyState(
            self.sharing_locations_table, EmptyGlyph.SHARE,
            help_text.SHARING_LOCATIONS_EMPTY,
            action=self.sharing_locations_empty_action,
        )

        uploads_section = QVBoxLayout()
        uploads_section.setSpacing(theme.SPACING_SM)
        uploads_label = PlainLabel("Currently uploading")
        uploads_label.setObjectName("sectionHeaderLabel")
        uploads_section.addWidget(uploads_label)

        self.sharing_uploads_table = QTableWidget(0, 4)
        self.sharing_uploads_table.setHorizontalHeaderLabels(
            ["Peer", "File", "State", "Progress"]
        )
        self.sharing_uploads_table.setToolTip(help_text.TOOLTIP_UPLOADS_TABLE)
        theme.apply_table_defaults(self.sharing_uploads_table)
        self.sharing_uploads_table.setIconSize(
            QSize(status_lamp.LAMP_SIZE, status_lamp.LAMP_SIZE),
        )
        theme.configure_columns(
            self.sharing_uploads_table, _SHARING_UPLOADS_COLUMNS,
        )
        uploads_section.addWidget(theme.make_card(self.sharing_uploads_table))
        layout.addLayout(uploads_section, 1)
        self.sharing_uploads_empty = EmptyState(
            self.sharing_uploads_table, EmptyGlyph.SHARE,
            help_text.SHARING_UPLOADS_EMPTY,
        )

        # The why of sharing is background reading: the counts and
        # tables come first, and the explanation stays closed until the
        # viewer opens it, then remembers their choice.
        framing_label = RichLabel(help_text.SHARING_FRAMING_BODY)
        framing_label.setWordWrap(True)
        framing_label.setMaximumWidth(
            framing_label.fontMetrics().averageCharWidth()
            * _EXPLAINER_MEASURE_CHARS,
        )
        # Open, it takes a table's share of the height and scrolls,
        # so a short window keeps both tables in view.
        self.explainer = Disclosure(
            help_text.SHARING_EXPLAINER_TITLE, theme.scrollable(framing_label),
            expanded=context.application.settings.sharing_explainer_open,
        )
        self.explainer.toggled.connect(self._on_explainer_toggled)
        layout.addWidget(self.explainer)
        self._content_layout = layout
        self._fit_explainer()

        self._current_sharing_self_managed = False
        self._last_snapshot: _SharingSnapshot | None = None

        # Lazy-loaded like Duplicates (first real page SHOW, never at
        # construction — see HISTORY §39's deadlock), but also joins the
        # standing 20s backend_poll_timer once visited, same shape as
        # Downloads' own real-slskd-call poll — sharing status/uploads
        # are live external state, not a one-shot local read like
        # Duplicates/History (HISTORY §56).
        self._sharing_page_visited = False
        self._sharing_poll_in_progress = False
        self._upload_eta_tracker = UploadEtaTracker()

        page = build_page("Sharing", help_text.SHARING_TAB_SUBTITLE, content)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _on_explainer_toggled(self, expanded: bool) -> None:
        self._fit_explainer()
        self._context.application.update_settings(
            sharing_explainer_open=expanded,
        )

    def _fit_explainer(self) -> None:
        self._content_layout.setStretchFactor(
            self.explainer, 1 if self.explainer.is_expanded() else 0,
        )

    def _gather_sharing_snapshot(self) -> _SharingSnapshot:
        if not self._context.application.soulseek_configured:
            return _SharingSnapshot(
                configured=False, status=None, self_managed=False,
                reconciliation=[], uploads=[],
            )

        service = self._context.application.sharing_service
        status = service.get_status()

        return _SharingSnapshot(
            configured=True,
            status=status,
            self_managed=service.is_self_managed(),
            reconciliation=service.get_reconciliation(status),
            uploads=service.get_uploads(),
        )

    def on_shown(self) -> None:
        """Refresh now, and join the backend poll from here on."""
        self._sharing_page_visited = True
        self._refresh_sharing()

    def _refresh_sharing(self) -> None:
        self._context.run_busy_worker(
            "sharing_refresh", self.sharing_refresh_button,
            self._gather_sharing_snapshot,
            status_label=self.sharing_status_label,
            on_finished=self._render_sharing,
            on_error=self.feedback.show_error,
        )

    def poll_sharing(self) -> None:
        if not self._sharing_page_visited:
            return

        if self._sharing_poll_in_progress:
            return

        if not self._context.application.soulseek_configured:
            return

        self._sharing_poll_in_progress = True

        def on_finished(snapshot: _SharingSnapshot) -> None:
            self._sharing_poll_in_progress = False
            self._render_sharing(snapshot)

        def on_error(_: str) -> None:
            self._sharing_poll_in_progress = False

        run_worker(
            self._context.thread_pool,
            self._gather_sharing_snapshot,
            on_finished=on_finished,
            on_error=on_error,
        )

    def refresh_lamps(self) -> None:
        """Repaint the tables' lamps in the active palette, from the
        last fetch: a theme switch needs no new call to slskd."""
        if self._last_snapshot is not None:
            self._paint_sharing(self._last_snapshot)

    def _render_sharing(self, snapshot: _SharingSnapshot) -> None:
        self._current_sharing_self_managed = snapshot.self_managed
        self._last_snapshot = snapshot
        self._record_upload_progress(snapshot.uploads)
        self._paint_sharing(snapshot)

    def _paint_sharing(self, snapshot: _SharingSnapshot) -> None:
        if not snapshot.configured:
            self.sharing_summary_label.setText(
                help_text.SHARING_UNCONFIGURED_NOTICE
            )
            self.sharing_locations_table.setRowCount(0)
            self.sharing_locations_empty.set_text(
                help_text.SHARING_LOCATIONS_UNCONFIGURED
            )
            self.sharing_uploads_table.setRowCount(0)
            return

        self.sharing_locations_empty.set_text(
            help_text.SHARING_LOCATIONS_EMPTY
        )

        status = snapshot.status
        assert status is not None

        managed_note = (
            "Managed by Seeker." if snapshot.self_managed
            else "Not managed by Seeker — sharing changes need manual steps."
        )
        self.sharing_summary_label.setText(
            f"{status.directories} directories, {status.files} files "
            f"shared. {managed_note}"
        )

        self._render_sharing_locations_table(snapshot.reconciliation)
        self._render_sharing_uploads_table(snapshot.uploads)

    def _render_sharing_locations_table(
            self, reconciliation: list[LocationShareState],
    ) -> None:
        table = self.sharing_locations_table
        action_widgets: list[QWidget] = []

        # Sorting is live on this table; disabled for the body of this
        # rebuild (see preserving_sort_order's own docstring for why)
        # and restored afterward.
        with preserving_sort_order(table):
            table.setRowCount(len(reconciliation))

            for row, state in enumerate(reconciliation):
                table.setItem(row, 0, QTableWidgetItem(state.location.name))
                table.setItem(
                    row, 1,
                    _lamp_item("Shared", status_lamp.PLAY) if state.shared
                    else _lamp_item("Not shared", status_lamp.STANDBY),
                )
                table.setItem(
                    row, 2,
                    QTableWidgetItem(
                        state.share.local_path if state.share else ""
                    ),
                )
                files = (
                    state.share.files
                    if state.share and state.share.files is not None
                    else None
                )
                # A real file count sorts numerically; the displayed
                # text would otherwise sort "10" before "9" (see
                # SortKeyItem).
                table.setItem(
                    row, 3,
                    SortKeyItem(
                        str(files) if files is not None else "",
                        files if files is not None else -1,
                    ),
                )

                if state.shared:
                    # The Shared column already says so.
                    table.removeCellWidget(row, 4)
                    continue

                button = QPushButton("Add to my SoulSeek share")
                button.setToolTip(help_text.TOOLTIP_ADD_LOCATION_TO_SHARE)
                button.clicked.connect(
                    lambda _checked=False, location=state.location:
                    self._on_add_location_to_share_clicked(location)
                )
                # A bare setCellWidget(button) gets literally resized to
                # fill the whole cell rect (setCellWidget positions its
                # widget directly, bypassing normal layout sizing), reading
                # as a filled cell rather than a button. cell_widget()'s
                # trailing stretch absorbs the leftover width instead
                # (HISTORY §80).
                button_widget = theme.cell_widget(
                    button, row_label=state.location.name,
                )
                action_widgets.append(button_widget)
                table.setCellWidget(row, 4, button_widget)

        self._size_sharing_locations_columns(action_widgets)

    def _configure_sharing_locations_columns(self) -> None:
        # Configured at construction so an empty table already has this
        # layout.
        theme.configure_columns(
            self.sharing_locations_table, _SHARING_LOCATIONS_COLUMNS,
        )

    def _size_sharing_locations_columns(
            self, action_widgets: list[QWidget],
    ) -> None:
        theme.size_columns(
            self.sharing_locations_table,
            _SHARING_LOCATIONS_COLUMNS,
            action_widgets,
        )

    def _record_upload_progress(self, uploads: list[UploadStatus]) -> None:
        """Feed each upload's bytes to the ETA tracker, once per fetch."""
        active_keys: set[tuple[str, str]] = set()
        now = datetime.now(UTC)
        for upload in uploads:
            key = _upload_key(upload)
            if key is None or upload.bytes_transferred is None:
                continue
            active_keys.add(key)
            self._upload_eta_tracker.record(key, upload.bytes_transferred, now)
        self._upload_eta_tracker.evict_except(active_keys)

    def _render_sharing_uploads_table(
            self, uploads: list[UploadStatus],
    ) -> None:
        table = self.sharing_uploads_table

        # Sorting is live on this table; disabled for the body of this
        # rebuild (see preserving_sort_order's own docstring for why)
        # and restored afterward.
        with preserving_sort_order(table):
            table.setRowCount(len(uploads))

            for row, upload in enumerate(uploads):
                table.setItem(
                    row, 0, QTableWidgetItem(upload.username or "")
                )
                table.setItem(
                    row, 1, QTableWidgetItem(upload.filename or "")
                )
                state = _upload_state(upload.state)
                state_item = _lamp_item(state.label, state.lamp, state.note)
                if upload.state:
                    state_item.setToolTip(plain_tooltip(
                        f"slskd: {upload.state}"
                    ))
                table.setItem(row, 2, state_item)

                key = _upload_key(upload)
                progress_text = (
                    self._upload_eta_tracker.describe(key, upload.size)
                    if key is not None and upload.bytes_transferred is not None
                    else ""
                )
                table.setItem(row, 3, QTableWidgetItem(progress_text))

        theme.size_columns(table, _SHARING_UPLOADS_COLUMNS, [])

    def _on_add_location_to_share_clicked(
            self, location: LibraryLocation,
    ) -> None:
        service = self._context.application.sharing_service
        plan = service.preview_add_location(location)

        if not self._current_sharing_self_managed:
            plain_text.information(
                self,
                help_text.SHARING_ADD_CONFIRM_TITLE,
                help_text.SHARING_NOT_SELF_MANAGED_NOTICE
                + "\n\n"
                + plan.compose_volume_line.strip()
                + "\n"
                + plan.slskd_share_directory_line.strip(),
            )
            return

        confirmed = plain_text.question(
            self,
            help_text.SHARING_ADD_CONFIRM_TITLE,
            help_text.format_add_to_share_confirm_body(
                location.name, location.path, plan.container_path,
            ),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        run_worker(
            self._context.thread_pool,
            lambda: service.add_location_to_share(location, confirm=True),
            status_label=self.sharing_status_label,
            on_finished=self._on_add_location_to_share_finished,
            on_error=self.feedback.show_error,
        )

    def _on_add_location_to_share_finished(
            self, result: SharingApplyResult,
    ) -> None:
        ready_note = (
                "" if result.became_ready else " Still finishing the scan."
        )
        self.sharing_notice.show_message(
            f"'{result.location.name}' shared — "
            f"{result.directories_after} directories, "
            f"{result.files_after} files "
            f"(was {result.directories_before}/{result.files_before})."
            + ready_note,
            kind="success",
        )
        self._refresh_sharing()

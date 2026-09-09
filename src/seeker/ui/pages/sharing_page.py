"""The Sharing page (HISTORY §119)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.library_location import LibraryLocation
from seeker.sharing_service import (
    LocationShareState,
    ShareStatus,
    SharingApplyResult,
    UploadStatus,
)
from seeker.ui import help_text, theme
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.upload_eta import UploadEtaTracker
from seeker.ui.workers import run_worker

# The remaining tables (Sharing locations here, Track, Review's three
# tabs) never grew a column IntEnum of their own — their layouts are
# declared the same way, just against plain column indices.
_SHARING_LOCATIONS_COLUMNS = theme.ColumnLayout(
    stretch=(2,), fit_content=(0, 1, 3), actions=4,
)


@dataclass
class _SharingSnapshot:
    """Everything the Sharing page (HISTORY §56 Phase 7) needs to
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
        # downloads from (HISTORY §56 Phase 7). See help_text.py's
        # SHARING_FRAMING_BODY for why this page frames things honestly
        # rather than as a persuasive pitch.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING_LG)

        framing_label = QLabel(help_text.SHARING_FRAMING_BODY)
        framing_label.setTextFormat(Qt.TextFormat.RichText)
        framing_label.setWordWrap(True)
        layout.addWidget(framing_label)

        # Round 8 §12.9 — a real confirmation ("'X' shared — N
        # directories, M files") used to go to sharing_status_label,
        # which _refresh_sharing() (called right after, to pick up the
        # new state) wipes via run_worker's own status_label.setText("")
        # at the top of every call — the confirmation was never actually
        # readable. Same fix notice.py's own docstring describes for
        # Dashboard: persistent, dismissible content belongs on an
        # InlineNotice, not the poll-cleared status label.
        self.sharing_notice = InlineNotice()
        layout.addWidget(self.sharing_notice)

        controls = QHBoxLayout()
        self.sharing_summary_label = QLabel("")
        controls.addWidget(self.sharing_summary_label, 1)

        self.sharing_refresh_button = QPushButton("Refresh")
        self.sharing_refresh_button.setToolTip(help_text.TOOLTIP_SHARING_REFRESH)
        self.sharing_refresh_button.clicked.connect(self._refresh_sharing)
        controls.addWidget(self.sharing_refresh_button)
        layout.addLayout(controls)

        self.sharing_status_label = QLabel("")
        layout.addWidget(self.sharing_status_label)

        self.sharing_locations_table = QTableWidget(0, 5)
        self.sharing_locations_table.setHorizontalHeaderLabels(
            ["Location", "Shared", "Container Path", "Files", "Action"]
        )
        theme.apply_table_defaults(self.sharing_locations_table)
        layout.addWidget(theme.make_card(self.sharing_locations_table))
        self._configure_sharing_locations_columns()

        uploads_label = QLabel("Currently uploading")
        # QLabel#sectionHeaderLabel in theme.py.
        uploads_label.setObjectName("sectionHeaderLabel")
        layout.addWidget(uploads_label)

        self.sharing_uploads_table = QTableWidget(0, 4)
        self.sharing_uploads_table.setHorizontalHeaderLabels(
            ["Peer", "File", "State", "Progress"]
        )
        self.sharing_uploads_table.setToolTip(help_text.TOOLTIP_UPLOADS_TABLE)
        # No ColumnLayout shape here either — see the same note on
        # `downloads_table` in downloads_page.py.
        self.sharing_uploads_table.horizontalHeader().setStretchLastSection(True)
        theme.apply_table_defaults(self.sharing_uploads_table)
        theme.apply_column_floors(self.sharing_uploads_table)
        layout.addWidget(theme.make_card(self.sharing_uploads_table))

        self._current_sharing_reconciliation: list[LocationShareState] = []
        self._current_sharing_self_managed = False

        # Lazy-loaded like Duplicates (first real page SHOW, never at
        # construction — see HISTORY §39's deadlock), but also joins the
        # standing 20s backend_poll_timer once visited, same shape as
        # Downloads' own real-slskd-call poll — sharing status/uploads
        # are live external state, not a one-shot local read like
        # Duplicates/History (HISTORY §56 Phase 7).
        self._sharing_page_visited = False
        self._sharing_poll_in_progress = False
        self._upload_eta_tracker = UploadEtaTracker()

        page = build_page("Sharing", help_text.SHARING_TAB_SUBTITLE, content)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _gather_sharing_snapshot(self) -> _SharingSnapshot:
        if not self._context.application.soulseek_configured:
            return _SharingSnapshot(
                configured=False, status=None, self_managed=False,
                reconciliation=[], uploads=[],
            )

        service = self._context.application.sharing_service

        return _SharingSnapshot(
            configured=True,
            status=service.get_status(),
            self_managed=service.is_self_managed(),
            reconciliation=service.get_reconciliation(),
            uploads=service.get_uploads(),
        )

    def _refresh_sharing(self) -> None:
        self._context.run_busy_worker(
            "sharing_refresh", self.sharing_refresh_button,
            self._gather_sharing_snapshot,
            status_label=self.sharing_status_label,
            on_finished=self._render_sharing,
        )

    def _trigger_sharing_poll(self) -> None:
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

    def _render_sharing(self, snapshot: _SharingSnapshot) -> None:
        self._current_sharing_reconciliation = snapshot.reconciliation
        self._current_sharing_self_managed = snapshot.self_managed

        if not snapshot.configured:
            self.sharing_summary_label.setText(
                help_text.SHARING_UNCONFIGURED_NOTICE
            )
            self.sharing_locations_table.setRowCount(0)
            self.sharing_uploads_table.setRowCount(0)
            return

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

        # Round 8 §12.2 — sorting is live on this table; disabled for
        # the body of this rebuild (see preserving_sort_order's own
        # docstring for why) and restored afterward.
        with preserving_sort_order(table):
            table.setRowCount(len(reconciliation))

            for row, state in enumerate(reconciliation):
                table.setItem(row, 0, QTableWidgetItem(state.location.name))
                table.setItem(
                    row, 1, QTableWidgetItem("Yes" if state.shared else "No"),
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
                # Round 8 §12.2 — a real file count sorts numerically;
                # the displayed text would otherwise sort "10" before
                # "9" (see SortKeyItem).
                table.setItem(
                    row, 3,
                    SortKeyItem(
                        str(files) if files is not None else "",
                        files if files is not None else -1,
                    ),
                )

                if state.shared:
                    shared_widget = theme.cell_widget(QLabel("Shared"))
                    action_widgets.append(shared_widget)
                    table.setCellWidget(row, 4, shared_widget)
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
                button_widget = theme.cell_widget(button)
                action_widgets.append(button_widget)
                table.setCellWidget(row, 4, button_widget)

        self._size_sharing_locations_columns(action_widgets)

    def _configure_sharing_locations_columns(self) -> None:
        # Roadmap item R5 (5b.1); split per item E2 (round 7) so an
        # empty table gets this layout at construction.
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

    def _render_sharing_uploads_table(
            self, uploads: list[UploadStatus],
    ) -> None:
        table = self.sharing_uploads_table
        active_keys: set[tuple[str, str]] = set()
        now = datetime.now(UTC)

        # Round 8 §12.2 — sorting is live on this table; disabled for
        # the body of this rebuild (see preserving_sort_order's own
        # docstring for why) and restored afterward.
        with preserving_sort_order(table):
            # Roadmap item 73 (P4 audit) — the SAME stale-span bug class as
            # the duplicates table, found live during that fix's own
            # "audit every other table" step: this table's empty-state
            # branch sets a 4-column span at row 0; setRowCount() doesn't
            # clear it, so a transition from empty -> a real upload left
            # that span active, visually swallowing the new row's
            # filename/state/progress cells into column 0 even though their
            # real QTableWidgetItem data was set correctly underneath.
            table.clearSpans()
            table.setRowCount(len(uploads))

            for row, upload in enumerate(uploads):
                table.setItem(
                    row, 0, QTableWidgetItem(upload.username or "")
                )
                table.setItem(
                    row, 1, QTableWidgetItem(upload.filename or "")
                )
                table.setItem(row, 2, QTableWidgetItem(upload.state or ""))

                progress_text = ""

                if (
                        upload.username is not None
                        and upload.filename is not None
                        and upload.bytes_transferred is not None
                ):
                    key = (upload.username, upload.filename)
                    active_keys.add(key)
                    self._upload_eta_tracker.record(
                        key, upload.bytes_transferred, now,
                    )
                    progress_text = self._upload_eta_tracker.describe(
                        key, upload.size,
                    )

                table.setItem(row, 3, QTableWidgetItem(progress_text))

            if not uploads:
                table.setRowCount(1)
                table.setSpan(0, 0, 1, 4)
                table.setItem(
                    0, 0, QTableWidgetItem(help_text.NO_UPLOADS_LABEL),
                )

        self._upload_eta_tracker.evict_except(active_keys)

    def _on_add_location_to_share_clicked(
            self, location: LibraryLocation,
    ) -> None:
        service = self._context.application.sharing_service
        plan = service.preview_add_location(location)

        if not self._current_sharing_self_managed:
            QMessageBox.information(
                self,
                help_text.SHARING_ADD_CONFIRM_TITLE,
                help_text.SHARING_NOT_SELF_MANAGED_NOTICE
                + "\n\n"
                + plan.compose_volume_line.strip()
                + "\n"
                + plan.slskd_share_directory_line.strip(),
            )
            return

        confirmed = QMessageBox.question(
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

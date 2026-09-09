"""The Review page (HISTORY §119) — the hardest page moved, since it
hosts three independent decision queues sharing one poll cycle and one
tray-badge/notification path back to the shell: SoulSeek needs-review
candidates, Phase 2 upgrade replacements, and local-file matches.

Beyond PageContext, this page needs a second, narrower seam —
`ReviewHost` — for `status_label` (the same shared Dashboard-owned
widget TaggingPanel already reaches through its own Host),
`refresh_track_table` (Dashboard's `_poll_selected_playlist`, called
after a local-match confirm/reject changes what's IN_LIBRARY), and
`check_for_needs_decision_notification` (real MainWindow/tray logic —
a de-duplicated notification — that stays shell-owned because it also
reads `_tray_icon`/`application.settings`, neither of which belongs on
a page).

`_pending_review_focus_track_id`/`_focus_pending_review_row` move here
too — both are genuinely Review-owned state/logic, just previously
stranded on MainWindow because `_show_page` needed to reach them
directly (set by a Dashboard double-click via `DashboardHost.
navigate_to_review`, itself a lambda closing over `self._show_page(
"review", focus_track_id=...)`). `_show_page` keeps doing exactly
that, just against `self._review_page` instead of `self` — same
"reach a moved page's private state directly, from the one shell
method that legitimately needs to" precedent as `_invalidate_after_
leaving_settings` calling `self._dashboard_page._poll_next_step()`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.upgrade_review import UpgradeReviewDetails
from seeker.soulseek.download_service import BulkUpgradeReplaceResult
from seeker.ui import help_text, theme
from seeker.ui.dialogs import BulkReplaceUpgradesDialog
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.table_sort import SortKeyItem, preserving_sort_order
from seeker.ui.workers import run_worker

NeedsReviewCandidates = list[tuple[Track, SoulseekReviewCandidate]]
PendingUpgrades = list[UpgradeReviewDetails]

# The three tables below never grew a column IntEnum of their own —
# their layouts are declared the same way, just against plain column
# indices. (Duplicates' own _DuplicatesColumn/_DUPLICATES_COLUMNS
# stayed on main_window.py; the Track table's own _TRACK_COLUMNS moved
# to dashboard_page.py — round 8 Phase 6.)
_REVIEW_NEEDS_COLUMNS = theme.ColumnLayout(
    stretch=(0,), fit_content=(1, 2), actions=3,
)
_REVIEW_UPGRADES_COLUMNS = theme.ColumnLayout(
    stretch=(0,), fit_content=(1, 2), actions=3,
)
_REVIEW_LOCAL_COLUMNS = theme.ColumnLayout(
    stretch=(0, 1), fit_content=(2, 3), actions=4,
)


@dataclass(frozen=True)
class ReviewHost:
    """What Review needs from the shell beyond PageContext (HISTORY
    §119).
    """
    status_label: QLabel
    refresh_track_table: Callable[[], None]
    check_for_needs_decision_notification: Callable[[int], None]


class ReviewPage(QWidget):
    def __init__(self, context: PageContext, host: ReviewHost):
        super().__init__()
        self._context = context
        self._host = host

        # The tray menu's own "Review (N)"/"Upgrades (N)" counts, read
        # by the shell via the MainWindow delegating properties of the
        # same private names (HISTORY §90).
        self._needs_review_count = 0
        self._pending_upgrades_count = 0
        # Set by a Dashboard double-click on a NEEDS_REVIEW/AWAITING_
        # REVIEW row (HISTORY §56 §2.4); consumed once by
        # _focus_pending_review_row the next time this page's data
        # actually loads.
        self._pending_review_focus_track_id: str | None = None

        # Two independent sections: SoulSeek needs-review candidates
        # (HISTORY §17's tier, gaining its first real confirm/reject
        # action here) and Phase 2 upgrade confirmations (HISTORY §8's
        # ready_for_review flow, previously CLI-only via `seeker
        # downloads review`). Both are driven by DownloadService methods
        # that were built explicit-decision and input()-free
        # specifically so a UI could call them directly (HISTORY §26).
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("SoulSeek candidates needing confirmation"))

        self.review_needs_table = QTableWidget(0, 4)
        self.review_needs_table.setHorizontalHeaderLabels(
            ["Track", "Score", "Candidate", "Actions"]
        )
        theme.apply_table_defaults(self.review_needs_table)
        layout.addWidget(theme.make_card(self.review_needs_table))
        self._configure_review_needs_columns()

        upgrades_header_row = QHBoxLayout()
        upgrades_header_row.addWidget(
            QLabel("Downloaded upgrades ready for review")
        )
        upgrades_header_row.addStretch()
        # "Replace all" (HISTORY §88). Real count set/refreshed in
        # _render_pending_upgrades, so it's never stale against what's
        # actually in the table.
        self.replace_all_upgrades_button = QPushButton("Replace all")
        self.replace_all_upgrades_button.setToolTip(
            help_text.TOOLTIP_REPLACE_ALL_UPGRADES
        )
        self.replace_all_upgrades_button.setEnabled(False)
        self.replace_all_upgrades_button.clicked.connect(
            self._on_replace_all_upgrades_clicked
        )
        upgrades_header_row.addWidget(self.replace_all_upgrades_button)
        layout.addLayout(upgrades_header_row)

        self.review_upgrades_table = QTableWidget(0, 4)
        self.review_upgrades_table.setHorizontalHeaderLabels(
            ["Track", "Current", "New quality", "Actions"]
        )
        theme.apply_table_defaults(self.review_upgrades_table)
        layout.addWidget(theme.make_card(self.review_upgrades_table))
        self._configure_review_upgrades_columns()

        # Third section (HISTORY §56 Phase 2), closing HISTORY §7's
        # long-outstanding gap: needs_review LOCAL-FILE matches (distinct
        # from the SoulSeek candidates table above) never had a
        # confirm/reject UI at all before this.
        layout.addWidget(QLabel("Local library matches needing confirmation"))

        self.review_local_table = QTableWidget(0, 5)
        self.review_local_table.setHorizontalHeaderLabels(
            ["Track", "Matched file", "Location", "Score", "Actions"]
        )
        theme.apply_table_defaults(self.review_local_table)
        layout.addWidget(theme.make_card(self.review_local_table))
        self._configure_review_local_columns()

        # The 2s poll_timer rebuilds this table's checkboxes from
        # scratch every tick; nothing carried the checked state across
        # that rebuild before this fix. Keyed by the stable
        # UpgradeReviewDetails.request_id, never row index — pruned to
        # only rows still present on every render (HISTORY §86).
        self._upgrade_delete_checked: set[int] = set()
        self._current_pending_upgrades: PendingUpgrades = []

        page = build_page(
            "Review", help_text.REVIEW_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _poll_review_items(self) -> None:
        # All three halves are cheap, local-DB-only reads (like
        # get_active_downloads above) — no real slskd network calls, so
        # this belongs on the 2s display-refresh timer, not the 20s
        # backend-poll one. Bundled into one worker call rather than
        # three so every table updates from the same consistent DB
        # snapshot.
        def fetch() -> tuple[
                NeedsReviewCandidates, PendingUpgrades,
                list[NeedsReviewMatch],
        ]:
            service = self._context.application.download_service
            return (
                service.get_review_candidates(),
                service.get_pending_upgrade_reviews(),
                self._context.application.library_service
                .get_needs_review_matches(),
            )

        run_worker(
            self._context.thread_pool,
            fetch,
            on_finished=self._render_review_items,
        )

    def _render_review_items(
            self,
            data: tuple[
                NeedsReviewCandidates, PendingUpgrades,
                list[NeedsReviewMatch],
            ],
    ) -> None:
        candidates, upgrades, local_matches = data
        total = len(candidates) + len(upgrades) + len(local_matches)
        self._context.update_nav_badge("review", total)
        # The tray menu's own "Review (N)"/"Upgrades (N)" counts, built
        # from this same fetch (never a third source of truth).
        # "Review" covers everything needing a confirm/reject decision;
        # "Upgrades" is its own real Phase 2 concept (replace/decline),
        # kept distinct in the menu the same way the two are already
        # distinct sections on this page (HISTORY §90).
        self._needs_review_count = len(candidates) + len(local_matches)
        self._pending_upgrades_count = len(upgrades)
        self._host.check_for_needs_decision_notification(total)
        self._render_needs_review_candidates(candidates)
        self._render_pending_upgrades(upgrades)
        self._render_local_needs_review_matches(local_matches)
        self._focus_pending_review_row()

    def _render_needs_review_candidates(
            self,
            candidates: NeedsReviewCandidates,
    ) -> None:
        # Counts/notifications are already computed by the caller
        # (_render_review_items) before this runs; the table rebuild
        # itself is pure waste while hidden (HISTORY §90).
        if self._context.is_hidden_to_tray():
            return

        action_widgets: list[QWidget] = []

        # Round 8 §12.2 — sorting is live on this table; disabled for
        # the body of this rebuild (see preserving_sort_order's own
        # docstring for why) and restored afterward.
        with preserving_sort_order(self.review_needs_table):
            self.review_needs_table.setRowCount(len(candidates))

            for row, (track, candidate) in enumerate(candidates):
                label = f"{track.artist} - {track.title}"
                label_item = QTableWidgetItem(label)
                # Round 8 §12.2 — the row's own anchor back to its real
                # track id, read by _focus_pending_review_row instead
                # of assuming this loop's row position still matches
                # the table's (possibly sorted) row order.
                label_item.setData(Qt.ItemDataRole.UserRole, track.id)
                self.review_needs_table.setItem(row, 0, label_item)
                self.review_needs_table.setItem(
                    row, 1,
                    SortKeyItem(f"{candidate.score:.1f}", candidate.score),
                )

                candidate_text = (
                        f"{candidate.quality_descriptor} — {candidate.username}"
                )
                self.review_needs_table.setItem(
                    row, 2, QTableWidgetItem(candidate_text),
                )

                needs_review_actions = self._build_needs_review_actions(
                    track.id,
                )
                action_widgets.append(needs_review_actions)
                self.review_needs_table.setCellWidget(
                    row, 3, needs_review_actions,
                )

        self._size_review_needs_columns(action_widgets)

    def _configure_review_needs_columns(self) -> None:
        theme.configure_columns(self.review_needs_table, _REVIEW_NEEDS_COLUMNS)

    def _size_review_needs_columns(
            self,
            action_widgets: list[QWidget],
    ) -> None:
        theme.size_columns(
            self.review_needs_table, _REVIEW_NEEDS_COLUMNS, action_widgets,
        )

    def _build_needs_review_actions(self, track_id: str) -> QWidget:
        confirm_button = QPushButton("Confirm")
        confirm_button.setToolTip(help_text.TOOLTIP_CONFIRM_REVIEW_CANDIDATE)
        reject_button = QPushButton("Reject")
        reject_button.setToolTip(help_text.TOOLTIP_REJECT_REVIEW_CANDIDATE)

        confirm_button.clicked.connect(
            lambda: self._on_confirm_review_candidate(track_id, confirm_button)
        )
        reject_button.clicked.connect(
            lambda: self._on_reject_review_candidate(track_id, reject_button)
        )

        return theme.cell_widget(confirm_button, reject_button)

    def _on_confirm_review_candidate(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        # confirm_review_candidate makes a real request_download() call
        # (network) — routed through the worker pool like every other
        # long-running action, never called directly on the main thread.
        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.download_service
            .confirm_review_candidate(track_id),
            button=button,
            status_label=self._host.status_label,
            on_finished=lambda _: self._poll_review_items(),
        )

    def _on_reject_review_candidate(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.download_service
            .reject_review_candidate(track_id),
            button=button,
            status_label=self._host.status_label,
            on_finished=lambda _: self._poll_review_items(),
        )

    def _render_pending_upgrades(self, upgrades: PendingUpgrades) -> None:
        # The real list "Replace all" acts on, recomputed fresh every
        # render so a click always sees exactly what's on screen right
        # now (HISTORY §76's "recompute at click time" lesson, applied
        # again in §88). Kept unconditional (not behind the
        # hidden-window gate below) — the underlying poll keeps
        # fetching fresh data while hidden, so this stays correct the
        # instant the window is shown again.
        self._current_pending_upgrades = upgrades

        # The table rebuild itself is pure waste while hidden
        # (HISTORY §90).
        if self._context.is_hidden_to_tray():
            return

        self.replace_all_upgrades_button.setEnabled(len(upgrades) > 0)
        self.replace_all_upgrades_button.setText(
            f"Replace all ({len(upgrades)})" if upgrades else "Replace all"
        )

        # Prune keys for rows that no longer exist, so this can't grow
        # unbounded across a long session (HISTORY §86).
        live_request_ids = {details.request_id for details in upgrades}
        self._upgrade_delete_checked &= live_request_ids

        action_widgets: list[QWidget] = []

        # Round 8 §12.2 — sorting is live on this table; disabled for
        # the body of this rebuild (see preserving_sort_order's own
        # docstring for why) and restored afterward.
        with preserving_sort_order(self.review_upgrades_table):
            self.review_upgrades_table.setRowCount(len(upgrades))

            for row, details in enumerate(upgrades):
                label = f"{details.track.artist} - {details.track.title}"
                label_item = QTableWidgetItem(label)
                # Round 8 §12.2 — the row's own anchor back to its real
                # track id, read by _focus_pending_review_row instead
                # of assuming this loop's row position still matches
                # the table's (possibly sorted) row order.
                label_item.setData(Qt.ItemDataRole.UserRole, details.track.id)
                self.review_upgrades_table.setItem(row, 0, label_item)
                self.review_upgrades_table.setItem(
                    row, 1, QTableWidgetItem(details.current_description),
                )
                self.review_upgrades_table.setItem(
                    row, 2, QTableWidgetItem(details.quality_descriptor or "—"),
                )
                upgrade_actions = self._build_upgrade_actions(details)
                action_widgets.append(upgrade_actions)
                self.review_upgrades_table.setCellWidget(
                    row, 3, upgrade_actions,
                )

        self._size_review_upgrades_columns(action_widgets)

    def _configure_review_upgrades_columns(self) -> None:
        theme.configure_columns(
            self.review_upgrades_table, _REVIEW_UPGRADES_COLUMNS,
        )

    def _size_review_upgrades_columns(
            self,
            action_widgets: list[QWidget],
    ) -> None:
        theme.size_columns(
            self.review_upgrades_table, _REVIEW_UPGRADES_COLUMNS, action_widgets,
        )

    def _on_upgrade_delete_checkbox_toggled(
            self, request_id: int, checked: bool,
    ) -> None:
        if checked:
            self._upgrade_delete_checked.add(request_id)
        else:
            self._upgrade_delete_checked.discard(request_id)

    def _build_upgrade_actions(self, details: UpgradeReviewDetails) -> QWidget:
        replace_button = QPushButton("Replace")
        replace_button.setToolTip(help_text.TOOLTIP_REPLACE_UPGRADE)
        decline_button = QPushButton("Decline")
        decline_button.setToolTip(help_text.TOOLTIP_DECLINE_UPGRADE)

        # The "delete old file?" control only ever appears when there's
        # a real old file to delete — mirrors the CLI's own guard around
        # its second input() prompt (get_upgrade_review_details leaves
        # old_file_path unset when there's nothing to replace).
        widgets: list[QWidget] = []
        delete_checkbox: QCheckBox | None = None
        if details.old_file_path is not None:
            delete_checkbox = QCheckBox("Delete old file")
            delete_checkbox.setToolTip(
                help_text.TOOLTIP_DELETE_OLD_FILE_CHECKBOX
            )
            # Restore whatever this row's checkbox was set to before
            # the last rebuild, and keep the state map updated as the
            # user toggles it, keyed by the stable request_id (never
            # row index, which shifts as rows are added/removed)
            # (HISTORY §86).
            request_id = details.request_id
            delete_checkbox.setChecked(
                request_id in self._upgrade_delete_checked
            )
            delete_checkbox.toggled.connect(
                lambda checked, request_id=request_id: (
                    self._on_upgrade_delete_checkbox_toggled(
                        request_id, checked,
                    )
                )
            )
            widgets.append(delete_checkbox)

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

        widgets.extend((replace_button, decline_button))
        return theme.cell_widget(*widgets)

    def _on_apply_upgrade_decision(
            self,
            request_id: int,
            replace: bool,
            delete_old: bool,
            button: QPushButton,
    ) -> None:
        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.download_service
            .apply_upgrade_decision(request_id, replace, delete_old),
            button=button,
            on_finished=self._on_upgrade_decision_finished,
        )

    def _on_upgrade_decision_finished(self, message: str | None) -> None:
        # apply_upgrade_decision returns None for a decline (no-op, no
        # message needed) and a short status string for a real replace —
        # run_worker's own status_label wiring only fires on error, so
        # the success message is surfaced here instead.
        if message is not None:
            self._host.status_label.setText(message)

        self._poll_review_items()

    def _on_replace_all_upgrades_clicked(self) -> None:
        # Built fresh from what's actually on screen right now, never a
        # stale plan from an earlier click (HISTORY §76, §88).
        upgrades = self._current_pending_upgrades

        if not upgrades:
            return

        dialog = BulkReplaceUpgradesDialog(self, upgrades)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        delete_old = dialog.delete_old_checkbox.isChecked()
        request_ids = [details.request_id for details in upgrades]

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.download_service
            .apply_upgrade_decisions_batch(request_ids, delete_old),
            button=self.replace_all_upgrades_button,
            status_label=self._host.status_label,
            on_finished=self._on_bulk_replace_upgrades_finished,
        )

    def _on_bulk_replace_upgrades_finished(
            self, result: BulkUpgradeReplaceResult,
    ) -> None:
        QMessageBox.information(
            self,
            help_text.BULK_REPLACE_UPGRADES_DIALOG_TITLE,
            help_text.format_bulk_replace_upgrades_result(result),
        )
        # A partial failure's rows stay ready_for_review (apply_upgrade_
        # decision's own contract — see apply_upgrade_decisions_batch's
        # docstring) and are simply offered again by this same refresh,
        # never dropped.
        self._poll_review_items()

    def _render_local_needs_review_matches(
            self,
            matches: list[NeedsReviewMatch],
    ) -> None:
        # The table rebuild itself is pure waste while hidden
        # (HISTORY §90).
        if self._context.is_hidden_to_tray():
            return

        action_widgets: list[QWidget] = []

        # Round 8 §12.2 — sorting is live on this table; disabled for
        # the body of this rebuild (see preserving_sort_order's own
        # docstring for why) and restored afterward.
        with preserving_sort_order(self.review_local_table):
            self.review_local_table.setRowCount(len(matches))

            for row, match in enumerate(matches):
                label = f"{match.track_artist} - {match.track_title}"
                label_item = QTableWidgetItem(label)
                # Round 8 §12.2 — the row's own anchor back to its real
                # track id, read by _focus_pending_review_row instead
                # of assuming this loop's row position still matches
                # the table's (possibly sorted) row order.
                label_item.setData(Qt.ItemDataRole.UserRole, match.track_id)
                self.review_local_table.setItem(row, 0, label_item)
                self.review_local_table.setItem(
                    row, 1, QTableWidgetItem(match.local_file_path),
                )
                self.review_local_table.setItem(
                    row, 2, QTableWidgetItem(match.location_name),
                )
                self.review_local_table.setItem(
                    row, 3, SortKeyItem(f"{match.score:.1f}", match.score),
                )
                local_review_actions = self._build_local_review_actions(
                    match.track_id,
                )
                action_widgets.append(local_review_actions)
                self.review_local_table.setCellWidget(
                    row, 4, local_review_actions,
                )

        self._size_review_local_columns(action_widgets)

    def _configure_review_local_columns(self) -> None:
        theme.configure_columns(self.review_local_table, _REVIEW_LOCAL_COLUMNS)

    def _size_review_local_columns(
            self,
            action_widgets: list[QWidget],
    ) -> None:
        theme.size_columns(
            self.review_local_table, _REVIEW_LOCAL_COLUMNS, action_widgets,
        )

    def _build_local_review_actions(self, track_id: str) -> QWidget:
        confirm_button = QPushButton("Confirm")
        confirm_button.setToolTip(help_text.TOOLTIP_CONFIRM_LOCAL_MATCH)
        reject_button = QPushButton("Reject")
        reject_button.setToolTip(help_text.TOOLTIP_REJECT_LOCAL_MATCH)

        confirm_button.clicked.connect(
            lambda: self._on_confirm_local_match(track_id, confirm_button)
        )
        reject_button.clicked.connect(
            lambda: self._on_reject_local_match(track_id, reject_button)
        )

        return theme.cell_widget(confirm_button, reject_button)

    def _on_confirm_local_match(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        # No file on disk is touched by confirm_match() — no double-
        # confirm gate, matching this project's precedent that its
        # confirmation gate is for file replacement, not DB state
        # (HISTORY §27).
        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.library_service
            .confirm_match(track_id),
            button=button,
            status_label=self._host.status_label,
            on_finished=self._on_local_review_decision_finished,
        )

    def _on_reject_local_match(
            self,
            track_id: str,
            button: QPushButton,
    ) -> None:
        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.library_service
            .reject_match(track_id),
            button=button,
            status_label=self._host.status_label,
            on_finished=self._on_local_review_decision_finished,
        )

    def _on_local_review_decision_finished(self, _result: None) -> None:
        self._poll_review_items()
        self._host.refresh_track_table()

    def _focus_pending_review_row(self) -> None:
        # Double-clicking a NEEDS_REVIEW/AWAITING_REVIEW/REVIEW_CANDIDATE
        # Dashboard cell (HISTORY §56 §2.4, extended by §66 to cover
        # REVIEW_CANDIDATE too) sets _pending_review_focus_track_id and
        # switches to this page; once
        # the real data has actually loaded, this scrolls to and selects
        # the matching row — a track that turns out to have nothing here
        # yet (e.g. a locked/shortlisted RETRYING row, not yet
        # ready_for_review) just lands on the page with nothing
        # selected, rather than erroring.
        track_id = self._pending_review_focus_track_id

        if track_id is None:
            return

        self._pending_review_focus_track_id = None

        for table in (
                self.review_needs_table,
                self.review_upgrades_table,
                self.review_local_table,
        ):
            if self._select_row_by_track_id(table, track_id):
                return

    def _select_row_by_track_id(
            self, table: QTableWidget, track_id: str,
    ) -> bool:
        # Round 8 §12.2 — scans the table's own UserRole anchors (set
        # by each _render_* method above) rather than a parallel
        # list's insertion order, which no longer matches row position
        # once the table has been sorted.
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if (
                    item is not None
                    and item.data(Qt.ItemDataRole.UserRole) == track_id
            ):
                table.selectRow(row)
                table.scrollToItem(item)
                return True

        return False

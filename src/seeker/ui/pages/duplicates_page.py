"""The Duplicates page (HISTORY §119)."""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.formatting import format_file_size
from seeker.library.duplicate_service import (
    BulkDuplicateResolutionResult,
    DuplicateGroup,
    GroupResolutionPlan,
)
from seeker.models.fingerprint_result import FingerprintResult
from seeker.models.library_location import LibraryLocation
from seeker.ui import help_text, plain_text, theme
from seeker.ui.dialogs import BulkResolveDuplicatesDialog
from seeker.ui.elided_text import BAND_ROLE
from seeker.ui.notice import FeedbackTarget, InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.plain_text import PlainLabel
from seeker.ui.row_actions import RunningRows
from seeker.ui.workers import run_worker

# A sentinel QButtonGroup id for the "Keep all" option, sharing the same
# group as the per-file keep radios so selecting one deselects the
# others (the exact behavior the user asked to keep). Real local_file
# ids are always positive (AUTOINCREMENT starts at 1), so 0 can never
# collide with one — and, confirmed live, -1 specifically CANNOT be used
# here: QButtonGroup.addButton(button, id=-1) doesn't set the id to -1
# at all — Qt treats -1 as its own "auto-assign an id" sentinel and
# silently substitutes a different, Qt-generated negative id
# (checkedId() returned -2 in a real, direct repro), breaking any
# comparison against a real -1 constant (HISTORY §56).
KEEP_ALL_DUPLICATES_ID = 0

# The busy action "Resolve all groups" runs under: the activity strip
# shows it, and the render keeps the button disabled while it runs.
RESOLVE_ALL_DUPLICATES_KEY = "resolve_all_duplicates"


def _group_key(group: DuplicateGroup) -> frozenset[int]:
    """A group's member file ids: it has no id of its own, and a
    rebuild keeps which files belong to a still-open group."""
    return frozenset(
        f.local_file.id for f in group.files if f.local_file.id is not None
    )


# Named constants for the duplicates table's real column layout,
# replacing literal indices scattered across the render path. Two
# independent investigations could NOT reproduce a genuine index-vs-
# header mismatch; this hardening exists so that bug CLASS becomes
# structurally impossible regardless, and so the regression test can
# resolve "Actions" by its real header text instead of sharing the same
# literal the render code uses (a test that shares the code's own
# mistake proves nothing) (HISTORY §68).
# Keep leads: a group's rows read as a choice of which copy to keep.
# Similarity and Actions belong to the group, so they span its rows.
@dataclass(frozen=True)
class _ShownGroup:
    """The cell widgets one group holds while it is near the view."""

    key: frozenset[int]
    rows: range
    button_group: QButtonGroup


class _DuplicatesColumn(IntEnum):
    KEEP = 0
    PATH = 1
    LOCATION = 2
    QUALITY = 3
    SIMILARITY = 4
    ACTIONS = 5


_DUPLICATES_COLUMN_HEADERS = [
    "Keep", "Path", "Location", "Quality", "Similarity", "Actions",
]

# The declarative layout each table used to write out by hand across a
# `_configure_*_columns`/`_size_*_columns` pair; see `theme.ColumnLayout`
# (HISTORY §118).
_DUPLICATES_COLUMNS = theme.ColumnLayout(
    stretch=(_DuplicatesColumn.PATH,),
    fit_content=(
        _DuplicatesColumn.KEEP, _DuplicatesColumn.LOCATION,
        _DuplicatesColumn.QUALITY, _DuplicatesColumn.SIMILARITY,
    ),
    actions=_DuplicatesColumn.ACTIONS,
    paths=(_DuplicatesColumn.PATH,),
    whole=(_DuplicatesColumn.QUALITY,),
)


class DuplicatesPage(QWidget):
    def __init__(self, context: PageContext):
        super().__init__()
        self._context = context

        # Fingerprint computation + clustering/scoring were built and
        # live-verified first, read-only; the delete action below is
        # the later, explicitly-scoped follow-up (HISTORY §5, §40).
        # Scoped to one library location at a time (the location combo
        # below), never merged across all of them.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        self.notice = InlineNotice()
        layout.addWidget(self.notice)

        # Persistent, cumulative, and celebratory. Hidden entirely at
        # zero — "an empty milestone is worse than no milestone,"
        # matching this app's existing "blank, not a misleading control"
        # precedent for a genuinely-nothing-to-show state (HISTORY §56).
        self.duplicates_milestone_label = PlainLabel("")
        self.duplicates_milestone_label.hide()

        controls = QHBoxLayout()

        self.duplicates_location_combo = QComboBox()
        self.duplicates_location_combo.setToolTip(
            help_text.TOOLTIP_DUPLICATES_LOCATION_COMBO
        )
        self.duplicates_location_combo.currentIndexChanged.connect(
            self._on_duplicates_location_changed
        )
        controls.addWidget(self.duplicates_location_combo)

        # The combo above used to be disabled in folder-scope mode
        # (reversed from an earlier version of this comment). It stays
        # enabled now — once resolve_folder_scopes() does
        # most-specific-wins matching, the selected location is a
        # genuinely useful tiebreak preference for an ambiguous
        # (nested-location) folder, not dead weight the user had to
        # uncheck-then-recheck around (HISTORY §77).
        self.duplicates_folders_checkbox = QCheckBox("Only these folders…")
        self.duplicates_folders_checkbox.setToolTip(
            help_text.TOOLTIP_DUPLICATES_FOLDERS_CHECKBOX
        )
        self.duplicates_folders_checkbox.toggled.connect(
            self._on_duplicates_folders_toggled
        )
        controls.addWidget(self.duplicates_folders_checkbox)

        self.compute_fingerprints_button = QPushButton("Compute fingerprints")
        self.compute_fingerprints_button.setToolTip(
            help_text.TOOLTIP_COMPUTE_FINGERPRINTS
        )
        self.compute_fingerprints_button.clicked.connect(
            self._on_compute_fingerprints_clicked
        )
        controls.addWidget(self.compute_fingerprints_button)

        self.find_duplicates_button = QPushButton("Find duplicates")
        self.find_duplicates_button.setToolTip(
            help_text.TOOLTIP_FIND_DUPLICATES
        )
        self.find_duplicates_button.clicked.connect(
            self._on_find_duplicates_clicked
        )
        controls.addWidget(self.find_duplicates_button)

        # The progress line shares the controls' row: empty, it would
        # hold a blank line of its own above the table.
        self.duplicates_status_label = PlainLabel("")
        self.feedback = FeedbackTarget(
            self.duplicates_status_label, self.notice,
        )
        controls.addSpacing(theme.SPACING_MD)
        controls.addWidget(self.duplicates_status_label)
        controls.addStretch()
        layout.addLayout(controls)

        # "Resolve all groups" (HISTORY §88). Real count set in
        # _render_duplicate_groups, never stale against the table.
        self.resolve_all_duplicates_button = QPushButton("Resolve all groups")
        self.resolve_all_duplicates_button.setToolTip(
            help_text.TOOLTIP_RESOLVE_ALL_DUPLICATES
        )
        self.resolve_all_duplicates_button.setEnabled(False)
        self.resolve_all_duplicates_button.clicked.connect(
            self._on_resolve_all_duplicates_clicked
        )

        # Hidden by default; shown only when "Only these folders…" is
        # checked. A plain QListWidget of real absolute paths, resolved
        # against registered locations only at scope-count/run time
        # (resolve_folder_scopes), not on every add — an unregistered
        # folder is a run-time error, not something that blocks merely
        # listing it (HISTORY §68).
        self.duplicates_folders_panel = QWidget()
        folders_panel_layout = QVBoxLayout(self.duplicates_folders_panel)
        folders_panel_layout.setContentsMargins(0, 0, 0, 0)

        self.duplicates_folders_list = QListWidget()
        folders_panel_layout.addWidget(
            theme.make_card(self.duplicates_folders_list)
        )

        folders_buttons_row = QHBoxLayout()

        self.duplicates_add_folder_button = QPushButton("Add folder…")
        self.duplicates_add_folder_button.setToolTip(
            help_text.TOOLTIP_DUPLICATES_ADD_FOLDER
        )
        self.duplicates_add_folder_button.clicked.connect(
            self._on_add_duplicates_folder_clicked
        )
        folders_buttons_row.addWidget(self.duplicates_add_folder_button)

        self.duplicates_remove_folder_button = QPushButton("Remove selected")
        self.duplicates_remove_folder_button.setToolTip(
            help_text.TOOLTIP_DUPLICATES_REMOVE_FOLDER
        )
        self.duplicates_remove_folder_button.clicked.connect(
            self._on_remove_duplicates_folder_clicked
        )
        folders_buttons_row.addWidget(self.duplicates_remove_folder_button)

        folders_panel_layout.addLayout(folders_buttons_row)

        # Shown BEFORE a real, potentially ~10-minute-at-real-scale run
        # (HISTORY §39) — see help_text.format_duplicates_scope_count's
        # own docstring.
        self.duplicates_scope_count_label = PlainLabel("")
        folders_panel_layout.addWidget(self.duplicates_scope_count_label)

        self.duplicates_folders_panel.setVisible(False)
        layout.addWidget(self.duplicates_folders_panel)

        # Above the table it acts on, beside what resolving has
        # reclaimed so far.
        table_header_row = QHBoxLayout()
        table_header_row.addWidget(self.duplicates_milestone_label)
        table_header_row.addStretch()
        table_header_row.addWidget(self.resolve_all_duplicates_button)
        layout.addLayout(table_header_row)

        self.duplicates_table = QTableWidget(
                0,
                len(_DUPLICATES_COLUMN_HEADERS),
        )
        self.duplicates_table.setHorizontalHeaderLabels(
            _DUPLICATES_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.duplicates_table)
        # This table's rows are grouped per duplicate cluster via
        # setSpan() (see _render_duplicate_groups below); Qt's own sort
        # reorders rows independent of that grouping, which would
        # visually merge/split unrelated clusters. Opted back out of the
        # sorting apply_table_defaults enables for every other table.
        self.duplicates_table.setSortingEnabled(False)
        layout.addWidget(theme.make_card(self.duplicates_table))
        self._configure_duplicates_columns()

        # The groups holding cell widgets, by index into
        # `_current_duplicate_groups`: only those near the view
        # (`_show_groups_in_view`). A QButtonGroup (one per group, so
        # only one radio per group can be selected) has no Qt
        # parent-child tie to the cells its radios live in, so it is
        # kept here for the same reason ui/workers.py keeps a Worker
        # until its own completion (HISTORY §22), and deleted with the
        # group's widgets.
        self._shown_groups: dict[int, _ShownGroup] = {}
        self._current_duplicate_groups: list[DuplicateGroup] = []
        # Each group's first table row, ascending, for finding the
        # groups a span of rows covers.
        self._group_first_rows: list[int] = []
        # Same rebuild-destroys-state bug the Review page's checkbox
        # fix addresses, for the Duplicates "keep" radio selection: a
        # group has no stable id of its own (it's recomputed fresh by
        # clustering, or locally re-derived after a delete — see
        # _on_delete_duplicates_finished), so the group's OWN set of
        # member local_file ids is used as the key instead — stable
        # across the poll rebuild and across a local re-render, since
        # neither changes which files belong to a still-open group.
        # Value is the checked button's id — either a real
        # local_file.id or the KEEP_ALL_DUPLICATES_ID sentinel. Pruned
        # to only still-present groups on every render (HISTORY §86).
        self._duplicates_keep_selection: dict[frozenset[int], int] = {}
        # The groups whose "Confirm delete" is ticked, by the same key.
        # Delete reads this, not the checkbox, which a rebuilt row
        # replaces. Cleared on every render, as the rebuilt checkboxes
        # always were: a confirmation is never carried into a new
        # render.
        self._delete_confirmed: set[frozenset[int]] = set()
        # The groups whose delete is running, by the same member-id
        # key, and the rendered Delete buttons' enable rules by group:
        # a rebuild or a changed keep choice must not offer a running
        # delete again, so a delete's end reapplies the rule rather
        # than re-enabling a button outright.
        self._running_deletes: RunningRows[frozenset[int]] = RunningRows()
        self._delete_enablers: dict[frozenset[int], Callable[[], None]] = {}
        self._duplicates_locations_by_name: dict[str, LibraryLocation] = {}
        # Resolved by local_file.location_id at render time so the
        # LOCATION column (and the delete flow's own path resolution
        # below) reads correctly per-file even for a pooled,
        # cross-location folder-scope result — a single "current
        # location" no longer holds for those (HISTORY §68).
        self._duplicates_locations_by_id: dict[int, LibraryLocation] = {}
        # Persisted across page shows deliberately (never reset in
        # _on_page_changed) — same "don't lose it on every revisit"
        # precedent as the location combo's own selection.
        self._duplicates_folder_paths: list[str] = []
        # Scrolling or resizing changes which groups are near the view.
        self.duplicates_table.verticalScrollBar().valueChanged.connect(
            lambda _value: self._show_groups_in_view(),
        )
        self.duplicates_table.viewport().installEventFilter(self)

        page = build_page(
            "Duplicates", help_text.DUPLICATES_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def refresh_locations(self) -> None:
        run_worker(
            self._context.thread_pool,
            self._context.application.library_service.list_locations,
            on_finished=self._render_duplicates_locations,
        )

    def refresh_milestone(self) -> None:
        run_worker(
            self._context.thread_pool,
            self._context.application.duplicate_service.get_cleanup_totals,
            on_finished=self._render_duplicates_milestone,
        )

    def _render_duplicates_milestone(self, totals: tuple[int, int]) -> None:
        files_deleted, bytes_freed = totals

        if bytes_freed == 0 and files_deleted == 0:
            self.duplicates_milestone_label.hide()
            return

        self.duplicates_milestone_label.setText(
            f"You've reclaimed {format_file_size(bytes_freed)} across "
            f"{files_deleted} file{'s' if files_deleted != 1 else ''}."
        )
        self.duplicates_milestone_label.show()

    def _render_duplicates_locations(
            self,
            locations: list[tuple[Any, bool]],
    ) -> None:
        # Preserve the current selection across a refresh when that
        # location still exists — losing it on every page revisit would
        # be a real regression of its own (HISTORY §56).
        previously_selected = self._selected_duplicates_location()

        self.duplicates_location_combo.clear()
        # The real LibraryLocation (path for the delete-confirmation
        # dialog's exact full paths and the table's own Location column;
        # id for the reclaimed-space milestone's cleanup record).
        # Neither is carried on LocalFile/DuplicateFile at all (only
        # location_id, and not even that on the milestone side), and
        # find_duplicate_groups() is already scoped to one location per
        # call, so this is resolved once here rather than plumbed
        # through the service layer (HISTORY §56).
        self._duplicates_locations_by_name = {
            location.name: location for location, _ in locations
        }
        self._duplicates_locations_by_id = {
            location.id: location
            for location, _ in locations
            if location.id is not None
        }

        for location, _ in locations:
            self.duplicates_location_combo.addItem(
                location.name, location.name
            )

        if previously_selected is not None:
            index = self.duplicates_location_combo.findData(
                previously_selected
            )
            if index >= 0:
                self.duplicates_location_combo.setCurrentIndex(index)

    def _selected_duplicates_location(self) -> str | None:
        name = self.duplicates_location_combo.currentData()
        return str(name) if name is not None else None

    def _selected_duplicates_location_id(self) -> int | None:
        # The combo stays enabled in folder-scope mode now, and its
        # selection is passed through as resolve_folder_scopes()'s
        # tiebreak preference rather than being dead weight while
        # checked (HISTORY §77).
        name = self._selected_duplicates_location()
        if name is None:
            return None
        location = self._duplicates_locations_by_name.get(name)
        return location.id if location else None

    def _selected_duplicates_folders(self) -> list[str]:
        if not self.duplicates_folders_checkbox.isChecked():
            return []
        return list(self._duplicates_folder_paths)

    def _on_duplicates_folders_toggled(self, checked: bool) -> None:
        self.duplicates_folders_panel.setVisible(checked)
        self._refresh_duplicates_folder_scope_count()

    def _on_duplicates_location_changed(self) -> None:
        # A location-combo change can change which real location a tied
        # folder scope resolves to, so the scope count must reflect it
        # live, not just sit stale until the next folder is
        # added/removed (HISTORY §77).
        self._refresh_duplicates_folder_scope_count()

    def _on_add_duplicates_folder_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose a folder to add to the scope"
        )

        if not path or path in self._duplicates_folder_paths:
            return

        self._duplicates_folder_paths.append(path)
        self.duplicates_folders_list.addItem(path)
        self._refresh_duplicates_folder_scope_count()

    def _on_remove_duplicates_folder_clicked(self) -> None:
        for item in self.duplicates_folders_list.selectedItems():
            path = item.text()
            self.duplicates_folders_list.takeItem(
                self.duplicates_folders_list.row(item)
            )
            if path in self._duplicates_folder_paths:
                self._duplicates_folder_paths.remove(path)

        self._refresh_duplicates_folder_scope_count()

    def _refresh_duplicates_folder_scope_count(self) -> None:
        if (
                not self.duplicates_folders_checkbox.isChecked()
                or not self._duplicates_folder_paths
        ):
            self.duplicates_scope_count_label.setText("")
            return

        folders = list(self._duplicates_folder_paths)
        preferred_location_id = self._selected_duplicates_location_id()

        def compute_summary() -> Any:
            service = self._context.application.duplicate_service
            scopes = service.resolve_folder_scopes(
                folders, preferred_location_id=preferred_location_id,
            )
            return service.summarize_scopes(scopes)

        run_worker(
            self._context.thread_pool, compute_summary,
            on_finished=lambda summary: self.duplicates_scope_count_label.setText(
                help_text.format_duplicates_scope_count(summary)
            ),
            on_error=self.duplicates_scope_count_label.setText,
        )

    def _on_compute_fingerprints_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            preferred_location_id = self._selected_duplicates_location_id()
            self._context.run_busy_worker(
                "compute_fingerprints", self.compute_fingerprints_button,
                lambda progress: self._compute_fingerprints_for_folders(
                    folders, progress, preferred_location_id,
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._render_fingerprint_result,
                on_error=self.feedback.show_error,
                reports_progress=True,
            )
            self.feedback.show_progress(
                f"Computing fingerprints for {len(folders)} folder(s)…"
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.feedback.show_outcome(
                "Select a library location first.", kind="warning",
            )
            return

        self._context.run_busy_worker(
            "compute_fingerprints", self.compute_fingerprints_button,
            lambda progress: (
                self._context.application.duplicate_service.compute_fingerprints(
                    location_name, progress=progress,
                    stop=self._context.quitting,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_fingerprint_result,
            on_error=self.feedback.show_error,
            reports_progress=True,
        )
        self.feedback.show_progress(
            f"Computing fingerprints for '{location_name}'…"
        )

    def _compute_fingerprints_for_folders(
            self,
            folders: list[str],
            progress: Callable[[str, int, int], None],
            preferred_location_id: int | None = None,
    ) -> FingerprintResult:
        # compute_fingerprints() is itself scoped to one library
        # location per call; folder mode can span more than one
        # (find_duplicate_groups_across_scopes' own cross-location
        # pooling), so this groups the resolved scopes by location,
        # calls it once per location, and translates each call's own
        # 1..N progress into a running offset against the real combined
        # total — so the activity strip still reads 1..total once, not
        # resetting partway through (HISTORY §68).
        service = self._context.application.duplicate_service
        scopes = service.resolve_folder_scopes(
            folders, preferred_location_id=preferred_location_id,
        )
        total = service.count_files_for_scopes(scopes)

        folders_by_location: dict[str, list[str]] = {}
        for scope in scopes:
            folders_by_location.setdefault(
                scope.location.name, [],
            ).append(scope.folder_relative_path)

        combined = FingerprintResult()
        completed_before = 0

        for location_name, relative_folders in folders_by_location.items():
            def report(
                    stage: str, current: int, _total: int,
                    offset: int = completed_before,
            ) -> None:
                progress(stage, offset + current, total)

            result = service.compute_fingerprints(
                location_name, folders=relative_folders, progress=report,
                stop=self._context.quitting,
            )
            combined += result

            if result.stopped:
                break

            completed_before += (
                result.computed
                + result.skipped_already_computed
                + result.failed
            )

        return combined

    def _render_fingerprint_result(self, result: FingerprintResult) -> None:
        self.feedback.show_outcome(
            help_text.format_fingerprint_result_message(result),
            kind="warning" if result.failed else "success",
        )

    def _on_find_duplicates_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            preferred_location_id = self._selected_duplicates_location_id()

            self._context.run_busy_worker(
                "find_duplicates", self.find_duplicates_button,
                lambda progress: (
                    self._context.application.duplicate_service
                    .find_duplicate_groups_across_scopes(
                        self._context.application.duplicate_service
                        .resolve_folder_scopes(
                            folders,
                            preferred_location_id=preferred_location_id,
                        ),
                        progress=progress,
                        stop=self._context.quitting,
                    )
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._on_duplicate_groups_found,
                on_error=self.feedback.show_error,
                reports_progress=True,
            )
            self.feedback.show_progress(
                f"Searching for duplicates in {len(folders)} folder(s)…"
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.feedback.show_outcome(
                "Select a library location first.", kind="warning",
            )
            return

        self._context.run_busy_worker(
            "find_duplicates", self.find_duplicates_button,
            lambda progress: (
                self._context.application.duplicate_service.find_duplicate_groups(
                    location_name, progress=progress,
                    stop=self._context.quitting,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._on_duplicate_groups_found,
            on_error=self.feedback.show_error,
            reports_progress=True,
        )
        self.feedback.show_progress(
            f"Searching for duplicates in '{location_name}'…"
        )

    def _on_duplicates_keep_toggled(
            self, group_key: frozenset[int], button_id: int, checked: bool,
    ) -> None:
        if checked:
            self._duplicates_keep_selection[group_key] = button_id

    def _keep_id(self, group: DuplicateGroup) -> int | None:
        """The file id the group keeps, or `KEEP_ALL_DUPLICATES_ID`:
        the person's choice when they made one, else the best-quality
        file, which the render preselects."""
        default_keep_id = group.files[0].local_file.id if group.files else None
        return self._duplicates_keep_selection.get(
            _group_key(group), default_keep_id,
        )

    def _on_delete_confirm_toggled(
            self, group_key: frozenset[int], checked: bool,
    ) -> None:
        if checked:
            self._delete_confirmed.add(group_key)
        else:
            self._delete_confirmed.discard(group_key)

    def _on_duplicate_groups_found(self, groups: list[DuplicateGroup]) -> None:
        self._render_duplicate_groups(groups)
        self.feedback.show_outcome(
            help_text.format_duplicate_groups_found(len(groups)),
            kind="success" if groups else "info",
        )

    def _render_duplicate_groups(self, groups: list[DuplicateGroup]) -> None:
        for index in list(self._shown_groups):
            self._hide_group_widgets(index)
        self._group_first_rows = []
        self._delete_confirmed = set()
        # Kept so a single-group resolution can drop just that group and
        # re-render locally afterward — see _on_delete_duplicates_finished's
        # own docstring for why re-fetching via find_duplicate_groups()
        # after every resolution is not an option at real scale.
        self._current_duplicate_groups = groups

        # setRowCount() does NOT clear spans, so a stale span from a
        # PREVIOUS render (different group shapes) could silently hide
        # a real Actions widget under a new row that happens to land
        # inside an old span's coverage. Confirmed via grep: this was
        # never called anywhere in this file before (HISTORY §73).
        self.duplicates_table.clearSpans()

        # Prune selection state for groups no longer present (resolved,
        # or no longer clustered together). Runs even for an empty
        # `groups` list (the early-return branch right below) — a "no
        # duplicates found" render must not leave stale selections
        # sitting in the map forever either (HISTORY §86).
        live_group_keys = {
            frozenset(f.local_file.id for f in group.files)
            for group in groups
        }
        self._duplicates_keep_selection = {
            key: value
            for key, value in self._duplicates_keep_selection.items()
            if key in live_group_keys
        }

        self._render_resolve_all_button(len(groups))

        if not groups:
            self.duplicates_table.setRowCount(0)
            return

        total_rows = sum(len(group.files) for group in groups)
        self.duplicates_table.setRowCount(total_rows)

        first_rows: list[int] = []
        row = 0
        for group_index, group in enumerate(groups, start=1):
            group_first_row = row
            first_rows.append(group_first_row)

            # Every other group sits on a band, so where one group
            # ends reads without a column of numbers.
            banded = group_index % 2 == 0

            def group_item(
                    text: str = "", banded: bool = banded,
            ) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setData(BAND_ROLE, banded)
                return item

            for duplicate_file in group.files:
                local_file = duplicate_file.local_file
                quality = duplicate_file.quality

                # Location + full relative path — "the same file in two
                # folders" is a judgement the user needs the real path
                # to make, not just a bare filename (HISTORY §56 Phase
                # 6.3). Resolved PER FILE rather than from one outer
                # variable — a pooled, cross-location folder-scope
                # result can put files from two different real
                # locations in the same group (HISTORY §68).
                file_location = self._duplicates_locations_by_id.get(
                    local_file.location_id
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.LOCATION,
                    group_item(file_location.name if file_location else "—"),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.PATH,
                    group_item(local_file.relative_path),
                )
                quality_text = local_file.format.upper()
                if quality.bitrate_kbps:
                    quality_text += f", {quality.bitrate_kbps} kbps"
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.QUALITY, group_item(quality_text),
                )
                # The item under the radio carries the band.
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.KEEP, group_item(),
                )

                row += 1

            # setSpan() BEFORE setCellWidget() (`_show_group_widgets`)
            # for the group's first row, so the real widget's geometry
            # is computed against the final spanned rect, not a
            # single-cell rect that a later setSpan() call then silently
            # changes underneath it. And no widget of any kind (blank
            # or otherwise) goes on the covered rows: a blank QWidget()
            # there used to get resolved by Qt's own span geometry to
            # the EXACT SAME rect as the real widget (visualRect()
            # resolves every cell inside a span to the whole span's
            # rect) and, being added to the viewport later, painted over
            # it — confirmed live via childAt(center of the Actions
            # cell) returning the blank widget, not the real one, before
            # this fix. The span itself is what makes the covered rows
            # read as blank; no cell widget is needed there at all
            # (HISTORY §77).
            for column in (
                    _DuplicatesColumn.SIMILARITY, _DuplicatesColumn.ACTIONS,
            ):
                self.duplicates_table.setSpan(
                    group_first_row, column, len(group.files), 1,
                )
            self.duplicates_table.setItem(
                group_first_row, _DuplicatesColumn.SIMILARITY,
                group_item(f"{group.similarity:.1%}"),
            )
            self.duplicates_table.setItem(
                group_first_row, _DuplicatesColumn.ACTIONS, group_item(),
            )

        self._group_first_rows = first_rows
        self._show_groups_in_view()
        # Every group's Actions are the same controls, so the shown
        # ones size the ACTIONS column for all (HISTORY §73).
        self._size_duplicates_columns([
            self._actions_widget(shown) for shown in self._shown_groups.values()
        ])
        self._fit_group_heights()
        # The sizing moved rows: settle which groups are near the view.
        self._show_groups_in_view()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
                watched is self.duplicates_table.viewport()
                and event.type() == QEvent.Type.Resize
        ):
            self._show_groups_in_view()
        return super().eventFilter(watched, event)

    def _groups_near_view(self) -> range:
        """The indexes of the groups in view, and of those within a
        view's height above or below it."""
        table = self.duplicates_table
        if not self._group_first_rows:
            return range(0)
        height = table.viewport().height()
        first = max(table.rowAt(0), 0)
        last = table.rowAt(height - 1) if height > 0 else first
        if last < 0:
            last = table.rowCount() - 1
        margin = last - first + 1
        start = bisect_right(self._group_first_rows, first - margin) - 1
        stop = bisect_right(self._group_first_rows, last + margin)
        return range(max(start, 0), stop)

    def _show_groups_in_view(self) -> None:
        """Gives the groups near the view their Keep radios and Actions,
        and takes every other group's away. Qt repositions every cell
        widget on each resize step, so all 1,800 groups' widgets held a
        fullscreen transition's main thread ~2 s (HISTORY §234). A
        group's keep choice and confirm tick live on the page, so its
        rebuilt widgets show them again."""
        near = self._groups_near_view()
        for index in [i for i in self._shown_groups if i not in near]:
            self._hide_group_widgets(index)
        for index in near:
            if index not in self._shown_groups:
                self._show_group_widgets(index)

    def _show_group_widgets(self, index: int) -> None:
        group = self._current_duplicate_groups[index]
        first_row = self._group_first_rows[index]
        group_key = _group_key(group)
        # group.files is ranked best-quality-first (see DuplicateGroup's
        # own docstring), so files[0] is the group's recommendation,
        # preselected but never auto-applied; a person's own choice,
        # recorded on every toggle, wins over it (HISTORY §86).
        keep_id = self._keep_id(group)
        button_group = QButtonGroup(self.duplicates_table)
        button_group.idToggled.connect(
            lambda button_id, checked: self._on_duplicates_keep_toggled(
                group_key, button_id, checked,
            )
        )
        for offset, duplicate_file in enumerate(group.files):
            local_file = duplicate_file.local_file
            assert local_file.id is not None
            keep_radio = QRadioButton()
            keep_radio.setToolTip(help_text.TOOLTIP_KEEP_FILE_RADIO)
            keep_radio.setAccessibleName(f"Keep {local_file.relative_path}")
            keep_radio.setChecked(local_file.id == keep_id)
            # The button's own id IS the local_file_id -- checkedId()
            # reads it back directly, no separate id-to-file mapping
            # needed.
            button_group.addButton(keep_radio, id=local_file.id)
            self.duplicates_table.setCellWidget(
                first_row + offset, _DuplicatesColumn.KEEP, keep_radio,
            )
        self.duplicates_table.setCellWidget(
            first_row, _DuplicatesColumn.ACTIONS,
            self._build_duplicate_group_actions(group, button_group, keep_id),
        )
        self._shown_groups[index] = _ShownGroup(
            group_key, range(first_row, first_row + len(group.files)),
            button_group,
        )

    def _hide_group_widgets(self, index: int) -> None:
        shown = self._shown_groups.pop(index)
        for row in shown.rows:
            self.duplicates_table.removeCellWidget(row, _DuplicatesColumn.KEEP)
        self.duplicates_table.removeCellWidget(
            shown.rows.start, _DuplicatesColumn.ACTIONS,
        )
        shown.button_group.deleteLater()
        self._delete_enablers.pop(shown.key, None)

    def _actions_widget(self, shown: _ShownGroup) -> QWidget:
        widget = self.duplicates_table.cellWidget(
            shown.rows.start, _DuplicatesColumn.ACTIONS,
        )
        assert widget is not None
        return widget

    def _fit_group_heights(self) -> None:
        """Gives every group's first row the height a shown group's
        took from its Actions: a group out of view has none, so its
        rows would otherwise change height as it scrolls into view."""
        if not self._shown_groups:
            return
        shown = next(iter(self._shown_groups.values()))
        head_height = self.duplicates_table.rowHeight(shown.rows.start)
        for first_row in self._group_first_rows:
            if self.duplicates_table.rowHeight(first_row) < head_height:
                self.duplicates_table.setRowHeight(first_row, head_height)

    def _configure_duplicates_columns(self) -> None:
        """A real, live-measured floor for the Actions column, closing
        the actual reported bug: at the app's real 960x640 minimum
        window size, against real production duplicate groups, this
        widget's own visibleRegion() was confirmed (0,0,0,0) — fully
        invisible, not merely clipped — because NOTHING in this app
        ever set a column width, so Actions (column 7 of 8) got
        whatever tiny sliver setStretchLastSection's leftover-space
        math happened to leave it. Fixed mode + an explicit width
        DERIVED from the real widget's own sizeHint() (never a magic
        number) makes this column immune to that squeeze regardless of
        window width (HISTORY §73).

        Split off from `_size_duplicates_columns` so an empty table
        gets this layout at construction, not only on its first
        populated render (HISTORY §114).
        """
        theme.configure_columns(self.duplicates_table, _DUPLICATES_COLUMNS)

    def _size_duplicates_columns(
            self, action_widgets: list[QWidget],
    ) -> None:
        theme.size_columns(
            self.duplicates_table, _DUPLICATES_COLUMNS, action_widgets,
        )

    def _build_duplicate_group_actions(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
            keep_id: int | None,
    ) -> QWidget:
        # "The same file living in several folders is sometimes
        # deliberate." An additional button in the group's EXISTING
        # QButtonGroup (a sentinel id, not a separate control/group) so
        # the "selecting one deselects the others" behavior is preserved
        # and simply extended, not reimplemented (HISTORY §56) .
        keep_all_radio = QRadioButton("Keep all")
        keep_all_radio.setToolTip(help_text.TOOLTIP_KEEP_ALL_DUPLICATES_RADIO)
        # Same preserved-selection treatment as the per-file keep radios
        # (HISTORY §86).
        keep_all_radio.setChecked(keep_id == KEEP_ALL_DUPLICATES_ID)
        button_group.addButton(keep_all_radio, id=KEEP_ALL_DUPLICATES_ID)

        confirm_checkbox = QCheckBox("Confirm delete")
        confirm_checkbox.setToolTip(
            help_text.TOOLTIP_DELETE_DUPLICATES_CHECKBOX
        )

        delete_button = QPushButton("Delete")
        delete_button.setToolTip(help_text.TOOLTIP_DELETE_DUPLICATES_BUTTON)
        group_key = _group_key(group)
        confirm_checkbox.setChecked(group_key in self._delete_confirmed)
        confirm_checkbox.toggled.connect(
            lambda checked: self._on_delete_confirm_toggled(group_key, checked)
        )
        delete_button.clicked.connect(
            lambda: self._on_delete_duplicates_clicked(group)
        )

        def _update_delete_enabled() -> None:
            # "Keep all" selected means there is nothing to delete.
            delete_button.setEnabled(
                button_group.checkedId() != KEEP_ALL_DUPLICATES_ID
                and group_key not in self._running_deletes
            )

        button_group.buttonToggled.connect(
            lambda _button, _checked: _update_delete_enabled()
        )
        self._delete_enablers[group_key] = _update_delete_enabled
        _update_delete_enabled()

        row_label = f"duplicates of {group.files[0].local_file.relative_path}"
        # Two lines, not one: a group spans at least two rows, and one
        # line was the widest cell in the table, leaving Path too
        # little at 960 wide (HISTORY §176).
        container = QWidget()
        container.setObjectName("cellWidgetContainer")
        lines = QVBoxLayout(container)
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(0)
        lines.addWidget(
            theme.cell_widget(
                keep_all_radio, confirm_checkbox, row_label=row_label,
            ),
        )
        lines.addWidget(theme.cell_widget(delete_button, row_label=row_label))
        lines.addStretch()
        return container

    def _on_delete_duplicates_clicked(self, group: DuplicateGroup) -> None:
        if _group_key(group) not in self._delete_confirmed:
            # The standing rule against touching a file without
            # confirmation applies in full here: a click alone is only
            # the FIRST signal (which file to keep); the checkbox is
            # the second, explicit one, mirroring the Review tab's own
            # Replace + "Delete old file" checkbox pair. Neither one
            # alone deletes anything.
            self.feedback.show_outcome(
                "Check \"Confirm delete\" before deleting duplicate "
                "files.",
                kind="warning",
            )
            return

        keep_id = self._keep_id(group)

        if keep_id is None or keep_id == KEEP_ALL_DUPLICATES_ID:
            # Defense in depth — the Delete button is already disabled
            # in this state, but nothing structurally prevents this
            # method being reached some other way.
            return

        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        # Resolved PER FILE via local_file.location_id rather than one
        # "current location": a pooled, cross-location folder-scope
        # group can hold files from more than one real registered
        # location (HISTORY §68). Deleting real user files warrants
        # naming them: the exact full paths about to be deleted, not
        # just a bare count, in a second, explicit confirmation
        # (HISTORY §56).
        paths_to_delete = [
            str(
                Path(
                    self._duplicates_locations_by_id[
                        duplicate_file.local_file.location_id
                    ].path
                ) / duplicate_file.local_file.relative_path
            )
            for duplicate_file in group.files
            if duplicate_file.local_file.id in delete_ids
            and duplicate_file.local_file.location_id
            in self._duplicates_locations_by_id
        ]

        # Purely informational provenance on the resulting
        # duplicate_cleanups row (DuplicateService.delete_local_files'
        # own docstring) — the KEPT file's location is the most
        # meaningful single answer to "where did this cleanup happen"
        # for a pooled, possibly cross-location group.
        keep_duplicate_file = next(
            (
                duplicate_file for duplicate_file in group.files
                if duplicate_file.local_file.id == keep_id
            ),
            None,
        )
        location_id = (
            keep_duplicate_file.local_file.location_id
            if keep_duplicate_file is not None else None
        )

        confirmed = plain_text.question(
            self,
            help_text.DELETE_DUPLICATES_CONFIRM_TITLE,
            help_text.format_delete_duplicates_confirm_body(paths_to_delete),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        # No button: the confirmation's nested event loop, or another
        # group's delete ending meanwhile, can rebuild the row, so the
        # enable rule of whichever row is rendered is reapplied.
        group_key = _group_key(group)

        def on_finished(result: dict[str, Any]) -> None:
            self._reapply_delete_enabled(group_key)
            self._on_delete_duplicates_finished(result, group)

        def on_error(message: str) -> None:
            self._reapply_delete_enabled(group_key)
            self.feedback.show_error(message)

        self._running_deletes.run(
            self._context.thread_pool, group_key, (),
            lambda: self._context.application.duplicate_service.delete_local_files(
                delete_ids, keep_id, location_id,
            ),
            status_label=self.duplicates_status_label,
            on_finished=on_finished,
            on_error=on_error,
        )
        self._reapply_delete_enabled(group_key)

    def _reapply_delete_enabled(self, group_key: frozenset[int]) -> None:
        enabler = self._delete_enablers.get(group_key)
        if enabler is not None:
            enabler()

    def _on_delete_duplicates_finished(
            self,
            result: dict[str, Any],
            group: DuplicateGroup,
    ) -> None:
        # Deliberately NOT a find_duplicate_groups() re-fetch after every
        # single-group resolution. That call recomputes the ENTIRE
        # location's clustering from scratch every time, by design
        # (never persisted, so a moved/rescanned file can't leave a
        # stale group behind) — real, live-verified cost against a real
        # ~3,100-file/344-group library was ~10 minutes (HISTORY §39).
        # Re-running that after every single group would make resolving
        # a real library's worth of duplicates one at a time completely
        # impractical (344 groups x ~10 minutes each). Instead, drop
        # just the resolved group from the in-memory list this tab
        # already holds and re-render from that — no backend call at
        # all.
        message = f"Deleted: {result['deleted']}, Failed: {result['failed']}."

        if result["failed"] > 0:
            # A partial failure means the DB/disk state for this group
            # may not actually match "fully resolved" (see
            # DuplicateService.delete_local_files' own per-item
            # semantics) — leave it visible rather than assuming it's
            # gone, so the user can see it's still there and retry.
            self.feedback.show_outcome(message, kind="warning")
            return

        self._current_duplicate_groups = [
            g for g in self._current_duplicate_groups if g is not group
        ]
        self._render_duplicate_groups(self._current_duplicate_groups)
        groups_left = len(self._current_duplicate_groups)
        self.feedback.show_outcome(
            f"{message} {help_text.format_duplicate_groups_left(groups_left)}",
            kind="success",
        )
        # A real deletion just happened (delete_local_files already
        # recorded it) — refresh the milestone total immediately rather
        # than waiting for the next page revisit.
        self.refresh_milestone()

    def _build_group_resolution_plan(
            self, group: DuplicateGroup, keep_id: int,
    ) -> tuple[GroupResolutionPlan, str, list[str]] | None:
        """The same per-group plan (real per-file location resolution,
        real absolute paths) `_on_delete_duplicates_clicked` builds for
        a single group, factored out so "Resolve all groups" can build
        the identical plan for every group without a second, drifting
        copy (HISTORY §88). `None` when there's nothing to delete or the
        keep selection doesn't resolve to a real file in this group
        (shouldn't happen for a real render, but never trusted blindly
        for a batch that deletes real files).
        """
        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        if not delete_ids:
            return None

        keep_duplicate_file = next(
            (
                duplicate_file for duplicate_file in group.files
                if duplicate_file.local_file.id == keep_id
            ),
            None,
        )

        if keep_duplicate_file is None:
            return None

        location_id = keep_duplicate_file.local_file.location_id
        keep_location = self._duplicates_locations_by_id.get(location_id)
        keep_path = (
            str(
                Path(keep_location.path)
                / keep_duplicate_file.local_file.relative_path
            )
            if keep_location is not None
            else keep_duplicate_file.local_file.relative_path
        )

        delete_paths = [
            str(
                Path(
                    self._duplicates_locations_by_id[
                        duplicate_file.local_file.location_id
                    ].path
                ) / duplicate_file.local_file.relative_path
            )
            for duplicate_file in group.files
            if duplicate_file.local_file.id in delete_ids
            and duplicate_file.local_file.location_id
            in self._duplicates_locations_by_id
        ]

        plan = GroupResolutionPlan(
            delete_local_file_ids=delete_ids,
            keep_local_file_id=keep_id,
            location_id=location_id,
        )

        return plan, keep_path, delete_paths

    def _render_resolve_all_button(self, count: int) -> None:
        # The render alone owns this button's enabled state; one a
        # finish re-enabled would offer groups a render may already
        # have dropped (HISTORY §145).
        button = self.resolve_all_duplicates_button
        button.setText(
            f"Resolve all groups ({count})" if count else "Resolve all groups"
        )
        button.setEnabled(
            count > 0
            and not self._context.busy_actions.is_running(
                RESOLVE_ALL_DUPLICATES_KEY,
            ),
        )

    def _on_resolve_all_duplicates_clicked(self) -> None:
        # Built fresh from what's actually on screen right now (the
        # current groups AND the current keep selections), never a
        # stale plan from an earlier click (HISTORY §76, §88).
        groups = self._current_duplicate_groups

        if not groups:
            return

        plans_with_labels: list[
                tuple[GroupResolutionPlan, str, list[str]]
        ] = []
        resolved_groups: list[DuplicateGroup] = []

        for group in groups:
            keep_id = self._keep_id(group)

            if keep_id is None or keep_id == KEEP_ALL_DUPLICATES_ID:
                # "Keep all" (or no resolvable keep target at all) is
                # never turned into a plan — skipped, not overridden.
                continue

            built = self._build_group_resolution_plan(group, keep_id)

            if built is None:
                continue

            plans_with_labels.append(built)
            resolved_groups.append(group)

        dialog = BulkResolveDuplicatesDialog(self, plans_with_labels)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if not plans_with_labels or not dialog.confirm_checkbox.isChecked():
            # Defense in depth — the confirm button is already disabled
            # in either state, but nothing structurally prevents this
            # method being reached some other way.
            return

        plans = [plan for plan, _, _ in plans_with_labels]

        self.resolve_all_duplicates_button.setEnabled(False)
        self._context.run_busy_worker(
            RESOLVE_ALL_DUPLICATES_KEY, None,
            lambda: self._context.application.duplicate_service.resolve_groups(
                plans, stop=self._context.quitting,
            ),
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_bulk_resolve_duplicates_finished(
                result, resolved_groups,
            ),
            on_error=self._on_bulk_resolve_duplicates_failed,
        )

    def _on_bulk_resolve_duplicates_failed(self, message: str) -> None:
        self.feedback.show_error(message)
        self._render_resolve_all_button(len(self._current_duplicate_groups))

    def _on_bulk_resolve_duplicates_finished(
            self,
            result: BulkDuplicateResolutionResult,
            attempted_groups: list[DuplicateGroup],
    ) -> None:
        plain_text.information(
            self,
            help_text.BULK_RESOLVE_DUPLICATES_DIALOG_TITLE,
            help_text.format_bulk_resolve_duplicates_result(result),
        )

        # Same "drop resolved groups locally, never a full
        # find_duplicate_groups() re-fetch" discipline as the
        # single-group flow (_on_delete_duplicates_finished's own
        # docstring) — a group that partially failed stays visible,
        # per plan_outcomes, so the user can see it's still there and
        # retry rather than assuming it's gone.
        succeeded_groups = {
            id(group)
            for group, succeeded in zip(
                attempted_groups, result.plan_outcomes, strict=True,
            )
            if succeeded
        }
        self._current_duplicate_groups = [
            group for group in self._current_duplicate_groups
            if id(group) not in succeeded_groups
        ]
        self._render_duplicate_groups(self._current_duplicate_groups)

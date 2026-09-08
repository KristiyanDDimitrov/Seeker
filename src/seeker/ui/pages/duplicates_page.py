"""The Duplicates page (HISTORY §119)."""

from collections.abc import Callable
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.library.duplicate_service import (
    BulkDuplicateResolutionResult,
    DuplicateGroup,
    GroupResolutionPlan,
)
from seeker.models.library_location import LibraryLocation
from seeker.ui import help_text, theme
from seeker.ui.dialogs import BulkResolveDuplicatesDialog
from seeker.ui.formatting import format_file_size
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.workers import run_worker

# A sentinel QButtonGroup id for the "Keep all" option, sharing the
# same group as the per-file keep radios so selecting one deselects the
# others (the exact behavior the user asked to keep). Real local_file
# ids are always positive (AUTOINCREMENT starts at 1), so 0 can never
# collide with one — and, confirmed live, -1 specifically CANNOT be
# used here: QButtonGroup.addButton(button, id=-1) doesn't set the id
# to -1 at all — Qt treats -1 as its own "auto-assign an id" sentinel
# and silently substitutes a different, Qt-generated negative id
# (checkedId() returned -2 in a real, direct repro), breaking any
# comparison against a real -1 constant (HISTORY §56 Phase 6.3).
KEEP_ALL_DUPLICATES_ID = 0

# Named constants for the duplicates table's real column layout,
# replacing literal indices scattered across the render path. Two
# independent investigations could NOT reproduce a genuine index-vs-
# header mismatch; this hardening exists so that bug CLASS becomes
# structurally impossible regardless, and so the regression test can
# resolve "Actions" by its real header text instead of sharing the same
# literal the render code uses (a test that shares the code's own
# mistake proves nothing) (HISTORY §68).
class _DuplicatesColumn(IntEnum):
    GROUP = 0
    LOCATION = 1
    PATH = 2
    FORMAT = 3
    BITRATE = 4
    SIMILARITY = 5
    KEEP = 6
    ACTIONS = 7


_DUPLICATES_COLUMN_HEADERS = [
    "Group", "Location", "Path", "Format", "Bitrate", "Similarity",
    "Keep", "Actions",
]

# The declarative layout each table used to write out by hand across a
# `_configure_*_columns`/`_size_*_columns` pair; see `theme.ColumnLayout`
# (HISTORY §118).
_DUPLICATES_COLUMNS = theme.ColumnLayout(
    stretch=(_DuplicatesColumn.PATH,),
    fit_content=(
        _DuplicatesColumn.GROUP, _DuplicatesColumn.LOCATION,
        _DuplicatesColumn.FORMAT, _DuplicatesColumn.BITRATE,
        _DuplicatesColumn.SIMILARITY, _DuplicatesColumn.KEEP,
    ),
    actions=_DuplicatesColumn.ACTIONS,
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

        # Persistent, cumulative, and celebratory. Hidden entirely at
        # zero — "an empty milestone is worse than no milestone,"
        # matching this app's existing "blank, not a misleading
        # control" precedent for a genuinely-nothing-to-show state
        # (HISTORY §56 Phase 6.4).
        self.duplicates_milestone_label = QLabel("")
        self.duplicates_milestone_label.hide()
        layout.addWidget(self.duplicates_milestone_label)

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

        layout.addLayout(controls)

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
        self.duplicates_scope_count_label = QLabel("")
        folders_panel_layout.addWidget(self.duplicates_scope_count_label)

        self.duplicates_folders_panel.setVisible(False)
        layout.addWidget(self.duplicates_folders_panel)

        duplicates_status_row = QHBoxLayout()
        self.duplicates_status_label = QLabel("")
        duplicates_status_row.addWidget(self.duplicates_status_label)
        duplicates_status_row.addStretch()
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
        duplicates_status_row.addWidget(self.resolve_all_duplicates_button)
        layout.addLayout(duplicates_status_row)

        self.duplicates_table = QTableWidget(
                0,
                len(_DUPLICATES_COLUMN_HEADERS),
        )
        self.duplicates_table.setHorizontalHeaderLabels(
            _DUPLICATES_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.duplicates_table)
        layout.addWidget(theme.make_card(self.duplicates_table))
        self._configure_duplicates_columns()

        # QButtonGroup instances (one per duplicate group, so only one
        # radio per group can be selected) have no Qt parent-child
        # ownership tie to the table cells their radios live in — kept
        # alive here for the same reason ui/workers.py's _callbacks
        # keeps a Worker reference until its own completion (HISTORY
        # §22): a Qt object with nothing else referencing it is a live
        # GC/use-after-free hazard, not just a style preference. Reset
        # on every render.
        self._duplicate_button_groups: list[QButtonGroup] = []
        self._current_duplicate_groups: list[DuplicateGroup] = []
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
        self._current_duplicates_location_name: str | None = None
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

        page = build_page(
            "Duplicates", help_text.DUPLICATES_TAB_SUBTITLE, content,
        )
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(page)

    def _refresh_duplicates_locations(self) -> None:
        run_worker(
            self._context.thread_pool,
            self._context.application.library_service.list_locations,
            on_finished=self._render_duplicates_locations,
        )

    def _refresh_duplicates_milestone(self) -> None:
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
        # be a real regression of its own (HISTORY §56 Phase 6.1).
        previously_selected = self._selected_duplicates_location()

        self.duplicates_location_combo.clear()
        # The real LibraryLocation (path for the delete-confirmation
        # dialog's exact full paths and the table's own Location
        # column; id for the reclaimed-space milestone's cleanup
        # record). Neither is carried on LocalFile/DuplicateFile at all
        # (only location_id, and not even that on the milestone side),
        # and find_duplicate_groups() is already scoped to one location
        # per call, so this is resolved once here rather than plumbed
        # through the service layer (HISTORY §56 Phase 6.3/6.4).
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
                reports_progress=True,
            )
            self.duplicates_status_label.setText(
                f"Computing fingerprints for {len(folders)} folder(s)..."
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        self._context.run_busy_worker(
            "compute_fingerprints", self.compute_fingerprints_button,
            lambda progress: (
                self._context.application.duplicate_service.compute_fingerprints(
                    location_name, progress=progress,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_fingerprint_result,
            reports_progress=True,
        )
        self.duplicates_status_label.setText(
            f"Computing fingerprints for '{location_name}'..."
        )

    def _compute_fingerprints_for_folders(
            self,
            folders: list[str],
            progress: Callable[[str, int, int], None],
            preferred_location_id: int | None = None,
    ) -> dict[str, Any]:
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

        combined: dict[str, Any] = {
            "computed": 0,
            "skipped_already_computed": 0,
            "failed": 0,
            "details": [],
        }
        completed_before = 0

        for location_name, relative_folders in folders_by_location.items():
            def report(
                    stage: str, current: int, _total: int,
                    offset: int = completed_before,
            ) -> None:
                progress(stage, offset + current, total)

            result = service.compute_fingerprints(
                location_name, folders=relative_folders, progress=report,
            )
            combined["computed"] += result["computed"]
            combined["skipped_already_computed"] += (
                result["skipped_already_computed"]
            )
            combined["failed"] += result["failed"]
            combined["details"].extend(result["details"])
            completed_before += (
                result["computed"]
                + result["skipped_already_computed"]
                + result["failed"]
            )

        return combined

    def _render_fingerprint_result(self, result: dict[str, Any]) -> None:
        self.duplicates_status_label.setText(
            help_text.format_fingerprint_result_message(result)
        )

    def _on_find_duplicates_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            # No single location applies to a pooled, possibly
            # cross-location result — _render_duplicate_groups resolves
            # each row's location individually via
            # _duplicates_locations_by_id instead.
            self._current_duplicates_location_name = None
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
                    )
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._render_duplicate_groups,
                reports_progress=True,
            )
            self.duplicates_status_label.setText(
                f"Searching for duplicates in {len(folders)} folder(s)..."
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        # The delete-confirmation dialog's full paths need a real
        # location; captured here rather than re-read from the combo
        # later, so a combo selection change while this search is still
        # running can't attach the wrong location name to the results
        # it eventually renders (HISTORY §56 Phase 6.3). The LOCATION
        # column itself resolves per-file, not from this — see
        # HISTORY §68.
        self._current_duplicates_location_name = location_name

        self._context.run_busy_worker(
            "find_duplicates", self.find_duplicates_button,
            lambda progress: (
                self._context.application.duplicate_service.find_duplicate_groups(
                    location_name, progress=progress,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_duplicate_groups,
            reports_progress=True,
        )
        self.duplicates_status_label.setText(
            f"Searching for duplicates in '{location_name}'..."
        )

    def _on_duplicates_keep_toggled(
            self, group_key: frozenset[int], button_id: int, checked: bool,
    ) -> None:
        if checked:
            self._duplicates_keep_selection[group_key] = button_id

    def _render_duplicate_groups(self, groups: list[DuplicateGroup]) -> None:
        self._duplicate_button_groups = []
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

        self.resolve_all_duplicates_button.setEnabled(len(groups) > 0)
        self.resolve_all_duplicates_button.setText(
            f"Resolve all groups ({len(groups)})" if groups
            else "Resolve all groups"
        )

        if not groups:
            self.duplicates_table.setRowCount(0)
            self.duplicates_status_label.setText(
                "No duplicates found. Run Compute fingerprints first if "
                "you haven't yet."
            )
            return

        self.duplicates_status_label.setText(
            f"Found {len(groups)} duplicate group(s)."
        )

        total_rows = sum(len(group.files) for group in groups)
        self.duplicates_table.setRowCount(total_rows)

        # Every real Actions widget built this render, so its true
        # widest sizeHint() can size the ACTIONS column for real below
        # (a per-group extra button — see _build_duplicate_group_actions
        # — means this isn't always the same width for every group)
        # (HISTORY §73).
        action_widgets: list[QWidget] = []

        row = 0
        for group_index, group in enumerate(groups, start=1):
            # group.files is already ranked best-quality-first (see
            # DuplicateGroup's own docstring) -- files[0] is this
            # group's own recommendation for which copy to keep,
            # pre-selected below but never auto-applied: the radio can
            # still be moved to any other file in the group before
            # Delete is ever clicked.
            button_group = QButtonGroup(self.duplicates_table)
            self._duplicate_button_groups.append(button_group)
            group_first_row = row

            # This group's stable key (its own member file ids) and
            # whatever was selected for it before the last rebuild, if
            # anything. Recorded back into the map on every real
            # toggle, not just read once here — the user can change
            # their mind more than once before Delete (HISTORY §86).
            group_key = frozenset(
                f.local_file.id for f in group.files
                if f.local_file.id is not None
            )
            previously_selected_id = self._duplicates_keep_selection.get(
                group_key
            )
            button_group.idToggled.connect(
                lambda button_id, checked, group_key=group_key: (
                    self._on_duplicates_keep_toggled(
                        group_key, button_id, checked,
                    )
                )
            )

            for file_index, duplicate_file in enumerate(group.files):
                local_file = duplicate_file.local_file
                quality = duplicate_file.quality
                assert local_file.id is not None

                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.GROUP,
                    QTableWidgetItem(str(group_index)),
                )
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
                    QTableWidgetItem(
                        file_location.name if file_location else "—"
                    ),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.PATH,
                    QTableWidgetItem(local_file.relative_path),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.FORMAT,
                    QTableWidgetItem(local_file.format),
                )
                bitrate_text = (
                    f"{quality.bitrate_kbps} kbps"
                    if quality.bitrate_kbps
                    else "—"
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.BITRATE,
                    QTableWidgetItem(bitrate_text),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.SIMILARITY,
                    QTableWidgetItem(f"{group.similarity:.1%}"),
                )

                keep_radio = QRadioButton()
                keep_radio.setToolTip(help_text.TOOLTIP_KEEP_FILE_RADIO)
                # Restore the user's own prior selection for this group
                # when there is one; only fall back to the "best
                # quality first" default when nothing was ever chosen
                # for it (HISTORY §86).
                keep_radio.setChecked(
                    local_file.id == previously_selected_id
                    if previously_selected_id is not None
                    else file_index == 0
                )
                # The button's own id IS the local_file_id -- checkedId()
                # below reads it back directly, no separate id-to-file
                # mapping needed.
                button_group.addButton(keep_radio, id=local_file.id)
                self.duplicates_table.setCellWidget(
                    row, _DuplicatesColumn.KEEP, keep_radio,
                )

                row += 1

            # setSpan() BEFORE setCellWidget() for the group's first
            # row, so the real widget's geometry is computed against
            # the final spanned rect, not a single-cell rect that a
            # later setSpan() call then silently changes underneath it.
            # And no widget of any kind (blank or otherwise) goes on
            # the covered rows: a blank QWidget() there used to get
            # resolved by Qt's own span geometry to the EXACT SAME rect
            # as the real widget (visualRect() resolves every cell
            # inside a span to the whole span's rect) and, being added
            # to the viewport later, painted over it — confirmed live
            # via childAt(center of the Actions cell) returning the
            # blank widget, not the real one, before this fix. The span
            # itself is what makes the covered rows read as blank; no
            # cell widget is needed there at all (HISTORY §77).
            self.duplicates_table.setSpan(
                group_first_row, _DuplicatesColumn.ACTIONS,
                len(group.files), 1,
            )
            group_actions_widget = self._build_duplicate_group_actions(
                group, button_group, previously_selected_id,
            )
            action_widgets.append(group_actions_widget)
            self.duplicates_table.setCellWidget(
                group_first_row, _DuplicatesColumn.ACTIONS,
                group_actions_widget,
            )

        self._size_duplicates_columns(action_widgets)

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
            previously_selected_id: int | None,
    ) -> QWidget:
        # "The same file living in several folders is sometimes
        # deliberate." An additional button in the group's EXISTING
        # QButtonGroup (a sentinel id, not a separate control/group) so
        # the "selecting one deselects the others" behavior is
        # preserved and simply extended, not reimplemented (HISTORY §56
        # Phase 6.3).
        keep_all_radio = QRadioButton("Keep all")
        keep_all_radio.setToolTip(help_text.TOOLTIP_KEEP_ALL_DUPLICATES_RADIO)
        # Same preserved-selection treatment as the per-file keep radios
        # above (HISTORY §86).
        keep_all_radio.setChecked(
            previously_selected_id == KEEP_ALL_DUPLICATES_ID
        )
        button_group.addButton(keep_all_radio, id=KEEP_ALL_DUPLICATES_ID)

        confirm_checkbox = QCheckBox("Confirm delete")
        confirm_checkbox.setToolTip(
            help_text.TOOLTIP_DELETE_DUPLICATES_CHECKBOX
        )

        delete_button = QPushButton("Delete")
        delete_button.setToolTip(help_text.TOOLTIP_DELETE_DUPLICATES_BUTTON)
        delete_button.clicked.connect(
            lambda: self._on_delete_duplicates_clicked(
                group, button_group, confirm_checkbox, delete_button,
            )
        )

        def _update_delete_enabled() -> None:
            # "Keep all" selected means there is nothing to delete.
            delete_button.setEnabled(
                button_group.checkedId() != KEEP_ALL_DUPLICATES_ID
            )

        button_group.buttonToggled.connect(
            lambda _button, _checked: _update_delete_enabled()
        )
        _update_delete_enabled()

        return theme.cell_widget(
                keep_all_radio,
                confirm_checkbox,
                delete_button,
        )

    def _on_delete_duplicates_clicked(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
            confirm_checkbox: QCheckBox,
            button: QPushButton,
    ) -> None:
        if not confirm_checkbox.isChecked():
            # The standing rule against touching a file without
            # confirmation applies in full here: a click alone is only
            # the FIRST signal (which file to keep); the checkbox is
            # the second, explicit one, mirroring the Review tab's own
            # Replace + "Delete old file" checkbox pair. Neither one
            # alone deletes anything.
            self.duplicates_status_label.setText(
                "Check \"Confirm delete\" before deleting duplicate "
                "files."
            )
            return

        keep_id = button_group.checkedId()

        if keep_id == KEEP_ALL_DUPLICATES_ID:
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
        # (HISTORY §56 Phase 6.3).
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

        confirmed = QMessageBox.question(
            self,
            help_text.DELETE_DUPLICATES_CONFIRM_TITLE,
            help_text.format_delete_duplicates_confirm_body(paths_to_delete),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.duplicate_service.delete_local_files(
                delete_ids, keep_id, location_id,
            ),
            button=button,
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_delete_duplicates_finished(
                result, group,
            ),
        )

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
            self.duplicates_status_label.setText(message)
            return

        self._current_duplicate_groups = [
            g for g in self._current_duplicate_groups if g is not group
        ]
        # _render_duplicate_groups sets its own "Found N group(s)"/"No
        # duplicates found" status text -- overwritten here afterward so
        # the deletion result is what the user actually sees.
        self._render_duplicate_groups(self._current_duplicate_groups)
        self.duplicates_status_label.setText(
            f"{message} {self.duplicates_status_label.text()}"
        )
        # A real deletion just happened (delete_local_files already
        # recorded it) — refresh the milestone total immediately rather
        # than waiting for the next page revisit.
        self._refresh_duplicates_milestone()

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

    def _on_resolve_all_duplicates_clicked(self) -> None:
        # Built fresh from what's actually on screen right now (the
        # current groups AND the current keep selections), never a
        # stale plan from an earlier click (HISTORY §76, §88).
        groups = self._current_duplicate_groups

        plans_with_labels: list[
                tuple[GroupResolutionPlan, str, list[str]]
        ] = []
        resolved_groups: list[DuplicateGroup] = []

        for group in groups:
            group_key = frozenset(
                f.local_file.id for f in group.files
                if f.local_file.id is not None
            )
            default_keep_id = (
                group.files[0].local_file.id if group.files else None
            )
            keep_id = self._duplicates_keep_selection.get(
                group_key, default_keep_id,
            )

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

        run_worker(
            self._context.thread_pool,
            lambda: self._context.application.duplicate_service.resolve_groups(
                plans,
            ),
            button=self.resolve_all_duplicates_button,
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_bulk_resolve_duplicates_finished(
                result, resolved_groups,
            ),
        )

    def _on_bulk_resolve_duplicates_finished(
            self,
            result: BulkDuplicateResolutionResult,
            attempted_groups: list[DuplicateGroup],
    ) -> None:
        QMessageBox.information(
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

"""Tests for the Duplicates page (seeker.ui.pages.duplicates_page).
Moved verbatim out of test_ui_smoke.py (round 8, §9.3.4, session
S11.6) — the mirror of §9.3.1's own Duplicates extraction (S10).

test_every_table_and_list_widget_is_routed_through_make_card stays in
test_ui_smoke.py as genuinely cross-cutting (it sweeps every page's
tables/lists in one test) — unmoved, but its own
table_and_list_attrs entries for Duplicates still touch
window._duplicates_page.duplicates_folders_list/duplicates_table directly.

BulkResolveDuplicatesDialog is imported from seeker.ui.dialogs
directly here, not re-exported from seeker.ui.main_window — that
re-export only existed for this file's own prior residence in
test_ui_smoke.py.
"""

import pytest
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
)

from seeker.models.library_location import LibraryLocation
from seeker.ui import help_text
from seeker.ui.dialogs import BulkResolveDuplicatesDialog
from seeker.ui.main_window import MainWindow
from test_ui_smoke import (
    FakeApplication,
    _confirm_yes,
    _duplicates_column,
    _make_duplicate_group,
    _make_duplicate_group_with_n_files,
    _switch_to_duplicates_tab,
)


def test_duplicates_tab_has_persistent_subtitle(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    duplicates_page = window.stacked_widget.widget(
        window._duplicates_page_index
    )
    labels = [w.text() for w in duplicates_page.findChildren(QLabel)]

    assert help_text.DUPLICATES_TAB_SUBTITLE in labels


def test_duplicates_milestone_hidden_when_nothing_reclaimed_yet(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicates_milestone((0, 0))

    assert window._duplicates_page.duplicates_milestone_label.isHidden()


def test_duplicates_milestone_shown_with_real_totals(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicates_milestone((312, 15_254_112_614))

    assert not window._duplicates_page.duplicates_milestone_label.isHidden()
    text = window._duplicates_page.duplicates_milestone_label.text()
    assert "reclaimed" in text
    assert "312 files" in text


def test_duplicates_tab_controls_have_tooltips(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._duplicates_page.duplicates_location_combo.toolTip() != ""
    assert window._duplicates_page.compute_fingerprints_button.toolTip() != ""
    assert window._duplicates_page.find_duplicates_button.toolTip() != ""
    assert window._duplicates_page.duplicates_folders_checkbox.toolTip() != ""
    assert window._duplicates_page.duplicates_add_folder_button.toolTip() != ""
    assert window._duplicates_page.duplicates_remove_folder_button.toolTip() != ""


def test_duplicates_folders_panel_hidden_until_checkbox_checked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._duplicates_page.duplicates_folders_panel.isHidden()

    window._duplicates_page.duplicates_folders_checkbox.setChecked(True)

    assert not window._duplicates_page.duplicates_folders_panel.isHidden()
    # Roadmap item 77 (P9) — the combo stays enabled in folder-scope
    # mode now: it's a real tiebreak preference for resolve_folder_
    # scopes' most-specific-wins matching (P8.2), not dead weight.
    assert window._duplicates_page.duplicates_location_combo.isEnabled()

    window._duplicates_page.duplicates_folders_checkbox.setChecked(False)

    assert window._duplicates_page.duplicates_folders_panel.isHidden()
    assert window._duplicates_page.duplicates_location_combo.isEnabled()


def test_duplicates_remove_folder_button_removes_selected_entry(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._duplicates_folder_paths = ["/music/Trance", "/music/House"]
    window._duplicates_page.duplicates_folders_list.addItem("/music/Trance")
    window._duplicates_page.duplicates_folders_list.addItem("/music/House")

    window._duplicates_page.duplicates_folders_list.setCurrentRow(0)
    window._duplicates_page._on_remove_duplicates_folder_clicked()

    assert window._duplicates_page._duplicates_folder_paths == ["/music/House"]
    assert window._duplicates_page.duplicates_folders_list.count() == 1
    assert (
        window._duplicates_page.duplicates_folders_list.item(0).text()
        == "/music/House"
    )


def test_duplicates_scope_count_updates_from_the_real_service(qtbot):
    application = FakeApplication()
    application.duplicate_service._scope_file_count = 42
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._duplicates_folder_paths = ["/music/Trance"]
    window._duplicates_page.duplicates_folders_list.addItem("/music/Trance")
    window._duplicates_page.duplicates_folders_checkbox.setChecked(True)

    qtbot.waitUntil(
        lambda: "42 files in scope" in (
            window._duplicates_page.duplicates_scope_count_label.text()
        ),
        timeout=2000,
    )
    assert (
        application.duplicate_service.resolve_folder_scopes_calls
        == [(["/music/Trance"], None)]
    )


def test_compute_fingerprints_in_folder_mode_calls_service_per_location(
        qtbot,
):
    from seeker.library.duplicate_service import DuplicateFolderScope

    location_a = LibraryLocation(
        id=1, name="A", path="/music/a", added_at="",
    )
    location_b = LibraryLocation(
        id=2, name="B", path="/music/b", added_at="",
    )
    scopes = [
        DuplicateFolderScope(location=location_a, folder_relative_path="Trance"),
        DuplicateFolderScope(location=location_b, folder_relative_path=""),
    ]
    application = FakeApplication(
        fingerprint_result={
            "computed": 1, "skipped_already_computed": 0, "failed": 0,
            "details": [],
        },
    )
    application.duplicate_service._folder_scopes = scopes
    application.duplicate_service._scope_file_count = 2
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._duplicates_folder_paths = ["/music/a/Trance", "/music/b"]
    window._duplicates_page.duplicates_folders_checkbox.setChecked(True)

    window._duplicates_page._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: len(
            application.duplicate_service.compute_fingerprints_calls
        ) == 2,
        timeout=2000,
    )
    assert sorted(
        application.duplicate_service.compute_fingerprints_calls
    ) == [("A", ["Trance"]), ("B", [""])]
    qtbot.waitUntil(
        lambda: "Fingerprinted: 2" in (
            window._duplicates_page.duplicates_status_label.text()
        ),
        timeout=2000,
    )


def test_find_duplicates_in_folder_mode_calls_across_scopes(qtbot):
    from seeker.library.duplicate_service import DuplicateFolderScope

    location = LibraryLocation(id=1, name="A", path="/music/a", added_at="")
    scopes = [
        DuplicateFolderScope(location=location, folder_relative_path="Trance"),
    ]
    application = FakeApplication()
    application.duplicate_service._folder_scopes = scopes
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._duplicates_folder_paths = ["/music/a/Trance"]
    window._duplicates_page.duplicates_folders_checkbox.setChecked(True)

    window._duplicates_page._on_find_duplicates_clicked()

    qtbot.waitUntil(
        lambda: bool(
            application.duplicate_service
            .find_duplicate_groups_across_scopes_calls
        ),
        timeout=2000,
    )
    assert (
        application.duplicate_service
        .find_duplicate_groups_across_scopes_calls == [scopes]
    )


def test_switching_to_duplicates_tab_loads_locations_lazily(qtbot):
    location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._duplicates_page.duplicates_location_combo.count() == 0

    _switch_to_duplicates_tab(window)

    qtbot.waitUntil(
        lambda: (
            window._duplicates_page.duplicates_location_combo.count() == 1
        ),
        timeout=2000,
    )
    assert window._duplicates_page.duplicates_location_combo.itemText(0) == "Main"


def test_switching_to_duplicates_tab_twice_refreshes_locations_each_time(
        qtbot,
):
    # Roadmap item 56 Phase 6.1 — reverses the old "loaded once ever"
    # guard: a location added after the first visit must actually
    # appear on a later revisit, which the old guard structurally
    # prevented (it was originally the fix for a real, confirmed Qt/
    # GIL deadlock from a CONSTRUCTION-time fetch — item 39 — not from
    # a page show, which is human-paced and doesn't reintroduce that
    # hazard).
    first_location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(first_location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: (
            window._duplicates_page.duplicates_location_combo.count() == 1
        ),
        timeout=2000,
    )
    assert window._duplicates_page.duplicates_location_combo.itemText(0) == "Main"

    # A location added since the first visit (mirrors adding one via
    # Settings, then coming back to Duplicates without restarting).
    second_location = LibraryLocation(
        id=2, name="Second", path="/music2",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application.library_service._locations = [
        (first_location, True), (second_location, True),
    ]

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: (
            window._duplicates_page.duplicates_location_combo.count() == 2
        ),
        timeout=2000,
    )
    assert {
        window._duplicates_page.duplicates_location_combo.itemText(i) for i in range(2)
    } == {"Main", "Second"}


def test_duplicates_location_refresh_preserves_the_current_selection(qtbot):
    first_location = LibraryLocation(
        id=1, name="Main", path="/music",
        added_at="2026-01-01T00:00:00+00:00",
    )
    second_location = LibraryLocation(
        id=2, name="Second", path="/music2",
        added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        locations=[(first_location, True), (second_location, True)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: (
            window._duplicates_page.duplicates_location_combo.count() == 2
        ),
        timeout=2000,
    )
    window._duplicates_page.duplicates_location_combo.setCurrentIndex(1)
    assert window._duplicates_page._selected_duplicates_location() == "Second"

    window._on_page_changed(window._duplicates_page_index)
    qtbot.waitUntil(
        lambda: (
            window._duplicates_page.duplicates_location_combo.count() == 2
        ),
        timeout=2000,
    )
    assert window._duplicates_page._selected_duplicates_location() == "Second"


def test_compute_fingerprints_without_selection_shows_message(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._on_compute_fingerprints_clicked()

    assert "Select a library location" in (
        window._duplicates_page.duplicates_status_label.text()
    )
    assert application.duplicate_service.compute_fingerprints_calls == []


def test_compute_fingerprints_calls_service_with_selected_location(qtbot):
    application = FakeApplication(
        fingerprint_result={
            "computed": 3, "skipped_already_computed": 1, "failed": 0,
            "details": [],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._duplicates_page._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: application.duplicate_service.compute_fingerprints_calls
        == [("Main", None)],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: "Fingerprinted: 3" in (
            window._duplicates_page.duplicates_status_label.text()
        ),
        timeout=2000,
    )


def test_compute_fingerprints_result_shows_failure_reason_breakdown(qtbot):
    # Roadmap item 68 (Phase 8.2) — a real per-reason breakdown, not
    # just an opaque "Failed: N".
    application = FakeApplication(
        fingerprint_result={
            "computed": 1, "skipped_already_computed": 0, "failed": 3,
            "details": [
                {"local_file_id": "1", "reason": "decode_unsupported", "message": "a"},
                {"local_file_id": "2", "reason": "decode_unsupported", "message": "b"},
                {"local_file_id": "3", "reason": "empty_file", "message": "c"},
            ],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._duplicates_page._on_compute_fingerprints_clicked()

    qtbot.waitUntil(
        lambda: "Failed: 3" in window._duplicates_page.duplicates_status_label.text(),
        timeout=2000,
    )
    status_text = window._duplicates_page.duplicates_status_label.text()
    assert "2 couldn't be decoded" in status_text
    assert "1 0-byte file" in status_text


def test_find_duplicates_without_selection_shows_message(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._on_find_duplicates_clicked()

    assert "Select a library location" in (
        window._duplicates_page.duplicates_status_label.text()
    )
    assert application.duplicate_service.find_duplicate_groups_calls == []


def test_find_duplicates_renders_no_duplicates_message(qtbot):
    application = FakeApplication(duplicate_groups=[])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )

    window._duplicates_page._on_find_duplicates_clicked()

    qtbot.waitUntil(
        lambda: "No duplicates found" in (
            window._duplicates_page.duplicates_status_label.text()
        ),
        timeout=2000,
    )
    assert window._duplicates_page.duplicates_table.rowCount() == 0


def test_render_duplicate_groups_populates_table(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    assert window._duplicates_page.duplicates_table.rowCount() == 2
    assert window._duplicates_page.duplicates_table.item(0, 2).text() == "a.flac"
    assert window._duplicates_page.duplicates_table.item(1, 2).text() == "a.mp3"
    assert window._duplicates_page.duplicates_table.item(0, 5).text() == "98.7%"


def test_render_duplicate_groups_preselects_the_best_quality_file_to_keep(
        qtbot,
):
    # group.files is already best-quality-first (a.flac, tier 2, over
    # a.mp3, tier 1) -- the radio on row 0 must be pre-checked, row 1
    # must not be, and neither is auto-applied without a later click.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    keep_radio_0 = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Keep"),
    )
    keep_radio_1 = window._duplicates_page.duplicates_table.cellWidget(
            1,
            _duplicates_column(window, "Keep"),
    )
    assert isinstance(keep_radio_0, QRadioButton)
    assert isinstance(keep_radio_1, QRadioButton)
    assert keep_radio_0.isChecked() is True
    assert keep_radio_1.isChecked() is False


# --- Roadmap item R3.2: "Resolve all groups" --------------------------------

def test_resolve_all_duplicates_button_disabled_when_no_groups(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicate_groups([])

    assert window._duplicates_page.resolve_all_duplicates_button.isEnabled() is False


def test_resolve_all_duplicates_uses_default_and_custom_keep_selections(
        qtbot, monkeypatch,
):
    group_a = _make_duplicate_group()  # ids 101 (flac), 102 (mp3)
    group_b = _make_duplicate_group_with_n_files(2)  # ids 200, 201
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([group_a, group_b])

    # Leave group_a (rows 0-1) on its default (best-quality) selection,
    # but move group_b's (rows 2-3) selection onto its SECOND file
    # (row 3, id 201) instead of the default (row 2, id 200).
    keep_column = _duplicates_column(window, "Keep")
    window._duplicates_page.duplicates_table.cellWidget(3, keep_column).setChecked(True)

    def fake_exec(self):
        self.confirm_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkResolveDuplicatesDialog, "exec", fake_exec)
    # Roadmap item C3 (round 5) — see the identical fix/comment on
    # test_replace_all_upgrades_button_calls_batch_with_every_request_id:
    # this test's own wait condition (resolve_groups_calls != []) can be
    # satisfied before `_on_bulk_resolve_duplicates_finished`'s real
    # QMessageBox.information() call has fired, leaving it queued to
    # pop a genuine blocking modal during a later test.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._duplicates_page.resolve_all_duplicates_button.click()

    qtbot.waitUntil(
        lambda: application.duplicate_service.resolve_groups_calls != [],
        timeout=2000,
    )
    plans = application.duplicate_service.resolve_groups_calls[0]
    assert len(plans) == 2
    plans_by_keep = {plan.keep_local_file_id: plan for plan in plans}
    assert plans_by_keep[101].delete_local_file_ids == [102]
    assert plans_by_keep[201].delete_local_file_ids == [200]


def test_resolve_all_duplicates_skips_keep_all_groups(qtbot, monkeypatch):
    group_a = _make_duplicate_group()  # ids 101, 102
    group_b = _make_duplicate_group_with_n_files(2)  # ids 200, 201
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([group_a, group_b])

    actions_column = _duplicates_column(window, "Actions")
    group_b_actions = window._duplicates_page.duplicates_table.cellWidget(
        2, actions_column,
    )
    keep_all_radio = next(
        w for w in group_b_actions.findChildren(QRadioButton)
        if w.text() == "Keep all"
    )
    keep_all_radio.setChecked(True)

    def fake_exec(self):
        self.confirm_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkResolveDuplicatesDialog, "exec", fake_exec)
    # Roadmap item C3 (round 5) — same real leaked-QMessageBox fix as
    # the two tests above.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._duplicates_page.resolve_all_duplicates_button.click()

    qtbot.waitUntil(
        lambda: application.duplicate_service.resolve_groups_calls != [],
        timeout=2000,
    )
    plans = application.duplicate_service.resolve_groups_calls[0]
    # Only group_a's plan -- group_b (Keep all) was skipped entirely,
    # never overridden.
    assert len(plans) == 1
    assert plans[0].keep_local_file_id == 101


def test_resolve_all_duplicates_cancelled_dialog_calls_nothing(
        qtbot,
        monkeypatch,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    monkeypatch.setattr(
        BulkResolveDuplicatesDialog, "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    window._duplicates_page.resolve_all_duplicates_button.click()

    assert application.duplicate_service.resolve_groups_calls == []


def test_resolve_all_duplicates_unconfirmed_checkbox_calls_nothing(
        qtbot, monkeypatch,
):
    # Defense in depth (R3.2) — even if exec() somehow returns Accepted
    # without the checkbox actually being checked, nothing real happens.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    monkeypatch.setattr(
        BulkResolveDuplicatesDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    window._duplicates_page.resolve_all_duplicates_button.click()

    assert application.duplicate_service.resolve_groups_calls == []


def test_resolve_all_duplicates_drops_only_succeeded_groups_locally(
        qtbot, monkeypatch,
):
    from seeker.library.duplicate_service import BulkDuplicateResolutionResult

    group_a = _make_duplicate_group()
    group_b = _make_duplicate_group_with_n_files(2)
    application = FakeApplication()
    application.duplicate_service.resolve_groups_result = (
        BulkDuplicateResolutionResult(
            groups_resolved=1, groups_failed=1, files_deleted=1,
            files_failed=1, files_skipped_same_physical_file=0,
            bytes_freed=10,
            details=["Group partially failed: 1 of 1 file(s) could not "
                     "be deleted."],
            plan_outcomes=[True, False],
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([group_a, group_b])

    def fake_exec(self):
        self.confirm_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkResolveDuplicatesDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._duplicates_page.resolve_all_duplicates_button.click()

    qtbot.waitUntil(
        lambda: window._duplicates_page.duplicates_table.rowCount() == 2, timeout=2000,
    )
    # group_a (succeeded, plan_outcomes[0]=True) is gone; group_b
    # (failed, plan_outcomes[1]=False) is still shown.
    assert len(window._duplicates_page._current_duplicate_groups) == 1
    assert window._duplicates_page._current_duplicate_groups[0] is group_b


def test_duplicate_groups_keep_selection_survives_rerender(qtbot):
    # Roadmap item R2.2/R2.6 — the user moves the "keep" selection off
    # the pre-selected best-quality file (row 0) onto row 1; a rerender
    # (e.g. after a local delete-finished re-render) must not silently
    # snap it back to the default.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    group = _make_duplicate_group()

    window._duplicates_page._render_duplicate_groups([group])
    keep_column = _duplicates_column(window, "Keep")
    window._duplicates_page.duplicates_table.cellWidget(1, keep_column).setChecked(True)

    for _ in range(3):
        window._duplicates_page._render_duplicate_groups([group])

    keep_radio_0 = window._duplicates_page.duplicates_table.cellWidget(0, keep_column)
    keep_radio_1 = window._duplicates_page.duplicates_table.cellWidget(1, keep_column)
    assert keep_radio_0.isChecked() is False
    assert keep_radio_1.isChecked() is True


def test_duplicate_groups_keep_all_selection_survives_rerender(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    group = _make_duplicate_group()

    window._duplicates_page._render_duplicate_groups([group])
    actions = window._duplicates_page.duplicates_table.cellWidget(
        0, _duplicates_column(window, "Actions"),
    )
    keep_all_radio = next(
        b for b in actions.findChildren(QRadioButton)
        if b.text() == "Keep all"
    )
    keep_all_radio.setChecked(True)

    window._duplicates_page._render_duplicate_groups([group])

    actions = window._duplicates_page.duplicates_table.cellWidget(
        0, _duplicates_column(window, "Actions"),
    )
    keep_all_radio = next(
        b for b in actions.findChildren(QRadioButton)
        if b.text() == "Keep all"
    )
    assert keep_all_radio.isChecked() is True
    keep_column = _duplicates_column(window, "Keep")
    assert window._duplicates_page.duplicates_table.cellWidget(
            0,
            keep_column,
    ).isChecked() is False
    assert window._duplicates_page.duplicates_table.cellWidget(
            1,
            keep_column,
    ).isChecked() is False


def test_duplicate_groups_keep_selection_pruned_when_group_removed(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    group = _make_duplicate_group()

    window._duplicates_page._render_duplicate_groups([group])
    keep_column = _duplicates_column(window, "Keep")
    window._duplicates_page.duplicates_table.cellWidget(1, keep_column).setChecked(True)
    assert len(window._duplicates_page._duplicates_keep_selection) == 1

    # The group is gone (resolved) -- R2.3's pruning.
    window._duplicates_page._render_duplicate_groups([])
    assert window._duplicates_page._duplicates_keep_selection == {}


def test_duplicates_actions_column_renders_with_a_real_service_and_real_fingerprinting(
        qtbot, tmp_path,
):
    # Roadmap item 56 Phase 6.2 — the reported bug ("Actions column is
    # empty") reproduced the same way item 40 originally verified it:
    # a real, offscreen MainWindow wired to a REAL DuplicateService
    # (real Database, real repositories), two real generated duplicate
    # .wav files in a disposable temp directory, real
    # compute_fingerprints/find_duplicate_groups (real libchromaprint),
    # never the real library. Investigated, not just asserted: checked
    # a first render, a full re-render (stale QTableWidget.setSpan from
    # a previous render was one live hypothesis), and the real
    # asynchronous run_worker click path (a queued cross-thread signal
    # behaves differently than a direct call).
    #
    # Roadmap item 73 (P4) — item 56's own conclusion here was wrong,
    # not this test's coverage: `isVisible()` is true even for a widget
    # clipped to near-zero real width, which is exactly what a real
    # production run at the app's own 960x640 minimum window size did
    # (confirmed live: a real 0px visibleRegion). Widened at the SAME
    # real pipeline this test already exercises, rather than replacing
    # it — now resizes to 960x640 and asserts real sectionSize/
    # visibleRegion geometry, not just presence + isVisible().
    import numpy as np
    import soundfile as sf

    from seeker import audio_fingerprint
    from seeker.database.connection import Database
    from seeker.database.repositories.library_location_repository import (
        LibraryLocationRepository,
    )
    from seeker.database.repositories.local_file_repository import (
        LocalFileRepository,
    )
    from seeker.database.repositories.track_match_repository import (
        TrackMatchRepository,
    )
    from seeker.library.duplicate_service import DuplicateService
    from seeker.library.scanner import LibraryScanner
    from seeker.models.library_location import LibraryLocation

    if audio_fingerprint._load_library() is None:
        pytest.skip("libchromaprint isn't installed on this machine")

    scratch = tmp_path / "dupes"
    scratch.mkdir()
    sample_rate = 44_100
    duration_seconds = 3
    t = np.linspace(
        0, duration_seconds, sample_rate * duration_seconds, endpoint=False,
    )
    tone = (0.2 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    sf.write(str(scratch / "a.wav"), tone, sample_rate)
    sf.write(str(scratch / "a_copy.wav"), tone, sample_rate)

    db = Database(tmp_path / "seeker.db")
    db.initialize()
    locations = LibraryLocationRepository(db)
    local_files = LocalFileRepository(db)
    track_matches = TrackMatchRepository(db)

    with db.transaction() as connection:
        locations.add(
            LibraryLocation(
                name="ReproDupes", path=str(scratch), added_at="2026-01-01",
            ),
            connection,
        )
        location = locations.get_by_name("ReproDupes", connection)

    duplicate_service = DuplicateService(
        db, locations, local_files, track_matches,
    )
    LibraryScanner(local_files, db).scan(location)
    duplicate_service.compute_fingerprints("ReproDupes")
    groups = duplicate_service.find_duplicate_groups("ReproDupes")
    assert len(groups) == 1  # sanity check: the real pair was found

    application = FakeApplication()
    application.duplicate_service = duplicate_service
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.resize(960, 640)
    window._show_page("duplicates")

    header = window._duplicates_page.duplicates_table.horizontalHeader()
    actions_column = _duplicates_column(window, "Actions")

    for _ in range(2):  # first render, then a full re-render
        window._duplicates_page._render_duplicate_groups(groups)
        qtbot.wait(20)
        widget = window._duplicates_page.duplicates_table.cellWidget(0, actions_column)
        assert widget is not None
        assert widget.isVisible()
        assert widget.findChild(QPushButton) is not None
        assert widget.findChild(QCheckBox) is not None

        assert header.sectionSize(actions_column) >= widget.sizeHint().width()
        visible_width = widget.visibleRegion().boundingRect().width()
        assert visible_width >= widget.sizeHint().width() - 2


def test_render_duplicate_groups_actions_only_on_group_first_row(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    first_row_actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    # Roadmap item 77 (P7, 5th report) — a covered row now gets NO cell
    # widget at all (not even a blank placeholder): a blank widget there
    # used to be resolved by the span to the exact same rect as the
    # real widget and paint over it. The span itself, not a widget,
    # is what makes the covered row read as blank.
    other_row_actions = window._duplicates_page.duplicates_table.cellWidget(
            1,
            _duplicates_column(window, "Actions"),
    )
    assert first_row_actions.findChildren(QPushButton)
    assert other_row_actions is None


def test_duplicates_actions_column_survives_manual_column_resize(qtbot):
    # Roadmap item 68 (Phase 7.1) — the one cheap extra check beyond the
    # index-hardening itself: a user manually drag-resizing a column
    # (setColumnWidth simulates this) must not disturb the Actions cell
    # widget's own correctness — Qt's view owns repositioning it.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions_column = _duplicates_column(window, "Actions")
    path_column = _duplicates_column(window, "Path")
    window._duplicates_page.duplicates_table.setColumnWidth(path_column, 500)
    window._duplicates_page.duplicates_table.setColumnWidth(actions_column, 50)

    widget = window._duplicates_page.duplicates_table.cellWidget(0, actions_column)
    assert widget is not None
    assert widget.findChild(QPushButton) is not None
    assert widget.findChild(QCheckBox) is not None


# --- Roadmap item 73 (P4): Actions column visibility + stale spans --------

def test_duplicates_actions_widget_is_really_visible_at_app_minimum_size(
        qtbot,
):
    # Regression test for the REAL reported bug, this brief's standing
    # rule #2: a test that only asserts cellWidget(row, col) returns a
    # widget is not a test that a user can SEE it -- three prior
    # investigations all asked that weaker question. This asserts real
    # geometry at the app's own real minimum window size (960x640,
    # main_window.py's setMinimumSize).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.resize(960, 640)
    window._show_page("duplicates")

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])
    qtbot.wait(20)

    header = window._duplicates_page.duplicates_table.horizontalHeader()
    actions_column = _duplicates_column(window, "Actions")
    widget = window._duplicates_page.duplicates_table.cellWidget(0, actions_column)
    assert widget is not None

    assert header.sectionSize(actions_column) >= widget.sizeHint().width()
    visible_width = widget.visibleRegion().boundingRect().width()
    # A small rounding/border gap between a widget's real width and its
    # own sizeHint is normal Qt layout behavior, not a visibility bug —
    # the actual regression this guards against is a widget clipped to
    # a SLIVER (confirmed live: a real 0px visibleRegion at 960x640
    # before this fix), not an exact-pixel match. Widened 2 -> 4px by
    # item E3 (round 7): removing make_card's universal `*` stylesheet
    # cascade let the button inside this cell widget draw its OWN real
    # 1px QPushButton border on each side for the first time (previously
    # forced off by the exact bug E3 fixed) — a genuine few-px shift in
    # its real rendered size, not a new visibility defect.
    assert visible_width >= widget.sizeHint().width() - 4


def test_duplicates_actions_widget_is_not_occluded_by_a_covered_row_widget(
        qtbot,
):
    # Roadmap item 77 (P7, 5th report) — the real root cause: a group
    # with more than one file used to place a blank QWidget() on every
    # row COVERED by the Actions span. QTableView resolves a spanned
    # region's geometry identically for every row inside the span, so
    # that blank widget landed on the EXACT SAME rect as the real
    # group_first_row widget and, being added later, painted over it —
    # confirmed live via a standalone PySide6 repro before this fix
    # (real geom == blank geom, child order REAL-then-BLANK,
    # childAt(center) returned the blank widget). Every prior
    # regression test (existence, geometry, visibleRegion) passed
    # anyway, because the real widget's own visibleRegion() is
    # non-empty even while occluded by a sibling — occlusion is a
    # z-order/paint-order property, not a geometry property. This test
    # is occlusion-aware: it asks what a real click would actually hit.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("duplicates")

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group_with_n_files(3)])
    qtbot.wait(20)

    actions_column = _duplicates_column(window, "Actions")
    real_widget = window._duplicates_page.duplicates_table.cellWidget(0, actions_column)
    assert real_widget is not None

    cell_rect = window._duplicates_page.duplicates_table.visualRect(
        window._duplicates_page.duplicates_table.model().index(0, actions_column)
    )
    hit = window._duplicates_page.duplicates_table.viewport().childAt(
        cell_rect.center()
    )
    assert hit is not None
    assert hit is real_widget or real_widget.isAncestorOf(hit)

    # And no widget at all should have been placed on the covered rows
    # — the span itself is what makes them read as blank.
    assert window._duplicates_page.duplicates_table.cellWidget(
        1, actions_column,
    ) is None
    assert window._duplicates_page.duplicates_table.cellWidget(
        2, actions_column,
    ) is None


def test_duplicates_actions_column_is_fixed_width_derived_from_sizehint(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    header = window._duplicates_page.duplicates_table.horizontalHeader()
    actions_column = _duplicates_column(window, "Actions")
    widget = window._duplicates_page.duplicates_table.cellWidget(0, actions_column)
    assert widget is not None

    assert (
        header.sectionResizeMode(actions_column)
        == QHeaderView.ResizeMode.Fixed
    )
    assert header.sectionSize(actions_column) == widget.sizeHint().width()


def test_duplicates_actions_widgets_all_visible_after_group_shape_changes(
        qtbot,
):
    # Regression test for the second, independent, CONFIRMED defect:
    # setRowCount() does not clear spans, so a big group's span from a
    # PREVIOUS render could still "own" a row that a later, differently-
    # shaped render's own span tries to claim as ITS OWN anchor. Every
    # prior investigation's test re-rendered with the SAME group shape,
    # which can never exercise this — this one deliberately doesn't.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("duplicates")

    # First render: one big 4-file group -- spans rows 0-3, anchored at
    # row 0.
    window._duplicates_page._render_duplicate_groups(
        [_make_duplicate_group_with_n_files(4)]
    )

    # Second render: two differently-shaped 2-file groups. Group B's own
    # span anchors at row 2 -- a row the FIRST render's span still
    # "owned" (as a non-anchor member) if clearSpans() were missing.
    window._duplicates_page._render_duplicate_groups(
        [
            _make_duplicate_group_with_n_files(2),
            _make_duplicate_group_with_n_files(2),
        ]
    )
    qtbot.wait(20)

    actions_column = _duplicates_column(window, "Actions")
    for group_first_row in (0, 2):
        widget = window._duplicates_page.duplicates_table.cellWidget(
            group_first_row, actions_column,
        )
        assert widget is not None
        assert widget.findChild(QPushButton) is not None
        assert (
            window._duplicates_page.duplicates_table.rowSpan(
                group_first_row, actions_column,
            )
            == 2
        )
        assert widget.isVisible()


def test_delete_duplicates_without_confirm_checkbox_does_not_delete(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    delete_button = actions.findChildren(QPushButton)[0]
    delete_button.click()

    assert application.duplicate_service.delete_local_files_calls == []
    assert "Confirm delete" in window._duplicates_page.duplicates_status_label.text()


def test_delete_duplicates_with_confirm_checkbox_deletes_non_kept_files(
        qtbot, monkeypatch,
):
    # a.flac (id 101) is pre-selected to keep (best quality) -- clicking
    # Delete with the checkbox checked must delete only a.mp3 (id 102).
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service.delete_local_files_calls = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    # location_id is the KEPT file's own local_file.location_id
    # (roadmap item 68 Phase 7.2) — resolved from the group itself, not
    # from a "current location" the UI happens to have loaded, so this
    # is correct even in this test's direct _render_duplicate_groups()
    # call with no combo selection made.
    assert application.duplicate_service.delete_local_files_calls == [
            ([102], 101, 1)
    ]


def test_delete_duplicates_respects_a_changed_keep_selection(
        qtbot,
        monkeypatch,
):
    # Moving the radio to a.mp3 (id 102) before deleting must delete
    # a.flac (id 101) instead of the pre-selected default.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    window._duplicates_page.duplicates_table.cellWidget(
            1,
            _duplicates_column(window, "Keep"),
    ).setChecked(True)

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    assert application.duplicate_service.delete_local_files_calls == [
            ([101], 102, 1)
    ]


def test_delete_duplicates_finished_removes_group_locally_without_refetch(
        qtbot, monkeypatch,
):
    # Deliberately NOT a find_duplicate_groups() re-fetch after a
    # single-group resolution -- that call recomputes an entire
    # location's clustering from scratch every time, confirmed live to
    # cost ~10 real minutes over a real ~3,100-file/344-group library
    # (docs/HISTORY.md item 39). Resolving groups one at a time must
    # drop each one from the in-memory list this tab already holds
    # instead, with zero additional service calls.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service._delete_result = {
        "deleted": 1, "failed": 0, "details": [],
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: "Deleted: 1, Failed: 0" in (
            window._duplicates_page.duplicates_status_label.text()
        ),
        timeout=2000,
    )
    assert application.duplicate_service.find_duplicate_groups_calls == []
    assert window._duplicates_page.duplicates_table.rowCount() == 0
    assert window._duplicates_page._current_duplicate_groups == []


def test_delete_duplicates_partial_failure_keeps_group_visible(
        qtbot,
        monkeypatch,
):
    # A partial failure means the group's real DB/disk state may not
    # actually match "fully resolved" -- it must stay visible rather
    # than being dropped as if it were.
    _confirm_yes(monkeypatch)
    application = FakeApplication(
        duplicate_groups=[_make_duplicate_group()],
    )
    application.duplicate_service._delete_result = {
        "deleted": 0, "failed": 1, "details": [],
    }
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: "Deleted: 0, Failed: 1" in (
            window._duplicates_page.duplicates_status_label.text()
        ),
        timeout=2000,
    )
    assert window._duplicates_page.duplicates_table.rowCount() == 2
    assert len(window._duplicates_page._current_duplicate_groups) == 1


def test_delete_duplicates_confirmation_dialog_lists_exact_full_paths(
        qtbot, monkeypatch,
):
    # Roadmap item 56 Phase 6.3 — deleting real user files warrants
    # naming them.
    captured: dict[str, str] = {}

    def fake_question(self, title, body, *args, **kwargs):
        captured["title"] = title
        captured["body"] = body
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)

    application = FakeApplication(duplicate_groups=[_make_duplicate_group()])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicates_locations(
        [(LibraryLocation(id=1, name="Main", path="/music", added_at=""), True)]
    )
    window._duplicates_page._current_duplicates_location_name = "Main"
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    assert "/music/a.mp3" in captured["body"]
    assert "a.flac" not in captured["body"]  # the kept file, not deleted


def test_keep_all_disables_delete_and_deletes_nothing(qtbot, monkeypatch):
    # Roadmap item 56 Phase 6.3 — "the same file living in several
    # folders is sometimes deliberate."
    _confirm_yes(monkeypatch)
    application = FakeApplication(duplicate_groups=[_make_duplicate_group()])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([_make_duplicate_group()])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox = actions.findChildren(QCheckBox)[0]
    keep_all_radio = next(
        w for w in actions.findChildren(QRadioButton)
        if w.text() == "Keep all"
    )

    assert delete_button.isEnabled()

    keep_all_radio.setChecked(True)

    assert not delete_button.isEnabled()

    # Defense in depth: even a direct call must not delete anything.
    checkbox.setChecked(True)
    window._duplicates_page._on_delete_duplicates_clicked(
        window._duplicates_page._current_duplicate_groups[0],
        window._duplicates_page._duplicate_button_groups[0],
        checkbox,
        delete_button,
    )
    assert application.duplicate_service.delete_local_files_calls == []


def test_delete_duplicates_group_of_three_deletes_exactly_two(
        qtbot,
        monkeypatch,
):
    _confirm_yes(monkeypatch)
    group = _make_duplicate_group_with_n_files(3)
    application = FakeApplication(duplicate_groups=[group])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([group])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    delete_ids, keep_id, _location_id = (
        application.duplicate_service.delete_local_files_calls[0]
    )
    assert keep_id == 200  # files[0] is the group's own recommendation
    assert sorted(delete_ids) == [201, 202]


def test_delete_duplicates_group_of_four_deletes_exactly_three(
        qtbot,
        monkeypatch,
):
    _confirm_yes(monkeypatch)
    group = _make_duplicate_group_with_n_files(4)
    application = FakeApplication(duplicate_groups=[group])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._duplicates_page._render_duplicate_groups([group])

    actions = window._duplicates_page.duplicates_table.cellWidget(
            0,
            _duplicates_column(window, "Actions"),
    )
    checkbox = actions.findChildren(QCheckBox)[0]
    delete_button = actions.findChildren(QPushButton)[0]
    checkbox.setChecked(True)
    delete_button.click()

    qtbot.waitUntil(
        lambda: bool(application.duplicate_service.delete_local_files_calls),
        timeout=2000,
    )
    delete_ids, keep_id, _location_id = (
        application.duplicate_service.delete_local_files_calls[0]
    )
    assert keep_id == 200
    assert sorted(delete_ids) == [201, 202, 203]



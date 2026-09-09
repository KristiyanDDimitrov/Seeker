"""Tests for the Review page (seeker.ui.pages.review_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.5) — the
mirror of §9.3.1's own Review extraction (S9).

Tests that exercise MainWindow's own not-yet-extracted orchestration or
other pages' state alongside Review's (the Dashboard-double-click-
navigates-here-and-selects-a-row test, the Downloads/Review nav-badge
and tray-menu-counts tests, and the four structural sweep tests that
check every page's tables/buttons at once) stay in test_ui_smoke.py as
cross-cutting, unmoved.

BulkReplaceUpgradesDialog is imported from seeker.ui.dialogs directly
here, not re-exported from seeker.ui.main_window — that re-export only
existed for this file's own prior residence in test_ui_smoke.py.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QMessageBox, QPushButton

from seeker.ui.dialogs import BulkReplaceUpgradesDialog
from seeker.ui.main_window import MainWindow
from test_ui_smoke import (
    FakeApplication,
    _make_needs_review_match,
    _make_review_candidate,
    _make_track,
    _make_upgrade_details,
)


def test_focus_pending_review_row_selects_the_correct_row_after_sorting(qtbot):
    # Round 8 §12.2 — the needs-review table is now sortable;
    # _focus_pending_review_row must resolve by the row's own UserRole
    # track-id anchor, not by re-deriving a row index from the
    # candidates list's insertion order (which no longer matches the
    # table's row order once a user has sorted it).
    candidates = [
        (
            _make_track(track_id="t1"),
            _make_review_candidate(track_id="t1", score=10.0),
        ),
        (
            _make_track(track_id="t2"),
            _make_review_candidate(track_id="t2", score=90.0),
        ),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_needs_review_candidates(candidates)
    window._review_page.review_needs_table.sortItems(
        1, Qt.SortOrder.DescendingOrder,
    )
    # t2 (score 90) now sits at row 0, t1 (score 10) at row 1 — the
    # reverse of insertion order.
    assert (
        window._review_page.review_needs_table.item(0, 0)
        .data(Qt.ItemDataRole.UserRole) == "t2"
    )

    window._review_page._pending_review_focus_track_id = "t1"
    window._review_page._focus_pending_review_row()

    assert window._review_page.review_needs_table.currentRow() == 1


def test_review_tab_renders_needs_review_candidates(qtbot):
    candidates = [(_make_track(), _make_review_candidate())]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_needs_review_candidates(candidates)

    assert window._review_page.review_needs_table.rowCount() == 1
    assert window._review_page.review_needs_table.item(0, 0).text() == "Artist - Title"
    assert window._review_page.review_needs_table.item(0, 1).text() == "73.2"
    assert "peer1" in window._review_page.review_needs_table.item(0, 2).text()

    actions = window._review_page.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    assert set(buttons) == {"Confirm", "Reject"}


def test_review_tab_confirm_button_calls_confirm_review_candidate(qtbot):
    candidates = [
            (_make_track(track_id="t7"), _make_review_candidate(track_id="t7"))
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_needs_review_candidates(candidates)

    actions = window._review_page.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Confirm"].click()

    qtbot.waitUntil(
        lambda: application.download_service.confirm_review_candidate_calls == ["t7"],
        timeout=2000,
    )
    assert application.download_service.reject_review_candidate_calls == []


def test_review_tab_reject_button_calls_reject_review_candidate(qtbot):
    candidates = [
            (_make_track(track_id="t9"), _make_review_candidate(track_id="t9"))
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_needs_review_candidates(candidates)

    actions = window._review_page.review_needs_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Reject"].click()

    qtbot.waitUntil(
        lambda: application.download_service.reject_review_candidate_calls == ["t9"],
        timeout=2000,
    )
    assert application.download_service.confirm_review_candidate_calls == []


def test_review_tab_renders_pending_upgrades_with_delete_checkbox_when_old_file_exists(
        qtbot,
):
    details = [_make_upgrade_details(old_file_path="/music/old.mp3")]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)

    table = window._review_page.review_upgrades_table
    assert table.rowCount() == 1
    assert table.item(0, 1).text() == "mp3"
    assert table.item(0, 2).text() == "flac 1000kbps"

    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    assert len(actions.findChildren(QCheckBox)) == 1
    buttons = {b.text() for b in actions.findChildren(QPushButton)}
    assert buttons == {"Replace", "Decline"}


def test_review_tab_renders_pending_upgrades_without_delete_checkbox_when_no_old_file(
        qtbot,
):
    # Mirrors the CLI's own guard around its second input() prompt —
    # there's nothing to offer deleting when there's no current file.
    details = [_make_upgrade_details(old_file_path=None)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)

    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    assert actions.findChildren(QCheckBox) == []


def test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag(
        qtbot,
):
    details = [_make_upgrade_details(request_id=42, old_file_path="/music/old.mp3")]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)

    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    checkbox = actions.findChildren(QCheckBox)[0]
    checkbox.setChecked(True)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Replace"].click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decision_calls
        == [(42, True, True)],
        timeout=2000,
    )
    assert window._dashboard_page.status_label.text() == "Replaced with /new/path"


def test_review_tab_delete_checkbox_state_survives_rerender_across_poll_ticks(
        qtbot,
):
    # Roadmap item R2.1/R2.6 — the 2s poll_timer rebuilds this table's
    # checkboxes from scratch every tick; before this fix, checking the
    # box and letting even one more tick land would silently reset it.
    details = [
            _make_upgrade_details(request_id=7, old_file_path="/music/old.mp3")
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)
    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    actions.findChildren(QCheckBox)[0].setChecked(True)
    assert window._review_page._upgrade_delete_checked == {7}

    # Three more "poll ticks" — a brand-new checkbox widget each time.
    for _ in range(3):
        window._review_page._render_pending_upgrades(details)

    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    checkbox = actions.findChildren(QCheckBox)[0]
    assert checkbox.isChecked() is True
    assert window._review_page._upgrade_delete_checked == {7}


def test_review_tab_delete_checkbox_state_pruned_when_row_removed(qtbot):
    details = [
            _make_upgrade_details(request_id=7, old_file_path="/music/old.mp3")
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)
    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    actions.findChildren(QCheckBox)[0].setChecked(True)
    assert window._review_page._upgrade_delete_checked == {7}

    # The row is gone (e.g. resolved) -- its stale key must not linger
    # forever (R2.3), and a LATER row that happens to reuse the same
    # request_id (can't really happen for a real autoincrement PK, but
    # confirms the map doesn't just grow unbounded) starts unchecked.
    window._review_page._render_pending_upgrades([])
    assert window._review_page._upgrade_delete_checked == set()


def test_review_tab_decline_button_calls_apply_upgrade_decision_with_replace_false(
        qtbot,
):
    details = [_make_upgrade_details(request_id=99)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)

    actions = window._review_page.review_upgrades_table.cellWidget(0, 3)
    buttons = {b.text(): b for b in actions.findChildren(QPushButton)}
    buttons["Decline"].click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decision_calls
        == [(99, False, False)],
        timeout=2000,
    )
    # A decline returns None from apply_upgrade_decision — no status
    # message should be surfaced, unlike a real replace.
    assert window._dashboard_page.status_label.text() == ""


# --- Roadmap item R3.1: "Replace all" upgrades -----------------------------

def test_replace_all_upgrades_button_disabled_when_no_upgrades(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades([])

    assert window._review_page.replace_all_upgrades_button.isEnabled() is False


def test_replace_all_upgrades_button_calls_batch_with_every_request_id(
        qtbot, monkeypatch,
):
    details = [
        _make_upgrade_details(request_id=1),
        _make_upgrade_details(request_id=2),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._review_page._render_pending_upgrades(details)
    assert window._review_page.replace_all_upgrades_button.isEnabled() is True

    def fake_exec(self):
        self.delete_old_checkbox.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BulkReplaceUpgradesDialog, "exec", fake_exec)
    # Roadmap item C3 (round 5) — found live while chasing a real,
    # reproducible full-suite hang: `_on_bulk_replace_upgrades_finished`
    # (the worker's on_finished callback) calls a real, unmocked
    # `QMessageBox.information()` after this test's own wait condition
    # is already satisfied (the batch call list is appended to on the
    # WORKER thread, before its finished signal is even emitted/
    # processed on the main thread) — so the test could return with
    # that call still QUEUED, popping a genuine blocking modal `exec()`
    # during a LATER, unrelated test with nothing to click under the
    # offscreen QPA. Confirmed via a real `lldb -p <pid> -o "bt all"`
    # attach on a live-hung `pytest` process: the main thread was
    # inside `QDialog::exec()`, called from `Sbk_QMessageBoxFunc_
    # information`. Mocked here (even though not asserted) so nothing
    # leaks past this test's own scope — the same defensive pattern
    # `test_resolve_all_duplicates_drops_only_succeeded_groups_locally`
    # already used correctly.
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    window._review_page.replace_all_upgrades_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.apply_upgrade_decisions_batch_calls
        != [],
        timeout=2000,
    )
    assert application.download_service.apply_upgrade_decisions_batch_calls == [
        ([1, 2], True),
    ]


def test_replace_all_upgrades_cancelled_dialog_calls_nothing(
        qtbot,
        monkeypatch,
):
    details = [_make_upgrade_details(request_id=1)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._review_page._render_pending_upgrades(details)

    monkeypatch.setattr(
        BulkReplaceUpgradesDialog, "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    window._review_page.replace_all_upgrades_button.click()

    assert application.download_service.apply_upgrade_decisions_batch_calls == []


def test_replace_all_upgrades_result_shown_in_message_box(qtbot, monkeypatch):
    from seeker.soulseek.download_service import BulkUpgradeReplaceResult

    details = [_make_upgrade_details(request_id=1)]
    application = FakeApplication()
    application.download_service.apply_upgrade_decisions_batch_result = (
        BulkUpgradeReplaceResult(
            replaced=1, failed=0, details=["Artist - Title: Replaced with x"],
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._review_page._render_pending_upgrades(details)

    monkeypatch.setattr(
        BulkReplaceUpgradesDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    info_calls = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: info_calls.append(a),
    )

    window._review_page.replace_all_upgrades_button.click()

    qtbot.waitUntil(lambda: info_calls != [], timeout=2000)
    assert "Replaced: 1, Failed: 0" in info_calls[0][2]


def test_review_tab_populates_both_sections_on_construction(qtbot):
    # _poll_review_items() runs once in __init__ (like the Downloads
    # tab's own initial call) so the Review tab isn't empty for the
    # first poll interval either.
    candidates = [
            (_make_track(track_id="tc"), _make_review_candidate(track_id="tc"))
    ]
    upgrades = [_make_upgrade_details(request_id=5)]
    application = FakeApplication(
        review_candidates=candidates, pending_upgrades=upgrades,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._review_page.review_needs_table.rowCount() == 1, timeout=2000,
    )
    assert window._review_page.review_upgrades_table.rowCount() == 1


def test_review_tab_renders_local_needs_review_matches(qtbot):
    matches = [_make_needs_review_match()]
    application = FakeApplication(needs_review_matches=matches)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )
    assert window._review_page.review_local_table.item(0, 0).text() == "Artist - Title"
    assert window._review_page.review_local_table.item(0, 1).text() == "Music/song.mp3"
    assert window._review_page.review_local_table.item(0, 2).text() == "Main"
    assert window._review_page.review_local_table.item(0, 3).text() == "85.7"
    assert window._review_page.review_local_table.cellWidget(0, 4) is not None


def test_review_tab_confirm_local_match_calls_confirm_match(qtbot):
    application = FakeApplication(
        needs_review_matches=[_make_needs_review_match(track_id="tc")]
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )
    confirm_button = window._review_page.review_local_table.cellWidget(
        0, 4
    ).findChildren(QPushButton)[0]
    confirm_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.confirm_match_calls == ["tc"],
        timeout=2000,
    )


def test_review_tab_reject_local_match_calls_reject_match(qtbot):
    application = FakeApplication(
        needs_review_matches=[_make_needs_review_match(track_id="tc")]
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )
    reject_button = window._review_page.review_local_table.cellWidget(
        0, 4
    ).findChildren(QPushButton)[1]
    reject_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.reject_match_calls == ["tc"],
        timeout=2000,
    )

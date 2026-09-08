"""Tests for the Tagging panel (seeker.ui.pages.tagging_panel). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, sessions S11.3 and
S11.4) — the mirror of §9.3.1's own Tagging panel extraction (S7).

Only the tests that touch nothing but TaggingPanel's own delegated
attributes/dialogs live here — most of the panel's own tests also drive
Dashboard's own track_table/playlist_list/dashboard_notice to set up a
selection, so those moved to test_dashboard_page.py instead (S11.4,
which also decided where the remaining S11.3-deferred cross-cutting
tests belong — see that file's own docstring).
"""

from itertools import pairwise
from pathlib import Path

from PySide6.QtCore import QRect

from seeker.library.metadata_service import RenamePlan
from seeker.ui import theme
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication


def _make_rename_plan(
        track_id="t1", action="rename",
        current="/music/old.mp3", proposed="/music/new.mp3",
        message=None,
) -> RenamePlan:
    return RenamePlan(
        track_id=track_id,
        local_file_id=1,
        current_path=Path(current) if current else None,
        proposed_path=Path(proposed) if proposed else None,
        action=action,
        message=message,
    )


def test_tagging_controls_row_reflows_to_multiple_rows_when_narrow(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    layout = window._dashboard_page._tagging_panel.tagging_controls_layout
    single_row_height = max(
        layout.itemAt(i).sizeHint().height() for i in range(layout.count())
    )

    # Wide: collapses back to a single row.
    assert layout.heightForWidth(1600) <= single_row_height + 4

    # Narrow: really does grow to 2+ rows, not just clip/scroll.
    assert layout.heightForWidth(320) >= single_row_height * 2


def test_tagging_controls_row_minimum_size_is_the_widest_item_not_the_sum(
        qtbot,
):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    layout = window._dashboard_page._tagging_panel.tagging_controls_layout
    widths = [
            layout.itemAt(i).sizeHint().width() for i in range(layout.count())
    ]

    assert layout.minimumSize().width() < sum(widths) / 2
    assert layout.minimumSize().width() >= max(widths)


def test_tagging_controls_row_has_real_spacing_between_items(qtbot):
    # Roadmap item 79 (P11) — bare FlowLayout() left h_spacing/
    # v_spacing at -1, falling through to _smart_spacing()'s style
    # query, which is approximately zero under this app's Fusion
    # styling — the buttons ended up touching. Checked at two widths:
    # a wide layout (items on one row, horizontal gaps matter) and a
    # narrow one (items wrap onto multiple rows, vertical gaps matter).
    #
    # Roadmap item RR2 — diagnosed for real, not reclassified as
    # "pre-existing": item.geometry() read back INCONSISTENT with what
    # FlowLayout's own _do_layout() had just requested via
    # setGeometry() — confirmed live by temporarily instrumenting
    # _do_layout() to print its real x/y/sizeHint() at the exact moment
    # it calls setGeometry(), then diffing against what this test's own
    # layout.itemAt(i).geometry() read back immediately afterward:
    # every item in one row was genuinely assigned the SAME y by the
    # layout (confirmed in the printed trace), but the read-back
    # geometry showed a checkbox row at height 10 and a button row at
    # height 16 sharing one row's worth of y, each keeping its own
    # right/bottom edge fixed — the signature of a widget whose
    # geometry was queried before the offscreen platform had actually
    # applied it, not a spacing bug. `qtbot.waitExposed(window)` alone
    # was NOT sufficient (confirmed by re-running 5x); a real
    # `QApplication.processEvents()` call after EACH setGeometry() —
    # this loop drives the layout through two different widths, so it
    # needs to settle twice — is what actually made every read
    # consistent, confirmed clean across 5 repeated runs both with and
    # without waitExposed() (dropped once shown redundant).
    from PySide6.QtWidgets import QApplication

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    layout = window._dashboard_page._tagging_panel.tagging_controls_layout

    for width in (1600, 320):
        layout.setGeometry(QRect(0, 0, width, layout.heightForWidth(width)))
        QApplication.processEvents()
        # Two items (bpm_min_edit/bpm_max_edit) start .hide()'n until
        # "Analyze audio" is checked -- QWidgetItem.setGeometry() is a
        # real no-op for a hidden widget (QWidgetItem.isEmpty() short-
        # circuits it), so a hidden item's geometry is stale/unrelated,
        # not a gap this test should judge.
        rects = [
            layout.itemAt(i).geometry() for i in range(layout.count())
            if not layout.itemAt(i).widget().isHidden()
        ]
        # Adjacent items on the SAME row must have a real horizontal
        # gap; items that wrapped onto a new row must have a real
        # vertical gap. Every consecutive pair satisfies at least one.
        for previous, current in pairwise(rects):
            same_row = previous.top() == current.top()
            if same_row:
                assert current.left() - previous.right() >= theme.SPACING_SM
            else:
                assert current.top() - previous.bottom() >= theme.SPACING_SM


def test_tagging_controls_checkboxes_get_their_full_label_width(qtbot):
    # Roadmap item 79 (P11.2) — the checkbox labels ("Analyze audio
    # (BPM/Key)", "Re-tag already tagged files") must render at their
    # own real sizeHint() width, not be clipped by the layout.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    tagging_panel = window._dashboard_page._tagging_panel
    for checkbox in (
            tagging_panel.analyze_audio_checkbox,
            tagging_panel.force_retag_checkbox,
    ):
        assert checkbox.width() >= checkbox.sizeHint().width()


def test_bpm_range_fields_hidden_until_analyze_audio_checked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    # isVisible() reflects actual on-screen visibility, which requires
    # a shown top-level window — isHidden() reflects the widget's own
    # explicit hide/show state regardless of ancestor visibility, which
    # is what this test actually cares about, so window.show() isn't
    # needed here.
    assert window._dashboard_page._tagging_panel.bpm_min_edit.isHidden()
    assert window._dashboard_page._tagging_panel.bpm_max_edit.isHidden()

    window._dashboard_page._tagging_panel.analyze_audio_checkbox.setChecked(True)

    assert not window._dashboard_page._tagging_panel.bpm_min_edit.isHidden()
    assert not window._dashboard_page._tagging_panel.bpm_max_edit.isHidden()

    window._dashboard_page._tagging_panel.analyze_audio_checkbox.setChecked(False)

    assert window._dashboard_page._tagging_panel.bpm_min_edit.isHidden()
    assert window._dashboard_page._tagging_panel.bpm_max_edit.isHidden()


def test_rename_preview_dialog_groups_plans_by_action(qtbot):
    plans = [
        _make_rename_plan("t1", "rename"),
        _make_rename_plan(
            "t2", "collision", "/music/a.mp3", "/music/b.mp3",
            "target already exists",
        ),
        _make_rename_plan(
            "t3", "already_correct", "/music/c.mp3", "/music/c.mp3",
        ),
        _make_rename_plan(
            "t4", "not_auto_matched", None, None, "not auto-matched",
        ),
    ]
    dialog = RenamePreviewDialog(None, "Test Playlist", plans)
    qtbot.addWidget(dialog)

    assert dialog.confirm_button.text() == "Rename 2 file(s)"
    assert dialog.confirm_button.isEnabled()


def test_rename_preview_dialog_disables_confirm_when_nothing_to_rename(qtbot):
    plans = [
        _make_rename_plan(
            "t1", "already_correct", "/music/c.mp3", "/music/c.mp3",
        ),
    ]
    dialog = RenamePreviewDialog(None, "Test Playlist", plans)
    qtbot.addWidget(dialog)

    assert dialog.confirm_button.text() == "Rename 0 file(s)"
    assert not dialog.confirm_button.isEnabled()

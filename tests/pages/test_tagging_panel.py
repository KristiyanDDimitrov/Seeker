"""Tests for the Tagging panel (seeker.ui.pages.tagging_panel). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, sessions S11.3 and
S11.4) — the mirror of §9.3.1's own Tagging panel extraction (S7).

Only the tests that touch nothing but TaggingPanel's own delegated
attributes/dialogs live here — most of the panel's own tests also drive
Dashboard's own track_table/playlist_list to set up a selection, so
those live in test_library_page.py instead (round 8 §12.6 moved
TaggingPanel itself onto its own Library page — see that file's own
docstring).
"""

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QLabel,
    QPushButton,
)

from fakes import FakeApplication
from seeker.library.metadata_service import RenamePlan
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.main_window import MainWindow


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


def _groups(panel) -> dict[str, QFrame]:
    return {
        card.accessibleName(): card
        for card in panel.findChildren(QFrame, "card")
    }


def test_tagging_options_and_actions_are_grouped_by_job(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    panel = window._library_page._tagging_panel

    groups = _groups(panel)

    assert list(groups) == ["Tags", "Tag options", "Cover art", "File names"]
    assert set(groups["Tag options"].findChildren(QCheckBox)) == {
        panel.analyze_audio_checkbox, panel.force_retag_checkbox,
    }
    for title, buttons in (
            ("Tags", {panel.tag_selected_button, panel.tag_playlist_button}),
            ("Tag options", set()),
            ("Cover art", {
                panel.fix_missing_art_button,
                panel.fill_missing_art_urls_button,
            }),
            ("File names", {panel.rename_files_button}),
    ):
        assert set(groups[title].findChildren(QPushButton)) == buttons
        # Its title, then one sentence saying what its controls do.
        heading, explanation = groups[title].findChildren(QLabel)[:2]
        assert heading.text() == title
        assert explanation.text().endswith(".")


def test_the_library_page_scrolls_rather_than_squeezing_its_buttons(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    window.resize(960, 640)
    window.show()
    window._show_page("library")
    qtbot.waitExposed(window)
    QApplication.processEvents()
    panel = window._library_page._tagging_panel

    for button in panel.findChildren(QPushButton):
        assert button.height() >= button.sizeHint().height(), button.text()


def test_tagging_controls_checkboxes_get_their_full_label_width(qtbot):
    # Roadmap item 79 (P11.2) — the checkbox labels ("Analyze audio
    # (BPM/Key)", "Re-tag already tagged files") must render at their
    # own real sizeHint() width, not be clipped by the layout.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    tagging_panel = window._library_page._tagging_panel
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
    assert window._library_page._tagging_panel.bpm_min_edit.isHidden()
    assert window._library_page._tagging_panel.bpm_max_edit.isHidden()

    window._library_page._tagging_panel.analyze_audio_checkbox.setChecked(True)

    assert not window._library_page._tagging_panel.bpm_min_edit.isHidden()
    assert not window._library_page._tagging_panel.bpm_max_edit.isHidden()

    window._library_page._tagging_panel.analyze_audio_checkbox.setChecked(False)

    assert window._library_page._tagging_panel.bpm_min_edit.isHidden()
    assert window._library_page._tagging_panel.bpm_max_edit.isHidden()


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

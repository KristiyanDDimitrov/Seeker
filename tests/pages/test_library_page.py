"""Tests for the Library page (seeker.ui.pages.library_page) and the
TaggingPanel it hosts. Moved out of test_dashboard_page.py (round 8
§12.6 — TaggingPanel split from a Dashboard sub-widget into its own
page). These tests still need Dashboard's own track_table/playlist_list
to set up a selection — Library has no selection state of its own, it
reads Dashboard's live state via LibraryHost — so they drive both
`window._dashboard_page` (selection setup) and `window._library_page`
(triggering tag actions, reading notice/results), the same cross-
cutting shape test_dashboard_page.py's own docstring already describes
for this exact test group, just with the two pages' roles swapped from
before the split.

Tests exercising only TaggingPanel's own layout/widgets with zero
Dashboard state stay in test_tagging_panel.py.
"""

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QDialog, QPushButton

from seeker.library.metadata_service import RenamePlan, RenameResult
from seeker.models.playlist import Playlist
from seeker.models.track_status import IN_LIBRARY
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication, _make_track_status


def _select_first_playlist(window, qtbot) -> None:
    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    # Selecting also kicks off the "next step" facts fetch
    # (_poll_next_step), which independently enables/disables
    # download_button — wait for it to actually land rather than
    # racing a click against a button that may still be disabled from
    # the pre-selection (no playlist selected) render.
    qtbot.waitUntil(
        window._dashboard_page.download_button.isEnabled, timeout=2000,
    )


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


def test_retag_context_menu_forces_regardless_of_checkbox(qtbot):
    statuses = [
        _make_track_status(
            track_id="t5", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    # The panel-wide force checkbox is deliberately left unchecked —
    # Re-tag via the context menu must force regardless of it.
    assert (
        window._library_page._tagging_panel.force_retag_checkbox.isChecked()
        is False
    )

    window._library_page._tagging_panel._on_retag_track_clicked("t5")

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t5"], False, None, True),
    ]


def test_force_retag_checkbox_passed_through_all_three_triggers(qtbot):
    statuses = [
        _make_track_status(
            track_id="t7", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    playlists = [Playlist(id="p1", name="240KM/H", track_count=1)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    window._library_page._tagging_panel.force_retag_checkbox.setChecked(True)

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    tag_button = actions.findChildren(QPushButton)[0] if actions.findChildren(
        QPushButton
    ) else None
    # This row is already tagged, so the per-row control is the muted
    # label, not a button — exercise the panel-wide checkbox via "Tag
    # selected" and "Tag playlist" instead, both of which apply
    # regardless of a row's own tagged state.
    assert tag_button is None

    selection_model = window._dashboard_page.track_table.selectionModel()
    selection_model.select(
        window._dashboard_page.track_table.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    window._library_page._tagging_panel.tag_selected_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t7"], False, None, True),
    ]

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    window._library_page._tagging_panel.tag_playlist_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_playlist_calls == [
        ("240KM/H", False, None, True),
    ]


def test_tag_track_button_calls_tag_tracks_with_correct_args(qtbot):
    statuses = [_make_track_status(track_id="t7", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    tag_button = actions.findChildren(QPushButton)[0]
    tag_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t7"], False, None, False),
    ]


def test_tag_track_with_analyze_audio_and_bpm_range_passes_options(qtbot):
    statuses = [_make_track_status(track_id="t9", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    window._library_page._tagging_panel.analyze_audio_checkbox.setChecked(True)
    window._library_page._tagging_panel.bpm_min_edit.setText("160")
    window._library_page._tagging_panel.bpm_max_edit.setText("180")

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t9"], True, (160.0, 180.0), False),
    ]


def test_bpm_range_partial_input_blocks_the_call_with_an_error(qtbot):
    statuses = [_make_track_status(track_id="t3", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    window._library_page._tagging_panel.analyze_audio_checkbox.setChecked(True)
    window._library_page._tagging_panel.bpm_min_edit.setText("160")
    # bpm_max_edit deliberately left blank.

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "both" in window._library_page.notice.text().lower()
    assert not window._library_page.notice.isHidden()


def test_tag_selected_calls_tag_tracks_with_selected_ids(qtbot):
    statuses = [
        _make_track_status(track_id="s1", state=IN_LIBRARY),
        _make_track_status(track_id="s2", state=IN_LIBRARY),
        _make_track_status(track_id="s3", state=IN_LIBRARY),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    # Select rows 0 and 2 additively through the selection model itself
    # (QItemSelectionModel.Select | .Rows) — selectRow() replaces the
    # existing selection instead of adding to it, which isn't what a
    # real ctrl/shift-click multi-select produces.
    selection_model = window._dashboard_page.track_table.selectionModel()
    for row in (0, 2):
        selection_model.select(
            window._dashboard_page.track_table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    window._library_page._tagging_panel.tag_selected_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    track_ids, analyze_audio, bpm_range, force = (
        application.metadata_service.tag_tracks_calls[0]
    )
    assert set(track_ids) == {"s1", "s3"}
    assert analyze_audio is False
    assert bpm_range is None
    assert force is False


def test_tag_selected_with_no_selection_shows_message_and_makes_no_call(qtbot):
    statuses = [_make_track_status(track_id="s1", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    window._library_page._tagging_panel.tag_selected_button.click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "select" in window._library_page.notice.text().lower()


def test_tag_playlist_calls_tag_playlist_with_playlist_name(qtbot):
    playlists = [Playlist(id="p1", name="240KM/H", track_count=5)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)

    window._library_page._tagging_panel.tag_playlist_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_playlist_calls == [
        ("240KM/H", False, None, False),
    ]


def test_tag_playlist_without_selection_shows_message_and_makes_no_call(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel.tag_playlist_button.click()

    assert application.metadata_service.tag_playlist_calls == []
    assert "playlist" in window._library_page.notice.text().lower()


def test_results_panel_renders_breakdown_and_per_item_reasons(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = {
        "tagged": 2,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 1,
        "skipped_format_unsupported": 1,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 1,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_no_match",
                "message": "Artist A - Title A: no matched local file",
            },
            {
                "track_id": "t2",
                "reason": "failed",
                "message": "Artist B - Title B: disk read error",
            },
        ],
    }

    window._library_page._tagging_panel._render_tag_result(result)

    text = window._library_page._tagging_panel.tagging_results.toPlainText()
    assert "Tagged: 2" in text
    assert "Failed: 1" in text
    assert "[skipped_no_match] Artist A - Title A: no matched local file" in text
    assert "[failed] Artist B - Title B: disk read error" in text


def test_tag_result_notice_reports_tracks_without_art(qtbot):
    # Roadmap item 56 Phase 4.2 — the real fix: the UI must never show
    # a bare success when some tracks were tagged without cover art.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel._render_tag_result({
        "tagged": 3,
        "tagged_without_art": 2,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [
            {
                "track_id": "t1",
                "reason": "tagged_without_art_no_url",
                "message": "Artist A - Title A: no album art URL stored",
            },
        ],
    })

    assert not window._library_page.notice.isHidden()
    assert "2 without cover art" in window._library_page.notice.text()


def test_tag_result_notice_shows_success_when_everything_worked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel._render_tag_result({
        "tagged": 5,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 0,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [],
    })

    assert not window._library_page.notice.isHidden()
    assert "Tagged 5 tracks" in window._library_page.notice.text()
    assert "without cover art" not in window._library_page.notice.text()


def test_tag_result_notice_reports_already_tagged_with_nothing_else_done(
        qtbot,
):
    # Roadmap item 66 (Phase 5.1) — the real gap found in Phase 0.4's
    # investigation: a fully-already-tagged re-run (tagged=0, nothing
    # failed, nothing missing art) previously produced NO notice at
    # all — only the easy-to-miss results panel said anything.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel._render_tag_result({
        "tagged": 0,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 4,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_already_tagged",
                "message": "Artist A - Title A: already tagged",
            },
        ],
    })

    assert not window._library_page.notice.isHidden()
    text = window._library_page.notice.text()
    assert "4 track" in text
    assert "already tagged" in text
    assert "Re-tag" in text
    # Roadmap item 75 (P6, 6.2) — the real gap: "already tagged" here
    # does not mean "art is fine," it means art was never checked.
    assert "NOT checked" in text
    assert not window._library_page.notice._action_button.isHidden()
    assert (
        window._library_page.notice._action_button.text()
        == "Fix missing cover art"
    )


def test_tag_result_notice_mentions_unchecked_art_even_on_a_mixed_run(qtbot):
    # Roadmap item 75 (P6, 6.2) — a real gap the all-skipped case alone
    # didn't cover: a run that freshly tags SOME tracks while skipping
    # others as already-tagged used to say nothing at all about the
    # skipped ones' art.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel._render_tag_result({
        "tagged": 2,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 3,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [],
    })

    assert not window._library_page.notice.isHidden()
    text = window._library_page.notice.text()
    assert "Tagged 2 track" in text
    assert "3 already-tagged" in text
    assert "NOT checked" in text


def test_tag_result_notice_fix_art_action_triggers_fix_missing_art(
        qtbot,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._library_page._tagging_panel._render_tag_result({
        "tagged": 0,
        "tagged_without_art": 0,
        "tagged_art_rarely_supported_format": 0,
        "skipped_no_match": 0,
        "skipped_format_unsupported": 0,
        "skipped_already_tagged": 1,
        "skipped_already_analyzed": 0,
        "failed": 0,
        "details": [
            {
                "track_id": "t1",
                "reason": "skipped_already_tagged",
                "message": "Artist A - Title A: already tagged",
            },
        ],
    })

    window._library_page.notice._action_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service
        .fix_missing_art_for_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.fix_missing_art_for_playlist_calls == [
        "Test",
    ]


# --- Fix missing cover art / fill missing art URLs (roadmap item 66,
# Phase 5.2/5.3) --------------------------------------------------------


def test_fix_missing_art_button_calls_service_and_shows_result(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(
        playlists=playlists,
        fix_art_result={
            "fixed": 3,
            "fixed_wav_rarely_supported": 0,
            "already_correct": 2,
            "no_url": 1,
            "download_failed": 0,
            "embed_failed": 0,
            "format_unsupported": 0,
            "skipped_no_match": 0,
            "failed": 0,
            "details": [
                {
                    "track_id": "t1",
                    "reason": "no_url",
                    "message": "Artist A - Title A: no album art URL stored",
                },
            ],
        },
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._library_page._tagging_panel.fix_missing_art_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service
        .fix_missing_art_for_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.fix_missing_art_for_playlist_calls == [
        "Test",
    ]
    qtbot.waitUntil(
        lambda: not window._library_page.notice.isHidden()
        and "Fixed art for 3" in window._library_page.notice.text(),
        timeout=2000,
    )
    text = window._library_page.notice.text()
    assert "2 already correct" in text
    assert "1 missing an art URL" in text
    assert "already correct" in text.lower()


def test_fix_missing_art_button_requires_a_selected_playlist(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel.fix_missing_art_button.click()

    assert not window._library_page.notice.isHidden()
    assert "playlist" in window._library_page.notice.text().lower()
    assert application.metadata_service.fix_missing_art_for_playlist_calls == []


def test_fill_missing_art_urls_button_reports_the_real_count(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists, art_urls_filled=7)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._library_page._tagging_panel.fill_missing_art_urls_button.click()

    qtbot.waitUntil(
        lambda: application.sync_service.sync_playlist_tracks_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: not window._library_page.notice.isHidden()
        and "7" in window._library_page.notice.text(),
        timeout=2000,
    )
    assert (
        "Filled in 7 missing album art URLs"
        in window._library_page.notice.text()
    )


def test_fill_missing_art_urls_button_reports_zero_found(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists, art_urls_filled=0)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._library_page._tagging_panel.fill_missing_art_urls_button.click()

    qtbot.waitUntil(
        lambda: not window._library_page.notice.isHidden()
        and "No missing" in window._library_page.notice.text(),
        timeout=2000,
    )


# --- Rename preview dialog (roadmap item 67, Phase 6.4) --------------------


def test_rename_files_button_requires_a_selected_playlist(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel.rename_files_button.click()

    assert not window._library_page.notice.isHidden()
    assert "playlist" in window._library_page.notice.text().lower()
    assert application.metadata_service.plan_renames_calls == []


def test_rename_files_button_plans_then_opens_dialog_and_cancels(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    plans = [_make_rename_plan()]
    application = FakeApplication(playlists=playlists, rename_plans=plans)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        RenamePreviewDialog, "exec", lambda self: QDialog.DialogCode.Rejected,
    )

    window._library_page._tagging_panel.rename_files_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.plan_renames_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.plan_renames_calls == ["Test"]
    # Cancelled -- apply_renames must never be called.
    assert application.metadata_service.apply_renames_calls == []


def test_rename_files_button_confirmed_calls_apply_and_shows_result(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    plans = [_make_rename_plan()]
    application = FakeApplication(
        playlists=playlists, rename_plans=plans,
        rename_result=RenameResult(renamed=1),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        RenamePreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted,
    )

    window._library_page._tagging_panel.rename_files_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.apply_renames_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.apply_renames_calls == [plans]
    qtbot.waitUntil(
        lambda: not window._library_page.notice.isHidden()
        and "Renamed 1" in window._library_page.notice.text(),
        timeout=2000,
    )


def test_rename_result_notice_names_files_whose_written_name_differed(
        qtbot, monkeypatch,
):
    # Roadmap item 76 (P2, 2.5) — the notice must name the count of
    # files whose real written name differed from the preview, not
    # bury it as just "N failed" or a bare success message.
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    plans = [_make_rename_plan()]
    application = FakeApplication(
        playlists=playlists, rename_plans=plans,
        rename_result=RenameResult(renamed=2, collisions=1),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        RenamePreviewDialog, "exec", lambda self: QDialog.DialogCode.Accepted,
    )

    window._library_page._tagging_panel.rename_files_button.click()

    qtbot.waitUntil(
        lambda: not window._library_page.notice.isHidden()
        and "Renamed 2" in window._library_page.notice.text(),
        timeout=2000,
    )
    text = window._library_page.notice.text()
    assert "1 file" in text
    assert "DIFFERENT name than the preview" in text

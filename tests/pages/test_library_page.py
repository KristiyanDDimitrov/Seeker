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

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton

from fakes import FakeApplication, make_track_status
from seeker.library.metadata_service import RenamePlan, RenameResult
from seeker.models.playlist import Playlist
from seeker.models.tag_result import FixArtResult, TagResult
from seeker.models.track_status import IN_LIBRARY, NOT_FOUND
from seeker.ui import help_text
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.elided_text import SECONDARY_ROLE
from seeker.ui.main_window import MainWindow


def _select_first_playlist(window, qtbot) -> None:
    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    # Selecting also kicks off the "next step" facts fetch
    # (poll_next_step), which independently enables/disables
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
        make_track_status(
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

    window._library_page._tagging_panel.retag_track("t5")

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t5"], False, None, True),
    ]


def test_force_retag_checkbox_passed_through_all_three_triggers(qtbot):
    statuses = [
        make_track_status(
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
    statuses = [make_track_status(track_id="t7", state=IN_LIBRARY)]
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
    statuses = [make_track_status(track_id="t9", state=IN_LIBRARY)]
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
    statuses = [make_track_status(track_id="t3", state=IN_LIBRARY)]
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
    # Clicked on a Dashboard row, so the error is reported there.
    dashboard_notice = window._dashboard_page.dashboard_notice
    assert "both" in dashboard_notice.text().lower()
    assert not dashboard_notice.isHidden()


def test_tag_selected_calls_tag_tracks_with_selected_ids(qtbot):
    statuses = [
        make_track_status(track_id="s1", state=IN_LIBRARY),
        make_track_status(track_id="s2", state=IN_LIBRARY),
        make_track_status(track_id="s3", state=IN_LIBRARY),
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


def _select_rows(window, rows) -> None:
    selection_model = window._dashboard_page.track_table.selectionModel()
    selection_model.clearSelection()
    for row in rows:
        selection_model.select(
            window._dashboard_page.track_table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )


def _three_track_application() -> FakeApplication:
    return FakeApplication(
        playlists=[Playlist(id="p1", name="Peak Time", track_count=3)],
        statuses=[
            make_track_status(track_id=f"s{index}", state=IN_LIBRARY)
            for index in (1, 2, 3)
        ],
    )


def _window_with_three_tracks(qtbot, application):
    # A selected playlist whose statuses the fake serves, so a refresh
    # after a run rebuilds the same rows instead of emptying the table.
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)
    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 3,
        timeout=2000,
    )
    return window


def test_tag_selected_is_disabled_with_a_tooltip_when_nothing_is_selected(
        qtbot,
):
    application = _three_track_application()
    window = _window_with_three_tracks(qtbot, application)
    button = window._library_page._tagging_panel.tag_selected_button

    assert not button.isEnabled()
    assert "Dashboard" in button.toolTip()
    button.click()
    assert application.metadata_service.tag_tracks_calls == []


def test_tag_selected_names_how_many_tracks_are_selected(
        qtbot,
):
    window = _window_with_three_tracks(qtbot, _three_track_application())
    button = window._library_page._tagging_panel.tag_selected_button

    _select_rows(window, (0, 2))
    assert button.text() == "Tag 2 selected"
    assert button.isEnabled()

    _select_rows(window, (1,))
    assert button.text() == "Tag 1 selected"

    _select_rows(window, ())
    assert not button.isEnabled()


def test_tag_selected_shows_the_live_selection_after_a_run(qtbot):
    application = _three_track_application()
    window = _window_with_three_tracks(qtbot, application)
    button = window._library_page._tagging_panel.tag_selected_button
    _select_rows(window, (0, 2))

    button.click()
    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: not window.busy_actions.is_running("tag_selected"),
        timeout=2000,
    )

    assert button.text() == "Tag 2 selected"
    assert button.isEnabled()


def test_a_selection_change_mid_run_leaves_tag_selected_disabled(qtbot):
    window = _window_with_three_tracks(qtbot, _three_track_application())
    button = window._library_page._tagging_panel.tag_selected_button
    _select_rows(window, (0,))
    window.busy_actions.begin("tag_selected", button)

    _select_rows(window, (0, 1))

    assert not button.isEnabled()


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


def test_results_panel_renders_summary_and_expandable_details(qtbot):
    # Round 8 §12.7 — replaced the old scrolling QPlainTextEdit dump
    # with a one-line summary plus a collapsed-by-default details list.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = TagResult(
        tagged=2,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=1,
        skipped_format_unsupported=1,
        skipped_already_tagged=0,
        skipped_already_analyzed=0,
        failed=1,
        details=[
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
    )

    window._library_page._tagging_panel._render_tag_result(result)

    results_panel = window._library_page._tagging_panel.results_panel
    assert results_panel.summary_label.text() == "Tagged 2 of 5 — 1 failed"
    # Collapsed by default — the CARD wrapper, not the inner list
    # itself, carries the real shown/hidden state (theme.make_card).
    assert results_panel._details_card.isHidden()

    results_panel.details_toggle.setChecked(True)
    assert not results_panel._details_card.isHidden()
    assert results_panel.details_list.count() == 2
    row_texts = [
        results_panel.details_list.itemWidget(
            results_panel.details_list.item(i)
        ).findChild(QLabel).text()
        for i in range(2)
    ]
    assert row_texts == [
        "[skipped_no_match] Artist A - Title A: no matched local file",
        "[failed] Artist B - Title B: disk read error",
    ]


def test_results_panel_failed_tag_row_offers_a_retry_that_re_tags(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = TagResult(
        tagged=0,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=0,
        skipped_format_unsupported=0,
        skipped_already_tagged=0,
        skipped_already_analyzed=0,
        failed=1,
        details=[
            {
                "track_id": "t2",
                "reason": "failed",
                "message": "Artist B - Title B: disk read error",
            },
        ],
    )
    window._library_page._tagging_panel._render_tag_result(result)

    results_panel = window._library_page._tagging_panel.results_panel
    results_panel.details_toggle.setChecked(True)
    row = results_panel.details_list.itemWidget(results_panel.details_list.item(0))
    retry_button = row.findChild(QPushButton)
    assert retry_button is not None
    assert retry_button.text() == "Retry"

    retry_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    # retag_track always forces, regardless of the panel's
    # own checkbox — same "guaranteed real retry" semantics as the row-
    # level context menu's own Re-tag action.
    assert application.metadata_service.tag_tracks_calls == [
        (["t2"], False, None, True),
    ]


def test_results_panel_non_failed_detail_has_no_retry_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = TagResult(
        tagged=0,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=1,
        skipped_format_unsupported=0,
        skipped_already_tagged=0,
        skipped_already_analyzed=0,
        failed=0,
        details=[
            {
                "track_id": "t1",
                "reason": "skipped_no_match",
                "message": "Artist A - Title A: no matched local file",
            },
        ],
    )
    window._library_page._tagging_panel._render_tag_result(result)

    results_panel = window._library_page._tagging_panel.results_panel
    results_panel.details_toggle.setChecked(True)
    row = results_panel.details_list.itemWidget(results_panel.details_list.item(0))
    assert row.findChild(QPushButton) is None


def test_tag_result_notice_reports_tracks_without_art(qtbot):
    # Roadmap item 56 Phase 4.2 — the real fix: the UI must never show
    # a bare success when some tracks were tagged without cover art.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel._render_tag_result(TagResult(
        tagged=3,
        tagged_without_art=2,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=0,
        skipped_format_unsupported=0,
        skipped_already_tagged=0,
        skipped_already_analyzed=0,
        failed=0,
        details=[
            {
                "track_id": "t1",
                "reason": "tagged_without_art_no_url",
                "message": "Artist A - Title A: no album art URL stored",
            },
        ],
    ))

    assert not window._library_page.notice.isHidden()
    assert "2 without cover art" in window._library_page.notice.text()


def test_tag_result_notice_shows_success_when_everything_worked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._library_page._tagging_panel._render_tag_result(TagResult(
        tagged=5,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=0,
        skipped_format_unsupported=0,
        skipped_already_tagged=0,
        skipped_already_analyzed=0,
        failed=0,
        details=[],
    ))

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

    window._library_page._tagging_panel._render_tag_result(TagResult(
        tagged=0,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=0,
        skipped_format_unsupported=0,
        skipped_already_tagged=4,
        skipped_already_analyzed=0,
        failed=0,
        details=[
            {
                "track_id": "t1",
                "reason": "skipped_already_tagged",
                "message": "Artist A - Title A: already tagged",
            },
        ],
    ))

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

    window._library_page._tagging_panel._render_tag_result(TagResult(
        tagged=2,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=0,
        skipped_format_unsupported=0,
        skipped_already_tagged=3,
        skipped_already_analyzed=0,
        failed=0,
        details=[],
    ))

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

    window._library_page._tagging_panel._render_tag_result(TagResult(
        tagged=0,
        tagged_without_art=0,
        tagged_art_rarely_supported_format=0,
        skipped_no_match=0,
        skipped_format_unsupported=0,
        skipped_already_tagged=1,
        skipped_already_analyzed=0,
        failed=0,
        details=[
            {
                "track_id": "t1",
                "reason": "skipped_already_tagged",
                "message": "Artist A - Title A: already tagged",
            },
        ],
    ))

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
        fix_art_result=FixArtResult(
            fixed=3,
            fixed_wav_rarely_supported=0,
            already_correct=2,
            no_url=1,
            download_failed=0,
            embed_failed=0,
            format_unsupported=0,
            skipped_no_match=0,
            failed=0,
            details=[
                {
                    "track_id": "t1",
                    "reason": "no_url",
                    "message": "Artist A - Title A: no album art URL stored",
                },
            ],
        ),
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
        "Found cover art on Spotify for 7 tracks"
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
        and "No track was missing" in window._library_page.notice.text(),
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


# --- round9 §7.2: the context header and its inline picker ---------------


def test_context_header_shows_empty_state_and_offers_picker(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=3)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._library_page._context_label.text() == (
        help_text.LIBRARY_NO_PLAYLIST_TEXT
    )
    assert window._library_page._change_playlist_button.isHidden()
    # The empty state offers the picker directly, not just the problem.
    assert not window._library_page._playlist_picker.isHidden()
    qtbot.waitUntil(
        lambda: window._library_page._playlist_picker.count() == 1,
        timeout=2000,
    )


def test_context_header_names_selected_playlist_and_track_count(qtbot):
    playlists = [Playlist(id="p1", name="240KM/H", track_count=7)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    text = window._library_page._context_label.text()
    assert "240KM/H" in text
    assert "7 tracks" in text
    assert window._library_page._playlist_picker.isHidden()
    assert not window._library_page._change_playlist_button.isHidden()


def _select_playlist_by_row(window, qtbot, row: int, count: int) -> None:
    # A local variant of module-level _select_first_playlist, which
    # asserts playlist_list.count() == 1 — these tests need a second,
    # unselected playlist available to pick from Library's own picker.
    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == count,
        timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(row)
    qtbot.waitUntil(
        window._dashboard_page.download_button.isEnabled, timeout=2000,
    )


def test_change_playlist_button_reveals_picker_populated_from_sync_service(
        qtbot,
):
    playlists = [
        Playlist(id="p1", name="240KM/H", track_count=7),
        Playlist(id="p2", name="Other", track_count=2),
    ]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_playlist_by_row(window, qtbot, 0, 2)

    window._library_page._change_playlist_button.setChecked(True)

    qtbot.waitUntil(
        lambda: window._library_page._playlist_picker.count() == 2,
        timeout=2000,
    )
    assert not window._library_page._playlist_picker.isHidden()


def test_picking_a_playlist_in_library_updates_shared_selection_and_dashboard(
        qtbot,
):
    playlists = [
        Playlist(id="p1", name="240KM/H", track_count=7),
        Playlist(id="p2", name="Other", track_count=2),
    ]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_playlist_by_row(window, qtbot, 0, 2)

    window._library_page._change_playlist_button.setChecked(True)
    qtbot.waitUntil(
        lambda: window._library_page._playlist_picker.count() == 2,
        timeout=2000,
    )

    other_item = window._library_page._playlist_picker.item(1)
    assert other_item.data(Qt.ItemDataRole.UserRole).name == "Other"
    window._library_page._on_playlist_picked(other_item)

    # One selection, two views: Library's write must show up in
    # Dashboard's own state, not just Library's.
    assert window._dashboard_page.selected_playlist.name == "Other"
    qtbot.waitUntil(
        lambda: (
            (current := window._dashboard_page.playlist_list.currentItem())
            is not None
            and current.data(Qt.ItemDataRole.UserRole).name == "Other"
        ),
        timeout=2000,
    )
    assert window._library_page._playlist_picker.isHidden()
    assert "Other" in window._library_page._context_label.text()


# Library's own track list: the playlist's tracks that are in the
# library (the only ones tagging acts on), each with its tag state.

def _tag_state_application() -> FakeApplication:
    return FakeApplication(
        playlists=[Playlist(id="p1", name="Peak Time", track_count=5)],
        statuses=[
            make_track_status(
                track_id="tagged", tagged_at="2026-10-01", has_art=True,
            ),
            make_track_status(
                track_id="no-art", tagged_at="2026-10-01", has_art=False,
                album_art_url="https://i.scdn.co/image/a",
            ),
            make_track_status(track_id="no-url", has_art=False),
            make_track_status(track_id="unread"),
            make_track_status(track_id="missing", state=NOT_FOUND),
        ],
    )


def _library_rows(window) -> dict[str, tuple[str, str, str]]:
    table = window._library_page.track_table
    rows = {}
    for row in range(table.rowCount()):
        track_id = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        rows[track_id] = (
            table.item(row, 1).text(),
            table.item(row, 2).text(),
            table.item(row, 2).data(SECONDARY_ROLE) or "",
        )
    return rows


def _window_on_library(qtbot, application):
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)
    window._show_page("library")
    return window


def test_library_lists_the_playlists_tracks_in_the_library_with_tag_state(
        qtbot,
):
    window = _window_on_library(qtbot, _tag_state_application())

    qtbot.waitUntil(
        lambda: window._library_page.track_table.rowCount() == 4,
        timeout=2000,
    )
    assert _library_rows(window) == {
        "tagged": ("Tagged", "Embedded", ""),
        "no-art": ("Tagged", "Missing", ""),
        # Fix missing cover art needs Spotify's URL first.
        "no-url": ("Not tagged", "Missing", "Get from Spotify"),
        "unread": ("Not tagged", "Not checked", "Scan to check"),
    }


def test_library_track_selection_is_what_tag_selected_tags(qtbot):
    application = _tag_state_application()
    window = _window_on_library(qtbot, application)
    table = window._library_page.track_table
    qtbot.waitUntil(lambda: table.rowCount() == 4, timeout=2000)
    button = window._library_page._tagging_panel.tag_selected_button

    table.selectRow(0)
    table.selectionModel().select(
        table.model().index(2, 0),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )

    selected = window.playlist_selection.track_ids
    assert len(selected) == 2
    assert button.text() == "Tag 2 selected"

    button.click()
    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls[0][0] == selected


def test_a_dashboard_selection_shows_on_librarys_track_list(qtbot):
    window = _window_on_library(qtbot, _tag_state_application())
    table = window._library_page.track_table
    qtbot.waitUntil(lambda: table.rowCount() == 4, timeout=2000)
    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 5,
        timeout=2000,
    )

    _select_rows(window, (1, 4))  # no-art, and a track not in the library

    def selected_ids():
        return {
            table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in table.selectionModel().selectedRows()
        }

    qtbot.waitUntil(lambda: selected_ids() == {"no-art"}, timeout=2000)


def test_library_track_list_refreshes_after_a_tag_run(qtbot):
    application = _tag_state_application()
    window = _window_on_library(qtbot, application)
    table = window._library_page.track_table
    qtbot.waitUntil(lambda: table.rowCount() == 4, timeout=2000)
    application.dashboard_service._statuses[3] = make_track_status(
        track_id="unread", tagged_at="2026-10-07", has_art=True,
    )

    window._library_page._tagging_panel.tag_playlist_button.click()

    qtbot.waitUntil(
        lambda: _library_rows(window).get("unread")
        == ("Tagged", "Embedded", ""),
        timeout=2000,
    )


def test_library_track_list_says_why_it_is_empty(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Peak Time", track_count=1)],
        statuses=[make_track_status(track_id="missing", state=NOT_FOUND)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._library_page

    assert page.track_table.rowCount() == 0
    assert page.track_empty_state.text() == (
        help_text.LIBRARY_TRACKS_NO_PLAYLIST_TEXT
    )

    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: page.track_empty_state.text()
        == help_text.LIBRARY_TRACKS_NONE_IN_LIBRARY_TEXT,
        timeout=2000,
    )

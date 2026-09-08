"""Tests for the Dashboard page (seeker.ui.pages.dashboard_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.4) — the
mirror of §9.3.1's own Dashboard extraction (S8).

Tests that also drive TaggingPanel (a Dashboard sub-widget,
window._dashboard_page._tagging_panel) live here too, not in
test_tagging_panel.py — S11.3 left them cross-cutting in
test_ui_smoke.py pending this session's own decision (HANDOFF.md);
since they need Dashboard's own track_table/playlist_list/
dashboard_notice regardless, Dashboard is their real home. Only the
two TaggingPanel tests needing zero Dashboard state moved to
test_tagging_panel.py instead.

Tests that exercise MainWindow's own not-yet-extracted orchestration
(the sync/scan/match/download click handlers, _open_destination_dialog,
the Review-tab-navigates-here-and-selects-a-row assertions) stay in
test_ui_smoke.py as cross-cutting, even though several of them use
Dashboard's buttons as their trigger or dashboard_notice/status_label
as their assertion target — same precedent as the activity-strip and
structural-sweep tests that also stayed.
"""

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton

from seeker.library.metadata_service import RenamePlan, RenameResult
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track_status import (
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    TrackStatus,
)
from seeker.ui import theme
from seeker.ui.dialogs import RenamePreviewDialog
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication, _make_track, _make_track_status


def _select_first_playlist(window, qtbot) -> None:
    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)
    # Selecting also kicks off the "next step" facts fetch
    # (_poll_next_step), which independently enables/disables
    # download_button — wait for it to actually land rather than
    # racing a click against a button that may still be disabled from
    # the pre-selection (no playlist selected) render.
    qtbot.waitUntil(window.download_button.isEnabled, timeout=2000)


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


def test_render_next_step_does_not_reenable_a_button_whose_action_is_running(
        qtbot,
):
    # Regression test for Phase 0's own 0.1 finding, live-proven via an
    # instrumented offscreen MainWindow: _render_next_step runs on every
    # 2s poll tick and used to unconditionally re-enable the scan button
    # from static facts alone, with no idea a real scan_and_match() might
    # still be running. Exercises the exact same method directly, with a
    # real busy_actions.begin() standing in for "still running".
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin("scan", window.scan_button, "Scanning…")
    assert window.scan_button.isEnabled() is False

    facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(facts)

    # Pre-fix, this would have been re-enabled here since
    # facts.has_library_location is True.
    assert window.scan_button.isEnabled() is False
    assert window.scan_button.text() == "Scanning…"

    window.busy_actions.end("scan")
    window._render_next_step(facts)
    assert window.scan_button.isEnabled() is True
    assert window.scan_button.text() == "Rescan and match library"



def test_render_next_step_does_not_hide_or_reenable_download_button_mid_download(
        qtbot,
):
    # Regression test for the real, reported bug found alongside 0.1:
    # download_button.setVisible(step.action != "download") could hide
    # the download button entirely mid-download, the instant the CTA's
    # own action was still "download" (which it usually still is, since
    # the missing-track count hasn't changed yet).
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.busy_actions.begin(
        "download", window.download_button, "Starting download…",
    )
    assert window.download_button.isEnabled() is False

    # CTA's own current action is "download" -- pre-fix, setVisible(step
    # .action != "download") would hide the button here.
    facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name="Test Playlist",
        track_statuses=[_make_track_status(state=NOT_FOUND)],
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(facts)

    assert not window.download_button.isHidden()
    assert window.download_button.isEnabled() is False
    assert window.download_button.text() == "Starting download…"

    window.busy_actions.end("download")
    window._render_next_step(facts)
    assert window.download_button.isHidden()  # CTA now owns it
    assert window.download_button.text() == "Download selected playlist"



def test_global_action_buttons_have_the_renamed_labels(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.sync_button.text() == "Refresh playlists"
    assert window.scan_button.text() == "Rescan and match library"
    assert window.match_button.text() == "Re-match library"
    assert window.download_button.text() == "Download selected playlist"


# --- Dashboard "next step" CTA (roadmap item 7) -----------------------------



def test_next_step_notice_hidden_when_nothing_selected_and_all_set_up(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        locations=[(
            LibraryLocation(
                id=1, name="Main", path="/music",
                added_at="2026-01-01T00:00:00+00:00",
            ),
            True,
        )],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.wait(50)
    assert window.next_step_notice.isHidden()



def test_next_step_notice_shows_connect_spotify_first(qtbot):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.next_step_notice.isHidden(), timeout=2000,
    )
    assert "spotify" in window.next_step_notice.text().lower()



def test_dismissed_next_step_notice_stays_hidden_across_poll_ticks(qtbot):
    # Regression test for the real reported bug: "You're all set"
    # reappeared ~2s after being dismissed, because _render_next_step
    # called show_message() unconditionally on every poll tick with no
    # memory of the dismissal. Drives _render_next_step directly
    # (not the real 2s timer) so three "ticks" are deterministic.
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    facts = _NextStepFacts(
        spotify_configured=False,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(facts)
    assert not window.next_step_notice.isHidden()

    window.next_step_notice.dismiss()
    assert window.next_step_notice.isHidden()

    for _ in range(3):
        window._render_next_step(facts)
        assert window.next_step_notice.isHidden()

    # A genuinely different step (facts changed) must still surface —
    # dismissal is per-step, not a permanent silence.
    other_facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=False,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._render_next_step(other_facts)
    assert not window.next_step_notice.isHidden()
    assert "music folder" in window.next_step_notice.text().lower()



def test_dismissed_next_step_notice_reappears_when_it_recurs_later(qtbot):
    # The identical step recurring after something else was shown in
    # between must NOT stay suppressed by an old dismissal.
    from seeker.ui.main_window import _NextStepFacts

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    step_facts = _NextStepFacts(
        spotify_configured=False,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    all_set_facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )

    window._render_next_step(step_facts)
    assert not window.next_step_notice.isHidden()
    window.next_step_notice.dismiss()

    window._render_next_step(all_set_facts)
    assert window.next_step_notice.isHidden()

    # The same step comes back later (e.g. the user disconnected
    # Spotify again) -- it must show, not stay silenced by the earlier
    # dismissal of a since-superseded instance of it.
    window._render_next_step(step_facts)
    assert not window.next_step_notice.isHidden()


# --- Roadmap item 72 (P1): tagging row reflows, playlist panel keeps its
# floor ------------------------------------------------------------------



def test_dashboard_content_minimum_width_fits_under_the_app_minimum(qtbot):
    # Regression test for the real reported bug: a plain QHBoxLayout's
    # minimum width is the SUM of its children's minimum widths, so the
    # 9-widget tagging controls row imposed a ~900-1000px floor on the
    # whole dashboard page, squeezing the playlist panel next to it
    # down to almost nothing at the app's own 960x640 minimum window
    # size (main_window.py:945).
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.resize(960, 640)

    dashboard_content = window.playlist_list.parentWidget()
    assert dashboard_content.minimumSizeHint().width() < 960



def test_playlist_list_keeps_its_floor_at_the_app_minimum_window_size(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.resize(960, 640)
    qtbot.wait(20)

    assert window.playlist_list.minimumWidth() > 0
    assert window.playlist_list.width() >= window.playlist_list.minimumWidth()


# --- Roadmap item 56 Phase 3: Settings as an in-window page -----------------



def test_next_step_notice_shows_download_count_and_triggers_download_flow(
        qtbot, monkeypatch,
):
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    statuses = [
        TrackStatus(track=_make_track("t1"), state=NOT_FOUND),
        TrackStatus(track=_make_track("t2"), state=NOT_FOUND),
    ]
    application = FakeApplication(
        # download_location_id=1 -- this playlist already has its own
        # destination, so Download proceeds directly with no dialog
        # (roadmap item 65 Phase 3.2: only a playlist with none of its
        # own gets prompted).
        playlists=[
            Playlist(
                id="p1", name="Test", track_count=2, download_location_id=1,
            ),
        ],
        locations=[(location, True)],
        statuses=statuses,
        soulseek_configured=True,
        resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: "2" in window.next_step_notice.text(), timeout=2000,
    )
    assert window.next_step_notice.text() == "2 tracks missing from 'Test'."

    window._on_next_step_action("download")

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )



def test_action_row_download_button_hides_while_cta_offers_the_same_action(
        qtbot,
):
    # download_button and the CTA's own "download" action both call the
    # identical download_playlist() against the identical unmatched-
    # tracks set — showing both is a real duplicate, not two distinct
    # actions, so the row's copy hides while the CTA already offers it.
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        locations=[(location, True)],
        statuses=[TrackStatus(track=_make_track("t1"), state=NOT_FOUND)],
        soulseek_configured=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        window.download_button.isHidden, timeout=2000,
    )



def test_action_row_download_button_visible_when_cta_offers_something_else(
        qtbot,
):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[],  # CTA offers "Load tracks", not "download".
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    assert not window.download_button.isHidden()



def test_download_button_disabled_with_no_playlist_selected(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.wait(50)
    assert not window.download_button.isEnabled()



def test_sync_button_disabled_when_spotify_not_connected(qtbot):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.sync_button.isEnabled(), timeout=2000,
    )



def test_scan_button_disabled_with_no_library_location(qtbot):
    application = FakeApplication(locations=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.scan_button.isEnabled(), timeout=2000,
    )



def test_match_button_disabled_with_nothing_to_match(qtbot):
    application = FakeApplication(playlists=[], locations=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window.match_button.isEnabled(), timeout=2000,
    )



def test_all_action_buttons_enabled_once_everything_is_set_up(qtbot):
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        locations=[(location, True)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window.sync_button.isEnabled()
        and window.scan_button.isEnabled()
        and window.match_button.isEnabled(),
        timeout=2000,
    )
    _select_first_playlist(window, qtbot)
    assert window.download_button.isEnabled()



def test_no_playlist_selected_shows_centred_empty_panel_no_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window.track_area_stack.currentWidget() is window._track_empty_panel
    assert "pick a playlist" in window.track_empty_label.text().lower()
    assert window.sync_tracks_button.isHidden()



def test_playlist_selected_no_tracks_shows_empty_panel_with_load_button(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=0)],
        statuses=[],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    # Both "nothing selected yet" and "selected but empty" render the
    # same panel widget — wait on the label text actually changing to
    # the playlist-specific message, not just on the panel being
    # current (already true before selection even happens).
    qtbot.waitUntil(
        lambda: "test" in window.track_empty_label.text().lower(),
        timeout=2000,
    )
    assert window.track_area_stack.currentWidget() is window._track_empty_panel
    assert not window.sync_tracks_button.isHidden()



def test_playlist_with_tracks_shows_the_real_table(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[TrackStatus(track=_make_track("t1"), state=NOT_FOUND)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: (
            window.track_area_stack.currentWidget() is window.track_table_card
        ),
        timeout=2000,
    )
    assert window.track_table.rowCount() == 1


# --- Download destination dialog (roadmap item 6 §3, "no dead end") -------



def test_main_window_populates_playlist_list_from_service(qtbot):
    playlists = [Playlist(id="p1", name="Test Playlist", track_count=3)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)

    assert "Test Playlist" in window.playlist_list.item(0).text()



def test_main_window_shows_sync_tracks_prompt_when_playlist_has_no_tracks(
        qtbot,
):
    # No auto-fetch of Spotify tracks on selection — an explicit button
    # instead (roadmap item 1's scoped-sync-tracks split).
    playlists = [Playlist(id="p1", name="Empty Playlist", track_count=0)]
    application = FakeApplication(playlists=playlists, statuses=[])
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)

    qtbot.waitUntil(
        window.sync_tracks_button.isVisible, timeout=2000,
    )
    assert application.sync_service.sync_playlist_tracks_calls == []



def test_needs_review_status_cell_has_tooltip_other_states_dont(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=2)],
        statuses=[
            _make_track_status(track_id="t1", state=NEEDS_REVIEW),
            _make_track_status(track_id="t2", state=IN_LIBRARY),
        ],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(lambda: window.track_table.rowCount() == 2, timeout=2000)
    assert window.track_table.item(0, 1).toolTip() != ""
    assert window.track_table.item(1, 1).toolTip() == ""



def test_dashboard_downloading_progress_bar_gets_the_accent_chunk_style(qtbot):
    # This cell is only ever rendered determinate (blank otherwise — see
    # _render_track_statuses), but it shares theme.py's
    # style_determinate_progress_bar() with the Downloads tab's own bar,
    # so it needs the identical guard against a regression that skips
    # applying it.
    status = TrackStatus(
        track=_make_track("t1"), state=DOWNLOADING,
        bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses([status])

    # Roadmap item C3 (round 5) — this cell widget is now wrapped by
    # _wrap_progress_bar (see the test just below for why: a bare bar
    # here reproduced the exact same top-clamped-bar bug B4/item 96
    # fixed on the Downloads page), so the real QProgressBar is a
    # child of the cell widget, not the cell widget itself.
    container = window.track_table.cellWidget(0, 2)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert "chunk" in bar.styleSheet()



def test_tag_button_appears_only_for_in_library_tracks(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY),
        _make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    in_library_actions = window.track_table.cellWidget(0, 3)
    assert [
            b.text() for b in in_library_actions.findChildren(QPushButton)
    ] == ["Tag"]

    not_found_actions = window.track_table.cellWidget(1, 3)
    assert not_found_actions.findChildren(QPushButton) == []



def test_tagged_track_shows_muted_label_instead_of_tag_button(qtbot):
    statuses = [
        _make_track_status(
            track_id="t1", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    actions = window.track_table.cellWidget(0, 3)
    assert actions.findChildren(QPushButton) == []
    labels = actions.findChildren(QLabel)
    assert [label.text() for label in labels] == ["Tagged"]
    assert "2026" in labels[0].toolTip()



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

    window._render_track_statuses(statuses)
    # The panel-wide force checkbox is deliberately left unchecked —
    # Re-tag via the context menu must force regardless of it.
    assert (
        window._dashboard_page._tagging_panel.force_retag_checkbox.isChecked()
        is False
    )

    window._on_retag_track_clicked("t5")

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t5"], False, None, True),
    ]



def test_context_menu_offers_nothing_for_an_untagged_or_missing_row(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None),
        _make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)

    # Neither row offers a real "Re-tag" action — an untagged row has
    # nothing to re-tag, and a not-in-library row has no local file at
    # all. Calling the handler directly (no real QMenu popup in an
    # offscreen test) must simply do nothing, not raise.
    window._on_track_table_context_menu(window.track_table.visualItemRect(
        window.track_table.item(0, 0)
    ).center())
    window._on_track_table_context_menu(window.track_table.visualItemRect(
        window.track_table.item(1, 0)
    ).center())



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

    window._render_track_statuses(statuses)
    window._dashboard_page._tagging_panel.force_retag_checkbox.setChecked(True)

    actions = window.track_table.cellWidget(0, 3)
    tag_button = actions.findChildren(QPushButton)[0] if actions.findChildren(
        QPushButton
    ) else None
    # This row is already tagged, so the per-row control is the muted
    # label, not a button — exercise the panel-wide checkbox via "Tag
    # selected" and "Tag playlist" instead, both of which apply
    # regardless of a row's own tagged state.
    assert tag_button is None

    selection_model = window.track_table.selectionModel()
    selection_model.select(
        window.track_table.model().index(0, 0),
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )
    window._dashboard_page._tagging_panel.tag_selected_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.tag_tracks_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.tag_tracks_calls == [
        (["t7"], False, None, True),
    ]

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)
    window._dashboard_page._tagging_panel.tag_playlist_button.click()

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

    window._render_track_statuses(statuses)

    actions = window.track_table.cellWidget(0, 3)
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

    window._render_track_statuses(statuses)

    window._dashboard_page._tagging_panel.analyze_audio_checkbox.setChecked(True)
    window._dashboard_page._tagging_panel.bpm_min_edit.setText("160")
    window._dashboard_page._tagging_panel.bpm_max_edit.setText("180")

    actions = window.track_table.cellWidget(0, 3)
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

    window._render_track_statuses(statuses)

    window._dashboard_page._tagging_panel.analyze_audio_checkbox.setChecked(True)
    window._dashboard_page._tagging_panel.bpm_min_edit.setText("160")
    # bpm_max_edit deliberately left blank.

    actions = window.track_table.cellWidget(0, 3)
    actions.findChildren(QPushButton)[0].click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "both" in window.dashboard_notice.text().lower()
    assert not window.dashboard_notice.isHidden()



def test_dashboard_notice_survives_the_2s_poll_that_used_to_wipe_it(qtbot):
    # Regression test for the real root cause found while building
    # Phase 3: run_worker() clears its target status_label to "" at the
    # START of every call, and _poll_selected_playlist() (which passes
    # status_label=self.status_label) runs on both the 2s poll_timer
    # tick and after every real backend poll — so ANY message written
    # to the old shared status_label had at most ~2s, often far less,
    # before the next poll silently wiped it regardless of severity.
    # InlineNotice lives outside run_worker's status_label plumbing
    # entirely, so a real poll tick must never clear it.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window.dashboard_notice.show_message(
            "Something worth reading",
            kind="error",
    )
    assert not window.dashboard_notice.isHidden()

    window._poll_selected_playlist()
    qtbot.wait(50)

    assert window.dashboard_notice.text() == "Something worth reading"
    assert not window.dashboard_notice.isHidden()



def test_tag_selected_calls_tag_tracks_with_selected_ids(qtbot):
    statuses = [
        _make_track_status(track_id="s1", state=IN_LIBRARY),
        _make_track_status(track_id="s2", state=IN_LIBRARY),
        _make_track_status(track_id="s3", state=IN_LIBRARY),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_track_statuses(statuses)
    # Select rows 0 and 2 additively through the selection model itself
    # (QItemSelectionModel.Select | .Rows) — selectRow() replaces the
    # existing selection instead of adding to it, which isn't what a
    # real ctrl/shift-click multi-select produces.
    selection_model = window.track_table.selectionModel()
    for row in (0, 2):
        selection_model.select(
            window.track_table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )

    window._dashboard_page._tagging_panel.tag_selected_button.click()

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

    window._render_track_statuses(statuses)
    window._dashboard_page._tagging_panel.tag_selected_button.click()

    assert application.metadata_service.tag_tracks_calls == []
    assert "select" in window.dashboard_notice.text().lower()



def test_tag_playlist_calls_tag_playlist_with_playlist_name(qtbot):
    playlists = [Playlist(id="p1", name="240KM/H", track_count=5)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(lambda: window.playlist_list.count() == 1, timeout=2000)
    window.playlist_list.setCurrentRow(0)

    window._dashboard_page._tagging_panel.tag_playlist_button.click()

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

    window._dashboard_page._tagging_panel.tag_playlist_button.click()

    assert application.metadata_service.tag_playlist_calls == []
    assert "playlist" in window.dashboard_notice.text().lower()



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

    window._render_tag_result(result)

    text = window._dashboard_page._tagging_panel.tagging_results.toPlainText()
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

    window._render_tag_result({
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

    assert not window.dashboard_notice.isHidden()
    assert "2 without cover art" in window.dashboard_notice.text()



def test_tag_result_notice_shows_success_when_everything_worked(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_tag_result({
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

    assert not window.dashboard_notice.isHidden()
    assert "Tagged 5 tracks" in window.dashboard_notice.text()
    assert "without cover art" not in window.dashboard_notice.text()



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

    window._render_tag_result({
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

    assert not window.dashboard_notice.isHidden()
    text = window.dashboard_notice.text()
    assert "4 track" in text
    assert "already tagged" in text
    assert "Re-tag" in text
    # Roadmap item 75 (P6, 6.2) — the real gap: "already tagged" here
    # does not mean "art is fine," it means art was never checked.
    assert "NOT checked" in text
    assert not window.dashboard_notice._action_button.isHidden()
    assert (
        window.dashboard_notice._action_button.text()
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

    window._render_tag_result({
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

    assert not window.dashboard_notice.isHidden()
    text = window.dashboard_notice.text()
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

    window._render_tag_result({
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

    window.dashboard_notice._action_button.click()

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

    window._dashboard_page._tagging_panel.fix_missing_art_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service
        .fix_missing_art_for_playlist_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.fix_missing_art_for_playlist_calls == [
        "Test",
    ]
    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Fixed art for 3" in window.dashboard_notice.text(),
        timeout=2000,
    )
    text = window.dashboard_notice.text()
    assert "2 already correct" in text
    assert "1 missing an art URL" in text
    assert "already correct" in text.lower()



def test_fix_missing_art_button_requires_a_selected_playlist(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._tagging_panel.fix_missing_art_button.click()

    assert not window.dashboard_notice.isHidden()
    assert "playlist" in window.dashboard_notice.text().lower()
    assert application.metadata_service.fix_missing_art_for_playlist_calls == []



def test_fill_missing_art_urls_button_reports_the_real_count(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists, art_urls_filled=7)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page._tagging_panel.fill_missing_art_urls_button.click()

    qtbot.waitUntil(
        lambda: application.sync_service.sync_playlist_tracks_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "7" in window.dashboard_notice.text(),
        timeout=2000,
    )
    assert "Filled in 7 missing album art URLs" in window.dashboard_notice.text()



def test_fill_missing_art_urls_button_reports_zero_found(qtbot):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(playlists=playlists, art_urls_filled=0)
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page._tagging_panel.fill_missing_art_urls_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "No missing" in window.dashboard_notice.text(),
        timeout=2000,
    )


# --- Rename preview dialog (roadmap item 67, Phase 6.4) --------------------



def test_rename_files_button_requires_a_selected_playlist(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._tagging_panel.rename_files_button.click()

    assert not window.dashboard_notice.isHidden()
    assert "playlist" in window.dashboard_notice.text().lower()
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

    window._dashboard_page._tagging_panel.rename_files_button.click()

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

    window._dashboard_page._tagging_panel.rename_files_button.click()

    qtbot.waitUntil(
        lambda: application.metadata_service.apply_renames_calls != [],
        timeout=2000,
    )
    assert application.metadata_service.apply_renames_calls == [plans]
    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Renamed 1" in window.dashboard_notice.text(),
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

    window._dashboard_page._tagging_panel.rename_files_button.click()

    qtbot.waitUntil(
        lambda: not window.dashboard_notice.isHidden()
        and "Renamed 2" in window.dashboard_notice.text(),
        timeout=2000,
    )
    text = window.dashboard_notice.text()
    assert "1 file" in text
    assert "DIFFERENT name than the preview" in text


# --- Duplicates tab (roadmap item 5) ---------------------------------------
#
# Locations load lazily, only once the page is actually shown (see
# main_window.py's own comment on _on_page_changed for why — an eager
# worker here, run during every MainWindow construction, was confirmed
# live to cause a real, reproducible deadlock under this test suite's
# own rapid-fire construction pattern). Tests below drive that
# explicitly rather than relying on construction alone.



def test_dashboard_downloading_bar_is_vertically_centered(qtbot):
    # Roadmap item C3 (round 5) — the real reported bug: the DASHBOARD
    # track table (Track/Status/Progress/Actions, with "In library"/
    # "Downloading" rows) builds its own bare QProgressBar directly in
    # `_render_track_statuses`, a second, independent site B4/item 96
    # never touched (that fix only reached the DOWNLOADS page's own
    # `_build_progress_widget`). Same real pixel-scan method as item
    # 96's own regression test — this is the Dashboard's own version of
    # it, proving the shared `_wrap_progress_bar` container now covers
    # both sites.
    status = TrackStatus(
        track=_make_track("t1"), state=DOWNLOADING,
        bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._render_track_statuses([status])
    qtbot.wait(100)

    viewport = window.track_table.viewport()
    row_rect = window.track_table.visualRect(
        window.track_table.model().index(0, 2)
    )
    widget = window.track_table.cellWidget(0, 2)
    assert widget is not None
    bar = widget.findChild(QProgressBar)
    assert bar is not None

    bar_center_y = bar.mapTo(viewport, bar.rect().center()).y()
    assert abs(bar_center_y - row_rect.center().y()) <= 2

    # Real pixel scan (item 102's own lesson: geometry alone can lie
    # about what actually got painted) — find the bar's real painted
    # color span and compare ITS midpoint to the row's real center.
    image = window.grab().toImage()
    dpr = image.width() / window.width()
    surface_rgb = tuple(
        int(theme.BG_SURFACE[i:i + 2], 16) for i in (1, 3, 5)
    )
    top_left = viewport.mapTo(window, viewport.rect().topLeft())
    x = round((top_left.x() + row_rect.left() + 10) * dpr)
    y0 = round((top_left.y() + row_rect.top()) * dpr)
    y1 = round((top_left.y() + row_rect.bottom()) * dpr)

    painted_ys = [
        y for y in range(y0, y1 + 1)
        if (
            image.pixelColor(x, y).red(),
            image.pixelColor(x, y).green(),
            image.pixelColor(x, y).blue(),
        ) != surface_rgb
    ]
    assert painted_ys, "no painted bar pixels found"
    painted_center = (painted_ys[0] + painted_ys[-1]) / 2 / dpr
    row_center = top_left.y() + row_rect.center().y()
    assert abs(painted_center - row_center) <= 2


"""Tests for the Dashboard page (seeker.ui.pages.dashboard_page): the
track table and its notices, the next-step CTA, and the page's own
actions — Refresh playlists, Rescan and match, Download (its
destination dialog and result notices), Load tracks — plus double-click
through to Review. Tests that drive TaggingPanel live in
test_library_page.py.
"""

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton

from fakes import (
    FakeApplication,
    make_needs_review_match,
    make_track,
    make_track_status,
)
from seeker.models.download_result import PlaylistDownloadResult, TrackFailure
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.spotify_sync import PlaylistRefreshResult, TrackSyncResult
from seeker.models.tag_result import TagResult
from seeker.models.track import Track
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    REVIEW_CANDIDATE,
    TrackStatus,
)
from seeker.ui import status_lamp, theme
from seeker.ui.dialogs import DestinationDialog
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

    window.busy_actions.begin("scan", window._dashboard_page.scan_button, "Scanning…")
    assert window._dashboard_page.scan_button.isEnabled() is False

    facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name=None,
        track_statuses=None,
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._dashboard_page._render_next_step(facts)

    # Pre-fix, this would have been re-enabled here since
    # facts.has_library_location is True.
    assert window._dashboard_page.scan_button.isEnabled() is False
    assert window._dashboard_page.scan_button.text() == "Scanning…"

    window.busy_actions.end("scan")
    window._dashboard_page._render_next_step(facts)
    assert window._dashboard_page.scan_button.isEnabled() is True
    assert window._dashboard_page.scan_button.text() == "Scan library"


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
        "download", window._dashboard_page.download_button, "Starting download…",
    )
    assert window._dashboard_page.download_button.isEnabled() is False

    # CTA's own current action is "download" -- pre-fix, setVisible(step
    # .action != "download") would hide the button here.
    facts = _NextStepFacts(
        spotify_configured=True,
        has_library_location=True,
        has_cached_playlists=True,
        selected_playlist_name="Test Playlist",
        track_statuses=[make_track_status(state=NOT_FOUND)],
        has_scanned_library=True,
        soulseek_configured=True,
    )
    window._dashboard_page._render_next_step(facts)

    assert not window._dashboard_page.download_button.isHidden()
    assert window._dashboard_page.download_button.isEnabled() is False
    assert window._dashboard_page.download_button.text() == "Starting download…"

    window.busy_actions.end("download")
    window._dashboard_page._render_next_step(facts)
    assert window._dashboard_page.download_button.isHidden()  # CTA now owns it
    assert window._dashboard_page.download_button.text() == "Download selected playlist"


def test_global_action_buttons_have_the_renamed_labels(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._dashboard_page.sync_button.text() == "Refresh playlists"
    assert window._dashboard_page.scan_button.text() == "Scan library"
    assert window._dashboard_page.match_button.text() == "Match tracks"
    assert window._dashboard_page.download_button.text() == "Download selected playlist"


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

    # The notice starts hidden, so assert only once the first render
    # has run: with nothing selected, it disables Download.
    qtbot.waitUntil(
        lambda: not window._dashboard_page.download_button.isEnabled(),
        timeout=2000,
    )
    assert window._dashboard_page.next_step_notice.isHidden()


def _one_location() -> list:
    return [(
        LibraryLocation(
            id=1, name="Main", path="/music",
            added_at="2026-01-01T00:00:00+00:00",
        ),
        True,
    )]


def test_next_step_says_a_selected_playlist_changed_on_spotify(qtbot):
    # Its cached tracks are all in the library and tagged, but they
    # come from an older snapshot: not "all set".
    stale = Playlist(
        id="p1", name="Peak Time", track_count=2,
        snapshot_id="s2", tracks_snapshot_id="s1",
    )
    application = FakeApplication(
        playlists=[stale], locations=_one_location(),
        statuses=[make_track_status(tagged_at="2026-01-01")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )

    window._dashboard_page.playlist_list.setCurrentRow(0)

    notice = window._dashboard_page.next_step_notice
    qtbot.waitUntil(
        lambda: "changed on Spotify" in notice.text(), timeout=2000,
    )
    assert "'Peak Time' changed on Spotify" in notice.text()
    assert "all set" not in notice.text()


def test_next_step_names_a_stale_playlist_with_nothing_selected(qtbot):
    playlists = [
        Playlist(id="p1", name="Current", track_count=1,
                 snapshot_id="s1", tracks_snapshot_id="s1"),
        Playlist(id="p2", name="Warmup", track_count=1,
                 snapshot_id="s3", tracks_snapshot_id="s2"),
    ]
    application = FakeApplication(
        playlists=playlists, locations=_one_location(),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    notice = window._dashboard_page.next_step_notice
    qtbot.waitUntil(lambda: not notice.isHidden(), timeout=2000)
    assert "'Warmup' changed on Spotify" in notice.text()


def test_refresh_playlists_reports_the_playlists_it_updated(qtbot):
    playlists = [
        Playlist(id="p1", name="Warmup", track_count=1),
        Playlist(id="p2", name="Peak", track_count=1),
    ]
    application = FakeApplication(
        playlists=playlists, locations=_one_location(),
    )
    application.sync_service.refresh_result = PlaylistRefreshResult(
        playlist_count=2, updated_playlist_names=["Peak"],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page.sync_button.click()

    notice = window._dashboard_page.dashboard_notice
    qtbot.waitUntil(lambda: not notice.isHidden(), timeout=2000)
    assert notice.text() == (
        "Refreshed 2 playlists. Updated tracks for 1 that changed on "
        "Spotify."
    )
    assert application.sync_service.refresh_playlists_calls == 1
    # Track re-syncs report progress on the activity strip.
    assert application.sync_service.refresh_progress is not None


def test_next_step_notice_shows_connect_spotify_first(qtbot):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window._dashboard_page.next_step_notice.isHidden(), timeout=2000,
    )
    assert "spotify" in window._dashboard_page.next_step_notice.text().lower()


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
    window._dashboard_page._render_next_step(facts)
    assert not window._dashboard_page.next_step_notice.isHidden()

    window._dashboard_page.next_step_notice.dismiss()
    assert window._dashboard_page.next_step_notice.isHidden()

    for _ in range(3):
        window._dashboard_page._render_next_step(facts)
        assert window._dashboard_page.next_step_notice.isHidden()

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
    window._dashboard_page._render_next_step(other_facts)
    assert not window._dashboard_page.next_step_notice.isHidden()
    assert "music folder" in window._dashboard_page.next_step_notice.text().lower()


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

    window._dashboard_page._render_next_step(step_facts)
    assert not window._dashboard_page.next_step_notice.isHidden()
    window._dashboard_page.next_step_notice.dismiss()

    window._dashboard_page._render_next_step(all_set_facts)
    assert window._dashboard_page.next_step_notice.isHidden()

    # The same step comes back later (e.g. the user disconnected
    # Spotify again) -- it must show, not stay silenced by the earlier
    # dismissal of a since-superseded instance of it.
    window._dashboard_page._render_next_step(step_facts)
    assert not window._dashboard_page.next_step_notice.isHidden()


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

    dashboard_content = window._dashboard_page.playlist_list.parentWidget()
    assert dashboard_content.minimumSizeHint().width() < 960


def test_playlist_list_keeps_its_floor_at_the_app_minimum_window_size(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.resize(960, 640)
    qtbot.wait(20)

    assert window._dashboard_page.playlist_list.minimumWidth() > 0
    assert (
        window._dashboard_page.playlist_list.width()
        >= window._dashboard_page.playlist_list.minimumWidth()
    )


def test_next_step_notice_shows_download_count_and_triggers_download_flow(
        qtbot, monkeypatch,
):
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    statuses = [
        TrackStatus(track=make_track("t1"), state=NOT_FOUND),
        TrackStatus(track=make_track("t2"), state=NOT_FOUND),
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
        lambda: "2" in window._dashboard_page.next_step_notice.text(), timeout=2000,
    )
    assert (
        window._dashboard_page.next_step_notice.text()
        == "2 tracks missing from 'Test'."
    )

    window._dashboard_page._on_next_step_action("download")

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
        statuses=[TrackStatus(track=make_track("t1"), state=NOT_FOUND)],
        soulseek_configured=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        window._dashboard_page.download_button.isHidden, timeout=2000,
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

    assert not window._dashboard_page.download_button.isHidden()


def test_download_button_disabled_with_no_playlist_selected(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # Enabled is Qt's default; the disable comes from the next-step
    # facts, fetched on a worker, so wait for it rather than a fixed time.
    download_button = window._dashboard_page.download_button
    qtbot.waitUntil(lambda: not download_button.isEnabled(), timeout=2000)


def test_sync_button_disabled_when_spotify_not_connected(qtbot):
    application = FakeApplication(spotify_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window._dashboard_page.sync_button.isEnabled(), timeout=2000,
    )


def test_scan_button_disabled_with_no_library_location(qtbot):
    application = FakeApplication(locations=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window._dashboard_page.scan_button.isEnabled(), timeout=2000,
    )


def test_match_button_disabled_with_nothing_to_match(qtbot):
    application = FakeApplication(playlists=[], locations=[])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: not window._dashboard_page.match_button.isEnabled(), timeout=2000,
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
        lambda: window._dashboard_page.sync_button.isEnabled()
        and window._dashboard_page.scan_button.isEnabled()
        and window._dashboard_page.match_button.isEnabled(),
        timeout=2000,
    )
    _select_first_playlist(window, qtbot)
    assert window._dashboard_page.download_button.isEnabled()


def test_no_playlist_selected_shows_centred_empty_panel_no_button(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert (
        window._dashboard_page.track_area_stack.currentWidget()
        is window._dashboard_page._track_empty_panel
    )
    assert (
        "pick a playlist"
        in window._dashboard_page.track_empty_label.text().lower()
    )
    assert window._dashboard_page.sync_tracks_button.isHidden()


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
        lambda: "test" in window._dashboard_page.track_empty_label.text().lower(),
        timeout=2000,
    )
    assert (
        window._dashboard_page.track_area_stack.currentWidget()
        is window._dashboard_page._track_empty_panel
    )
    assert not window._dashboard_page.sync_tracks_button.isHidden()


def test_playlist_with_tracks_shows_the_real_table(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[TrackStatus(track=make_track("t1"), state=NOT_FOUND)],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.track_area_stack.currentWidget()
            is window._dashboard_page.track_table_card
        ),
        timeout=2000,
    )
    assert window._dashboard_page.track_table.rowCount() == 1


def test_main_window_populates_playlist_list_from_service(qtbot):
    playlists = [Playlist(id="p1", name="Test Playlist", track_count=3)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )

    assert "Test Playlist" in window._dashboard_page.playlist_list.item(0).text()


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

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)

    qtbot.waitUntil(
        window._dashboard_page.sync_tracks_button.isVisible, timeout=2000,
    )
    assert application.sync_service.sync_playlist_tracks_calls == []


def test_load_tracks_warns_when_spotify_local_files_were_skipped(qtbot):
    # A Spotify local file has no Spotify id, so it can never be matched
    # or downloaded automatically; a DJ needs to be told.
    playlists = [Playlist(id="p1", name="Bootlegs", track_count=5)]
    application = FakeApplication(playlists=playlists, statuses=[])
    application.sync_service.track_sync_result = TrackSyncResult(
        tracks_saved=3, local_files_skipped=2,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    qtbot.waitUntil(
        window._dashboard_page.sync_tracks_button.isVisible, timeout=2000,
    )

    window._dashboard_page.sync_tracks_button.click()

    notice = window._dashboard_page.dashboard_notice
    qtbot.waitUntil(lambda: not notice.isHidden(), timeout=2000)
    assert "2 Spotify local files" in notice.text()
    assert "Bootlegs" in notice.text()


def test_load_tracks_shows_no_notice_when_nothing_was_skipped(qtbot):
    playlists = [Playlist(id="p1", name="Clean", track_count=3)]
    application = FakeApplication(playlists=playlists, statuses=[])
    application.sync_service.track_sync_result = TrackSyncResult(
        tracks_saved=3,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    window._dashboard_page.playlist_list.setCurrentRow(0)
    qtbot.waitUntil(
        window._dashboard_page.sync_tracks_button.isVisible, timeout=2000,
    )

    window._dashboard_page.sync_tracks_button.click()

    # The busy action ends in the same main-thread call that runs the
    # finish handler, which is what would show a notice.
    qtbot.waitUntil(
        lambda: application.sync_service.sync_playlist_tracks_calls != []
        and not window.busy_actions.is_running("sync_tracks"),
        timeout=2000,
    )
    assert window._dashboard_page.dashboard_notice.isHidden()


def test_dashboard_reflects_a_selection_write_that_originates_elsewhere(
        qtbot,
):
    # round9 §7.2 — Library's own picker writes into the shared
    # PlaylistSelection too, not just Dashboard's playlist_list click.
    # "One selection, two views, never two truths" requires Dashboard
    # to notice a write it didn't itself make.
    playlists = [Playlist(id="p1", name="Elsewhere", track_count=4)]
    application = FakeApplication(playlists=playlists)
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(
        lambda: window._dashboard_page.playlist_list.count() == 1, timeout=2000,
    )
    assert window._dashboard_page.playlist_list.currentItem() is None

    # Simulates the write Library's inline picker makes — never touches
    # Dashboard's own playlist_list widget directly.
    window.playlist_selection.set_playlist(playlists[0])

    qtbot.waitUntil(
        lambda: (
            (current := window._dashboard_page.playlist_list.currentItem())
            is not None
            and current.data(Qt.ItemDataRole.UserRole) == playlists[0]
        ),
        timeout=2000,
    )
    assert "Elsewhere" in application.dashboard_service.calls


def test_needs_review_status_cell_has_tooltip_other_states_dont(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=2)],
        statuses=[
            make_track_status(track_id="t1", state=NEEDS_REVIEW),
            make_track_status(track_id="t2", state=IN_LIBRARY),
        ],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 2, timeout=2000,
    )
    assert window._dashboard_page.track_table.item(0, 1).toolTip() != ""
    assert window._dashboard_page.track_table.item(1, 1).toolTip() == ""


def test_dashboard_downloading_progress_bar_gets_the_accent_chunk_style(qtbot):
    # This cell is only ever rendered determinate (blank otherwise — see
    # _render_track_statuses), but it shares theme.py's
    # style_determinate_progress_bar() with the Downloads tab's own bar,
    # so it needs the identical guard against a regression that skips
    # applying it.
    status = TrackStatus(
        track=make_track("t1"), state=DOWNLOADING,
        bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses([status])

    # Roadmap item C3 (round 5) — this cell widget is now wrapped by
    # _wrap_progress_bar (see the test just below for why: a bare bar
    # here reproduced the exact same top-clamped-bar bug B4/item 96
    # fixed on the Downloads page), so the real QProgressBar is a
    # child of the cell widget, not the cell widget itself.
    container = window._dashboard_page.track_table.cellWidget(0, 2)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert "chunk" in bar.styleSheet()


def test_tag_button_appears_only_for_in_library_tracks(qtbot):
    statuses = [
        make_track_status(track_id="t1", state=IN_LIBRARY),
        make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    in_library_actions = window._dashboard_page.track_table.cellWidget(0, 3)
    assert [
            b.text() for b in in_library_actions.findChildren(QPushButton)
    ] == ["Tag"]

    assert window._dashboard_page.track_table.cellWidget(1, 3) is None


def test_tagged_track_shows_muted_label_instead_of_tag_button(qtbot):
    statuses = [
        make_track_status(
            track_id="t1", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    assert actions.findChildren(QPushButton) == []
    labels = actions.findChildren(QLabel)
    assert [label.text() for label in labels] == ["Tagged"]
    assert "2026" in labels[0].toolTip()


def test_context_menu_offers_nothing_for_an_untagged_or_missing_row(qtbot):
    statuses = [
        make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None),
        make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    # Neither row offers a real "Re-tag" action — an untagged row has
    # nothing to re-tag, and a not-in-library row has no local file at
    # all. Calling the handler directly (no real QMenu popup in an
    # offscreen test) must simply do nothing, not raise.
    window._dashboard_page._on_track_table_context_menu(window._dashboard_page.track_table.visualItemRect(
        window._dashboard_page.track_table.item(0, 0)
    ).center())
    window._dashboard_page._on_track_table_context_menu(window._dashboard_page.track_table.visualItemRect(
        window._dashboard_page.track_table.item(1, 0)
    ).center())


def test_dashboard_notice_survives_the_2s_poll_that_used_to_wipe_it(qtbot):
    # Regression test for the real root cause found while building
    # Phase 3: run_worker() clears its target status_label to "" at the
    # START of every call, and poll_selected_playlist() (which passes
    # status_label=self.status_label) runs on both the 2s poll_timer
    # tick and after every real backend poll — so ANY message written
    # to the old shared status_label had at most ~2s, often far less,
    # before the next poll silently wiped it regardless of severity.
    # InlineNotice lives outside run_worker's status_label plumbing
    # entirely, so a real poll tick must never clear it.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page.dashboard_notice.show_message(
            "Something worth reading",
            kind="error",
    )
    assert not window._dashboard_page.dashboard_notice.isHidden()

    window._dashboard_page.poll_selected_playlist()
    qtbot.wait(50)

    assert window._dashboard_page.dashboard_notice.text() == "Something worth reading"
    assert not window._dashboard_page.dashboard_notice.isHidden()


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
        track=make_track("t1"), state=DOWNLOADING,
        bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._dashboard_page._render_track_statuses([status])
    qtbot.wait(100)

    viewport = window._dashboard_page.track_table.viewport()
    row_rect = window._dashboard_page.track_table.visualRect(
        window._dashboard_page.track_table.model().index(0, 2)
    )
    widget = window._dashboard_page.track_table.cellWidget(0, 2)
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
        int(theme.active_palette().BG_SURFACE[i:i + 2], 16) for i in (1, 3, 5)
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


# --- Track status filter (round 8 §12.8) ------------------------------------


def _visible_track_ids(window) -> set[str]:
    # Reads each row's own UserRole anchor (see _render_track_statuses),
    # not the displayed label — every track in these tests shares the
    # same "Artist - Title" text (fakes.py's make_track), so
    # only the id actually distinguishes rows.
    table = window._dashboard_page.track_table
    return {
        table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(table.rowCount())
    }


def test_track_filter_defaults_to_all_and_shows_every_status(qtbot):
    statuses = [
        make_track_status(track_id="t1", state=IN_LIBRARY),
        make_track_status(track_id="t2", state=NOT_FOUND),
        make_track_status(track_id="t3", state=NEEDS_REVIEW),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert (
        window._dashboard_page._track_filter_buttons["all"].isChecked()
    )
    window._dashboard_page._render_track_statuses(statuses)

    assert window._dashboard_page.track_table.rowCount() == 3


def test_track_filter_missing_shows_not_found_and_review_candidate_only(qtbot):
    statuses = [
        make_track_status(track_id="t1", state=IN_LIBRARY),
        make_track_status(track_id="t2", state=NOT_FOUND),
        make_track_status(track_id="t3", state=REVIEW_CANDIDATE),
        make_track_status(track_id="t4", state=NEEDS_REVIEW),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    window._dashboard_page._track_filter_buttons["missing"].click()

    assert window._dashboard_page.track_table.rowCount() == 2
    assert _visible_track_ids(window) == {"t2", "t3"}


def test_track_filter_needs_review_shows_needs_and_awaiting_review_only(qtbot):
    statuses = [
        make_track_status(track_id="t1", state=NEEDS_REVIEW),
        make_track_status(track_id="t2", state=AWAITING_REVIEW),
        make_track_status(track_id="t3", state=NOT_FOUND),
        make_track_status(track_id="t4", state=IN_LIBRARY),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    window._dashboard_page._track_filter_buttons["needs_review"].click()

    assert window._dashboard_page.track_table.rowCount() == 2
    assert _visible_track_ids(window) == {"t1", "t2"}


def test_track_filter_untagged_shows_untagged_in_library_tracks_only(qtbot):
    statuses = [
        make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None),
        make_track_status(
            track_id="t2", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
        make_track_status(track_id="t3", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    window._dashboard_page._track_filter_buttons["untagged"].click()

    assert window._dashboard_page.track_table.rowCount() == 1
    assert _visible_track_ids(window) == {"t1"}


def test_track_filter_with_no_matches_shows_empty_state_without_load_button(
        qtbot,
):
    statuses = [make_track_status(track_id="t1", state=IN_LIBRARY)]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)
    window._dashboard_page._track_filter_buttons["missing"].click()

    assert window._dashboard_page.track_table.rowCount() == 0
    assert (
        window._dashboard_page.track_area_stack.currentWidget()
        is window._dashboard_page._track_empty_panel
    )
    assert "filter" in window._dashboard_page.track_empty_label.text().lower()
    # Distinct from the "tracks haven't been loaded yet" empty state —
    # there's nothing to load here, so no button.
    assert window._dashboard_page.sync_tracks_button.isHidden()

    # Switching back to "All" restores the real row.
    window._dashboard_page._track_filter_buttons["all"].click()
    assert window._dashboard_page.track_table.rowCount() == 1


def _run_one_poll_tick(window, qtbot) -> None:
    # What the 2 s track-status timer does; waits for its render so a
    # label it cleared at submit time stays cleared.
    calls = window._dashboard_page._context.application.dashboard_service.calls
    before = len(calls)
    window._dashboard_page.poll_selected_playlist()
    qtbot.waitUntil(lambda: len(calls) > before, timeout=2000)
    qtbot.wait(50)


def test_scan_summary_stays_readable_after_the_next_poll_tick(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Warmup", track_count=1)],
        locations=_one_location(),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.scan_button.click()
    qtbot.waitUntil(
        lambda: application.library_service.scan_and_match_calls == 1,
        timeout=2000,
    )
    qtbot.waitUntil(window._dashboard_page.scan_button.isEnabled, timeout=2000)
    _run_one_poll_tick(window, qtbot)

    notice = window._dashboard_page.dashboard_notice
    assert not notice.isHidden()
    assert "Scanned: 0 added" in notice.text()
    # In-progress text only; nothing left over once the scan is done.
    assert window._dashboard_page.status_label.text() == ""


def test_failed_refresh_playlists_error_stays_readable(qtbot):
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Warmup", track_count=1)],
        locations=_one_location(),
    )
    application.sync_service.refresh_error = RuntimeError(
        "Spotify is rate-limiting Seeker. Try again in 3h 42m.",
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.sync_button.click()
    qtbot.waitUntil(
        lambda: application.sync_service.refresh_playlists_calls == 1,
        timeout=2000,
    )
    qtbot.waitUntil(window._dashboard_page.sync_button.isEnabled, timeout=2000)
    _run_one_poll_tick(window, qtbot)

    notice = window._dashboard_page.dashboard_notice
    assert not notice.isHidden()
    assert "rate-limiting" in notice.text()


def test_tag_from_a_dashboard_row_reports_on_the_dashboard(qtbot):
    tag_result = TagResult(
        failed=1,
        details=[{
            "track_id": "t1", "reason": "failed",
            "message": "File not found: /music/a.mp3",
        }],
    )
    application = FakeApplication(tag_result=tag_result)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._dashboard_page._render_track_statuses([
        make_track_status(track_id="t1", state=IN_LIBRARY),
    ])

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    [button] = actions.findChildren(QPushButton)
    button.click()

    dashboard_notice = window._dashboard_page.dashboard_notice
    qtbot.waitUntil(lambda: not dashboard_notice.isHidden(), timeout=2000)
    assert "failed" in dashboard_notice.text().lower()
    assert window._library_page.notice.isHidden()


def test_scan_button_click_calls_scan_and_match_not_scan_all(qtbot):
    # Roadmap item 56 — the guided scan action must chain into a match
    # pass in one call, not leave newly-scanned files unmatched until a
    # separate "Re-match library" click.
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(locations=[(location, True)])
    window = MainWindow(application)
    qtbot.addWidget(window)

    qtbot.waitUntil(window._dashboard_page.scan_button.isEnabled, timeout=2000)
    window._dashboard_page.scan_button.click()

    qtbot.waitUntil(
        lambda: application.library_service.scan_and_match_calls == 1,
        timeout=2000,
    )
    assert application.library_service.scan_all_calls == 0


def test_download_with_no_selection_shows_a_warning_notice(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page.download_button.click()

    assert "playlist" in window._dashboard_page.dashboard_notice.text().lower()
    assert not window._dashboard_page.dashboard_notice.isHidden()


def test_download_with_its_own_destination_skips_the_dialog(qtbot):
    # Roadmap item 65 (Phase 3.2) — the ONLY case that skips the dialog:
    # the playlist already has its own destination
    # (download_location_id set on the Playlist itself, loaded from the
    # DB). A resolvable configured DEFAULT alone is no longer enough to
    # skip it — see test_download_with_a_resolvable_default_still_
    # prompts_once below.
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists, resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.download_playlist_calls == ["Test"]
    # No destination needed setting — it was already the playlist's own.
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == []


def test_download_with_a_resolvable_default_still_prompts_once(
        qtbot, monkeypatch,
):
    # Roadmap item 65 (Phase 3.2) — the real, decided behavior: a
    # playlist with NO destination of its own always prompts first, even
    # when the configured default would already resolve — never a
    # silent fallback. Pre-filled with the exact real fallback (location
    # + sanitized subfolder), not just the raw playlist name.
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    dialog = opened_dialogs[0]
    assert dialog.selected_location_id() == 1
    assert dialog.subfolder_field.text() == "Test"
    # Rejected -- never silently downloaded without the user seeing it.
    assert application.download_service.download_playlist_calls == []


# --- Roadmap item 56 Phase 5.1: download button feedback -------------------

def test_download_button_shows_starting_immediately_on_click(qtbot):
    # Roadmap item 56 Phase 5.1 — the real bug: the button previously
    # gave no feedback that anything had started.
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists, resolved_destination=(location, "Test"),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    # Synchronous, main-thread state set at click time — true
    # immediately, not just eventually once some worker lands.
    assert window._dashboard_page.download_button.text() == "Starting download…"
    assert not window._dashboard_page.download_button.isEnabled()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.download_button.text()
            == "Download selected playlist"
        ),
        timeout=2000,
    )
    assert window._dashboard_page.download_button.isEnabled()


def test_download_button_resets_when_dialog_is_cancelled(qtbot, monkeypatch):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        DestinationDialog, "exec", lambda self: QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: (
            window._dashboard_page.download_button.text()
            == "Download selected playlist"
        ),
        timeout=2000,
    )
    assert window._dashboard_page.download_button.isEnabled()
    assert application.download_service.download_playlist_calls == []


def test_download_result_notice_reports_already_in_progress_tracks(qtbot):
    # Roadmap item 56 Phase 5.1 — how many downloads were requested,
    # and how many tracks were skipped because they were already in
    # flight (Phase 5.2's own real dedup guard reports through here).
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result=PlaylistDownloadResult(
            requested=2, skipped=3, total=5,
            already_in_progress=[
                "Artist A - Title A", "Artist B - Title B", "Artist C - Title C",
            ],
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden()
        and "Requested 2" in window._dashboard_page.dashboard_notice.text(),
        timeout=2000,
    )
    assert (
        "3 already downloading/downloaded"
        in window._dashboard_page.dashboard_notice.text()
    )


def test_download_result_notice_warns_and_lists_failed_tracks(qtbot):
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result=PlaylistDownloadResult(
            requested=1, total=2,
            failures=[TrackFailure("Artist A - Title A", "Search timed out.")],
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    notice = window._dashboard_page.dashboard_notice
    qtbot.waitUntil(
        lambda: not notice.isHidden() and "1 failed" in notice.text(),
        timeout=2000,
    )
    assert "Artist A - Title A: Search timed out." in notice.text()
    assert notice.property("variant") == "warning"


def test_download_result_notice_reports_needs_review_separately_from_skipped(
        qtbot,
):
    # Roadmap item 66 (Phase 4.2) — the real fix: "Requested 16, skipped
    # 12 (no candidates found)" was wrong when several of those 12 had
    # actually become real Review candidates, not "nothing found."
    playlists = [
        Playlist(
            id="p1", name="Test", track_count=1, download_location_id=1,
        ),
    ]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        resolved_destination=(location, "Test"),
        download_playlist_result=PlaylistDownloadResult(
            requested=4, skipped=6, total=10,
            already_in_progress=[],
            needs_review=[
                "Prdk - ONE MORE NIGHT", "Zigi SC, A-Cray - Bit Perfect",
            ],
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden()
        and "Requested 4" in window._dashboard_page.dashboard_notice.text(),
        timeout=2000,
    )
    text = window._dashboard_page.dashboard_notice.text()
    assert "2 sent to Review" in text
    # 6 skipped total - 0 already-in-progress - 2 needs-review = 4 with
    # genuinely no candidate at all.
    assert "4 no candidate found" in text
    assert "Review page" in text


def test_download_with_no_destination_opens_dialog_prefilled_with_playlist_name(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    dialog = opened_dialogs[0]
    # Prefilled: the only real location, and the subfolder defaults to
    # the playlist's own name.
    assert dialog.selected_location_id() == 1
    assert dialog.subfolder_field.text() == "Test"
    assert dialog.remember_checkbox.isChecked()
    # Rejected — no destination call, no download.
    assert application.download_service.set_destination_calls == []
    assert application.download_service.download_playlist_calls == []


def test_download_dialog_prefills_the_configured_default_location(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    main_location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    other_location = LibraryLocation(
        id=2, name="Other", path="/other", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(main_location, True), (other_location, True)],
        resolved_destination=None,
    )
    application._config_store = replace(
        application._config_store, default_download_location_id=2,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    opened_dialogs = []
    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(lambda: opened_dialogs != [], timeout=2000)
    assert opened_dialogs[0].selected_location_id() == 2


def test_download_dialog_confirmed_with_remember_calls_set_destination_then_downloads(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    monkeypatch.setattr(
        DestinationDialog, "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.set_destination_calls == [
        ("Test", "Main", "Test"),
    ]
    assert application.persist_default_destination_calls == []
    assert application.download_service.download_playlist_calls == ["Test"]


def test_download_dialog_confirmed_without_remember_persists_the_default(
        qtbot, monkeypatch,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    location = LibraryLocation(
        id=1, name="Main", path="/music", added_at="2026-01-01T00:00:00+00:00",
    )
    application = FakeApplication(
        playlists=playlists,
        locations=[(location, True)],
        resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    def fake_exec(self):
        self.remember_checkbox.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DestinationDialog, "exec", fake_exec)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: application.download_service.download_playlist_calls != [],
        timeout=2000,
    )
    assert application.download_service.set_destination_calls == []
    assert application.persist_default_destination_calls == [(1, True)]
    assert application.download_service.download_playlist_calls == ["Test"]


def test_download_with_no_locations_at_all_shows_a_notice_not_an_empty_dialog(
        qtbot,
):
    playlists = [Playlist(id="p1", name="Test", track_count=1)]
    application = FakeApplication(
        playlists=playlists, locations=[], resolved_destination=None,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    window._dashboard_page.download_button.click()

    qtbot.waitUntil(
        lambda: not window._dashboard_page.dashboard_notice.isHidden(), timeout=2000,
    )
    assert "location" in window._dashboard_page.dashboard_notice.text().lower()


# --- Roadmap item 56 §2.4: Dashboard double-click -> Review -----------------

def test_double_clicking_needs_review_row_navigates_to_review_and_selects_it(
        qtbot,
):
    status = make_track_status(track_id="t1", state=NEEDS_REVIEW)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
        needs_review_matches=[make_needs_review_match(track_id="t1")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 1, timeout=2000,
    )
    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["review"]
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.selectedItems() != [],
        timeout=2000,
    )
    assert window._review_page.review_local_table.currentRow() == 0


def test_double_clicking_in_library_row_is_a_no_op(qtbot):
    status = make_track_status(track_id="t1", state=IN_LIBRARY)
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=1)],
        statuses=[status],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 1, timeout=2000,
    )
    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["dashboard"]
    )


def test_double_click_after_sorting_the_track_table_navigates_to_the_right_row(
        qtbot,
):
    # Round 8 §12.2 — the track table is now sortable; a row-position
    # lookup into _current_track_statuses (this table's insertion-order
    # list) would resolve the WRONG track the moment a user sorts.
    # track_table's own row-anchor (UserRole data set in
    # _render_track_statuses) is what must be read instead.
    status_a = TrackStatus(
        track=Track(
            id="ta", title="Zzz Last", artist="Zzz Artist", album="Album",
            duration_ms=200_000,
        ),
        state=IN_LIBRARY,
    )
    status_b = TrackStatus(
        track=Track(
            id="tb", title="Aaa First", artist="Aaa Artist", album="Album",
            duration_ms=200_000,
        ),
        state=NEEDS_REVIEW,
    )
    application = FakeApplication(
        playlists=[Playlist(id="p1", name="Test", track_count=2)],
        statuses=[status_a, status_b],
        needs_review_matches=[make_needs_review_match(track_id="tb")],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _select_first_playlist(window, qtbot)

    qtbot.waitUntil(
        lambda: window._dashboard_page.track_table.rowCount() == 2, timeout=2000,
    )
    # Sort ascending by the Track column — "Aaa Artist..." (status_b,
    # inserted second) now sits at row 0.
    window._dashboard_page.track_table.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert (
        window._dashboard_page.track_table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        == "tb"
    )

    window._dashboard_page._on_track_table_cell_double_clicked(0, 1)

    assert (
        window.stacked_widget.currentIndex()
        == window._page_indices["review"]
    )
    qtbot.waitUntil(
        lambda: window._review_page.review_local_table.rowCount() == 1, timeout=2000,
    )


# --- Re-render cost on the 2-second poll (HISTORY §166) ---------------------


_PROBE_ROLE = Qt.ItemDataRole.UserRole + 1


def _downloading(bytes_transferred: int, total_bytes: int = 1_000):
    return TrackStatus(
        track=make_track("t1"), state=DOWNLOADING,
        bytes_transferred=bytes_transferred, total_bytes=total_bytes,
    )


def test_an_unchanged_poll_leaves_the_rows_alone(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    page._render_track_statuses(
        [make_track_status(track_id="t1", state=IN_LIBRARY)],
    )
    page.track_table.item(0, 0).setData(_PROBE_ROLE, "first render")

    page._render_track_statuses(
        [make_track_status(track_id="t1", state=IN_LIBRARY)],
    )

    assert page.track_table.item(0, 0).data(_PROBE_ROLE) == "first render"


def test_a_progress_only_poll_updates_the_bar_in_place(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    page._render_track_statuses([_downloading(500)])
    page.track_table.item(0, 0).setData(_PROBE_ROLE, "first render")

    page._render_track_statuses([_downloading(750, total_bytes=1_500)])

    assert page.track_table.item(0, 0).data(_PROBE_ROLE) == "first render"
    bar = page.track_table.cellWidget(0, 2).findChild(QProgressBar)
    assert (bar.value(), bar.maximum()) == (750, 1_500)
    assert page.track_table.item(0, 2).sort_key == 0.5


def test_a_state_change_rebuilds_the_row(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    page._render_track_statuses([_downloading(500)])

    page._render_track_statuses(
        [make_track_status(track_id="t1", state=IN_LIBRARY)],
    )

    assert page.track_table.item(0, 1).text() == "In library"
    assert page.track_table.cellWidget(0, 2) is None
    assert page.track_table.cellWidget(0, 3).findChildren(QPushButton)


def _lamp_image(icon):
    return icon.pixmap(status_lamp.LAMP_SIZE).toImage()


@pytest.mark.parametrize("state", list(status_lamp.TRACK_LAMPS))
def test_each_status_shows_its_lamp_beside_its_label(qtbot, state):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page

    page._render_track_statuses(
        [make_track_status(track_id="t1", state=state)],
    )

    item = page.track_table.item(0, 1)
    expected = status_lamp.lamp_icon(
        status_lamp.TRACK_LAMPS[state], theme.active_palette(),
    )
    assert _lamp_image(item.icon()) == _lamp_image(expected)
    assert item.text()


def test_a_review_status_is_a_lamp_not_a_link(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page

    page._render_track_statuses(
        [make_track_status(track_id="t1", state=NEEDS_REVIEW)],
    )

    item = page.track_table.item(0, 1)
    assert item.font().underline() is False
    assert item.foreground().style() == Qt.BrushStyle.NoBrush
    assert item.toolTip() != ""


def test_a_found_candidate_is_quieter_text_beside_needs_review(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    status = replace(
        make_track_status(track_id="t1", state=NEEDS_REVIEW),
        soulseek_candidate=object(),
    )

    page._render_track_statuses([status])

    item = page.track_table.item(0, 1)
    assert item.text() == "Needs review"
    assert item.data(SECONDARY_ROLE) == "SoulSeek candidate found"


def test_a_download_shows_its_percentage_beside_the_lamp(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    page._render_track_statuses([_downloading(500)])
    page.track_table.item(0, 0).setData(_PROBE_ROLE, "first render")

    assert page.track_table.item(0, 1).data(SECONDARY_ROLE) == "50%"
    # The status label wins the cell; the percentage gives way.
    assert page.track_table.itemDelegate().secondary_min_share == 0

    page._render_track_statuses([_downloading(750)])

    assert page.track_table.item(0, 0).data(_PROBE_ROLE) == "first render"
    assert page.track_table.item(0, 1).data(SECONDARY_ROLE) == "75%"


def test_a_theme_change_repaints_the_lamps(qtbot, monkeypatch):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    statuses = [make_track_status(track_id="t1", state=NOT_FOUND)]
    page._render_track_statuses(statuses)
    repainted = replace(theme.DARK, DANGER="#123456")
    monkeypatch.setattr(theme, "active_palette", lambda: repainted)

    page._render_track_statuses(statuses)

    expected = status_lamp.lamp_icon(status_lamp.FAULT, repainted)
    assert _lamp_image(page.track_table.item(0, 1).icon()) == (
        _lamp_image(expected)
    )


def test_a_row_with_nothing_to_show_has_no_cell_widgets(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page

    page._render_track_statuses(
        [make_track_status(track_id="t1", state=NOT_FOUND)],
    )

    assert page.track_table.cellWidget(0, 2) is None
    assert page.track_table.cellWidget(0, 3) is None


def test_a_progress_only_poll_re_sorts_a_table_sorted_by_progress(qtbot):
    def downloading(track_id: str, bytes_transferred: int) -> TrackStatus:
        return TrackStatus(
            track=make_track(track_id), state=DOWNLOADING,
            bytes_transferred=bytes_transferred, total_bytes=1_000,
        )

    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._dashboard_page
    page._render_track_statuses([downloading("a", 100), downloading("b", 900)])
    page.track_table.sortItems(2, Qt.SortOrder.AscendingOrder)

    page._render_track_statuses([downloading("a", 950), downloading("b", 900)])

    assert [
        page.track_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(2)
    ] == ["b", "a"]

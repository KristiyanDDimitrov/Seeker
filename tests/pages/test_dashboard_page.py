"""Tests for the Dashboard page (seeker.ui.pages.dashboard_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.4) — the
mirror of §9.3.1's own Dashboard extraction (S8).

Round 8 §12.6 split TaggingPanel out to its own page (library_page.py);
tests that drive it — even the ones that also need Dashboard's own
track_table/playlist_list to set up a selection — moved to
test_library_page.py accordingly. What's left here is genuinely
Dashboard-only: the track table's own rendering (including the Tag
button/muted label a row shows, which TaggingPanel's own click handler
now reads via DashboardHost) and dashboard_notice's own poll-survival
behavior.

Tests that exercise MainWindow's own not-yet-extracted orchestration
(the sync/scan/match/download click handlers, _open_destination_dialog,
the Review-tab-navigates-here-and-selects-a-row assertions) stay in
test_ui_smoke.py as cross-cutting, even though several of them use
Dashboard's buttons as their trigger or dashboard_notice/status_label
as their assertion target — same precedent as the activity-strip and
structural-sweep tests that also stayed.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton

from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    REVIEW_CANDIDATE,
    TrackStatus,
)
from seeker.ui import theme
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication, _make_track, _make_track_status


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
    assert window._dashboard_page.scan_button.text() == "Rescan and match library"


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
        track_statuses=[_make_track_status(state=NOT_FOUND)],
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
    assert window._dashboard_page.scan_button.text() == "Rescan and match library"
    assert window._dashboard_page.match_button.text() == "Re-match library"
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

    qtbot.wait(50)
    assert window._dashboard_page.next_step_notice.isHidden()


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
        statuses=[TrackStatus(track=_make_track("t1"), state=NOT_FOUND)],
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

    qtbot.wait(50)
    assert not window._dashboard_page.download_button.isEnabled()


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
        statuses=[TrackStatus(track=_make_track("t1"), state=NOT_FOUND)],
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
        track=_make_track("t1"), state=DOWNLOADING,
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
        _make_track_status(track_id="t1", state=IN_LIBRARY),
        _make_track_status(track_id="t2", state=NOT_FOUND),
    ]
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(statuses)

    in_library_actions = window._dashboard_page.track_table.cellWidget(0, 3)
    assert [
            b.text() for b in in_library_actions.findChildren(QPushButton)
    ] == ["Tag"]

    not_found_actions = window._dashboard_page.track_table.cellWidget(1, 3)
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

    window._dashboard_page._render_track_statuses(statuses)

    actions = window._dashboard_page.track_table.cellWidget(0, 3)
    assert actions.findChildren(QPushButton) == []
    labels = actions.findChildren(QLabel)
    assert [label.text() for label in labels] == ["Tagged"]
    assert "2026" in labels[0].toolTip()


def test_context_menu_offers_nothing_for_an_untagged_or_missing_row(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None),
        _make_track_status(track_id="t2", state=NOT_FOUND),
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

    window._dashboard_page.dashboard_notice.show_message(
            "Something worth reading",
            kind="error",
    )
    assert not window._dashboard_page.dashboard_notice.isHidden()

    window._dashboard_page._poll_selected_playlist()
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
        track=_make_track("t1"), state=DOWNLOADING,
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


# --- Track status filter (round 8 §12.8) ------------------------------------


def _visible_track_ids(window) -> set[str]:
    # Reads each row's own UserRole anchor (see _render_track_statuses),
    # not the displayed label — every track in these tests shares the
    # same "Artist - Title" text (test_ui_smoke.py's _make_track), so
    # only the id actually distinguishes rows.
    table = window._dashboard_page.track_table
    return {
        table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for row in range(table.rowCount())
    }


def test_track_filter_defaults_to_all_and_shows_every_status(qtbot):
    statuses = [
        _make_track_status(track_id="t1", state=IN_LIBRARY),
        _make_track_status(track_id="t2", state=NOT_FOUND),
        _make_track_status(track_id="t3", state=NEEDS_REVIEW),
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
        _make_track_status(track_id="t1", state=IN_LIBRARY),
        _make_track_status(track_id="t2", state=NOT_FOUND),
        _make_track_status(track_id="t3", state=REVIEW_CANDIDATE),
        _make_track_status(track_id="t4", state=NEEDS_REVIEW),
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
        _make_track_status(track_id="t1", state=NEEDS_REVIEW),
        _make_track_status(track_id="t2", state=AWAITING_REVIEW),
        _make_track_status(track_id="t3", state=NOT_FOUND),
        _make_track_status(track_id="t4", state=IN_LIBRARY),
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
        _make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None),
        _make_track_status(
            track_id="t2", state=IN_LIBRARY,
            tagged_at="2026-08-30T12:00:00+00:00",
        ),
        _make_track_status(track_id="t3", state=NOT_FOUND),
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
    statuses = [_make_track_status(track_id="t1", state=IN_LIBRARY)]
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


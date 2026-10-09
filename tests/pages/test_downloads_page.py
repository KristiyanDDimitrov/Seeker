"""Tests for the Downloads page (seeker.ui.pages.downloads_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.3) — the
mirror of §9.3.1's own Downloads extraction (S7).
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton

from fakes import (
    FakeApplication,
    force_tray_available,
    make_active_download,
    make_track,
)
from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.download_result import CancelOutcome, TrackSearchOutcome
from seeker.models.track import Track
from seeker.ui import help_text, theme
from seeker.ui.elided_text import BADGE_ROLE, SECONDARY_ROLE
from seeker.ui.main_window import MainWindow


def test_downloads_tab_renders_rows_across_playlists(qtbot):
    downloads = [
        make_active_download(track_id="t1", playlist_name="Playlist A"),
        make_active_download(
            track_id="t2", status="locked", role="upgrade",
            bytes_transferred=None, total_bytes=None,
            playlist_name="Playlist B",
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads(downloads)

    table = window._downloads_page.downloads_table
    assert table.rowCount() == 2
    assert table.item(0, 1).text() == "Playlist A"
    assert table.item(1, 1).text() == "Playlist B"
    # A raw "locked" status reads as the Dashboard's "Retrying", with
    # why beside it, not the raw state string.
    assert table.item(1, 2).text() == "Retrying"
    assert table.item(1, 2).data(SECONDARY_ROLE) == "File locked by the peer"


# --- Downloads aggregate remaining-time header (Task 9) --------------------

def test_downloads_aggregate_header_blank_with_no_active_downloads(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    eta_label = window._downloads_page.downloads_eta_label
    # The label starts blank, so it must show something first for blank
    # to prove the clear.
    window._downloads_page._render_active_downloads([
        make_active_download(status="queued", bytes_transferred=None),
    ])
    assert eta_label.text() != ""
    assert eta_label.toolTip() != ""

    window._downloads_page._render_active_downloads([])

    assert eta_label.text() == ""
    assert eta_label.toolTip() == ""


def test_downloads_aggregate_header_shows_estimate_once_a_download_has_samples(
        qtbot
):
    download = ActiveDownload(
        request=DownloadRequest(
            id=1, track_id="t1", username="peer1", filename="file.flac",
            format="flac", status="downloading",
            requested_at="2026-01-01T00:00:00+00:00",
            bytes_transferred=500, total_bytes=1_000,
        ),
        track=Track(
            id="t1", title="Title", artist="Artist", album="Album",
            duration_ms=200_000,
        ),
        playlist_name="Playlist A",
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # aggregate() reads from _eta_tracker's own recorded samples, not
    # from the ActiveDownload snapshot itself — feed it two directly,
    # the same way _record_eta_samples does on a real 20s backend poll.
    window._downloads_page._eta_tracker.record(
            1,
            200,
            datetime(2026, 1, 1, tzinfo=UTC),
    )
    window._downloads_page._eta_tracker.record(
            1,
            500,
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )

    window._downloads_page._render_active_downloads([download])

    assert "remaining" in window._downloads_page.downloads_eta_label.text()
    assert "1 transferring" in window._downloads_page.downloads_eta_label.text()
    assert window._downloads_page.downloads_eta_label.toolTip() != ""


def test_downloads_aggregate_header_reports_waiting_with_no_samples(qtbot):
    download = make_active_download(
        status="queued", bytes_transferred=None, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    assert window._downloads_page.downloads_eta_label.text() == (
        "Waiting for transfers to start · 0 transferring · "
        "1 queued (no estimate)"
    )


def test_a_queued_row_has_no_bar(qtbot):
    # It waits in the peer's queue: no transfer, so nothing to animate.
    # Its lit amber lamp already says the wait is on the network.
    download = make_active_download(
        status="queued", bytes_transferred=None, total_bytes=None,
    )
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    table = window._downloads_page.downloads_table
    assert table.item(0, 2).text() == "Queued"
    assert table.cellWidget(0, 3).findChild(QProgressBar) is None


def test_downloads_tab_progress_bar_indeterminate_with_no_bytes_yet(qtbot):
    download = make_active_download(
        status="downloading", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    # Roadmap item 96 (B4) — wrapped in the same QHBoxLayout container
    # shape as every other exit of _build_progress_widget, not returned
    # bare: a bare bar
    # returned directly from setCellWidget gets resized to the FULL
    # cell rect by Qt, and the global QProgressBar max-height: 14px
    # rule then clamps it to the TOP of a tall row instead of centering
    # it (the real reported bug — a queued row's bar visibly sat above
    # center while a downloading row's own bar, already wrapped, sat
    # centered).
    container = window._downloads_page.downloads_table.cellWidget(0, 3)
    assert not isinstance(container, QProgressBar)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.minimum() == 0
    assert bar.maximum() == 0
    # No ETA label for an indeterminate bar — nothing determinate to
    # estimate against (Task 2's own scoping, unchanged by the B4 fix).
    assert container.findChildren(QLabel) == []
    # Real, live-found bug (Phase 3): ANY QProgressBar::chunk QSS rule
    # matching a bar, even one applied only to determinate bars
    # elsewhere, replaces Qt's native animated "busy" indeterminate
    # indicator with a static solid block that reads as "stuck at
    # 100%." The accent chunk fill must never be applied to an
    # indeterminate bar — asserting no local stylesheet override here
    # is what would catch a regression that started calling
    # theme.style_meter() unconditionally.
    assert bar.styleSheet() == ""
    # Busy in the working amber, not the accent.
    assert bar.palette().highlight().color().name().upper() == (
        theme.active_palette().CUE.upper()
    )


def test_downloads_tab_progress_bar_determinate_with_real_bytes(qtbot):
    # A determinate bar is wrapped in a container alongside the ETA
    # label (Task 2) — the bar itself is a child widget, not the cell
    # widget directly (the indeterminate/queued case above is now
    # wrapped the identical way, roadmap item 96).
    download = make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    container = window._downloads_page.downloads_table.cellWidget(0, 3)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.maximum() == 1_000
    assert bar.value() == 500
    # The accent chunk fill IS a per-instance stylesheet override, not
    # a global QSS rule (see theme.py's own QProgressBar::chunk
    # comment) — a determinate bar must actually receive it.
    assert "chunk" in bar.styleSheet()


def test_downloads_tab_busy_and_determinate_bars_are_both_vertically_centered(
        qtbot,
):
    # Roadmap item 96 (B4.3) — real pixel verification of the reported
    # bug: a queued row's bar used to sit clamped to the TOP of its
    # cell (a bare bar returned from setCellWidget gets resized to the
    # full, tall cell rect, then the global 14px max-height rule clamps
    # it upward) while a downloading row's own bar, already wrapped in
    # a container, sat centered. Both must now match.
    downloads = [
        make_active_download(
            track_id="t1", status="downloading",
            bytes_transferred=None, total_bytes=None,
        ),
        make_active_download(
            track_id="t2", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("downloads")

    window._downloads_page._render_active_downloads(downloads)
    qtbot.wait(20)

    viewport = window._downloads_page.downloads_table.viewport()

    for row in (0, 1):
        row_rect = window._downloads_page.downloads_table.visualRect(
            window._downloads_page.downloads_table.model().index(row, 3)
        )
        widget = window._downloads_page.downloads_table.cellWidget(row, 3)
        assert widget is not None
        bar = widget.findChild(QProgressBar)
        assert bar is not None

        bar_center_y = bar.mapTo(
            viewport, bar.rect().center()
        ).y()

        assert abs(bar_center_y - row_rect.center().y()) <= 2

    # Roadmap item 102 — a post-round review correctly pointed out that
    # a geometry check (mapTo above) isn't the same thing as verifying
    # what actually got PAINTED (item 77's own lesson: occlusion/paint
    # order is invisible to geometry queries). Real pixel scan of a
    # real window.grab(): find the bar's actual colored pixel span
    # inside the progress column and compare ITS midpoint to the row's
    # own real center — independent of and stronger than the mapTo
    # check above.
    image = window.grab().toImage()
    surface_rgb = tuple(
        int(theme.active_palette().BG_SURFACE[i:i + 2], 16) for i in (1, 3, 5)
    )
    top_left = viewport.mapTo(window, viewport.rect().topLeft())
    # window.grab() returns a QImage in DEVICE pixels; every geometry
    # query above (visualRect/mapTo) is in LOGICAL pixels. Discovered
    # live adding item C1's own test: this real Qt session's
    # devicePixelRatio is 2.0, silently sampling the wrong quadrant of
    # the image before this fix — this test happened to still pass
    # only because it compared two equally-mis-scaled quantities
    # against a 2px tolerance, not because the coordinates were right.
    dpr = image.width() / window.width()

    for row in (0, 1):
        row_rect = window._downloads_page.downloads_table.visualRect(
            window._downloads_page.downloads_table.model().index(row, 3)
        )
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
        assert painted_ys, f"row {row}: no painted bar pixels found"

        painted_center = (painted_ys[0] + painted_ys[-1]) / 2 / dpr
        row_center = top_left.y() + row_rect.center().y()
        assert abs(painted_center - row_center) <= 2


def test_downloads_header_shows_a_real_divider_between_columns(qtbot):
    # Roadmap item C1 (round 5) — a real window.grab() bisect found that
    # `QHeaderView::section:horizontal:last-child` (invalid Qt QSS —
    # `last-child` is CSS, not a real Qt pseudo-state) poisoned the
    # WHOLE `QHeaderView::section` rule, silently dropping
    # `border-right` everywhere despite the CSS text reading correctly
    # — the exact "asserts a property, never looked at a pixel" failure
    # mode the round-5 brief called out by name (this was "fixed" and
    # reported green twice before, per B2/item 97). A test that greps
    # the stylesheet string can't catch this class of bug at all — it
    # must sample real painted pixels.
    downloads = [
        make_active_download(
            track_id="t1", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("downloads")
    window._downloads_page._render_active_downloads(downloads)
    qtbot.wait(100)

    table = window._downloads_page.downloads_table
    header = table.horizontalHeader()
    image = window.grab().toImage()
    header_top_left = header.mapTo(window, header.rect().topLeft())
    header_h = header.height()
    # window.grab() returns a QImage sized in DEVICE pixels, while every
    # Qt geometry query above (mapTo/sectionPosition/etc.) is in LOGICAL
    # pixels — on this machine's real Qt session (devicePixelRatio 2.0,
    # discovered live; a bare ad hoc QApplication used while diagnosing
    # this reported 1.0) sampling logical coordinates directly into the
    # device-pixel image silently reads the wrong quadrant. Scale by the
    # image's own real ratio rather than assuming any particular value.
    dpr = image.width() / window.width()

    border_strong_rgb = tuple(
        int(theme.active_palette().BORDER_STRONG[i:i + 2], 16) for i in (1, 3, 5)
    )
    ncols = table.columnCount()

    for col in range(ncols):
        section_end = header.sectionPosition(col) + header.sectionSize(col)
        base_x = round((header_top_left.x() + section_end) * dpr)
        y0 = round(header_top_left.y() * dpr)
        y1 = round((header_top_left.y() + header_h - 1) * dpr)
        dx_span = max(2, round(2 * dpr))
        divider_present = any(
            (
                image.pixelColor(x, y).red(),
                image.pixelColor(x, y).green(),
                image.pixelColor(x, y).blue(),
            ) == border_strong_rgb
            for x in range(base_x - dx_span, base_x + dx_span + 1)
            if 0 <= x < image.width()
            # exclude the header's own bottom border row, which is
            # unrelated to the per-column right-divider under test
            for y in range(y0, y1)
        )
        if col == ncols - 1:
            # the trailing section's divider is deliberately suppressed
            # — nothing to separate it from on that side
            assert not divider_present, f"col {col} (last) should have no divider"
        else:
            assert divider_present, f"col {col} is missing its real divider"


def test_downloads_tab_locked_row_has_no_progress_bar(qtbot):
    # Locked/shortlisted rows have no real, current transfer — a
    # progress claim there would be misleading.
    download = make_active_download(
        status="locked", role="upgrade",
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    bar = window._downloads_page.downloads_table.cellWidget(0, 3)
    assert not isinstance(bar, QProgressBar)


# --- Roadmap item 56 Phase 5.4: a finished download must not read as
# "Stalled" ------------------------------------------------------------

def test_a_just_completed_download_never_consults_the_eta_tracker(qtbot):
    # The real bug, reproduced directly: sample a completed row 3 times
    # with identical bytes (exactly what the 20s backend-poll loop used
    # to do for a recently-finished row still inside
    # RECENTLY_FINISHED_WINDOW_SECONDS) — old behavior would eventually
    # report "Stalled" once _is_stalled's 3-identical-sample threshold
    # was reached; the real fix is that a terminal row's status is
    # never even routed to describe()/the tracker at all.
    download = make_active_download(
        status="completed", bytes_transferred=1_000, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(3):
        window._downloads_page._eta_tracker.record(
            1, 1_000, now + timedelta(seconds=i * 20),
        )

    window._downloads_page._render_active_downloads([download])

    container = window._downloads_page.downloads_table.cellWidget(0, 3)
    label_texts = [
        child.text() for child in container.findChildren(QLabel)
    ]
    assert "Stalled" not in label_texts
    assert window._downloads_page.downloads_table.item(0, 2).text() == (
        "Completed"
    )
    # Evicted immediately, not left for the row to eventually drop out
    # of get_active_downloads() on its own.
    assert 1 not in window._downloads_page._eta_tracker._history


def test_a_finished_row_shows_its_lamp_and_no_bar(qtbot):
    # The lamp says it is done; a full bar beside it said it twice.
    for status, label in (
            ("completed", "Completed"),
            ("ready_for_review", "Ready for review"),
    ):
        download = make_active_download(
            status=status, role="upgrade",
            bytes_transferred=1_000, total_bytes=1_000,
        )
        window = MainWindow(FakeApplication())
        qtbot.addWidget(window)

        window._downloads_page._render_active_downloads([download])

        table = window._downloads_page.downloads_table
        assert table.item(0, 2).text() == label
        assert not table.item(0, 2).icon().isNull()
        assert table.cellWidget(0, 3).findChild(QProgressBar) is None
        # Still sorts as done, above any transfer in progress.
        assert table.item(0, 3).sort_key == 1.0


def test_a_transfer_shows_its_percentage_beside_its_status(qtbot):
    download = make_active_download(
        status="downloading", bytes_transferred=650, total_bytes=1_000,
    )
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    item = window._downloads_page.downloads_table.item(0, 2)
    assert item.text() == "Downloading"
    assert item.data(SECONDARY_ROLE) == "65%"
    assert item.data(Qt.ItemDataRole.AccessibleTextRole) == (
        "Downloading: 65%"
    )


def test_terminal_progress_widget_for_failed_is_blank_not_a_bar(qtbot):
    download = make_active_download(
        status="failed", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    widget = window._downloads_page.downloads_table.cellWidget(0, 3)
    assert not isinstance(widget, QProgressBar)
    assert widget.findChild(QProgressBar) is None


def test_aggregate_header_excludes_terminal_rows_from_queued_count(qtbot):
    # Roadmap item 56 Phase 5.4 §4 — a completed row was previously
    # folded into the "queued (no estimate)" figure.
    completed = make_active_download(
        track_id="t1", status="completed",
        bytes_transferred=1_000, total_bytes=1_000,
    )
    completed.request.id = 1
    queued = make_active_download(
        track_id="t2", status="queued",
        bytes_transferred=None, total_bytes=1_000,
    )
    queued.request.id = 2
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([completed, queued])

    assert window._downloads_page.downloads_eta_label.text() == (
        "Waiting for transfers to start · 0 transferring · "
        "1 queued (no estimate)"
    )


def test_downloads_tab_eta_shows_calculating_before_second_sample(qtbot):
    download = make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    container = window._downloads_page.downloads_table.cellWidget(0, 3)
    label = container.findChild(QLabel)
    assert label.text() == "Calculating…"


def test_downloads_tab_eta_shows_estimate_after_two_samples(qtbot):
    download = make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(UTC)
    # 400 bytes/second over the last interval, 400 bytes remaining ->
    # a clean 1s ETA, easy to assert on exactly.
    window._downloads_page._eta_tracker.record(1, 200, now - timedelta(seconds=1))
    window._downloads_page._eta_tracker.record(1, 600, now)

    window._downloads_page._render_active_downloads([download])

    container = window._downloads_page.downloads_table.cellWidget(0, 3)
    label = container.findChild(QLabel)
    assert label.text() == "1s"


def test_downloads_tab_eta_shows_stalled_after_flat_samples(qtbot):
    download = make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(UTC)
    for offset in (2, 1, 0):
        window._downloads_page._eta_tracker.record(
            1, 600, now - timedelta(seconds=offset),
        )

    window._downloads_page._render_active_downloads([download])

    container = window._downloads_page.downloads_table.cellWidget(0, 3)
    label = container.findChild(QLabel)
    assert label.text() == "Stalled"


def test_record_eta_samples_evicts_ids_no_longer_active(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(UTC)
    window._downloads_page._eta_tracker.record(1, 100, now)
    window._downloads_page._eta_tracker.record(1, 200, now)

    # request id 1 has since disappeared from get_active_downloads() —
    # completed, failed, or superseded — so a fresh sampling pass with
    # no row for it must drop its history rather than keep it forever
    # (Task 2's own explicit leak-prevention requirement).
    window._downloads_page._record_eta_samples([])

    assert window._downloads_page._eta_tracker.describe(1, 1_000) == "Calculating…"


def test_trigger_backend_poll_samples_eta_after_poll_succeeds(qtbot):
    download = make_active_download(bytes_transferred=500, total_bytes=1_000)
    download.request.id = 7

    application = FakeApplication(
        soulseek_configured=True, active_downloads=[download],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    qtbot.waitUntil(
        lambda: 7 in window._downloads_page._eta_tracker._history, timeout=2000,
    )


def test_downloads_paged_render_skips_table_population_while_hidden(
        qtbot, monkeypatch,
):
    # Roadmap item R7.6.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._lifecycle._hidden_to_tray = True

    downloads = [
        ActiveDownload(
            track=make_track("t1"),
            request=DownloadRequest(
                track_id="t1", username="peer1", filename="a.flac",
                format="flac", quality_descriptor="flac", role="settled",
                status="downloading", requested_at="2026-01-01",
            ),
            playlist_name="Test",
        ),
    ]
    window._downloads_page._render_active_downloads(downloads)

    # The count used by the tray IS still updated...
    assert window._downloads_page.active_downloads_count == 1
    # ...but the actual table was never touched.
    assert window._downloads_page.downloads_table.rowCount() == 0


# --- Failures stay visible ---------------------------------------------------

def test_a_failed_row_shows_its_reason_with_the_full_text_in_a_tooltip(
        qtbot,
):
    download = make_active_download(
        status="failed", bytes_transferred=None, total_bytes=None,
    )
    download.request.failure_reason = "Peer rejected: too many requests"
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    item = window._downloads_page.downloads_table.item(0, 2)
    assert item.text() == "Failed"
    assert item.data(SECONDARY_ROLE) == "Peer rejected: too many requests"
    tooltip = QTextDocument()
    tooltip.setHtml(item.toolTip())
    assert tooltip.toPlainText() == "Failed — Peer rejected: too many requests"


def test_a_failure_reason_with_markup_renders_literally_in_the_tooltip(
        qtbot,
):
    reason = 'Peer said <a href="https://evil.example">update</a>'
    download = make_active_download(
        status="failed", bytes_transferred=None, total_bytes=None,
    )
    download.request.failure_reason = reason
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    tooltip = QTextDocument()
    tooltip.setHtml(window._downloads_page.downloads_table.item(0, 2).toolTip())
    assert tooltip.toPlainText() == f"Failed — {reason}"


def test_an_unavailable_row_shows_its_reason(qtbot):
    download = make_active_download(
        status="unavailable", bytes_transferred=None, total_bytes=None,
    )
    download.request.failure_reason = "Peer kept refusing after 8 attempts"
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    item = window._downloads_page.downloads_table.item(0, 2)
    assert item.text() == "Unavailable"
    assert item.data(SECONDARY_ROLE) == "Peer kept refusing after 8 attempts"


def test_a_failure_from_before_reasons_were_stored_shows_the_plain_label(
        qtbot,
):
    download = make_active_download(
        status="failed", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    item = window._downloads_page.downloads_table.item(0, 2)
    assert item.text() == "Failed"
    assert item.data(SECONDARY_ROLE) is None


def test_clear_finished_is_disabled_with_nothing_finished(qtbot):
    downloads = [make_active_download(status="downloading")]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads(downloads)

    assert not window._downloads_page.clear_finished_button.isEnabled()


def test_clear_finished_dismisses_finished_rows_and_refreshes(qtbot):
    downloads = [
        make_active_download(track_id="t1", status="downloading"),
        make_active_download(
            track_id="t2", status="failed",
            bytes_transferred=None, total_bytes=None,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads(list(downloads))
    assert page.clear_finished_button.isEnabled()

    page.clear_finished_button.click()

    dashboard_service = application.dashboard_service
    qtbot.waitUntil(
        lambda: page.downloads_table.rowCount() == 1, timeout=2000,
    )
    assert dashboard_service.clear_finished_calls == 1
    assert page.downloads_table.item(0, 2).text() == "Downloading"
    assert not page.clear_finished_button.isEnabled()


def test_page_copy_says_failures_stay_until_cleared():
    assert "Clear finished" in help_text.DOWNLOADS_TAB_SUBTITLE
    assert "see the Downloads page" not in help_text.HISTORY_PAGE_SUBTITLE
    assert "Clear finished" in help_text.HISTORY_PAGE_SUBTITLE


def test_clear_finished_finishing_never_re_enables_over_a_newer_render(
        qtbot,
):
    # The display tick can render the cleared list before the clear's
    # own completion is handled. Rendering here, synchronously after
    # the click, always lands first: the worker's finished signal is
    # queued until control returns to the event loop.
    finished = make_active_download(
        track_id="t1", status="failed",
        bytes_transferred=None, total_bytes=None,
    )
    active = make_active_download(track_id="t2", status="downloading")
    application = FakeApplication(active_downloads=[finished, active])
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([finished, active])
    refreshes: list[int] = []
    page.poll_active_downloads = lambda: refreshes.append(1)

    page.clear_finished_button.click()
    page._render_active_downloads([active])
    qtbot.waitUntil(lambda: refreshes == [1], timeout=2000)

    assert not page.clear_finished_button.isEnabled()


def test_an_empty_downloads_page_points_at_the_dashboard(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    window._show_page("downloads")
    page = window._downloads_page

    assert page.downloads_empty.text() == help_text.DOWNLOADS_EMPTY
    assert page.downloads_empty.isVisibleTo(page)

    page.downloads_empty_action.click()

    assert window._current_page_key == "dashboard"


def test_downloads_marks_an_upgrade_with_a_badge_not_a_column(qtbot):
    downloads = [
        make_active_download(track_id="t1", role="settled"),
        make_active_download(track_id="t2", role="upgrade"),
    ]
    window = MainWindow(FakeApplication(active_downloads=downloads))
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads(downloads)

    table = window._downloads_page.downloads_table
    headers = [
        table.horizontalHeaderItem(column).text()
        for column in range(table.columnCount())
    ]
    assert headers == ["Track", "Playlist", "Status", "Progress", "Actions"]
    assert table.item(0, 0).data(BADGE_ROLE) is None
    assert table.item(1, 0).data(BADGE_ROLE) == help_text.UPGRADE_BADGE_TEXT
    assert table.item(1, 0).data(Qt.ItemDataRole.AccessibleTextRole) == (
        f"Upgrade: {table.item(1, 0).text()}"
    )


def test_an_unavailable_download_says_it_stopped_retrying(qtbot):
    download = make_active_download(status="unavailable")
    window = MainWindow(FakeApplication(active_downloads=[download]))
    qtbot.addWidget(window)

    window._downloads_page._render_active_downloads([download])

    item = window._downloads_page.downloads_table.item(0, 2)
    assert item.text() == "Unavailable"
    assert item.data(SECONDARY_ROLE) == "Stopped retrying"


def test_status_sorts_closest_to_done_first(qtbot):
    # Listed alphabetically by label, the order a text sort would keep.
    downloads = [
        make_active_download(track_id=status, status=status)
        for status in (
            "completed", "downloading", "failed", "queued", "shortlisted",
            "ready_for_review", "locked", "unavailable",
        )
    ]
    window = MainWindow(FakeApplication(active_downloads=downloads))
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads(downloads)

    page.downloads_table.sortItems(2, Qt.SortOrder.AscendingOrder)

    assert [
        page.downloads_table.item(row, 2).text()
        for row in range(page.downloads_table.rowCount())
    ] == [
        "Completed", "Downloading", "Queued", "Retrying", "Queued as backup",
        "Ready for review", "Failed", "Unavailable",
    ]


def test_a_progress_only_tick_keeps_every_rows_widgets(qtbot):
    # A rebuild under the pointer kills a cell widget's shown tooltip
    # and a click pressed across it, so a tick that moves only bytes
    # updates the row in place (ui/CLAUDE.md, HISTORY §195).
    downloads = [
        make_active_download(track_id="t1", bytes_transferred=100),
        make_active_download(track_id="t2", status="queued"),
    ]
    window = MainWindow(FakeApplication(active_downloads=downloads))
    qtbot.addWidget(window)
    page = window._downloads_page
    table = page.downloads_table
    page._render_active_downloads(downloads)
    table.sortItems(0, Qt.SortOrder.DescendingOrder)
    before = [table.cellWidget(row, 3) for row in range(table.rowCount())]

    page._render_active_downloads([
        make_active_download(track_id="t1", bytes_transferred=750),
        make_active_download(track_id="t2", status="queued"),
    ])

    assert [
        table.cellWidget(row, 3) for row in range(table.rowCount())
    ] == before
    row = next(
        row for row in range(table.rowCount())
        if table.item(row, 2).text() == "Downloading"
    )
    assert table.cellWidget(row, 3).findChild(QProgressBar).value() == 750
    assert table.item(row, 2).data(SECONDARY_ROLE) == "75%"
    assert table.item(row, 3).sort_key == 0.75


def test_a_status_change_rebuilds_the_row(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([make_active_download(status="queued")])

    page._render_active_downloads([make_active_download(status="downloading")])

    assert page.downloads_table.item(0, 2).text() == "Downloading"
    assert page.downloads_table.cellWidget(0, 3).findChild(QProgressBar)


# --- Retry ------------------------------------------------------------------

def _row_button(page, row: int, text: str) -> QPushButton | None:
    container = page.downloads_table.cellWidget(row, 4)
    if container is None:
        return None
    return next(
        (
            button for button in container.findChildren(QPushButton)
            if button.text() == text
        ),
        None,
    )


def test_only_a_failed_or_unavailable_row_offers_retry(qtbot):
    downloads = [
        make_active_download(track_id=status, status=status, request_id=row)
        for row, status in enumerate((
            "failed", "unavailable", "downloading", "completed", "locked",
        ))
    ]
    window = MainWindow(FakeApplication(active_downloads=downloads))
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads(downloads)

    offered = [
        _row_button(page, row, "Retry") is not None for row in range(5)
    ]

    assert offered == [True, True, False, False, False]
    button = _row_button(page, 0, "Retry")
    assert button.accessibleName() == "Retry Artist - Title"
    assert button.toolTip() == help_text.TOOLTIP_RETRY_DOWNLOAD


def test_retry_searches_again_and_reports_what_it_found(qtbot):
    failed = make_active_download(
        status="failed", request_id=7, failure_reason="Peer offline",
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication(active_downloads=[failed])
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([failed])

    _row_button(page, 0, "Retry").click()

    qtbot.waitUntil(
        lambda: page.notice.text()
        == help_text.retry_outcome_text(
            TrackSearchOutcome.REQUESTED, "Artist - Title",
        ),
        timeout=2000,
    )
    assert application.download_service.retry_download_calls == [7]


def test_retry_stays_disabled_across_renders_while_it_searches(qtbot):
    failed = make_active_download(
        status="failed", request_id=7,
        bytes_transferred=None, total_bytes=None,
    )
    other = make_active_download(
        track_id="t2", status="unavailable", request_id=8,
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication(active_downloads=[failed, other])
    gate = threading.Event()
    application.download_service.retry_gate = gate
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([failed, other])

    _row_button(page, 0, "Retry").click()
    # A theme switch rebuilds every row while the search runs.
    page._rendered_rows = None
    page._render_active_downloads([failed, other])

    # One retry searches at a time.
    assert not _row_button(page, 0, "Retry").isEnabled()
    assert not _row_button(page, 1, "Retry").isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: page.notice.text() != "", timeout=2000)
    page._rendered_rows = None
    page._render_active_downloads([failed, other])
    assert _row_button(page, 1, "Retry").isEnabled()


def test_a_retry_that_fails_says_why(qtbot):
    failed = make_active_download(
        status="failed", request_id=7,
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication(active_downloads=[failed])
    application.download_service.retry_error = RuntimeError(
        "slskd went away."
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([failed])

    _row_button(page, 0, "Retry").click()

    qtbot.waitUntil(
        lambda: "slskd went away." in page.notice.text(), timeout=2000,
    )


# --- Cancel -----------------------------------------------------------------

def test_only_a_queued_row_offers_cancel(qtbot):
    downloads = [
        make_active_download(track_id=status, status=status, request_id=row)
        for row, status in enumerate((
            "queued", "downloading", "failed", "locked", "shortlisted",
        ))
    ]
    window = MainWindow(FakeApplication(active_downloads=downloads))
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads(downloads)

    offered = [
        _row_button(page, row, "Cancel") is not None for row in range(5)
    ]

    assert offered == [True, False, False, False, False]
    button = _row_button(page, 0, "Cancel")
    assert button.accessibleName() == "Cancel Artist - Title"
    assert button.toolTip() == help_text.TOOLTIP_CANCEL_DOWNLOAD


@pytest.mark.parametrize("outcome", list(CancelOutcome))
def test_cancel_stops_the_download_and_says_what_happened(qtbot, outcome):
    queued = make_active_download(status="queued", request_id=7)
    application = FakeApplication(active_downloads=[queued])
    application.download_service.cancel_outcome = outcome
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([queued])

    _row_button(page, 0, "Cancel").click()

    qtbot.waitUntil(
        lambda: page.notice.text()
        == help_text.cancel_outcome_text(outcome, "Artist - Title"),
        timeout=2000,
    )
    assert application.download_service.cancel_download_calls == [7]


def test_cancel_stays_disabled_across_renders_while_it_runs(qtbot):
    queued = make_active_download(status="queued", request_id=7)
    other = make_active_download(track_id="t2", status="queued", request_id=8)
    application = FakeApplication(active_downloads=[queued, other])
    gate = threading.Event()
    application.download_service.cancel_gate = gate
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([queued, other])

    _row_button(page, 0, "Cancel").click()
    page._rendered_rows = None
    page._render_active_downloads([queued, other])

    assert not _row_button(page, 0, "Cancel").isEnabled()
    assert not _row_button(page, 1, "Cancel").isEnabled()
    gate.set()
    qtbot.waitUntil(lambda: page.notice.text() != "", timeout=2000)
    page._rendered_rows = None
    page._render_active_downloads([queued, other])
    assert _row_button(page, 1, "Cancel").isEnabled()


def test_a_cancel_that_fails_says_why(qtbot):
    queued = make_active_download(status="queued", request_id=7)
    application = FakeApplication(active_downloads=[queued])
    application.download_service.cancel_error = RuntimeError(
        "slskd went away."
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._downloads_page
    page._render_active_downloads([queued])

    _row_button(page, 0, "Cancel").click()

    qtbot.waitUntil(
        lambda: "slskd went away." in page.notice.text(), timeout=2000,
    )


def _leftover(name: str, size: int):
    from seeker.models.leftover_result import LeftoverFile, LeftoverFolder

    return LeftoverFile(
        f"/slskd/downloads/{name}", LeftoverFolder.DOWNLOADS, size, 0.0,
        f"downloads/{name}",
    )


def _cleanup_page(qtbot, monkeypatch, answer):
    from seeker.ui.dialogs import LeftoverCleanupDialog

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    shown: list[LeftoverCleanupDialog] = []

    def fake_exec(dialog):
        shown.append(dialog)
        return answer

    monkeypatch.setattr(LeftoverCleanupDialog, "exec", fake_exec)
    return application.leftover_service, window._downloads_page, shown


def test_clean_up_with_no_leftovers_says_so_and_asks_nothing(
        qtbot, monkeypatch,
):
    from PySide6.QtWidgets import QDialog

    leftovers, page, shown = _cleanup_page(
        qtbot, monkeypatch, QDialog.DialogCode.Accepted,
    )

    page.clean_up_button.click()

    qtbot.waitUntil(lambda: not page.notice.isHidden(), timeout=2000)
    assert page.notice.text() == help_text.leftover_listing_empty_text(0)
    assert shown == []
    assert leftovers.delete_calls == []


def test_clean_up_declined_deletes_nothing(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from seeker.models.leftover_result import LeftoverListing

    leftovers, page, shown = _cleanup_page(
        qtbot, monkeypatch, QDialog.DialogCode.Rejected,
    )
    leftovers.listing = LeftoverListing([_leftover("Old.mp3", 5)])

    page.clean_up_button.click()

    qtbot.waitUntil(lambda: len(shown) == 1, timeout=2000)
    qtbot.waitUntil(page.clean_up_button.isEnabled, timeout=2000)
    assert leftovers.delete_calls == []
    assert page.notice.isHidden()


def test_clean_up_confirmed_deletes_the_listed_files_and_reports(
        qtbot, monkeypatch,
):
    from PySide6.QtWidgets import QDialog

    from seeker.models.leftover_result import LeftoverCleanup, LeftoverListing

    leftovers, page, shown = _cleanup_page(
        qtbot, monkeypatch, QDialog.DialogCode.Accepted,
    )
    files = [_leftover("Big.mp3", 30), _leftover("Old.mp3", 5)]
    leftovers.listing = LeftoverListing(files)
    leftovers.cleanup = LeftoverCleanup(deleted=files)

    page.clean_up_button.click()

    qtbot.waitUntil(lambda: not page.notice.isHidden(), timeout=2000)
    qtbot.waitUntil(page.clean_up_button.isEnabled, timeout=2000)
    assert len(shown) == 1
    assert leftovers.delete_calls == [files]
    assert page.notice.text() == help_text.leftover_cleanup_outcome_text(
        leftovers.cleanup,
    )
    assert page.notice.property("variant") == "success"


def test_clean_up_shows_why_it_could_not_list(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from seeker.soulseek.leftovers import LeftoverFolderUnknownError

    leftovers, page, shown = _cleanup_page(
        qtbot, monkeypatch, QDialog.DialogCode.Accepted,
    )
    leftovers.error = LeftoverFolderUnknownError("Not slskd's folder.")

    page.clean_up_button.click()

    qtbot.waitUntil(lambda: not page.notice.isHidden(), timeout=2000)
    qtbot.waitUntil(page.clean_up_button.isEnabled, timeout=2000)
    assert page.notice.text() == "Not slskd's folder."
    assert page.notice.property("variant") == "error"
    assert shown == []

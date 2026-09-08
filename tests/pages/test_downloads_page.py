"""Tests for the Downloads page (seeker.ui.pages.downloads_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.3) — the
mirror of §9.3.1's own Downloads extraction (S7).
"""

from datetime import UTC, datetime, timedelta

from PySide6.QtWidgets import QLabel, QProgressBar

from seeker.models.active_download import ActiveDownload
from seeker.models.download_request import DownloadRequest
from seeker.models.track import Track
from seeker.ui import theme
from seeker.ui.main_window import MainWindow
from test_ui_smoke import (
    FakeApplication,
    _force_tray_available,
    _make_active_download,
    _make_track,
)


def test_downloads_tab_renders_rows_across_playlists(qtbot):
    downloads = [
        _make_active_download(track_id="t1", playlist_name="Playlist A"),
        _make_active_download(
            track_id="t2", status="locked", role="upgrade",
            bytes_transferred=None, total_bytes=None,
            playlist_name="Playlist B",
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads(downloads)

    assert window.downloads_table.rowCount() == 2
    assert window.downloads_table.item(0, 1).text() == "Playlist A"
    assert window.downloads_table.item(1, 1).text() == "Playlist B"
    # A raw "locked" status gets a plain-language note, not the raw
    # state string.
    assert window.downloads_table.item(1, 3).text() == "Retrying (locked)"


# --- Downloads aggregate remaining-time header (Task 9) --------------------

def test_downloads_aggregate_header_blank_with_no_active_downloads(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([])

    assert window.downloads_eta_label.text() == ""
    assert window.downloads_eta_label.toolTip() == ""


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
    window._eta_tracker.record(
            1,
            200,
            datetime(2026, 1, 1, tzinfo=UTC),
    )
    window._eta_tracker.record(
            1,
            500,
            datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )

    window._render_active_downloads([download])

    assert "remaining" in window.downloads_eta_label.text()
    assert "1 transferring" in window.downloads_eta_label.text()
    assert window.downloads_eta_label.toolTip() != ""


def test_downloads_aggregate_header_reports_waiting_with_no_samples(qtbot):
    download = _make_active_download(
        status="queued", bytes_transferred=None, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    assert window.downloads_eta_label.text() == (
        "Waiting for transfers to start · 0 transferring · "
        "1 queued (no estimate)"
    )


def test_downloads_tab_progress_bar_indeterminate_with_no_bytes_yet(qtbot):
    download = _make_active_download(
        status="queued", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    # Roadmap item 96 (B4) — wrapped in the same QHBoxLayout container
    # shape as every other exit of _build_progress_widget/
    # _build_terminal_progress_widget, not returned bare: a bare bar
    # returned directly from setCellWidget gets resized to the FULL
    # cell rect by Qt, and the global QProgressBar max-height: 14px
    # rule then clamps it to the TOP of a tall row instead of centering
    # it (the real reported bug — a queued row's bar visibly sat above
    # center while a downloading row's own bar, already wrapped, sat
    # centered).
    container = window.downloads_table.cellWidget(0, 4)
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
    # theme.style_determinate_progress_bar() unconditionally.
    assert bar.styleSheet() == ""


def test_downloads_tab_progress_bar_determinate_with_real_bytes(qtbot):
    # A determinate bar is wrapped in a container alongside the ETA
    # label (Task 2) — the bar itself is a child widget, not the cell
    # widget directly (the indeterminate/queued case above is now
    # wrapped the identical way, roadmap item 96).
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.maximum() == 1_000
    assert bar.value() == 500
    # The accent chunk fill IS a per-instance stylesheet override, not
    # a global QSS rule (see theme.py's own QProgressBar::chunk
    # comment) — a determinate bar must actually receive it.
    assert "chunk" in bar.styleSheet()


def test_downloads_tab_queued_and_downloading_bars_are_both_vertically_centered(
        qtbot,
):
    # Roadmap item 96 (B4.3) — real pixel verification of the reported
    # bug: a queued row's bar used to sit clamped to the TOP of its
    # cell (a bare bar returned from setCellWidget gets resized to the
    # full, tall cell rect, then the global 14px max-height rule clamps
    # it upward) while a downloading row's own bar, already wrapped in
    # a container, sat centered. Both must now match.
    downloads = [
        _make_active_download(
            track_id="t1", status="queued",
            bytes_transferred=None, total_bytes=None,
        ),
        _make_active_download(
            track_id="t2", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("downloads")

    window._render_active_downloads(downloads)
    qtbot.wait(20)

    viewport = window.downloads_table.viewport()

    for row in (0, 1):
        row_rect = window.downloads_table.visualRect(
            window.downloads_table.model().index(row, 4)
        )
        widget = window.downloads_table.cellWidget(row, 4)
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
        int(theme.BG_SURFACE[i:i + 2], 16) for i in (1, 3, 5)
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
        row_rect = window.downloads_table.visualRect(
            window.downloads_table.model().index(row, 4)
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
        _make_active_download(
            track_id="t1", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ]
    application = FakeApplication(active_downloads=downloads)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window._show_page("downloads")
    window._render_active_downloads(downloads)
    qtbot.wait(100)

    table = window.downloads_table
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
        int(theme.BORDER_STRONG[i:i + 2], 16) for i in (1, 3, 5)
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
    download = _make_active_download(
        status="locked", role="upgrade",
        bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    bar = window.downloads_table.cellWidget(0, 4)
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
    download = _make_active_download(
        status="completed", bytes_transferred=1_000, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(3):
        window._eta_tracker.record(1, 1_000, now + timedelta(seconds=i * 20))

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label_texts = [
        child.text() for child in container.findChildren(QLabel)
    ]
    assert "Completed" in label_texts
    assert "Stalled" not in label_texts
    # Evicted immediately, not left for the row to eventually drop out
    # of get_active_downloads() on its own.
    assert 1 not in window._eta_tracker._history


def test_terminal_progress_widget_shows_a_full_bar_for_completed(qtbot):
    download = _make_active_download(
        status="completed", bytes_transferred=1_000, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    bar = container.findChild(QProgressBar)
    assert bar is not None
    assert bar.value() == bar.maximum()


def test_terminal_progress_widget_shows_ready_for_review_label(qtbot):
    download = _make_active_download(
        status="ready_for_review", role="upgrade",
        bytes_transferred=1_000, total_bytes=1_000,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label_texts = [
        child.text() for child in container.findChildren(QLabel)
    ]
    assert "Ready for review" in label_texts


def test_terminal_progress_widget_for_failed_is_blank_not_a_bar(qtbot):
    download = _make_active_download(
        status="failed", bytes_transferred=None, total_bytes=None,
    )
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    widget = window.downloads_table.cellWidget(0, 4)
    assert not isinstance(widget, QProgressBar)
    assert widget.findChild(QProgressBar) is None


def test_aggregate_header_excludes_terminal_rows_from_queued_count(qtbot):
    # Roadmap item 56 Phase 5.4 §4 — a completed row was previously
    # folded into the "queued (no estimate)" figure.
    completed = _make_active_download(
        track_id="t1", status="completed",
        bytes_transferred=1_000, total_bytes=1_000,
    )
    completed.request.id = 1
    queued = _make_active_download(
        track_id="t2", status="queued",
        bytes_transferred=None, total_bytes=1_000,
    )
    queued.request.id = 2
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([completed, queued])

    assert window.downloads_eta_label.text() == (
        "Waiting for transfers to start · 0 transferring · "
        "1 queued (no estimate)"
    )


def test_downloads_tab_eta_shows_calculating_before_second_sample(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=500, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "Calculating…"


def test_downloads_tab_eta_shows_estimate_after_two_samples(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(UTC)
    # 400 bytes/second over the last interval, 400 bytes remaining ->
    # a clean 1s ETA, easy to assert on exactly.
    window._eta_tracker.record(1, 200, now - timedelta(seconds=1))
    window._eta_tracker.record(1, 600, now)

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "1s"


def test_downloads_tab_eta_shows_stalled_after_flat_samples(qtbot):
    download = _make_active_download(
        status="downloading", bytes_transferred=600, total_bytes=1_000,
    )
    download.request.id = 1
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(UTC)
    for offset in (2, 1, 0):
        window._eta_tracker.record(1, 600, now - timedelta(seconds=offset))

    window._render_active_downloads([download])

    container = window.downloads_table.cellWidget(0, 4)
    label = container.findChild(QLabel)
    assert label.text() == "Stalled"


def test_record_eta_samples_evicts_ids_no_longer_active(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    now = datetime.now(UTC)
    window._eta_tracker.record(1, 100, now)
    window._eta_tracker.record(1, 200, now)

    # request id 1 has since disappeared from get_active_downloads() —
    # completed, failed, or superseded — so a fresh sampling pass with
    # no row for it must drop its history rather than keep it forever
    # (Task 2's own explicit leak-prevention requirement).
    window._record_eta_samples([])

    assert window._eta_tracker.describe(1, 1_000) == "Calculating…"


def test_trigger_backend_poll_samples_eta_after_poll_succeeds(qtbot):
    download = _make_active_download(bytes_transferred=500, total_bytes=1_000)
    download.request.id = 7

    application = FakeApplication(
        soulseek_configured=True, active_downloads=[download],
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._trigger_backend_poll()

    qtbot.waitUntil(lambda: 7 in window._eta_tracker._history, timeout=2000)


def test_downloads_paged_render_skips_table_population_while_hidden(
        qtbot, monkeypatch,
):
    # Roadmap item R7.6.
    _force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._hidden_to_tray = True

    downloads = [
        ActiveDownload(
            track=_make_track("t1"),
            request=DownloadRequest(
                track_id="t1", username="peer1", filename="a.flac",
                format="flac", quality_descriptor="flac", role="settled",
                status="downloading", requested_at="2026-01-01",
            ),
            playlist_name="Test",
        ),
    ]
    window._render_active_downloads(downloads)

    # The count used by the tray IS still updated...
    assert window._active_downloads_count == 1
    # ...but the actual table was never touched.
    assert window.downloads_table.rowCount() == 0

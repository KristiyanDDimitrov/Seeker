"""Every table and list across every page: shared chrome, column
sizing, header fit and cell-widget wrapping.
"""

from PySide6.QtWidgets import (
    QProgressBar,
    QPushButton,
)

from fakes import (
    FakeApplication,
    make_active_download,
    make_duplicate_group,
    make_location,
    make_needs_review_match,
    make_review_candidate,
    make_track,
    make_track_status,
    make_upgrade_details,
)
from seeker.models.track_status import (
    DOWNLOADING,
    IN_LIBRARY,
    TrackStatus,
)
from seeker.ui import theme
from seeker.ui.main_window import (
    MainWindow,
)


def test_every_table_and_list_widget_is_routed_through_make_card(qtbot):
    # Roadmap item 80 (P10.1) — a table/list's own border-radius does
    # NOT clip its children; any cell-widget button reaching its edge
    # paints over the rounded corner. theme.make_card() is the
    # structural fix, and this asserts it's actually used everywhere
    # a QTableWidget/QListWidget is added to the real window, not just
    # available for someone to remember to call.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    # History/Search/Sharing/Downloads/Dashboard/Review/Duplicates have
    # no delegating properties (S11.1/S11.2/S11.3/S11.4/S11.5/S11.6,
    # §9.3.4) — same check, against their own page widgets directly.
    page_owned_tables = [
        ("history_table", window._history_page.history_table),
        ("search_results_table", window._search_page.search_results_table),
        (
            "sharing_locations_table",
            window._sharing_page.sharing_locations_table,
        ),
        ("sharing_uploads_table", window._sharing_page.sharing_uploads_table),
        ("downloads_table", window._downloads_page.downloads_table),
        ("playlist_list", window._dashboard_page.playlist_list),
        ("track_table", window._dashboard_page.track_table),
        ("review_needs_table", window._review_page.review_needs_table),
        ("review_upgrades_table", window._review_page.review_upgrades_table),
        ("review_local_table", window._review_page.review_local_table),
        (
            "duplicates_folders_list",
            window._duplicates_page.duplicates_folders_list,
        ),
        ("duplicates_table", window._duplicates_page.duplicates_table),
    ]
    for name, widget in page_owned_tables:
        parent = widget.parentWidget()
        assert parent is not None, name
        assert parent.objectName() == "card", (
            f"{name}'s parent is {parent!r}, not routed through make_card()"
        )


def test_every_actions_column_table_has_a_derived_floor_for_row_height_and_width(
        qtbot,
):
    # Roadmap item R5 (5b.4) — regression coverage for every table with
    # a real Actions column, generalizing item 73's own single-table
    # test: the column must be widened to at least the real Actions
    # widget's own sizeHint().width() ("Confirm" clipped to "onfirm"),
    # and every row must be at least as tall as that widget's own
    # sizeHint().height() ("Replace"/"Decline" sliced off at the
    # bottom) — both derived from the real widget actually built this
    # render, never a magic number.
    from seeker.soulseek.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._dashboard_page._render_track_statuses(
        [make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._review_page._render_needs_review_candidates(
        [(make_track(), make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
        LocationShareState(
            location=make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window.settings_page._render_locations(
        [(make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )

    tables_and_columns = [
        (window._dashboard_page.track_table, 3),
        (window._review_page.review_needs_table, 4),
        (window._review_page.review_upgrades_table, 3),
        (window._review_page.review_local_table, 4),
        (window._sharing_page.sharing_locations_table, 4),
        # Roadmap item 97 (B6.3) — settings_window.py's own table had
        # never had a derived Actions width before this.
        (window.settings_page.locations_table, 3),
    ]

    for table, actions_column in tables_and_columns:
        assert table.rowCount() >= 1, table.objectName() or repr(table)
        widget = table.cellWidget(0, actions_column)
        assert widget is not None

        header = table.horizontalHeader()
        assert header.sectionSize(actions_column) >= widget.sizeHint().width()
        assert table.rowHeight(0) >= widget.sizeHint().height()


def test_every_table_and_list_goes_through_the_shared_chrome_helpers(qtbot):
    # Roadmap item 97 (B6.4) — this is the third round in a row a shared
    # table-chrome fix landed in main_window.py and not settings_window.py
    # (item 80, then R5, now this). A real structural check over every
    # live QTableWidget/QListWidget in the real app, not just the two
    # settings_window.py had, so a FOURTH table added anywhere without
    # going through apply_table_defaults()/make_card() fails this test
    # instead of quietly reappearing as the same class of bug.
    from PySide6.QtWidgets import QFrame, QListWidget, QTableWidget

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    def _has_card_ancestor(widget) -> bool:
        parent = widget.parent()
        while parent is not None:
            if isinstance(parent, QFrame) and parent.objectName() == "card":
                return True
            parent = parent.parent()
        return False

    tables = window.findChildren(QTableWidget)
    lists = window.findChildren(QListWidget)
    assert tables, "no QTableWidget found — test itself is broken"
    assert lists, "no QListWidget found — test itself is broken"

    for table in tables:
        assert table.verticalHeader().isVisible() is False, (
            table.objectName() or repr(table)
        )
        assert _has_card_ancestor(table), table.objectName() or repr(table)

    for widget_list in lists:
        assert _has_card_ancestor(widget_list), (
            widget_list.objectName() or repr(widget_list)
        )


def _assert_every_column_fits_its_own_header(window) -> None:
    from PySide6.QtWidgets import QTableWidget

    for table in window.findChildren(QTableWidget):
        header = table.horizontalHeader()
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            if item is None or not item.text():
                continue
            floor = theme.header_label_floor(table, column)
            assert header.sectionSize(column) >= floor, (
                f"{table.objectName() or table!r} col {column} "
                f"({item.text()!r}): section={header.sectionSize(column)} "
                f"< floor={floor}"
            )


def test_no_table_column_clips_its_own_header_label_when_empty(qtbot):
    # Roadmap item C2 (round 5) — the real reported bug: "Actions"
    # rendered as ".ction" on Review's three EMPTY tables (a brand-new
    # user's very first look at that page). `size_action_column`'s old
    # fallback for zero real action widgets was a generic 40px floor
    # with no relation to the header text at all. Every real
    # QTableWidget in the app starts with zero rows at construction —
    # this is exactly that state, checked structurally across the
    # whole window rather than one page at a time.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    _assert_every_column_fits_its_own_header(window)

    # And again at the app's real 960x640 minimum — construction-time
    # column widths don't depend on window size, but this is the exact
    # size the brief's own screenshot was taken at.
    window.resize(960, 640)
    qtbot.wait(20)
    _assert_every_column_fits_its_own_header(window)


def test_no_table_column_clips_its_own_header_label_when_populated(qtbot):
    # C2.3/C2.4 — the same invariant must keep holding once real rows
    # (and real, possibly-narrow Actions widgets) exist, at both the
    # app's real 960x640 minimum and a default-sized window.
    from seeker.soulseek.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window._dashboard_page._render_track_statuses(
        [make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._review_page._render_needs_review_candidates(
        [(make_track(), make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
        LocationShareState(
            location=make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window._duplicates_page._render_duplicate_groups([make_duplicate_group()])
    window.settings_page._render_locations(
        [(make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )
    qtbot.wait(20)

    for width, height in [(960, 640), (1280, 800)]:
        window.resize(width, height)
        qtbot.wait(20)
        _assert_every_column_fits_its_own_header(window)


def _assert_no_dead_band_at_stretch_columns(window, qtbot) -> None:
    from PySide6.QtWidgets import QTableWidget

    # Roadmap item E2.3 (round 7) — this used to `continue` past any
    # table with no Stretch column/stretchLastSection, which sounds
    # like a reasonable "this invariant doesn't apply here" guard but
    # is derived from the SAME state E2's own bug corrupts: an empty
    # table (nothing has ever assigned it a resize mode) reads as "no
    # stretch column" and was skipped by this exact test, on the exact
    # screen (an empty Search/Duplicates table) the user photographed
    # as broken. A skip condition computed from the state the bug
    # corrupts cannot be a guard — asserting the real invariant
    # unconditionally for every visible table is the only way this test
    # can't blind itself to the case it exists to catch.
    for page_key in (
        "dashboard", "search", "downloads", "review",
        "duplicates", "sharing", "history", "settings",
    ):
        window._show_page(page_key)
        qtbot.wait(10)
        for table in window.findChildren(QTableWidget):
            if not table.isVisible():
                continue
            header = table.horizontalHeader()
            total = sum(
                header.sectionSize(column)
                for column in range(table.columnCount())
            )
            viewport_width = table.viewport().width()
            assert total >= viewport_width - 2, (
                f"{table.objectName() or table!r} on page {page_key!r}: "
                f"sum(sectionSize)={total} < viewport width="
                f"{viewport_width} — a Stretch column left dead space"
            )


def test_stretch_columns_reach_the_viewport_edge_with_no_dead_band(qtbot):
    # Roadmap item D3.5 (round 6) — the actual regression check for the
    # reported bug: a `Stretch` column pinned to its header-label floor
    # by the OLD, unscoped `apply_table_defaults` loop, leaving a dead
    # band between the last real column and the table's own right edge.
    # Paired deliberately with the C2 header-floor test above — the two
    # invariants pull in opposite directions (widen a column for its
    # header vs. never pin a column that's supposed to size itself) and
    # both must hold at once, with zero rows and with real ones, at the
    # app's real 960x640 minimum and a default-sized window.
    from seeker.models.soulseek_file import SoulseekFile
    from seeker.soulseek.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    for width, height in [(960, 640), (1280, 800)]:
        window.resize(width, height)
        qtbot.wait(20)
        _assert_no_dead_band_at_stretch_columns(window, qtbot)

    window._dashboard_page._render_track_statuses(
        [make_track_status(track_id="t1", state=IN_LIBRARY, tagged_at=None)]
    )
    window._search_page._render_search_results(
        "Dom Dolla", "Rhyme Dust",
        [
            SoulseekFile(
                username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
                extension="flac", size=25_000_000, queue_length=0,
                upload_speed=1_000_000, has_free_upload_slot=True,
            ),
        ],
    )
    window._review_page._render_needs_review_candidates(
        [(make_track(), make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
        LocationShareState(
            location=make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window._duplicates_page._render_duplicate_groups([make_duplicate_group()])
    window.settings_page._render_locations(
        [(make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )
    qtbot.wait(20)

    for width, height in [(960, 640), (1280, 800)]:
        window.resize(width, height)
        qtbot.wait(20)
        _assert_no_dead_band_at_stretch_columns(window, qtbot)


def test_every_table_has_a_stretch_column_immediately_after_construction(
        qtbot,
):
    # Roadmap item E2.4 (round 7) — the structural invariant whose
    # absence caused E2 in the first place: seven tables only assigned
    # their real resize modes (a Stretch column, or stretchLastSection)
    # inside a render method that never runs while the table is empty,
    # so a freshly-built, still-empty table sat at Qt's default 100px-
    # per-column layout with no column owning the leftover viewport
    # width. Checked with NO `.show()` and NO render call at all — every
    # page is built eagerly in `MainWindow.__init__` (`_register_page`),
    # so this is genuinely "immediately after construction," the exact
    # moment E2's fix (`_configure_*_columns`, called from each table's
    # own `_build_*`) must already hold.
    #
    # Roadmap item 8.1.2 (round 8, Phase 5) — strengthened alongside the
    # ColumnLayout refactor (§8.1.1): a table can have a real Stretch
    # column while still leaving its OTHER columns at Qt's raw default
    # width, if nothing ever derived a width for them either. Every
    # table built through `theme.configure_columns` derives every
    # non-stretch column's width from its own header label (or a real
    # Actions widget) via `apply_column_floors`/`size_action_column` —
    # so for those tables, no non-stretch column may still equal
    # `header.defaultSectionSize()`.
    from PySide6.QtWidgets import QHeaderView, QTableWidget

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    tables = window.findChildren(QTableWidget)
    assert tables, "expected at least one QTableWidget in the window"

    # Roadmap item 8.1.3 — these three genuinely have no ColumnLayout:
    # no Actions column, no per-column resize mode at all, just
    # stretchLastSection for their one flex column (see the comments
    # beside their construction in main_window.py). Excluded from the
    # stronger per-column check below only — the `has_stretch` check
    # above still runs on them, which is the actual E2 invariant this
    # test exists to guard; their non-flex columns were never claimed
    # to be derived and are not the bug class E2 fixed.
    _no_column_layout = {
        window._downloads_page.downloads_table, window._history_page.history_table,
        window._sharing_page.sharing_uploads_table,
    }

    for table in tables:
        header = table.horizontalHeader()
        has_stretch = header.stretchLastSection() or any(
            header.sectionResizeMode(column)
            == QHeaderView.ResizeMode.Stretch
            for column in range(table.columnCount())
        )
        assert has_stretch, (
            f"{table.objectName() or table!r} has no Stretch column and "
            f"no stretchLastSection immediately after construction — an "
            f"empty render of this table will sit at Qt's default "
            f"100px-per-column layout"
        )

        if table in _no_column_layout:
            continue

        last_column = table.columnCount() - 1
        for column in range(table.columnCount()):
            if header.stretchLastSection() and column == last_column:
                continue
            if (
                header.sectionResizeMode(column)
                == QHeaderView.ResizeMode.Stretch
            ):
                continue
            assert (
                header.sectionSize(column) != header.defaultSectionSize()
            ), (
                f"{table.objectName() or table!r} column {column} is "
                f"still at Qt's raw default width immediately after "
                f"construction — ColumnLayout should have derived a "
                f"real width for it"
            )


def test_no_table_ever_hands_a_bare_progress_bar_or_button_to_setcellwidget(
        qtbot,
):
    # Roadmap item C3 (round 5, C3.3) — the actual root cause of both
    # this item and B4/item 96: a bare QProgressBar or QPushButton
    # handed directly to setCellWidget gets resized to fill the WHOLE
    # cell rect, then either the global max-height rule clamps it to
    # the top (QProgressBar) or it paints as an oversized filled block
    # (QPushButton, item 80's own P10.3). A real structural sweep, not
    # a hand-picked list of tables — a fifth call site introduced
    # anywhere in the app fails this automatically.
    from seeker.models.soulseek_file import SoulseekFile
    from seeker.soulseek.sharing_service import LocationShareState

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window._dashboard_page._render_track_statuses([
        TrackStatus(
            track=make_track("t1"), state=DOWNLOADING,
            bytes_transferred=500, total_bytes=1_000,
        ),
        make_track_status(track_id="t2", state=IN_LIBRARY, tagged_at=None),
    ])
    window._show_page("downloads")
    window._downloads_page._render_active_downloads([
        make_active_download(
            track_id="t3", status="downloading",
            bytes_transferred=500, total_bytes=1_000,
        ),
    ])
    window._show_page("search")
    window._search_page._render_search_results(
        "Dom Dolla", "Rhyme Dust",
        [
            SoulseekFile(
                username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
                extension="flac", size=25_000_000, queue_length=0,
                upload_speed=1_000_000, has_free_upload_slot=True,
            ),
        ],
    )
    window._show_page("duplicates")
    window._duplicates_page._render_duplicate_groups([make_duplicate_group()])
    window._show_page("review")
    window._review_page._render_needs_review_candidates(
        [(make_track(), make_review_candidate())]
    )
    window._review_page._render_pending_upgrades(
        [make_upgrade_details(old_file_path="/music/old.mp3")]
    )
    window._review_page._render_local_needs_review_matches([make_needs_review_match()])
    window._sharing_page._render_sharing_locations_table([
        LocationShareState(
            location=make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=False, share=None,
        ),
    ])
    window.settings_page._render_locations(
        [(make_location(2, "Main", "/Volumes/Drive/Main"), True)]
    )
    qtbot.wait(20)

    from PySide6.QtWidgets import QTableWidget

    checked = 0
    for table in window.findChildren(QTableWidget):
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                widget = table.cellWidget(row, column)
                if widget is None:
                    continue
                checked += 1
                assert not isinstance(widget, (QProgressBar, QPushButton)), (
                    f"{table.objectName() or table!r} ({row}, {column}) "
                    f"got a bare {type(widget).__name__} directly"
                )
    assert checked > 0, "no cell widgets found — test itself is broken"

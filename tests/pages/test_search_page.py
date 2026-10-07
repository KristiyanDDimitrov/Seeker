"""Tests for the Search page (seeker.ui.pages.search_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.2) — the
mirror of §9.3.1's own Search extraction (S6).
"""

from PySide6.QtWidgets import QPushButton

from fakes import FakeApplication
from seeker.models.download_result import ManualDownloadResult
from seeker.ui import help_text
from seeker.ui.main_window import MainWindow


def _search_column(window, header_text: str) -> int:
    header = window._search_page.search_results_table.horizontalHeaderItem
    for column in range(window._search_page.search_results_table.columnCount()):
        if header(column).text() == header_text:
            return column
    raise AssertionError(f"No Search column named {header_text!r}")


def test_search_empty_fields_shows_a_message_and_does_not_search(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._search_page._on_search_clicked()

    assert application.download_service.search_manual_calls == []
    assert window._search_page.notice.text() == (
        help_text.SEARCH_EMPTY_FIELDS_MESSAGE
    )
    assert window._search_page.notice.isVisibleTo(window)


def test_search_renders_results_ranked_best_first(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    flac_file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    mp3_file = SoulseekFile(
        username="peer2", filename="Dom Dolla - Rhyme Dust.mp3",
        extension="mp3", size=8_000_000, queue_length=1,
        upload_speed=1_000_000, has_free_upload_slot=True, bit_rate=320,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [
        mp3_file, flac_file,
    ]
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._search_page.search_artist_edit.setText("Dom Dolla")
    window._search_page.search_title_edit.setText("Rhyme Dust")
    window._search_page._on_search_clicked()

    qtbot.waitUntil(
        lambda: window._search_page.search_results_table.rowCount() == 2, timeout=2000,
    )
    assert application.download_service.search_manual_calls == [
        ("Dom Dolla", "Rhyme Dust")
    ]

    peer_col = _search_column(window, "Peer")
    results_table = window._search_page.search_results_table
    # flac (lossless) outranks mp3 regardless of search result order.
    assert results_table.item(0, peer_col).text() == "peer1"
    assert results_table.item(1, peer_col).text() == "peer2"
    assert "Found 2 results" in window._search_page.search_status_label.text()
    assert window._search_page.download_best_button.isEnabled()


def test_search_no_results_shows_a_clear_message(qtbot):
    application = FakeApplication()
    application.download_service._search_manual_results = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._search_page.search_artist_edit.setText("Nobody")
    window._search_page.search_title_edit.setText("Nothing")
    window._search_page._on_search_clicked()

    empty = window._search_page.search_results_empty
    qtbot.waitUntil(lambda: "Nobody - Nothing" in empty.text(), timeout=2000)
    assert empty.text() == help_text.format_search_no_results(
        "Nobody", "Nothing",
    )
    assert empty.isVisibleTo(window)
    assert not window._search_page.download_best_button.isEnabled()


def test_search_results_invite_a_search_before_the_first_one(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)

    empty = window._search_page.search_results_empty

    assert empty.text() == help_text.SEARCH_RESULTS_EMPTY
    assert empty.isVisibleTo(window._search_page)


def test_search_download_best_passes_the_already_fetched_results(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_result = (
        ManualDownloadResult(
            track_id="manual:fake", requested=True, settled=True,
            username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._search_page.search_artist_edit.setText("Dom Dolla")
    window._search_page.search_title_edit.setText("Rhyme Dust")
    window._search_page._on_search_clicked()
    qtbot.waitUntil(
        window._search_page.download_best_button.isEnabled, timeout=2000,
    )

    window._search_page.download_best_button.click()

    qtbot.waitUntil(
        lambda: bool(application.download_service.download_manual_calls),
        timeout=2000,
    )
    artist, title, chosen, files = (
        application.download_service.download_manual_calls[0]
    )
    assert (artist, title) == ("Dom Dolla", "Rhyme Dust")
    assert chosen is None
    # Roadmap item 82 — reuses the already-fetched results, no second
    # real 20-45s network search.
    assert files == [file]
    qtbot.waitUntil(
        lambda: "Requested from peer1" in window._search_page.notice.text(),
        timeout=2000,
    )
    assert window._search_page.search_status_label.text() == ""


def test_search_download_this_one_passes_the_explicit_pick(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_result = (
        ManualDownloadResult(
            track_id="manual:fake", requested=True, settled=True,
            username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._search_page.search_artist_edit.setText("Dom Dolla")
    window._search_page.search_title_edit.setText("Rhyme Dust")
    window._search_page._on_search_clicked()
    qtbot.waitUntil(
        lambda: window._search_page.search_results_table.rowCount() == 1, timeout=2000,
    )

    actions_col = _search_column(window, "Actions")
    button = (
        window._search_page.search_results_table.cellWidget(0, actions_col)
        .findChild(QPushButton)
    )
    button.click()

    qtbot.waitUntil(
        lambda: bool(application.download_service.download_manual_calls),
        timeout=2000,
    )
    artist, title, chosen, files = (
        application.download_service.download_manual_calls[0]
    )
    assert (artist, title) == ("Dom Dolla", "Rhyme Dust")
    assert chosen is file
    assert files is None


def test_search_no_destination_shows_settings_guidance(qtbot):
    from seeker.models.soulseek_file import SoulseekFile
    from seeker.soulseek.download_service import NoDestinationConfiguredError

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_error = (
        NoDestinationConfiguredError(
            "No download destination is configured yet."
        )
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")

    window._search_page.search_artist_edit.setText("Dom Dolla")
    window._search_page.search_title_edit.setText("Rhyme Dust")
    window._search_page._on_search_clicked()
    qtbot.waitUntil(
        window._search_page.download_best_button.isEnabled, timeout=2000,
    )

    window._search_page.download_best_button.click()

    qtbot.waitUntil(
        lambda: "Settings" in window._search_page.notice.text(),
        timeout=2000,
    )


def _peer_file(**overrides):
    from seeker.models.soulseek_file import SoulseekFile

    fields = {
        "username": "peer1",
        "filename": "Music\\Dom Dolla\\Rhyme Dust.flac",
        "extension": "flac", "size": 25_000_000, "queue_length": 0,
        "upload_speed": 1_000_000, "has_free_upload_slot": True,
    }
    return SoulseekFile(**(fields | overrides))


def test_search_results_lead_with_the_file_name(qtbot):
    from seeker.ui.elided_text import BADGE_ROLE

    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._search_page

    page._render_search_results("Dom Dolla", "Rhyme Dust", [
        _peer_file(),
        _peer_file(
            username="peer2", filename="Rhyme Dust.mp3", extension="mp3",
            bit_rate=320, locked=True,
        ),
    ])

    table = page.search_results_table
    filename_col = _search_column(window, "Filename")
    quality_col = _search_column(window, "Quality")
    assert filename_col == 0
    assert table.item(0, filename_col).text() == "Rhyme Dust.flac"
    assert "Music\\Dom Dolla\\Rhyme Dust.flac" in (
        table.item(0, filename_col).toolTip()
    )
    assert table.item(0, filename_col).data(BADGE_ROLE) is None
    assert table.item(1, filename_col).data(BADGE_ROLE) == "Locked"
    assert table.item(0, quality_col).text() == "FLAC"
    assert table.item(1, quality_col).text() == "MP3, 320 kbps"


def test_search_quality_sorts_lossless_above_any_bitrate(qtbot):
    from PySide6.QtCore import Qt

    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._search_page
    page._render_search_results("Dom Dolla", "Rhyme Dust", [
        _peer_file(username="lossless"),
        _peer_file(
            username="mp3_320", filename="a.mp3", extension="mp3",
            bit_rate=320,
        ),
        _peer_file(
            username="mp3_96", filename="b.mp3", extension="mp3", bit_rate=96,
        ),
    ])
    table = page.search_results_table

    table.sortItems(
        _search_column(window, "Quality"), Qt.SortOrder.AscendingOrder,
    )

    peer_col = _search_column(window, "Peer")
    assert [table.item(row, peer_col).text() for row in range(3)] == [
        "mp3_96", "mp3_320", "lossless",
    ]


def test_return_in_a_field_searches(qtbot):
    from PySide6.QtCore import Qt

    application = FakeApplication()
    application.download_service._search_manual_results = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._search_page
    page.search_artist_edit.setText("Dom Dolla")
    page.search_title_edit.setText("Rhyme Dust")

    qtbot.keyClick(page.search_title_edit, Qt.Key.Key_Return)

    qtbot.waitUntil(
        lambda: bool(application.download_service.search_manual_calls),
        timeout=2000,
    )
    assert application.download_service.search_manual_calls == [
        ("Dom Dolla", "Rhyme Dust"),
    ]


def test_return_while_a_search_runs_does_not_start_another(qtbot):
    from PySide6.QtCore import Qt

    application = FakeApplication()
    application.download_service._search_manual_results = []
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._search_page
    page.search_artist_edit.setText("Dom Dolla")
    page.search_title_edit.setText("Rhyme Dust")
    window.busy_actions.begin("search_manual", page.search_button, None)

    qtbot.keyClick(page.search_title_edit, Qt.Key.Key_Return)
    qtbot.wait(50)

    assert application.download_service.search_manual_calls == []


def test_a_failed_search_reports_on_the_notice(qtbot):
    application = FakeApplication()
    application.download_service._search_manual_error = RuntimeError(
        "SoulSeek search failed."
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._search_page
    page.search_artist_edit.setText("Dom Dolla")
    page.search_title_edit.setText("Rhyme Dust")

    page._on_search_clicked()

    qtbot.waitUntil(
        lambda: "SoulSeek search failed" in page.notice.text(), timeout=2000,
    )

"""Tests for the Search page (seeker.ui.pages.search_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.2) — the
mirror of §9.3.1's own Search extraction (S6).
"""

from PySide6.QtWidgets import QPushButton

from seeker.ui import help_text
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication


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
    assert help_text.SEARCH_EMPTY_FIELDS_MESSAGE in (
        window._search_page.search_status_label.text()
    )


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

    username_col = _search_column(window, "Username")
    results_table = window._search_page.search_results_table
    # flac (lossless) outranks mp3 regardless of search result order.
    assert results_table.item(0, username_col).text() == "peer1"
    assert results_table.item(1, username_col).text() == "peer2"
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

    status_label = window._search_page.search_status_label
    qtbot.waitUntil(lambda: status_label.text() != "", timeout=2000)
    assert help_text.SEARCH_NO_RESULTS_MESSAGE in status_label.text()
    assert not window._search_page.download_best_button.isEnabled()


def test_search_download_best_passes_the_already_fetched_results(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_result = {
        "requested": True, "settled": True,
        "username": "peer1", "filename": "Dom Dolla - Rhyme Dust.flac",
    }
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
    assert "Requested from peer1" in window._search_page.search_status_label.text()


def test_search_download_this_one_passes_the_explicit_pick(qtbot):
    from seeker.models.soulseek_file import SoulseekFile

    file = SoulseekFile(
        username="peer1", filename="Dom Dolla - Rhyme Dust.flac",
        extension="flac", size=25_000_000, queue_length=0,
        upload_speed=1_000_000, has_free_upload_slot=True,
    )
    application = FakeApplication()
    application.download_service._search_manual_results = [file]
    application.download_service._download_manual_result = {
        "requested": True, "settled": True,
        "username": "peer1", "filename": "Dom Dolla - Rhyme Dust.flac",
    }
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
        lambda: "Settings" in window._search_page.search_status_label.text(),
        timeout=2000,
    )

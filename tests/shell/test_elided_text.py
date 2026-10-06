"""Long text elides on one line, and its full text is a hover away:
the playlist lists never scroll sideways, a table cell never wraps,
and a path keeps its filename."""
from PySide6.QtCore import QEvent, QModelIndex, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
)

from fakes import FakeApplication, make_duplicate_group
from seeker.models.playlist import Playlist
from seeker.ui import theme
from seeker.ui.main_window import MainWindow

# Wider than any of the three lists at 960 wide, Library's included.
_LONG_NAME = (
    "Warehouse Anthems for the Last Hour of a Very Long Night, Volume "
    "Two: Extended Edits, Dubs and Unreleased Versions (2026 Remaster)"
)


def _tooltip_at(view: QAbstractItemView, index: QModelIndex) -> str:
    QToolTip.hideText()
    position = view.visualRect(index).center()
    event = QHelpEvent(
        QEvent.Type.ToolTip, position, view.viewport().mapToGlobal(position),
    )
    QApplication.sendEvent(view.viewport(), event)
    return QToolTip.text() if QToolTip.isVisible() else ""


def _assert_elides(widget_list: QListWidget, qtbot) -> None:
    qtbot.waitUntil(widget_list.isVisible)
    index = widget_list.model().index(0, 0)
    assert widget_list.horizontalScrollBar().isVisible() is False
    assert (
        widget_list.visualRect(index).width()
        <= widget_list.viewport().width()
    )
    assert _LONG_NAME in _tooltip_at(widget_list, index)


def _window(qtbot) -> MainWindow:
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    window.resize(960, 640)
    window.show()
    return window


def test_the_dashboard_playlist_list_elides_a_long_name(qtbot):
    window = _window(qtbot)
    page = window._dashboard_page
    page._populate_playlists([Playlist("p1", _LONG_NAME, 12)])

    _assert_elides(page.playlist_list, qtbot)


def test_the_library_playlist_picker_elides_a_long_name(qtbot):
    window = _window(qtbot)
    window._show_page("library")
    page = window._library_page
    page._populate_playlist_picker([Playlist("p1", _LONG_NAME, 12)])
    page._playlist_picker.show()

    _assert_elides(page._playlist_picker, qtbot)


def test_the_settings_destination_list_elides_a_long_name(qtbot):
    window = _window(qtbot)
    window._show_page("settings")
    settings = window.settings_page
    settings.tabs.setCurrentIndex(1)
    settings._render_destinations(([Playlist("p1", _LONG_NAME, 12)], []))

    _assert_elides(settings.destinations_playlist_list, qtbot)


def _table(qtbot, text: str) -> QTableWidget:
    table = QTableWidget(1, 2)
    qtbot.addWidget(table)
    table.setHorizontalHeaderLabels(["Track", "Status"])
    table.setItem(0, 0, QTableWidgetItem(text))
    table.setItem(0, 1, QTableWidgetItem("Queued"))
    theme.apply_table_defaults(table)
    theme.configure_columns(
        table, theme.ColumnLayout(stretch=(0,), fit_content=(1,)),
    )
    table.resize(400, 120)
    table.show()
    qtbot.waitUntil(table.isVisible)
    return table


def test_a_table_cell_stays_on_one_line_and_hovers_its_full_text(qtbot):
    table = _table(qtbot, _LONG_NAME)

    assert table.wordWrap() is False
    assert _LONG_NAME in _tooltip_at(table, table.model().index(0, 0))


def test_a_cell_that_fits_has_no_tooltip(qtbot):
    table = _table(qtbot, "Nova Reyes")

    assert _tooltip_at(table, table.model().index(0, 0)) == ""


def test_a_cell_keeps_the_tooltip_it_already_has(qtbot):
    table = _table(qtbot, _LONG_NAME)
    table.item(0, 0).setToolTip("Its own explanation")

    assert (
        _tooltip_at(table, table.model().index(0, 0))
        == "Its own explanation"
    )


def test_a_duplicates_path_elides_in_the_middle_and_keeps_its_filename(
        qtbot,
):
    window = _window(qtbot)
    window._show_page("duplicates")
    page = window._duplicates_page
    page._render_duplicate_groups([make_duplicate_group()])
    table = page.duplicates_table
    index = table.model().index(0, 2)

    delegate = table.itemDelegateForIndex(index)
    assert delegate.elide_mode(index) == Qt.TextElideMode.ElideMiddle
    assert (
        delegate.elide_mode(table.model().index(0, 1))
        == Qt.TextElideMode.ElideRight
    )

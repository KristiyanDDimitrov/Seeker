"""Long text elides on one line, and its full text is a hover away:
the playlist lists never scroll sideways, a table cell never wraps,
and a path keeps its filename."""
import pytest
from PySide6.QtCore import QEvent, QModelIndex, Qt
from PySide6.QtGui import QColor, QHelpEvent
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
from seeker.ui.settings_window import SETTINGS_TAB_LIBRARY

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
    settings.select_tab(SETTINGS_TAB_LIBRARY)
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


def test_a_badge_takes_its_width_from_the_text(qtbot):
    from seeker.ui.elided_text import BADGE_ROLE

    table = QTableWidget(1, 1)
    theme.apply_table_defaults(table)
    qtbot.addWidget(table)
    text = "Nova Reyes - Voltage Drop"
    item = QTableWidgetItem(text)
    table.setItem(0, 0, item)
    table.resize(400, 120)
    table.show()
    qtbot.waitExposed(table)
    index = table.model().index(0, 0)
    # Just wide enough for the text alone.
    table.setColumnWidth(
        0, table.fontMetrics().horizontalAdvance(text) + 24,
    )
    assert _tooltip_at(table, index) == ""

    item.setData(BADGE_ROLE, "Upgrade")

    assert text in _tooltip_at(table, index)
    assert table.sizeHintForColumn(0) > (
        table.fontMetrics().horizontalAdvance(text) + 24
    )


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT])
def test_secondary_text_reads_on_every_row_ground(palette):
    from seeker.ui.elided_text import secondary_text_color

    for ground in (
            palette.BG_SURFACE, palette.BG_SURFACE_2, palette.ACCENT_SUBTLE,
    ):
        color = secondary_text_color(QColor(palette.TEXT), QColor(ground))
        assert theme.contrast_ratio(color.name(), ground) >= 4.5
        # Still visibly quieter than the primary text.
        assert theme.contrast_ratio(color.name(), ground) < (
            theme.contrast_ratio(palette.TEXT, ground)
        )


def test_secondary_text_takes_width_and_joins_the_hover(qtbot):
    from seeker.ui.elided_text import SECONDARY_ROLE

    text = "Nova Reyes - Voltage Drop.flac"
    table = _table(qtbot, text)
    index = table.model().index(0, 0)
    table.setColumnWidth(
        0, table.fontMetrics().horizontalAdvance(text) + 24,
    )
    assert _tooltip_at(table, index) == ""

    table.item(0, 0).setData(SECONDARY_ROLE, "FLAC, 1411kbps from nova_fan")

    hover = _tooltip_at(table, index)
    assert text in hover
    assert "FLAC, 1411kbps from nova_fan" in hover
    assert table.sizeHintForColumn(0) > (
        table.fontMetrics().horizontalAdvance(text) + 24
    )


def test_a_cells_icon_counts_against_the_primary_text(qtbot):
    # A status lamp sits before the text. Secondary text may take only
    # what the icon and the primary text leave, or the primary text
    # elides while the secondary still has room to give.
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QStyleOptionViewItem

    from seeker.ui import status_lamp
    from seeker.ui.elided_text import SECONDARY_ROLE, _secondary_share

    text = "Needs review"
    table = _table(qtbot, "Nova Reyes - Voltage Drop")
    item = table.item(0, 1)
    item.setText(text)
    item.setData(SECONDARY_ROLE, "SoulSeek candidate found")
    item.setIcon(
        status_lamp.lamp_icon(status_lamp.CUE_WAITING, theme.DARK),
    )
    size = status_lamp.LAMP_SIZE
    table.setIconSize(QSize(size, size))
    table.setColumnWidth(1, table.fontMetrics().horizontalAdvance(text) + 140)
    index = table.model().index(0, 1)
    delegate = table.itemDelegate()
    option = QStyleOptionViewItem()
    option.rect = table.visualRect(index)
    option.widget = table
    option.font = table.font()
    option.fontMetrics = table.fontMetrics()
    option.decorationSize = table.iconSize()
    delegate.initStyleOption(option, index)
    style = table.style()
    text_left = style.subElementRect(
        style.SubElement.SE_ItemViewItemText, option, table,
    ).left()

    taken = _secondary_share(option, index)

    primary_right = text_left + table.fontMetrics().horizontalAdvance(text)
    assert option.rect.right() - taken >= primary_right


def test_secondary_text_with_room_is_painted_whole(qtbot):
    # What the secondary text asks for must cover the gap and margin
    # its paint area leaves out, or a short "65%" elides to "6…" in a
    # cell with room to spare.
    from PySide6.QtWidgets import QStyleOptionViewItem

    from seeker.ui.elided_text import (
        SECONDARY_ROLE,
        _secondary_area,
        _secondary_share,
    )

    table = _table(qtbot, "Nova Reyes - Voltage Drop")
    table.item(0, 1).setText("Downloading")
    table.item(0, 1).setData(SECONDARY_ROLE, "65%")
    table.setColumnWidth(1, 300)
    index = table.model().index(0, 1)
    option = QStyleOptionViewItem()
    option.rect = table.visualRect(index)
    option.widget = table
    option.font = table.font()
    option.fontMetrics = table.fontMetrics()
    table.itemDelegate().initStyleOption(option, index)

    area = _secondary_area(option, _secondary_share(option, index))

    assert area.width() >= table.fontMetrics().horizontalAdvance("65%")

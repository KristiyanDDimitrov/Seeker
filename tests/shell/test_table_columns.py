"""Column policy, checked on every screen the screenshot harness
renders, at the app's 960x640 minimum where a squeeze shows first: the
primary text column keeps a readable width, no table scrolls sideways,
and every header aligns with its own column's text."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QWidget

from seeker.ui import theme
from seeker.ui.main_window import MainWindow

_SIZE = (960, 640)
# The column each table's rows are about. A table whose headers name
# none of these fails the walk below, so a new table has to say which
# of its columns is primary.
_PRIMARY_HEADERS = frozenset(
    {"Track", "Filename", "Path", "File", "Container Path"},
)
# Narrow enough that the Dashboard's track table, the narrowest in the
# app at 960 wide, can still hold it next to Status/Progress/Actions.
_PRIMARY_FLOOR = 160


def _horizontal(alignment: Qt.AlignmentFlag) -> Qt.AlignmentFlag:
    return alignment & Qt.AlignmentFlag.AlignHorizontal_Mask


def _misfits(screen: str, root: QWidget) -> list[str]:
    found = []
    for table in root.findChildren(QTableWidget):
        # A table on a page that is not showing has no laid-out width.
        # Every table is visible on at least one screen of the walk.
        if not table.isVisible():
            continue
        headers = [
            table.horizontalHeaderItem(column).text()
            for column in range(table.columnCount())
        ]
        name = f"{screen}: {'/'.join(headers)}"
        primary = [
            column for column, text in enumerate(headers)
            if text in _PRIMARY_HEADERS
        ]
        if not primary:
            found.append(f"{name}: no primary column in {headers}")
            continue
        header = table.horizontalHeader()
        for column in primary:
            width = header.sectionSize(column)
            if width < _PRIMARY_FLOOR:
                found.append(
                    f"{name}: {headers[column]!r} is {width} px wide",
                )
        if table.horizontalScrollBar().isVisible():
            found.append(f"{name}: scrolls sideways")
        if table.rowCount() == 0:
            continue
        for column in range(table.columnCount()):
            item = table.item(0, column)
            # A column of cell widgets has no text to align with.
            if item is None or not item.text():
                continue
            header_item = table.horizontalHeaderItem(column)
            header_alignment = _horizontal(
                Qt.AlignmentFlag(header_item.textAlignment())
                or header.defaultAlignment(),
            )
            cell_alignment = _horizontal(
                Qt.AlignmentFlag(item.textAlignment())
                or Qt.AlignmentFlag.AlignLeft,
            )
            if header_alignment != cell_alignment:
                found.append(
                    f"{name}: {headers[column]!r} header is "
                    f"{header_alignment!r} over {cell_alignment!r} cells",
                )
    return found


@pytest.fixture
def _restore_theme(qapp):
    yield
    theme.apply_theme(qapp)


@pytest.mark.usefixtures("_restore_theme")
def test_every_table_keeps_its_primary_column_readable(qapp, screenshots):
    misfits: list[str] = []

    application = screenshots.build_demo_application()
    theme.apply_theme(qapp, "dark")
    window = MainWindow(application)
    try:
        window.resize(*_SIZE)
        window.show()
        screenshots.settle(qapp, window, 1.0)
        for screen in screenshots.SCREENS:
            for step in screen.steps:
                step(window)
                screenshots.settle(qapp, window)
            misfits += _misfits(screen.name, window)
    finally:
        screenshots.close(qapp, window)

    assert misfits == [], "\n".join(misfits)

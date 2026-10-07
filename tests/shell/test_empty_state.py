"""An empty table says why it is empty and what to do next: one
sentence, a glyph, and an optional action, over the table's own
viewport so its headers stay in place."""
import pytest
from PySide6.QtWidgets import QPushButton, QTableWidget, QVBoxLayout, QWidget

from seeker.ui.empty_state import EmptyGlyph, EmptyState


def _table_in_window(qtbot, height: int = 300) -> tuple[QWidget, QTableWidget]:
    window = QWidget()
    layout = QVBoxLayout(window)
    table = QTableWidget(0, 3)
    layout.addWidget(table)
    qtbot.addWidget(window)
    window.resize(600, height)
    window.show()
    qtbot.waitExposed(window)
    return window, table


def test_shows_over_an_empty_table_and_hides_once_rows_arrive(qtbot):
    _, table = _table_in_window(qtbot)
    empty = EmptyState(table, EmptyGlyph.RECORD, "Nothing here yet.")

    assert empty.isVisible()
    assert empty.parent() is table.viewport()

    table.setRowCount(2)
    assert not empty.isVisible()

    table.setRowCount(0)
    assert empty.isVisible()


def test_covers_the_viewport_as_the_table_resizes(qtbot):
    window, table = _table_in_window(qtbot)
    empty = EmptyState(table, EmptyGlyph.SEARCH, "Search above.")

    window.resize(800, 420)
    qtbot.waitUntil(lambda: empty.size() == table.viewport().size())

    assert empty.geometry() == table.viewport().rect()


def test_set_text_changes_the_sentence(qtbot):
    _, table = _table_in_window(qtbot)
    empty = EmptyState(table, EmptyGlyph.DONE, "First.")

    empty.set_text("Second.")

    assert empty.text() == "Second."


def test_the_action_takes_its_size_hint_and_is_clickable(qtbot):
    _, table = _table_in_window(qtbot)
    clicks: list[bool] = []
    button = QPushButton("Go to Dashboard")
    button.clicked.connect(lambda: clicks.append(True))
    EmptyState(table, EmptyGlyph.RECORD, "Nothing yet.", action=button)
    qtbot.waitUntil(button.isVisible)

    assert button.width() <= button.sizeHint().width() + 2
    button.click()
    assert clicks == [True]


def test_a_short_table_drops_the_glyph_and_keeps_the_sentence(qtbot):
    _, table = _table_in_window(qtbot, height=90)
    empty = EmptyState(table, EmptyGlyph.SHARE, "No one is downloading.")

    qtbot.waitUntil(lambda: empty.size() == table.viewport().size())

    assert not empty.glyph.isVisible()
    assert empty.label.isVisible()


@pytest.mark.parametrize("glyph", list(EmptyGlyph))
def test_every_glyph_paints(qtbot, glyph):
    _, table = _table_in_window(qtbot)
    empty = EmptyState(table, glyph, "Text.")
    qtbot.waitUntil(empty.glyph.isVisible)

    image = empty.glyph.grab().toImage()
    colors = {
        image.pixel(x, y)
        for x in range(0, image.width(), 2)
        for y in range(0, image.height(), 2)
    }

    assert len(colors) > 1

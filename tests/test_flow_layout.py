from PySide6.QtWidgets import QPushButton, QWidget

from seeker.ui.flow_layout import FlowLayout


def _build(qtbot, texts: list[str]) -> tuple[QWidget, FlowLayout]:
    container = QWidget()
    qtbot.addWidget(container)
    layout = FlowLayout(container)
    for text in texts:
        layout.addWidget(QPushButton(text))
    return container, layout


def test_minimum_size_is_widest_item_not_the_sum(qtbot):
    _, layout = _build(
        qtbot,
        ["short", "a much much much longer button label than the rest"],
    )
    widths = [layout.itemAt(i).sizeHint().width() for i in range(layout.count())]

    assert layout.minimumSize().width() < sum(widths)
    assert layout.minimumSize().width() >= max(widths)


def test_has_height_for_width(qtbot):
    _, layout = _build(qtbot, ["a", "b", "c"])
    assert layout.hasHeightForWidth() is True


def test_height_for_width_grows_as_available_width_shrinks(qtbot):
    _, layout = _build(
        qtbot, [f"Button {i}" for i in range(8)],
    )

    wide = layout.heightForWidth(2000)
    narrow = layout.heightForWidth(150)

    assert narrow > wide


def test_take_at_and_count(qtbot):
    _, layout = _build(qtbot, ["a", "b"])
    assert layout.count() == 2

    item = layout.takeAt(0)
    assert item is not None
    assert layout.count() == 1
    assert layout.takeAt(5) is None


def test_item_at_out_of_range_returns_none(qtbot):
    _, layout = _build(qtbot, ["a"])
    assert layout.itemAt(1) is None
    assert layout.itemAt(-1) is None

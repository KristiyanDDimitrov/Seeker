from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QPushButton, QTableWidget

from seeker.ui import theme


def test_make_card_wraps_inner_in_a_card_frame(qtbot):
    table = QTableWidget(0, 1)
    card = theme.make_card(table)
    qtbot.addWidget(card)

    assert isinstance(card, QFrame)
    assert card.objectName() == "card"
    assert table.parentWidget() is card


def test_make_card_turns_off_the_inner_widgets_own_border(qtbot):
    # Roadmap item 80 (P10.1) — the frame owns the real rounded border;
    # `inner` must have its own turned off, or the same corner-cutting
    # defect just moves one level in (see make_card's own docstring).
    table = QTableWidget(0, 1)
    card = theme.make_card(table)
    qtbot.addWidget(card)

    style = table.styleSheet()
    assert "border: none" in style
    assert "border-radius: 0px" in style


def test_make_card_leaves_a_real_margin_between_inner_and_the_frame(qtbot):
    # The margin is the load-bearing part of the whole fix — with zero
    # margin, an edge-reaching child of `inner` could still paint over
    # the frame's own rounded corner.
    listw = QListWidget()
    card = theme.make_card(listw)
    qtbot.addWidget(card)
    card.resize(200, 200)
    card.show()
    qtbot.waitExposed(card)

    margins = card.layout().contentsMargins()
    assert margins.left() > 0
    assert margins.top() > 0
    assert margins.right() > 0
    assert margins.bottom() > 0


def test_cell_widget_packs_widgets_with_a_real_gap(qtbot):
    button_a = QPushButton("A")
    button_b = QPushButton("B")
    container = theme.cell_widget(button_a, button_b)
    qtbot.addWidget(container)
    container.resize(400, 40)
    container.show()
    qtbot.waitExposed(container)

    assert button_b.x() - (button_a.x() + button_a.width()) >= theme.SPACING_SM


def test_cell_widget_does_not_stretch_a_lone_widget_to_fill_the_container(qtbot):
    # Roadmap item 80 (P10.3) — the brief's own named example: a bare
    # setCellWidget(button) gets resized to the whole cell rect by Qt.
    # cell_widget()'s trailing stretch must absorb that leftover space
    # instead of the button itself.
    button = QPushButton("Add to my SoulSeek share")
    container = theme.cell_widget(button)
    qtbot.addWidget(container)
    container.resize(800, 40)
    container.show()
    qtbot.waitExposed(container)

    assert button.width() <= button.sizeHint().width() + 2
    assert button.width() < container.width() / 2


def test_cell_widget_single_label_matches_existing_shared_state_pattern(qtbot):
    label = QLabel("Shared")
    container = theme.cell_widget(label)
    qtbot.addWidget(container)

    assert label.parentWidget() is container


def test_header_section_has_a_right_hand_divider():
    # Roadmap item 97 (B2.4) — a real regression from item 47:
    # QHeaderView::section's own `border: none` removed the native
    # left/right divider between column headers with no fallback
    # underneath (once ANY QHeaderView::section rule exists, Qt paints
    # the header entirely from that box model). A weak test — it can't
    # see a real pixel — but it pins the exact property whose removal
    # caused this, which is more than existed before.
    assert "border-right: 1px solid" in theme.STYLESHEET

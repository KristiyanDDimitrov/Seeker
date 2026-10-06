import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

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
    #
    # Roadmap item E3 (round 7) — this used to be a per-widget
    # `inner.setStyleSheet("border: none; border-radius: 0px;")`, which
    # Qt parses as a universal `* {...}` rule cascading onto every
    # descendant (found live stripping a QProgressBar's own border
    # inside a card). Scoped via objectName + a real `#cardInner`
    # selector in the app-wide stylesheet instead — checked here via the
    # objectName and the global stylesheet text, not a per-widget one
    # (`table.styleSheet()` is correctly empty now).
    table = QTableWidget(0, 1)
    card = theme.make_card(table)
    qtbot.addWidget(card)

    assert table.styleSheet() == ""
    assert table.objectName() == "cardInner"

    stylesheet = theme.build_stylesheet(theme.DARK)
    assert "#cardInner" in stylesheet
    assert "border: none" in stylesheet
    assert "border-radius: 0px" in stylesheet


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


def test_cell_widget_does_not_stretch_a_lone_widget_to_fill_the_container(
        qtbot
):
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


def test_cell_widget_button_does_not_steal_tab_focus_when_disabled(qtbot):
    # §1.1 — a real click gives the button keyboard focus; disabling it
    # the way run_worker does (workers.py) then makes Qt synthesize a
    # Tab press on its behalf, walking the current cell one column to
    # the right. Confirm's "does nothing but the highlight moves" bug
    # was exactly this. cell_widget() must set NoFocus on every button
    # it wraps so a click never grants focus in the first place.
    table = QTableWidget(1, 3)
    table.setItem(0, 0, QTableWidgetItem("track"))
    table.setItem(0, 1, QTableWidgetItem("score"))
    button = QPushButton("Confirm")
    table.setCellWidget(0, 2, theme.cell_widget(button))
    qtbot.addWidget(table)
    table.resize(400, 100)
    table.show()
    qtbot.waitExposed(table)

    table.setCurrentCell(0, 0)
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    button.setEnabled(False)

    assert table.currentColumn() == 0


def test_actions_column_click_never_sorts_and_shows_no_indicator(qtbot):
    # §5.2 — a click on an Actions column header must neither sort by
    # it nor leave the indicator sitting on it; a real click, not a
    # manually emitted signal, since Qt's own indicator flip + re-sort
    # happens inside header mouse handling itself, before
    # sectionClicked is even emitted.
    table = QTableWidget(3, 2)
    qtbot.addWidget(table)
    table.setHorizontalHeaderLabels(["Name", "Actions"])
    table.setItem(0, 0, QTableWidgetItem("b"))
    table.setItem(1, 0, QTableWidgetItem("a"))
    table.setItem(2, 0, QTableWidgetItem("c"))
    theme.apply_table_defaults(table)
    theme.configure_columns(
        table, theme.ColumnLayout(stretch=(0,), fit_content=(), actions=1),
    )
    table.show()

    header = table.horizontalHeader()
    header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
    assert table.item(0, 0).text() == "a"

    section_center = QPoint(
        header.sectionViewportPosition(1) + header.sectionSize(1) // 2,
        header.height() // 2,
    )
    qtbot.mouseClick(header, Qt.MouseButton.LeftButton, pos=section_center)

    assert header.sortIndicatorSection() == 0
    assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
    assert table.item(0, 0).text() == "a"


def test_header_section_has_a_right_hand_divider():
    # Roadmap item 97 (B2.4) — a real regression from item 47:
    # QHeaderView::section's own `border: none` removed the native
    # left/right divider between column headers with no fallback
    # underneath (once ANY QHeaderView::section rule exists, Qt paints
    # the header entirely from that box model). A weak test — it can't
    # see a real pixel, and item 103 (C1) found live that this exact
    # property being PRESENT in the string is no guarantee it actually
    # PAINTS (an invalid neighboring selector silently poisoned the
    # whole rule for two rounds while this string check kept passing).
    # The real verification is test_downloads_page.py's own real
    # window.grab() pixel scan
    # (test_downloads_header_shows_a_real_divider_between_columns) —
    # kept here too only as a cheap sanity pin on the property itself.
    assert "border-right: 1px solid" in theme.build_stylesheet(theme.DARK)


# --- Roadmap item C5.8 (round 5) — "make the contrast a test, not a
# claim." A real WCAG relative-luminance/contrast-ratio implementation,
# verified against known reference values, then used to assert real
# floors on both palettes so a future palette change that regresses
# accessibility fails CI instead of shipping. ---------------------------

def test_contrast_ratio_matches_known_reference_values():
    # Textbook cases, not this project's own colors — proves the
    # formula itself is correct before trusting it to grade a palette.
    assert theme.contrast_ratio(
            "#000000",
            "#FFFFFF",
    ) == pytest.approx(21.0, abs=0.01)
    assert theme.contrast_ratio(
            "#FFFFFF",
            "#000000",
    ) == pytest.approx(21.0, abs=0.01)
    assert theme.contrast_ratio(
            "#808080",
            "#808080",
    ) == pytest.approx(1.0, abs=0.01)
    # A widely-cited reference pair (WCAG's own worked examples use
    # #767676 on white as landing almost exactly at the AA text floor).
    assert theme.contrast_ratio(
            "#767676",
            "#FFFFFF",
    ) == pytest.approx(4.54, abs=0.01)


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_body_text_meets_the_aa_floor_on_its_own_background(palette):
    assert theme.contrast_ratio(palette.TEXT, palette.BG_SURFACE) >= 4.5
    assert theme.contrast_ratio(palette.TEXT, palette.BG_APP) >= 4.5


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_faint_text_and_borders_meet_the_decorative_floor(palette):
    # TEXT_FAINT is deliberately right at the edge (it's decorative, not
    # load-bearing text) — both palettes were designed to that same
    # ~3:1 floor, not a coincidence.
    assert theme.contrast_ratio(palette.TEXT_FAINT, palette.BG_SURFACE) >= 3.0
    assert theme.contrast_ratio(palette.BORDER, palette.BG_SURFACE) >= 1.0
    assert theme.contrast_ratio(
            palette.BORDER_STRONG,
            palette.BG_SURFACE,
    ) >= 1.9


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_progress_bar_percentage_text_reads_on_both_its_backgrounds(palette):
    # Roadmap item C5 (round 5) — found live via a real screenshot: the
    # percentage label spans the ACCENT fill AND the plain
    # BG_SURFACE_2 track at once. TEXT_MUTED (the original color) was
    # only 1.26:1 against ACCENT in light — a real crop showed it
    # nearly invisible. TEXT (the fix) must clear the 3:1 UI-component
    # floor against BOTH.
    assert theme.contrast_ratio(palette.TEXT, palette.ACCENT) >= 3.0
    assert theme.contrast_ratio(palette.TEXT, palette.BG_SURFACE_2) >= 3.0


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_on_accent_text_meets_the_ui_component_floor(palette):
    # Roadmap item C5.8 — found live building this exact test: the
    # QSS used to put plain `TEXT` on top of a saturated ACCENT/DANGER
    # fill (QPushButton[variant="primary"], the danger button's hover
    # state) — fine in dark (TEXT is near-white) but wrong in light
    # (TEXT is near-BLACK, dark text on a purple button). Fixed with a
    # dedicated `ON_ACCENT` token (white in both palettes), asserted
    # here against BOTH saturated fills it's actually used on. 3:1 is
    # WCAG's own floor for large-scale/UI-component text, the correct
    # standard for a short bold button label rather than the stricter
    # 4.5:1 body-text floor — DARK's own real number here (verified,
    # not the brief's originally-claimed one) is 4.35:1 for ACCENT and
    # 3.91:1 for DANGER, both real but short of 4.5.
    assert theme.contrast_ratio(palette.ON_ACCENT, palette.ACCENT) >= 3.0
    assert theme.contrast_ratio(palette.ON_ACCENT, palette.DANGER) >= 3.0


# --- Backgrounds: only real surfaces paint one (§27.1) ----------------------


@pytest.fixture(params=["dark", "light"])
def applied_palette(request, qapp):
    palette = theme.apply_theme(qapp, request.param)
    yield palette
    theme.apply_theme(qapp)


def _rgb(image, point: QPoint) -> tuple[int, int, int]:
    color = image.pixelColor(point)
    return color.red(), color.green(), color.blue()


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _grab_card(qtbot, inner):
    card = theme.make_card(inner)
    qtbot.addWidget(card)
    card.resize(640, 240)
    card.show()
    qtbot.waitExposed(card)
    image = card.grab().toImage()
    dpr = image.width() / card.width()

    def at(widget, point: QPoint) -> tuple[int, int, int]:
        mapped = widget.mapTo(card, point)
        return _rgb(image, QPoint(round(mapped.x() * dpr),
                                  round(mapped.y() * dpr)))

    return at


def test_a_cell_widget_paints_the_rows_own_background(
        qtbot, applied_palette,
):
    # A progress cell, a checkbox cell and a radio cell, next to a
    # plain item: each container's empty corner is the row's pixel.
    table = QTableWidget(1, 4)
    table.setItem(0, 0, QTableWidgetItem("Nova Reyes - Voltage Drop"))
    bar = QProgressBar()
    bar.setValue(50)
    table.setCellWidget(0, 1, theme.wrap_progress_bar(bar, None))
    checkbox = QCheckBox("Keep all")
    table.setCellWidget(0, 2, theme.cell_widget(checkbox))
    radio = QRadioButton("Keep")
    table.setCellWidget(0, 3, theme.cell_widget(radio))
    for column in range(4):
        table.setColumnWidth(column, 150)
    table.setRowHeight(0, 40)
    at = _grab_card(qtbot, table)

    viewport = table.viewport()
    item_rect = table.visualRect(table.model().index(0, 0))
    row_pixel = at(viewport, item_rect.topRight() + QPoint(-3, 3))

    for column in (1, 2, 3):
        container = table.cellWidget(0, column)
        corner = container.rect().topRight() + QPoint(-2, 2)
        assert at(container, corner) == row_pixel, f"column {column}"
    for control in (checkbox, radio):
        corner = control.rect().topRight() + QPoint(-1, 1)
        assert at(control, corner) == row_pixel, type(control).__name__


def test_controls_on_a_card_show_the_card_surface(qtbot, applied_palette):
    # A Settings-style form: a plain QWidget holding a checkbox and a
    # radio row on a card. Nothing between them and the card paints.
    form = QWidget()
    layout = QVBoxLayout(form)
    checkbox = QCheckBox("Subfolder per playlist")
    radio = QRadioButton("Dark")
    layout.addWidget(checkbox)
    layout.addWidget(radio)
    layout.addStretch()
    at = _grab_card(qtbot, form)

    surface = _hex_rgb(applied_palette.BG_SURFACE)
    assert at(form, form.rect().bottomRight() + QPoint(-2, -2)) == surface
    for control in (checkbox, radio):
        corner = control.rect().topRight() + QPoint(-1, 1)
        assert at(control, corner) == surface, type(control).__name__


# --- Combo boxes show a drop-down chevron (§27.2) ---------------------------


def test_a_combo_box_shows_a_chevron_in_its_drop_down(
        qtbot, applied_palette,
):
    # A combo with no arrow reads as a text field. Somewhere in the
    # drop-down band (the right-hand 24 px, inside the border) a pixel
    # reaches the 3:1 UI-component floor against the field itself.
    combo = QComboBox()
    combo.addItems(["All locations", "Music"])
    form = QWidget()
    layout = QVBoxLayout(form)
    layout.addWidget(combo)
    layout.addStretch()
    at = _grab_card(qtbot, form)

    field = at(combo, QPoint(6, combo.height() // 2))
    band = [
        at(combo, QPoint(x, y))
        for x in range(combo.width() - 24, combo.width() - 3)
        for y in range(3, combo.height() - 3)
    ]
    field_hex = "#{:02X}{:02X}{:02X}".format(*field)
    best = max(
        theme.contrast_ratio("#{:02X}{:02X}{:02X}".format(*pixel), field_hex)
        for pixel in band
    )
    assert best >= 3.0


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_the_combo_chevron_is_drawn_in_the_palettes_muted_text(palette):
    path = theme.combo_chevron_path(palette)
    assert path.is_file()
    assert f'stroke="{palette.TEXT_MUTED}"' in path.read_text()
    assert path.as_posix() in theme.build_stylesheet(palette)

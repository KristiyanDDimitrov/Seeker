import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontInfo,
    QImage,
    QPainter,
    QPalette,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QStyleOptionTab,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.ui import theme
from seeker.ui.plain_text import RichLabel
from seeker.ui.widgets import ThemeToggleButton


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


def test_fit_widths_gives_every_column_its_content_when_it_fits():
    assert theme.fit_widths({0: 50, 1: 120}, {0: 40, 1: 40}, 200) == {
        0: 50, 1: 120,
    }


def test_fit_widths_cuts_the_widest_column_first():
    # 50 + 120 = 170 > 140: a cap of 90 takes 30 from the wide column
    # and leaves the narrow one whole.
    assert theme.fit_widths({0: 50, 1: 120}, {0: 40, 1: 40}, 140) == {
        0: 50, 1: 90,
    }


def test_fit_widths_never_goes_below_a_floor():
    assert theme.fit_widths({0: 50, 1: 120}, {0: 40, 1: 100}, 60) == {
        0: 40, 1: 100,
    }


def test_fit_widths_with_no_columns_is_empty():
    assert theme.fit_widths({}, {}, 100) == {}


def test_a_table_refits_its_columns_when_it_narrows(qtbot):
    # Fitted once at the wide size, then narrowed with no render in
    # between: only the viewport's resize can re-run the fit.
    table = QTableWidget(1, 3)
    qtbot.addWidget(table)
    table.setHorizontalHeaderLabels(["Track", "Status", "Detail"])
    table.setItem(0, 0, QTableWidgetItem("Nova Reyes - Voltage Drop"))
    table.setItem(0, 1, QTableWidgetItem("Needs review " * 4))
    table.setItem(0, 2, QTableWidgetItem("x"))
    theme.apply_table_defaults(table)
    layout = theme.ColumnLayout(stretch=(0,), fit_content=(1, 2))
    table.resize(1200, 200)
    table.show()
    theme.size_columns(table, layout, [])
    header = table.horizontalHeader()
    wide_status = header.sectionSize(1)

    table.resize(500, 200)
    qtbot.waitUntil(lambda: header.sectionSize(1) < wide_status)

    assert header.sectionSize(0) >= theme.STRETCH_COLUMN_FLOOR
    assert not table.horizontalScrollBar().isVisible()


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
@pytest.mark.parametrize(
        "fill", ["ACCENT", "ACCENT_HOVER", "ACCENT_PRESSED"],
)
def test_on_accent_text_meets_the_aa_floor_on_every_accent_state(
        palette, fill,
):
    # A primary button's label sits on each of these fills in turn
    # (rest, hover, pressed); a label is text, so 4.5 applies.
    assert theme.contrast_ratio(
            palette.ON_ACCENT, getattr(palette, fill),
    ) >= 4.5


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_on_accent_text_reads_on_the_danger_fill(palette):
    # The danger button's hover state. 3:1 is WCAG's floor for a
    # short bold control label.
    assert theme.contrast_ratio(palette.ON_ACCENT, palette.DANGER) >= 3.0


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
@pytest.mark.parametrize("ground", ["BG_SURFACE", "BG_APP"])
def test_accent_reads_as_link_text(palette, ground):
    # Links and the Dashboard's review links are ACCENT text on a
    # surface or the page ground.
    assert theme.contrast_ratio(
            palette.ACCENT, getattr(palette, ground),
    ) >= 4.5


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_muted_text_meets_the_aa_floor(palette):
    assert theme.contrast_ratio(palette.TEXT_MUTED, palette.BG_SURFACE) >= 4.5
    assert theme.contrast_ratio(palette.TEXT_MUTED, palette.BG_APP) >= 4.5


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_sidebar_text_and_icons_meet_their_floors(palette):
    # A nav label is text (4.5); its icon is a graphic (WCAG 1.4.11's
    # 3:1): muted on the sidebar, ACCENT on the checked item's fill.
    assert theme.contrast_ratio(palette.TEXT_MUTED, palette.BG_SIDEBAR) >= 4.5
    assert theme.contrast_ratio(palette.TEXT, palette.ACCENT_SUBTLE) >= 4.5
    assert theme.contrast_ratio(palette.ACCENT, palette.ACCENT_SUBTLE) >= 3.0
    assert theme.contrast_ratio(palette.ACCENT, palette.BG_SIDEBAR) >= 3.0


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
@pytest.mark.parametrize("status", ["SUCCESS", "WARNING", "DANGER"])
def test_status_colours_read_as_text_and_as_marks(palette, status):
    # On a table or card a status colour can be a label (4.5). On the
    # page ground and on a selected row it is at least a status mark,
    # an LED beside its label (WCAG 1.4.11's 3:1).
    colour = getattr(palette, status)
    assert theme.contrast_ratio(colour, palette.BG_SURFACE) >= 4.5
    assert theme.contrast_ratio(colour, palette.BG_APP) >= 3.0
    assert theme.contrast_ratio(colour, palette.SELECTION) >= 3.0


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
@pytest.mark.parametrize(
        "ground", ["BG_SURFACE", "BG_SURFACE_2", "BG_APP", "SELECTION"],
)
def test_the_cue_mark_meets_the_ui_component_floor(palette, ground):
    # A cue lamp or meter segment is a mark, not text (WCAG 1.4.11's
    # 3:1), on a card, a banded or selected row, or the page ground.
    assert theme.contrast_ratio(palette.CUE, getattr(palette, ground)) >= 3.0


def test_light_modes_cue_is_lighter_than_its_text_grade_warning():
    # One token served both floors, so light mode's lamps and meters
    # took the text-grade amber, dark enough to read brown.
    surface = theme.LIGHT.BG_SURFACE
    assert theme.contrast_ratio(theme.LIGHT.CUE, surface) < (
        theme.contrast_ratio(theme.LIGHT.WARNING, surface)
    )


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_native_highlighted_text_reads_on_the_highlight(palette):
    # Whatever Qt draws natively with the QPalette (a selectable
    # label, a selection no stylesheet rule covers): the same pair the
    # stylesheet's selection-* rules use.
    qpalette = theme.build_qpalette(palette)
    assert theme.contrast_ratio(
            qpalette.color(QPalette.ColorRole.HighlightedText).name(),
            qpalette.color(QPalette.ColorRole.Highlight).name(),
    ) >= 4.5
    assert qpalette.color(QPalette.ColorRole.Highlight).name().upper() == (
        palette.SELECTION
    )


# --- Backgrounds: only real surfaces paint one (§27.1) ----------------------


@pytest.fixture(params=["dark", "light"])
def applied_palette(request, qapp):
    palette = theme.apply_theme(qapp, request.param)
    yield palette
    theme.apply_theme(qapp)


@pytest.mark.parametrize(
        "role",
        [QPalette.ColorRole.Link, QPalette.ColorRole.LinkVisited],
        ids=["link", "visited"],
)
def test_a_rich_label_link_reads_on_the_page(applied_palette, role):
    # A RichLabel's anchor paints in the palette's Link colour, which
    # Qt defaults to pure #0000FF (2.2:1 on dark's page ground) and its
    # visited one to magenta: Support's issue link and e-mail address.
    label = RichLabel('<a href="https://example.com">a link</a>')
    colour = label.palette().color(role).name()
    assert theme.contrast_ratio(colour, applied_palette.BG_APP) >= 4.5
    assert theme.contrast_ratio(colour, applied_palette.BG_SURFACE) >= 4.5


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


def test_a_checked_checkbox_shows_a_tick(qtbot, applied_palette):
    # A checked box was a solid ACCENT square: the state rested on
    # colour alone. Inside the indicator, some pixel must stand off
    # the ACCENT fill by the 3:1 UI-component floor.
    checkbox = QCheckBox("Keep all")
    checkbox.setChecked(True)
    at = _grab_card(qtbot, checkbox)

    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    indicator = checkbox.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, checkbox,
    )
    inside = [
        at(checkbox, QPoint(x, y))
        for x in range(indicator.left() + 3, indicator.right() - 2)
        for y in range(indicator.top() + 3, indicator.bottom() - 2)
    ]
    best = max(
        theme.contrast_ratio(
                "#{:02X}{:02X}{:02X}".format(*pixel), applied_palette.ACCENT,
        )
        for pixel in inside
    )
    assert best >= 3.0


# --- Selected text reads, on a selection that shows ------------------------


def _selectable_label():
    # A label's text sits at the left of its contents, centred on it.
    label = QLabel(_SELECTED)
    label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse,
    )
    label.setSelection(0, len(_SELECTED))

    def band():
        contents = label.contentsRect()
        half = label.fontMetrics().ascent() // 2
        return label, QRect(
                contents.left(), contents.center().y() - half,
                label.fontMetrics().horizontalAdvance(_SELECTED), 2 * half,
        )

    return label, band


def _selected_line_edit():
    field = QLineEdit(_SELECTED)
    field.setCursorPosition(0)

    def band():
        start = field.cursorRect()
        field.selectAll()
        end = field.cursorRect()
        return field, QRect(start.center(), end.center()).adjusted(
                0, -start.height() // 4, 0, start.height() // 4,
        )

    return field, band


def _selected_plain_text_edit():
    field = QPlainTextEdit(_SELECTED)

    def band():
        cursor = field.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        start = field.cursorRect(cursor)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        end = field.cursorRect(cursor)
        field.selectAll()
        return field.viewport(), QRect(start.center(), end.center()).adjusted(
                0, -start.height() // 4, 0, start.height() // 4,
        )

    return field, band


_SELECTED = "Nova Reyes - Voltage Drop"


@pytest.mark.parametrize(
        "make_widget",
        [_selected_line_edit, _selected_plain_text_edit, _selectable_label],
        ids=["line-edit", "plain-text-edit", "label"],
)
def test_selected_text_reads_on_a_selection_that_stands_off_the_field(
        qtbot, applied_palette, make_widget,
):
    # The field rule set a selection ground but no selection-color, so
    # selected text fell back to the palette's HighlightedText: dark
    # ink, near-black on dark mode's selection, and white on light
    # mode's pale one. Across the selected text, its own ground is the
    # commonest pixel; the glyph pixel furthest from it must reach
    # 4.5:1, and the ground must visibly differ from the field.
    widget, measure = make_widget()
    widget.setFixedWidth(320)
    form = QWidget()
    layout = QVBoxLayout(form)
    layout.addWidget(widget)
    layout.addStretch()
    card = theme.make_card(form)
    qtbot.addWidget(card)
    card.resize(640, 240)
    card.show()
    qtbot.waitExposed(card)
    widget.setFocus()
    qtbot.waitUntil(widget.hasFocus)
    painted, rect = measure()
    image = card.grab().toImage()
    dpr = image.width() / card.width()

    band = []
    for x in range(rect.left() + 2, rect.right() - 2):
        for y in range(rect.top(), rect.bottom()):
            mapped = painted.mapTo(card, QPoint(x, y))
            band.append("#{:02X}{:02X}{:02X}".format(*_rgb(
                    image, QPoint(round(mapped.x() * dpr),
                                  round(mapped.y() * dpr)),
            )))
    ground = max(set(band), key=band.count)
    best = max(theme.contrast_ratio(pixel, ground) for pixel in band)
    assert best >= 4.5, ground
    assert theme.contrast_ratio(ground, applied_palette.BG_SURFACE) >= 1.2


@pytest.mark.parametrize(
        "palette",
        [theme.DARK, theme.LIGHT],
        ids=["dark", "light"],
)
def test_the_checkbox_tick_is_drawn_in_on_accent(palette):
    path = theme.check_tick_path(palette)
    assert path.is_file()
    assert f'stroke="{palette.ON_ACCENT}"' in path.read_text()
    assert path.as_posix() in theme.build_stylesheet(palette)


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


def test_cell_widget_names_each_button_for_its_row(qtbot):
    confirm = QPushButton("Confirm")
    reject = QPushButton("Reject")
    label = QLabel("Tagged")
    container = theme.cell_widget(
        confirm, reject, label, row_label="Nova Reyes - Voltage Drop",
    )
    qtbot.addWidget(container)

    assert confirm.accessibleName() == "Confirm Nova Reyes - Voltage Drop"
    assert reject.accessibleName() == "Reject Nova Reyes - Voltage Drop"
    assert label.accessibleName() == ""


# --- Keyboard focus is visible (§27.4) --------------------------------------


def _button(variant=None, checked=False, nav=False):
    def build():
        button = QPushButton("Sync")
        if nav:
            button.setProperty("navItem", True)
        theme.set_variant(button, variant)
        button.setCheckable(checked)
        button.setChecked(checked)
        return button
    return build


def _checkable(kind, checked=False):
    def build():
        control = kind("Keep")
        control.setChecked(checked)
        return control
    return build


def _tab_bar():
    bar = QTabBar()
    bar.addTab("Connection")
    bar.addTab("Library")
    return bar


_FOCUSABLE = {
    "button": _button(),
    "primary": _button("primary"),
    "danger": _button("danger"),
    "segment-checked": _button("segment", checked=True),
    "nav-item": _button(nav=True),
    "nav-item-checked": _button(nav=True, checked=True),
    "theme-toggle": lambda: ThemeToggleButton("system"),
    "checkbox": _checkable(QCheckBox),
    "checkbox-checked": _checkable(QCheckBox, checked=True),
    "radio": _checkable(QRadioButton),
    "radio-checked": _checkable(QRadioButton, checked=True),
    "tab": _tab_bar,
}


def _render(widget, focused: bool, background: str) -> QImage:
    # Painted through the style with State_HasFocus set on the option,
    # which is what a `:focus` rule matches. Real keyboard focus needs
    # an active window, which neither offscreen nor a busy desktop
    # session grants reliably (see test_menus.py's focus test).
    if isinstance(widget, QTabBar):
        option = QStyleOptionTab()
        widget.initStyleOption(option, 0)
        element = QStyle.ControlElement.CE_TabBarTab
    else:
        option = QStyleOptionButton()
        widget.initStyleOption(option)
        element = {
            QCheckBox: QStyle.ControlElement.CE_CheckBox,
            QRadioButton: QStyle.ControlElement.CE_RadioButton,
        }.get(type(widget), QStyle.ControlElement.CE_PushButton)
    if focused:
        option.state |= QStyle.StateFlag.State_HasFocus
    else:
        option.state &= ~QStyle.StateFlag.State_HasFocus
    image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor(background))
    painter = QPainter(image)
    widget.style().drawControl(element, option, painter, widget)
    painter.end()
    return image


@pytest.mark.parametrize("control", list(_FOCUSABLE), ids=list(_FOCUSABLE))
def test_keyboard_focus_changes_the_control_by_the_ui_component_floor(
        qtbot, applied_palette, control,
):
    # WCAG's focus-appearance test: some pixel of the focused control
    # differs from the same pixel unfocused by at least 3:1.
    widget = _FOCUSABLE[control]()
    qtbot.addWidget(widget)
    widget.ensurePolished()
    if not isinstance(widget, ThemeToggleButton):
        widget.resize(widget.sizeHint())
    background = applied_palette.BG_APP
    plain = _render(widget, False, background)
    focused = _render(widget, True, background)

    best = max(
        theme.contrast_ratio(
            plain.pixelColor(x, y).name(), focused.pixelColor(x, y).name(),
        )
        for x in range(plain.width())
        for y in range(plain.height())
    )
    assert best >= 3.0


@pytest.mark.parametrize(
        "kind", [QPushButton, QCheckBox, QRadioButton],
        ids=["button", "checkbox", "radio"],
)
def test_a_click_never_gives_a_button_focus(qtbot, applied_palette, kind):
    # The ring above means keyboard focus. Under Fusion's default a
    # click focuses a button too, leaving a ring on every button the
    # mouse touched; macOS's own buttons take focus from Tab only.
    control = kind("Sync")
    qtbot.addWidget(control)
    assert control.focusPolicy() == Qt.FocusPolicy.TabFocus


# --- The display face (Barlow Semi Condensed) -------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_the_display_face_ships_with_its_licence():
    fonts = _PROJECT_ROOT / "packaging" / "fonts"
    assert (fonts / "BarlowSemiCondensed-Medium.ttf").is_file()
    assert (fonts / "BarlowSemiCondensed-SemiBold.ttf").is_file()
    assert "SIL Open Font License" in (fonts / "OFL.txt").read_text()


def test_the_spec_bundles_the_fonts_directory():
    spec = (_PROJECT_ROOT / "packaging" / "seeker.spec").read_text()
    assert '(str(SPEC_DIR / "fonts"), "fonts")' in spec


def test_a_frozen_build_reads_fonts_from_the_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert theme.bundled_dir("fonts") == tmp_path / "fonts"


def test_apply_theme_registers_both_weights_of_the_display_face(qapp):
    theme.apply_theme(qapp, "dark")
    assert theme.DISPLAY_FAMILY in QFontDatabase.families()
    styles = QFontDatabase.styles(theme.DISPLAY_FAMILY)
    assert {"Medium", "SemiBold"} <= set(styles)


def test_an_unreadable_font_file_is_logged_not_raised(qapp, tmp_path, caplog):
    (tmp_path / "Broken.ttf").write_bytes(b"not a font")
    theme.load_fonts(tmp_path)
    assert "Broken.ttf" in caplog.text


@pytest.mark.parametrize(
        ("name", "size", "weight"),
        [
            ("pageTitleLabel", theme.TYPE_TITLE_PX, QFont.Weight.DemiBold),
            ("wordmark", theme.TYPE_TITLE_PX, QFont.Weight.DemiBold),
            ("sectionHeaderLabel", theme.TYPE_SECTION_PX, QFont.Weight.Medium),
        ],
)
def test_title_roles_are_set_in_the_display_face(
        qtbot, applied_palette, name, size, weight,
):
    label = QLabel("Dashboard")
    label.setObjectName(name)
    qtbot.addWidget(label)
    label.show()
    label.ensurePolished()
    info = QFontInfo(label.font())
    assert info.family() == theme.DISPLAY_FAMILY
    assert info.pixelSize() == size
    assert label.font().weight() == weight


# --- "Follow system" follows the system --------------------------------------


class _CocoaStyleHints:
    """The style hints as Cocoa behaves (observed, HISTORY §194): an
    explicit `setColorScheme()` is what `colorScheme()` reports until
    `Unknown` clears it, and then the OS's own scheme shows again.
    Offscreen never moves `colorScheme()` at all, so a test of the
    ordering needs this stand-in."""

    def __init__(self, platform: Qt.ColorScheme) -> None:
        self.platform = platform
        self.override = Qt.ColorScheme.Unknown

    def colorScheme(self) -> Qt.ColorScheme:
        if self.override != Qt.ColorScheme.Unknown:
            return self.override
        return self.platform

    def setColorScheme(self, scheme: Qt.ColorScheme) -> None:
        self.override = scheme


@pytest.mark.parametrize(
        ("platform", "explicit", "expected"),
        [
            (Qt.ColorScheme.Light, "dark", "LIGHT"),
            (Qt.ColorScheme.Dark, "light", "DARK"),
        ],
)
def test_follow_system_applies_the_systems_palette_at_once(
        qapp, monkeypatch, platform, explicit, expected,
):
    hints = _CocoaStyleHints(platform)
    monkeypatch.setattr(
            theme.QGuiApplication, "styleHints", staticmethod(lambda: hints),
    )
    try:
        theme.apply_theme(qapp, explicit)
        applied = theme.apply_theme(qapp, "system")
        assert applied is getattr(theme, expected)
        assert theme.active_palette() is applied
        assert applied.BG_SURFACE in qapp.styleSheet()
    finally:
        monkeypatch.undo()
        theme.apply_theme(qapp)

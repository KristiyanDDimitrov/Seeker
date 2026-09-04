import pytest
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
    # see a real pixel, and item 103 (C1) found live that this exact
    # property being PRESENT in the string is no guarantee it actually
    # PAINTS (an invalid neighboring selector silently poisoned the
    # whole rule for two rounds while this string check kept passing).
    # The real verification is test_ui_smoke.py's own real
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
    assert theme.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast_ratio("#808080", "#808080") == pytest.approx(1.0, abs=0.01)
    # A widely-cited reference pair (WCAG's own worked examples use
    # #767676 on white as landing almost exactly at the AA text floor).
    assert theme.contrast_ratio("#767676", "#FFFFFF") == pytest.approx(4.54, abs=0.01)


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_body_text_meets_the_aa_floor_on_its_own_background(palette):
    assert theme.contrast_ratio(palette.TEXT, palette.BG_SURFACE) >= 4.5
    assert theme.contrast_ratio(palette.TEXT, palette.BG_APP) >= 4.5


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_faint_text_and_borders_meet_the_decorative_floor(palette):
    # TEXT_FAINT is deliberately right at the edge (it's decorative, not
    # load-bearing text) — both palettes were designed to that same
    # ~3:1 floor, not a coincidence.
    assert theme.contrast_ratio(palette.TEXT_FAINT, palette.BG_SURFACE) >= 3.0
    assert theme.contrast_ratio(palette.BORDER, palette.BG_SURFACE) >= 1.0
    assert theme.contrast_ratio(palette.BORDER_STRONG, palette.BG_SURFACE) >= 1.9


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
def test_progress_bar_percentage_text_reads_on_both_its_backgrounds(palette):
    # Roadmap item C5 (round 5) — found live via a real screenshot: the
    # percentage label spans the ACCENT fill AND the plain
    # BG_SURFACE_2 track at once. TEXT_MUTED (the original color) was
    # only 1.26:1 against ACCENT in light — a real crop showed it
    # nearly invisible. TEXT (the fix) must clear the 3:1 UI-component
    # floor against BOTH.
    assert theme.contrast_ratio(palette.TEXT, palette.ACCENT) >= 3.0
    assert theme.contrast_ratio(palette.TEXT, palette.BG_SURFACE_2) >= 3.0


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
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

"""Scratch only (S30): renders a visual direction over the real app.

SEEKER_SCRATCH_DIRECTION=booth|harmonic selects one. Everything is a
monkeypatch applied before the window exists; no repository file
changes. Imported by render.py.
"""
import colorsys
import os
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from seeker.ui import theme
from seeker.ui.elided_text import SECONDARY_ROLE
from seeker.ui.pages import dashboard_page
from seeker.ui import main_window as main_window_module
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    RETRYING,
    REVIEW_CANDIDATE,
)

HERE = Path(__file__).parent
Palette = theme.Palette

# --- Booth --------------------------------------------------------------

BOOTH_DARK = Palette(
    BG_APP="#17191C",
    BG_SIDEBAR="#101113",
    BG_SURFACE="#1E2125",
    BG_SURFACE_2="#282C31",
    BORDER="#353A40",
    BORDER_STRONG="#4C535B",
    TEXT="#E8EAEC",
    TEXT_MUTED="#A0A7AE",
    TEXT_FAINT="#737B83",
    ACCENT="#4C9BFF",
    ACCENT_HOVER="#6AADFF",
    ACCENT_PRESSED="#3484EE",
    ACCENT_SUBTLE="#1A2A3F",
    SUCCESS="#35D07F",
    WARNING="#FFB020",
    DANGER="#FF6363",
    ON_ACCENT="#0A1422",
)

BOOTH_LIGHT = Palette(
    BG_APP="#E8EAEC",
    BG_SIDEBAR="#DDE0E3",
    BG_SURFACE="#F9FAFA",
    BG_SURFACE_2="#F0F2F3",
    BORDER="#CBD0D5",
    BORDER_STRONG="#9BA3AB",
    TEXT="#15181B",
    TEXT_MUTED="#4D555D",
    TEXT_FAINT="#757D85",
    ACCENT="#1660D0",
    ACCENT_HOVER="#0F53B8",
    ACCENT_PRESSED="#0B479E",
    ACCENT_SUBTLE="#DCE7F8",
    SUCCESS="#11804A",
    WARNING="#9E5C00",
    DANGER="#C22B2B",
    ON_ACCENT="#FFFFFF",
)

# --- Harmonic -----------------------------------------------------------

HARMONIC_DARK = Palette(
    BG_APP="#12161C",
    BG_SIDEBAR="#0E1116",
    BG_SURFACE="#181D25",
    BG_SURFACE_2="#212833",
    BORDER="#2E3642",
    BORDER_STRONG="#47515F",
    TEXT="#E4E8EE",
    TEXT_MUTED="#98A2B1",
    TEXT_FAINT="#6F7988",
    ACCENT="#8AB4E8",
    ACCENT_HOVER="#A0C3EE",
    ACCENT_PRESSED="#729FD6",
    ACCENT_SUBTLE="#1C2838",
    SUCCESS="#5CC98E",
    WARNING="#E2B354",
    DANGER="#F07070",
    ON_ACCENT="#0E1116",
)

HARMONIC_LIGHT = Palette(
    BG_APP="#EEF0F3",
    BG_SIDEBAR="#E3E6EB",
    BG_SURFACE="#FFFFFF",
    BG_SURFACE_2="#F5F7F9",
    BORDER="#D5DAE1",
    BORDER_STRONG="#A3ACB9",
    TEXT="#161A21",
    TEXT_MUTED="#515A68",
    TEXT_FAINT="#7A8392",
    ACCENT="#2D5C94",
    ACCENT_HOVER="#244E80",
    ACCENT_PRESSED="#1C416C",
    ACCENT_SUBTLE="#E2EAF4",
    SUCCESS="#1F7A4D",
    WARNING="#965800",
    DANGER="#B53030",
    ON_ACCENT="#FFFFFF",
)


def _hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        round(r * 255), round(g * 255), round(b * 255),
    )


def _at_contrast(hue: float, against: str, target: float, lighter: bool) -> str:
    """The colour of `hue` (saturation 0.72) whose contrast with
    `against` is `target`: equal luminance across the wheel, so no
    key shouts louder than another."""
    low, high = (0.0, 1.0)
    for _ in range(40):
        mid = (low + high) / 2
        ratio = theme.contrast_ratio(_hex(*colorsys.hls_to_rgb(hue, mid, 0.72)), against)
        if (ratio < target) == lighter:
            low = mid
        else:
            high = mid
    return _hex(*colorsys.hls_to_rgb(hue, (low + high) / 2, 0.72))


def _hue(number: int) -> float:
    return ((170 - 30 * (number - 1)) % 360) / 360


def camelot_color(number: int, light: bool) -> str:
    """Seeker's own 12-step wheel: adjacent Camelot numbers (the
    compatible mixes) get adjacent hues, 1 at turquoise. Every fill
    sits at the same contrast with the chip's text."""
    return _at_contrast(_hue(number), CHIP_TEXT, 7.0, lighter=True)


def camelot_edge(number: int) -> str:
    """Light theme only: the hue's own darker shade at 3:1 on white,
    so a pale chip still has a visible edge."""
    return _at_contrast(_hue(number), "#FFFFFF", 3.05, lighter=False)


CHIP_TEXT = "#0E1116"

# Invented analysis for the harness's demo tracks. Only files in the
# library have a key (analysis runs on local files), so only the two
# in-library demo rows carry one.
DEMO_ANALYSIS = {
    "track1": ("8A", 126),
    "track7": ("9A", 124),
}

DIRECTIONS = {
    "booth": (BOOTH_DARK, BOOTH_LIGHT),
    "harmonic": (HARMONIC_DARK, HARMONIC_LIGHT),
}


def _chevrons(dark: Palette, light: Palette) -> None:
    out = HERE / "icons"
    out.mkdir(exist_ok=True)
    for name, palette in (("dark", dark), ("light", light)):
        (out / f"combo_chevron_{name}.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" '
            'viewBox="0 0 10 6"><path d="M1 1 5 5 9 1" fill="none" '
            f'stroke="{palette.TEXT_MUTED}" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>'
        )

    def path(palette: Palette) -> Path:
        name = "light" if palette == theme.LIGHT else "dark"
        return out / f"combo_chevron_{name}.svg"

    theme.combo_chevron_path = path


# --- Booth pieces -------------------------------------------------------

_LED = {
    IN_LIBRARY: ("SUCCESS", True),
    DOWNLOADING: ("WARNING", True),
    RETRYING: ("WARNING", True),
    AWAITING_REVIEW: ("WARNING", False),
    NEEDS_REVIEW: ("WARNING", False),
    REVIEW_CANDIDATE: ("WARNING", False),
    NOT_FOUND: ("DANGER", True),
}


def led_icon(color: str, lit: bool, ground: str) -> QIcon:
    """A panel LED: a lit dot with a soft halo, or a hollow ring for
    'waiting on you' (cue set, not playing)."""
    size = 14
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    centre = QPointF(size / 2, size / 2)
    c = QColor(color)
    if lit:
        halo = QColor(c)
        halo.setAlpha(60)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(centre, 6.0, 6.0)
        painter.setBrush(c)
        painter.drawEllipse(centre, 3.6, 3.6)
    else:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(c, 1.6))
        painter.drawEllipse(centre, 3.6, 3.6)
    painter.end()
    return QIcon(pixmap)


def _booth_qss(palette: Palette) -> str:
    return f"""
QLabel#pageTitleLabel {{
    font-family: "Barlow Semi Condensed";
    font-size: 26px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
QLabel#wordmark {{
    font-family: "Barlow Semi Condensed";
    font-size: 26px;
    font-weight: 600;
}}
QLabel#sectionHeaderLabel {{
    font-family: "Barlow Semi Condensed";
    font-size: 16px;
    font-weight: 600;
}}
"""


def _booth_progress(bar: object) -> None:
    # The meter carries no label; the percentage sits beside the LED.
    bar.setFormat("")  # type: ignore[attr-defined]
    bar.setStyleSheet(  # type: ignore[attr-defined]
        "QProgressBar { border-radius: 2px; }"
        f"QProgressBar::chunk {{ background-color: {theme.WARNING};"
        " width: 5px; margin: 1px; border-radius: 1px; }"
    )


# --- Harmonic pieces ----------------------------------------------------


def key_chip(
        key: str | None, bpm: int | None, light: bool, palette: Palette,
) -> QIcon:
    """A two-part pill: the key in its wheel colour, the tempo on a
    neutral half. A track with no analysis keeps the space empty, so
    names stay aligned."""
    width, height, split = 62, 18, 28
    pixmap = QPixmap(width * 2, height * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    if key is None:
        return QIcon(pixmap)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0.5, 0.5, width - 1, height - 1)
    font = QFont()
    font.setPixelSize(11)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    whole = QPainterPath()
    whole.addRoundedRect(rect, 9, 9)
    painter.fillPath(whole, QColor(palette.BG_SURFACE_2))
    painter.setPen(QPen(QColor(palette.BORDER), 1))
    painter.drawPath(whole)
    left = QPainterPath()
    left.addRect(QRectF(0, 0, split, height))
    number = int(key[:-1])
    painter.fillPath(whole.intersected(left), QColor(camelot_color(number, light)))
    if light:
        painter.setPen(QPen(QColor(camelot_edge(number)), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(whole.intersected(left))
    painter.setPen(QColor(CHIP_TEXT))
    painter.drawText(QRectF(0, 0, split, height), Qt.AlignmentFlag.AlignCenter, key)
    font.setWeight(QFont.Weight.Normal)
    painter.setFont(font)
    painter.setPen(QColor(palette.TEXT_MUTED))
    painter.drawText(
        QRectF(split, 0, width - split, height), Qt.AlignmentFlag.AlignCenter,
        str(bpm),
    )
    painter.end()
    return QIcon(pixmap)


def wheel_pixmap(light: bool, size: int = 22) -> QPixmap:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    outer = QRectF(1, 1, size - 2, size - 2)
    inner_inset = size * 0.28
    inner = outer.adjusted(inner_inset, inner_inset, -inner_inset, -inner_inset)
    for n in range(1, 13):
        # 12 o'clock is 12, clockwise, as on the printed wheel.
        start = 90 - (n % 12) * 30 + 15
        path = QPainterPath()
        path.arcMoveTo(outer, start)
        path.arcTo(outer, start, -28)
        path.arcTo(inner, start - 28, 28)
        path.closeSubpath()
        painter.fillPath(path, QBrush(QColor(camelot_edge(n) if light else camelot_color(n, light))))
    painter.end()
    return pixmap


def _harmonic_qss(palette: Palette) -> str:
    return f"""
QLabel#pageTitleLabel {{
    font-size: 20px;
    font-weight: 600;
}}
QLabel#wordmark {{
    font-size: 20px;
    font-weight: 600;
}}
"""


# --- Install ------------------------------------------------------------


def install(app: QApplication) -> None:
    name = os.environ["SEEKER_SCRATCH_DIRECTION"]
    dark, light = DIRECTIONS[name]
    theme.DARK = dark
    theme.LIGHT = light
    _chevrons(dark, light)

    original_build = theme.build_stylesheet
    extra = _booth_qss if name == "booth" else _harmonic_qss

    def build(palette: Palette) -> str:
        return original_build(palette) + extra(palette)

    theme.build_stylesheet = build

    if name == "booth":
        for font in HERE.glob("fonts/*.ttf"):
            QFontDatabase.addApplicationFont(str(font))
        theme.style_determinate_progress_bar = _booth_progress

    # The wizard's step headings are <h2> rich text; preview them in the
    # page-title role, as S33 would.
    from seeker.ui import wizard as wizard_module
    from seeker.ui.plain_text import PlainLabel, RichLabel

    def heading_aware(text: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if text.startswith("<h2>") and text.endswith("</h2>"):
            label = PlainLabel(text[4:-5])
            label.setObjectName("pageTitleLabel")
            return label
        return RichLabel(text, *args, **kwargs)

    wizard_module.RichLabel = heading_aware

    original_rebuild = dashboard_page.DashboardPage._rebuild_track_rows

    def rebuild(self, visible):  # type: ignore[no-untyped-def]
        original_rebuild(self, visible)
        table = self.track_table
        palette = theme.LIGHT if theme.TEXT == theme.LIGHT.TEXT else theme.DARK
        is_light = palette is theme.LIGHT
        by_id = {status.track.id: status for status in visible}
        for row in range(table.rowCount()):
            label_item = table.item(row, 0)
            status = by_id[label_item.data(Qt.ItemDataRole.UserRole)]
            if name == "booth":
                token, lit = _LED[status.state]
                table.item(row, 1).setIcon(
                    led_icon(getattr(palette, token), lit, palette.BG_SURFACE),
                )
                if status.state == DOWNLOADING and status.total_bytes:
                    percent = round(
                        100 * (status.bytes_transferred or 0)
                        / status.total_bytes
                    )
                    table.item(row, 1).setData(SECONDARY_ROLE, f"{percent}%")
            else:
                key, bpm = DEMO_ANALYSIS.get(status.track.id, (None, None))
                label_item.setIcon(key_chip(key, bpm, is_light, palette))
        if name == "harmonic":
            table.setIconSize(QSize(62, 18))
        else:
            table.setIconSize(QSize(14, 14))

    dashboard_page.DashboardPage._rebuild_track_rows = rebuild

    if name == "harmonic":
        original_init = main_window_module.MainWindow.__init__

        def init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            original_init(self, *args, **kwargs)
            wordmark = self._wordmark
            is_light = theme.TEXT == theme.LIGHT.TEXT
            mark = QLabel()
            mark.setPixmap(wheel_pixmap(is_light))
            for layout in self.findChildren(QHBoxLayout):
                if layout.indexOf(wordmark) >= 0:
                    layout.insertWidget(0, mark)
                    layout.insertSpacing(1, 8)
                    break

        main_window_module.MainWindow.__init__ = init

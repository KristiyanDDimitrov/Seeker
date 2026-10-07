"""A progress bar's percentage reads on both of its backgrounds: the
ACCENT fill and the track. Walks the harness's Dashboard and Downloads
screens, in both themes, and measures each determinate bar's label at
its midpoint."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QProgressBar, QStyle, QStyleOptionProgressBar

from seeker.ui import theme
from seeker.ui.main_window import MainWindow

# Antialiasing softens a glyph's edge, never its stem: a stem pixel
# reaches the label colour itself. The slack covers rounding only.
_STEM = 0.9


def _hex(color) -> str:
    return color.name().upper()


def _label_contrast(bar: QProgressBar) -> dict[str, float]:
    """The best contrast any label pixel reaches against the fill and
    against the track, for whichever of the two the label overlaps."""
    option = QStyleOptionProgressBar()
    bar.initStyleOption(option)
    contents = bar.style().subElementRect(
        QStyle.SubElement.SE_ProgressBarContents, option, bar,
    )
    fraction = (bar.value() - bar.minimum()) / (bar.maximum() - bar.minimum())
    split = contents.left() + round(contents.width() * fraction)
    text_width = bar.fontMetrics().horizontalAdvance(bar.text())
    text_left = (bar.width() - text_width) // 2
    text_right = text_left + text_width

    # Rendered at 2x on every platform: at offscreen's 1x a small
    # glyph's stems never reach the label colour itself.
    dpr = 2
    image = QImage(bar.size() * dpr, QImage.Format.Format_ARGB32)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    bar.render(image)
    regions = {
        # The fill's rounded end shows the track in its corners; the
        # fill is sampled only where it is full height.
        "fill": (
            theme.active_palette().ACCENT,
            range(
                text_left,
                min(text_right, split - theme.PROGRESS_BAR_RADIUS),
            ),
        ),
        "track": (
            theme.active_palette().BG_SURFACE_2,
            range(max(text_left, split + 1), text_right),
        ),
    }
    best: dict[str, float] = {}
    for name, (ground, columns) in regions.items():
        if len(columns) < 3:
            continue
        best[name] = max(
            theme.contrast_ratio(
                _hex(image.pixelColor(round(x * dpr), round(y * dpr))),
                ground,
            )
            for x in columns
            for y in range(contents.top() + 1, contents.bottom())
        )
    return best


@pytest.fixture
def _restore_theme(qapp):
    yield
    theme.apply_theme(qapp)


@pytest.mark.usefixtures("_restore_theme")
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_the_percentage_reads_on_the_fill_and_on_the_track(
        qapp, screenshots, mode,
):
    palette = theme.apply_theme(qapp, mode)
    floor = {
        "fill": _STEM * theme.contrast_ratio(palette.ON_ACCENT, palette.ACCENT),
        "track": _STEM * theme.contrast_ratio(
            palette.TEXT, palette.BG_SURFACE_2,
        ),
    }
    window = MainWindow(screenshots.build_demo_application())
    measured: list[tuple[str, str, float]] = []
    try:
        window.resize(1280, 820)
        window.show()
        screenshots.settle(qapp, window, 1.0)
        for screen in screenshots.SCREENS:
            if screen.name not in ("dashboard", "downloads"):
                continue
            for step in screen.steps:
                step(window)
                screenshots.settle(qapp, window)
            for bar in window.findChildren(QProgressBar):
                # The activity strip's bar never shows a label, and an
                # indeterminate bar or a meter (theme.style_meter, its
                # percentage beside it as cell text) has none: its
                # text() is empty, so no label is painted to measure.
                if (
                        bar is window.activity_strip_bar
                        or not bar.isVisible()
                        or not bar.text()
                ):
                    continue
                # At the midpoint the label straddles the fill's edge,
                # so both halves are measured on each page's own bar.
                bar.setValue(
                    bar.minimum() + (bar.maximum() - bar.minimum()) // 2,
                )
                qapp.processEvents()
                for region, ratio in _label_contrast(bar).items():
                    measured.append((screen.name, region, ratio))
    finally:
        screenshots.close(qapp, window)

    assert {region for _, region, _ in measured} == {"fill", "track"}
    short = [
        (screen, region, round(ratio, 2))
        for screen, region, ratio in measured
        if ratio < floor[region]
    ]
    assert short == []

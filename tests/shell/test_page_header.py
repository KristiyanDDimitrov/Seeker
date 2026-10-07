"""The page header every page gets from `build_page`: its title and
subtitle read as one unit, at a readable measure."""

from PySide6.QtWidgets import QLabel, QWidget

from seeker.ui import help_text, theme
from seeker.ui.pages.context import SUBTITLE_MEASURE_CHARS, build_page


def _shown_page(qtbot, subtitle: str) -> tuple[QWidget, QLabel, QLabel, QWidget]:
    content = QWidget()
    page = build_page("Downloads", subtitle, content)
    qtbot.addWidget(page)
    page.resize(1100, 600)
    page.show()
    qtbot.waitExposed(page)
    title = page.findChild(QLabel, "pageTitleLabel")
    subtitle_label = next(
        label for label in page.findChildren(QLabel)
        if label.text() == subtitle
    )
    return page, title, subtitle_label, content


def test_the_subtitle_sits_close_under_the_title_and_apart_from_content(qtbot):
    _page, title, subtitle, content = _shown_page(
        qtbot, help_text.DASHBOARD_TAB_SUBTITLE,
    )

    title_bottom = title.geometry().bottom()
    assert subtitle.geometry().top() - title_bottom <= theme.SPACING_XS + 1
    assert content.geometry().top() - subtitle.geometry().bottom() >= (
        theme.SPACING_LG
    )


def test_a_long_subtitle_wraps_at_a_readable_measure(qtbot):
    _page, _title, subtitle, _content = _shown_page(
        qtbot, help_text.HISTORY_PAGE_SUBTITLE,
    )

    measure = subtitle.fontMetrics().averageCharWidth() * SUBTITLE_MEASURE_CHARS
    assert subtitle.width() <= measure
    assert SUBTITLE_MEASURE_CHARS <= 90

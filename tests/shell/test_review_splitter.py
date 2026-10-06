"""The Review splitter: its sizes survive a quit and relaunch (saved by
cleanup_before_quit, restored the first time the page is shown), and
each handle draws a 1 px line across a wider grab area."""
from PySide6.QtCore import QPoint

from fakes import FakeApplication, force_tray_available
from seeker.ui import theme
from seeker.ui.main_window import MainWindow

# Far from the 3:2:2 stretch-factor default, so a restore that silently
# fell back to the default could not pass for one that worked.
DRAGGED_SIZES = [120, 400, 160]


def _open_review(qtbot, application) -> MainWindow:
    # Each window gets the same explicit size. A saved window geometry
    # would be restored instead, and Qt fits a restored geometry to the
    # available screen: offscreen's is 800x800 (CI runs offscreen), so
    # the second window came up shorter and redistributed the sizes.
    application.update_settings(window_geometry=None)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.resize(1200, 900)
    window.show()
    qtbot.waitExposed(window)
    window._nav_buttons["review"].click()
    qtbot.waitUntil(window._review_page.isVisible)
    return window


def _splitter(window: MainWindow):
    return window._review_page.review_splitter


def _drag(window: MainWindow, sizes: list[int]) -> list[int]:
    splitter = _splitter(window)
    splitter.setSizes(sizes)
    # Qt fits the request to the real height and handle widths; the
    # sizes it settles on are what a user's drag would have produced.
    return splitter.sizes()


def test_splitter_sizes_survive_quit_and_relaunch(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()

    first = _open_review(qtbot, application)
    dragged = _drag(first, DRAGGED_SIZES)
    first.cleanup_before_quit()
    first.close()

    assert application.settings.review_splitter_state

    second = _open_review(qtbot, application)

    assert _splitter(second).sizes() == dragged
    second.cleanup_before_quit()


def test_a_later_visit_keeps_a_size_dragged_since_the_restore(
        qtbot, monkeypatch,
):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    first = _open_review(qtbot, application)
    _drag(first, DRAGGED_SIZES)
    first.cleanup_before_quit()
    first.close()

    second = _open_review(qtbot, application)
    redragged = _drag(second, [400, 160, 120])
    second._nav_buttons["dashboard"].click()
    second._nav_buttons["review"].click()
    qtbot.waitUntil(second._review_page.isVisible)

    assert _splitter(second).sizes() == redragged
    second.cleanup_before_quit()


def test_an_unreadable_saved_state_keeps_the_default_proportions(
        qtbot, monkeypatch,
):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    default_sizes = _splitter(_open_review(qtbot, application)).sizes()

    application.update_settings(review_splitter_state="not base64 !!")
    window = _open_review(qtbot, application)

    assert _splitter(window).sizes() == default_sizes
    window.cleanup_before_quit()


def test_a_handle_is_a_one_pixel_line_in_a_wider_grab_area(qtbot):
    window = _open_review(qtbot, FakeApplication())
    handle = _splitter(window).handle(1)

    image = window.grab().toImage()
    dpr = image.width() / window.width()
    column = handle.mapTo(window, QPoint(handle.width() // 2, 0))
    painted = [
        image.pixelColor(
            round(column.x() * dpr), round((column.y() + y) * dpr),
        ).name().upper()
        for y in range(handle.height())
    ]
    assert painted.count(theme.BORDER_STRONG) == 1
    assert painted.count(theme.BG_APP) == handle.height() - 1
    assert handle.height() >= 7

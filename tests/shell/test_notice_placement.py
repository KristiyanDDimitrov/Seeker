"""A notice stays in view however far its page scrolls: an action at
the bottom of a tall page reports to a notice the user can see, never
one scrolled out above them (Settings' tabs did, HISTORY §220)."""
from PySide6.QtWidgets import QScrollArea, QWidget

from fakes import FakeApplication
from seeker.ui.main_window import MainWindow
from seeker.ui.notice import InlineNotice


def _scrolled_by(notice: InlineNotice) -> QWidget | None:
    """The scroll area carrying `notice`, or None. A notice inside a
    card reports on that card alone and scrolls with it (Library's
    nesting warning, beside the table it is about), so the walk stops
    there: a page's own notice never sits in a card, so that stop cannot
    hide a page notice placed in a scroll area."""
    parent = notice.parentWidget()

    while parent is not None:
        if parent.objectName() == "card":
            return None
        if isinstance(parent, QScrollArea):
            return parent
        parent = parent.parentWidget()

    return None


def test_no_page_notice_scrolls_with_its_page(qtbot):
    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    notices = window.findChildren(InlineNotice)
    # Every page builds its notices up front, Settings' four tab
    # notices among them: the walk sees all of them unshown.
    assert len(notices) > 10

    scrolled = [
        notice for notice in notices if _scrolled_by(notice) is not None
    ]

    assert scrolled == []

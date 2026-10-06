"""Buttons take their size hint: never stretched to fill a row, never
squeezed below their own height. Walks every screen the screenshot
harness renders, at its smaller size, where a squeeze shows first."""
import pytest
from PySide6.QtWidgets import QPushButton, QWidget

from seeker.ui import theme
from seeker.ui.main_window import MainWindow
from seeker.ui.wizard import OnboardingWizard

_SIZE = (960, 640)
# Rounding slack: a size hint and a laid-out width can differ by a
# pixel under fractional scaling.
_SLACK = 2


def _misfits(screen: str, root: QWidget) -> list[str]:
    found = []
    for button in root.findChildren(QPushButton):
        # A hidden button has no laid-out geometry to judge. The walk
        # visits every screen with its demo data loaded, so a button
        # the sizing bug touches is visible on at least one of them.
        if not button.isVisible():
            continue
        # The sidebar's nav items fill the sidebar by design, and a
        # layout that wants a full-width primary says so with the
        # `fullWidth` property; neither is a stretched button.
        if button.property("navItem") or button.property("fullWidth"):
            continue
        hint = button.sizeHint()
        if button.width() > hint.width() + _SLACK:
            found.append(
                f"{screen}: {button.text()!r} is {button.width()} px "
                f"wide, hint {hint.width()}",
            )
        if button.height() < hint.height() - _SLACK:
            found.append(
                f"{screen}: {button.text()!r} is {button.height()} px "
                f"tall, hint {hint.height()}",
            )
    return found


@pytest.fixture
def _restore_theme(qapp):
    yield
    theme.apply_theme(qapp)


@pytest.mark.usefixtures("_restore_theme")
def test_no_button_is_stretched_or_squeezed_on_any_screen(
        qapp, screenshots,
):
    misfits: list[str] = []

    application = screenshots.build_demo_application()
    theme.apply_theme(qapp, "dark")
    window = MainWindow(application)
    try:
        window.resize(*_SIZE)
        window.show()
        screenshots.settle(qapp, window, 1.0)
        for screen in screenshots.SCREENS:
            for step in screen.steps:
                step(window)
                screenshots.settle(qapp, window)
            misfits += _misfits(screen.name, window)
    finally:
        screenshots.close(qapp, window)

    application = screenshots.build_demo_application()
    application.spotify_configured = False
    wizard = OnboardingWizard(application, on_complete=lambda: None)
    try:
        wizard.resize(*_SIZE)
        wizard.show()
        for index, step in enumerate(screenshots.WIZARD_STEPS):
            wizard.stack.setCurrentIndex(index)
            screenshots.settle(qapp, wizard, 0.3)
            misfits += _misfits(f"wizard-{step}", wizard)
    finally:
        screenshots.close(qapp, wizard)

    assert misfits == []

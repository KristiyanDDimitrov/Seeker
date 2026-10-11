"""`tools/screenshots.py` runs end to end, so a UI change that breaks
the harness fails here rather than at the next README refresh."""
import pytest
from PySide6.QtGui import QImage

from seeker.ui import theme


@pytest.fixture
def _restore_theme(qapp):
    yield
    theme.apply_theme(qapp)


@pytest.mark.usefixtures("_restore_theme")
def test_renders_a_page_at_the_requested_size(qapp, screenshots, tmp_path):
    written = screenshots.render_all(
        qapp, tmp_path, page_filter=["review"], themes=["light"],
        sizes=[(960, 640)],
    )

    assert written == [tmp_path / "review-light-960x640.png"]
    # A Retina screen (local runs on Cocoa) grabs at twice the size.
    ratio = qapp.primaryScreen().devicePixelRatio()
    image = QImage(str(written[0]))
    assert (image.width(), image.height()) == (960 * ratio, 640 * ratio)


@pytest.mark.usefixtures("_restore_theme")
def test_renders_every_wizard_step(qapp, screenshots, tmp_path):
    written = screenshots.render_all(
        qapp, tmp_path, page_filter=["wizard"], themes=["dark"],
        sizes=[(960, 640)],
    )

    assert [path.name for path in written] == [
        f"wizard-{step}-dark-960x640.png"
        for step in screenshots.WIZARD_STEPS
    ]


@pytest.mark.usefixtures("_restore_theme")
def test_the_soulseek_step_shows_the_share_offer_a_new_user_sees(
        qapp, screenshots, tmp_path, monkeypatch,
):
    # A new user reaches the SoulSeek step having chosen a folder, so
    # the step offers to share it; a resumed wizard's step does not.
    shown_at_grab: list[bool] = []

    class RecordingWizard(screenshots.OnboardingWizard):
        def grab(self, *args):
            shown_at_grab.append(not self.share_library_checkbox.isHidden())
            return super().grab(*args)

    monkeypatch.setattr(screenshots, "OnboardingWizard", RecordingWizard)

    screenshots.capture_wizard(
        qapp, "dark", [(960, 640)],
        lambda name, size: tmp_path / f"{name}.png",
        steps=["soulseek"],
    )

    assert shown_at_grab == [True]


def test_every_readme_image_names_a_real_screen(screenshots):
    names = {screen.name for screen in screenshots.SCREENS}

    for _file, screen, image_theme in screenshots.README_IMAGES:
        assert screen in names
        assert image_theme in screenshots.THEMES

    _file, step, wizard_theme = screenshots.README_WIZARD
    assert step in screenshots.WIZARD_STEPS
    assert wizard_theme in screenshots.THEMES

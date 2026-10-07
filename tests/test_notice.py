import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from seeker.ui import theme
from seeker.ui.notice import InlineNotice
from seeker.ui.widgets import CloseButton


def test_starts_hidden(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)
    assert notice.isHidden()


def test_show_message_displays_text_and_shows(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)

    notice.show_message("Something happened", kind="error")

    assert notice.text() == "Something happened"
    assert not notice.isHidden()


def test_dismiss_hides_again(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)

    notice.show_message("Hello", kind="info")
    notice.dismiss()

    assert notice.isHidden()


def test_action_button_hidden_without_an_action(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)

    notice.show_message("No action here")

    assert notice._action_button.isHidden()


def test_action_button_shown_and_wired_with_an_action(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)
    calls = []

    notice.show_message(
        "Do something?", action_text="Do it", on_action=lambda: calls.append(1),
    )

    assert not notice._action_button.isHidden()
    assert notice._action_button.text() == "Do it"

    notice._action_button.click()

    assert calls == [1]


def test_dismiss_emits_dismissed_signal(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)
    calls = []
    notice.dismissed.connect(lambda: calls.append(1))

    notice.show_message("Hello", kind="info")
    notice.dismiss()

    assert calls == [1]


def test_dismiss_button_click_emits_dismissed_signal(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)
    calls = []
    notice.dismissed.connect(lambda: calls.append(1))

    notice.show_message("Hello", kind="info")
    notice._dismiss_button.click()

    assert calls == [1]
    assert notice.isHidden()


def test_second_show_message_replaces_the_action_rather_than_stacking(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)
    calls = []

    notice.show_message(
        "First", action_text="A", on_action=lambda: calls.append("a"),
    )
    notice.show_message(
        "Second", action_text="B", on_action=lambda: calls.append("b"),
    )

    notice._action_button.click()

    assert calls == ["b"]


def test_a_peer_filename_in_a_message_renders_literally_not_as_a_link(
        qtbot,
):
    from PySide6.QtCore import Qt

    filename = '<a href="https://evil.example">Update Seeker</a>.mp3'
    notice = InlineNotice()
    qtbot.addWidget(notice)

    notice.show_message(
        f"slskd rejected the download of '{filename}' from 'peer'.",
        kind="error",
    )

    assert notice._message_label.textFormat() == Qt.TextFormat.PlainText
    assert filename in notice.text()


def test_the_dismiss_control_is_a_named_cross_not_a_letter(qtbot):
    notice = InlineNotice()
    qtbot.addWidget(notice)

    button = notice._dismiss_button

    assert isinstance(button, CloseButton)
    assert button.text() == ""
    assert button.accessibleName() == "Dismiss"


_EDGE_TOKENS = {
    "info": "TEXT_MUTED",
    "success": "SUCCESS",
    "warning": "WARNING",
    "error": "DANGER",
}


@pytest.mark.parametrize("palette", [theme.DARK, theme.LIGHT], ids=["dark", "light"])
@pytest.mark.parametrize("kind", list(_EDGE_TOKENS))
def test_a_notice_lights_only_its_left_edge(qtbot, palette, kind):
    # The variant colour marks the left edge alone, like a lamp; the
    # rest of the frame is the ordinary hairline. Info is not the
    # accent, which marks only selection, focus and the primary action.
    host = QWidget()
    qtbot.addWidget(host)
    host.setStyleSheet(theme.build_stylesheet(palette))
    notice = InlineNotice(host)
    notice.show_message("Scan finished.", kind)
    notice.resize(400, 48)
    host.resize(400, 48)
    host.show()
    qtbot.waitExposed(host)

    image = notice.grab().toImage()
    scale = image.width() / notice.width()
    middle_y = image.height() // 2
    left_edge = image.pixelColor(round(1 * scale), middle_y)
    top_edge = image.pixelColor(image.width() // 2, 0)

    assert left_edge == QColor(getattr(palette, _EDGE_TOKENS[kind]))
    assert top_edge == QColor(palette.BORDER)

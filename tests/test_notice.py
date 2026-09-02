from seeker.ui.notice import InlineNotice


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

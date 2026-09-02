from PySide6.QtWidgets import QPushButton

from seeker.ui.busy_actions import BusyActionRegistry


def test_begin_disables_button_and_end_reenables(qtbot):
    button = QPushButton("Go")
    qtbot.addWidget(button)
    registry = BusyActionRegistry()

    registry.begin("scan", button)
    assert button.isEnabled() is False
    assert registry.is_running("scan") is True

    registry.end("scan")
    assert button.isEnabled() is True
    assert registry.is_running("scan") is False


def test_begin_with_busy_text_restores_original_text_on_end(qtbot):
    button = QPushButton("Rescan library")
    qtbot.addWidget(button)
    registry = BusyActionRegistry()

    registry.begin("scan", button, "Scanning…")
    assert button.text() == "Scanning…"

    registry.end("scan")
    assert button.text() == "Rescan library"


def test_begin_without_busy_text_leaves_text_unchanged(qtbot):
    button = QPushButton("Download")
    qtbot.addWidget(button)
    registry = BusyActionRegistry()

    registry.begin("download", button)
    assert button.text() == "Download"

    registry.end("download")
    assert button.text() == "Download"


def test_begin_is_idempotent_and_never_clobbers_stored_original_text(qtbot):
    button = QPushButton("Download")
    qtbot.addWidget(button)
    registry = BusyActionRegistry()

    registry.begin("download", button, "Starting…")
    # A second begin() for the same key while already running (matches
    # _set_download_button_busy's own repeated calls across the real
    # multi-hop download chain) must not re-capture "Starting…" as the
    # "original" text to restore later.
    registry.begin("download", button, "Starting…")

    registry.end("download")
    assert button.text() == "Download"


def test_end_on_a_key_that_was_never_running_is_a_safe_no_op(qtbot):
    registry = BusyActionRegistry()
    registry.end("nonexistent")  # must not raise
    assert registry.is_running("nonexistent") is False


def test_running_keys_reflects_multiple_concurrent_actions(qtbot):
    button_a = QPushButton("A")
    button_b = QPushButton("B")
    qtbot.addWidget(button_a)
    qtbot.addWidget(button_b)
    registry = BusyActionRegistry()

    registry.begin("scan", button_a)
    registry.begin("sync", button_b)
    assert registry.running_keys() == frozenset({"scan", "sync"})

    registry.end("scan")
    assert registry.running_keys() == frozenset({"sync"})

    registry.end("sync")
    assert registry.running_keys() == frozenset()


def test_two_different_keys_on_the_same_button_do_not_interfere(qtbot):
    # Not a real usage pattern in this app, but the registry itself
    # shouldn't assume one button maps to only one key.
    button = QPushButton("Shared")
    qtbot.addWidget(button)
    registry = BusyActionRegistry()

    registry.begin("a", button, "Busy A")
    registry.begin("b", button, "Busy B")  # already disabled -- no text clobber issue here since begin() only sets text, never reads current disabled state

    registry.end("a")
    # "a" ending restores to whatever text() was captured by "a"'s own
    # begin() ("Shared") -- "b" is still tracked as running independently.
    assert button.text() == "Shared"
    assert registry.is_running("b") is True

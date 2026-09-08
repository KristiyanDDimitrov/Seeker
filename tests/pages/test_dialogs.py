"""Tests for the standalone dialogs in seeker.ui.dialogs — About and the
missing-destination prompt. Moved verbatim out of test_ui_smoke.py (round
8, §9.3.4, session S11.1) — the mirror of §9.3.1's own dialogs.py
extraction (S5). RenamePreviewDialog/BulkReplaceUpgradesDialog/
BulkResolveDuplicatesDialog stay in test_ui_smoke.py: each is constructed
by one specific page (tagging_panel.py/review_page.py/duplicates_page.py
respectively, not by MainWindow directly), so their tests belong with
that page's own future test-split session (S11.3/S11.5/S11.6), not here.
"""

from pathlib import Path

from PySide6.QtWidgets import QLabel, QPushButton

from seeker.models.library_location import LibraryLocation
from seeker.ui import help_text
from seeker.ui.dialogs import AboutDialog, DestinationDialog
from seeker.ui.main_window import MainWindow
from test_ui_smoke import FakeApplication


def test_destination_dialog_preview_shows_new_folder_when_it_does_not_exist(
        qtbot, tmp_path,
):
    location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location], default_location_id=1,
        initial_subfolder="Does Not Exist Yet",
    )
    qtbot.addWidget(dialog)

    text = dialog.location_path_preview.text()
    assert str(tmp_path / "Does Not Exist Yet") in text
    assert "new folder" in text


def test_destination_dialog_preview_counts_real_audio_files(qtbot, tmp_path):
    subfolder = tmp_path / "Test"
    subfolder.mkdir()
    (subfolder / "a.mp3").write_bytes(b"\x00")
    (subfolder / "b.flac").write_bytes(b"\x00")
    (subfolder / "notes.txt").write_bytes(b"\x00")  # not audio -- excluded

    location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location], default_location_id=1,
        initial_subfolder="Test",
    )
    qtbot.addWidget(dialog)

    text = dialog.location_path_preview.text()
    assert str(subfolder) in text
    assert "already exists" in text
    assert "2 audio files" in text


def test_destination_dialog_preview_updates_live_as_fields_change(
        qtbot, tmp_path,
):
    location_a = LibraryLocation(
        id=1, name="A", path=str(tmp_path / "a"),
        added_at="2026-01-01T00:00:00+00:00",
    )
    location_b = LibraryLocation(
        id=2, name="B", path=str(tmp_path / "b"),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location_a, location_b], default_location_id=1,
        initial_subfolder="Sub",
    )
    qtbot.addWidget(dialog)

    assert str(
            Path(location_a.path) / "Sub"
    ) in dialog.location_path_preview.text()

    dialog.location_combo.setCurrentIndex(1)
    assert str(
            Path(location_b.path) / "Sub"
    ) in dialog.location_path_preview.text()

    dialog.subfolder_field.setText("Other")
    assert str(
            Path(location_b.path) / "Other"
    ) in dialog.location_path_preview.text()


def test_about_dialog_opens_without_crashing(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dialog = AboutDialog(window)
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == help_text.ABOUT_DIALOG_TITLE


def test_about_dialog_shows_build_identity(qtbot):
    # Roadmap item 81 (0.1) — "dev" is the committed _build_info.py
    # fallback. Reliable regardless of real local build state (RR1.2 —
    # see conftest.py's autouse fixture and test_main_window_
    # constructs_without_crashing's own identical comment).
    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    labels_html = [widget.text() for widget in dialog.findChildren(QLabel)]
    combined = "\n".join(labels_html)

    assert "Build:" in combined
    assert "dev" in combined


def test_about_dialog_shows_author_license_and_notices(qtbot):
    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    labels_html = [
        widget.text() for widget in dialog.findChildren(QLabel)
    ]
    combined = "\n".join(labels_html)

    assert "Kristiyan Dimitrov" in combined
    assert "mailto:kristiyanddimitrov@gmail.com" in combined
    assert "github.com/KristiyanDDimitrov/Seeker" in combined
    assert "MIT License" in combined
    assert "Third-party notices" in combined
    assert "PySide6" in combined


def test_about_dialog_renders_a_button_for_every_real_support_link(
        qtbot, monkeypatch,
):
    # Both Revolut and PayPal are real links as of 2026-09-01 — every
    # entry in the real SUPPORT_LINKS dict should render a working
    # button (the "at least one still-placeholder" filtering behavior
    # itself is covered separately below, via a synthetic placeholder,
    # so this guard stays exercised even though production data no
    # longer has a real one to filter).
    # build_support_links_row() (round 8 §9.3.1) lives in seeker.ui.dialogs
    # now — see the identical note on the Support-page version of this
    # test above.
    from seeker.ui import dialogs as dialogs_module

    opened: list[str] = []
    monkeypatch.setattr(
        dialogs_module.webbrowser, "open", opened.append
    )

    assert all(
        help_text.is_real_support_link(url)
        for url in help_text.SUPPORT_LINKS.values()
    ), "expected every current SUPPORT_LINKS entry to be a real link"

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    buttons = [
        widget
        for widget in dialog.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert len(buttons) == len(help_text.SUPPORT_LINKS)
    assert {button.text() for button in buttons} == {
        f"Support on {name}" for name in help_text.SUPPORT_LINKS
    }

    for button in buttons:
        button.click()

    assert set(opened) == set(help_text.SUPPORT_LINKS.values())


def test_about_dialog_filters_out_a_placeholder_support_link(
        qtbot, monkeypatch,
):
    # Regression guard for is_real_support_link() itself: since the real
    # SUPPORT_LINKS no longer has a TODO entry to filter (PayPal went
    # live), inject a synthetic one here so a dead, non-URL button is
    # still proven to never render, rather than this guard silently
    # stopping being exercised. Patched on seeker.ui.dialogs's own
    # help_text binding — that's where AboutDialog's build_support_
    # links_row() actually reads SUPPORT_LINKS from (help_text is a
    # shared singleton module either way, so this patches the same real
    # object main_window's own binding would have too).
    from seeker.ui import dialogs as dialogs_module

    monkeypatch.setattr(
        dialogs_module.help_text, "SUPPORT_LINKS",
        {
            "Revolut": "https://revolut.me/kddimitrov",
            "Ko-fi": "TODO: paste real Ko-fi link",
        },
    )

    dialog = AboutDialog()
    qtbot.addWidget(dialog)

    buttons = [
        widget
        for widget in dialog.findChildren(QPushButton)
        if widget.text().startswith("Support on")
    ]
    assert [button.text() for button in buttons] == ["Support on Revolut"]

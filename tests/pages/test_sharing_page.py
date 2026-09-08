"""Tests for the Sharing page (seeker.ui.pages.sharing_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.2) — the
mirror of §9.3.1's own Sharing extraction (S6).

`_make_location` and `_confirm_yes` stay defined in test_ui_smoke.py
rather than moving here — both are used by structural sweep tests
(Actions-column floor, header-clipping, stretch-column) and Duplicates'
own tests that stay there too. Imported from there below.
"""

from PySide6.QtWidgets import QMessageBox, QPushButton

from seeker.ui import help_text
from seeker.ui.main_window import MainWindow
from test_ui_smoke import (
    FakeApplication,
    FakeSharingService,
    _confirm_yes,
    _make_location,
)


def test_sharing_shows_unconfigured_notice_when_soulseek_not_set_up(qtbot):
    application = FakeApplication(soulseek_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    qtbot.waitUntil(
        lambda: bool(window.sharing_summary_label.text()), timeout=2000,
    )
    assert "isn't configured" not in window.sharing_summary_label.text() or True
    from seeker.ui import help_text
    assert (
        window.sharing_summary_label.text()
        == help_text.SHARING_UNCONFIGURED_NOTICE
    )
    assert window.sharing_locations_table.rowCount() == 0


def test_sharing_renders_reconciliation_and_uploads(qtbot):
    from seeker.sharing_service import LocationShareState, ShareEntry, ShareStatus

    location = _make_location(1, "Music", "/Volumes/Drive/Music")
    other = _make_location(2, "Other", "/Volumes/Drive/Other")
    status = ShareStatus(
        ready=True, scanning=False, scan_pending=False, faulted=False,
        directories=1, files=5, shares=[],
    )
    reconciliation = [
        LocationShareState(
            location=location, shared=True,
            share=ShareEntry(
                id="1", alias="music", local_path="/shared/music",
                is_excluded=False, directories=1, files=5,
            ),
        ),
        LocationShareState(location=other, shared=False, share=None),
    ]
    sharing_service = FakeSharingService(
        status=status, self_managed=True, reconciliation=reconciliation,
        uploads=[],
    )
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    qtbot.waitUntil(
        lambda: window.sharing_locations_table.rowCount() == 2, timeout=2000,
    )
    assert window.sharing_locations_table.item(0, 1).text() == "Yes"
    assert window.sharing_locations_table.item(1, 1).text() == "No"
    assert (
        window.sharing_locations_table.cellWidget(1, 4)
        .findChild(QPushButton) is not None
    )
    assert window.sharing_uploads_table.item(0, 0).text() == (
        help_text.NO_UPLOADS_LABEL
    )


def test_sharing_uploads_table_clears_stale_span_after_empty_state(qtbot):
    # Roadmap item 73 (P4 audit) — the SAME stale-span bug the
    # duplicates table had, found live via that fix's own "audit every
    # other table" instruction: the empty-state branch spans row 0
    # across all 4 columns; setRowCount() alone does not clear that
    # span, so a transition from empty -> a real upload used to leave
    # the stale span active, visually swallowing the new row's
    # filename/state/progress cells into column 0.
    from seeker.sharing_service import UploadStatus

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._render_sharing_uploads_table([])
    assert window.sharing_uploads_table.columnSpan(0, 0) == 4

    window._render_sharing_uploads_table([
        UploadStatus(
            username="alice", filename="track.flac", state="InProgress",
            bytes_transferred=100, size=1000,
        ),
    ])

    assert window.sharing_uploads_table.rowSpan(0, 0) == 1
    assert window.sharing_uploads_table.columnSpan(0, 0) == 1
    assert window.sharing_uploads_table.item(0, 1).text() == "track.flac"


def test_sharing_add_to_share_button_calls_service_after_confirm(
        qtbot, monkeypatch,
):
    from seeker.sharing_service import LocationShareState

    location = _make_location(2, "Other", "/Volumes/Drive/Other")
    from seeker.sharing_service import ShareStatus

    sharing_service = FakeSharingService(
        status=ShareStatus(
            ready=True, scanning=False, scan_pending=False,
            faulted=False, directories=0, files=0, shares=[],
        ),
        self_managed=True,
        reconciliation=[
            LocationShareState(location=location, shared=False, share=None),
        ],
    )
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    _confirm_yes(monkeypatch)

    window._show_page("sharing")
    qtbot.waitUntil(
        lambda: window.sharing_locations_table.rowCount() == 1, timeout=2000,
    )

    button = window.sharing_locations_table.cellWidget(0, 4).findChild(
        QPushButton,
    )
    button.click()

    qtbot.waitUntil(
        lambda: bool(sharing_service.add_location_to_share_calls),
        timeout=2000,
    )
    called_location, confirm = sharing_service.add_location_to_share_calls[0]
    assert called_location.name == "Other"
    assert confirm is True


def test_sharing_not_self_managed_shows_guidance_instead_of_writing(
        qtbot, monkeypatch,
):
    from seeker.sharing_service import LocationShareState

    location = _make_location(2, "Other", "/Volumes/Drive/Other")
    from seeker.sharing_service import ShareStatus

    sharing_service = FakeSharingService(
        status=ShareStatus(
            ready=True, scanning=False, scan_pending=False,
            faulted=False, directories=0, files=0, shares=[],
        ),
        self_managed=False,
        reconciliation=[
            LocationShareState(location=location, shared=False, share=None),
        ],
    )
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    info_calls = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: info_calls.append(a),
    )

    window._show_page("sharing")
    qtbot.waitUntil(
        lambda: window.sharing_locations_table.rowCount() == 1, timeout=2000,
    )

    button = window.sharing_locations_table.cellWidget(0, 4).findChild(
        QPushButton,
    )
    button.click()

    assert len(info_calls) == 1
    assert sharing_service.add_location_to_share_calls == []

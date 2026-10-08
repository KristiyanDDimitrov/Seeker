"""Tests for the Sharing page (seeker.ui.pages.sharing_page). Moved
verbatim out of test_ui_smoke.py (round 8, §9.3.4, session S11.2) — the
mirror of §9.3.1's own Sharing extraction (S6).

`make_location` and `confirm_yes` come from `tests/fakes.py`: the
structural sweep tests and Duplicates' own tests use them too.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from fakes import (
    FakeApplication,
    FakeSharingService,
    confirm_yes,
    make_location,
)
from seeker.ui import help_text, plain_text, status_lamp
from seeker.ui.elided_text import SECONDARY_ROLE
from seeker.ui.main_window import MainWindow
from seeker.ui.pages.sharing_page import _upload_state


def test_sharing_shows_unconfigured_notice_when_soulseek_not_set_up(qtbot):
    application = FakeApplication(soulseek_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    summary_label = window._sharing_page.sharing_summary_label
    qtbot.waitUntil(lambda: bool(summary_label.text()), timeout=2000)
    assert summary_label.text() == help_text.SHARING_UNCONFIGURED_NOTICE
    assert window._sharing_page.sharing_locations_table.rowCount() == 0


def test_sharing_renders_the_default_fake_status_like_a_real_one(qtbot):
    # The real get_status returns a ShareStatus or raises; it never
    # returns None. A default FakeApplication must honour that, or every
    # test that shows Sharing with SoulSeek configured exercises an
    # error path production cannot reach.
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    summary_label = window._sharing_page.sharing_summary_label
    qtbot.waitUntil(
        lambda: summary_label.text().startswith("0 directories"),
        timeout=2000,
    )
    assert window._sharing_page.sharing_status_label.text() == ""


def test_sharing_renders_reconciliation_and_uploads(qtbot):
    from seeker.soulseek.sharing_service import (
        LocationShareState,
        ShareEntry,
        ShareStatus,
    )

    location = make_location(1, "Music", "/Volumes/Drive/Music")
    other = make_location(2, "Other", "/Volumes/Drive/Other")
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

    locations_table = window._sharing_page.sharing_locations_table
    qtbot.waitUntil(lambda: locations_table.rowCount() == 2, timeout=2000)
    assert locations_table.item(0, 1).text() == "Shared"
    assert not locations_table.item(0, 1).icon().isNull()
    assert locations_table.item(1, 1).text() == "Not shared"
    # A shared row's action cell is empty: Shared already says so.
    assert locations_table.cellWidget(0, 4) is None
    assert (
        locations_table.cellWidget(1, 4).findChild(QPushButton) is not None
    )
    uploads_table = window._sharing_page.sharing_uploads_table
    assert uploads_table.rowCount() == 0
    assert window._sharing_page.sharing_uploads_empty.isVisibleTo(window)
    assert window._sharing_page.sharing_uploads_empty.text() == (
        help_text.SHARING_UPLOADS_EMPTY
    )


def test_sharing_uploads_empty_state_gives_way_to_a_real_upload(qtbot):
    from seeker.soulseek.sharing_service import UploadStatus

    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    page = window._sharing_page

    page._render_sharing_uploads_table([])
    assert page.sharing_uploads_empty.isVisibleTo(page)

    page._render_sharing_uploads_table([
        UploadStatus(
            username="alice", filename="track.flac", state="InProgress",
            bytes_transferred=100, size=1000,
        ),
    ])

    assert not page.sharing_uploads_empty.isVisibleTo(page)
    assert page.sharing_uploads_table.columnSpan(0, 0) == 1
    assert page.sharing_uploads_table.item(0, 1).text() == "track.flac"


def test_sharing_locations_empty_state_sends_you_to_settings(qtbot):
    application = FakeApplication(soulseek_configured=False)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("sharing")
    page = window._sharing_page

    qtbot.waitUntil(
        lambda: page.sharing_locations_empty.text()
        == help_text.SHARING_LOCATIONS_UNCONFIGURED,
        timeout=2000,
    )
    page.sharing_locations_empty_action.click()

    assert window._current_page_key == "settings"


def test_sharing_locations_empty_state_asks_for_a_location(qtbot):
    sharing_service = FakeSharingService(reconciliation=[], uploads=[])
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("sharing")
    page = window._sharing_page

    qtbot.waitUntil(
        lambda: page.sharing_locations_empty.text()
        == help_text.SHARING_LOCATIONS_EMPTY,
        timeout=2000,
    )


def test_sharing_add_to_share_button_calls_service_after_confirm(
        qtbot, monkeypatch,
):
    from seeker.soulseek.sharing_service import LocationShareState

    location = make_location(2, "Other", "/Volumes/Drive/Other")
    from seeker.soulseek.sharing_service import ShareStatus

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
    confirm_yes(monkeypatch)

    window._show_page("sharing")
    locations_table = window._sharing_page.sharing_locations_table
    qtbot.waitUntil(lambda: locations_table.rowCount() == 1, timeout=2000)

    button = locations_table.cellWidget(0, 4).findChild(QPushButton)
    button.click()

    qtbot.waitUntil(
        lambda: bool(sharing_service.add_location_to_share_calls),
        timeout=2000,
    )
    called_location, confirm = sharing_service.add_location_to_share_calls[0]
    assert called_location.name == "Other"
    assert confirm is True


def test_sharing_add_to_share_confirmation_survives_the_immediate_refresh(
        qtbot, monkeypatch,
):
    # Round 8 §12.9 regression test — real bug found tracing the "five
    # feedback channels" rule through every page: the confirmation used
    # to go to sharing_status_label, which _on_add_location_to_share_
    # finished's own _refresh_sharing() call wipes via run_worker's
    # status_label.setText("") at the top of every call, before the
    # user could ever read it. Now on sharing_notice (InlineNotice),
    # outside run_worker's status_label plumbing entirely.
    from seeker.soulseek.sharing_service import LocationShareState, ShareStatus

    location = make_location(2, "Other", "/Volumes/Drive/Other")
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
    confirm_yes(monkeypatch)

    window._show_page("sharing")
    locations_table = window._sharing_page.sharing_locations_table
    qtbot.waitUntil(lambda: locations_table.rowCount() == 1, timeout=2000)

    assert window._sharing_page.sharing_notice.isHidden()

    button = locations_table.cellWidget(0, 4).findChild(QPushButton)
    button.click()

    qtbot.waitUntil(
        lambda: not window._sharing_page.sharing_notice.isHidden(),
        timeout=2000,
    )
    text = window._sharing_page.sharing_notice.text()
    assert "'Other' shared" in text
    assert "1 directories" in text
    assert "1 files" in text

    # The immediate _refresh_sharing() call this same handler triggers
    # must not wipe it — wait for that refresh to actually settle
    # (locations_table repopulated) and confirm the notice is still
    # showing the same text, not blanked.
    qtbot.wait(200)
    assert not window._sharing_page.sharing_notice.isHidden()
    assert window._sharing_page.sharing_notice.text() == text


def test_sharing_not_self_managed_shows_guidance_instead_of_writing(
        qtbot, monkeypatch,
):
    from seeker.soulseek.sharing_service import LocationShareState

    location = make_location(2, "Other", "/Volumes/Drive/Other")
    from seeker.soulseek.sharing_service import ShareStatus

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
        plain_text, "information",
        lambda *a, **k: info_calls.append(a),
    )

    window._show_page("sharing")
    locations_table = window._sharing_page.sharing_locations_table
    qtbot.waitUntil(lambda: locations_table.rowCount() == 1, timeout=2000)

    button = locations_table.cellWidget(0, 4).findChild(QPushButton)
    button.click()

    assert len(info_calls) == 1
    assert sharing_service.add_location_to_share_calls == []


def test_sharing_explainer_starts_closed_below_the_tables(qtbot):
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    page = window._sharing_page
    assert page.explainer.toggle.text() == help_text.SHARING_EXPLAINER_TITLE
    assert not page.explainer.is_expanded()
    assert not page.explainer.body.isVisibleTo(window)
    # The counts and both tables come first; the explanation is last.
    content = page.explainer.parentWidget().layout()
    assert content.indexOf(page.explainer) == content.count() - 1


def test_opening_the_sharing_explainer_is_remembered(qtbot):
    application = FakeApplication(soulseek_configured=True)
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("sharing")
    page = window._sharing_page

    page.explainer.toggle.click()

    assert page.explainer.body.isVisibleTo(window)
    assert application.settings.sharing_explainer_open is True

    page.explainer.toggle.click()

    assert not page.explainer.body.isVisibleTo(window)
    assert application.settings.sharing_explainer_open is False


def test_sharing_explainer_reopens_as_the_viewer_left_it(qtbot):
    application = FakeApplication(soulseek_configured=True)
    application.update_settings(sharing_explainer_open=True)
    application.update_settings_calls.clear()
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    assert window._sharing_page.explainer.body.isVisibleTo(window)
    # Restoring the state is not a new choice to save.
    assert not any(
        "sharing_explainer_open" in call
        for call in application.update_settings_calls
    )


def test_a_failed_sharing_refresh_stays_on_the_notice(qtbot):
    class FailingSharingService(FakeSharingService):
        def get_status(self):
            raise RuntimeError("slskd answered 500")

    application = FakeApplication(
        soulseek_configured=True, sharing_service=FailingSharingService(),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    page = window._sharing_page
    qtbot.waitUntil(lambda: page.sharing_notice.isVisibleTo(window), timeout=2000)
    assert "slskd answered 500" in page.sharing_notice.text()
    assert page.sharing_status_label.text() == ""


@pytest.mark.parametrize(
    ("raw", "label", "lamp", "note"),
    [
        ("Queued, Remotely", "Queued", status_lamp.CUE, None),
        ("Requested", "Queued", status_lamp.CUE, None),
        ("Initializing", "Queued", status_lamp.CUE, None),
        ("InProgress", "Uploading", status_lamp.CUE, None),
        ("Completed, Succeeded", "Sent", status_lamp.PLAY, None),
        ("Completed, TimedOut", "Failed", status_lamp.FAULT, "Timed out"),
        ("Completed, Cancelled", "Failed", status_lamp.FAULT, "Cancelled"),
        ("Completed, Errored", "Failed", status_lamp.FAULT, "Error"),
        ("SomethingNew", "SomethingNew", None, None),
        (None, "", None, None),
    ],
)
def test_an_upload_state_reads_in_seekers_words(raw, label, lamp, note):
    state = _upload_state(raw)

    assert (state.label, state.lamp, state.note) == (label, lamp, note)


def test_an_upload_row_shows_its_state_with_a_lamp(qtbot):
    from seeker.soulseek.sharing_service import UploadStatus

    sharing_service = FakeSharingService(uploads=[
        UploadStatus(
            username="listener", filename="Music\\a.flac",
            state="Completed, TimedOut", bytes_transferred=10, size=100,
        ),
    ])
    application = FakeApplication(
        soulseek_configured=True, sharing_service=sharing_service,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    window._show_page("sharing")

    table = window._sharing_page.sharing_uploads_table
    qtbot.waitUntil(lambda: table.rowCount() == 1, timeout=2000)
    item = table.item(0, 2)
    assert item.text() == "Failed"
    assert item.data(SECONDARY_ROLE) == "Timed out"
    assert not item.icon().isNull()
    assert "Completed, TimedOut" in item.toolTip()


def test_upload_state_sorts_closest_to_done_first(qtbot):
    from seeker.soulseek.sharing_service import UploadStatus

    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._sharing_page
    # Listed alphabetically by label, the order a text sort would keep.
    page._render_sharing_uploads_table([
        UploadStatus(
            username="peer", filename=state, state=state,
            bytes_transferred=None, size=None,
        )
        for state in (
            "Completed, Errored", "Queued, Remotely", "Completed, Succeeded",
            "InProgress",
        )
    ])
    table = page.sharing_uploads_table

    table.sortItems(2, Qt.SortOrder.AscendingOrder)

    assert [table.item(row, 2).text() for row in range(4)] == [
        "Sent", "Uploading", "Queued", "Failed",
    ]


def test_shared_sorts_above_not_shared(qtbot):
    from seeker.soulseek.sharing_service import LocationShareState

    window = MainWindow(FakeApplication())
    qtbot.addWidget(window)
    page = window._sharing_page
    page._render_sharing_locations_table([
        LocationShareState(
            location=make_location(1, "Music", "/Volumes/Drive/Music"),
            shared=True, share=None,
        ),
        LocationShareState(
            location=make_location(2, "Other", "/Volumes/Drive/Other"),
            shared=False, share=None,
        ),
    ])
    table = page.sharing_locations_table

    table.sortItems(1, Qt.SortOrder.AscendingOrder)

    assert [table.item(row, 1).text() for row in range(2)] == [
        "Shared", "Not shared",
    ]

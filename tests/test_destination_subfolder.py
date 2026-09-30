"""A playlist's destination subfolder: what the user sees is what is
used, and a download never lands outside its library location."""

import pytest

from seeker import cli
from seeker.destination_resolution import (
    InvalidDestinationSubfolderError,
    validate_destination_subfolder,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.ui.dialogs import DestinationDialog
from test_cli import FakeApplication, FakeSyncService, make_matcher
from test_download_service import _seed_default_destination_scenario


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("Techno", "Techno"),
        (" Techno ", "Techno"),
        ("Techno/", "Techno"),
        ("Music/240KMH", "Music/240KMH"),
        ("240KM/H", "240KM/H"),
        ("Mr. Oizo", "Mr. Oizo"),
    ],
)
def test_valid_subfolders_are_used_as_typed(raw, expected):
    assert validate_destination_subfolder(raw) == expected


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("../Elsewhere", "inside"),
        ("Music/../../x", "inside"),
        ("./Music", "inside"),
        ("/abs", "absolute"),
        ("Music//Techno", "empty"),
        ("Bad:Name", "Bad-Name"),
        (".hidden", "_hidden"),
        ("Music/Trailing.", "Trailing"),
        ("Back\\slash", "Back-slash"),
    ],
)
def test_unsafe_subfolders_are_rejected_with_a_reason(raw, reason):
    with pytest.raises(InvalidDestinationSubfolderError, match=reason):
        validate_destination_subfolder(raw)


def _specific_scenario(tmp_path):
    service, _default_root = _seed_default_destination_scenario(
        tmp_path, playlist_name="Test", subfolder_per_playlist=True,
        playlist_specific_location_name="Specific",
    )
    return service, tmp_path / "specific_music"


@pytest.mark.parametrize("raw", ["../Elsewhere", "/abs", "Bad:Name"])
def test_set_destination_rejects_an_unsafe_subfolder_and_saves_nothing(
        tmp_path, raw,
):
    service, _root = _specific_scenario(tmp_path)

    with pytest.raises(InvalidDestinationSubfolderError):
        service.set_destination("Test", "Specific", raw)

    with service.database.transaction() as connection:
        playlist = service.playlists.get_by_name("Test", connection)

    assert playlist.download_subfolder is None


def test_a_nested_subfolder_downloads_to_exactly_that_path(tmp_path):
    service, root = _specific_scenario(tmp_path)

    service.set_destination("Test", "Specific", "240KM/H/")

    with service.database.transaction() as connection:
        playlist = service.playlists.get_by_name("Test", connection)
    assert playlist.download_subfolder == "240KM/H"

    counts = service.poll_downloads()

    assert counts.completed == 1
    assert (root / "240KM" / "H" / "Artist - Title.mp3").exists()


def test_a_stored_unsafe_subfolder_never_moves_a_file_outside_the_location(
        tmp_path,
):
    # A value saved before validation existed: resolution must refuse
    # it rather than join "../" onto the location path.
    service, _root = _specific_scenario(tmp_path)

    with service.database.transaction() as connection:
        playlist = service.playlists.get_by_name("Test", connection)
        service.playlists.set_destination(
            playlist.id, playlist.download_location_id, "../Elsewhere",
            connection,
        )

    counts = service.poll_downloads()

    assert counts.completed == 0
    assert not (tmp_path / "Elsewhere").exists()
    assert (
        tmp_path / "slskd_downloads" / "Artist - Title.mp3"
    ).exists()
    assert service.get_resolved_destination("Test") is None


def _dialog(qtbot, tmp_path, subfolder):
    location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "Test", [location], default_location_id=1,
        initial_subfolder=subfolder,
    )
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_previews_the_nested_path_the_download_will_use(
        qtbot, tmp_path,
):
    dialog = _dialog(qtbot, tmp_path, "240KM/H")

    assert str(tmp_path / "240KM" / "H") in (
        dialog.location_path_preview.text()
    )
    assert dialog.confirm_button.isEnabled()
    assert dialog.selected_subfolder() == "240KM/H"


@pytest.mark.parametrize("raw", ["../x", "/abs"])
def test_dialog_explains_and_blocks_an_unsafe_subfolder(
        qtbot, tmp_path, raw,
):
    dialog = _dialog(qtbot, tmp_path, "Fine")
    assert dialog.confirm_button.isEnabled()

    dialog.subfolder_field.setText(raw)

    assert not dialog.confirm_button.isEnabled()
    assert str(tmp_path) not in dialog.location_path_preview.text()
    assert dialog.location_path_preview.text()


def test_dialog_prefills_the_playlist_folder_the_default_rule_uses(
        qtbot, tmp_path,
):
    location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path),
        added_at="2026-01-01T00:00:00+00:00",
    )
    dialog = DestinationDialog(
        None, "240KM/H", [location], default_location_id=1,
    )
    qtbot.addWidget(dialog)

    assert dialog.subfolder_field.text() == "240KM-H"


class _RejectingDownloadService:
    def set_destination(self, playlist_name, location_name, subfolder):
        raise InvalidDestinationSubfolderError(
            "The subfolder must stay inside the location."
        )


def test_cli_set_destination_reports_an_unsafe_subfolder(tmp_path, capsys):
    application = FakeApplication(
        make_matcher(tmp_path),
        download_service=_RejectingDownloadService(),
        sync_service=FakeSyncService(
            [Playlist(id="p1", name="Test", track_count=0)],
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.run(
            application,
            ["playlists", "set-destination", "Test", "Main", "../x"],
        )

    assert exit_info.value.code == 1
    assert "inside the location" in capsys.readouterr().out

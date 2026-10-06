"""Library locations never nest: one inside another indexes every file
under the inner one twice (HISTORY §171).
"""
import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.library.service import (
    LibraryLocationOverlapError,
    LibraryLocationPathAlreadyRegisteredError,
    LibraryService,
)


def make_service(tmp_path) -> LibraryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return LibraryService(
        database,
        LibraryLocationRepository(),
        LocalFileRepository(),
        playlist_repo=PlaylistRepository(),
    )


def add_with_name(service: LibraryService, path: str) -> None:
    service.add_location("new", path)


def add_from_path(service: LibraryService, path: str) -> None:
    service.add_location_from_path(path)


ADD_PATHS = pytest.mark.parametrize(
    "add", [add_with_name, add_from_path], ids=["named", "from_path"],
)


@ADD_PATHS
def test_adding_a_folder_inside_a_location_is_refused(tmp_path, add):
    service = make_service(tmp_path)
    outer = tmp_path / "Drive"
    inner = outer / "Music"
    inner.mkdir(parents=True)
    service.add_location("drive", str(outer))

    with pytest.raises(LibraryLocationOverlapError) as excinfo:
        add(service, str(inner))

    message = str(excinfo.value)
    assert "inside" in message
    assert "'drive'" in message
    assert excinfo.value.existing.name == "drive"
    assert [loc.name for loc, _ in service.list_locations()] == ["drive"]


@ADD_PATHS
def test_adding_a_folder_containing_a_location_is_refused(tmp_path, add):
    service = make_service(tmp_path)
    outer = tmp_path / "Drive"
    inner = outer / "Music"
    inner.mkdir(parents=True)
    service.add_location("music", str(inner))

    with pytest.raises(LibraryLocationOverlapError) as excinfo:
        add(service, str(outer))

    message = str(excinfo.value)
    assert "contains" in message
    assert "Remove 'music' first" in message
    assert [loc.name for loc, _ in service.list_locations()] == ["music"]


@ADD_PATHS
def test_a_sibling_sharing_a_name_prefix_is_not_nested(tmp_path, add):
    service = make_service(tmp_path)
    (tmp_path / "Music").mkdir()
    (tmp_path / "Music2").mkdir()
    service.add_location("music", str(tmp_path / "Music"))

    add(service, str(tmp_path / "Music2"))

    assert len(service.list_locations()) == 2


@ADD_PATHS
def test_a_symlink_into_a_location_is_refused(tmp_path, add):
    service = make_service(tmp_path)
    inner = tmp_path / "Drive" / "Music"
    inner.mkdir(parents=True)
    (tmp_path / "shortcut").symlink_to(inner)
    service.add_location("drive", str(tmp_path / "Drive"))

    with pytest.raises(LibraryLocationOverlapError):
        add(service, str(tmp_path / "shortcut"))


def _is_case_insensitive(directory) -> bool:
    probe = directory / "CaseProbe"
    probe.mkdir()

    return (directory / "caseprobe").exists()


@ADD_PATHS
def test_a_differently_cased_path_inside_a_location_is_refused(
        tmp_path, add,
):
    # macOS's default APFS volume is case-insensitive, so `music/House`
    # is a folder inside `Music`. Only meaningful on such a volume.
    if not _is_case_insensitive(tmp_path):
        pytest.skip("needs a case-insensitive filesystem")
    service = make_service(tmp_path)
    (tmp_path / "Music" / "House").mkdir(parents=True)
    service.add_location("music", str(tmp_path / "Music"))

    with pytest.raises(LibraryLocationOverlapError):
        add(service, str(tmp_path / "music" / "House"))


@ADD_PATHS
def test_a_differently_cased_copy_of_a_location_is_already_registered(
        tmp_path, add,
):
    if not _is_case_insensitive(tmp_path):
        pytest.skip("needs a case-insensitive filesystem")
    service = make_service(tmp_path)
    (tmp_path / "Music").mkdir()
    service.add_location("music", str(tmp_path / "Music"))

    with pytest.raises(LibraryLocationPathAlreadyRegisteredError):
        add(service, str(tmp_path / "music"))

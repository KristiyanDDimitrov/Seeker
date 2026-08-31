import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.library.scanner import LibraryUnavailableError
from seeker.library.service import (
    LibraryLocationPathAlreadyRegisteredError,
    LibraryService,
)
from seeker.models.local_file import LocalFile


def make_service(tmp_path) -> LibraryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return LibraryService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
    )


def test_add_location_raises_for_nonexistent_path(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(LibraryUnavailableError):
        service.add_location("main", str(tmp_path / "does-not-exist"))


def test_add_location_raises_clear_error_for_duplicate_name(tmp_path):
    service = make_service(tmp_path)

    first_root = tmp_path / "music1"
    second_root = tmp_path / "music2"
    first_root.mkdir()
    second_root.mkdir()

    service.add_location("main", str(first_root))

    with pytest.raises(RuntimeError, match="named 'main' already exists"):
        service.add_location("main", str(second_root))


def test_add_location_raises_clear_error_for_duplicate_path(tmp_path):
    service = make_service(tmp_path)

    library_root = tmp_path / "music"
    library_root.mkdir()

    service.add_location("main", str(library_root))

    with pytest.raises(RuntimeError, match="already registered"):
        service.add_location("other", str(library_root))


def test_add_location_from_path_uses_folder_basename_as_the_name(tmp_path):
    service = make_service(tmp_path)
    library_root = tmp_path / "Music"
    library_root.mkdir()

    location = service.add_location_from_path(str(library_root))

    assert location.name == "Music"
    assert location.path == str(library_root)


def test_add_location_from_path_auto_suffixes_on_name_collision(tmp_path):
    service = make_service(tmp_path)
    first_root = tmp_path / "Music"
    first_root.mkdir()
    (tmp_path / "nested").mkdir()
    second_root = tmp_path / "nested" / "Music"
    second_root.mkdir()

    first = service.add_location_from_path(str(first_root))
    second = service.add_location_from_path(str(second_root))

    assert first.name == "Music"
    assert second.name == "Music (2)"


def test_add_location_from_path_raises_a_clear_error_naming_the_existing_location(
        tmp_path,
):
    service = make_service(tmp_path)
    library_root = tmp_path / "Music"
    library_root.mkdir()

    first = service.add_location_from_path(str(library_root))

    with pytest.raises(LibraryLocationPathAlreadyRegisteredError) as excinfo:
        service.add_location_from_path(str(library_root))

    assert excinfo.value.existing.name == first.name
    assert first.name in str(excinfo.value)


def test_add_location_from_path_raises_for_nonexistent_path(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(LibraryUnavailableError):
        service.add_location_from_path(str(tmp_path / "does-not-exist"))


def test_rename_location_updates_the_name(tmp_path):
    service = make_service(tmp_path)
    library_root = tmp_path / "Music"
    library_root.mkdir()
    location = service.add_location_from_path(str(library_root))

    renamed = service.rename_location(location.id, "My Music")

    assert renamed.name == "My Music"
    with service.database.transaction() as connection:
        assert service.locations.get_by_name("My Music", connection) is not None
        assert service.locations.get_by_name("Music", connection) is None


def test_rename_location_raises_a_clear_error_on_name_collision(tmp_path):
    service = make_service(tmp_path)
    first_root = tmp_path / "Music"
    first_root.mkdir()
    second_root = tmp_path / "Podcasts"
    second_root.mkdir()
    service.add_location_from_path(str(first_root))
    second = service.add_location_from_path(str(second_root))

    with pytest.raises(RuntimeError, match="named 'Music' already exists"):
        service.rename_location(second.id, "Music")


def test_scan_all_skips_unreachable_location_without_touching_its_rows(
        tmp_path,
):
    library_root = tmp_path / "music"
    library_root.mkdir()

    service = make_service(tmp_path)
    service.add_location("main", str(library_root))

    with service.database.transaction() as connection:
        location = service.locations.get_by_name("main", connection)

        service.local_files.upsert(
            LocalFile(
                location_id=location.id,
                relative_path="song.mp3",
                filename="song.mp3",
                format="mp3",
                size_bytes=123,
                mtime=111.0,
                scanned_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )

    # Simulate the drive going offline after the location was registered
    # and an earlier scan had already recorded a row for it.
    library_root.rmdir()

    service.scan_all()

    with service.database.transaction() as connection:
        remaining = service.local_files.get_all(connection)

    assert len(remaining) == 1
    assert remaining[0].relative_path == "song.mp3"

import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.library.scanner import LibraryScanner, LibraryUnavailableError
from seeker.models.library_location import LibraryLocation


def test_scan_raises_when_location_path_does_not_exist(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    missing_path = tmp_path / "does-not-exist"

    location = LibraryLocation(
        id=1,
        name="main",
        path=str(missing_path),
        added_at="2026-01-01T00:00:00+00:00",
    )

    scanner = LibraryScanner(LocalFileRepository(database), database)

    with pytest.raises(LibraryUnavailableError) as exc_info:
        scanner.scan(location)

    assert str(missing_path) in str(exc_info.value)
    assert "drive" in str(exc_info.value).lower()


def test_scan_skips_appledouble_sidecar_files(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    library_root = tmp_path / "music"
    library_root.mkdir()

    (library_root / "song.mp3").write_bytes(b"")
    (library_root / "._song.mp3").write_bytes(b"")

    local_files = LocalFileRepository(database)
    locations = LibraryLocationRepository(database)

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(
                name="main",
                path=str(library_root),
                added_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )
        location = locations.get_by_name("main", connection)

    scanner = LibraryScanner(local_files, database)
    summary = scanner.scan(location)

    assert summary["added"] == 1

    with database.transaction() as connection:
        scanned = local_files.get_all(connection)

    assert [local_file.relative_path for local_file in scanned] == [
        "song.mp3"
    ]

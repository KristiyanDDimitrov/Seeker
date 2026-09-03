import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.library.scanner import (
    LibraryScanner,
    LibraryUnavailableError,
    index_single_file,
)
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


def test_scan_indexes_aiff_files(tmp_path):
    # Roadmap item R1 — .aiff was entirely invisible to the whole app
    # before AUDIO_EXTENSIONS gained it (this test would have asserted
    # added == 0 on the pre-fix code).
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    library_root = tmp_path / "music"
    library_root.mkdir()

    (library_root / "track.aiff").write_bytes(b"")
    (library_root / "track2.aif").write_bytes(b"")

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

    assert summary["added"] == 2

    with database.transaction() as connection:
        scanned = local_files.get_all(connection)

    assert {local_file.relative_path for local_file in scanned} == {
        "track.aiff", "track2.aif",
    }
    assert {local_file.format for local_file in scanned} == {"aiff", "aif"}


def test_index_single_file_matches_scan_loop_result(tmp_path):
    # index_single_file is the one place both the scan loop and the
    # SoulSeek upgrade-confirmation flow read tags and upsert — this
    # confirms a direct call produces the same row scan() would.
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    library_root = tmp_path / "music"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"")

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

    with database.transaction() as connection:
        indexed = index_single_file(
            location, "song.mp3", local_files, connection
        )

    assert indexed.id is not None
    assert indexed.relative_path == "song.mp3"
    assert indexed.format == "mp3"

    scanner = LibraryScanner(local_files, database)
    scanner.scan(location)

    with database.transaction() as connection:
        scanned = local_files.get_all(connection)

    assert len(scanned) == 1
    assert scanned[0].id == indexed.id
    assert scanned[0].relative_path == indexed.relative_path

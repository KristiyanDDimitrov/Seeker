import wave

import pytest
from mutagen.id3 import APIC
from mutagen.wave import WAVE

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

    scanner = LibraryScanner(LocalFileRepository(), database)

    with pytest.raises(LibraryUnavailableError) as exc_info:
        scanner.scan(location)

    assert str(missing_path) in str(exc_info.value)


def test_scan_skips_appledouble_sidecar_files(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    library_root = tmp_path / "music"
    library_root.mkdir()

    (library_root / "song.mp3").write_bytes(b"")
    (library_root / "._song.mp3").write_bytes(b"")

    local_files = LocalFileRepository()
    locations = LibraryLocationRepository()

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

    assert summary.added == 1

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

    local_files = LocalFileRepository()
    locations = LibraryLocationRepository()

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

    assert summary.added == 2

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

    local_files = LocalFileRepository()
    locations = LibraryLocationRepository()

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


def _write_wav(path, *, with_art: bool) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8_000)
        handle.writeframes(b"\x00\x00" * 800)

    if with_art:
        audio = WAVE(path)
        audio.add_tags()
        audio.tags.add(
            APIC(encoding=3, mime="image/jpeg", type=3, data=b"\xff\xd8art")
        )
        audio.save()


def _scan_location(tmp_path, library_root):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    local_files = LocalFileRepository()

    with database.transaction() as connection:
        LibraryLocationRepository().add(
            LibraryLocation(
                name="main",
                path=str(library_root),
                added_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )
        location = LibraryLocationRepository().get_by_name("main", connection)

    return database, local_files, LibraryScanner(local_files, database), location


def _has_art_by_path(database, local_files):
    with database.transaction() as connection:
        return {
            local_file.relative_path: local_file.has_art
            for local_file in local_files.get_all(connection)
        }


def test_scan_records_whether_each_file_has_embedded_art(tmp_path):
    library_root = tmp_path / "music"
    library_root.mkdir()
    _write_wav(library_root / "with.wav", with_art=True)
    _write_wav(library_root / "without.wav", with_art=False)
    (library_root / "unreadable.mp3").write_bytes(b"not audio")

    database, local_files, scanner, location = _scan_location(
        tmp_path, library_root,
    )
    scanner.scan(location)

    # None is "could not tell", never "no art": an unreadable file is
    # not reported as one cover-art repair would fix.
    assert _has_art_by_path(database, local_files) == {
        "with.wav": True, "without.wav": False, "unreadable.mp3": None,
    }


def test_scan_reads_art_for_an_unchanged_file_it_never_checked(tmp_path):
    # A row indexed before the column existed holds NULL; the next scan
    # reads it once even though the file is unchanged, and still counts
    # it as unchanged, since the file is.
    library_root = tmp_path / "music"
    library_root.mkdir()
    _write_wav(library_root / "with.wav", with_art=True)

    database, local_files, scanner, location = _scan_location(
        tmp_path, library_root,
    )
    scanner.scan(location)
    with database.transaction() as connection:
        connection.execute("UPDATE local_files SET has_art = NULL")

    summary = scanner.scan(location)

    assert (summary.added, summary.updated, summary.unchanged) == (0, 0, 1)
    assert _has_art_by_path(database, local_files) == {"with.wav": True}


def test_index_single_file_records_embedded_art(tmp_path):
    library_root = tmp_path / "music"
    library_root.mkdir()
    _write_wav(library_root / "with.wav", with_art=True)

    database, local_files, _, location = _scan_location(
        tmp_path, library_root,
    )
    with database.transaction() as connection:
        indexed = index_single_file(
            location, "with.wav", local_files, connection,
        )

    assert indexed.has_art is True

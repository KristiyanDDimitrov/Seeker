import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.library.matcher import TrackMatcher
from seeker.library.scanner import LibraryUnavailableError
from seeker.library.service import (
    LibraryLocationPathAlreadyRegisteredError,
    LibraryService,
)
from seeker.models.local_file import LocalFile
from seeker.models.track import Track


def make_service(tmp_path) -> LibraryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return LibraryService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
    )


def make_service_with_matcher(tmp_path) -> LibraryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    track_matcher = TrackMatcher(
        database,
        TrackRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
    )

    return LibraryService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
        track_matcher=track_matcher,
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


def test_has_scanned_library_false_with_no_local_files(tmp_path):
    service = make_service(tmp_path)

    assert service.has_scanned_library() is False


def test_has_scanned_library_true_after_a_real_scan_finds_files(tmp_path):
    library_root = tmp_path / "music"
    library_root.mkdir()
    (library_root / "song.mp3").write_bytes(b"not real audio")

    service = make_service(tmp_path)
    service.add_location("Main", str(library_root))
    service.scan_all()

    assert service.has_scanned_library() is True


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


def test_scan_all_returns_aggregated_totals_across_locations(tmp_path):
    root_a = tmp_path / "music-a"
    root_b = tmp_path / "music-b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "one.mp3").write_bytes(b"not real audio")
    (root_b / "two.mp3").write_bytes(b"not real audio")
    (root_b / "three.mp3").write_bytes(b"not real audio")

    service = make_service(tmp_path)
    service.add_location("a", str(root_a))
    service.add_location("b", str(root_b))

    totals = service.scan_all()

    assert totals == {"added": 3, "updated": 0, "removed": 0, "unchanged": 0}

    # A second scan with nothing changed on disk reports everything as
    # unchanged, still aggregated across both locations.
    totals_again = service.scan_all()
    assert totals_again == {
        "added": 0, "updated": 0, "removed": 0, "unchanged": 3,
    }


def test_scan_and_match_requires_a_track_matcher(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(RuntimeError, match="track_matcher"):
        service.scan_and_match()


def test_scan_and_match_chains_scan_then_match_in_one_call(tmp_path):
    library_root = tmp_path / "music"
    library_root.mkdir()
    (library_root / "3AMDISCO - Get Back.wav").write_bytes(b"not real audio")

    service = make_service_with_matcher(tmp_path)
    service.add_location("main", str(library_root))

    with service.database.transaction() as connection:
        service.track_matcher.tracks.save(
            Track(
                id="track1",
                title="Get Back",
                artist="3amdisco",
                album="Get Back EP",
                duration_ms=200_000,
            ),
            connection,
        )

    # Before scan_and_match, nothing has been scanned or matched at all.
    assert service.has_scanned_library() is False

    result = service.scan_and_match()

    # scan_all()'s keys and match_all()'s keys, combined in one dict —
    # this is the real regression this chaining fixes: a plain scan_all()
    # alone would leave "auto"/"needs_review"/"unmatched" entirely absent
    # (and the track unmatched) until a separate match_all() call.
    assert result["added"] == 1
    assert result["auto"] == 1
    assert result["needs_review"] == 0
    assert result["unmatched"] == 0

    with service.database.transaction() as connection:
        stored = service.track_matcher.track_matches.get_by_track_id(
            "track1", connection
        )

    assert stored is not None
    assert stored.match_method == "auto"

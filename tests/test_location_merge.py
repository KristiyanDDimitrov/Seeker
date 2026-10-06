"""Merging a nested library location into the one kept: every match,
Review rejection, analysis, cleanup record and playlist destination of
the merged location's files lands on the kept location's rows for the
same physical files (HISTORY §172).
"""
from pathlib import Path

import pytest

from seeker.database.connection import Database
from seeker.database.repositories.duplicate_cleanup_repository import (
    DuplicateCleanupRepository,
)
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.rejection_repository import (
    RejectionRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.errors import LibraryLocationNotFoundError
from seeker.library.nesting import NestedPathMap, nested_path_map
from seeker.library.scanner import LibraryUnavailableError
from seeker.library.service import LibraryService, LocationsNotNestedError
from seeker.models.duplicate_cleanup import DuplicateCleanup
from seeker.models.library_location import LibraryLocation
from seeker.models.location_merge import LocationMergeSummary
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch

# Relative to the drive root; Test sits inside Music, Music inside it.
FILES = (
    "loose.mp3",
    "Music/House/a.mp3",
    "Music/House/b.mp3",
    "Music/Test/c.mp3",
)


def rel(*parts: str) -> str:
    """A relative path in the scanner's own spelling."""
    return str(Path(*parts))


@pytest.fixture
def drive(tmp_path) -> Path:
    root = tmp_path / "Drive"

    for relative in FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(relative.encode())

    return root


def make_service(tmp_path, drive: Path) -> LibraryService:
    """x9-pro, Music and Test registered the way builds before the
    nesting guard did, and scanned.
    """
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    service = LibraryService(
        database,
        LibraryLocationRepository(),
        LocalFileRepository(),
        playlist_repo=PlaylistRepository(),
    )

    with database.transaction() as connection:
        for name, path in (
                ("x9-pro", drive),
                ("Music", drive / "Music"),
                ("Test", drive / "Music" / "Test"),
        ):
            service.locations.add(
                LibraryLocation(name=name, path=str(path), added_at="t"),
                connection,
            )

    service.scan_all()

    return service


def location_id(service: LibraryService, name: str) -> int:
    with service.database.transaction() as connection:
        location = service.locations.get_by_name(name, connection)

    assert location is not None
    assert location.id is not None

    return location.id


def file_id(service: LibraryService, name: str, relative: str) -> int:
    with service.database.transaction() as connection:
        file = service.local_files.get_by_location_and_relative_path(
            location_id(service, name), relative, connection,
        )

    assert file is not None
    assert file.id is not None

    return file.id


def add_track(service: LibraryService, track_id: str) -> None:
    with service.database.transaction() as connection:
        TrackRepository().save(
            Track(
                id=track_id,
                title=track_id,
                artist="artist",
                album="album",
                duration_ms=1,
            ),
            connection,
        )


def match(
        service: LibraryService,
        track_id: str,
        local_file_id: int,
        *,
        confirmed: bool = False,
) -> None:
    add_track(service, track_id)

    with service.database.transaction() as connection:
        TrackMatchRepository().upsert(
            TrackMatch(
                track_id=track_id,
                matched_at="t",
                local_file_id=local_file_id,
                match_method="auto",
                score=0.9,
                confirmed_at="c" if confirmed else None,
            ),
            connection,
        )


def matched_file(service: LibraryService, track_id: str) -> tuple:
    with service.database.transaction() as connection:
        row = TrackMatchRepository().get_by_track_id(track_id, connection)

    assert row is not None

    return row.local_file_id, row.match_method, row.confirmed_at


def location_names(service: LibraryService) -> list[str]:
    return sorted(location.name for location, _ in service.list_locations())


def test_merging_an_inner_location_moves_its_matches_to_the_outer(
        tmp_path, drive,
):
    service = make_service(tmp_path, drive)
    match(service, "t1", file_id(service, "Test", "c.mp3"), confirmed=True)

    summary = service.merge_location("Test", "Music")

    assert summary == LocationMergeSummary(
        merged_name="Test",
        kept_name="Music",
        files_merged=1,
        files_forgotten=0,
        matches_moved=1,
        matches_cleared=0,
        analyses_kept=0,
        playlists_moved=0,
        playlists_cleared=0,
        was_default=False,
    )
    assert matched_file(service, "t1") == (
        file_id(service, "Music", rel("Test", "c.mp3")),
        "auto",
        "c",
    )
    assert location_names(service) == ["Music", "x9-pro"]


def test_merging_an_outer_location_forgets_what_lies_outside_the_kept(
        tmp_path, drive,
):
    service = make_service(tmp_path, drive)
    match(service, "inside", file_id(
        service, "x9-pro", rel("Music", "House", "a.mp3"),
    ))
    match(service, "outside", file_id(service, "x9-pro", "loose.mp3"))

    summary = service.merge_location("x9-pro", "Music")

    assert (
        summary.files_merged,
        summary.files_forgotten,
        summary.matches_moved,
        summary.matches_cleared,
    ) == (3, 1, 1, 1)
    assert matched_file(service, "inside")[0] == file_id(
        service, "Music", rel("House", "a.mp3"),
    )
    assert matched_file(service, "outside") == (None, None, None)
    assert location_names(service) == ["Music", "Test"]


def test_a_file_the_kept_location_has_not_indexed_is_forgotten(
        tmp_path, drive,
):
    service = make_service(tmp_path, drive)
    # Indexed under Test only: Music has not been scanned since.
    (drive / "Music" / "Test" / "new.mp3").write_bytes(b"new")
    service.scan_all()
    with service.database.transaction() as connection:
        service.local_files.delete_by_id(
            file_id(service, "Music", rel("Test", "new.mp3")),
            connection,
        )
    match(service, "t1", file_id(service, "Test", "new.mp3"))

    summary = service.merge_location("Test", "Music")

    assert (summary.files_merged, summary.files_forgotten) == (1, 1)
    assert (summary.matches_moved, summary.matches_cleared) == (0, 1)
    assert matched_file(service, "t1") == (None, None, None)


def test_rejections_move_to_the_kept_file(tmp_path, drive):
    service = make_service(tmp_path, drive)
    add_track(service, "t1")
    rejections = RejectionRepository()
    with service.database.transaction() as connection:
        rejections.add_local_match(
            "t1", file_id(service, "Test", "c.mp3"), "r", connection,
        )

    service.merge_location("Test", "Music")

    with service.database.transaction() as connection:
        rejected = rejections.get_rejected_local_file_ids(connection)

    assert rejected == {
        "t1": {file_id(service, "Music", rel("Test", "c.mp3"))},
    }


def analysis(service: LibraryService, local_file_id: int) -> tuple:
    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT bpm, camelot_key, fingerprint, tagged_at "
            "FROM local_files WHERE id = ?",
            (local_file_id,),
        ).fetchone()

    return tuple(row)


def test_analysis_fills_only_what_the_kept_file_lacks(tmp_path, drive):
    service = make_service(tmp_path, drive)
    old = file_id(service, "x9-pro", rel("Music", "House", "a.mp3"))
    kept = file_id(service, "Music", rel("House", "a.mp3"))
    with service.database.transaction() as connection:
        service.local_files.update_analysis(old, 120.0, "8A", 0.9, connection)
        service.local_files.update_fingerprint(old, "FP", 1.0, "f", connection)
        service.local_files.mark_tagged(old, "tagged", connection)
        # The kept row's own key analysis is never overwritten.
        service.local_files.update_analysis(kept, 128.0, "5A", 0.8, connection)

    summary = service.preview_merge_location("x9-pro", "Music")
    service.merge_location("x9-pro", "Music")

    assert summary.analyses_kept == 1
    assert analysis(service, kept) == (128.0, "5A", "FP", "tagged")


def test_analysis_of_a_file_that_changed_since_is_not_carried(
        tmp_path, drive,
):
    service = make_service(tmp_path, drive)
    old = file_id(service, "Test", "c.mp3")
    with service.database.transaction() as connection:
        service.local_files.update_analysis(old, 120.0, "8A", 0.9, connection)
        connection.execute(
            "UPDATE local_files SET size_bytes = size_bytes + 1 WHERE id = ?",
            (old,),
        )

    summary = service.merge_location("Test", "Music")

    assert summary.analyses_kept == 0
    assert analysis(service, file_id(
        service, "Music", rel("Test", "c.mp3"),
    )) == (None, None, None, None)


def set_destination(
        service: LibraryService,
        playlist_id: str,
        location: str,
        subfolder: str | None,
) -> None:
    playlists = PlaylistRepository()

    with service.database.transaction() as connection:
        playlists.save(
            Playlist(id=playlist_id, name=playlist_id, track_count=0),
            connection,
        )
        playlists.set_destination(
            playlist_id, location_id(service, location), subfolder,
            connection,
        )


def destination(service: LibraryService, playlist_id: str) -> tuple:
    with service.database.transaction() as connection:
        playlist = PlaylistRepository().get_by_id(playlist_id, connection)
        names = {
            location.id: location.name
            for location in service.locations.get_all(connection)
        }

    assert playlist is not None

    return (
        names.get(playlist.download_location_id),
        playlist.download_subfolder,
    )


def test_destinations_in_an_outer_location_name_the_same_folder(
        tmp_path, drive,
):
    service = make_service(tmp_path, drive)
    set_destination(service, "house", "x9-pro", "Music/House")
    set_destination(service, "music", "x9-pro", "Music")
    set_destination(service, "loose", "x9-pro", "Elsewhere")
    set_destination(service, "root", "x9-pro", None)

    summary = service.merge_location("x9-pro", "Music")

    assert (summary.playlists_moved, summary.playlists_cleared) == (2, 2)
    assert destination(service, "house") == ("Music", "House")
    assert destination(service, "music") == ("Music", None)
    assert destination(service, "loose") == (None, None)
    assert destination(service, "root") == (None, None)


def test_destinations_in_an_inner_location_gain_its_folder(tmp_path, drive):
    service = make_service(tmp_path, drive)
    set_destination(service, "nested", "Test", "Music/Test")
    set_destination(service, "root", "Test", None)

    summary = service.merge_location("Test", "Music")

    assert (summary.playlists_moved, summary.playlists_cleared) == (2, 0)
    assert destination(service, "nested") == ("Music", "Test/Music/Test")
    assert destination(service, "root") == ("Music", "Test")


def test_duplicate_cleanup_records_move_to_the_kept_location(
        tmp_path, drive,
):
    service = make_service(tmp_path, drive)
    with service.database.transaction() as connection:
        DuplicateCleanupRepository().add(
            DuplicateCleanup(
                occurred_at="t",
                files_deleted=1,
                bytes_freed=10,
                location_id=location_id(service, "Test"),
            ),
            connection,
        )

    service.merge_location("Test", "Music")

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT location_id FROM duplicate_cleanups"
        ).fetchone()

    assert row[0] == location_id(service, "Music")


def test_merging_the_default_location_reports_it(tmp_path, drive):
    service = make_service(tmp_path, drive)

    summary = service.merge_location(
        "Test", "Music", default_location_id=location_id(service, "Test"),
    )

    assert summary.was_default


def test_preview_reports_the_merge_and_changes_nothing(tmp_path, drive):
    service = make_service(tmp_path, drive)
    match(service, "t1", file_id(service, "Test", "c.mp3"))
    set_destination(service, "p", "Test", None)
    before = file_id(service, "Test", "c.mp3")

    preview = service.preview_merge_location("Test", "Music")

    assert matched_file(service, "t1")[0] == before
    assert location_names(service) == ["Music", "Test", "x9-pro"]
    assert service.merge_location("Test", "Music") == preview


def test_locations_that_are_not_nested_are_refused(tmp_path, drive):
    service = make_service(tmp_path, drive)
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    service.add_location("Elsewhere", str(elsewhere))

    with pytest.raises(LocationsNotNestedError):
        service.merge_location("Elsewhere", "Music")

    with pytest.raises(LocationsNotNestedError):
        service.merge_location("Music", "Music")


def test_an_unknown_location_is_refused(tmp_path, drive):
    service = make_service(tmp_path, drive)

    with pytest.raises(LibraryLocationNotFoundError):
        service.merge_location("Nope", "Music")


def test_an_unreachable_location_is_refused(tmp_path, drive):
    service = make_service(tmp_path, drive)
    drive.rename(tmp_path / "Unmounted")

    with pytest.raises(LibraryUnavailableError):
        service.merge_location("Test", "Music")

    assert location_names(service) == ["Music", "Test", "x9-pro"]


# --- Path mapping ------------------------------------------------------


def test_nested_path_map_prefixes_an_inner_path(tmp_path):
    path_map = nested_path_map(tmp_path / "A" / "B", tmp_path)

    assert path_map == NestedPathMap(prefix=("A", "B"), source_is_inner=True)
    assert path_map.map_relative_path("c.mp3") == rel(
        "A", "B", "c.mp3",
    )


def test_nested_path_map_strips_the_prefix_from_an_outer_path(tmp_path):
    path_map = nested_path_map(tmp_path, tmp_path / "A")

    assert path_map is not None
    assert path_map.map_relative_path(rel("A", "c.mp3")) == "c.mp3"
    assert path_map.map_relative_path("c.mp3") is None
    assert path_map.map_relative_path("A") is None


def test_nested_path_map_is_none_for_siblings(tmp_path):
    assert nested_path_map(tmp_path / "A", tmp_path / "B") is None

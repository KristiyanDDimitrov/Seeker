"""What keeps the polls cheap at production library size (HISTORY
§165): default reads leave fingerprints out, and the Dashboard reads
only one playlist's rows."""

from pathlib import Path

import pytest

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile


def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return database


def add_fingerprinted_file(database: Database) -> int:
    repository = LocalFileRepository()

    with database.transaction() as connection:
        locations = LibraryLocationRepository()
        locations.add(
            LibraryLocation(
                name="Music", path="/music", added_at="2026-01-01",
            ),
            connection,
        )
        location = locations.get_by_name("Music", connection)
        assert location is not None and location.id is not None
        location_id = location.id
        repository.upsert(
            LocalFile(
                location_id=location_id,
                relative_path="a.mp3",
                filename="a.mp3",
                format="mp3",
                size_bytes=1,
                mtime=0.0,
                scanned_at="2026-01-01",
                tag_title="A",
            ),
            connection,
        )
        local_file = repository.get_by_location_and_relative_path(
            location_id, "a.mp3", connection,
        )
        assert local_file is not None and local_file.id is not None
        repository.update_fingerprint(
            local_file.id, "AQAA-fingerprint", 180.0, "2026-01-02",
            connection,
        )

    return location_id


# --- §22.1: fingerprints only where they are compared ------------------


def test_default_reads_leave_the_fingerprint_columns_out(tmp_path):
    database = make_database(tmp_path)
    location_id = add_fingerprinted_file(database)
    repository = LocalFileRepository()

    with database.transaction() as connection:
        everything = repository.get_all(connection)
        for_location = repository.get_all_for_location(
            location_id, connection,
        )
        by_path = repository.get_by_location_and_relative_path(
            location_id, "a.mp3", connection,
        )
        assert by_path is not None and by_path.id is not None
        by_id = repository.get_by_id(by_path.id, connection)

    for local_file in [*everything, *for_location, by_path, by_id]:
        assert local_file is not None
        assert local_file.tag_title == "A"
        assert local_file.fingerprint is None
        assert local_file.fingerprint_duration is None
        assert local_file.fingerprint_computed_at is None


def test_the_fingerprint_read_returns_the_fingerprint_columns(tmp_path):
    database = make_database(tmp_path)
    location_id = add_fingerprinted_file(database)

    with database.transaction() as connection:
        (local_file,) = (
            LocalFileRepository().get_all_for_location_with_fingerprints(
                location_id, connection,
            )
        )

    assert local_file.tag_title == "A"
    assert local_file.fingerprint == "AQAA-fingerprint"
    assert local_file.fingerprint_duration == 180.0
    assert local_file.fingerprint_computed_at == "2026-01-02"


@pytest.mark.parametrize(
    ("query", "index"),
    [
        (
            "SELECT * FROM track_matches WHERE local_file_id = ?",
            "idx_track_matches_local_file_id",
        ),
        (
            "SELECT * FROM download_requests WHERE track_id = ?",
            "idx_download_requests_track_id",
        ),
        (
            "SELECT * FROM download_requests WHERE status = ?"
            " ORDER BY requested_at",
            "idx_download_requests_status_requested_at",
        ),
        # Without PlaylistRepository's `ORDER BY p.name`, which sorts
        # whatever index finds the rows.
        (
            "SELECT p.id FROM playlists p"
            " JOIN playlist_tracks pt ON pt.playlist_id = p.id"
            " WHERE pt.track_id = ?",
            "idx_playlist_tracks_track_id",
        ),
    ],
)
def test_lookups_by_a_foreign_key_or_status_use_an_index(
        tmp_path, query, index,
):
    database = make_database(tmp_path)

    with database.transaction() as connection:
        plan = "\n".join(
            row[3]
            for row in connection.execute(
                f"EXPLAIN QUERY PLAN {query}", ("x",),
            )
        )

    assert f"USING INDEX {index}" in plan
    assert "TEMP B-TREE" not in plan

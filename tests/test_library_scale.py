"""A library location of any size scans, matches and cleans up.

SQLite caps the number of bound parameters per statement
(`SQLITE_LIMIT_VARIABLE_NUMBER`, 32,766 on current builds), so anything
binding one `?` per file breaks on a big enough location.
"""
import logging
import sqlite3

import seeker.library.scanner as scanner_module
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.library.scanner import LibraryScanner, index_single_file
from seeker.models.library_location import LibraryLocation
from test_library_integrity import (
    local_file_ids,
    make_scenario,
    match_row,
    unmatched_ids,
)

# One more than SQLite's default variable limit.
OVER_THE_VARIABLE_LIMIT = 32_767


def insert_bulk_rows(matcher, count: int) -> set[str]:
    paths = {f"bulk/{index:05d}.mp3" for index in range(count)}

    with matcher.database.transaction() as connection:
        connection.executemany(
            """
            INSERT INTO local_files (
                location_id, relative_path, filename, format,
                size_bytes, mtime, scanned_at
            )
            VALUES (1, ?, ?, 'mp3', 1, 0, '2026-01-01')
            """,
            [(path, path.rsplit("/", 1)[1]) for path in paths],
        )

    return paths


# --- §7.1: delete_missing past the variable limit -------------------------

def test_delete_missing_handles_more_seen_paths_than_sqlite_variables(
        tmp_path,
):
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    service.confirm_match("t1")
    seen = insert_bulk_rows(matcher, OVER_THE_VARIABLE_LIMIT)

    with matcher.database.transaction() as connection:
        matcher.local_files.delete_missing(1, seen, connection)

    # The matched file was not seen, so it goes, and so does its match.
    assert len(local_file_ids(matcher)) == OVER_THE_VARIABLE_LIMIT
    assert match_row(matcher) == (None, None, None, None)
    assert unmatched_ids(matcher) == ["t1"]


def test_delete_missing_removes_more_rows_than_sqlite_variables(tmp_path):
    service, matcher = make_scenario(tmp_path)
    service.scan_and_match()
    insert_bulk_rows(matcher, OVER_THE_VARIABLE_LIMIT)

    with matcher.database.transaction() as connection:
        matcher.local_files.delete_missing(1, set(), connection)

    assert local_file_ids(matcher) == []
    assert match_row(matcher) == (None, None, None, None)


# --- §7.2: the scanner's walk and transaction shape -----------------------

def scan_tree(tmp_path, relative_paths: list[str]):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    root = tmp_path / "music"

    for relative_path in relative_paths:
        (root / relative_path).parent.mkdir(parents=True, exist_ok=True)
        (root / relative_path).write_bytes(b"")

    with database.transaction() as connection:
        LibraryLocationRepository(database).add(
            LibraryLocation(name="main", path=str(root), added_at="x"),
            connection,
        )
        location = LibraryLocationRepository(database).get_by_name(
            "main", connection,
        )

    local_files = LocalFileRepository(database)
    return database, local_files, LibraryScanner(local_files, database), location


def indexed_paths(database, local_files) -> list[str]:
    with database.transaction() as connection:
        return sorted(f.relative_path for f in local_files.get_all(connection))


def test_scan_skips_hidden_directories_but_not_dot_led_audio_files(
        tmp_path,
):
    database, local_files, scanner, location = scan_tree(tmp_path, [
        "song.mp3",
        ".dot-led song.mp3",
        ".Trashes/501/deleted.mp3",
        ".Spotlight-V100/x.mp3",
        "Artist/.hidden/y.mp3",
        "Artist/._song.mp3",
    ])

    scanner.scan(location)

    assert indexed_paths(database, local_files) == [
        ".dot-led song.mp3", "song.mp3",
    ]


def test_scan_logs_an_unreadable_tag_at_debug_with_the_traceback(
        tmp_path, monkeypatch, caplog,
):
    database, local_files, scanner, location = scan_tree(
        tmp_path, ["song.mp3"],
    )

    def broken(*args, **kwargs):
        raise ValueError("corrupt frame")

    monkeypatch.setattr("seeker.library.scanner.MutagenFile", broken)

    with caplog.at_level(logging.DEBUG, logger="seeker.library.scanner"):
        scanner.scan(location)

    [record] = [r for r in caplog.records if "song.mp3" in r.getMessage()]
    assert record.levelno == logging.DEBUG
    assert record.exc_info is not None
    assert indexed_paths(database, local_files) == ["song.mp3"]


def test_scan_reads_tags_without_holding_the_write_lock(
        tmp_path, monkeypatch,
):
    database, local_files, scanner, location = scan_tree(
        tmp_path, [f"{index}.mp3" for index in range(3)],
    )
    could_write: list[bool] = []

    def probe_the_lock(*args, **kwargs):
        # Stands in for a slow tag read; meanwhile another writer (the
        # download poll, tagging) must be able to take the lock.
        other = sqlite3.connect(database.path, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
            could_write.append(True)
        except sqlite3.OperationalError:
            could_write.append(False)
        finally:
            other.close()

    monkeypatch.setattr("seeker.library.scanner.MutagenFile", probe_the_lock)

    scanner.scan(location)

    assert could_write == [True, True, True]
    assert len(indexed_paths(database, local_files)) == 3


def test_scan_keeps_a_row_another_writer_indexes_mid_scan(
        tmp_path, monkeypatch,
):
    """A download placed while the scan walks must survive the scan's
    missing-file cleanup, even if the walk passed its folder already.
    """
    database, local_files, scanner, location = scan_tree(
        tmp_path, ["a.mp3"],
    )
    real_read = scanner_module._read_tags
    placed: list[str] = []

    def place_a_download(file_path):
        if not placed:
            placed.append("zz-new.mp3")
            (tmp_path / "music" / "zz-new.mp3").write_bytes(b"")
            with database.transaction() as connection:
                index_single_file(
                    location, "zz-new.mp3", local_files, connection,
                )
        return real_read(file_path)

    monkeypatch.setattr(scanner_module, "_read_tags", place_a_download)

    summary = scanner.scan(location)

    assert summary["removed"] == 0
    assert indexed_paths(database, local_files) == ["a.mp3", "zz-new.mp3"]

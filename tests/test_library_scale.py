"""A library location of any size scans, matches and cleans up.

SQLite caps the number of bound parameters per statement
(`SQLITE_LIMIT_VARIABLE_NUMBER`, 32,766 on current builds), so anything
binding one `?` per file breaks on a big enough location.
"""
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

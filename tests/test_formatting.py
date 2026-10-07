import ast
from datetime import datetime
from pathlib import Path

import pytest

import seeker
from seeker.formatting import (
    format_duration_seconds,
    format_file_size,
    format_timestamp,
    remote_basename,
)


def test_format_timestamp_none_renders_never():
    assert format_timestamp(None) == "Never"


def test_format_timestamp_unparseable_renders_never():
    assert format_timestamp("not a real timestamp") == "Never"


def test_format_timestamp_converts_aware_utc_to_local():
    # This codebase's own standing convention: matched_at/completed_at/
    # tagged_at are always timezone-AWARE UTC strings, never naive — a
    # regression that dropped the astimezone() conversion (rendering
    # the raw UTC wall-clock time as if it were already local) would
    # only be caught by comparing against a real, independently-
    # computed local conversion, not the UTC string itself.
    value = "2026-08-30T12:00:00+00:00"
    expected_local = datetime.fromisoformat(value).astimezone()
    expected = expected_local.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")

    assert format_timestamp(value) == expected


def test_format_file_size_bytes():
    assert format_file_size(500) == "500 B"


def test_format_file_size_kb():
    assert format_file_size(2048) == "2.0 KB"


def test_format_file_size_mb():
    assert format_file_size(12_257_951) == "11.7 MB"


def test_format_file_size_none():
    assert format_file_size(None) == "?"


def test_format_duration_seconds_under_a_minute():
    assert format_duration_seconds(42) == "42s"


def test_format_duration_seconds_minutes_and_seconds():
    assert format_duration_seconds(125) == "2m 5s"


def test_format_duration_seconds_hours_and_minutes():
    assert format_duration_seconds(3725) == "1h 2m"


def test_format_duration_seconds_never_negative():
    assert format_duration_seconds(-5) == "0s"


def test_nothing_outside_ui_imports_the_qt_package():
    """The CLI and the services must run without PySide6's widgets;
    `main_ui.py` is the GUI's own entry point and the one exception."""
    source_root = Path(seeker.__file__).parent
    offenders = []

    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if relative.parts[0] == "ui" or relative.name == "main_ui.py":
            continue

        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            if any(
                    name == "seeker.ui" or name.startswith("seeker.ui.")
                    for name in names
            ):
                offenders.append(str(relative))

    assert offenders == []


@pytest.mark.parametrize(
    ("remote_path", "expected"),
    [
        ("@@peer\\Music\\Club\\Track (Mix).flac", "Track (Mix).flac"),
        ("music/club/Track.mp3", "Track.mp3"),
        ("Track.mp3", "Track.mp3"),
    ],
)
def test_remote_basename_splits_either_separator(remote_path, expected):
    assert remote_basename(remote_path) == expected

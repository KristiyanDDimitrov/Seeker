from datetime import datetime

from seeker.ui.formatting import (
    format_duration_seconds,
    format_file_size,
    format_speed,
    format_timestamp,
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


def test_format_speed_renders_per_second():
    assert format_speed(1024) == "1.0 KB/s"


def test_format_speed_none_or_zero_is_unknown():
    assert format_speed(None) == "?"
    assert format_speed(0) == "?"


def test_format_duration_seconds_under_a_minute():
    assert format_duration_seconds(42) == "42s"


def test_format_duration_seconds_minutes_and_seconds():
    assert format_duration_seconds(125) == "2m 5s"


def test_format_duration_seconds_hours_and_minutes():
    assert format_duration_seconds(3725) == "1h 2m"


def test_format_duration_seconds_never_negative():
    assert format_duration_seconds(-5) == "0s"

import stat
import sys

import pytest

from seeker.atomic_file import write_text_locked

skip_on_windows = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX chmod semantics don't apply on Windows",
)


def test_write_text_locked_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "file.json"

    write_text_locked(path, "hello")

    assert path.read_text() == "hello"


def test_write_text_locked_overwrites_existing_content(tmp_path):
    path = tmp_path / "file.json"
    path.write_text("old")

    write_text_locked(path, "new")

    assert path.read_text() == "new"


def test_write_text_locked_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "file.json"

    write_text_locked(path, "hello")

    assert [p.name for p in tmp_path.iterdir()] == ["file.json"]


@skip_on_windows
def test_write_text_locked_sets_restrictive_permissions(tmp_path):
    path = tmp_path / "file.json"

    write_text_locked(path, "hello")

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600

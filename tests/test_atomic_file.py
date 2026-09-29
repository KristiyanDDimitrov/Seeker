import stat
import sys
from pathlib import Path

import pytest

from seeker.atomic_file import write_text_atomic, write_text_locked

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


@skip_on_windows
def test_write_text_atomic_keeps_the_existing_files_permissions(tmp_path):
    # slskd.yml is read by slskd inside its container; an edit must not
    # change who can read it.
    path = tmp_path / "slskd.yml"
    path.write_text("old")
    path.chmod(0o644)

    write_text_atomic(path, "new")

    assert path.read_text() == "new"
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_write_text_atomic_failure_leaves_the_original_and_no_temp_file(
        tmp_path, monkeypatch,
):
    path = tmp_path / "slskd.yml"
    path.write_text("original")
    real_write_text = Path.write_text

    def dies_part_way(self, data, *args, **kwargs):
        real_write_text(self, data[:3], *args, **kwargs)
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(Path, "write_text", dies_part_way)

    with pytest.raises(OSError, match="disk full"):
        write_text_atomic(path, "replacement")

    assert path.read_text() == "original"
    assert [child.name for child in tmp_path.iterdir()] == ["slskd.yml"]

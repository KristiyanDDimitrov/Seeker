import os
import stat
import sys

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

    def fails(fd):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "fsync", fails)

    with pytest.raises(OSError, match="disk full"):
        write_text_atomic(path, "replacement")

    assert path.read_text() == "original"
    assert [child.name for child in tmp_path.iterdir()] == ["slskd.yml"]


@skip_on_windows
def test_write_text_locked_creates_the_temp_file_0600_exclusively(
        tmp_path, monkeypatch,
):
    # chmod after the write would leave a window where the credential
    # is readable at the process umask (0644 by default on macOS).
    path = tmp_path / "token.json"
    real_open = os.open
    created: list[tuple[str, int, int]] = []

    def recording_open(file, flags, mode=0o777, *args, **kwargs):
        created.append((os.fspath(file), flags, mode))
        return real_open(file, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)

    write_text_locked(path, "secret")

    temp_creates = [
        (flags, mode) for name, flags, mode in created
        if name.startswith(f"{path}.") and name.endswith(".tmp")
    ]
    assert len(temp_creates) == 1
    flags, mode = temp_creates[0]
    assert flags & os.O_CREAT and flags & os.O_EXCL
    assert mode == 0o600


def test_write_text_locked_fsyncs_the_file_before_replacing(
        tmp_path, monkeypatch,
):
    path = tmp_path / "token.json"
    real_fsync = os.fsync
    synced_sizes: list[int] = []

    def recording_fsync(fd):
        real_fsync(fd)
        if not path.exists():
            synced_sizes.append(os.fstat(fd).st_size)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    write_text_locked(path, "secret")

    assert synced_sizes == [len("secret")]


def test_write_text_locked_failure_leaves_the_original_and_no_temp_file(
        tmp_path, monkeypatch,
):
    path = tmp_path / "token.json"
    path.write_text("original")

    def fails(fd):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "fsync", fails)

    with pytest.raises(OSError, match="disk full"):
        write_text_locked(path, "replacement")

    assert path.read_text() == "original"
    assert [child.name for child in tmp_path.iterdir()] == ["token.json"]

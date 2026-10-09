import contextlib
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Replace `path`'s contents with `text` in one step.

    Writes and fsyncs a sibling temp file (same directory, so
    `os.replace()` is a same-filesystem atomic rename) and renames it
    over `path`, so a crash, full disk or power cut mid-write leaves the
    old file intact rather than a truncated one. An existing file's
    permission bits carry over; the temp file is removed if anything
    fails.
    """
    _write_atomic(path, text, mode=None)


def write_text_locked(path: Path, text: str) -> None:
    """Write `text` to `path` atomically and chmod it 0600.

    Used for files holding credentials (config.json, the Spotify token
    cache): on top of `write_text_atomic`'s guarantees, the file must
    never be readable by anyone but this user, including the temp file
    mid-write. `chmod` is a no-op on Windows; the suppression mirrors
    config_store.save_config's own long-standing tolerance for that.
    """
    _write_atomic(path, text, mode=0o600)


def make_private_dir(path: Path) -> None:
    """Create `path` if it is missing and leave it 0700.

    For Seeker's own data, log and cache directories: on Linux their
    parents are commonly 0755, so a directory at the umask would let
    another local user read the database, the logs and slskd's
    downloads. `mkdir(mode=)` is masked by the umask and never touches
    an existing directory, so the `chmod` does the work, and it fixes a
    directory an earlier version created. Missing parents keep the
    umask: they are the platform's. On Windows `chmod` sets only the
    read-only flag, which 0700 leaves clear.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _write_atomic(path: Path, text: str, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    # O_EXCL: never write through a file (or symlink) someone else put
    # at the temp name. A locked file is 0600 from creation, not chmod'd
    # after the write, so the secret is never readable at the umask.
    fd = os.open(
        temp_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o666 if mode is None else mode,
    )
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        with contextlib.suppress(OSError):
            if mode is not None:
                temp_path.chmod(mode)
            elif path.exists():
                shutil.copymode(path, temp_path)

        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

    _fsync_directory(path.parent)


def rewrite_via_copy(path: Path, rewrite: Callable[[Path], None]) -> None:
    """Change `path` by rewriting a copy of it, then renaming the copy
    over it.

    For edits a library performs in place, such as mutagen growing a
    tag ahead of the audio: `rewrite` gets a sibling copy (same
    directory, so the rename is atomic), and the original stays
    untouched until the finished copy replaces it. Permission bits
    carry over; the copy is removed if anything fails.
    """
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle, path.open("rb") as source:
            shutil.copyfileobj(source, handle)
        shutil.copymode(path, temp_path)

        rewrite(temp_path)

        with temp_path.open("rb+") as handle:
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Persist the rename itself; best effort, since not every platform
    (Windows) can open a directory for fsync."""
    with contextlib.suppress(OSError):
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

import contextlib
import shutil
import uuid
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Replace `path`'s contents with `text` in one step.

    Writes a sibling temp file (same directory, so `Path.replace()` is
    a same-filesystem atomic rename) and renames it over `path`, so a
    crash, full disk or power cut mid-write leaves the old file intact
    rather than a truncated one. An existing file's permission bits
    carry over; the temp file is removed if anything fails.
    """
    _write_atomic(path, text, mode=None)


def write_text_locked(path: Path, text: str) -> None:
    """Write `text` to `path` atomically and chmod it 0600.

    Used for files holding credentials (config.json, the Spotify token
    cache): on top of `write_text_atomic`'s guarantees, the file must
    never be readable by anyone but this user. `chmod` is a no-op on
    Windows; the suppression mirrors config_store.save_config's own
    long-standing tolerance for that.
    """
    _write_atomic(path, text, mode=0o600)


def _write_atomic(path: Path, text: str, mode: int | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    try:
        temp_path.write_text(text)

        with contextlib.suppress(OSError):
            if mode is not None:
                temp_path.chmod(mode)
            elif path.exists():
                shutil.copymode(path, temp_path)

        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

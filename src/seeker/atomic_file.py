import contextlib
import uuid
from pathlib import Path


def write_text_locked(path: Path, text: str) -> None:
    """Write `text` to `path` atomically and chmod it 0600.

    Used for files holding credentials (config.json, the Spotify token
    cache) — a crash, full disk, or power cut mid-write must never leave
    a truncated file where a corrupt-but-half-written one used to be,
    and the file must never be readable by anyone but this user. Writes
    to a sibling temp file first (same directory, so the final
    `Path.replace()` is a same-filesystem atomic rename, not a
    cross-filesystem copy), chmods that, then replaces the real path in
    one step. `chmod` is a no-op on
    Windows; the try/except mirrors config_store.save_config's own
    long-standing tolerance for that.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(text)

    with contextlib.suppress(OSError):
        temp_path.chmod(0o600)

    temp_path.replace(path)

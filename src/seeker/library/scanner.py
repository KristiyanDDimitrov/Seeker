import logging
import os
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

from seeker.audio_formats import AUDIO_EXTENSIONS
from seeker.database.connection import Database
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile

logger = logging.getLogger(__name__)

# Rows written per short scan transaction.
UPSERT_BATCH_SIZE = 200


class LibraryUnavailableError(RuntimeError):
    def __init__(self, path: Path):
        message = f"Library path {path} does not exist or is not a directory."

        # macOS mounts every external drive under /Volumes.
        if path.is_absolute() and path.parts[1:2] == ("Volumes",):
            message += " The drive it lives on may not be connected."

        super().__init__(message)


class LibraryScanner:
    def __init__(
        self,
        local_files: LocalFileRepository,
        database: Database,
    ):
        self.local_files = local_files
        self.database = database

    def scan(self, location: LibraryLocation) -> dict[str, int]:
        # location always comes from LibraryLocationRepository here (the
        # only real caller is LibraryService.scan_all, iterating rows
        # already fetched from the DB), so .id is always populated —
        # None is only possible for a not-yet-persisted LibraryLocation.
        assert location.id is not None

        root = Path(location.path)

        if not root.is_dir():
            raise LibraryUnavailableError(root)

        logger.info("Scanning library location '%s': %s", location.name, root)

        with self.database.transaction() as connection:
            existing_by_relative_path = {
                local_file.relative_path: local_file
                for local_file in self.local_files.get_all_for_location(
                    location.id, connection,
                )
            }

        added = 0
        updated = 0
        unchanged = 0
        seen_relative_paths = set()
        pending: list[LocalFile] = []

        # Tags are read outside any transaction and written in short
        # batches, so a long first scan never holds the write lock
        # while it walks; other writers (the download poll, tagging)
        # otherwise wait out SQLite's 5-second busy timeout and fail
        # with "database is locked" (measured: HISTORY §142).
        for relative_path in _walk_audio_files(root):
            seen_relative_paths.add(relative_path)

            file_path = root / relative_path
            stat = file_path.stat()
            existing = existing_by_relative_path.get(relative_path)

            if (
                    existing is not None
                    and existing.size_bytes == stat.st_size
                    and existing.mtime == stat.st_mtime
            ):
                unchanged += 1
                continue

            pending.append(
                _read_local_file(location.id, relative_path, file_path, stat)
            )

            if existing is None:
                added += 1
            else:
                updated += 1

            if len(pending) >= UPSERT_BATCH_SIZE:
                self._write(pending)
                pending = []

        self._write(pending)

        # Only rows that existed when the scan started: a file another
        # writer indexed meanwhile (a finished download) is not in the
        # walk if its folder was already passed, and must stay.
        removed_ids = [
            local_file.id
            for relative_path, local_file in existing_by_relative_path.items()
            if relative_path not in seen_relative_paths
            and local_file.id is not None
        ]

        with self.database.transaction() as connection:
            self.local_files.delete_by_ids(removed_ids, connection)

        removed = len(removed_ids)

        summary = {
            "added": added,
            "updated": updated,
            "removed": removed,
            "unchanged": unchanged,
        }

        logger.info(
            "Added: %d, Updated: %d, Removed: %d, Unchanged: %d.",
            added, updated, removed, unchanged,
        )

        return summary

    def _write(self, local_files: list[LocalFile]) -> None:
        if not local_files:
            return

        with self.database.transaction() as connection:
            for local_file in local_files:
                self.local_files.upsert(local_file, connection)


def _walk_audio_files(root: Path) -> Iterator[str]:
    """Relative paths of the audio files under `root`.

    Hidden directories (`.Trashes`, `.Spotlight-V100`, `.fseventsd` on
    a volume root) are never entered, and AppleDouble `._*` sidecars
    are skipped. A dot-led audio *file* is still indexed: the user may
    own one.
    """
    for directory, subdirectories, filenames in os.walk(root):
        subdirectories[:] = [
            name for name in subdirectories if not name.startswith(".")
        ]

        for filename in filenames:
            if filename.startswith("._"):
                continue

            file_path = Path(directory) / filename

            if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            if not file_path.is_file():
                continue

            yield str(file_path.relative_to(root))


def index_single_file(
        location: LibraryLocation,
        relative_path: str,
        local_file_repository: LocalFileRepository,
        connection: sqlite3.Connection,
) -> LocalFile:
    # Same invariant as LibraryScanner.scan() above — location is always
    # an already-persisted row by the time indexing happens.
    assert location.id is not None

    file_path = Path(location.path) / relative_path
    stat = file_path.stat()

    local_file = _read_local_file(
        location.id,
        relative_path,
        file_path,
        stat,
    )

    local_file_repository.upsert(local_file, connection)

    indexed = local_file_repository.get_by_location_and_relative_path(
        location.id,
        relative_path,
        connection,
    )

    # We just upserted this exact (location_id, relative_path) row in
    # the same transaction, so it must exist.
    assert indexed is not None

    return indexed


def _read_local_file(
        location_id: int,
        relative_path: str,
        file_path: Path,
        stat: os.stat_result,
) -> LocalFile:
    tag_artist, tag_title, tag_album, duration_ms = _read_tags(file_path)

    return LocalFile(
        location_id=location_id,
        relative_path=relative_path,
        filename=file_path.name,
        format=file_path.suffix.lower().lstrip("."),
        size_bytes=stat.st_size,
        mtime=stat.st_mtime,
        tag_artist=tag_artist,
        tag_title=tag_title,
        tag_album=tag_album,
        duration_ms=duration_ms,
        scanned_at=datetime.now(UTC).isoformat(),
    )


def _read_tags(
        file_path: Path,
) -> tuple[str | None, str | None, str | None, int | None]:
    # Tag parsing can fail in more ways than mutagen.MutagenError covers
    # (corrupt frames, permission errors, decode errors) — any of them
    # means "no tags", not "abort the whole scan" or "drop this file".
    try:
        audio = MutagenFile(file_path, easy=True)

        tag_artist = None
        tag_title = None
        tag_album = None
        duration_ms = None

        if audio is not None:
            if audio.tags:
                tag_artist = _first_tag(audio.tags, "artist")
                tag_title = _first_tag(audio.tags, "title")
                tag_album = _first_tag(audio.tags, "album")

            if audio.info is not None and getattr(audio.info, "length", None):
                duration_ms = int(audio.info.length * 1000)

        return tag_artist, tag_title, tag_album, duration_ms
    except Exception:
        logger.debug("Could not read tags from %s", file_path, exc_info=True)
        return None, None, None, None


def _first_tag(tags: Any, key: str) -> str | None:
    values = tags.get(key)
    return values[0] if values else None

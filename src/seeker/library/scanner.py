import os
import sqlite3
from datetime import datetime, timezone
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


class LibraryUnavailableError(RuntimeError):
    def __init__(self, path: Path):
        super().__init__(
            f"Library path {path} does not exist or is not a "
            f"directory. The drive it lives on may not be connected."
        )


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

        print(f"Scanning library location '{location.name}': {root}")

        added = 0
        updated = 0
        unchanged = 0
        seen_relative_paths = set()

        with self.database.transaction() as connection:
            existing_by_relative_path = {
                local_file.relative_path: local_file
                for local_file in self.local_files.get_all(connection)
                if local_file.location_id == location.id
            }

            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue

                if file_path.name.startswith("._"):
                    continue

                if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
                    continue

                relative_path = str(file_path.relative_to(root))
                seen_relative_paths.add(relative_path)

                stat = file_path.stat()
                existing = existing_by_relative_path.get(relative_path)

                if (
                        existing is not None
                        and existing.size_bytes == stat.st_size
                        and existing.mtime == stat.st_mtime
                ):
                    unchanged += 1
                    continue

                index_single_file(
                    location,
                    relative_path,
                    self.local_files,
                    connection,
                )

                if existing is None:
                    added += 1
                else:
                    updated += 1

            removed = len(
                set(existing_by_relative_path) - seen_relative_paths
            )

            self.local_files.delete_missing(
                location.id,
                seen_relative_paths,
                connection,
            )

        summary = {
            "added": added,
            "updated": updated,
            "removed": removed,
            "unchanged": unchanged,
        }

        print(
            f"  Added: {added}, Updated: {updated}, "
            f"Removed: {removed}, Unchanged: {unchanged}."
        )

        return summary


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
        scanned_at=datetime.now(timezone.utc).isoformat(),
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
        return None, None, None, None


def _first_tag(tags: Any, key: str) -> str | None:
    values = tags.get(key)
    return values[0] if values else None

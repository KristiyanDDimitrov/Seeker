from datetime import datetime, timezone
from pathlib import Path

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.library.scanner import LibraryScanner, LibraryUnavailableError
from seeker.models.library_location import LibraryLocation


class LibraryLocationPathAlreadyRegisteredError(RuntimeError):
    def __init__(self, existing: LibraryLocation):
        self.existing = existing
        super().__init__(
            f"'{existing.path}' is already registered as "
            f"'{existing.name}'."
        )


# Untuned constant — how many auto-suffix attempts (" (2)", " (3)", ...)
# before giving up. A real user is never going to genuinely have this
# many same-named folders; this exists purely as a sane upper bound
# against an infinite loop if something is very wrong.
MAX_NAME_SUFFIX_ATTEMPTS = 50


class LibraryService:
    def __init__(
        self,
        database: Database,
        location_repo: LibraryLocationRepository,
        local_file_repo: LocalFileRepository,
    ):
        self.database = database
        self.locations = location_repo
        self.local_files = local_file_repo
        self.scanner = LibraryScanner(local_file_repo, database)

    def add_location(self, name: str, path: str) -> LibraryLocation:
        resolved_path = Path(path)

        if not resolved_path.is_dir():
            raise LibraryUnavailableError(resolved_path)

        location = LibraryLocation(
            name=name,
            path=str(resolved_path),
            added_at=datetime.now(timezone.utc).isoformat(),
        )

        with self.database.transaction() as connection:
            self.locations.add(location, connection)
            saved = self.locations.get_by_name(name, connection)

        # We just added this exact name in the same transaction, so it
        # must exist.
        assert saved is not None

        print(f"Added library location '{saved.name}': {saved.path}")

        return saved

    def add_location_from_path(self, path: str) -> LibraryLocation:
        """The UI's own "pick a folder, name it later (or never)" flow
        (roadmap item 5) — derives the name from the folder's own
        basename rather than prompting for one first, auto-suffixing
        on a name collision ("Music", "Music (2)", ...). `add_location`
        above (explicit name + path) stays the CLI's own entry point,
        unchanged.
        """
        resolved_path = Path(path)

        if not resolved_path.is_dir():
            raise LibraryUnavailableError(resolved_path)

        resolved_path_str = str(resolved_path)

        with self.database.transaction() as connection:
            existing = self.locations.get_by_path(resolved_path_str, connection)

            if existing is not None:
                raise LibraryLocationPathAlreadyRegisteredError(existing)

            base_name = resolved_path.name
            name = base_name
            suffix = 2

            while self.locations.get_by_name(name, connection) is not None:
                if suffix > MAX_NAME_SUFFIX_ATTEMPTS:
                    raise RuntimeError(
                        f"Could not find a free name for '{base_name}' "
                        f"after {MAX_NAME_SUFFIX_ATTEMPTS} attempts."
                    )

                name = f"{base_name} ({suffix})"
                suffix += 1

            location = LibraryLocation(
                name=name,
                path=resolved_path_str,
                added_at=datetime.now(timezone.utc).isoformat(),
            )
            self.locations.add(location, connection)
            saved = self.locations.get_by_name(name, connection)

        # We just added this exact name in the same transaction, so it
        # must exist.
        assert saved is not None

        print(f"Added library location '{saved.name}': {saved.path}")

        return saved

    def rename_location(self, location_id: int, new_name: str) -> LibraryLocation:
        with self.database.transaction() as connection:
            self.locations.update_name(location_id, new_name, connection)
            saved = self.locations.get_by_id(location_id, connection)

        if saved is None:
            raise RuntimeError(
                f"Location {location_id} no longer exists."
            )

        print(f"Renamed library location to '{saved.name}'.")

        return saved

    def list_locations(self) -> list[tuple[LibraryLocation, bool]]:
        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        return [
            (location, Path(location.path).is_dir())
            for location in locations
        ]

    def has_scanned_library(self) -> bool:
        """Roadmap item 7's Dashboard "next step" CTA needs to
        distinguish "tracks are cached but the library has never been
        scanned" from "already scanned, matching just didn't find
        anything" — but no `last_scanned_at` column exists on
        `library_locations` (a schema change was explicitly out of
        scope for that task), so this approximates it: true once at
        least one `local_files` row exists anywhere. Known, accepted
        limitation: a real scan of a location that genuinely contains
        zero matching audio files would be indistinguishable from
        "never scanned" by this proxy — not solvable without a schema
        change, so not solved here.
        """
        with self.database.transaction() as connection:
            return self.local_files.exists_any(connection)

    def remove_location(self, name: str) -> None:
        with self.database.transaction() as connection:
            location = self.locations.get_by_name(name, connection)

            if location is None:
                print(
                    f"No library location named '{name}' is registered."
                )
                return

            # Loaded from the DB via get_by_name above, so .id is set.
            assert location.id is not None
            self.locations.delete(location.id, connection)

        print(f"Removed library location '{name}'.")

    def scan_all(self) -> None:
        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        if not locations:
            print("No library locations registered.")
            return

        for location in locations:
            if not Path(location.path).is_dir():
                print(
                    f"Skipping '{location.name}' ({location.path}): "
                    f"path is unreachable. The drive it lives on may "
                    f"not be connected."
                )
                continue

            self.scanner.scan(location)

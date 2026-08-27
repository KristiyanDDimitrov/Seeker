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

    def list_locations(self) -> list[tuple[LibraryLocation, bool]]:
        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        return [
            (location, Path(location.path).is_dir())
            for location in locations
        ]

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

import sqlite3

from seeker.database.connection import Database
from seeker.models.library_location import LibraryLocation


class LibraryLocationRepository:
    def __init__(self, database: Database):
        self.database = database

    def add(
            self,
            location: LibraryLocation,
            connection: sqlite3.Connection,
    ) -> None:
        try:
            connection.execute(
                """
                INSERT INTO library_locations (
                    name,
                    path,
                    added_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    location.name,
                    location.path,
                    location.added_at,
                ),
            )
        except sqlite3.IntegrityError as error:
            if "library_locations.name" in str(error):
                raise RuntimeError(
                    f"A location named '{location.name}' already exists."
                ) from error

            if "library_locations.path" in str(error):
                raise RuntimeError(
                    f"A location at '{location.path}' is already "
                    f"registered."
                ) from error

            raise

    def get_all(self, connection: sqlite3.Connection) -> list[LibraryLocation]:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                path,
                added_at
            FROM library_locations
            ORDER BY name
            """
        ).fetchall()

        return [_row_to_location(row) for row in rows]

    def get_by_name(
            self,
            name: str,
            connection: sqlite3.Connection,
    ) -> LibraryLocation | None:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                path,
                added_at
            FROM library_locations
            WHERE name = ?
            """,
            (name,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_location(row)

    def get_by_path(
            self,
            path: str,
            connection: sqlite3.Connection,
    ) -> LibraryLocation | None:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                path,
                added_at
            FROM library_locations
            WHERE path = ?
            """,
            (path,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_location(row)

    def update_name(
            self,
            location_id: int,
            name: str,
            connection: sqlite3.Connection,
    ) -> None:
        try:
            connection.execute(
                "UPDATE library_locations SET name = ? WHERE id = ?",
                (name, location_id),
            )
        except sqlite3.IntegrityError as error:
            if "library_locations.name" in str(error):
                raise RuntimeError(
                    f"A location named '{name}' already exists."
                ) from error

            raise

    def get_by_id(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> LibraryLocation | None:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                path,
                added_at
            FROM library_locations
            WHERE id = ?
            """,
            (location_id,),
        ).fetchone()

        if row is None:
            return None

        return _row_to_location(row)

    def delete(
            self,
            location_id: int,
            connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            DELETE FROM library_locations
            WHERE id = ?
            """,
            (location_id,),
        )


def _row_to_location(row: sqlite3.Row) -> LibraryLocation:
    return LibraryLocation(
        id=row["id"],
        name=row["name"],
        path=row["path"],
        added_at=row["added_at"],
    )

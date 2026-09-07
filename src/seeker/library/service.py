from datetime import datetime, timezone
from pathlib import Path

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.library.matcher import TrackMatcher
from seeker.library.scanner import LibraryScanner, LibraryUnavailableError
from seeker.models.library_location import LibraryLocation
from seeker.models.needs_review_match import NeedsReviewMatch


class LibraryLocationPathAlreadyRegisteredError(RuntimeError):
    def __init__(self, existing: LibraryLocation):
        self.existing = existing
        super().__init__(
            f"'{existing.path}' is already registered as "
            f"'{existing.name}'."
        )


class PlaylistNotFoundError(RuntimeError):
    pass


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
        track_matcher: TrackMatcher | None = None,
        playlist_repo: PlaylistRepository | None = None,
    ):
        self.database = database
        self.locations = location_repo
        self.local_files = local_file_repo
        self.scanner = LibraryScanner(local_file_repo, database)
        # Both optional — only scan_and_match()/get_needs_review_matches()
        # etc. need them (roadmap item 56). Every existing caller that
        # constructs a LibraryService without them (tests included) is
        # unaffected; scan_all()/scan a location alone still work with
        # neither.
        self.track_matcher = track_matcher
        self.playlists = playlist_repo

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
            existing = self.locations.get_by_path(
                    resolved_path_str,
                    connection,
            )

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

    def rename_location(
            self,
            location_id: int,
            new_name: str,
    ) -> LibraryLocation:
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

    def scan_all(self) -> dict[str, int]:
        totals = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}

        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        if not locations:
            print("No library locations registered.")
            return totals

        for location in locations:
            if not Path(location.path).is_dir():
                print(
                    f"Skipping '{location.name}' ({location.path}): "
                    f"path is unreachable. The drive it lives on may "
                    f"not be connected."
                )
                continue

            summary = self.scanner.scan(location)

            for key in totals:
                totals[key] += summary[key]

        return totals

    def scan_and_match(self) -> dict[str, int]:
        """Chains a full scan into a match pass in one call — the
        guided Dashboard "Scan library" CTA used to call scan_all()
        alone, leaving newly-scanned files with no track_matches row
        at all until a separate, non-obvious "Re-match library" click
        (roadmap item 56). Combines both dicts into one result; a key
        collision isn't possible since scan_all()'s keys
        (added/updated/removed/unchanged) and match_all()'s
        (auto/needs_review/unmatched) are disjoint by construction.
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "scan_and_match() requires a track_matcher — this "
                "LibraryService was constructed without one."
            )

        scan_totals = self.scan_all()
        match_counts = self.track_matcher.match_all()

        return {**scan_totals, **match_counts}

    def get_needs_review_matches(
            self,
            playlist_name: str | None = None,
    ) -> list[NeedsReviewMatch]:
        """Roadmap item 56 Phase 2 — closes item 7's long-outstanding
        gap: a `review` command/screen for needs_review LOCAL-FILE
        matches (distinct from the Soulseek-side review candidates
        DownloadService already exposes). Resolved with enough context
        for a human to judge the pairing, not just the bare score.
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "get_needs_review_matches() requires a track_matcher — "
                "this LibraryService was constructed without one."
            )

        with self.database.transaction() as connection:
            if playlist_name is not None:
                if self.playlists is None:
                    raise RuntimeError(
                        "get_needs_review_matches(playlist_name=...) "
                        "requires a playlist repository — this "
                        "LibraryService was constructed without one."
                    )

                playlist = self.playlists.get_by_name(
                    playlist_name, connection
                )

                if playlist is None:
                    raise PlaylistNotFoundError(
                        f"No playlist named '{playlist_name}' has been "
                        f"synced."
                    )

                tracks = self.track_matcher.tracks.get_all_for_playlist(
                    playlist.id, connection
                )
            else:
                tracks = self.track_matcher.tracks.get_all(connection)

            tracks_by_id = {track.id: track for track in tracks}
            matches = self.track_matcher.track_matches.get_all(connection)

            results = []

            for match in matches:
                if match.match_method != "needs_review":
                    continue

                track = tracks_by_id.get(match.track_id)

                if track is None or match.local_file_id is None:
                    continue

                local_file = self.local_files.get_by_id(
                    match.local_file_id, connection
                )

                if local_file is None:
                    continue

                location = self.locations.get_by_id(
                    local_file.location_id, connection
                )

                # Loaded from the DB via get_by_id above, so .id is set.
                assert local_file.id is not None

                results.append(
                    NeedsReviewMatch(
                        track_id=track.id,
                        track_artist=track.artist,
                        track_title=track.title,
                        local_file_id=local_file.id,
                        local_file_path=local_file.relative_path,
                        location_name=(
                            location.name if location is not None else "?"
                        ),
                        # A needs_review-classified match always has a
                        # real numeric score (that's what put it in this
                        # bucket) — same `or 0.0` type-satisfying pattern
                        # generate_match_report() already uses.
                        score=match.score or 0.0,
                        tag_artist=local_file.tag_artist,
                        tag_title=local_file.tag_title,
                    )
                )

        results.sort(key=lambda item: item.score, reverse=True)

        return results

    def confirm_match(self, track_id: str) -> None:
        """A human confirmed a needs_review local-file match — sets
        match_method='auto' and stamps confirmed_at, WITHOUT touching
        local_file_id/score (the real computed score stays visible
        rather than a 100.0 sentinel — item 45's precedent). No file on
        disk is touched, so no double-confirm gate — this project's
        confirmation gate is for file replacement, not DB state (item
        27's precedent).
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "confirm_match() requires a track_matcher — this "
                "LibraryService was constructed without one."
            )

        with self.database.transaction() as connection:
            self.track_matcher.track_matches.confirm(
                track_id,
                datetime.now(timezone.utc).isoformat(),
                connection,
            )

    def reject_match(self, track_id: str) -> None:
        """Deletes the track_matches row entirely — the track returns to
        unmatched and becomes eligible for download. No blacklist,
        matching reject_review_candidate's deliberate non-feature (item
        26): the same candidate can resurface on a later match run, and
        that is fine.
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "reject_match() requires a track_matcher — this "
                "LibraryService was constructed without one."
            )

        with self.database.transaction() as connection:
            self.track_matcher.track_matches.delete(track_id, connection)

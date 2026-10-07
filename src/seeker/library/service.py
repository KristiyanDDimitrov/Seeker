import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.location_merge_repository import (
    LocationMergeRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.destination_resolution import (
    InvalidDestinationSubfolderError,
    validate_destination_subfolder,
)
from seeker.errors import (
    LibraryLocationNotFoundError,
    PlaylistNotFoundError,
    SeekerError,
)
from seeker.files.deletion import same_file
from seeker.library.matcher import TrackMatcher
from seeker.library.nesting import (
    NestedPathMap,
    find_nested,
    is_within,
    nested_path_map,
    same_directory,
)
from seeker.library.scanner import LibraryScanner, LibraryUnavailableError
from seeker.models.library_location import LibraryLocation
from seeker.models.library_result import ScanAndMatchResult, ScanResult
from seeker.models.location_merge import LocationMergeSummary
from seeker.models.location_removal import LocationRemovalSummary
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.nested_location import NestedLocation

logger = logging.getLogger(__name__)


class LibraryLocationPathAlreadyRegisteredError(SeekerError):
    def __init__(self, existing: LibraryLocation):
        self.existing = existing
        super().__init__(
            f"'{existing.path}' is already registered as "
            f"'{existing.name}'."
        )


class LibraryLocationOverlapError(SeekerError):
    """A new location would sit inside, or contain, `existing`."""

    def __init__(self, path: str, existing: LibraryLocation, *, inside: bool):
        self.existing = existing

        if inside:
            message = (
                f"'{path}' is inside the library location "
                f"'{existing.name}' ({existing.path}), which already "
                f"scans it. Keep using '{existing.name}', or remove it "
                "first and add the folders you want one by one."
            )
        else:
            message = (
                f"'{path}' contains the library location "
                f"'{existing.name}' ({existing.path}), so its files "
                f"would be indexed twice. Remove '{existing.name}' "
                f"first, then add '{path}'."
            )

        super().__init__(message)


class LocationsNotNestedError(SeekerError):
    def __init__(self, merged_name: str, kept_name: str):
        super().__init__(
            f"'{merged_name}' and '{kept_name}' are not one inside the "
            "other, so there is nothing to merge. Remove the one you "
            "no longer want instead."
        )


@dataclass(frozen=True)
class _MergePlan:
    """A merge worked out against the disk, outside any transaction:
    `pairs` holds (merged row id, kept row id) for every merged file
    the kept location indexes too.
    """
    merged: LibraryLocation
    kept: LibraryLocation
    path_map: NestedPathMap
    pairs: list[tuple[int, int]]


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
        self.track_matches = TrackMatchRepository()
        self.location_merges = LocationMergeRepository()
        # Both optional — only scan_and_match()/get_needs_review_matches()
        # etc. need them; scan_all()/scan a location alone still work
        # with neither.
        self.track_matcher = track_matcher
        self.playlists = playlist_repo

    def add_location(self, name: str, path: str) -> LibraryLocation:
        resolved_path = Path(path).expanduser().resolve()

        if not resolved_path.is_dir():
            raise LibraryUnavailableError(resolved_path)

        location = LibraryLocation(
            name=name,
            path=str(resolved_path),
            added_at=datetime.now(UTC).isoformat(),
        )

        with self.database.transaction() as connection:
            self._refuse_overlap(resolved_path, connection)
            self.locations.add(location, connection)
            saved = self.locations.get_by_name(name, connection)

        # We just added this exact name in the same transaction, so it
        # must exist.
        assert saved is not None

        logger.info(
            "Added library location '%s': %s", saved.name, saved.path,
        )

        return saved

    def add_location_from_path(self, path: str) -> LibraryLocation:
        """The UI's own "pick a folder, name it later (or never)" flow
        — derives the name from the folder's own basename rather than
        prompting for one first, auto-suffixing on a name collision
        ("Music", "Music (2)", ...). `add_location` above (explicit name
        + path) is the CLI's own entry point.
        """
        resolved_path = Path(path).expanduser().resolve()

        if not resolved_path.is_dir():
            raise LibraryUnavailableError(resolved_path)

        resolved_path_str = str(resolved_path)

        with self.database.transaction() as connection:
            self._refuse_overlap(resolved_path, connection)

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
                added_at=datetime.now(UTC).isoformat(),
            )
            self.locations.add(location, connection)
            saved = self.locations.get_by_name(name, connection)

        # We just added this exact name in the same transaction, so it
        # must exist.
        assert saved is not None

        logger.info(
            "Added library location '%s': %s", saved.name, saved.path,
        )

        return saved

    def _refuse_overlap(
            self,
            resolved_path: Path,
            connection: sqlite3.Connection,
    ) -> None:
        """Raises when `resolved_path` is already a location, or sits
        inside or around one.
        """
        for existing in self.locations.get_all(connection):
            existing_path = Path(existing.path)

            if same_directory(resolved_path, existing_path):
                raise LibraryLocationPathAlreadyRegisteredError(existing)

            if is_within(resolved_path, existing_path):
                raise LibraryLocationOverlapError(
                    str(resolved_path), existing, inside=True,
                )

            if is_within(existing_path, resolved_path):
                raise LibraryLocationOverlapError(
                    str(resolved_path), existing, inside=False,
                )

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

        logger.info("Renamed library location to '%s'.", saved.name)

        return saved

    def list_locations(self) -> list[tuple[LibraryLocation, bool]]:
        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        return [
            (location, Path(location.path).is_dir())
            for location in locations
        ]

    def find_nested_locations(self) -> list[NestedLocation]:
        """Locations inside other locations, which the add guard now
        refuses but older builds registered. Touches the disk to compare
        folders, so call it off the UI thread.
        """
        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        return find_nested(locations)

    def has_scanned_library(self) -> bool:
        """The Dashboard's "next step" CTA needs to distinguish "tracks
        are cached but the library has never been scanned" from "already
        scanned, matching just didn't find anything" — but no
        `last_scanned_at` column exists on `library_locations`, so this
        approximates it: true once at least one `local_files` row exists
        anywhere. Known, accepted limitation: a real scan of a location
        that genuinely contains zero matching audio files would be
        indistinguishable from "never scanned" by this proxy — not
        solvable without a schema change, so not solved here.
        """
        with self.database.transaction() as connection:
            return self.local_files.exists_any(connection)

    def preview_remove_location(
            self,
            name: str,
            default_location_id: int | None = None,
    ) -> LocationRemovalSummary:
        """What `remove_location` would forget, read-only."""
        self._require_playlists("preview_remove_location()")

        with self.database.transaction() as connection:
            location = self._get_location_or_raise(name, connection)
            return self._removal_summary(
                location, default_location_id, connection,
            )

    def remove_location(
            self,
            name: str,
            default_location_id: int | None = None,
    ) -> LocationRemovalSummary:
        """Forgets a location in one transaction: its indexed files and
        every match to them (confirmed ones included), and the
        destination of every playlist that downloads into it. Files on
        disk are not touched. `default_location_id` is the configured
        default destination, which only the caller can clear.
        """
        playlists = self._require_playlists("remove_location()")

        with self.database.transaction() as connection:
            location = self._get_location_or_raise(name, connection)
            # Loaded from the DB, so .id is set.
            assert location.id is not None
            summary = self._removal_summary(
                location, default_location_id, connection,
            )

            self._forget_location(location.id, playlists, connection)

        logger.info(
            "Removed library location '%s': %d files forgotten, %d "
            "matches cleared (%d confirmed), %d playlists lost their "
            "destination.",
            name,
            summary.files_forgotten,
            summary.matches_cleared,
            summary.confirmed_matches_cleared,
            summary.playlists_affected,
        )

        return summary

    def preview_merge_location(
            self,
            merged_name: str,
            kept_name: str,
            default_location_id: int | None = None,
    ) -> LocationMergeSummary:
        """What `merge_location` would do, read-only. Touches the disk,
        so call it off the UI thread.
        """
        playlists = self._require_playlists("preview_merge_location()")
        plan = self._plan_merge(merged_name, kept_name)

        with self.database.transaction() as connection:
            self._stage_merge(plan, connection)
            summary, _ = self._merge_summary(
                plan, default_location_id, playlists, connection,
            )

        return summary

    def merge_location(
            self,
            merged_name: str,
            kept_name: str,
            default_location_id: int | None = None,
    ) -> LocationMergeSummary:
        """Folds a location nested inside, or around, the kept one into
        it, in one transaction, then forgets it as `remove_location`
        does. Each merged file the kept location indexes too (the same
        physical file, checked on disk) hands its matches, Review
        rejections and analysis to the kept row; playlists downloading
        into the merged location download into the same folder through
        the kept one. Both locations must be reachable. Files on disk
        are not touched.
        """
        playlists = self._require_playlists("merge_location()")
        plan = self._plan_merge(merged_name, kept_name)
        merged_id, kept_id = self._location_ids(plan)

        with self.database.transaction() as connection:
            self._stage_merge(plan, connection)
            summary, moves = self._merge_summary(
                plan, default_location_id, playlists, connection,
            )

            self.location_merges.move_matches(connection)
            self.location_merges.move_rejections(connection)
            self.location_merges.carry_analyses(connection)
            self.location_merges.move_duplicate_cleanups(
                merged_id, kept_id, connection,
            )

            for playlist_id, subfolder in moves:
                playlists.set_destination(
                    playlist_id, kept_id, subfolder, connection,
                )

            self._forget_location(merged_id, playlists, connection)

        logger.info(
            "Merged library location '%s' into '%s': %d files merged, "
            "%d forgotten, %d matches moved, %d cleared, %d analyses "
            "kept, %d playlists moved, %d lost their destination.",
            merged_name,
            kept_name,
            summary.files_merged,
            summary.files_forgotten,
            summary.matches_moved,
            summary.matches_cleared,
            summary.analyses_kept,
            summary.playlists_moved,
            summary.playlists_cleared,
        )

        return summary

    def _plan_merge(self, merged_name: str, kept_name: str) -> _MergePlan:
        with self.database.transaction() as connection:
            merged = self._get_location_or_raise(merged_name, connection)
            kept = self._get_location_or_raise(kept_name, connection)
            merged_id, kept_id = merged.id, kept.id
            # Loaded from the DB, so both ids are set.
            assert merged_id is not None
            assert kept_id is not None
            merged_files = self.local_files.get_all_for_location(
                merged_id, connection,
            )
            kept_files = self.local_files.get_all_for_location(
                kept_id, connection,
            )

        merged_root = Path(merged.path)
        kept_root = Path(kept.path)
        path_map = (
            nested_path_map(merged_root, kept_root)
            if merged_id != kept_id
            else None
        )

        if path_map is None:
            raise LocationsNotNestedError(merged_name, kept_name)

        for root in (merged_root, kept_root):
            if not root.is_dir():
                raise LibraryUnavailableError(root)

        kept_ids = {file.relative_path: file.id for file in kept_files}
        pairs = []

        for file in merged_files:
            kept_path = path_map.map_relative_path(file.relative_path)
            kept_file_id = kept_ids.get(kept_path) if kept_path else None

            if (
                    file.id is not None
                    and kept_path is not None
                    and kept_file_id is not None
                    and same_file(
                        merged_root / file.relative_path,
                        kept_root / kept_path,
                    )
            ):
                pairs.append((file.id, kept_file_id))

        return _MergePlan(merged, kept, path_map, pairs)

    @staticmethod
    def _location_ids(plan: _MergePlan) -> tuple[int, int]:
        # _plan_merge loaded both from the DB, so both ids are set.
        assert plan.merged.id is not None
        assert plan.kept.id is not None

        return plan.merged.id, plan.kept.id

    def _stage_merge(
            self,
            plan: _MergePlan,
            connection: sqlite3.Connection,
    ) -> None:
        """Stages the plan's pairs, refusing if either location was
        removed or replaced since the plan was made.
        """
        for planned in (plan.merged, plan.kept):
            current = self._get_location_or_raise(planned.name, connection)

            if current.id != planned.id:
                raise LibraryLocationNotFoundError(
                    f"The library location '{planned.name}' changed "
                    "while the merge was being prepared. Try again."
                )

        merged_id, kept_id = self._location_ids(plan)
        self.location_merges.stage(plan.pairs, merged_id, kept_id, connection)

    def _merge_summary(
            self,
            plan: _MergePlan,
            default_location_id: int | None,
            playlists: PlaylistRepository,
            connection: sqlite3.Connection,
    ) -> tuple[LocationMergeSummary, list[tuple[str, str | None]]]:
        """The summary of a staged merge, and the (playlist id, new
        subfolder) destinations that move to the kept location.
        """
        merged_id, _ = self._location_ids(plan)
        files_merged = self.location_merges.count_files(connection)
        matches_moved, matches_cleared = (
            self.location_merges.count_matches(merged_id, connection)
        )
        moves: list[tuple[str, str | None]] = []
        playlists_cleared = 0

        for playlist in playlists.get_all(connection):
            if playlist.download_location_id != merged_id:
                continue

            subfolder = _kept_subfolder(
                plan.path_map, playlist.download_subfolder,
            )

            if subfolder is None:
                playlists_cleared += 1
            else:
                moves.append((playlist.id, subfolder or None))

        summary = LocationMergeSummary(
            merged_name=plan.merged.name,
            kept_name=plan.kept.name,
            files_merged=files_merged,
            files_forgotten=self.local_files.count_for_location(
                merged_id, connection,
            ) - files_merged,
            matches_moved=matches_moved,
            matches_cleared=matches_cleared,
            analyses_kept=self.location_merges.count_analyses(connection),
            playlists_moved=len(moves),
            playlists_cleared=playlists_cleared,
            was_default=merged_id == default_location_id,
        )

        return summary, moves

    def _forget_location(
            self,
            location_id: int,
            playlists: PlaylistRepository,
            connection: sqlite3.Connection,
    ) -> None:
        """Deletes a location with its indexed files, releasing every
        match to them and clearing every playlist destination in it.
        """
        self.local_files.delete_all_for_location(location_id, connection)
        playlists.clear_destination_for_location(location_id, connection)
        self.locations.delete(location_id, connection)

    def _get_location_or_raise(
            self,
            name: str,
            connection: sqlite3.Connection,
    ) -> LibraryLocation:
        location = self.locations.get_by_name(name, connection)

        if location is None:
            raise LibraryLocationNotFoundError(
                f"No library location named '{name}' is registered."
            )

        return location

    def _removal_summary(
            self,
            location: LibraryLocation,
            default_location_id: int | None,
            connection: sqlite3.Connection,
    ) -> LocationRemovalSummary:
        playlists = self._require_playlists("_removal_summary()")
        # Loaded from the DB, so .id is set.
        assert location.id is not None
        matches, confirmed = self.track_matches.count_for_location(
            location.id, connection,
        )

        return LocationRemovalSummary(
            location_name=location.name,
            files_forgotten=self.local_files.count_for_location(
                location.id, connection,
            ),
            matches_cleared=matches,
            confirmed_matches_cleared=confirmed,
            playlists_affected=playlists.count_with_destination(
                location.id, connection,
            ),
            was_default=location.id == default_location_id,
        )

    def _require_playlists(self, caller: str) -> PlaylistRepository:
        if self.playlists is None:
            raise RuntimeError(
                f"{caller} requires a playlist repository — this "
                "LibraryService was constructed without one."
            )

        return self.playlists

    def scan_all(self) -> ScanResult:
        totals = ScanResult()

        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        if not locations:
            logger.info("No library locations registered.")
            return totals

        for location in locations:
            if not Path(location.path).is_dir():
                logger.warning(
                    "Skipping '%s': %s",
                    location.name,
                    LibraryUnavailableError(Path(location.path)),
                )
                continue

            totals += self.scanner.scan(location)

        return totals

    def scan_and_match(self) -> ScanAndMatchResult:
        """Chains a full scan into a match pass in one call, so newly
        scanned files never sit without a track_matches row until a
        separate "Match tracks" click.
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "scan_and_match() requires a track_matcher — this "
                "LibraryService was constructed without one."
            )

        scan = self.scan_all()
        match = self.track_matcher.match_all()

        return ScanAndMatchResult(scan=scan, match=match)

    def get_needs_review_matches(
            self,
            playlist_name: str | None = None,
    ) -> list[NeedsReviewMatch]:
        """Needs-review LOCAL-FILE matches, for the `review` command
        and the Review screen (distinct from the Soulseek-side review candidates
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
        rather than a 100.0 sentinel). No file on disk is touched, so
        no double-confirm gate — this project's confirmation gate is
        for file replacement, not DB state.
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "confirm_match() requires a track_matcher — this "
                "LibraryService was constructed without one."
            )

        with self.database.transaction() as connection:
            self.track_matcher.track_matches.confirm(
                track_id,
                datetime.now(UTC).isoformat(),
                connection,
            )

    def reject_match(self, track_id: str) -> None:
        """The track returns to unmatched and becomes eligible for
        download, and its file is never suggested for it again: later
        match runs fall through to the next best file.
        """
        if self.track_matcher is None:
            raise RuntimeError(
                "reject_match() requires a track_matcher — this "
                "LibraryService was constructed without one."
            )

        with self.database.transaction() as connection:
            match = self.track_matcher.track_matches.get_by_track_id(
                track_id, connection,
            )

            if match is not None and match.local_file_id is not None:
                self.track_matcher.rejections.add_local_match(
                    track_id,
                    match.local_file_id,
                    datetime.now(UTC).isoformat(),
                    connection,
                )

            self.track_matcher.track_matches.delete(track_id, connection)


def _kept_subfolder(
        path_map: NestedPathMap,
        subfolder: str | None,
) -> str | None:
    """A merged location's destination subfolder as a subfolder of the
    kept location naming the same folder: "" for the kept root itself,
    None when the folder is outside the kept location or not a valid
    subfolder there.
    """
    parts = tuple(subfolder.split("/")) if subfolder else ()
    mapped = path_map.map_parts(parts)

    if mapped is None:
        return None

    try:
        return validate_destination_subfolder("/".join(mapped)) or ""
    except InvalidDestinationSubfolderError:
        return None

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from seeker.audio.fingerprint import (
    FingerprintError,
    FingerprintingUnavailableError,
    compute_fingerprint,
    decode_fingerprint,
    similarity_from_decoded,
)
from seeker.audio.fingerprint import (
    is_available as fingerprinting_is_available,
)
from seeker.audio.quality import (
    LocalFileQuality,
    analyze_local_file_quality,
)
from seeker.database.connection import Database
from seeker.database.repositories.duplicate_cleanup_repository import (
    DuplicateCleanupRepository,
)
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.errors import LibraryLocationNotFoundError
from seeker.files.deletion import delete_file, same_file
from seeker.models.duplicate_cleanup import DuplicateCleanup
from seeker.models.fingerprint_result import FingerprintResult
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.track_match import TrackMatch

logger = logging.getLogger(__name__)


# Per-file fingerprint-failure reason codes, surfaced in
# compute_fingerprints()'s `details` (printed per line by the CLI, read
# by the UI) instead of one generic "failed" for everything.
# `_EmptyFileError` keeps a 0-byte file distinct from a decode failure:
# it can never be fingerprinted (nothing to decode), so it can never
# enter a duplicate group, and nothing here ever offers to delete it.
_REASON_FILE_MISSING = "file_missing"
_REASON_EMPTY_FILE = "empty_file"
_REASON_DECODE_UNSUPPORTED = "decode_unsupported"
_REASON_ERROR = "error"


class _FileMissingError(RuntimeError):
    pass


class _SamePhysicalFileError(RuntimeError):
    """Overlapping registered library locations can index the SAME
    real file twice, as two different local_files rows.
    find_duplicate_groups is deliberately content-based and
    location-agnostic, so a group built from exactly that pair is a
    real, valid cluster — but deleting "the other" row would delete the
    very file the caller asked to keep. Raised by _delete_one_local_file
    before either the DB row or the disk file is touched; caught by
    delete_local_files and counted separately from an ordinary failure.
    See HISTORY §93."""


class _EmptyFileError(RuntimeError):
    pass


def _classify_fingerprint_failure(error: Exception) -> str:
    if isinstance(error, _FileMissingError):
        return _REASON_FILE_MISSING
    if isinstance(error, _EmptyFileError):
        return _REASON_EMPTY_FILE
    if isinstance(error, FingerprintError):
        return _REASON_DECODE_UNSUPPORTED
    return _REASON_ERROR


# Hamming-distance similarity at or above this counts as a duplicate.
# Real duplicate pairs, including a cross-format FLAC/MP3 transcode,
# score 99.87-99.98 % similarity, while an unrelated pair scores
# ~58 %; 0.95 leaves a wide margin on both sides of that gap without
# tuning. See HISTORY §38.
DUPLICATE_SIMILARITY_THRESHOLD = 0.95

# Cheap pre-filter before the real (comparatively expensive) fingerprint
# comparison — two genuinely duplicate files' reported durations should
# be within a couple of seconds of each other. Untuned; this is what
# keeps an O(n^2) clustering pass over a location's files tractable —
# revisit if a real library's tagging/encoding quirks ever produce a
# real duplicate pair with a bigger duration gap than this.
DURATION_TOLERANCE_MS = 3_000


@dataclass
class DuplicateFile:
    local_file: LocalFile
    quality: LocalFileQuality


@dataclass
class DuplicateGroup:
    # Ranked best-quality first (see _quality_sort_key) — files[0] is
    # this group's own recommendation for which copy to keep.
    files: list[DuplicateFile]
    # The LOWEST pairwise similarity found within this group — a
    # conservative "how confident is this really one group" summary,
    # since union-find clustering (see _cluster_by_similarity) can
    # transitively merge a chain of pairwise matches into one group of
    # more than two files.
    similarity: float


@dataclass
class DuplicateFolderScope:
    """One resolved folder to include in a pooled duplicate search: a
    registered library location plus the folder's path relative to that
    location's root (empty string means the whole location). Built by
    resolve_folder_scopes() from real absolute paths (e.g. a folder
    picker) — never constructed directly by a caller that hasn't gone
    through that resolution, so a scope can never silently point outside
    every registered location.
    """
    location: LibraryLocation
    folder_relative_path: str


@dataclass
class ScopeSummary:
    """The scope-count result: not just a bare number, but which
    location(s) it resolved to and which of those have never been
    scanned at all."""
    file_count: int
    resolved_location_names: list[str]
    empty_locations: list[str]


@dataclass
class GroupResolutionPlan:
    """One group's already-decided resolution, computed by the caller
    (the UI, from the user's own kept-radio selection) and trusted here
    exactly the same way `delete_local_files` already trusts an explicit
    `local_file_ids`/`keep_local_file_id` pair — this dataclass doesn't
    re-derive or re-validate the choice against
    `find_duplicate_groups`'s own clustering."""
    delete_local_file_ids: list[int]
    keep_local_file_id: int
    location_id: int | None


@dataclass
class BulkDuplicateResolutionResult:
    """The per-group/per-file outcome of a "Resolve all groups" batch,
    same reporting shape as
    `BulkUpgradeReplaceResult`/`format_rename_result_message`: counts
    for the headline, plus one detail line per group that had any real
    failure. `plan_outcomes` (same order/length as the input `plans`)
    lets a caller that also tracks per-group UI state (e.g. dropping a
    fully-resolved group from an in-memory list without a full re-fetch)
    know exactly which plans actually succeeded, rather than inferring
    it from the aggregate counts alone."""
    groups_resolved: int
    groups_failed: int
    files_deleted: int
    files_failed: int
    # Files that were neither deleted nor counted as failed: refused by
    # the same-physical-file guard (an overlapping registered location
    # indexed the exact file being kept a second time). Not a failure —
    # the safety check did exactly what it should — but not silently
    # folded into files_deleted either.
    files_skipped_same_physical_file: int
    bytes_freed: int
    details: list[str]
    plan_outcomes: list[bool]


def _path_within_folder(
        file_relative_path: str,
        folder_relative_path: str,
) -> bool:
    # Path-prefix matching that respects separator boundaries: "Trance"
    # must never match "TranceX". A bare str.startswith() check would
    # get this wrong; PurePath.is_relative_to (via Path here, a pure
    # logical operation — no filesystem I/O) does not.
    if not folder_relative_path:
        return True  # "" means the whole location.

    return Path(file_relative_path).is_relative_to(Path(folder_relative_path))


class DuplicateService:
    """Per-library-location fingerprint computation and duplicate
    clustering, plus the group-resolution delete action — scoped to one
    `library_locations` row at a time, the same unit `library add`/
    `list`/`remove` use, unless a caller pools folder scopes
    explicitly. `compute_fingerprints`/`find_duplicate_groups` are
    read-only; `delete_local_files` is the one filesystem-destructive
    method here, and is never called without an explicit,
    caller-confirmed list of ids (the UI confirms twice first). See
    HISTORY §39, HISTORY §40."""

    def __init__(
        self,
        database: Database,
        location_repository: LibraryLocationRepository,
        local_file_repository: LocalFileRepository,
        track_match_repository: TrackMatchRepository,
        duplicate_cleanup_repository: DuplicateCleanupRepository | None = None,
    ):
        self.database = database
        self.locations = location_repository
        self.local_files = local_file_repository
        self.track_matches = track_match_repository
        # Optional, defaulted rather than required: only
        # record_cleanup()/get_cleanup_totals() need it.
        self.duplicate_cleanups = (
            duplicate_cleanup_repository or DuplicateCleanupRepository()
        )

    def _get_location_or_raise(
            self, location_name: str, connection: Any,
    ) -> LibraryLocation:
        location = self.locations.get_by_name(location_name, connection)

        if location is None:
            raise LibraryLocationNotFoundError(
                f"No library location named '{location_name}' is "
                f"registered."
            )

        return location

    def compute_fingerprints(
            self,
            location_name: str,
            force: bool = False,
            folders: list[str] | None = None,
            progress: Callable[[str, int, int], None] | None = None,
    ) -> FingerprintResult:
        """Compute and persist a fingerprint for every file at this
        location that doesn't already have one (or every file,
        regardless, if force=True) — mirrors MetadataService.tag_tracks'
        own skip-already-done/force/per-item-try-except shape.

        `folders`, when given, scopes this to only the files whose
        relative_path falls under one of these (location-relative)
        folder paths — fingerprinting one folder instead of a whole
        multi-thousand-file location. `progress`, when given, is called
        as `progress(stage, current, total)` — a single stage here
        ("Fingerprinting"), `total` = files actually in scope.
        """
        if not fingerprinting_is_available():
            # One clear failure, not N per-file ones, for a single root
            # cause — same "checked before use" precedent as
            # Application.soulseek_configured.
            raise FingerprintingUnavailableError(
                "libchromaprint isn't installed or couldn't be found. "
                "Install it to use duplicate detection — e.g. "
                "`brew install chromaprint` on macOS, "
                "`apt install libchromaprint1` on Debian/Ubuntu, or the "
                "Chromaprint installer on Windows."
            )

        with self.database.transaction() as connection:
            location = self._get_location_or_raise(location_name, connection)
            # Loaded from the DB just above via get_by_name, so .id is set.
            assert location.id is not None
            local_files = (
                self.local_files.get_all_for_location_with_fingerprints(
                    location.id, connection,
                )
            )

        if folders:
            local_files = [
                f for f in local_files
                if any(
                    _path_within_folder(f.relative_path, folder)
                    for folder in folders
                )
            ]

        result = FingerprintResult()
        total = len(local_files)

        for index, local_file in enumerate(local_files, start=1):
            try:
                self._compute_one(
                    location, local_file, force, result,
                )
            except Exception as error:
                result.failed += 1
                result.details.append(
                    {
                        "local_file_id": str(local_file.id),
                        "reason": _classify_fingerprint_failure(error),
                        "message": f"{local_file.filename}: {error}",
                    }
                )
                logger.warning(
                    "Failed to fingerprint %s: %s", local_file.filename, error,
                )

            if progress is not None:
                progress("Fingerprinting", index, total)

        return result

    def _compute_one(
            self,
            location: LibraryLocation,
            local_file: LocalFile,
            force: bool,
            result: FingerprintResult,
    ) -> None:
        if local_file.fingerprint is not None and not force:
            result.skipped_already_computed += 1
            return

        file_path = Path(location.path) / local_file.relative_path

        # Checked BEFORE compute_fingerprint() so these two distinct
        # causes get their own reason codes instead of surfacing as
        # whatever message soundfile/ffmpeg happen to raise for "nothing
        # here."
        if not file_path.is_file():
            raise _FileMissingError(f"{file_path} does not exist")
        if file_path.stat().st_size == 0:
            raise _EmptyFileError(f"{file_path} is a 0-byte file")

        fingerprint = compute_fingerprint(file_path)

        with self.database.transaction() as connection:
            # Loaded from the DB just above, so .id is set.
            assert local_file.id is not None

            self.local_files.update_fingerprint(
                local_file.id,
                fingerprint.data,
                fingerprint.duration_seconds,
                datetime.now(UTC).isoformat(),
                connection,
            )

        result.computed += 1
        logger.debug("Fingerprinted: %s", local_file.filename)

    def resolve_folder_scopes(
            self,
            folder_paths: list[str],
            preferred_location_id: int | None = None,
    ) -> list[DuplicateFolderScope]:
        """Resolves absolute folder paths (e.g. from a folder picker)
        against every registered library location. Each folder must
        resolve inside a registered location; anything else is rejected
        with a clear message — fingerprints only exist for indexed
        files, and an unregistered folder was never scanned at all.

        MOST-SPECIFIC-WINS: a folder can be "inside" more than one
        registered location at once (a location registered at a parent
        path, and another at a nested child path, both cover the same
        folder). Taking the first match by name can pick an unscanned
        parent and report a false "0 files in scope", so every
        candidate location is scored by its resolved path length and
        the LONGEST (most specific) one wins. `preferred_location_id`,
        when given (the UI's selected location combo), breaks a
        genuine tie only; it can never override a strictly-more-specific
        match, so "prefer this location" never silently widens a
        folder's real scope. See HISTORY §78.
        """
        with self.database.transaction() as connection:
            locations = self.locations.get_all(connection)

        scopes = []

        for folder_path in folder_paths:
            folder = Path(folder_path).resolve()
            candidates: list[tuple[LibraryLocation, str]] = []

            for location in locations:
                location_path = Path(location.path).resolve()

                if folder == location_path:
                    candidates.append((location, ""))
                elif folder.is_relative_to(location_path):
                    candidates.append(
                        (location, str(folder.relative_to(location_path))),
                    )

            if not candidates:
                raise LibraryLocationNotFoundError(
                    f"'{folder_path}' is not inside any registered "
                    f"library location — add it as a location first, or "
                    f"pick a folder inside one that's already registered."
                )

            best_specificity = max(
                len(str(Path(location.path).resolve())) for location, _ in candidates
            )
            tied = [
                (location, relative) for location, relative in candidates
                if len(str(Path(location.path).resolve())) == best_specificity
            ]

            matched_location, matched_relative = tied[0]
            if preferred_location_id is not None:
                for location, relative in tied:
                    if location.id == preferred_location_id:
                        matched_location, matched_relative = location, relative
                        break

            scopes.append(
                DuplicateFolderScope(
                    location=matched_location,
                    folder_relative_path=matched_relative,
                )
            )

        return scopes

    def find_duplicate_groups(
            self,
            location_name: str,
            folders: list[str] | None = None,
            progress: Callable[[str, int, int], None] | None = None,
    ) -> list[DuplicateGroup]:
        """Cluster this location's already-fingerprinted files by
        Hamming distance — computed fresh from cached fingerprints on
        every call, never persisted as its own table (persisted group
        membership would go stale the moment a file moves or gets
        rescanned). Files with no fingerprint yet
        (compute_fingerprints() hasn't run for them) are silently
        excluded, not treated as an error — a partial fingerprint
        coverage is a completely normal, expected state.

        `folders`, when given (location-relative paths), scopes this to
        only files under one of them; omitted, the whole location.
        """
        with self.database.transaction() as connection:
            location = self._get_location_or_raise(location_name, connection)
            # Loaded from the DB just above via get_by_name, so .id is set.
            assert location.id is not None
            local_files = (
                self.local_files.get_all_for_location_with_fingerprints(
                    location.id, connection,
                )
            )

        if folders:
            local_files = [
                f for f in local_files
                if any(
                    _path_within_folder(f.relative_path, folder)
                    for folder in folders
                )
            ]

        files_with_locations = [(f, location) for f in local_files]

        return _cluster_duplicate_groups(files_with_locations, progress)

    def _files_for_scopes(
            self, scopes: list[DuplicateFolderScope],
    ) -> list[tuple[LocalFile, LibraryLocation]]:
        files_with_locations: list[tuple[LocalFile, LibraryLocation]] = []

        with self.database.transaction() as connection:
            for scope in scopes:
                assert scope.location.id is not None
                all_files = (
                    self.local_files.get_all_for_location_with_fingerprints(
                        scope.location.id, connection,
                    )
                )
                scoped_files = [
                    f for f in all_files
                    if _path_within_folder(
                        f.relative_path, scope.folder_relative_path,
                    )
                ]
                files_with_locations.extend(
                    (f, scope.location) for f in scoped_files
                )

        return files_with_locations

    def find_duplicate_groups_across_scopes(
            self,
            scopes: list[DuplicateFolderScope],
            progress: Callable[[str, int, int], None] | None = None,
    ) -> list[DuplicateGroup]:
        """Pools every given folder (each already resolved via
        resolve_folder_scopes) into ONE set, compared together —
        including across different real library locations, deliberately
        allowed: the clustering itself is purely content-based (Hamming
        distance over decoded audio fingerprints) and location-agnostic,
        so there's no reason two folders living in different registered
        locations couldn't hold the same real recording.
        """
        return _cluster_duplicate_groups(
            self._files_for_scopes(scopes), progress,
        )

    def count_files_for_scopes(
            self, scopes: list[DuplicateFolderScope],
    ) -> int:
        """A file count BEFORE starting a potentially ~10-minute
        operation at real library scale, so the user sees what a scope
        actually covers first. See HISTORY §39."""
        return len(self._files_for_scopes(scopes))

    def summarize_scopes(
            self, scopes: list[DuplicateFolderScope],
    ) -> "ScopeSummary":
        """count_files_for_scopes() with its context: a bare "0 files
        in scope" gives no way to tell "this folder really is empty"
        apart from "this resolved to an unscanned location". Also
        reports which location(s) the folders resolved to and which of
        those have NO scanned files at all, location-wide, not just
        within the folder — a location with zero total local_files rows
        was never scanned, so "run a scan" is the real fix, not
        something more fingerprinting could ever solve.
        """
        file_count = 0
        resolved_location_names: list[str] = []
        empty_locations: list[str] = []
        files_by_location_id: dict[int, list[LocalFile]] = {}

        with self.database.transaction() as connection:
            for scope in scopes:
                assert scope.location.id is not None

                if scope.location.id not in files_by_location_id:
                    all_files = (
                        self.local_files.get_all_for_location_with_fingerprints(
                            scope.location.id, connection,
                        )
                    )
                    files_by_location_id[scope.location.id] = all_files
                    resolved_location_names.append(scope.location.name)
                    if not all_files:
                        empty_locations.append(scope.location.name)

                all_files = files_by_location_id[scope.location.id]
                file_count += sum(
                    1 for f in all_files
                    if _path_within_folder(
                        f.relative_path, scope.folder_relative_path,
                    )
                )

        return ScopeSummary(
            file_count=file_count,
            resolved_location_names=resolved_location_names,
            empty_locations=empty_locations,
        )

    def delete_local_files(
            self,
            local_file_ids: list[int],
            keep_local_file_id: int | None = None,
            location_id: int | None = None,
    ) -> dict[str, Any]:
        """Deletes each given local file — both its `local_files` DB row
        and the real file on disk — used to resolve a duplicate group by
        removing every member except whichever one the caller decided to
        keep. Deliberately has no notion of "groups" itself beyond
        `keep_local_file_id`: the caller (the UI, after confirming
        twice) decides which specific ids to delete; this method trusts
        that decision rather than re-deriving or re-validating it
        against `find_duplicate_groups`' own clustering. Per-item
        try/except, same batch-safety shape as `compute_fingerprints`.

        `keep_local_file_id`, when given, is the surviving file within
        the same group — see `_repoint_or_clear_match`'s own docstring
        for why a `track_matches` row pointing at a file being deleted
        gets re-pointed to it rather than left to the schema's own
        `ON DELETE SET NULL` cascade. `None` (no known survivor, e.g. a
        caller deleting files with no group context at all) falls back
        to that cascade, matching this method's original behavior.

        Order is deliberate and matters: for each file, the DB row is
        deleted FIRST, then the file on disk. These two steps aren't
        atomic. If something interrupts between them, THIS order fails
        in the safer direction — an orphaned-but-still-present file,
        which `library/scanner.py`'s walk already self-heals on the
        next `library scan` by simply rediscovering it as a "new"
        file. The reverse
        order (file first, DB row second) would instead leave a
        `local_files` row pointing at a file that no longer exists, in
        the window before that same next scan repairs it — a state a
        matcher or tagger run in that window could act on and fail
        against, which is worse than a merely-orphaned file.

        `location_id`, when given, is recorded on the resulting
        `duplicate_cleanups` row — purely informational provenance for
        the reclaimed-space milestone, not used to scope or validate the
        deletion itself. A real, non-zero `bytes_freed` is recorded
        whenever at least one file was actually deleted; a batch that
        deleted nothing (all failed) records nothing at all, matching
        "an empty milestone is worse than no milestone."
        """
        # Resolved ONCE, up front — every deletion attempt below compares
        # against this same real path, not a per-file re-read of a row
        # that this same loop could itself be in the middle of deleting.
        keep_file_path = self._resolve_local_file_path(keep_local_file_id)

        counts = {"deleted": 0, "failed": 0, "skipped_same_physical_file": 0}
        details: list[dict[str, str]] = []
        bytes_freed = 0

        for local_file_id in local_file_ids:
            try:
                bytes_freed += self._delete_one_local_file(
                    local_file_id, keep_local_file_id, keep_file_path,
                )
            except _SamePhysicalFileError as error:
                counts["skipped_same_physical_file"] += 1
                details.append(
                    {
                        "local_file_id": str(local_file_id),
                        "message": str(error),
                    }
                )
                logger.warning(
                    "Refused to delete local file %s: %s",
                    local_file_id, error,
                )
            except Exception as error:
                counts["failed"] += 1
                details.append(
                    {
                        "local_file_id": str(local_file_id),
                        "message": str(error),
                    }
                )
                logger.exception(
                    "Failed to delete local file %s: %s",
                    local_file_id, error,
                )
            else:
                counts["deleted"] += 1

        if counts["deleted"] > 0:
            self.record_cleanup(counts["deleted"], bytes_freed, location_id)

        return {**counts, "details": details, "bytes_freed": bytes_freed}

    def resolve_groups(
            self, plans: list[GroupResolutionPlan],
    ) -> BulkDuplicateResolutionResult:
        """"Resolve all groups". Applies `delete_local_files()` per plan
        (one per group the caller decided to resolve — a "Keep all"
        group is never turned into a plan at all, decided by the UI
        before this is ever called, not filtered here). Per-plan
        try/except, so one group's total failure can't abort the rest —
        `delete_local_files` already has its own per-FILE try/except
        underneath this, so a failure here means the whole group call
        raised, not just one file within it.
        """
        groups_resolved = 0
        groups_failed = 0
        files_deleted = 0
        files_failed = 0
        files_skipped_same_physical_file = 0
        bytes_freed = 0
        details: list[str] = []
        plan_outcomes: list[bool] = []

        for plan in plans:
            try:
                result = self.delete_local_files(
                    plan.delete_local_file_ids,
                    plan.keep_local_file_id,
                    plan.location_id,
                )
            except Exception as error:
                groups_failed += 1
                details.append(f"Group failed entirely: {error}")
                plan_outcomes.append(False)
                continue

            files_deleted += result["deleted"]
            files_failed += result["failed"]
            files_skipped_same_physical_file += result[
                "skipped_same_physical_file"
            ]
            bytes_freed += result["bytes_freed"]

            if result["skipped_same_physical_file"]:
                details.append(
                    f"Group: {result['skipped_same_physical_file']} "
                    f"file(s) refused — same real file as the one kept "
                    f"(an overlapping library location double-indexed "
                    f"it)."
                )

            # A same-physical-file skip is the safety check working
            # correctly, not a failure — it does not move this group
            # into groups_failed.
            if result["failed"] == 0:
                groups_resolved += 1
                plan_outcomes.append(True)
            else:
                groups_failed += 1
                plan_outcomes.append(False)
                details.append(
                    f"Group partially failed: {result['failed']} of "
                    f"{len(plan.delete_local_file_ids)} file(s) could "
                    f"not be deleted."
                )

        return BulkDuplicateResolutionResult(
            groups_resolved=groups_resolved,
            groups_failed=groups_failed,
            files_deleted=files_deleted,
            files_failed=files_failed,
            files_skipped_same_physical_file=files_skipped_same_physical_file,
            bytes_freed=bytes_freed,
            details=details,
            plan_outcomes=plan_outcomes,
        )

    def record_cleanup(
            self,
            files_deleted: int,
            bytes_freed: int,
            location_id: int | None = None,
    ) -> None:
        with self.database.transaction() as connection:
            self.duplicate_cleanups.add(
                DuplicateCleanup(
                    occurred_at=datetime.now(UTC).isoformat(),
                    files_deleted=files_deleted,
                    bytes_freed=bytes_freed,
                    location_id=location_id,
                ),
                connection,
            )

    def get_cleanup_totals(self) -> tuple[int, int]:
        """(total_files_deleted, total_bytes_freed) across every real
        recorded cleanup, ever — (0, 0) when none have happened yet."""
        with self.database.transaction() as connection:
            return self.duplicate_cleanups.get_totals(connection)

    def _resolve_local_file_path(
            self, local_file_id: int | None,
    ) -> Path | None:
        if local_file_id is None:
            return None

        with self.database.transaction() as connection:
            local_file = self.local_files.get_by_id(local_file_id, connection)

            if local_file is None:
                return None

            location = self.locations.get_by_id(
                local_file.location_id, connection,
            )

        if location is None:
            return None

        return Path(location.path) / local_file.relative_path

    def _delete_one_local_file(
            self,
            local_file_id: int,
            keep_local_file_id: int | None,
            keep_file_path: Path | None = None,
    ) -> int:
        with self.database.transaction() as connection:
            local_file = self.local_files.get_by_id(local_file_id, connection)

            if local_file is None:
                # Already gone -- the desired end state (no such row,
                # no such file tracked) is already true. Nothing was
                # freed by THIS call.
                return 0

            location = self.locations.get_by_id(
                local_file.location_id, connection,
            )
            file_path = (
                Path(location.path) / local_file.relative_path
                if location is not None else None
            )

            # Checked before anything else touches the DB row or disk.
            # See _SamePhysicalFileError's own docstring for why this is
            # reachable at all: two overlapping registered locations can
            # each hold their own local_files row for the identical real
            # file.
            if (
                    local_file_id != keep_local_file_id
                    and file_path is not None
                    and keep_file_path is not None
                    and same_file(file_path, keep_file_path)
            ):
                raise _SamePhysicalFileError(
                    f"{file_path} is the same real file as the one "
                    f"being kept ({keep_file_path}) — refused, not "
                    f"deleted"
                )

            # Measured from the real file via stat() BEFORE either the
            # DB row or the file itself is deleted (the deletion order
            # below is DB row first, then file). Falls back to
            # the stored size_bytes column if the real file is already
            # gone from disk — still a real, previously-recorded size,
            # not a guess.
            bytes_freed = local_file.size_bytes
            if file_path is not None:
                with contextlib.suppress(OSError):
                    bytes_freed = file_path.stat().st_size

            self._repoint_or_clear_match(
                local_file_id, keep_local_file_id, connection,
            )
            self.local_files.delete_by_id(local_file_id, connection)

        if location is None or file_path is None:
            # A local_files row with no matching library_locations row
            # isn't a state this schema's own foreign keys allow --
            # nothing further to delete on disk.
            return bytes_freed

        error = delete_file(file_path)

        if error is not None:
            # The DB row is already gone at this point (see this
            # method's own docstring for why that ordering is the
            # deliberately safer one) -- the file itself is still on
            # disk, which is a real, worth-surfacing partial failure,
            # not a silent success.
            raise RuntimeError(
                f"removed from the library but could not delete "
                f"{file_path}: {error}"
            )

        return bytes_freed

    def _repoint_or_clear_match(
            self,
            local_file_id: int,
            keep_local_file_id: int | None,
            connection: Any,
    ) -> None:
        """If a `track_matches` row currently points at the file about
        to be deleted, re-point it at the group's surviving file.
        Otherwise `delete_by_id` would reset it to unmatched, and the
        next download would fetch a track whose near-identical copy is
        already in the library.

        `match_method`/`score` are kept, not re-evaluated: the surviving
        audio is fingerprint-confirmed near-identical
        (>= DUPLICATE_SIMILARITY_THRESHOLD).
        """
        if keep_local_file_id is None:
            return

        matches = self.track_matches.get_by_local_file_id(
            local_file_id, connection,
        )

        for match in matches:
            self.track_matches.upsert(
                TrackMatch(
                    track_id=match.track_id,
                    local_file_id=keep_local_file_id,
                    match_method=match.match_method,
                    score=match.score,
                    matched_at=datetime.now(UTC).isoformat(),
                ),
                connection,
            )


def _cluster_duplicate_groups(
        files_with_locations: list[tuple[LocalFile, LibraryLocation]],
        progress: Callable[[str, int, int], None] | None = None,
) -> list[DuplicateGroup]:
    """The clustering core shared by find_duplicate_groups (single
    location) and find_duplicate_groups_across_scopes (pooled, possibly
    cross-location) — each file carries its OWN location here (not one
    shared location) specifically so quality analysis resolves the right
    real path for every file regardless of which location it actually
    lives in.
    """
    location_by_id = {
        local_file.id: location for local_file, location in files_with_locations
    }
    fingerprinted = [
        local_file for local_file, _ in files_with_locations
        if local_file.fingerprint is not None
    ]

    # Decoded once per file and reused across every pairwise comparison
    # below (see HISTORY §39). Progress is staged: "Decoding
    # fingerprints" is per-file progress — n steps, not one bar
    # covering both stages.
    decoded_by_id: dict[int, np.ndarray] = {}
    total = len(fingerprinted)
    for index, local_file in enumerate(fingerprinted, start=1):
        assert local_file.id is not None and local_file.fingerprint is not None
        decoded_by_id[local_file.id] = decode_fingerprint(
            local_file.fingerprint
        )
        if progress is not None:
            progress("Decoding fingerprints", index, total)

    clusters = _cluster_by_similarity(fingerprinted, decoded_by_id, progress)

    groups = []
    # A file can have a cached fingerprint (so it clusters here) while
    # its local_files row no longer resolves to a real file on disk — a
    # stale row left behind by a rename that updated one overlapping
    # location's copy but not another's. analyze_local_file_quality()
    # opens the real file via mutagen, so this is the one place in
    # clustering that touches disk at all, and one bad file must not
    # abort the batch. Two separately-counted reasons, not one generic
    # "failed": a row whose path doesn't exist at all (stale index —
    # self-heals on the next `library scan`) vs. a real file mutagen/
    # the OS still can't open. Reported via logger.warning(), like the
    # other batch methods' skipped items; the return type stays
    # list[DuplicateGroup]. See HISTORY §93.
    skipped_missing = 0
    skipped_other = 0

    for cluster in clusters:
        files = []

        for local_file in cluster:
            location = location_by_id[local_file.id]
            file_path = Path(location.path) / local_file.relative_path

            try:
                if not file_path.exists():
                    raise _FileMissingError(f"{file_path} does not exist")

                quality = analyze_local_file_quality(file_path)
            except Exception as error:
                if isinstance(error, _FileMissingError):
                    skipped_missing += 1
                else:
                    skipped_other += 1
                logger.warning(
                    "Skipping %s from duplicate clustering: %s",
                    local_file.filename, error,
                )
                continue

            files.append(DuplicateFile(local_file=local_file, quality=quality))

        # A "duplicate" of one (or zero) remaining, present file isn't
        # a group worth reporting any more — matches the same
        # "silently excluded, not an error" precedent this function's
        # own docstring already documents for files with no fingerprint
        # at all.
        if len(files) < 2:
            continue

        files.sort(key=lambda f: _quality_sort_key(f.quality), reverse=True)

        groups.append(
            DuplicateGroup(
                files=files,
                similarity=_min_pairwise_similarity(cluster, decoded_by_id),
            )
        )

    if skipped_missing or skipped_other:
        logger.warning(
            "Duplicate scan: %d file(s) skipped (index out of date — "
            "file no longer at its recorded path; a library scan will "
            "reconcile this), %d file(s) skipped (could not be opened).",
            skipped_missing, skipped_other,
        )

    return groups


def _quality_sort_key(quality: LocalFileQuality) -> tuple[int, int]:
    # Reuses the same tier scale quality_tier_for_format() already
    # establishes (lossless > lossy > unknown); bitrate is the
    # secondary tiebreak, matching soulseek/quality.py's own
    # _sort_key precedent for remote candidates. Clipping/loudness are
    # deliberately NOT part of the sort key — informational only, per
    # the task's own scoping.
    return (quality.tier, quality.bitrate_kbps or 0)


def _cluster_by_similarity(
        files: list[LocalFile],
        decoded_by_id: dict[int, np.ndarray],
        progress: Callable[[str, int, int], None] | None = None,
) -> list[list[LocalFile]]:
    n = len(files)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    # An O(n^2) sweep over every pair — even with a cheap per-pair skip
    # check — takes several minutes at ~3,100 fingerprinted files
    # purely from Python-loop overhead, independent of
    # fingerprint-decode caching (see HISTORY §39). Sorting by duration
    # first turns it into a bounded sliding window: once two files (in
    # duration order) are more than DURATION_TOLERANCE_MS apart, every
    # file further along is even further apart, so the inner loop can
    # break instead of scanning the rest of the list.
    def _duration_ms(i: int) -> int:
        duration = files[i].duration_ms
        assert duration is not None
        return duration

    with_duration = sorted(
        (i for i in range(n) if files[i].duration_ms is not None),
        key=_duration_ms,
    )

    # Stage 2's progress counts the OUTER loop (n steps, "Comparing
    # 900/3,142"), not the inner window, which has no fixed size to
    # report against.
    comparison_total = len(with_duration)

    for a_pos in range(len(with_duration)):
        i = with_duration[a_pos]
        duration_i = files[i].duration_ms
        assert duration_i is not None

        for b_pos in range(a_pos + 1, len(with_duration)):
            j = with_duration[b_pos]
            duration_j = files[j].duration_ms
            assert duration_j is not None

            if duration_j - duration_i > DURATION_TOLERANCE_MS:
                break

            if _plausible_duplicate_pair(files[i], files[j], decoded_by_id):
                union(i, j)

        if progress is not None:
            progress("Comparing", a_pos + 1, comparison_total)

    # Files with no reported duration never had a pre-filter applied at
    # all (see _plausible_duplicate_pair) — still compared against
    # every other file, same as before this optimization. Expected to
    # be empty/rare in practice (library/scanner.py always populates
    # duration_ms via mutagen), so an unoptimized sweep here is fine.
    without_duration = [i for i in range(n) if files[i].duration_ms is None]
    already_compared: set[tuple[int, int]] = set()

    for i in without_duration:
        for j in range(n):
            if j == i:
                continue

            pair_key = (min(i, j), max(i, j))
            if pair_key in already_compared:
                continue
            already_compared.add(pair_key)

            if _plausible_duplicate_pair(files[i], files[j], decoded_by_id):
                union(i, j)

    groups: dict[int, list[LocalFile]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(files[i])

    return [group for group in groups.values() if len(group) > 1]


def _plausible_duplicate_pair(
        a: LocalFile,
        b: LocalFile,
        decoded_by_id: dict[int, np.ndarray],
) -> bool:
    if (
        a.duration_ms is not None
        and b.duration_ms is not None
        and abs(a.duration_ms - b.duration_ms) > DURATION_TOLERANCE_MS
    ):
        return False

    assert a.id is not None and b.id is not None

    return (
        similarity_from_decoded(decoded_by_id[a.id], decoded_by_id[b.id])
        >= DUPLICATE_SIMILARITY_THRESHOLD
    )


def _min_pairwise_similarity(
        files: list[LocalFile],
        decoded_by_id: dict[int, np.ndarray],
) -> float:
    similarities = []

    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            a, b = files[i], files[j]
            assert a.id is not None and b.id is not None
            similarities.append(
                similarity_from_decoded(decoded_by_id[a.id], decoded_by_id[b.id])
            )

    # A group always has >= 2 members (see _cluster_by_similarity's own
    # len(group) > 1 filter), so at least one pair always exists.
    return min(similarities)

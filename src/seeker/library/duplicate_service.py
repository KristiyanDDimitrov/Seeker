from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from seeker.audio_fingerprint import (
    FingerprintError,
    FingerprintingUnavailableError,
    compute_fingerprint,
    decode_fingerprint,
    similarity_from_decoded,
)
from seeker.audio_fingerprint import (
    is_available as fingerprinting_is_available,
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
from seeker.file_deletion import delete_file, same_file
from seeker.models.duplicate_cleanup import DuplicateCleanup
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.track_match import TrackMatch
from seeker.soulseek.quality import LocalFileQuality, analyze_local_file_quality


class LibraryLocationNotFoundError(RuntimeError):
    pass


# Roadmap item 68 (Phase 8.2/8.3) — per-file fingerprint-failure reason
# codes, surfaced in compute_fingerprints()'s `details` (already printed
# per-line by both the CLI and consumable by the UI) instead of one
# generic "failed" for everything. `_EmptyFileError` in particular
# exists to satisfy Phase 8.3: a genuinely 0-byte file is flagged
# distinctly from a real decode failure — it can never succeed a
# fingerprint attempt (nothing to decode), so it can also never enter a
# duplicate group; nothing here ever offers to delete it, matching the
# brief's own "never offer to delete" scope.
_REASON_FILE_MISSING = "file_missing"
_REASON_EMPTY_FILE = "empty_file"
_REASON_DECODE_UNSUPPORTED = "decode_unsupported"
_REASON_ERROR = "error"


class _FileMissingError(RuntimeError):
    pass


class _SamePhysicalFileError(RuntimeError):
    """Roadmap item 93 (R3.3) — overlapping registered library locations
    (item 77) can index the SAME real file twice, as two different
    local_files rows. find_duplicate_groups is deliberately content-
    based and location-agnostic, so a group built from exactly that
    pair is a real, valid cluster — but deleting "the other" row would
    delete the very file the caller asked to keep. Raised by
    _delete_one_local_file before either the DB row or the disk file is
    touched; caught by delete_local_files and counted separately from
    an ordinary failure."""


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


# Untuned threshold, flagged same as every other constant in this
# codebase — Hamming-distance similarity at or above this counts as a
# real duplicate. Confirmed live (item 5's Phase 0 spike, see
# docs/HISTORY.md §38): real duplicate pairs — including a real
# cross-format FLAC/MP3 transcode — scored 99.87-99.98% similarity,
# while an unrelated real pair scored ~58%. 0.95 sits with a wide, real
# margin on both sides of that gap without needing tuning yet.
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
    """Roadmap item 68 (Phase 7.2) — one real, resolved folder to
    include in a pooled duplicate search: a registered library location
    plus the folder's path relative to that location's root (empty
    string means the whole location). Built by resolve_folder_scopes()
    from real absolute paths (e.g. a folder picker) — never constructed
    directly by a caller that hasn't gone through that resolution, so a
    scope can never silently point outside every registered location.
    """
    location: LibraryLocation
    folder_relative_path: str


@dataclass
class ScopeSummary:
    """Roadmap item 77 (P8.3/8.4) — the honest scope-count result:
    not just a bare number, but which real location(s) it resolved to
    and which of those have never been scanned at all."""
    file_count: int
    resolved_location_names: list[str]
    empty_locations: list[str]


@dataclass
class GroupResolutionPlan:
    """Roadmap item R3.2 — one group's already-decided resolution,
    computed by the caller (the UI, from the user's own kept-radio
    selection — see main_window's `_duplicates_keep_selection`) and
    trusted here exactly the same way `delete_local_files` already
    trusts an explicit `local_file_ids`/`keep_local_file_id` pair —
    this dataclass doesn't re-derive or re-validate the choice against
    `find_duplicate_groups`'s own clustering."""
    delete_local_file_ids: list[int]
    keep_local_file_id: int
    location_id: int | None


@dataclass
class BulkDuplicateResolutionResult:
    """Roadmap item R3.2 — the real per-group/per-file outcome of a
    "Resolve all groups" batch, same honest-reporting shape as
    `BulkUpgradeReplaceResult`/`format_rename_result_message`: counts
    for the headline, plus one detail line per group that had any real
    failure. `plan_outcomes` (same order/length as the input `plans`)
    lets a caller that also tracks per-group UI state (e.g. dropping a
    fully-resolved group from an in-memory list without a full
    re-fetch) know exactly which plans actually succeeded, rather than
    inferring it from the aggregate counts alone."""
    groups_resolved: int
    groups_failed: int
    files_deleted: int
    files_failed: int
    # Roadmap item 93 (R3.3) — a SUBSET of files that were neither
    # deleted nor counted as failed: refused by the same-physical-file
    # guard (an overlapping registered location indexed the exact file
    # being kept a second time). Not a failure — the safety check did
    # exactly what it should — but not silently folded into
    # files_deleted either.
    files_skipped_same_physical_file: int
    bytes_freed: int
    details: list[str]
    plan_outcomes: list[bool]


def _path_within_folder(
        file_relative_path: str,
        folder_relative_path: str,
) -> bool:
    # Roadmap item 68 (Phase 7.2) — path-prefix matching that respects
    # separator boundaries: "Trance" must never match "TranceX". A bare
    # str.startswith() check would get this wrong; PurePath.is_relative_to
    # (via Path here, a pure logical operation — no filesystem I/O) does
    # not.
    if not folder_relative_path:
        return True  # "" means the whole location.

    return Path(file_relative_path).is_relative_to(Path(folder_relative_path))


class DuplicateService:
    """Per-library-location fingerprint computation and duplicate
    clustering (roadmap item 5), plus the group-resolution delete action
    (roadmap item 40) — deliberately scoped to one `library_locations`
    row at a time, the same unit `library add`/`list`/`remove` already
    use, not merged across every registered location.
    `compute_fingerprints`/`find_duplicate_groups` are read-only, per
    item 5's own build-order note; `delete_local_files` is the one
    filesystem-destructive method here, and is never called without an
    explicit, caller-confirmed list of ids (see CLAUDE.md item 40 for
    the UI's own double-confirm flow before it's ever invoked)."""

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
        # Optional, defaulted rather than required — every existing
        # caller/test that constructs a DuplicateService without one
        # (Phase 6.4 is additive) is unaffected; only record_cleanup()/
        # get_cleanup_totals() need it.
        self.duplicate_cleanups = (
            duplicate_cleanup_repository or DuplicateCleanupRepository(database)
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
    ) -> dict[str, Any]:
        """Compute and persist a fingerprint for every file at this
        location that doesn't already have one (or every file,
        regardless, if force=True) — mirrors MetadataService.tag_tracks'
        own skip-already-done/force/per-item-try-except shape.

        Roadmap item 68 (Phase 7.2) — `folders`, when given, scopes this
        to only the files whose relative_path falls under one of these
        (location-relative) folder paths — fingerprinting one real
        folder instead of a whole multi-thousand-file location is the
        bigger practical win of the two scoped operations (Phase 7.2's
        own brief). `progress` (Phase 7.3), when given, is called as
        `progress(stage, current, total)` — a single stage here
        ("Fingerprinting"), `total` = files actually in scope.
        """
        if not fingerprinting_is_available():
            # One clear failure, not N per-file ones, for a single root
            # cause — same "checked before use" precedent as
            # Application.soulseek_configured (item 28).
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
            local_files = self.local_files.get_all_for_location(
                location.id, connection,
            )

        if folders:
            local_files = [
                f for f in local_files
                if any(
                    _path_within_folder(f.relative_path, folder)
                    for folder in folders
                )
            ]

        counts: dict[str, int] = {
            "computed": 0,
            "skipped_already_computed": 0,
            "failed": 0,
        }
        details: list[dict[str, str]] = []
        total = len(local_files)

        for index, local_file in enumerate(local_files, start=1):
            try:
                self._compute_one(
                    location, local_file, force, counts, details,
                )
            except Exception as error:
                counts["failed"] += 1
                details.append(
                    {
                        "local_file_id": str(local_file.id),
                        "reason": _classify_fingerprint_failure(error),
                        "message": f"{local_file.filename}: {error}",
                    }
                )
                print(f"  Failed to fingerprint {local_file.filename}: {error}")

            if progress is not None:
                progress("Fingerprinting", index, total)

        return {**counts, "details": details}

    def _compute_one(
            self,
            location: LibraryLocation,
            local_file: LocalFile,
            force: bool,
            counts: dict[str, int],
            details: list[dict[str, str]],
    ) -> None:
        if local_file.fingerprint is not None and not force:
            counts["skipped_already_computed"] += 1
            return

        file_path = Path(location.path) / local_file.relative_path

        # Roadmap item 68 (Phase 8.2/8.3) — checked BEFORE
        # compute_fingerprint() so these two real, distinct causes get
        # their own reason codes instead of surfacing as whatever
        # message soundfile/ffmpeg happen to raise for "nothing here."
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

        counts["computed"] += 1
        print(f"  Fingerprinted: {local_file.filename}")

    def resolve_folder_scopes(
            self,
            folder_paths: list[str],
            preferred_location_id: int | None = None,
    ) -> list[DuplicateFolderScope]:
        """Roadmap item 68 (Phase 7.2) — resolves real, absolute folder
        paths (e.g. from a folder picker) against every registered
        library location. Each folder must resolve inside a registered
        location; anything else is rejected with a clear message —
        fingerprints only exist for indexed files, and an unregistered
        folder was never scanned at all.

        Roadmap item 77 (P8) — MOST-SPECIFIC-WINS: a folder can be
        "inside" more than one registered location at once (a location
        registered at a parent path, and another registered at a
        nested child path both cover the same real folder), and the
        previous code took the first alphabetical-by-name match
        (get_all()'s own ORDER BY name), not the best one. Confirmed
        live against this project's own real production DB: a folder
        equal to the "Test" location's own path (nested under "Music",
        which is itself nested under "x9-pro") alphabetically matched
        "Music" first — a location with ZERO scanned files — giving a
        false "0 files in scope" even though "Test" had real
        fingerprinted files at that exact path. Now every candidate
        location the folder resolves inside is scored by its own
        resolved path length and the LONGEST (most specific) one wins.
        `preferred_location_id`, when given (the UI's own selected
        location combo — see P9), breaks a genuine tie only; it can
        never override a strictly-more-specific match, so "prefer this
        location" never silently widens a folder's real scope.
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
        every call, never persisted as its own table (see CLAUDE.md
        item 5: persisting group membership would go stale the moment
        a file moves or gets rescanned). Files with no fingerprint yet
        (compute_fingerprints() hasn't run for them) are silently
        excluded, not treated as an error — a partial fingerprint
        coverage is a completely normal, expected state.

        Roadmap item 68 (Phase 7.2) — `folders`, when given (location-
        relative paths), scopes this to only files under one of them.
        Unchanged single-location behavior when omitted, for the CLI
        and every existing caller.
        """
        with self.database.transaction() as connection:
            location = self._get_location_or_raise(location_name, connection)
            # Loaded from the DB just above via get_by_name, so .id is set.
            assert location.id is not None
            local_files = self.local_files.get_all_for_location(
                location.id, connection,
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
                all_files = self.local_files.get_all_for_location(
                    scope.location.id, connection,
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
        """Roadmap item 68 (Phase 7.2) — pools every given folder (each
        already resolved via resolve_folder_scopes) into ONE set,
        compared together — including across different real library
        locations, deliberately allowed: the clustering itself is
        purely content-based (Hamming distance over decoded audio
        fingerprints) and location-agnostic, so there's no reason two
        folders living in different registered locations couldn't hold
        the same real recording.
        """
        return _cluster_duplicate_groups(
            self._files_for_scopes(scopes), progress,
        )

    def count_files_for_scopes(
            self, scopes: list[DuplicateFolderScope],
    ) -> int:
        """Roadmap item 68 (Phase 7.2) — a real file count BEFORE
        starting a real, potentially ~10-minute-at-real-scale operation
        (item 39's own real number), so the scope control is worth
        having — the user sees what a scope actually covers first."""
        return len(self._files_for_scopes(scopes))

    def summarize_scopes(
            self, scopes: list[DuplicateFolderScope],
    ) -> "ScopeSummary":
        """Roadmap item 77 (P8.3/8.4) — the honest version of
        count_files_for_scopes(): a bare "0 files in scope" gives no
        way to tell "this folder really is empty" apart from "this
        resolved to the wrong (unscanned) location", which is exactly
        what made the reported bug unreadable. Also reports which
        location(s) the folders actually resolved to (P8.3) and which
        of those have NO scanned files at all, location-wide, not just
        within the folder (P8.4) — a location with zero total
        local_files rows was never scanned, so "run a scan" is the
        real fix, not something more fingerprinting could ever solve.
        """
        file_count = 0
        resolved_location_names: list[str] = []
        empty_locations: list[str] = []
        files_by_location_id: dict[int, list[LocalFile]] = {}

        with self.database.transaction() as connection:
            for scope in scopes:
                assert scope.location.id is not None

                if scope.location.id not in files_by_location_id:
                    all_files = self.local_files.get_all_for_location(
                        scope.location.id, connection,
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
        `keep_local_file_id`: the caller (the UI, per its own double-
        confirm flow — see CLAUDE.md item 40) decides which specific ids
        to delete; this method trusts that decision rather than
        re-deriving or re-validating it against `find_duplicate_groups`'
        own clustering. Per-item try/except, same batch-safety shape as
        `compute_fingerprints`.

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
        which `library/scanner.py`'s own reachability logic
        (`delete_missing`) already self-heals on the next `library
        scan` by simply rediscovering it as a "new" file. The reverse
        order (file first, DB row second) would instead leave a
        `local_files` row pointing at a file that no longer exists, in
        the window before that same next scan repairs it — a state a
        matcher or tagger run in that window could act on and fail
        against, which is worse than a merely-orphaned file.

        `location_id` (roadmap item 56 Phase 6.4), when given, is
        recorded on the resulting `duplicate_cleanups` row — purely
        informational provenance for the reclaimed-space milestone, not
        used to scope or validate the deletion itself. A real,
        non-zero `bytes_freed` is recorded whenever at least one file
        was actually deleted; a batch that deleted nothing (all
        failed) records nothing at all, matching "an empty milestone
        is worse than no milestone."
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
                print(f"  Refused to delete local file {local_file_id}: {error}")
            except Exception as error:
                counts["failed"] += 1
                details.append(
                    {
                        "local_file_id": str(local_file_id),
                        "message": str(error),
                    }
                )
                print(f"  Failed to delete local file {local_file_id}: {error}")
            else:
                counts["deleted"] += 1

        if counts["deleted"] > 0:
            self.record_cleanup(counts["deleted"], bytes_freed, location_id)

        return {**counts, "details": details, "bytes_freed": bytes_freed}

    def resolve_groups(
            self, plans: list[GroupResolutionPlan],
    ) -> BulkDuplicateResolutionResult:
        """Roadmap item R3.2 — "Resolve all groups". Applies
        `delete_local_files()` per plan (one per group the caller
        decided to resolve — a "Keep all" group is never turned into a
        plan at all, decided by the UI before this is ever called, not
        filtered here). Per-plan try/except (item 15's standing
        batch-loop pattern) so one group's total failure can't abort
        the rest — `delete_local_files` already has its own per-FILE
        try/except underneath this, so a failure here means the whole
        group call raised, not just one file within it.
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

            # Roadmap item 93 (R3.3) — checked before anything else
            # touches the DB row or disk. See _SamePhysicalFileError's
            # own docstring for why this is reachable at all: two
            # overlapping registered locations can each hold their own
            # local_files row for the identical real file.
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

            # Roadmap item 56 Phase 6.4 — measured from the real file
            # via stat() BEFORE either the DB row or the file itself is
            # deleted (item 40's own standing ordering rule still
            # applies below: DB row first, then file). Falls back to
            # the stored size_bytes column if the real file is already
            # gone from disk — still a real, previously-recorded size,
            # not a guess.
            bytes_freed = local_file.size_bytes
            if file_path is not None:
                try:
                    bytes_freed = file_path.stat().st_size
                except OSError:
                    pass

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
        to be deleted, re-point it at the group's surviving file instead
        of leaving it to fall back to the schema's `ON DELETE SET NULL`
        cascade.

        Confirmed live, not assumed, that this matters: the cascade
        only nulls `local_file_id` — it leaves `match_method`/`score`
        untouched, so a track that was `match_method='auto'` stays
        `'auto'` with `local_file_id=NULL`. Checked directly what that
        combination does downstream: `DashboardService._compute_status`
        requires BOTH `match_method == "auto"` AND a resolvable
        `local_file_id` for `IN_LIBRARY`, so the track falsely shows
        `NOT_FOUND` — even though the group's other (often
        higher-quality) copy is sitting right there. Checked the
        actual re-download risk this could imply, not just the display
        bug: `TrackRepository.get_unmatched_for_playlist` (what
        `download_playlist` actually schedules against) filters on
        `match_method IS NULL`, which stays FALSE for this row (it's
        still `'auto'`) — so `download_playlist` does NOT pick it back
        up either, meaning the track is stuck in limbo (shown missing,
        never re-searched) rather than actually re-downloaded. Neither
        outcome is acceptable, and re-pointing avoids both: no separate
        "repoint" helper exists elsewhere to reuse (every real call site
        — `TrackMatcher.match_all()`, `DownloadService
        .apply_upgrade_decision`'s replace path — just constructs a
        `TrackMatch` and calls `TrackMatchRepository.upsert()` directly;
        that IS the reusable primitive, already used the same way here).
        `match_method`/`score` are preserved as-is (not re-evaluated) —
        the underlying audio is fingerprint-confirmed near-identical
        (>= DUPLICATE_SIMILARITY_THRESHOLD), so the existing match's own
        confidence is still the right thing to report; only
        `matched_at` is refreshed to reflect that the pointer just
        changed.
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
    """Roadmap item 68 (Phase 7.2/7.3) — the real clustering core shared
    by find_duplicate_groups (single location) and
    find_duplicate_groups_across_scopes (pooled, possibly cross-
    location) — each file carries its OWN location here (not one shared
    location) specifically so quality analysis resolves the right real
    path for every file regardless of which location it actually lives
    in.
    """
    location_by_id = {
        local_file.id: location for local_file, location in files_with_locations
    }
    fingerprinted = [
        local_file for local_file, _ in files_with_locations
        if local_file.fingerprint is not None
    ]

    # Decoded once per file and reused across every pairwise comparison
    # below (item 5's own live-verified optimization — see
    # docs/HISTORY.md). Staged progress (Phase 7.3): "Decoding
    # fingerprints" is real, honest per-file progress — n steps, not a
    # fake single bar covering both real stages.
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
    # Roadmap item 93 (B3.5/R3.3) — a real, previously-uncaught crash:
    # a file can have a cached fingerprint (so it clusters here) while
    # its local_files row no longer resolves to a real file on disk — a
    # stale row left behind by a rename that updated one overlapping
    # location's copy but not another's (item 76's own documented drift
    # class). analyze_local_file_quality() opens the real file via
    # mutagen, so this is the one place in clustering that touches disk
    # at all. Per-file try/except, this codebase's own standing "one bad
    # item must not abort a batch" pattern (item 15) — every OTHER batch
    # method here already has this; clustering didn't. Two distinct,
    # separately-counted reasons, not one generic "failed": a row whose
    # path doesn't exist at all (stale index — self-heals on the next
    # `library scan`) vs. a real file mutagen/the OS still can't open
    # (a genuinely bad file). Reported via print(), matching this
    # codebase's own console-reporting idiom for skipped-in-a-batch
    # items (e.g. compute_fingerprints/tag_tracks) — surfacing this in
    # the UI's own result panel is a real follow-up, not done here (see
    # CLAUDE.md roadmap item 93 for why the return type stayed
    # unchanged: list[DuplicateGroup], not a (groups, skipped) tuple).
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
                print(
                    f"  Skipping {local_file.filename} from duplicate "
                    f"clustering: {error}"
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
        print(
            f"  Duplicate scan: {skipped_missing} file(s) skipped "
            f"(index out of date — file no longer at its recorded "
            f"path; a library scan will reconcile this), "
            f"{skipped_other} file(s) skipped (could not be opened)."
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

    # A genuine O(n^2) sweep over every pair — even with a cheap
    # per-pair skip check — was confirmed live (item 5's verification
    # against ~3,100 real fingerprinted files, see docs/HISTORY.md) to
    # take several real minutes purely from Python-loop overhead at
    # that scale, independent of fingerprint-decode caching. Sorting
    # by duration first turns it into a bounded sliding window: once
    # two files (in duration order) are more than DURATION_TOLERANCE_MS
    # apart, every file further along is even further apart, so the
    # inner loop can break instead of scanning the rest of the list.
    def _duration_ms(i: int) -> int:
        duration = files[i].duration_ms
        assert duration is not None
        return duration

    with_duration = sorted(
        (i for i in range(n) if files[i].duration_ms is not None),
        key=_duration_ms,
    )

    # Roadmap item 68 (Phase 7.3) — Stage 2's own real progress: the
    # OUTER loop here is n steps (matching the brief's own "Comparing
    # 900/3,142" example), not the inner window (which has no fixed
    # size to report against meaningfully).
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
    if a.duration_ms is not None and b.duration_ms is not None:
        if abs(a.duration_ms - b.duration_ms) > DURATION_TOLERANCE_MS:
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

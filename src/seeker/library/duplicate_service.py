from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from seeker.audio_fingerprint import (
    FingerprintingUnavailableError,
    compute_fingerprint,
    decode_fingerprint,
    is_available as fingerprinting_is_available,
    similarity_from_decoded,
)
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.file_deletion import delete_file
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.soulseek.quality import LocalFileQuality, analyze_local_file_quality


class LibraryLocationNotFoundError(RuntimeError):
    pass


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
    ):
        self.database = database
        self.locations = location_repository
        self.local_files = local_file_repository

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
    ) -> dict[str, Any]:
        """Compute and persist a fingerprint for every file at this
        location that doesn't already have one (or every file,
        regardless, if force=True) — mirrors MetadataService.tag_tracks'
        own skip-already-done/force/per-item-try-except shape.
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

        counts: dict[str, int] = {
            "computed": 0,
            "skipped_already_computed": 0,
            "failed": 0,
        }
        details: list[dict[str, str]] = []

        for local_file in local_files:
            try:
                self._compute_one(
                    location, local_file, force, counts, details,
                )
            except Exception as error:
                counts["failed"] += 1
                details.append(
                    {
                        "local_file_id": str(local_file.id),
                        "reason": "failed",
                        "message": f"{local_file.filename}: {error}",
                    }
                )
                print(f"  Failed to fingerprint {local_file.filename}: {error}")

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
        fingerprint = compute_fingerprint(file_path)

        with self.database.transaction() as connection:
            # Loaded from the DB just above, so .id is set.
            assert local_file.id is not None

            self.local_files.update_fingerprint(
                local_file.id,
                fingerprint.data,
                fingerprint.duration_seconds,
                datetime.now(timezone.utc).isoformat(),
                connection,
            )

        counts["computed"] += 1
        print(f"  Fingerprinted: {local_file.filename}")

    def find_duplicate_groups(
            self,
            location_name: str,
    ) -> list[DuplicateGroup]:
        """Cluster this location's already-fingerprinted files by
        Hamming distance — computed fresh from cached fingerprints on
        every call, never persisted as its own table (see CLAUDE.md
        item 5: persisting group membership would go stale the moment
        a file moves or gets rescanned). Files with no fingerprint yet
        (compute_fingerprints() hasn't run for them) are silently
        excluded, not treated as an error — a partial fingerprint
        coverage is a completely normal, expected state.
        """
        with self.database.transaction() as connection:
            location = self._get_location_or_raise(location_name, connection)
            # Loaded from the DB just above via get_by_name, so .id is set.
            assert location.id is not None
            local_files = self.local_files.get_all_for_location(
                location.id, connection,
            )

        fingerprinted = [f for f in local_files if f.fingerprint is not None]

        # Decoded once per file and reused across every pairwise
        # comparison below, rather than re-decoding a file's
        # fingerprint on every comparison it's involved in — confirmed
        # live to matter for real: a real clustering pass over ~3,100
        # real fingerprinted files was multiple minutes slower and used
        # several GB more memory before this caching was added (item
        # 5's live verification, see docs/HISTORY.md).
        decoded_by_id: dict[int, np.ndarray] = {}
        for local_file in fingerprinted:
            assert local_file.id is not None and local_file.fingerprint is not None
            decoded_by_id[local_file.id] = decode_fingerprint(
                local_file.fingerprint
            )

        clusters = _cluster_by_similarity(fingerprinted, decoded_by_id)

        groups = []

        for cluster in clusters:
            files = [
                DuplicateFile(
                    local_file=local_file,
                    quality=analyze_local_file_quality(
                        Path(location.path) / local_file.relative_path
                    ),
                )
                for local_file in cluster
            ]
            files.sort(key=lambda f: _quality_sort_key(f.quality), reverse=True)

            groups.append(
                DuplicateGroup(
                    files=files,
                    similarity=_min_pairwise_similarity(cluster, decoded_by_id),
                )
            )

        return groups

    def delete_local_files(self, local_file_ids: list[int]) -> dict[str, Any]:
        """Deletes each given local file — both its `local_files` DB row
        and the real file on disk — used to resolve a duplicate group by
        removing every member except whichever one the caller decided to
        keep. Deliberately has no notion of "groups" itself: the caller
        (the UI, per its own double-confirm flow — see CLAUDE.md item
        40) decides which specific ids to delete; this method trusts
        that decision rather than re-deriving or re-validating it against
        `find_duplicate_groups`' own clustering. Per-item try/except,
        same batch-safety shape as `compute_fingerprints`.

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
        against, which is worse than a merely-orphaned file. Checked
        directly rather than assumed: `local_files.delete_by_id`
        cascades `track_matches.local_file_id` to NULL via the schema's
        own `ON DELETE SET NULL` (confirmed enforced —
        `Database`/`connection.py` sets `PRAGMA foreign_keys = ON`), so
        a track matched to a deleted duplicate goes back to unmatched
        rather than being left pointing at a deleted row.
        """
        counts = {"deleted": 0, "failed": 0}
        details: list[dict[str, str]] = []

        for local_file_id in local_file_ids:
            try:
                self._delete_one_local_file(local_file_id)
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

        return {**counts, "details": details}

    def _delete_one_local_file(self, local_file_id: int) -> None:
        with self.database.transaction() as connection:
            local_file = self.local_files.get_by_id(local_file_id, connection)

            if local_file is None:
                # Already gone -- the desired end state (no such row,
                # no such file tracked) is already true.
                return

            location = self.locations.get_by_id(
                local_file.location_id, connection,
            )
            self.local_files.delete_by_id(local_file_id, connection)

        if location is None:
            # A local_files row with no matching library_locations row
            # isn't a state this schema's own foreign keys allow --
            # nothing further to delete on disk.
            return

        file_path = Path(location.path) / local_file.relative_path
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

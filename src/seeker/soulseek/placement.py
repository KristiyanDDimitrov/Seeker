"""Where a finished download goes, and getting it there: finding the
file slskd wrote, moving it into its destination folder without ever
landing on an existing file, then indexing and matching it into the
library."""

import glob
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from seeker.config_store import SeekerConfig
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
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.destination_resolution import resolve_playlist_destination
from seeker.files.naming import clean_peer_filename
from seeker.files.placement import resolve_collision
from seeker.library.matcher import find_best_match
from seeker.library.scanner import index_single_file
from seeker.models.download_request import DownloadRequest
from seeker.models.download_result import PollResult
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.track import is_manual_track_id
from seeker.models.track_match import TrackMatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompletedFileLookup:
    """Where a finished download sits in slskd's download directory.
    `path` is None when it cannot be named unambiguously; `problem`
    then says why (None when the file is simply not there yet)."""
    path: Path | None
    problem: str | None = None


def _locate_completed_file(
        download_dir: Path,
        request: DownloadRequest,
) -> CompletedFileLookup:
    """Finds the file slskd wrote for `request`, or refuses to guess.

    slskd writes `<remote parent folder>/<basename>` and, when that
    name is taken, `<stem>_<UtcNow.Ticks><suffix>` instead
    (`FileService.MoveFile`, HISTORY §138). So candidates are looked
    for under the remote parent's name first, with a whole-tree search
    only as the fallback, and `request.size` (the requested file's
    exact byte size) narrows them. Several same-size survivors are one
    file downloaded more than once: the newest wins. With no size to
    check, more than one candidate is ambiguous and nothing is chosen.
    """
    remote = PurePosixPath(request.filename.replace("\\", "/"))
    basename = remote.name

    if basename in ("", ".", ".."):
        return CompletedFileLookup(
            None, f"remote filename {request.filename!r} names no file",
        )

    stem = PurePosixPath(basename).stem
    suffix = PurePosixPath(basename).suffix
    clash_copy = re.compile(
        re.escape(stem) + r"_\d+" + re.escape(suffix),
    )

    def is_candidate(path: Path) -> bool:
        return path.is_file() and (
            path.name == basename or clash_copy.fullmatch(path.name) is not None
        )

    def of_requested_size(paths: list[Path]) -> list[Path]:
        if request.size is None:
            return paths
        return [path for path in paths if path.stat().st_size == request.size]

    found: list[Path] = []
    survivors: list[Path] = []
    parent_folder = download_dir / remote.parent.name

    if remote.parent.name not in ("", ".", "..") and parent_folder.is_dir():
        found = [path for path in parent_folder.iterdir() if is_candidate(path)]
        survivors = of_requested_size(found)

    if not survivors:
        tree = set(download_dir.rglob(glob.escape(basename)))
        tree.update(
            download_dir.rglob(f"{glob.escape(stem)}_*{glob.escape(suffix)}")
        )
        found = sorted(path for path in tree if is_candidate(path))
        survivors = of_requested_size(found)

    if len(survivors) == 1:
        return CompletedFileLookup(survivors[0])

    if not survivors:
        if not found:
            return CompletedFileLookup(None)
        return CompletedFileLookup(
            None,
            f"{len(found)} file(s) named '{basename}' found, none of the "
            f"requested {request.size} bytes",
        )

    if request.size is None:
        return CompletedFileLookup(
            None,
            f"{len(survivors)} files named '{basename}' found and the "
            f"requested size is unknown; not guessing",
        )

    newest = max(survivors, key=lambda path: path.stat().st_mtime)
    logger.info(
        "%d files named '%s' of %d bytes; taking the newest, %s",
        len(survivors), basename, request.size, newest,
    )
    return CompletedFileLookup(newest)


@dataclass(frozen=True)
class SettleTarget:
    """A finished download's current path, and the path it would take
    in its destination folder before any collision is resolved."""
    location: LibraryLocation
    source: Path
    proposed_path: Path


class DownloadPlacement:
    def __init__(
        self,
        database: Database,
        playlist_repository: PlaylistRepository,
        track_repository: TrackRepository,
        library_location_repository: LibraryLocationRepository,
        local_file_repository: LocalFileRepository,
        track_match_repository: TrackMatchRepository,
        slskd_download_dir: str | None,
        get_config: Callable[[], SeekerConfig],
    ):
        self.database = database
        self.playlists = playlist_repository
        self.tracks = track_repository
        self.locations = library_location_repository
        self.local_files = local_file_repository
        self.track_matches = track_match_repository
        self.slskd_download_dir = slskd_download_dir
        # A callable, not a snapshot: a Settings change to the default
        # destination applies on the very next call.
        self._get_config = get_config
        # Request ids whose file could not be located unambiguously
        # and have been logged at WARNING already: every poll retries
        # them, but the condition is reported once per process.
        self._unlocatable_reported: set[int] = set()

    def resolve_destination(
            self,
            playlist: Playlist | None,
    ) -> tuple[LibraryLocation, str | None] | None:
        """A playlist-specific download_location_id/download_subfolder
        always wins when set. Otherwise falls back to the configured
        default destination. The playlist's own name becomes the
        subfolder (sanitized — a real playlist name, "240KM/H",
        contains a literal path separator) only when
        default_download_subfolder_per_playlist is on. Returns None
        when neither resolves to a real, still-registered location —
        the caller's job to report that clearly.

        `playlist=None` is a manual (not-from-Spotify) search-and-
        download track, which has no playlist at all: always resolves
        via the configured default with a fixed "Manual" subfolder.

        The precedence rule itself lives in destination_resolution.py,
        shared with MetadataService's rename preview.
        """
        with self.database.transaction() as connection:
            return resolve_playlist_destination(
                playlist, self.locations, self._get_config, connection,
            )

    def settle_target(
            self,
            request: DownloadRequest,
    ) -> SettleTarget | None:
        """Where `request`'s finished file is now, and the path it
        would take in its destination folder. None, logged, when either
        cannot be determined."""
        if not self.slskd_download_dir:
            logger.warning(
                "SLSKD_DOWNLOAD_DIR is not configured; cannot move '%s'.",
                request.filename,
            )
            return None

        with self.database.transaction() as connection:
            playlists = self.playlists.get_by_track_id(
                request.track_id,
                connection,
            )

        resolved = None

        for playlist in playlists:
            resolved = self.resolve_destination(playlist)

            if resolved is not None:
                break

        if not playlists:
            # A manual (not-from-Spotify) track belongs to no playlist,
            # so the loop above never runs; without this every
            # completed manual download would stay in slskd's own
            # download dir forever. Scoped to "genuinely no playlist"
            # only — a playlist track with no resolvable destination is
            # left in place.
            resolved = self.resolve_destination(None)

        if resolved is None:
            logger.warning(
                "No configured destination found for track %s; leaving "
                "'%s' in place.", request.track_id, request.filename,
            )
            return None

        location, subfolder = resolved

        lookup = _locate_completed_file(
            Path(self.slskd_download_dir), request,
        )

        if lookup.path is None:
            self._report_unlocatable(request, lookup.problem)
            return None

        basename = clean_peer_filename(
            PurePosixPath(request.filename.replace("\\", "/")).name,
        )
        destination_dir = Path(location.path)

        if subfolder:
            destination_dir = destination_dir / subfolder

        return SettleTarget(location, lookup.path, destination_dir / basename)

    def move_completed_file(
            self,
            request: DownloadRequest,
    ) -> tuple[LibraryLocation, str] | None:
        target = self.settle_target(request)

        if target is None:
            return None

        return self.place_without_overwrite(target)

    def place_without_overwrite(
            self,
            target: SettleTarget,
    ) -> tuple[LibraryLocation, str]:
        target.proposed_path.parent.mkdir(parents=True, exist_ok=True)

        # Never onto an existing file: shutil.move replaces one silently
        # (os.rename on one volume, copy-then-unlink across volumes).
        destination_path = resolve_collision(
            target.source, target.proposed_path,
        )
        shutil.move(str(target.source), str(destination_path))

        logger.info(
            "Moved '%s' to %s", target.proposed_path.name, destination_path,
        )

        location = target.location
        relative_path = str(
            destination_path.relative_to(Path(location.path))
        )

        return (location, relative_path)

    def _report_unlocatable(
            self,
            request: DownloadRequest,
            problem: str | None,
    ) -> None:
        if problem is None:
            return

        if request.id is not None and request.id in self._unlocatable_reported:
            logger.debug("Still cannot locate '%s': %s", request.filename, problem)
            return

        if request.id is not None:
            self._unlocatable_reported.add(request.id)

        logger.warning(
            "Cannot locate the finished download '%s': %s. Leaving it "
            "for the next poll.", request.filename, problem,
        )

    def index_and_match(
            self,
            request: DownloadRequest,
            move_result: tuple[LibraryLocation, str],
            counts: PollResult,
    ) -> None:
        # Indexes and matches an ordinary settled download once it's
        # moved into place — without this, the file was invisible to
        # the rest of the app (no local_files row, no track_matches
        # row), and a second download run could re-search and
        # re-request a file already sitting on disk (HISTORY §45).
        #
        # Mirrors apply_upgrade_decision's own index+match tail.
        # match_method='auto' is set unconditionally,
        # regardless of the computed fuzzy score: this exact file was
        # searched, filtered by quality.py, and downloaded FOR this
        # exact track — that provenance is a stronger signal than
        # filename fuzzy-matching (HISTORY §26). Unlike the upgrade's
        # hardcoded score=100.0 sentinel, the real find_best_match()
        # score is computed and stored here so a genuinely bad pairing
        # stays visible in the data instead of being hidden behind a
        # fake perfect score.
        #
        # Wrapped in its own try/except, per this codebase's standing
        # per-item batch rule: an indexing/matching failure must not
        # undo the 'completed' status the caller already set (the file
        # really did download successfully), and must not abort the
        # rest of the poll.
        try:
            location, relative_path = move_result

            with self.database.transaction() as connection:
                local_file = index_single_file(
                    location, relative_path, self.local_files, connection,
                )

                track = self.tracks.get_by_id(request.track_id, connection)
                score = None

                if track is not None:
                    match = find_best_match(track, [local_file])
                    if match is not None:
                        score = match[1]

                    # A manual (not-from-Spotify) track is created with
                    # a placeholder duration_ms=0 (there's no real
                    # Spotify duration to record). find_best_match()
                    # above never reads duration at all (matching.py's
                    # scoring is artist+title only), so this doesn't
                    # affect THIS match — but a LATER match_all() re-run
                    # applies its own duration pre-filter
                    # (DURATION_TOLERANCE_MS, matcher.py) against every
                    # candidate local file, which a real duration_ms=0
                    # would fail against almost any real file and could
                    # demote this match back to unmatched. Backfilled
                    # here, once, from the real just-downloaded file's
                    # own read duration — never touches a real Spotify
                    # track's authoritative duration_ms (HISTORY §82).
                    if (
                            is_manual_track_id(track.id)
                            and local_file.duration_ms is not None
                    ):
                        self.tracks.save(
                            replace(
                                track, duration_ms=local_file.duration_ms,
                            ),
                            connection,
                        )

                self.track_matches.upsert(
                    TrackMatch(
                        track_id=request.track_id,
                        local_file_id=local_file.id,
                        match_method="auto",
                        score=score,
                        matched_at=datetime.now(UTC).isoformat(),
                    ),
                    connection,
                )

            counts.indexed += 1
        except Exception as error:
            counts.index_failed += 1
            logger.warning(
                "Downloaded '%s' but failed to index/match it into the "
                "library: %s", request.filename, error,
            )

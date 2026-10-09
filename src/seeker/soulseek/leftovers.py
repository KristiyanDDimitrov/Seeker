"""Files slskd left behind: finished transfers Seeker never placed
(superseded, failed, cancelled), clash copies and abandoned partial
files. Listing them never deletes anything; a cleanup deletes only
files a person confirmed from a listing, and only while they are
still unchanged and unclaimed."""

import logging
import os
import re
import stat
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

import httpx

from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.errors import SeekerError
from seeker.models.download_request import UNRESOLVED
from seeker.models.leftover_result import (
    LeftoverCleanup,
    LeftoverFailure,
    LeftoverFile,
    LeftoverFolder,
    LeftoverListing,
)
from seeker.soulseek.client import SlskdUnreachableError

logger = logging.getLogger(__name__)

# A file written this recently may belong to a transfer whose name
# matched nothing below; it is held back rather than listed.
RECENTLY_WRITTEN_SECONDS = 10 * 60

# slskd's own config file, which marks a folder as its app directory.
_SLSKD_CONFIG_NAME = "slskd.yml"

# slskd's clash copy, `<stem>_<UtcNow.Ticks><suffix>` (HISTORY §138).
_CLASH_TICKS = re.compile(r"_\d+$")

_NOT_A_NAME_CHARACTER = re.compile(r"[\W_]+")


class LeftoverFolderUnknownError(SeekerError):
    pass


class _TransferLister(Protocol):
    base_url: str

    def get_downloads(self) -> Any: ...


def _name_key(stem: str, suffix: str) -> str:
    # slskd sanitizes a remote name before writing it, so names compare
    # by their letters and digits alone. A looser match only protects
    # more files; it never exposes one.
    return _NOT_A_NAME_CHARACTER.sub("", f"{stem}{suffix}".casefold())


def _remote_name_key(remote_filename: str) -> str | None:
    name = PurePosixPath(remote_filename.replace("\\", "/")).name
    if name in ("", ".", ".."):
        return None
    path = PurePosixPath(name)
    return _name_key(path.stem, path.suffix)


def _local_name_keys(name: str) -> set[str]:
    path = PurePosixPath(name)
    return {
        _name_key(path.stem, path.suffix),
        _name_key(_CLASH_TICKS.sub("", path.stem), path.suffix),
    }


def _live_transfer_filenames(data: Any) -> Iterable[str]:
    """The remote filenames of slskd's unfinished downloads. slskd
    0.26.0 groups them by user, then directory (`TransfersController.
    GetDownloadsAsync`, read in its source); a finished one's state
    starts with "Completed". Read defensively: an entry of any other
    shape is skipped."""
    if not isinstance(data, list):
        return
    for user in data:
        if not isinstance(user, dict):
            continue
        for directory in user.get("directories") or []:
            if not isinstance(directory, dict):
                continue
            for transfer in directory.get("files") or []:
                if not isinstance(transfer, dict):
                    continue
                filename = transfer.get("filename")
                state = transfer.get("state")
                if not isinstance(filename, str):
                    continue
                if isinstance(state, str) and state.startswith("Completed"):
                    continue
                yield filename


class LeftoverService:
    def __init__(
            self,
            database: Database,
            download_requests: DownloadRequestRepository,
            soulseek: Callable[[], _TransferLister],
            download_dir: Callable[[], str | None],
            clock: Callable[[], float] = time.time,
    ):
        self.database = database
        self.download_requests = download_requests
        self._soulseek = soulseek
        self._download_dir = download_dir
        self._clock = clock

    def _folders(self) -> dict[LeftoverFolder, Path]:
        """slskd's download and incomplete folders. Seeker's container
        leaves both at slskd's defaults, `downloads/` and `incomplete/`
        beside `slskd.yml` in its app directory; any other download
        folder is refused rather than guessed at, since a cleanup of
        the wrong folder deletes someone's files."""
        configured = self._download_dir()
        if not configured:
            raise LeftoverFolderUnknownError(
                "slskd's download folder isn't set, so there is nothing "
                "to clean up."
            )

        downloads = Path(configured).expanduser().resolve()
        app_dir = downloads.parent
        if (
                downloads.name != LeftoverFolder.DOWNLOADS
                or not (app_dir / _SLSKD_CONFIG_NAME).is_file()
        ):
            raise LeftoverFolderUnknownError(
                f"{downloads} isn't the download folder of an slskd that "
                f"Seeker set up, so Seeker won't clean it up."
            )

        return {
            LeftoverFolder.DOWNLOADS: downloads,
            LeftoverFolder.INCOMPLETE: app_dir / LeftoverFolder.INCOMPLETE,
        }

    def _claimed_name_keys(self) -> set[str]:
        """Every name an unresolved request or a live slskd transfer
        may have written. Asks slskd first: without its transfer list
        nothing can be called a leftover."""
        soulseek = self._soulseek()
        try:
            transfers = soulseek.get_downloads()
        except httpx.TransportError as error:
            raise SlskdUnreachableError(soulseek.base_url) from error

        with self.database.transaction() as connection:
            requests = self.download_requests.get_all(connection)

        filenames = [
            request.filename for request in requests
            if request.status in UNRESOLVED
        ]
        filenames.extend(_live_transfer_filenames(transfers))

        return {
            key for key in map(_remote_name_key, filenames) if key is not None
        }

    def list_leftover_files(self) -> LeftoverListing:
        folders = self._folders()
        claimed = self._claimed_name_keys()
        cutoff = self._clock() - RECENTLY_WRITTEN_SECONDS
        listing = LeftoverListing()

        for folder, root in folders.items():
            for path, status in _regular_files(root):
                if _local_name_keys(path.name) & claimed:
                    continue
                if status.st_mtime > cutoff:
                    listing.held_back += 1
                    continue
                listing.files.append(
                    LeftoverFile(
                        str(path), folder, status.st_size, status.st_mtime,
                    ),
                )

        listing.files.sort(key=lambda file: (-file.size, file.path))
        logger.info(
            "%d leftover file(s) in slskd's folders, %d bytes; %d held "
            "back as recently written",
            len(listing.files), listing.total_bytes, listing.held_back,
        )
        return listing

    def delete_leftover_files(
            self,
            files: Sequence[LeftoverFile],
    ) -> LeftoverCleanup:
        """Deletes the confirmed `files` that a fresh listing still
        shows unchanged; the rest are kept. Empty folders the deletes
        leave behind go too, never slskd's two folders themselves."""
        folders = self._folders()
        current = {file.path: file for file in self.list_leftover_files().files}
        cleanup = LeftoverCleanup()

        for file in files:
            if current.get(file.path) != file:
                cleanup.kept.append(file)
                continue
            try:
                Path(file.path).unlink()
            except OSError as error:
                logger.warning("Could not delete %s: %s", file.path, error)
                cleanup.failures.append(LeftoverFailure(file, str(error)))
                continue
            logger.info("Deleted leftover %s (%d bytes)", file.path, file.size)
            cleanup.deleted.append(file)
            _remove_empty_parents(
                Path(file.path).parent, folders[file.folder],
            )

        return cleanup


def _regular_files(root: Path) -> Iterable[tuple[Path, os.stat_result]]:
    """Every regular file under `root`, with its stat. Symlinks are
    neither followed nor listed: one could point anywhere."""
    if not root.is_dir():
        return
    for directory, _subdirectories, names in os.walk(root):
        for name in names:
            path = Path(directory) / name
            status = path.lstat()
            if stat.S_ISREG(status.st_mode):
                yield path, status


def _remove_empty_parents(directory: Path, root: Path) -> None:
    while directory != root and directory.is_relative_to(root):
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent

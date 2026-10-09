import os
from pathlib import Path

import httpx
import pytest

from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.download_request import (
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.leftover_result import LeftoverFile, LeftoverFolder
from seeker.models.track import Track
from seeker.soulseek.client import SlskdUnreachableError
from seeker.soulseek.leftovers import (
    LeftoverFolderUnknownError,
    LeftoverService,
)

NOW = 1_800_000_000.0
AN_HOUR_AGO = NOW - 3600


class FakeSlskd:
    base_url = "http://slskd.test"

    def __init__(self, downloads=None, error: Exception | None = None):
        self.downloads = downloads if downloads is not None else []
        self.error = error

    def get_downloads(self):
        if self.error is not None:
            raise self.error
        return self.downloads


def _transfer(username: str, filename: str, state: str) -> dict:
    return {
        "username": username,
        "directories": [
            {
                "directory": filename.rsplit("\\", 1)[0],
                "fileCount": 1,
                "files": [
                    {"username": username, "filename": filename,
                     "state": state, "size": 10},
                ],
            },
        ],
    }


@pytest.fixture
def app_dir(tmp_path) -> Path:
    app = tmp_path / "slskd-data"
    (app / "downloads").mkdir(parents=True)
    (app / "incomplete").mkdir()
    (app / "slskd.yml").write_text("")
    return app


@pytest.fixture
def database(tmp_path) -> Database:
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    return database


def _write(path: Path, size: int, mtime: float = AN_HOUR_AGO) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def _add_request(
        database: Database,
        filename: str,
        status: DownloadStatus,
        username: str = "peer",
) -> None:
    with database.transaction() as connection:
        TrackRepository().save(
            Track("t1", "Song", "Artist", "Album", 200_000), connection,
        )
        DownloadRequestRepository().add(
            DownloadRequest(
                track_id="t1", username=username, filename=filename,
                format="mp3", requested_at="2026-10-09T10:00:00+00:00",
                role=DownloadRole.SETTLED, status=status, size=10,
            ),
            connection,
        )


def _service(
        database: Database,
        app_dir: Path,
        slskd: FakeSlskd | None = None,
        download_dir: str | None = None,
) -> LeftoverService:
    fake = slskd or FakeSlskd()
    return LeftoverService(
        database,
        DownloadRequestRepository(),
        soulseek=lambda: fake,
        download_dir=lambda: (
            download_dir if download_dir is not None
            else str(app_dir / "downloads")
        ),
        clock=lambda: NOW,
    )


def _listed_names(service: LeftoverService) -> set[str]:
    return {Path(file.path).name for file in service.list_leftover_files().files}


def test_lists_unreferenced_files_in_both_folders_largest_first(
        database, app_dir,
):
    _write(app_dir / "downloads" / "Album" / "Old - Song.mp3", 30)
    _write(app_dir / "incomplete" / "peer" / "Music" / "Partial.flac", 50)

    listing = _service(database, app_dir).list_leftover_files()

    assert [(Path(f.path).name, f.folder, f.size) for f in listing.files] == [
        ("Partial.flac", LeftoverFolder.INCOMPLETE, 50),
        ("Old - Song.mp3", LeftoverFolder.DOWNLOADS, 30),
    ]
    assert listing.total_bytes == 80
    assert listing.held_back == 0


@pytest.mark.parametrize(
    "status",
    [
        DownloadStatus.QUEUED,
        DownloadStatus.DOWNLOADING,
        DownloadStatus.LOCKED,
        DownloadStatus.SHORTLISTED,
        DownloadStatus.READY_FOR_REVIEW,
    ],
)
def test_a_file_an_unresolved_request_names_is_never_listed(
        database, app_dir, status,
):
    _add_request(database, "@@peer\\Music\\Album\\Artist - Song.mp3", status)
    _write(app_dir / "downloads" / "Album" / "Artist - Song.mp3", 10)
    _write(app_dir / "downloads" / "Album" / "Artist - Song_63898.mp3", 10)
    _write(
        app_dir / "incomplete" / "peer" / "Music" / "Album"
        / "Artist - Song.mp3",
        4,
    )
    _write(app_dir / "downloads" / "Other.mp3", 10)

    assert _listed_names(_service(database, app_dir)) == {"Other.mp3"}


@pytest.mark.parametrize(
    "status",
    [
        DownloadStatus.COMPLETED,
        DownloadStatus.FAILED,
        DownloadStatus.SUPERSEDED,
        DownloadStatus.UNAVAILABLE,
    ],
)
def test_a_finished_requests_file_is_a_leftover(database, app_dir, status):
    _add_request(database, "@@peer\\Music\\Artist - Song.mp3", status)
    _write(app_dir / "downloads" / "Music" / "Artist - Song.mp3", 10)

    assert _listed_names(_service(database, app_dir)) == {"Artist - Song.mp3"}


def test_a_name_slskd_sanitized_still_matches_its_request(database, app_dir):
    # slskd sanitizes a remote name for the local filesystem; the
    # comparison ignores punctuation, so a changed character never
    # exposes an in-use file.
    _add_request(
        database, "@@peer\\Music\\Artist: Song?.mp3", DownloadStatus.QUEUED,
    )
    _write(app_dir / "incomplete" / "peer" / "Music" / "Artist_ Song_.mp3", 4)

    assert _listed_names(_service(database, app_dir)) == set()


def test_a_file_a_live_slskd_transfer_names_is_never_listed(
        database, app_dir,
):
    # A superseded row's transfer keeps running in slskd; no request
    # row protects its file, slskd's own transfer list does.
    slskd = FakeSlskd([
        _transfer("peer", "@@peer\\Music\\Running.mp3", "InProgress"),
        _transfer("peer", "@@peer\\Music\\Queued.mp3", "Queued, Remotely"),
        _transfer("peer", "@@peer\\Music\\Done.mp3", "Completed, Succeeded"),
    ])
    for name in ("Running.mp3", "Queued.mp3", "Done.mp3"):
        _write(app_dir / "incomplete" / "peer" / "Music" / name, 4)

    assert _listed_names(_service(database, app_dir, slskd)) == {"Done.mp3"}


def test_a_recently_written_file_is_held_back(database, app_dir):
    _write(app_dir / "incomplete" / "peer" / "Fresh.mp3", 4, mtime=NOW - 60)
    _write(app_dir / "downloads" / "Stale.mp3", 4)

    listing = _service(database, app_dir).list_leftover_files()

    assert [Path(file.path).name for file in listing.files] == ["Stale.mp3"]
    assert listing.held_back == 1


def test_a_symlink_is_neither_listed_nor_followed(database, app_dir, tmp_path):
    outside = tmp_path / "outside"
    _write(outside / "Precious.flac", 10)
    (app_dir / "downloads" / "link").symlink_to(outside)
    (app_dir / "downloads" / "file-link.flac").symlink_to(
        outside / "Precious.flac",
    )

    assert _listed_names(_service(database, app_dir)) == set()


def test_slskd_unreachable_refuses_to_list(database, app_dir):
    _write(app_dir / "downloads" / "Old.mp3", 4)
    slskd = FakeSlskd(error=httpx.ConnectError("refused"))

    with pytest.raises(SlskdUnreachableError):
        _service(database, app_dir, slskd).list_leftover_files()


@pytest.mark.parametrize("case", ["unset", "not-downloads", "no-slskd-yml"])
def test_a_folder_that_is_not_slskds_own_is_refused(
        database, app_dir, tmp_path, case,
):
    music = tmp_path / "Music"
    _write(music / "Keep.flac", 10)
    download_dir = {
        "unset": "",
        "not-downloads": str(music),
        "no-slskd-yml": str(app_dir / "downloads"),
    }[case]
    if case == "no-slskd-yml":
        (app_dir / "slskd.yml").unlink()

    service = _service(database, app_dir, download_dir=download_dir)

    with pytest.raises(LeftoverFolderUnknownError):
        service.list_leftover_files()


def test_cleanup_deletes_the_confirmed_files_and_their_empty_folders(
        database, app_dir,
):
    old = _write(app_dir / "downloads" / "Album" / "Old.mp3", 30)
    partial = _write(app_dir / "incomplete" / "peer" / "Music" / "P.mp3", 5)
    unconfirmed = _write(app_dir / "downloads" / "Unconfirmed.mp3", 7)
    service = _service(database, app_dir)
    listing = service.list_leftover_files()
    confirmed = [f for f in listing.files if f.path != str(unconfirmed)]

    cleanup = service.delete_leftover_files(confirmed)

    assert {Path(file.path).name for file in cleanup.deleted} == {
        "Old.mp3", "P.mp3",
    }
    assert cleanup.freed_bytes == 35
    assert cleanup.kept == []
    assert cleanup.failures == []
    assert not old.exists()
    assert not partial.exists()
    assert unconfirmed.exists()
    assert not (app_dir / "downloads" / "Album").exists()
    assert not (app_dir / "incomplete" / "peer").exists()
    assert (app_dir / "downloads").is_dir()
    assert (app_dir / "incomplete").is_dir()


def test_cleanup_keeps_a_file_that_changed_or_came_into_use(
        database, app_dir,
):
    grown = _write(app_dir / "incomplete" / "peer" / "Grown.mp3", 5)
    claimed = _write(app_dir / "downloads" / "Music" / "Claimed.mp3", 5)
    service = _service(database, app_dir)
    listing = service.list_leftover_files()

    _write(grown, 9)
    _add_request(
        database, "@@peer\\Music\\Claimed.mp3", DownloadStatus.DOWNLOADING,
    )
    cleanup = service.delete_leftover_files(listing.files)

    assert cleanup.deleted == []
    assert {Path(file.path).name for file in cleanup.kept} == {
        "Grown.mp3", "Claimed.mp3",
    }
    assert grown.exists()
    assert claimed.exists()


def test_cleanup_never_deletes_a_file_it_did_not_list(
        database, app_dir, tmp_path,
):
    precious = _write(tmp_path / "Music" / "Precious.flac", 10)
    service = _service(database, app_dir)
    forged = [
        LeftoverFile(
            str(precious), LeftoverFolder.DOWNLOADS, 10,
            precious.stat().st_mtime,
        ),
    ]

    cleanup = service.delete_leftover_files(forged)

    assert cleanup.deleted == []
    assert [file.path for file in cleanup.kept] == [str(precious)]
    assert precious.exists()


def test_cleanup_reports_a_file_it_could_not_delete(
        database, app_dir, monkeypatch,
):
    _write(app_dir / "downloads" / "Stuck.mp3", 4)
    service = _service(database, app_dir)
    listing = service.list_leftover_files()

    def refuse(path, missing_ok=False):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(Path, "unlink", refuse)
    cleanup = service.delete_leftover_files(listing.files)

    assert cleanup.deleted == []
    [failure] = cleanup.failures
    assert Path(failure.file.path).name == "Stuck.mp3"
    assert "Permission denied" in failure.message

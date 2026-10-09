"""A settled download that fails falls back to the next-best file.

`select_downloads` ranks backups behind the settled file;
`search_and_request` records them as shortlisted settled rows; the
poll requests the next one, in turn, when a settled row fails or
locks, and places a backup like any settled download (HISTORY §206).
"""
import httpx
import pytest

from db_seed import add_playlist_track
from seeker.config_store import SeekerConfig
from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.playlist_repository import (
    PlaylistRepository,
)
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.download_request import DownloadRequest
from seeker.models.library_location import LibraryLocation
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track
from seeker.soulseek.client import SoulseekDownloadError
from seeker.soulseek.download_service import (
    DownloadService,
    TrackSearchOutcome,
)
from test_download_service import (
    FakeSoulseekClient,
    get_status,
    make_service,
    seed_pending_request,
)

QUERY = "Dom Dolla Rhyme Dust"
TRACK = Track(
    id="track1",
    title="Rhyme Dust",
    artist="Dom Dolla",
    album="Rhyme Dust",
    duration_ms=215_000,
)
THRESHOLDS = (90.0, 70.0)
NOT_SHARED = "Transfer rejected: File not shared."


def _flac(peer: int, queue_length: int, **overrides) -> SoulseekFile:
    defaults = {
        "username": f"peer{peer}",
        "filename": f"@@peer{peer}\\Dom Dolla - Rhyme Dust.flac",
        "extension": "flac",
        "size": 30_000_000 + peer,
        "queue_length": queue_length,
        "upload_speed": 1_048_576,
        "has_free_upload_slot": True,
        "length": 215,
        "bit_rate": None,
        "bit_depth": 16,
        "sample_rate": 44_100,
        "is_variable_bitrate": None,
    }
    defaults.update(overrides)
    return SoulseekFile(**defaults)


def _save_track(service: DownloadService) -> None:
    with service.database.transaction() as connection:
        service.tracks.save(TRACK, connection)


def _rows(service: DownloadService) -> list[DownloadRequest]:
    with service.database.transaction() as connection:
        return sorted(
            service.download_requests.get_all(connection),
            key=lambda row: (row.role, row.rank or 0),
        )


def _seed_settled_with_backups(service: DownloadService) -> None:
    """A settled row on transfer t1 from peer1, backups peer2 (rank 2)
    and peer3 (rank 3), and an upgrade shortlisted from peer9."""
    seed_pending_request(
        service, "t1", role="settled", filename="settled.flac",
        username="peer1",
    )

    for rank, peer in ((2, 2), (3, 3)):
        seed_pending_request(
            service, None, role="settled", status="shortlisted",
            rank=rank, filename=f"backup{peer}.flac",
            username=f"peer{peer}",
        )

    seed_pending_request(
        service, None, role="upgrade", status="shortlisted", rank=2,
        filename="upgrade.flac", username="peer9",
    )


def _status_by_filename(service: DownloadService) -> dict[str, str]:
    return {row.filename: row.status for row in _rows(service)}


def test_search_records_backups_as_shortlisted_settled_rows(tmp_path):
    files = [_flac(peer, queue_length=peer) for peer in range(1, 6)]
    service = make_service(
        tmp_path, states={}, search_results={QUERY: files},
    )
    _save_track(service)

    outcome = service.search_and_request(TRACK, THRESHOLDS)

    assert outcome == TrackSearchOutcome.REQUESTED
    # Only the settled file goes to slskd; backups wait for the poll.
    assert [call[0] for call in service.soulseek.request_download_calls] == [
        "peer1",
    ]
    assert [
        (row.username, row.role, row.status, row.rank)
        for row in _rows(service)
    ] == [
        ("peer1", "settled", "queued", None),
        ("peer2", "settled", "shortlisted", 2),
        ("peer3", "settled", "shortlisted", 3),
        ("peer4", "settled", "shortlisted", 4),
    ]


def test_a_failed_settled_row_requests_its_next_backup_in_the_same_poll(
        tmp_path,
):
    service = make_service(
        tmp_path,
        states={"t1": "Completed, Errored", "b2": "Requested"},
        retry_results={"backup2.flac": "b2"},
    )
    _seed_settled_with_backups(service)

    service.poll_downloads()

    assert _status_by_filename(service) == {
        "settled.flac": "failed",
        "backup2.flac": "queued",
        "backup3.flac": "shortlisted",
        "upgrade.flac": "shortlisted",
    }


def test_a_locked_settled_row_falls_back_at_once_and_keeps_its_retry_loop(
        tmp_path,
):
    service = make_service(
        tmp_path,
        states={"t1": "Completed, Rejected", "b2": "Requested"},
        exceptions={"t1": NOT_SHARED},
        retry_results={"backup2.flac": "b2"},
    )
    _seed_settled_with_backups(service)

    service.poll_downloads()

    statuses = _status_by_filename(service)
    assert statuses["settled.flac"] == "locked"
    assert statuses["backup2.flac"] == "queued"
    assert statuses["upgrade.flac"] == "shortlisted"


def test_the_fallback_cascades_past_a_backup_rejected_at_once(tmp_path):
    service = make_service(
        tmp_path,
        states={
            "t1": "Completed, Errored",
            "b2": "Completed, Errored",
            "b3": "InProgress",
        },
        retry_results={"backup2.flac": "b2", "backup3.flac": "b3"},
    )
    _seed_settled_with_backups(service)

    service.poll_downloads()

    statuses = _status_by_filename(service)
    assert statuses["backup2.flac"] == "failed"
    assert statuses["backup3.flac"] == "downloading"
    assert statuses["upgrade.flac"] == "shortlisted"


def test_a_backup_finished_at_once_stays_in_flight_for_placement(tmp_path):
    # An upgrade finished at once goes to Review; a settled backup must
    # not, or the track waits on a person for a file it simply needs.
    service = make_service(
        tmp_path,
        states={"t1": "Completed, Errored", "b2": "Completed, Succeeded"},
        retry_results={"backup2.flac": "b2"},
    )
    _seed_settled_with_backups(service)

    service.poll_downloads()

    assert get_status(service, "b2") == "downloading"


def _placing_service(tmp_path, client: FakeSoulseekClient):
    """A service whose finished settled downloads really move: a
    default destination, the track in a playlist, a scratch slskd
    download folder. Returns it with the destination's root."""
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    music = tmp_path / "music"
    music.mkdir()
    slskd_dir = tmp_path / "slskd"
    slskd_dir.mkdir()
    locations = LibraryLocationRepository()
    playlists = PlaylistRepository()

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(name="Main", path=str(music), added_at="2026-01-01"),
            connection,
        )
        location = locations.get_by_name("Main", connection)
        playlists.save(
            Playlist(id="p1", name="Test", track_count=1), connection,
        )
        TrackRepository().save(TRACK, connection)
        add_playlist_track("p1", TRACK.id, connection)

    config = SeekerConfig(
        default_download_location_id=location.id,
        default_download_subfolder_per_playlist=False,
    )
    service = DownloadService(
        database, client, playlists, TrackRepository(), locations,
        DownloadRequestRepository(), TrackMatchRepository(),
        LocalFileRepository(), SoulseekReviewCandidateRepository(),
        str(slskd_dir),
        get_config=lambda: config,
    )
    return service, music, slskd_dir


def test_a_backup_finished_at_once_is_placed_by_the_next_poll(tmp_path):
    content = b"backup audio"
    client = FakeSoulseekClient(
        states={"t1": "Completed, Errored", "b2": "Completed, Succeeded"},
        retry_results={"backup2.flac": "b2"},
    )
    service, music, slskd_dir = _placing_service(tmp_path, client)
    seed_pending_request(
        service, "t1", filename="settled.flac", username="peer1",
    )
    seed_pending_request(
        service, None, status="shortlisted", rank=2,
        filename="backup2.flac", username="peer2", size=len(content),
    )
    (slskd_dir / "backup2.flac").write_bytes(content)

    service.poll_downloads()
    counts = service.poll_downloads()

    assert counts.completed == 1
    assert get_status(service, "b2") == "completed"
    assert (music / "backup2.flac").read_bytes() == content


def _offline(file: SoulseekFile) -> SoulseekDownloadError:
    # The client's own wrapping of slskd's synchronous 404.
    message = f"User {file.username} appears to be offline"
    return SoulseekDownloadError(
        f"slskd rejected the download of '{file.filename}' from "
        f"'{file.username}': {message}",
        reason=message,
    )


def test_a_settled_peer_offline_at_enqueue_locks_and_falls_back_at_once(
        tmp_path,
):
    files = [_flac(peer, queue_length=peer) for peer in range(1, 4)]
    service = make_service(
        tmp_path,
        states={"b2": "Requested"},
        search_results={QUERY: files},
        retry_results={
            files[0].filename: _offline(files[0]),
            files[1].filename: "b2",
        },
    )
    _save_track(service)

    outcome = service.search_and_request(TRACK, THRESHOLDS)

    assert outcome == TrackSearchOutcome.REQUESTED
    assert [call[0] for call in service.soulseek.request_download_calls] == [
        "peer1", "peer2",
    ]
    assert [
        (row.username, row.status, row.rank, row.transfer_id)
        for row in _rows(service)
    ] == [
        ("peer1", "locked", None, None),
        ("peer2", "queued", 2, "b2"),
        ("peer3", "shortlisted", 3, None),
    ]


def test_a_settled_offline_peer_with_no_backup_still_counts_requested(
        tmp_path,
):
    # The locked row's own retry loop is the request: the peer may come
    # back within its budget.
    only = _flac(1, queue_length=0)
    service = make_service(
        tmp_path,
        states={},
        search_results={QUERY: [only]},
        retry_results={only.filename: _offline(only)},
    )
    _save_track(service)

    outcome = service.search_and_request(TRACK, THRESHOLDS)

    assert outcome == TrackSearchOutcome.REQUESTED
    assert [(row.username, row.status) for row in _rows(service)] == [
        ("peer1", "locked"),
    ]


def test_an_unrecognized_settled_enqueue_error_stays_loud(tmp_path):
    first, second = _flac(1, queue_length=0), _flac(2, queue_length=1)
    error = httpx.HTTPStatusError(
        "500", request=httpx.Request("POST", "http://slskd"),
        response=httpx.Response(500),
    )
    service = make_service(
        tmp_path,
        states={},
        search_results={QUERY: [first, second]},
        retry_results={first.filename: error},
    )
    _save_track(service)

    with pytest.raises(httpx.HTTPStatusError):
        service.search_and_request(TRACK, THRESHOLDS)

    assert _rows(service) == []


def test_a_placed_backup_supersedes_the_other_settled_rows_only(tmp_path):
    # The settled row is still in its locked retry loop; once a backup
    # is in the library, asking that peer again would fetch a second
    # copy. The upgrade is a different question and stays.
    content = b"backup audio"
    client = FakeSoulseekClient(states={"b2": "Completed, Succeeded"})
    service, _music, slskd_dir = _placing_service(tmp_path, client)
    seed_pending_request(
        service, None, status="locked", filename="settled.flac",
        username="peer1",
    )
    seed_pending_request(
        service, "b2", filename="backup2.flac", username="peer2", rank=2,
        size=len(content),
    )
    seed_pending_request(
        service, None, status="shortlisted", rank=3,
        filename="backup3.flac", username="peer3",
    )
    seed_pending_request(
        service, None, role="upgrade", status="shortlisted", rank=2,
        filename="upgrade.flac", username="peer9",
    )
    (slskd_dir / "backup2.flac").write_bytes(content)

    service.poll_downloads()

    assert _status_by_filename(service) == {
        "settled.flac": "superseded",
        "backup2.flac": "completed",
        "backup3.flac": "superseded",
        "upgrade.flac": "shortlisted",
    }
    # Superseded, so its retry loop never asked the peer again.
    assert client.request_download_calls == []


def test_a_locked_settled_row_placed_on_retry_supersedes_its_backup(
        tmp_path,
):
    content = b"settled audio"
    client = FakeSoulseekClient(
        states={"t9": "Completed, Succeeded", "b2": "InProgress"},
        retry_results={"settled.flac": "t9"},
    )
    service, _music, slskd_dir = _placing_service(tmp_path, client)
    seed_pending_request(
        service, None, status="locked", filename="settled.flac",
        username="peer1", size=len(content),
    )
    seed_pending_request(
        service, "b2", status="downloading", filename="backup2.flac",
        username="peer2", rank=2,
    )
    (slskd_dir / "settled.flac").write_bytes(content)

    service.poll_downloads()

    assert _status_by_filename(service) == {
        "settled.flac": "completed",
        "backup2.flac": "superseded",
    }


def test_cancelling_a_settled_row_supersedes_its_backups_only(tmp_path):
    service = make_service(tmp_path, states={"t1": "InProgress"})
    _seed_settled_with_backups(service)
    settled_id = next(
        row.id for row in _rows(service) if row.filename == "settled.flac"
    )

    service.cancel_download(settled_id)

    assert _status_by_filename(service) == {
        "settled.flac": "failed",
        "backup2.flac": "superseded",
        "backup3.flac": "superseded",
        "upgrade.flac": "shortlisted",
    }

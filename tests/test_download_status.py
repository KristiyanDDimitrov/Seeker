from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.database.schema import SCHEMA
from seeker.models.download_request import (
    AWAITING_A_HUMAN,
    BLOCKS_REDOWNLOAD,
    FAILED_OUTCOMES,
    IN_FLIGHT,
    RETRYING_IN_BACKGROUND,
    SHOWS_NO_FURTHER_PROGRESS,
    STAMPS_COMPLETED_AT,
    UNRESOLVED,
    DownloadRequest,
    DownloadRole,
    DownloadStatus,
)
from seeker.models.track import Track

# Each named set against the literal set it replaced, so the move to
# DownloadStatus is provably behaviour-neutral.


def test_stamps_completed_at_is_the_old_terminal_set():
    assert {"completed", "failed", "unavailable"} == STAMPS_COMPLETED_AT


def test_in_flight_awaiting_and_retrying():
    assert {"queued", "downloading"} == IN_FLIGHT
    assert {"ready_for_review"} == AWAITING_A_HUMAN
    assert {"locked", "shortlisted"} == RETRYING_IN_BACKGROUND
    assert {"failed", "unavailable"} == FAILED_OUTCOMES


def test_unresolved_is_the_dashboards_old_active_set():
    assert {
        "queued", "downloading", "locked", "shortlisted", "ready_for_review",
    } == UNRESOLVED


def test_blocks_redownload_is_everything_but_the_three_dead_ends():
    assert (
        set(DownloadStatus) - {"failed", "superseded", "unavailable"}
    ) == BLOCKS_REDOWNLOAD


def test_shows_no_further_progress_is_the_old_downloads_page_set():
    assert {
        "completed", "failed", "ready_for_review", "unavailable",
    } == SHOWS_NO_FURTHER_PROGRESS


def test_the_schema_comment_describes_every_status():
    for status in DownloadStatus:
        assert f"--   {status.value} " in SCHEMA


def test_a_row_reads_back_as_enums(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    requests = DownloadRequestRepository(database)

    with database.transaction() as connection:
        TrackRepository(database).save(
            Track(
                id="track-1", title="Rhyme Dust", artist="Dom Dolla",
                album="Rhyme Dust", duration_ms=1,
            ),
            connection,
        )
        requests.add(
            DownloadRequest(
                track_id="track-1",
                username="peer",
                filename="a.flac",
                format="flac",
                requested_at="2026-01-01T00:00:00+00:00",
                role=DownloadRole.UPGRADE,
                status=DownloadStatus.LOCKED,
            ),
            connection,
        )
        [request] = requests.get_all(connection)

    assert type(request.status) is DownloadStatus
    assert type(request.role) is DownloadRole
    assert request.status == "locked"
    assert request.role == "upgrade"

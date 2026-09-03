from seeker.database.connection import Database
from seeker.database.repositories.download_request_repository import (
    DownloadRequestRepository,
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
from seeker.history_service import HistoryService
from seeker.models.download_request import DownloadRequest
from seeker.models.history_event import DOWNLOADED, TAGGED
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch


def make_service(tmp_path) -> HistoryService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return HistoryService(
        database,
        DownloadRequestRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
        TrackRepository(database),
        PlaylistRepository(database),
    )


def seed_playlist(
        service: HistoryService, playlist_id: str, name: str = "Playlist",
) -> None:
    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id=playlist_id, name=name, track_count=0), connection,
        )


def seed_track(
        service: HistoryService,
        track_id: str,
        playlist_id: str | None = None,
        artist: str = "Artist",
        title: str = "Title",
) -> None:
    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id=track_id, title=title, artist=artist, album="Album",
                duration_ms=200_000,
            ),
            connection,
        )
        if playlist_id is not None:
            service.tracks.save_playlist_track(
                playlist_id, track_id, connection,
            )


def seed_download_request(
        service: HistoryService,
        track_id: str,
        status: str = "completed",
        completed_at: str | None = "2026-01-02T00:00:00+00:00",
        requested_at: str = "2026-01-01T00:00:00+00:00",
        username: str = "peer1",
        filename: str = "file.flac",
        format_: str = "flac",
) -> None:
    with service.database.transaction() as connection:
        service.download_requests.add(
            DownloadRequest(
                track_id=track_id, username=username, filename=filename,
                format=format_, role="settled", status=status,
                requested_at=requested_at, completed_at=completed_at,
            ),
            connection,
        )


def seed_local_file(
        service: HistoryService,
        filename: str = "song.mp3",
        tagged_at: str | None = None,
) -> int:
    with service.database.transaction() as connection:
        connection.execute(
            "INSERT INTO library_locations (name, path, added_at) "
            "VALUES (?, ?, ?)",
            (filename, "/music", "2026-01-01T00:00:00+00:00"),
        )
        location_id = connection.execute(
            "SELECT id FROM library_locations WHERE name = ?", (filename,),
        ).fetchone()[0]

        service.local_files.upsert(
            LocalFile(
                location_id=location_id, relative_path=filename,
                filename=filename, format="mp3", size_bytes=1_000,
                mtime=1.0, scanned_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )
        local_file = service.local_files.get_by_location_and_relative_path(
            location_id, filename, connection,
        )
        assert local_file is not None
        assert local_file.id is not None

        if tagged_at is not None:
            service.local_files.mark_tagged(
                local_file.id, tagged_at, connection,
            )

    return local_file.id


def seed_match(
        service: HistoryService,
        track_id: str,
        local_file_id: int | None,
) -> None:
    with service.database.transaction() as connection:
        service.track_matches.upsert(
            TrackMatch(
                track_id=track_id, local_file_id=local_file_id,
                match_method="auto", score=100.0,
                matched_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )


def test_no_events_on_an_empty_database(tmp_path):
    service = make_service(tmp_path)

    assert service.get_recent_events() == []


def test_completed_download_produces_a_downloaded_event(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1", name="240KM/H")
    seed_track(service, "t1", playlist_id="p1", artist="ZENEA", title="INFINITE")
    seed_download_request(
        service, "t1", status="completed",
        completed_at="2026-01-02T00:00:00+00:00",
        username="peer1", format_="flac",
    )

    events = service.get_recent_events()

    assert len(events) == 1
    event = events[0]
    assert event.event_type == DOWNLOADED
    assert event.occurred_at == "2026-01-02T00:00:00+00:00"
    assert event.track_artist == "ZENEA"
    assert event.track_title == "INFINITE"
    assert event.playlist_name == "240KM/H"
    assert event.detail == "FLAC from peer1"


def test_failed_download_produces_no_event(tmp_path):
    # Deliberate scope decision: download_requests has no persisted
    # failure-reason column, so a "failed" event could never show an
    # honest detail — left entirely to the Downloads page instead.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "t1", playlist_id="p1")
    seed_download_request(
        service, "t1", status="failed",
        completed_at="2026-01-02T00:00:00+00:00",
    )

    assert service.get_recent_events() == []


def test_pending_download_produces_no_event(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "t1", playlist_id="p1")
    seed_download_request(
        service, "t1", status="downloading", completed_at=None,
    )

    assert service.get_recent_events() == []


def test_tagged_local_file_produces_a_tagged_event(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1", name="Test")
    seed_track(service, "t1", playlist_id="p1", artist="Kamäleon", title="Quadrat")
    local_file_id = seed_local_file(
        service, filename="quadrat.mp3",
        tagged_at="2026-01-03T00:00:00+00:00",
    )
    seed_match(service, "t1", local_file_id)

    events = service.get_recent_events()

    assert len(events) == 1
    event = events[0]
    assert event.event_type == TAGGED
    assert event.occurred_at == "2026-01-03T00:00:00+00:00"
    assert event.track_artist == "Kamäleon"
    assert event.track_title == "Quadrat"
    assert event.playlist_name == "Test"
    assert event.detail == "Tagged with Spotify metadata"


def test_untagged_local_file_produces_no_tagged_event(tmp_path):
    service = make_service(tmp_path)
    local_file_id = seed_local_file(service, tagged_at=None)
    seed_track(service, "t1")
    seed_match(service, "t1", local_file_id)

    assert service.get_recent_events() == []


def test_tagged_local_file_with_no_track_match_produces_no_event(tmp_path):
    # E.g. a duplicate-delete cascade removed the track_matches row
    # without repointing it (or it was never matched at all) — the
    # event can't identify a track, so it's skipped rather than shown
    # with blank/misleading data.
    service = make_service(tmp_path)
    seed_local_file(service, tagged_at="2026-01-03T00:00:00+00:00")

    assert service.get_recent_events() == []


def test_events_sorted_most_recent_first(tmp_path):
    service = make_service(tmp_path)
    seed_track(service, "t1", artist="Old", title="Old Track")
    seed_track(service, "t2", artist="New", title="New Track")
    seed_download_request(
        service, "t1", completed_at="2026-01-01T00:00:00+00:00",
        requested_at="2025-12-31T00:00:00+00:00",
    )
    seed_download_request(
        service, "t2", completed_at="2026-01-05T00:00:00+00:00",
        requested_at="2026-01-04T00:00:00+00:00", filename="other.flac",
    )

    events = service.get_recent_events()

    assert [event.track_artist for event in events] == ["New", "Old"]


def test_limit_caps_the_number_of_returned_events(tmp_path):
    service = make_service(tmp_path)
    for i in range(5):
        seed_track(service, f"t{i}")
        seed_download_request(
            service, f"t{i}",
            completed_at=f"2026-01-0{i + 1}T00:00:00+00:00",
            requested_at=f"2026-01-0{i + 1}T00:00:00+00:00",
            filename=f"file{i}.flac",
        )

    events = service.get_recent_events(limit=2)

    assert len(events) == 2
    # Still the two most recent (0-indexed loop above -> "05"/"04" are
    # the last two seeded), not an arbitrary truncation.
    assert [event.occurred_at for event in events] == [
        "2026-01-05T00:00:00+00:00", "2026-01-04T00:00:00+00:00",
    ]


def test_stale_duplicate_download_rows_collapse_to_the_most_recent(tmp_path):
    # Same real candidate (track/role/username/filename) requested twice
    # — the exact pre-item-16 dedup-gap shape items 24/25 already fixed
    # on the read/write sides; History must not show it as two events.
    service = make_service(tmp_path)
    seed_track(service, "t1")
    seed_download_request(
        service, "t1", status="completed",
        completed_at="2026-01-01T00:00:00+00:00",
        requested_at="2026-01-01T00:00:00+00:00",
        username="peer1", filename="same.flac",
    )
    seed_download_request(
        service, "t1", status="completed",
        completed_at="2026-01-02T00:00:00+00:00",
        requested_at="2026-01-02T00:00:00+00:00",
        username="peer1", filename="same.flac",
    )

    events = service.get_recent_events()

    assert len(events) == 1
    assert events[0].occurred_at == "2026-01-02T00:00:00+00:00"


def test_track_not_linked_to_any_playlist_shows_unknown(tmp_path):
    service = make_service(tmp_path)
    seed_track(service, "t1", playlist_id=None)
    seed_download_request(service, "t1")

    events = service.get_recent_events()

    assert len(events) == 1
    assert events[0].playlist_name == "Unknown"


def test_manual_track_shows_manual_not_unknown(tmp_path):
    # Roadmap item 82 (P13.7) — a manual (not-from-Spotify) search-and-
    # download track ALSO has no playlist, same as the "Unknown" case
    # above, but this is a real, expected state, not a data-integrity
    # concern — the label must say so honestly.
    service = make_service(tmp_path)
    seed_track(service, "manual:abc123", playlist_id=None)
    seed_download_request(service, "manual:abc123")

    events = service.get_recent_events()

    assert len(events) == 1
    assert events[0].playlist_name == "Manual"

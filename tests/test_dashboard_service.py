from datetime import datetime, timedelta, UTC

import pytest

from seeker.dashboard_service import DashboardService, PlaylistNotFoundError
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
from seeker.database.repositories.soulseek_review_candidate_repository import (
    SoulseekReviewCandidateRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.models.download_request import DownloadRequest
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.models.track_status import (
    AWAITING_REVIEW,
    DOWNLOADING,
    IN_LIBRARY,
    NEEDS_REVIEW,
    NOT_FOUND,
    RETRYING,
    REVIEW_CANDIDATE,
)


def make_service(tmp_path) -> DashboardService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return DashboardService(
        database,
        PlaylistRepository(database),
        TrackRepository(database),
        TrackMatchRepository(database),
        DownloadRequestRepository(database),
        SoulseekReviewCandidateRepository(database),
        LocalFileRepository(database),
    )


def seed_playlist(
        service: DashboardService, playlist_id: str, name: str = "Playlist",
) -> None:
    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id=playlist_id, name=name, track_count=0), connection,
        )


def seed_track(
        service: DashboardService,
        playlist_id: str,
        track_id: str,
        artist: str = "Artist",
        title: str = "Title",
) -> None:
    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id=track_id,
                title=title,
                artist=artist,
                album="Album",
                duration_ms=200_000,
            ),
            connection,
        )
        service.tracks.save_playlist_track(playlist_id, track_id, connection)


def seed_local_file(
        service: DashboardService,
        filename: str = "song.mp3",
        tagged_at: str | None = None,
) -> int:
    with service.database.transaction() as connection:
        location_count = connection.execute(
            "SELECT COUNT(*) FROM library_locations"
        ).fetchone()[0]

        if location_count == 0:
            connection.execute(
                "INSERT INTO library_locations (name, path, added_at) "
                "VALUES (?, ?, ?)",
                ("main", "/music", "2026-01-01T00:00:00+00:00"),
            )

        location_id = connection.execute(
            "SELECT id FROM library_locations LIMIT 1"
        ).fetchone()[0]

        service.local_files.upsert(
            LocalFile(
                location_id=location_id,
                relative_path=filename,
                filename=filename,
                format="mp3",
                size_bytes=1_000,
                mtime=1.0,
                scanned_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )
        local_file = service.local_files.get_by_location_and_relative_path(
            location_id, filename, connection,
        )

        assert local_file is not None
        assert local_file.id is not None

        # upsert() deliberately never writes tagged_at (a routine scan
        # must not wipe existing tagging state, same pattern as bpm/
        # fingerprint) — mark_tagged() is the real, separate write path.
        if tagged_at is not None:
            service.local_files.mark_tagged(
                    local_file.id,
                    tagged_at,
                    connection,
            )

    return local_file.id


def seed_match(
        service: DashboardService,
        track_id: str,
        match_method: str | None,
        local_file_id: int | None = None,
        score: float | None = None,
) -> None:
    with service.database.transaction() as connection:
        service.track_matches.upsert(
            TrackMatch(
                track_id=track_id,
                local_file_id=local_file_id,
                match_method=match_method,
                score=score,
                matched_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )


def seed_download_request(
        service: DashboardService,
        track_id: str,
        status: str,
        role: str = "settled",
        bytes_transferred: int | None = None,
        total_bytes: int | None = None,
        completed_at: str | None = None,
        requested_at: str = "2026-01-01T00:00:00+00:00",
        username: str = "peer1",
        filename: str = "file.flac",
) -> None:
    with service.database.transaction() as connection:
        service.download_requests.add(
            DownloadRequest(
                track_id=track_id,
                username=username,
                filename=filename,
                format="flac",
                role=role,
                status=status,
                transfer_id=(
                    "transfer-1" if status in ("queued", "downloading")
                    else None
                ),
                size=1_000,
                requested_at=requested_at,
                completed_at=completed_at,
            ),
            connection,
        )

        if bytes_transferred is not None or total_bytes is not None:
            request_id = connection.execute(
                "SELECT id FROM download_requests WHERE track_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (track_id,),
            ).fetchone()[0]
            service.download_requests.update_progress(
                request_id, bytes_transferred, total_bytes, connection,
            )


def seed_review_candidate(service: DashboardService, track_id: str) -> None:
    with service.database.transaction() as connection:
        service.soulseek_review_candidates.upsert(
            SoulseekReviewCandidate(
                track_id=track_id,
                username="peer2",
                filename="candidate.flac",
                score=75.0,
                quality_descriptor="flac",
                found_at="2026-01-01T00:00:00+00:00",
            ),
            connection,
        )


def test_playlist_not_found_raises(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(PlaylistNotFoundError, match="never-synced"):
        service.get_playlist_track_status("never-synced")


def test_in_library_state_for_auto_match_with_real_local_file(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    local_file_id = seed_local_file(service)
    seed_match(service, "t1", "auto", local_file_id=local_file_id, score=95.0)

    statuses = service.get_playlist_track_status("Playlist")

    assert len(statuses) == 1
    assert statuses[0].state == IN_LIBRARY
    assert statuses[0].soulseek_candidate is None
    assert statuses[0].tagged_at is None


def test_in_library_state_surfaces_real_tagged_at(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    local_file_id = seed_local_file(
        service, tagged_at="2026-08-30T12:00:00+00:00",
    )
    seed_match(service, "t1", "auto", local_file_id=local_file_id, score=95.0)

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == IN_LIBRARY
    assert statuses[0].tagged_at == "2026-08-30T12:00:00+00:00"


def test_downloading_state_surfaces_real_progress(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(
        service, "t1", status="downloading",
        bytes_transferred=500, total_bytes=1_000,
    )

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == DOWNLOADING
    assert statuses[0].bytes_transferred == 500
    assert statuses[0].total_bytes == 1_000


def test_downloading_state_covers_queued_too(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(service, "t1", status="queued")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == DOWNLOADING


def test_awaiting_review_state(tmp_path):
    # Roadmap item 66 (Phase 4.1) — narrowed to ready_for_review only;
    # locked/shortlisted is RETRYING now (see the test right below).
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(
        service, "t1", status="ready_for_review", role="upgrade",
    )

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == AWAITING_REVIEW


@pytest.mark.parametrize("status", ["locked", "shortlisted"])
def test_retrying_state(tmp_path, status):
    # Roadmap item 66 (Phase 4.1) — the split fixing the real, reported
    # AWAITING_REVIEW <-> DOWNLOADING flicker: a locked/shortlisted row
    # is being retried in the background, not waiting on a human.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(service, "t1", status=status, role="upgrade")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == RETRYING


@pytest.mark.parametrize("status", ["completed", "failed", "superseded"])
def test_terminal_download_statuses_do_not_count_as_awaiting_or_downloading(
        tmp_path, status,
):
    # A stale terminal-status row must not be mistaken for live activity
    # — falls through to NOT_FOUND (no track_match at all here).
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(service, "t1", status=status, role="upgrade")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == NOT_FOUND


def test_needs_review_state_with_no_active_download_activity(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_match(service, "t1", "needs_review", score=75.0)

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == NEEDS_REVIEW


def test_not_found_state_with_no_match_and_no_download_activity(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == NOT_FOUND


def test_in_library_takes_precedence_over_stale_leftover_download_request(
        tmp_path,
):
    # A track that already has a real auto match must show IN_LIBRARY
    # even if a stale download_requests row from before it was matched
    # is still sitting in the DB — the goal is achieved regardless of
    # leftover rows.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    local_file_id = seed_local_file(service)
    seed_match(service, "t1", "auto", local_file_id=local_file_id, score=95.0)
    seed_download_request(service, "t1", status="queued")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == IN_LIBRARY


def test_downloading_takes_precedence_over_awaiting_review(tmp_path):
    # Precedence order matters beyond just "in_library wins" — a track
    # with both an active downloading row AND a locked row (e.g. a
    # settled download in progress plus a separate stale upgrade
    # attempt) must report DOWNLOADING, not AWAITING_REVIEW.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(service, "t1", status="downloading", role="settled")
    seed_download_request(service, "t1", status="locked", role="upgrade")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == DOWNLOADING


def test_secondary_tag_surfaces_alongside_needs_review(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_match(service, "t1", "needs_review", score=75.0)
    seed_review_candidate(service, "t1")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == NEEDS_REVIEW
    assert statuses[0].soulseek_candidate is not None
    assert statuses[0].soulseek_candidate.username == "peer2"


def test_review_candidate_with_no_download_requests_row_is_its_own_state(
        tmp_path,
):
    # Roadmap item 66 (Phase 4.1) — the fix for item 0.2's own finding:
    # this used to be NOT_FOUND with the candidate as a silent secondary
    # tag; it's REVIEW_CANDIDATE's own primary state now, and the tag
    # still carries the real candidate for the Review page to use.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_review_candidate(service, "t1")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == REVIEW_CANDIDATE
    assert statuses[0].soulseek_candidate is not None


def test_secondary_tag_suppressed_when_auto_matched_despite_leftover_candidate(
        tmp_path,
):
    # The hypothetical invariant-violation case: a track somehow has
    # BOTH a real auto match AND a leftover soulseek_review_candidates
    # row (which download_playlist's clearing logic should never leave
    # behind — confirmed against the real production DB: zero such rows
    # exist there). Deliberate choice: suppress the tag rather than
    # surface a contradictory "in your library AND needs a SoulSeek
    # download" combination — enforced by construction here (the
    # candidate lookup is never even consulted for IN_LIBRARY), not by
    # a runtime special case.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    local_file_id = seed_local_file(service)
    seed_match(service, "t1", "auto", local_file_id=local_file_id, score=95.0)
    seed_review_candidate(service, "t1")

    statuses = service.get_playlist_track_status("Playlist")

    assert statuses[0].state == IN_LIBRARY
    assert statuses[0].soulseek_candidate is None


def test_scoping_two_playlists_sharing_no_tracks_never_leak(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "pA", name="Playlist A")
    seed_playlist(service, "pB", name="Playlist B")

    seed_track(service, "pA", "a1", artist="Artist A", title="Song A")
    local_file_id = seed_local_file(service, filename="a1.mp3")
    seed_match(service, "a1", "auto", local_file_id=local_file_id, score=95.0)

    seed_track(service, "pB", "b1", artist="Artist B", title="Song B")
    seed_match(service, "b1", "needs_review", score=75.0)
    seed_review_candidate(service, "b1")

    statuses_a = service.get_playlist_track_status("Playlist A")
    statuses_b = service.get_playlist_track_status("Playlist B")

    assert len(statuses_a) == 1
    assert statuses_a[0].track.id == "a1"
    assert statuses_a[0].state == IN_LIBRARY

    assert len(statuses_b) == 1
    assert statuses_b[0].track.id == "b1"
    assert statuses_b[0].state == NEEDS_REVIEW
    assert statuses_b[0].soulseek_candidate is not None


def test_get_active_downloads_is_global_across_playlists(tmp_path):
    # The exact scoping bug class this project already found once
    # (global-vs-playlist-scoped check/match_all confusion) — this
    # asserts get_active_downloads() is NOT scoped to one playlist:
    # a row from a different playlist must never be excluded.
    service = make_service(tmp_path)
    seed_playlist(service, "pA", name="Playlist A")
    seed_playlist(service, "pB", name="Playlist B")
    seed_track(service, "pA", "a1", artist="Artist A", title="Song A")
    seed_track(service, "pB", "b1", artist="Artist B", title="Song B")
    seed_download_request(service, "a1", status="downloading")
    seed_download_request(service, "b1", status="locked", role="upgrade")

    downloads = service.get_active_downloads()

    assert {d.track.id for d in downloads} == {"a1", "b1"}
    playlist_names_by_track = {d.track.id: d.playlist_name for d in downloads}
    assert playlist_names_by_track["a1"] == "Playlist A"
    assert playlist_names_by_track["b1"] == "Playlist B"


def test_get_active_downloads_manual_track_shows_manual_not_unknown(
        tmp_path,
):
    # Roadmap item 82 (P13.7) — a manual (not-from-Spotify) track
    # genuinely belongs to no playlist, same shape as an unexpected
    # "Unknown" case, but this one is real and expected — the label
    # must say so honestly rather than reading like a data-integrity
    # problem.
    service = make_service(tmp_path)

    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id="manual:abc123", title="Rhyme Dust", artist="Dom Dolla",
                album="", duration_ms=0,
            ),
            connection,
        )

    seed_download_request(service, "manual:abc123", status="downloading")

    downloads = service.get_active_downloads()

    assert len(downloads) == 1
    assert downloads[0].playlist_name == "Manual"


@pytest.mark.parametrize(
    "status", ["queued", "downloading", "locked", "shortlisted", "ready_for_review"],
)
def test_get_active_downloads_includes_every_non_terminal_status(
        tmp_path, status,
):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(service, "t1", status=status, role="upgrade")

    downloads = service.get_active_downloads()

    assert len(downloads) == 1
    assert downloads[0].request.status == status


def test_get_active_downloads_excludes_superseded(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(service, "t1", status="superseded", role="upgrade")

    downloads = service.get_active_downloads()

    assert downloads == []


def test_get_active_downloads_includes_recently_completed(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    recent = (
        datetime.now(UTC) - timedelta(seconds=10)
    ).isoformat()
    seed_download_request(
        service, "t1", status="completed", completed_at=recent,
    )

    downloads = service.get_active_downloads()

    assert len(downloads) == 1
    assert downloads[0].request.status == "completed"


def test_get_active_downloads_excludes_long_completed(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    stale = (
        datetime.now(UTC) - timedelta(hours=1)
    ).isoformat()
    seed_download_request(
        service, "t1", status="completed", completed_at=stale,
    )

    downloads = service.get_active_downloads()

    assert downloads == []


def test_get_active_downloads_excludes_long_failed(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    stale = (
        datetime.now(UTC) - timedelta(hours=1)
    ).isoformat()
    seed_download_request(
        service, "t1", status="failed", completed_at=stale,
    )

    downloads = service.get_active_downloads()

    assert downloads == []


def test_get_active_downloads_sorted_most_recent_first(tmp_path):
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1", title="Older")
    seed_track(service, "p1", "t2", title="Newer")
    seed_download_request(
        service, "t1", status="queued",
        requested_at="2026-01-01T00:00:00+00:00",
    )
    seed_download_request(
        service, "t2", status="queued",
        requested_at="2026-01-02T00:00:00+00:00",
    )

    downloads = service.get_active_downloads()

    assert [d.track.id for d in downloads] == ["t2", "t1"]


def test_get_active_downloads_collapses_genuine_duplicate_candidate_rows(
        tmp_path,
):
    # Real, live-observed shape (2026-08-28 Step 5 follow-up): three
    # rows for the same track, all rank=1, all the identical peer+file
    # — stale leftovers from before download_playlist()'s
    # get_active_for_track guard (item 16) was fully effective, not
    # Phase 4's legitimate multi-candidate shortlist (which always uses
    # distinct peers/files per rank). Only the most-recently-requested
    # of the three should surface.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(
        service, "t1", status="queued", role="upgrade",
        username="long25", filename="Breach.flac",
        requested_at="2026-08-27T13:01:24+00:00",
    )
    seed_download_request(
        service, "t1", status="locked", role="upgrade",
        username="long25", filename="Breach.flac",
        requested_at="2026-08-27T13:15:47+00:00",
    )
    seed_download_request(
        service, "t1", status="locked", role="upgrade",
        username="long25", filename="Breach.flac",
        requested_at="2026-08-27T17:41:05+00:00",
    )

    downloads = service.get_active_downloads()

    assert len(downloads) == 1
    assert downloads[0].request.requested_at == "2026-08-27T17:41:05+00:00"


def test_get_active_downloads_keeps_legitimate_multi_candidate_rows_separate(
        tmp_path,
):
    # The exact case the dedup above must NOT collapse: Phase 4's
    # ranked shortlist — a rank-1 active row plus rank-2/3 backups for
    # the same track, each a genuinely different real peer/file. These
    # must all keep showing, since they're real, distinct candidates,
    # not repeats of one attempt.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(
        service, "t1", status="locked", role="upgrade",
        username="peerA", filename="candidate-a.flac",
        requested_at="2026-08-28T10:00:00+00:00",
    )
    seed_download_request(
        service, "t1", status="shortlisted", role="upgrade",
        username="peerB", filename="candidate-b.flac",
        requested_at="2026-08-28T10:00:00+00:00",
    )
    seed_download_request(
        service, "t1", status="shortlisted", role="upgrade",
        username="peerC", filename="candidate-c.flac",
        requested_at="2026-08-28T10:00:00+00:00",
    )

    downloads = service.get_active_downloads()

    assert len(downloads) == 3
    assert {
            d.request.username for d in downloads
    } == {"peerA", "peerB", "peerC"}


def test_get_active_downloads_dedup_does_not_merge_across_roles(tmp_path):
    # A track can legitimately have both a settled request and an
    # upgrade request in flight at once (item 8) — even if they somehow
    # shared a peer/file, role keeps them distinct rather than merging
    # two conceptually different attempts.
    service = make_service(tmp_path)
    seed_playlist(service, "p1")
    seed_track(service, "p1", "t1")
    seed_download_request(
        service, "t1", status="downloading", role="settled",
        username="peer1", filename="same.flac",
        requested_at="2026-08-28T10:00:00+00:00",
    )
    seed_download_request(
        service, "t1", status="queued", role="upgrade",
        username="peer1", filename="same.flac",
        requested_at="2026-08-28T10:00:00+00:00",
    )

    downloads = service.get_active_downloads()

    assert len(downloads) == 2

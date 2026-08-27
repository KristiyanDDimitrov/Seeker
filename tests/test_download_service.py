from datetime import datetime, timezone

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
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.soulseek.client import SoulseekDownloadError
from seeker.soulseek.download_service import DownloadService, _build_search_query


def test_build_search_query_strips_comma_from_multi_artist_track():
    # track.artist may credit multiple artists joined with ", " (e.g.
    # "MK, Dom Dolla") — the literal comma isn't a sane search string,
    # so it must not appear in the built query.
    track = Track(
        id="track1",
        title="Rhyme Dust",
        artist="MK, Dom Dolla",
        album="Rhyme Dust",
        duration_ms=215_000,
    )

    query = _build_search_query(track)

    assert "," not in query
    assert query == "MK Dom Dolla Rhyme Dust"


class FakeSoulseekClient:
    def __init__(
            self,
            states: dict[str, str],
            exceptions: dict[str, str] | None = None,
            retry_results: dict[str, "str | Exception"] | None = None,
            search_results: dict[str, "list[SoulseekFile] | Exception"]
            | None = None,
    ):
        self.states = states
        self.exceptions = exceptions or {}
        # Phase 3 retry: keyed by filename (request_download itself has
        # no transfer_id to key off — it's issuing a brand new one), maps
        # to either the new transfer_id to return, or an Exception
        # instance to raise (rejected again at the batch level).
        self.retry_results = retry_results or {}
        self.request_download_calls: list[tuple[str, str, int]] = []
        # Keyed by the exact search query string — either a list of
        # candidates, or an Exception to raise (simulating a real
        # search failure for one track mid-batch).
        self.search_results = search_results or {}
        self.search_calls: list[str] = []

    def search(self, query: str) -> list["SoulseekFile"]:
        self.search_calls.append(query)

        result = self.search_results.get(query)

        if isinstance(result, Exception):
            raise result

        return result or []

    def get_download_status(self, username: str, transfer_id: str) -> str:
        return self.states[transfer_id]

    def get_download_exception(
            self, username: str, transfer_id: str,
    ) -> str | None:
        return self.exceptions.get(transfer_id)

    def request_download(self, username: str, filename: str, size: int) -> str:
        self.request_download_calls.append((username, filename, size))

        result = self.retry_results.get(filename)

        if isinstance(result, Exception):
            raise result

        return result or f"retry-transfer-for-{filename}"


def make_service(
        tmp_path,
        states: dict[str, str],
        exceptions: dict[str, str] | None = None,
        retry_results: dict | None = None,
        search_results: dict | None = None,
) -> DownloadService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return DownloadService(
        database,
        FakeSoulseekClient(
            states, exceptions, retry_results, search_results,
        ),
        PlaylistRepository(database),
        TrackRepository(database),
        LibraryLocationRepository(database),
        DownloadRequestRepository(database),
        TrackMatchRepository(database),
        LocalFileRepository(database),
        SoulseekReviewCandidateRepository(database),
        slskd_download_dir=None,
    )


def seed_pending_request(
        service: DownloadService,
        transfer_id: str | None,
        track_id: str = "track1",
        role: str = "settled",
        status: str = "queued",
        size: int = 1_000_000,
        filename: str = "Dom Dolla - Rhyme Dust.mp3",
        rank: int | None = None,
        username: str = "peer1",
) -> None:
    with service.database.transaction() as connection:
        existing = service.tracks.get_by_id(track_id, connection)

        if existing is None:
            service.tracks.save(
                Track(
                    id=track_id,
                    title="Rhyme Dust",
                    artist="Dom Dolla",
                    album="Rhyme Dust",
                    duration_ms=215_000,
                ),
                connection,
            )

        service.download_requests.add(
            DownloadRequest(
                track_id=track_id,
                username=username,
                filename=filename,
                format="mp3",
                quality_descriptor="flac",
                role=role,
                status=status,
                transfer_id=transfer_id,
                size=size,
                rank=rank,
                requested_at=datetime.now(timezone.utc).isoformat(),
            ),
            connection,
        )


def get_status(service: DownloadService, transfer_id: str) -> str:
    with service.database.transaction() as connection:
        rows = service.download_requests.get_pending(connection)

    for row in rows:
        if row.transfer_id == transfer_id:
            return row.status

    # Not pending means it moved to a terminal state; check directly.
    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status, completed_at FROM download_requests "
            "WHERE transfer_id = ?",
            (transfer_id,),
        ).fetchone()

    return row["status"]


def _seed_playlist_with_unmatched_tracks(
        service: DownloadService,
        tmp_path,
        track_ids: list[str],
) -> None:
    lib_root = tmp_path / "music"
    lib_root.mkdir(exist_ok=True)

    with service.database.transaction() as connection:
        service.locations.add(
            LibraryLocation(
                name="Main", path=str(lib_root), added_at="2026-01-01"
            ),
            connection,
        )
        location = service.locations.get_by_name("Main", connection)

        service.playlists.save(
            Playlist(id="p1", name="Test", track_count=len(track_ids)),
            connection,
        )
        service.playlists.set_destination(
            "p1", location.id, None, connection
        )

        for track_id in track_ids:
            service.tracks.save(
                Track(
                    id=track_id,
                    title=f"Title {track_id}",
                    artist="Dom Dolla",
                    album="Album",
                    duration_ms=200_000,
                ),
                connection,
            )
            service.tracks.save_playlist_track("p1", track_id, connection)


def make_soulseek_file(**overrides) -> SoulseekFile:
    defaults = dict(
        username="peer1",
        filename="Dom Dolla - Title.flac",
        extension="flac",
        size=1_000_000,
        queue_length=2,
        upload_speed=1_000_000,
        has_free_upload_slot=True,
    )
    defaults.update(overrides)
    return SoulseekFile(**defaults)


def test_download_playlist_mid_batch_exception_does_not_abort_remaining_tracks(
        tmp_path,
):
    # Real bug, found via a real "Test" playlist run: an uncaught
    # exception during ONE track's search (a network blip, a malformed
    # response — anything) used to propagate straight out of
    # download_playlist(), silently aborting every track after it with
    # no accounting at all. Every track must land in exactly one bucket:
    # requested, skipped (no candidates), or failed (with a reason) —
    # never silently dropped.
    query_t1 = "Dom Dolla Title t1"
    query_t2 = "Dom Dolla Title t2"
    query_t3 = "Dom Dolla Title t3"

    candidate = make_soulseek_file(
        filename="Dom Dolla - Title t2.flac",
        queue_length=2,
    )

    service = make_service(
        tmp_path,
        states={},
        search_results={
            query_t1: RuntimeError("simulated network failure"),
            query_t2: [candidate],
            query_t3: [],
        },
    )
    _seed_playlist_with_unmatched_tracks(
        service, tmp_path, ["t1", "t2", "t3"]
    )

    result = service.download_playlist("Test")

    assert result["total"] == 3
    assert result["requested"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 1
    # Every track accounted for exactly once.
    assert (
        result["requested"] + result["skipped"] + result["failed"]
        == result["total"]
    )

    # t2 (after the failing t1) was genuinely processed and requested —
    # confirming the loop didn't just stop at t1.
    with service.database.transaction() as connection:
        rows = connection.execute(
            "SELECT track_id FROM download_requests"
        ).fetchall()

    assert [row["track_id"] for row in rows] == ["t2"]

    # All three tracks were actually searched — the loop kept going past
    # the failure, it didn't just silently stop.
    assert service.soulseek.search_calls == [query_t1, query_t2, query_t3]


def test_download_playlist_requests_locked_only_candidate_as_upgrade(
        tmp_path,
):
    # Real bug, found live against the real "Test" playlist (2026-08-27):
    # a real slskd search for "Jade Venom - Scared Now? - DIVERGENCE VI"
    # returned exactly one candidate passing filter_candidates (score
    # 90.9, above AUTO_MATCH_THRESHOLD) — but it was locked, so
    # select_downloads correctly returned (settled=None,
    # shortlist=[that locked file]) per its own documented contract.
    # download_playlist's `if settled is None: ... continue` branch never
    # looked at upgrade_shortlist, silently discarding a real,
    # above-threshold candidate instead of requesting it into
    # poll_downloads' existing locked-retry cascade. Reproduces the exact
    # real candidate data (username/filename/size/queue_length) captured
    # from that live search, not a synthetic stand-in.
    query = "Jade Venom Scared Now? - DIVERGENCE VI"

    locked_candidate = make_soulseek_file(
        username="ofoijacussa",
        filename=(
            "Music (unsorted)\\Labels\\Eatbrain [FLAC]\\"
            "[EATBRAIN211] Jade Venom - Scared Now "
            "(Divergence VI. Sampler) [2025]\\"
            "01. Jade Venom - Scared Now (DIVERGENCE VI).flac"
        ),
        size=55_144_573,
        queue_length=7,
        upload_speed=228_249,
        has_free_upload_slot=True,
        length=242,
        bit_depth=24,
        sample_rate=44_100,
        locked=True,
    )

    service = make_service(
        tmp_path,
        states={},
        search_results={query: [locked_candidate]},
    )

    lib_root = tmp_path / "music"
    lib_root.mkdir(exist_ok=True)

    with service.database.transaction() as connection:
        service.locations.add(
            LibraryLocation(
                name="Main", path=str(lib_root), added_at="2026-01-01"
            ),
            connection,
        )
        location = service.locations.get_by_name("Main", connection)

        service.playlists.save(
            Playlist(id="p1", name="Test", track_count=1),
            connection,
        )
        service.playlists.set_destination(
            "p1", location.id, None, connection
        )

        service.tracks.save(
            Track(
                id="jade-venom-track",
                title="Scared Now? - DIVERGENCE VI",
                artist="Jade Venom",
                album="",
                duration_ms=242_000,
            ),
            connection,
        )
        service.tracks.save_playlist_track(
            "p1", "jade-venom-track", connection
        )

    result = service.download_playlist("Test")

    # A real download WAS requested (as an upgrade, not settled) — this
    # must not be reported as "skipped, nothing found."
    assert result["requested"] == 1
    assert result["skipped"] == 0
    assert result["failed"] == 0

    assert service.soulseek.request_download_calls == [
        (
            "ofoijacussa",
            locked_candidate.filename,
            55_144_573,
        )
    ]

    with service.database.transaction() as connection:
        rows = connection.execute(
            "SELECT track_id, role, rank, status, username, filename "
            "FROM download_requests"
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["track_id"] == "jade-venom-track"
    assert row["role"] == "upgrade"
    assert row["rank"] == 1
    assert row["status"] == "queued"
    assert row["username"] == "ofoijacussa"
    assert row["filename"] == locked_candidate.filename


def _seed_single_unmatched_track(
        service: DownloadService,
        tmp_path,
        track_id: str,
        artist: str,
        title: str,
) -> None:
    lib_root = tmp_path / "music"
    lib_root.mkdir(exist_ok=True)

    with service.database.transaction() as connection:
        service.locations.add(
            LibraryLocation(
                name="Main", path=str(lib_root), added_at="2026-01-01"
            ),
            connection,
        )
        location = service.locations.get_by_name("Main", connection)

        service.playlists.save(
            Playlist(id="p1", name="Test", track_count=1),
            connection,
        )
        service.playlists.set_destination(
            "p1", location.id, None, connection
        )

        service.tracks.save(
            Track(
                id=track_id,
                title=title,
                artist=artist,
                album="",
                duration_ms=200_000,
            ),
            connection,
        )
        service.tracks.save_playlist_track("p1", track_id, connection)


def test_download_playlist_records_real_prdk_and_zigi_sc_as_needs_review(
        tmp_path,
):
    # STEP 4: confirms two of the real, previously-silently-dropped
    # "Test" playlist candidates (captured live 2026-08-27 — see
    # test_quality.py's REAL_PRDK_CANDIDATE/REAL_ZIGI_SC_CANDIDATE for the
    # exact same real data) now land in soulseek_review_candidates instead
    # of vanishing behind "No candidates found."
    prdk_candidate = make_soulseek_file(
        username="musicmasterrdjpool",
        filename=(
            "DJPOOLS\\2026\\MONTHS\\FEB\\20\\The Mash Up 20 FEB\\"
            "Prdk - One More Night (Clean) 4A 87.mp3"
        ),
        extension="mp3",
        size=9_251_601,
        queue_length=67_376,
        upload_speed=143_109,
        has_free_upload_slot=False,
        length=227,
        bit_rate=320,
        bit_depth=None,
        sample_rate=None,
        is_variable_bitrate=False,
    )
    zigi_sc_candidate = make_soulseek_file(
        username="musicmasterrdjpool",
        filename=(
            "DJPOOLS\\2026\\MONTHS\\AUG\\18\\"
            "Beatport Best of Independent Artist [July 2026]\\"
            "A-Cray, Zigi SC - Bit Perfect (Original Mix).mp3"
        ),
        extension="mp3",
        size=12_424_929,
        queue_length=67_377,
        upload_speed=143_109,
        has_free_upload_slot=False,
        length=306,
        bit_rate=320,
        bit_depth=None,
        sample_rate=None,
        is_variable_bitrate=False,
    )

    prdk_query = "Prdk ONE MORE NIGHT"
    service = make_service(
        tmp_path,
        states={},
        search_results={prdk_query: [prdk_candidate]},
    )
    _seed_single_unmatched_track(
        service, tmp_path, "prdk-track", "Prdk", "ONE MORE NIGHT"
    )

    result = service.download_playlist("Test")

    # No auto-tier candidate exists — a real download must not be
    # requested for a needs_review-only result.
    assert result["requested"] == 0
    assert result["skipped"] == 1
    assert service.soulseek.request_download_calls == []

    with service.database.transaction() as connection:
        rows = connection.execute(
            "SELECT track_id, username, filename, score, "
            "quality_descriptor FROM soulseek_review_candidates"
        ).fetchall()

    assert len(rows) == 1
    row = rows[0]
    assert row["track_id"] == "prdk-track"
    assert row["username"] == "musicmasterrdjpool"
    assert row["filename"] == prdk_candidate.filename
    assert 70.0 <= row["score"] < 90.0
    assert row["quality_descriptor"] == "mp3 320kbps"

    review_candidates = service.get_review_candidates()
    assert len(review_candidates) == 1
    track, candidate = review_candidates[0]
    assert track.artist == "Prdk"
    assert track.title == "ONE MORE NIGHT"
    assert candidate.username == "musicmasterrdjpool"
    assert candidate.filename == prdk_candidate.filename

    # Second track, same real Zigi SC/A-Cray data, on a fully separate DB
    # (own subdirectory) so it can't collide with the first service's
    # library_locations UNIQUE(path) constraint.
    zigi_query = "Zigi SC A-Cray Bit Perfect"
    zigi_tmp_path = tmp_path / "zigi"
    zigi_tmp_path.mkdir()
    service2 = make_service(
        zigi_tmp_path,
        states={},
        search_results={zigi_query: [zigi_sc_candidate]},
    )
    _seed_single_unmatched_track(
        service2,
        zigi_tmp_path,
        "zigi-track",
        "Zigi SC, A-Cray",
        "Bit Perfect",
    )

    result2 = service2.download_playlist("Test")

    assert result2["requested"] == 0
    assert result2["skipped"] == 1

    with service2.database.transaction() as connection:
        rows2 = connection.execute(
            "SELECT track_id, username, filename, score "
            "FROM soulseek_review_candidates"
        ).fetchall()

    assert len(rows2) == 1
    assert rows2[0]["track_id"] == "zigi-track"
    assert rows2[0]["filename"] == zigi_sc_candidate.filename
    assert 70.0 <= rows2[0]["score"] < 90.0


def test_download_playlist_clears_stale_review_candidate_once_settled(
        tmp_path,
):
    # A needs_review row from an earlier run must not keep being surfaced
    # once a later run finds a real, downloadable auto-tier candidate for
    # the same track.
    query = "Dom Dolla Title t1"
    needs_review_candidate = make_soulseek_file(
        # Scores ~78 — comfortably inside the needs_review band, well
        # below AUTO_MATCH_THRESHOLD (verified against the real
        # score_title/normalize_soulseek_title functions, not assumed).
        filename="Dom Dolla - Title t1 (Clean).flac",
    )
    auto_candidate = make_soulseek_file(
        filename="Dom Dolla - Title t1.flac",
        queue_length=2,
    )

    service = make_service(
        tmp_path,
        states={},
        search_results={query: [needs_review_candidate]},
    )
    _seed_playlist_with_unmatched_tracks(service, tmp_path, ["t1"])

    first = service.download_playlist("Test")
    assert first["skipped"] == 1

    with service.database.transaction() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM soulseek_review_candidates"
        ).fetchone()[0]
    assert count == 1

    service.soulseek.search_results[query] = [auto_candidate]

    second = service.download_playlist("Test")
    assert second["requested"] == 1

    with service.database.transaction() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM soulseek_review_candidates"
        ).fetchone()[0]
    assert count == 0


def test_succeeded_state_marks_completed(tmp_path, monkeypatch):
    service = make_service(
        tmp_path, {"t1": "Completed, Succeeded"}
    )
    seed_pending_request(service, "t1")

    fake_location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path), added_at="2026-01-01"
    )
    monkeypatch.setattr(
        service,
        "_move_completed_file",
        lambda request: (fake_location, "song.mp3"),
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert get_status(service, "t1") == "completed"


def test_poll_downloads_mid_batch_exception_does_not_abort_remaining_requests(
        tmp_path,
):
    # Same class of bug as download_playlist's mid-batch fix — an
    # unexpected exception polling ONE request (t1's transfer_id is
    # deliberately not stubbed in `states`, triggering a real KeyError,
    # standing in for any real unexpected failure talking to slskd) must
    # not stop t2 from being polled in the same run.
    service = make_service(tmp_path, {"t2": "InProgress"})
    seed_pending_request(service, "t1", track_id="track1")
    seed_pending_request(service, "t2", track_id="track2")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert counts["downloading"] == 1
    assert get_status(service, "t2") == "downloading"


def test_errored_state_marks_failed_not_completed(tmp_path):
    service = make_service(
        tmp_path, {"t1": "Completed, Errored"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert counts["completed"] == 0
    assert get_status(service, "t1") == "failed"


def test_cancelled_state_marks_failed(tmp_path):
    service = make_service(
        tmp_path, {"t1": "Cancelled"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert get_status(service, "t1") == "failed"


def test_timed_out_state_marks_failed(tmp_path):
    service = make_service(
        tmp_path, {"t1": "Completed, TimedOut"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert get_status(service, "t1") == "failed"


def test_rejected_state_marks_failed(tmp_path):
    service = make_service(
        tmp_path, {"t1": "Rejected"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert get_status(service, "t1") == "failed"


def test_rejected_settled_role_marks_failed_even_with_lock_exception_text(
        tmp_path,
):
    # The locked-retry treatment is scoped to role='upgrade' only —
    # select_downloads() never picks a locked candidate as 'settled', so
    # a settled-role rejection (even one that happens to carry
    # lock-shaped exception text) stays a plain failure, not a retry.
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: File not shared."},
    )
    seed_pending_request(service, "t1", role="settled")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert get_status(service, "t1") == "failed"


def test_rejected_upgrade_with_lock_exception_routes_to_locked_not_failed(
        tmp_path,
):
    # Real confirmed rejection text (2026-08-27 live investigation).
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: File not shared."},
    )
    seed_pending_request(service, "t1", role="upgrade")

    counts = service.poll_downloads()

    assert counts["failed"] == 0
    assert counts["locked"] == 1
    assert get_status(service, "t1") == "locked"


def test_rejected_upgrade_with_other_reason_still_marks_failed(tmp_path):
    # Any OTHER rejection reason must still terminate as 'failed' — the
    # locked-retry path is specifically for the confirmed lock signal,
    # not a blanket "any rejection gets retried" policy.
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: Too many requests."},
    )
    seed_pending_request(service, "t1", role="upgrade")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert counts["locked"] == 0
    assert get_status(service, "t1") == "failed"


def test_locked_request_succeeds_on_retry_transitions_to_downloading(
        tmp_path,
):
    service = make_service(
        tmp_path,
        # "old-1" is never polled directly (it's already 'locked', not
        # pending) — only the NEW transfer_id issued by the retry is.
        states={"new-1": "InProgress"},
        retry_results={"Dom Dolla - Rhyme Dust.mp3": "new-1"},
    )
    seed_pending_request(
        service, "old-1", role="upgrade", status="locked", size=12_345,
    )

    counts = service.poll_downloads()

    assert counts["locked"] == 0
    assert service.soulseek.request_download_calls == [
        ("peer1", "Dom Dolla - Rhyme Dust.mp3", 12_345),
    ]

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status, transfer_id FROM download_requests "
            "WHERE filename = 'Dom Dolla - Rhyme Dust.mp3'"
        ).fetchone()

    assert row["status"] == "downloading"
    assert row["transfer_id"] == "new-1"


def test_locked_request_rejected_again_stays_locked_not_failed(tmp_path):
    service = make_service(
        tmp_path,
        states={"new-1": "Completed, Rejected"},
        retry_results={"Dom Dolla - Rhyme Dust.mp3": "new-1"},
    )
    seed_pending_request(
        service, "old-1", role="upgrade", status="locked", size=12_345,
    )

    counts = service.poll_downloads()

    # Only a genuinely different rejection reason should ever move a
    # locked request out of the retry cycle — a repeat rejection (any
    # reason) on the retry itself stays 'locked', not 'failed'.
    assert counts["failed"] == 0
    assert counts["locked"] == 1

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status, transfer_id FROM download_requests "
            "WHERE filename = 'Dom Dolla - Rhyme Dust.mp3'"
        ).fetchone()

    assert row["status"] == "locked"
    # transfer_id was updated to the new attempt even though it stayed
    # locked, so the next run polls the latest attempt, not the stale one.
    assert row["transfer_id"] == "new-1"


def test_locked_request_rejected_at_batch_level_stays_locked(tmp_path):
    # request_download() itself can raise (rejected before a transfer_id
    # is even issued) — this must also stay 'locked', not crash the poll
    # or fall through to 'failed'.
    service = make_service(
        tmp_path,
        states={},
        retry_results={
            "Dom Dolla - Rhyme Dust.mp3": SoulseekDownloadError(
                "rejected"
            ),
        },
    )
    seed_pending_request(
        service, "old-1", role="upgrade", status="locked", size=12_345,
    )

    counts = service.poll_downloads()

    assert counts["failed"] == 0
    assert counts["locked"] == 1
    assert get_status(service, "old-1") == "locked"


def test_completed_without_succeeded_is_not_treated_as_done(tmp_path):
    # "Completed" alone (no recognized outcome flag) must not be
    # mistaken for success — only an explicit "Succeeded" should trigger
    # the file move and a 'completed' status.
    service = make_service(
        tmp_path, {"t1": "Completed"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["completed"] == 0
    assert counts["failed"] == 0
    assert get_status(service, "t1") == "downloading"


def test_in_progress_state_marks_downloading(tmp_path):
    service = make_service(
        tmp_path, {"t1": "InProgress"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["downloading"] == 1
    assert get_status(service, "t1") == "downloading"


def test_requested_state_stays_queued(tmp_path):
    service = make_service(
        tmp_path, {"t1": "Requested"}
    )
    seed_pending_request(service, "t1")

    counts = service.poll_downloads()

    assert counts["queued"] == 1
    assert get_status(service, "t1") == "queued"


def test_completed_upgrade_transfer_marks_ready_for_review_without_moving(
        tmp_path, monkeypatch,
):
    service = make_service(
        tmp_path, {"t1": "Completed, Succeeded"}
    )
    seed_pending_request(service, "t1", role="upgrade")

    # role='upgrade' must not trigger a move (or touch track_matches) on
    # poll_downloads() — that's review_pending_upgrades()'s job, and
    # poll_downloads() never calls it (no input() involved here at all).
    def fail_if_called(request):
        raise AssertionError(
            "settled-style move must not run for an unconfirmed upgrade"
        )

    monkeypatch.setattr(service, "_move_completed_file", fail_if_called)

    counts = service.poll_downloads()

    assert counts["ready_for_review"] == 1
    assert get_status(service, "t1") == "ready_for_review"

    with service.database.transaction() as connection:
        assert service.track_matches.get_by_track_id("t1", connection) is None


def _seed_upgrade_scenario(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    lib_root = tmp_path / "music"
    lib_root.mkdir()
    (lib_root / "old.mp3").write_bytes(b"old audio data")

    slskd_dir = tmp_path / "slskd_downloads"
    slskd_dir.mkdir()
    (slskd_dir / "Dom Dolla - Rhyme Dust.flac").write_bytes(b"new flac data")

    locations = LibraryLocationRepository(database)
    playlists = PlaylistRepository(database)
    tracks = TrackRepository(database)
    track_matches = TrackMatchRepository(database)
    local_files = LocalFileRepository(database)
    download_requests = DownloadRequestRepository(database)

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(
                name="Main", path=str(lib_root), added_at="2026-01-01"
            ),
            connection,
        )
        location = locations.get_by_name("Main", connection)

        playlists.save(Playlist(id="p1", name="DnB", track_count=1), connection)
        playlists.set_destination("p1", location.id, None, connection)

        tracks.save(
            Track(
                id="t1",
                title="Rhyme Dust",
                artist="Dom Dolla",
                album="Rhyme Dust",
                duration_ms=181_000,
            ),
            connection,
        )
        tracks.save_playlist_track("p1", "t1", connection)

        local_files.upsert(
            LocalFile(
                location_id=location.id,
                relative_path="old.mp3",
                filename="old.mp3",
                format="mp3",
                size_bytes=14,
                mtime=1.0,
                scanned_at="2026-01-01",
            ),
            connection,
        )
        old_local_file = local_files.get_by_location_and_relative_path(
            location.id, "old.mp3", connection,
        )

        track_matches.upsert(
            TrackMatch(
                track_id="t1",
                local_file_id=old_local_file.id,
                match_method="auto",
                score=95.0,
                matched_at="2026-01-01",
            ),
            connection,
        )

        download_requests.add(
            DownloadRequest(
                track_id="t1",
                username="peer1",
                filename="Dom Dolla - Rhyme Dust.flac",
                format="flac",
                quality_descriptor="flac",
                role="upgrade",
                status="ready_for_review",
                transfer_id="tid1",
                requested_at="2026-01-01",
            ),
            connection,
        )

    service = DownloadService(
        database,
        FakeSoulseekClient({}),
        playlists,
        tracks,
        locations,
        download_requests,
        track_matches,
        local_files,
        SoulseekReviewCandidateRepository(database),
        str(slskd_dir),
    )

    return service, lib_root


def _ready_for_review_count(service: DownloadService) -> int:
    with service.database.transaction() as connection:
        return len(service.download_requests.get_ready_for_review(connection))


def test_review_pending_upgrades_yes_replaces_file_and_track_match(
        tmp_path, monkeypatch,
):
    # Operates directly on a pre-seeded ready_for_review row — no poll
    # step needed, since review_pending_upgrades() never talks to slskd.
    service, lib_root = _seed_upgrade_scenario(tmp_path)

    # First prompt: confirm replacement. Second prompt: decline deleting
    # the old file.
    answers = iter(["y", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    service.review_pending_upgrades()

    assert _ready_for_review_count(service) == 0

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM download_requests WHERE transfer_id = ?",
            ("tid1",),
        ).fetchone()
        assert row["status"] == "completed"

        match = service.track_matches.get_by_track_id("t1", connection)
        new_local_file = service.local_files.get_by_id(
            match.local_file_id, connection,
        )
        assert new_local_file.relative_path == "Dom Dolla - Rhyme Dust.flac"

    assert (lib_root / "Dom Dolla - Rhyme Dust.flac").exists()
    # Declined deletion — old file must still be on disk.
    assert (lib_root / "old.mp3").exists()


def test_review_pending_upgrades_yes_then_yes_deletes_old_file(
        tmp_path, monkeypatch,
):
    service, lib_root = _seed_upgrade_scenario(tmp_path)

    answers = iter(["y", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    service.review_pending_upgrades()

    assert not (lib_root / "old.mp3").exists()
    assert (lib_root / "Dom Dolla - Rhyme Dust.flac").exists()


def test_review_pending_upgrades_no_leaves_ready_for_review(
        tmp_path, monkeypatch,
):
    service, lib_root = _seed_upgrade_scenario(tmp_path)

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    service.review_pending_upgrades()

    assert _ready_for_review_count(service) == 1

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM download_requests WHERE transfer_id = ?",
            ("tid1",),
        ).fetchone()
        assert row["status"] == "ready_for_review"

        match = service.track_matches.get_by_track_id("t1", connection)
        old_local_file = service.local_files.get_by_id(
            match.local_file_id, connection,
        )
        assert old_local_file.relative_path == "old.mp3"

    # Untouched — the new file stays put in slskd's own dir, unmoved.
    assert (lib_root / "old.mp3").exists()
    assert not (lib_root / "Dom Dolla - Rhyme Dust.flac").exists()


def test_review_pending_upgrades_prints_nothing_to_review_when_empty(
        tmp_path, capsys,
):
    service = make_service(tmp_path, {})

    service.review_pending_upgrades()

    assert "Nothing to review." in capsys.readouterr().out


# Real peer usernames/sizes captured from a live "Dom Dolla Rhyme Dust"
# search earlier in this project's history (the locked-file investigation
# behind Phase 3/4) — reused here for realistic shortlist data at the
# download_service layer, which operates on already-selected candidates
# (DB rows) rather than raw search results, so the messier real filenames
# (which wouldn't all survive quality.py's fuzzy title matching — that's
# exercised separately in test_quality.py) don't need to round-trip
# through filter_candidates here.
REAL_RANK1 = dict(username="Wolfring", filename="wolfring.flac", size=34_279_790)
REAL_RANK2 = dict(username="lifelooop", filename="lifelooop.flac", size=58_789_866)
REAL_RANK3 = dict(username="CDM-Addicted", filename="cdm-addicted.wav", size=58_701_680)


def test_cascade_through_two_rejections_to_third_candidate_that_succeeds(
        tmp_path,
):
    service = make_service(
        tmp_path,
        states={
            "active-1": "Completed, Rejected",
            "new-2": "Completed, Rejected",
            "new-3": "Completed, Succeeded",
        },
        exceptions={
            "active-1": "Transfer rejected: File not shared.",
            "new-2": "Transfer rejected: File not shared.",
        },
        retry_results={
            REAL_RANK2["filename"]: "new-2",
            REAL_RANK3["filename"]: "new-3",
        },
    )

    seed_pending_request(
        service, "active-1", track_id="t1", role="upgrade",
        status="queued", rank=1, **REAL_RANK1,
    )
    seed_pending_request(
        service, None, track_id="t1", role="upgrade",
        status="shortlisted", rank=2, **REAL_RANK2,
    )
    seed_pending_request(
        service, None, track_id="t1", role="upgrade",
        status="shortlisted", rank=3, **REAL_RANK3,
    )

    counts = service.poll_downloads()

    assert counts["ready_for_review"] == 1
    assert counts["locked"] == 0
    assert counts["shortlisted"] == 0
    assert counts["superseded"] == 2

    with service.database.transaction() as connection:
        rows = connection.execute(
            "SELECT username, status FROM download_requests "
            "WHERE track_id = 't1' ORDER BY rank"
        ).fetchall()

    statuses = {row["username"]: row["status"] for row in rows}
    # rank 1 and 2 were both rejected this same run, then superseded the
    # instant rank 3 succeeded — not left dangling as 'locked'.
    assert statuses["Wolfring"] == "superseded"
    assert statuses["lifelooop"] == "superseded"
    assert statuses["CDM-Addicted"] == "ready_for_review"


def test_shortlist_exhaustion_falls_back_to_per_entry_daily_retry(tmp_path):
    # Run 1: all three ranks get rejected in cascade within the same run,
    # exhausting the shortlist.
    service = make_service(
        tmp_path,
        states={"active-1": "Completed, Rejected"},
        exceptions={"active-1": "Transfer rejected: File not shared."},
        retry_results={
            REAL_RANK2["filename"]: SoulseekDownloadError(
                "File not shared."
            ),
            REAL_RANK3["filename"]: SoulseekDownloadError(
                "File not shared."
            ),
        },
    )

    seed_pending_request(
        service, "active-1", track_id="t1", role="upgrade",
        status="queued", rank=1, **REAL_RANK1,
    )
    seed_pending_request(
        service, None, track_id="t1", role="upgrade",
        status="shortlisted", rank=2, **REAL_RANK2,
    )
    seed_pending_request(
        service, None, track_id="t1", role="upgrade",
        status="shortlisted", rank=3, **REAL_RANK3,
    )

    counts_run1 = service.poll_downloads()

    assert counts_run1["locked"] == 3
    assert counts_run1["shortlisted"] == 0

    # Run 2: EVERY locked entry for the track gets retried, not just the
    # highest-ranked one — extending Phase 3's per-entry retry to the
    # whole shortlist.
    service.soulseek.retry_results = {
        REAL_RANK1["filename"]: SoulseekDownloadError("File not shared."),
        REAL_RANK2["filename"]: SoulseekDownloadError("File not shared."),
        REAL_RANK3["filename"]: SoulseekDownloadError("File not shared."),
    }

    counts_run2 = service.poll_downloads()

    assert counts_run2["locked"] == 3

    calls_by_filename: dict[str, int] = {}
    for _, filename, _ in service.soulseek.request_download_calls:
        calls_by_filename[filename] = calls_by_filename.get(filename, 0) + 1

    # rank 1 is only ever retried (never cascaded to, since it was the
    # initially active one); ranks 2 and 3 were cascaded to in run 1 AND
    # retried again in run 2 — two calls each.
    assert calls_by_filename[REAL_RANK1["filename"]] == 1
    assert calls_by_filename[REAL_RANK2["filename"]] == 2
    assert calls_by_filename[REAL_RANK3["filename"]] == 2


def test_success_on_rank_two_supersedes_locked_rank_one_and_shortlisted_rank_three(
        tmp_path,
):
    # rank 1 is ALREADY 'locked' from a previous run (not rejected THIS
    # run) — it's picked up by the separate Phase 3 retry loop, which
    # runs AFTER the main loop. rank 2 is this run's active/pending
    # entry, and succeeds directly (no cascade involved). Confirms the
    # race fix: the stale retry loop must not resurrect rank 1 after it's
    # been superseded mid-run by rank 2's success.
    service = make_service(
        tmp_path,
        states={"active-2": "Completed, Succeeded"},
        # If rank 1 were (incorrectly) retried after being superseded,
        # this would raise and fail the test loudly.
        retry_results={
            REAL_RANK1["filename"]: AssertionError(
                "superseded rank 1 must not be retried this run"
            ),
        },
    )

    seed_pending_request(
        service, "locked-1", track_id="t1", role="upgrade",
        status="locked", rank=1, **REAL_RANK1,
    )
    seed_pending_request(
        service, "active-2", track_id="t1", role="upgrade",
        status="queued", rank=2, **REAL_RANK2,
    )
    seed_pending_request(
        service, None, track_id="t1", role="upgrade",
        status="shortlisted", rank=3, **REAL_RANK3,
    )

    counts = service.poll_downloads()

    assert counts["ready_for_review"] == 1
    assert counts["locked"] == 0
    assert counts["shortlisted"] == 0
    assert counts["superseded"] == 2

    with service.database.transaction() as connection:
        rows = connection.execute(
            "SELECT username, status FROM download_requests "
            "WHERE track_id = 't1' ORDER BY rank"
        ).fetchall()

    statuses = {row["username"]: row["status"] for row in rows}
    assert statuses["Wolfring"] == "superseded"
    assert statuses["lifelooop"] == "ready_for_review"
    assert statuses["CDM-Addicted"] == "superseded"


def test_poll_downloads_never_calls_input(tmp_path, monkeypatch):
    # poll_downloads() must be safe to run unattended — assert it takes
    # no interactive path at all, even with a ready_for_review-eligible
    # completed upgrade, the Phase 3 locked-retry cycle (new-lock
    # detection, and a retry of an already-locked request), AND the
    # Phase 4 cascade (a rejection activating a shortlisted candidate,
    # landing in-progress) all in the same run.
    def fail_if_called(prompt=""):
        raise AssertionError("poll_downloads() must never call input()")

    monkeypatch.setattr("builtins.input", fail_if_called)

    service = make_service(
        tmp_path,
        {
            "settled-1": "Completed, Succeeded",
            "upgrade-1": "Completed, Succeeded",
            "failing-1": "Errored",
            "progress-1": "InProgress",
            "newly-locked-1": "Completed, Rejected",
            "retry-1": "InProgress",
            "cascade-active-1": "Completed, Rejected",
            "cascade-new-2": "InProgress",
        },
        exceptions={
            "newly-locked-1": "Transfer rejected: File not shared.",
            "cascade-active-1": "Transfer rejected: File not shared.",
        },
        retry_results={
            "already-locked.mp3": "retry-1",
            "cascade-rank2.flac": "cascade-new-2",
        },
    )
    seed_pending_request(service, "settled-1", track_id="s1", role="settled")
    seed_pending_request(service, "upgrade-1", track_id="u1", role="upgrade")
    seed_pending_request(service, "failing-1", track_id="f1", role="settled")
    seed_pending_request(service, "progress-1", track_id="p1", role="settled")
    seed_pending_request(
        service, "newly-locked-1", track_id="nl1", role="upgrade",
    )
    seed_pending_request(
        service,
        "already-locked-1",
        track_id="al1",
        role="upgrade",
        status="locked",
        filename="already-locked.mp3",
    )
    seed_pending_request(
        service, "cascade-active-1", track_id="cs1", role="upgrade",
        status="queued", rank=1, username="peerX",
        filename="cascade-rank1.flac", size=1_000,
    )
    seed_pending_request(
        service, None, track_id="cs1", role="upgrade",
        status="shortlisted", rank=2, username="peerY",
        filename="cascade-rank2.flac", size=2_000,
    )

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    # progress-1, plus the cascaded rank-2 candidate landing in-progress.
    assert counts["downloading"] == 2
    assert counts["ready_for_review"] == 1
    # cascade-active-1 (nothing shortlisted for it beyond rank 2, which
    # got activated) and newly-locked-1 (no shortlist at all) — the
    # already-locked-1 row moved on to 'downloading' via its own retry.
    assert counts["locked"] == 2
    assert counts["shortlisted"] == 0

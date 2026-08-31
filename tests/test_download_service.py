from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.soulseek_review_candidate import SoulseekReviewCandidate
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.soulseek.client import SoulseekDownloadError, TransferStatus
from seeker.soulseek.download_service import (
    DownloadService,
    NoDestinationConfiguredError,
    PlaylistNotFoundError,
    ReviewCandidateMissingSizeError,
    ReviewCandidateNotFoundError,
    _build_search_query,
)


def test_single_source_of_truth_for_recognized_rejection_patterns():
    # Guards against the exact drift pattern this codebase has hit
    # before (matching.py, AUDIO_EXTENSIONS): the rejection-pattern
    # constant/classifier used to live in download_service.py as
    # LOCK_REJECTION_PATTERNS/_is_lock_rejection — now moved down to
    # client.py (below download_service.py in the layering) as
    # RECOGNIZED_REJECTION_PATTERNS/is_recognized_rejection, with
    # download_service.py importing it rather than keeping a second
    # copy that could silently diverge.
    import seeker.soulseek.download_service as download_service_module
    from seeker.soulseek.client import is_recognized_rejection

    assert not hasattr(download_service_module, "LOCK_REJECTION_PATTERNS")
    assert not hasattr(download_service_module, "_is_lock_rejection")
    assert (
        download_service_module.is_recognized_rejection
        is is_recognized_rejection
    )


def test_soulseek_property_raises_clear_error_when_client_is_none(tmp_path):
    # Step 8: Application.download_service now constructs DownloadService
    # with soulseek_client=None when SoulSeek isn't configured, rather
    # than making construction itself impossible — methods that never
    # touch SoulSeek (set_destination, get_review_candidates, ...) must
    # stay usable. Anything that DOES need it raises a clear error at
    # the point of actual use instead.
    service = make_service(tmp_path, states={}, get_config=None)
    service._soulseek_client = None

    with pytest.raises(RuntimeError, match="SoulSeek is not configured"):
        service.soulseek


def test_set_destination_works_without_soulseek_configured(tmp_path):
    # The real gap this was built to fix: a user who skipped the
    # wizard's optional SoulSeek step must still be able to set
    # playlist destinations via Settings.
    service = make_service(tmp_path, states={})
    service._soulseek_client = None

    lib_root = tmp_path / "music"
    lib_root.mkdir()

    with service.database.transaction() as connection:
        service.locations.add(
            LibraryLocation(
                name="Main", path=str(lib_root), added_at="2026-01-01"
            ),
            connection,
        )
        service.playlists.save(
            Playlist(id="p1", name="Test", track_count=0), connection,
        )

    service.set_destination("Test", "Main", "DnB")  # must not raise

    with service.database.transaction() as connection:
        playlist = service.playlists.get_by_name("Test", connection)

    assert playlist.download_subfolder == "DnB"


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
            progress: dict[str, tuple[int | None, int | None]]
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
        # Keyed by transfer_id -> (bytes_transferred, size). Missing
        # entries default to (None, None) — most existing tests don't
        # care about progress at all, only the state transition.
        self.progress = progress or {}
        self.get_download_status_calls: list[tuple[str, str]] = []

    def search(self, query: str) -> list[SoulseekFile]:
        self.search_calls.append(query)

        result = self.search_results.get(query)

        if isinstance(result, Exception):
            raise result

        return result or []

    def get_download_status(
            self, username: str, transfer_id: str,
    ) -> TransferStatus:
        self.get_download_status_calls.append((username, transfer_id))
        bytes_transferred, size = self.progress.get(
            transfer_id, (None, None)
        )

        return TransferStatus(
            state=self.states[transfer_id],
            bytes_transferred=bytes_transferred,
            size=size,
        )

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
        progress: dict[str, tuple[int | None, int | None]] | None = None,
        get_config=None,
) -> DownloadService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return DownloadService(
        database,
        FakeSoulseekClient(
            states, exceptions, retry_results, search_results, progress,
        ),
        PlaylistRepository(database),
        TrackRepository(database),
        LibraryLocationRepository(database),
        DownloadRequestRepository(database),
        TrackMatchRepository(database),
        LocalFileRepository(database),
        SoulseekReviewCandidateRepository(database),
        slskd_download_dir=None,
        get_config=get_config,
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
        requested_at: str | None = None,
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
                requested_at=(
                    requested_at
                    or datetime.now(timezone.utc).isoformat()
                ),
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


def test_download_playlist_skips_track_with_existing_active_request(
        tmp_path,
):
    # Real bug, found live (2026-08-27): re-running `seeker download`
    # against the real "Test" playlist while an earlier request for the
    # same track was still 'locked' created a SECOND, otherwise-identical
    # download_requests row (same track/role/rank/username/filename,
    # differing only in id and requested_at) instead of recognizing the
    # existing attempt. download_playlist() must skip a track that
    # already has any active (non-terminal) request rather than
    # re-searching and re-requesting it.
    service = make_service(tmp_path, states={})
    _seed_single_unmatched_track(
        service,
        tmp_path,
        "jade-venom-track",
        "Jade Venom",
        "Scared Now? - DIVERGENCE VI",
    )
    seed_pending_request(
        service,
        transfer_id="old-transfer-1",
        track_id="jade-venom-track",
        role="upgrade",
        status="locked",
        filename=(
            "Music (unsorted)\\Labels\\Eatbrain [FLAC]\\"
            "01. Jade Venom - Scared Now (DIVERGENCE VI).flac"
        ),
        username="ofoijacussa",
    )

    result = service.download_playlist("Test")

    assert result["requested"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    # The guard fires before ever searching or requesting again.
    assert service.soulseek.search_calls == []
    assert service.soulseek.request_download_calls == []

    with service.database.transaction() as connection:
        rows = connection.execute(
            "SELECT id, status FROM download_requests "
            "WHERE track_id = 'jade-venom-track'"
        ).fetchall()

    # Still exactly one row — no duplicate created.
    assert len(rows) == 1
    assert rows[0]["status"] == "locked"


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


def test_download_playlist_resolves_threshold_from_config_end_to_end(
        tmp_path,
):
    # Step 8's editable thresholds — same real Prdk data/query as the
    # needs_review test above (default: needs_review only, 70.4 < 90).
    # Proves the actual service-layer wiring, not just select_downloads'
    # own override parameter in isolation: a config value set (mirroring
    # what Settings does via Application._config_store), no explicit
    # override passed to download_playlist() itself, and the real
    # candidate moves from needs_review into a real requested download.
    prdk_candidate = make_soulseek_file(
        username="musicmasterrdjpool",
        filename=(
            "DJPOOLS\\2026\\MONTHS\\FEB\\20\\The Mash Up 20 FEB\\"
            "Prdk - One More Night (Clean) 4A 87.mp3"
        ),
        extension="mp3",
        size=9_251_601,
        # Practical (unlike the real 67_376 in the needs_review test) —
        # this test is about threshold resolution, not queue-length
        # practicality, so keep every other variable simple.
        queue_length=2,
        upload_speed=143_109,
        has_free_upload_slot=False,
        length=227,
        bit_rate=320,
        is_variable_bitrate=False,
    )

    prdk_query = "Prdk ONE MORE NIGHT"
    config_state = SeekerConfig()

    service = make_service(
        tmp_path,
        states={},
        search_results={prdk_query: [prdk_candidate]},
        get_config=lambda: config_state,
    )
    _seed_single_unmatched_track(
        service, tmp_path, "prdk-track", "Prdk", "ONE MORE NIGHT"
    )

    result_before = service.download_playlist("Test")

    assert result_before["requested"] == 0
    assert result_before["skipped"] == 1
    assert service.soulseek.request_download_calls == []

    # Settings-equivalent action: lower the config threshold below the
    # real 70.4 score, without reconstructing DownloadService.
    config_state = replace(config_state, auto_match_threshold=70.0)

    result_after = service.download_playlist("Test")

    assert result_after["requested"] == 1
    assert result_after["skipped"] == 0
    assert len(service.soulseek.request_download_calls) == 1
    assert service.soulseek.request_download_calls[0][1] == (
        prdk_candidate.filename
    )


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


def seed_review_candidate(
        service: DownloadService,
        track_id: str = "t1",
        username: str = "musicmasterrdjpool",
        filename: str = "Prdk - One More Night (Clean) 4A 87.mp3",
        score: float = 70.4,
        size: int | None = 2_000_000,
) -> None:
    with service.database.transaction() as connection:
        existing_track = service.tracks.get_by_id(track_id, connection)

        if existing_track is None:
            service.tracks.save(
                Track(
                    id=track_id, title="ONE MORE NIGHT", artist="Prdk",
                    album="Album", duration_ms=200_000,
                ),
                connection,
            )

        service.soulseek_review_candidates.upsert(
            SoulseekReviewCandidate(
                track_id=track_id,
                username=username,
                filename=filename,
                score=score,
                quality_descriptor="mp3",
                found_at="2026-01-01T00:00:00+00:00",
                size=size,
            ),
            connection,
        )


def test_confirm_review_candidate_requests_settled_download_and_clears_row(
        tmp_path,
):
    service = make_service(tmp_path, states={})
    seed_review_candidate(service, track_id="t1", size=2_000_000)

    service.confirm_review_candidate("t1")

    assert service.soulseek.request_download_calls == [
        (
            "musicmasterrdjpool",
            "Prdk - One More Night (Clean) 4A 87.mp3",
            2_000_000,
        ),
    ]

    with service.database.transaction() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM soulseek_review_candidates"
        ).fetchone()[0]
        row = connection.execute(
            "SELECT role, status, transfer_id, size, format "
            "FROM download_requests WHERE track_id = 't1'"
        ).fetchone()

    # Cleared immediately once the request was made — not waiting for
    # the download to finish.
    assert remaining == 0
    assert row["role"] == "settled"
    assert row["status"] == "queued"
    assert row["transfer_id"] is not None
    assert row["size"] == 2_000_000
    assert row["format"] == "mp3"


def test_confirm_review_candidate_locked_rejection_uses_existing_classification(
        tmp_path,
):
    # confirm_review_candidate() itself does no special-casing for
    # rejections — the resulting row goes through the exact same
    # poll_downloads() classification as any other request. This is the
    # scenario item 26's broadened classification exists for:
    # find_best_needs_review_candidate never filters on lock status, so
    # a confirmed candidate genuinely can be locked.
    service = make_service(
        tmp_path,
        states={"transfer-1": "Completed, Rejected"},
        exceptions={"transfer-1": "Transfer rejected: File not shared."},
        retry_results={
            "Prdk - One More Night (Clean) 4A 87.mp3": "transfer-1",
        },
    )
    seed_review_candidate(service, track_id="t1", size=2_000_000)

    service.confirm_review_candidate("t1")
    counts = service.poll_downloads()

    assert counts["failed"] == 0
    assert get_status(service, "transfer-1") == "locked"


def test_reject_review_candidate_deletes_and_requests_nothing(tmp_path):
    service = make_service(tmp_path, states={})
    seed_review_candidate(service, track_id="t1", size=2_000_000)

    service.reject_review_candidate("t1")

    assert service.soulseek.request_download_calls == []

    with service.database.transaction() as connection:
        remaining_candidates = connection.execute(
            "SELECT COUNT(*) FROM soulseek_review_candidates"
        ).fetchone()[0]
        request_count = connection.execute(
            "SELECT COUNT(*) FROM download_requests"
        ).fetchone()[0]

    assert remaining_candidates == 0
    assert request_count == 0


def test_confirm_review_candidate_raises_when_no_candidate_found(tmp_path):
    service = make_service(tmp_path, states={})

    with pytest.raises(ReviewCandidateNotFoundError):
        service.confirm_review_candidate("missing-track")


def test_confirm_review_candidate_raises_for_legacy_row_without_size(
        tmp_path,
):
    # A row persisted before `size` existed on this table (item 26) —
    # must refuse rather than guess/default a size for request_download.
    service = make_service(tmp_path, states={})
    seed_review_candidate(service, track_id="t1", size=None)

    with pytest.raises(ReviewCandidateMissingSizeError):
        service.confirm_review_candidate("t1")

    assert service.soulseek.request_download_calls == []


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


def test_settled_completion_indexes_and_matches_the_downloaded_file(
        tmp_path,
):
    # Phase 1 fix: a plain, ordinary settled download previously left
    # the moved file completely invisible to the rest of the app — no
    # local_files row, no track_matches row — so the track stayed
    # NOT_FOUND on the Dashboard forever and get_unmatched_for_playlist
    # kept offering it up for re-download even though it was already on
    # disk. See CLAUDE.md roadmap item 45 / docs/HISTORY.md.
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    lib_root = tmp_path / "music"
    lib_root.mkdir()

    slskd_dir = tmp_path / "slskd_downloads"
    slskd_dir.mkdir()
    (slskd_dir / "Dom Dolla - Rhyme Dust.mp3").write_bytes(b"not real audio")

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

        playlists.save(
            Playlist(id="p1", name="Test", track_count=1), connection,
        )
        playlists.set_destination("p1", location.id, None, connection)

        tracks.save(
            Track(
                id="t1", title="Rhyme Dust", artist="Dom Dolla",
                album="Rhyme Dust", duration_ms=215_000,
            ),
            connection,
        )
        tracks.save_playlist_track("p1", "t1", connection)

        download_requests.add(
            DownloadRequest(
                track_id="t1",
                username="peer1",
                filename="Dom Dolla - Rhyme Dust.mp3",
                format="mp3",
                quality_descriptor="mp3",
                role="settled",
                status="downloading",
                transfer_id="tx-1",
                size=1_000,
                requested_at="2026-01-01",
            ),
            connection,
        )

    service = DownloadService(
        database,
        FakeSoulseekClient(states={"tx-1": "Completed, Succeeded"}),
        playlists, tracks, locations, download_requests, track_matches,
        local_files, SoulseekReviewCandidateRepository(database),
        str(slskd_dir),
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert counts.get("indexed") == 1
    assert counts.get("index_failed") is None

    with database.transaction() as connection:
        local_file = local_files.get_by_location_and_relative_path(
            location.id, "Dom Dolla - Rhyme Dust.mp3", connection,
        )
        assert local_file is not None

        match = track_matches.get_by_track_id("t1", connection)
        assert match is not None
        assert match.match_method == "auto"
        assert match.local_file_id == local_file.id
        assert match.score is not None

        unmatched = tracks.get_unmatched_for_playlist("p1", connection)
        assert unmatched == []


def test_settled_completion_moves_a_filename_with_glob_special_characters(
        tmp_path,
):
    # Real, live-found bug: _move_completed_file's rglob(basename) treats
    # the basename as a glob PATTERN, not a literal name. Real Soulseek
    # filenames routinely contain '[' ']' (release tags like
    # "[www.dj-promo.org]"), which fnmatch interprets as a character
    # class — an unescaped lookup silently finds nothing (empty list, no
    # error) and the file is never moved, staying stuck 'downloading'
    # forever. Reproduced live against a real completed transfer with
    # exactly this filename shape while verifying the Phase 1 indexing
    # fix end-to-end.
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    lib_root = tmp_path / "music"
    lib_root.mkdir()

    slskd_dir = tmp_path / "slskd_downloads" / "Some Release [FLAC]"
    slskd_dir.mkdir(parents=True)
    filename = "Artist - Title (Mix) [www.dj-promo.org].mp3"
    (slskd_dir / filename).write_bytes(b"not real audio")

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

        playlists.save(
            Playlist(id="p1", name="Test", track_count=1), connection,
        )
        playlists.set_destination("p1", location.id, None, connection)

        tracks.save(
            Track(
                id="t1", title="Title", artist="Artist",
                album="Album", duration_ms=200_000,
            ),
            connection,
        )
        tracks.save_playlist_track("p1", "t1", connection)

        download_requests.add(
            DownloadRequest(
                track_id="t1",
                username="peer1",
                filename=f"Some Release [FLAC]\\{filename}",
                format="mp3",
                quality_descriptor="mp3",
                role="settled",
                status="downloading",
                transfer_id="tx-1",
                size=1_000,
                requested_at="2026-01-01",
            ),
            connection,
        )

    service = DownloadService(
        database,
        FakeSoulseekClient(states={"tx-1": "Completed, Succeeded"}),
        playlists, tracks, locations, download_requests, track_matches,
        local_files, SoulseekReviewCandidateRepository(database),
        str(tmp_path / "slskd_downloads"),
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert (lib_root / filename).exists()

    with database.transaction() as connection:
        local_file = local_files.get_by_location_and_relative_path(
            location.id, filename, connection,
        )
        assert local_file is not None


# --- Default destination (roadmap item 6) ----------------------------------

def test_get_resolved_destination_none_when_nothing_configured(tmp_path):
    service = make_service(tmp_path, states={})

    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="Test", track_count=0), connection,
        )

    assert service.get_resolved_destination("Test") is None


def test_get_resolved_destination_raises_for_unknown_playlist(tmp_path):
    service = make_service(tmp_path, states={})

    with pytest.raises(PlaylistNotFoundError):
        service.get_resolved_destination("Nope")


def test_get_resolved_destination_resolves_via_the_default(tmp_path):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    lib_root = tmp_path / "music"
    lib_root.mkdir()

    locations = LibraryLocationRepository(database)
    playlists = PlaylistRepository(database)

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(name="Main", path=str(lib_root), added_at="2026-01-01"),
            connection,
        )
        location = locations.get_by_name("Main", connection)
        playlists.save(Playlist(id="p1", name="Test", track_count=0), connection)

    config = SeekerConfig(default_download_location_id=location.id)
    service = DownloadService(
        database,
        FakeSoulseekClient(states={}),
        playlists, TrackRepository(database), locations,
        DownloadRequestRepository(database), TrackMatchRepository(database),
        LocalFileRepository(database), SoulseekReviewCandidateRepository(database),
        slskd_download_dir=None,
        get_config=lambda: config,
    )

    resolved = service.get_resolved_destination("Test")

    assert resolved is not None
    resolved_location, subfolder = resolved
    assert resolved_location.name == "Main"
    assert subfolder == "Test"


def test_download_playlist_raises_interface_neutral_error_with_no_destination(
        tmp_path,
):
    # Shared by the CLI and the UI (roadmap item 6 §2) — must never
    # mention a shell command, since the UI can't be told to "run"
    # anything. The CLI appends its own command-line guidance
    # separately (see cli.py's own NoDestinationConfiguredError catch).
    service = make_service(tmp_path, states={})

    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="Test", track_count=0), connection,
        )

    with pytest.raises(NoDestinationConfiguredError) as excinfo:
        service.download_playlist("Test")

    message = str(excinfo.value)
    assert "seeker" not in message.lower()
    assert "run" not in message.lower()


def test_download_playlist_succeeds_with_only_a_default_destination_configured(
        tmp_path,
):
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    lib_root = tmp_path / "music"
    lib_root.mkdir()

    locations = LibraryLocationRepository(database)
    playlists = PlaylistRepository(database)

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(name="Main", path=str(lib_root), added_at="2026-01-01"),
            connection,
        )
        location = locations.get_by_name("Main", connection)
        playlists.save(Playlist(id="p1", name="Test", track_count=0), connection)
        # Deliberately NOT calling playlists.set_destination — only a
        # default is configured, nothing playlist-specific.

    config = SeekerConfig(default_download_location_id=location.id)
    service = DownloadService(
        database,
        FakeSoulseekClient(states={}),
        playlists, TrackRepository(database), locations,
        DownloadRequestRepository(database), TrackMatchRepository(database),
        LocalFileRepository(database), SoulseekReviewCandidateRepository(database),
        slskd_download_dir=None,
        get_config=lambda: config,
    )

    # No unmatched tracks seeded — this call only needs to get PAST the
    # destination guard without raising; it would have raised
    # NoDestinationConfiguredError before ever reaching the empty-track
    # loop if the default weren't being resolved.
    result = service.download_playlist("Test")

    assert result["requested"] == 0
    assert result["skipped"] == 0
    assert result["failed"] == 0


def _seed_default_destination_scenario(
        tmp_path,
        playlist_name: str,
        subfolder_per_playlist: bool,
        playlist_specific_location_name: str | None = None,
):
    """Shared setup for the default-destination file-placement tests
    below: one real completed settled download, a default location
    configured via SeekerConfig, and optionally a SECOND, playlist-
    specific location/destination to prove it still wins over the
    default when both are set.
    """
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    default_root = tmp_path / "default_music"
    default_root.mkdir()

    slskd_dir = tmp_path / "slskd_downloads"
    slskd_dir.mkdir()
    (slskd_dir / "Artist - Title.mp3").write_bytes(b"not real audio")

    locations = LibraryLocationRepository(database)
    playlists = PlaylistRepository(database)
    tracks = TrackRepository(database)

    with database.transaction() as connection:
        locations.add(
            LibraryLocation(
                name="Default", path=str(default_root), added_at="2026-01-01",
            ),
            connection,
        )
        default_location = locations.get_by_name("Default", connection)

        playlists.save(
            Playlist(id="p1", name=playlist_name, track_count=1), connection,
        )

        if playlist_specific_location_name is not None:
            specific_root = tmp_path / "specific_music"
            specific_root.mkdir()
            locations.add(
                LibraryLocation(
                    name=playlist_specific_location_name,
                    path=str(specific_root), added_at="2026-01-01",
                ),
                connection,
            )
            specific_location = locations.get_by_name(
                playlist_specific_location_name, connection,
            )
            playlists.set_destination(
                "p1", specific_location.id, None, connection,
            )

        tracks.save(
            Track(
                id="t1", title="Title", artist="Artist",
                album="Album", duration_ms=200_000,
            ),
            connection,
        )
        tracks.save_playlist_track("p1", "t1", connection)

        DownloadRequestRepository(database).add(
            DownloadRequest(
                track_id="t1",
                username="peer1",
                filename="Artist - Title.mp3",
                format="mp3",
                quality_descriptor="mp3",
                role="settled",
                status="downloading",
                transfer_id="tx-1",
                size=1_000,
                requested_at="2026-01-01",
            ),
            connection,
        )

    config = SeekerConfig(
        default_download_location_id=default_location.id,
        default_download_subfolder_per_playlist=subfolder_per_playlist,
    )
    service = DownloadService(
        database,
        FakeSoulseekClient(states={"tx-1": "Completed, Succeeded"}),
        playlists, tracks, locations, DownloadRequestRepository(database),
        TrackMatchRepository(database), LocalFileRepository(database),
        SoulseekReviewCandidateRepository(database),
        str(slskd_dir),
        get_config=lambda: config,
    )

    return service, default_root


def test_settled_completion_uses_default_destination_with_playlist_subfolder(
        tmp_path,
):
    service, default_root = _seed_default_destination_scenario(
        tmp_path, playlist_name="Test", subfolder_per_playlist=True,
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert (default_root / "Test" / "Artist - Title.mp3").exists()


def test_settled_completion_uses_default_destination_with_no_subfolder(
        tmp_path,
):
    service, default_root = _seed_default_destination_scenario(
        tmp_path, playlist_name="Test", subfolder_per_playlist=False,
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert (default_root / "Artist - Title.mp3").exists()
    assert not (default_root / "Test").exists()


def test_settled_completion_sanitizes_a_real_playlist_name_with_a_slash(
        tmp_path,
):
    # "240KM/H" is a real playlist name in this project's own
    # production database — a raw '/' in a subfolder name would
    # otherwise be silently interpreted as a path separator.
    service, default_root = _seed_default_destination_scenario(
        tmp_path, playlist_name="240KM/H", subfolder_per_playlist=True,
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert (default_root / "240KM-H" / "Artist - Title.mp3").exists()
    assert not (default_root / "240KM").exists()


def test_playlist_specific_destination_wins_over_the_default(tmp_path):
    service, default_root = _seed_default_destination_scenario(
        tmp_path, playlist_name="Test", subfolder_per_playlist=True,
        playlist_specific_location_name="Specific",
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    # Landed in the playlist-specific location, not the default one.
    assert not (default_root / "Test" / "Artist - Title.mp3").exists()

    with service.database.transaction() as connection:
        specific_location = service.locations.get_by_name(
            "Specific", connection,
        )

    assert (
        Path(specific_location.path) / "Artist - Title.mp3"
    ).exists()


def test_settled_completion_index_failure_still_counts_as_completed(
        tmp_path, monkeypatch,
):
    # An indexing/matching failure (e.g. a real file-read error) must
    # not undo the 'completed' status — the file genuinely did
    # download successfully — and must not raise out of poll_downloads
    # and abort the rest of the batch. Counted separately as
    # 'index_failed' so it's visible rather than silently swallowed.
    service = make_service(tmp_path, {"t1": "Completed, Succeeded"})
    seed_pending_request(service, "t1")

    fake_location = LibraryLocation(
        id=1, name="Main", path=str(tmp_path), added_at="2026-01-01"
    )
    monkeypatch.setattr(
        service,
        "_move_completed_file",
        lambda request: (fake_location, "missing-file-not-on-disk.mp3"),
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert counts.get("index_failed") == 1
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


def test_rejected_settled_role_with_lock_exception_routes_to_locked_not_failed(
        tmp_path,
):
    # Item 26 correction: lock-pattern classification applies regardless
    # of role, not just role=='upgrade'. The old scoping rested on the
    # premise that select_downloads() never assigns a locked candidate to
    # 'settled', so a settled-role rejection was "never expected to be
    # lock-related" — that stopped being universally true once
    # confirm_review_candidate could request a role='settled' download
    # for a human-confirmed needs-review candidate that was never
    # filtered on lock status at all (see item 26). This is the GENERAL
    # case, not specific to the new confirm-review feature — an ordinary
    # settled request hitting this same real rejection text must now
    # also retry instead of failing immediately.
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: File not shared."},
    )
    seed_pending_request(service, "t1", role="settled")

    counts = service.poll_downloads()

    assert counts["failed"] == 0
    assert counts["locked"] == 1
    assert get_status(service, "t1") == "locked"


def test_rejected_settled_role_with_other_reason_still_marks_failed(
        tmp_path,
):
    # The broadened classification isn't "every settled rejection
    # retries" — only a recognized rejection pattern does. Mirrors
    # test_rejected_upgrade_with_other_reason_still_marks_failed for the
    # settled role.
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: Too many requests."},
    )
    seed_pending_request(service, "t1", role="settled")

    counts = service.poll_downloads()

    assert counts["failed"] == 1
    assert counts["locked"] == 0
    assert get_status(service, "t1") == "failed"


def test_settled_role_rejection_does_not_trigger_upgrade_cascade(tmp_path):
    # The Phase 4 cascade stays role-specific even after broadening the
    # rejection classification itself — get_next_shortlisted() isn't
    # role-scoped, so calling the cascade for a settled rejection could
    # otherwise incorrectly activate an unrelated upgrade-role
    # shortlist entry for the same track.
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: File not shared."},
    )
    seed_pending_request(service, "t1", track_id="shared-track", role="settled")
    seed_pending_request(
        service, None, track_id="shared-track", role="upgrade",
        status="shortlisted", rank=2, filename="other-candidate.mp3",
        username="peer2",
    )

    service.poll_downloads()

    with service.database.transaction() as connection:
        shortlisted_status = connection.execute(
            "SELECT status FROM download_requests "
            "WHERE filename = 'other-candidate.mp3'"
        ).fetchone()["status"]

    assert shortlisted_status == "shortlisted"


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


def test_settled_role_locked_request_succeeds_on_retry_auto_moves_without_review(
        tmp_path,
):
    # Item 26 correction: a role='settled' row can now genuinely reach
    # 'locked' (via confirm_review_candidate — a needs-review candidate
    # is never filtered on lock status). Once such a retry succeeds, it
    # must auto-move into the library exactly like an ordinary settled
    # success — never through ready_for_review, which would demand a
    # SECOND human confirmation for a candidate that was already
    # confirmed once.
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    lib_root = tmp_path / "music"
    lib_root.mkdir()

    slskd_dir = tmp_path / "slskd_downloads"
    slskd_dir.mkdir()
    (slskd_dir / "Prdk - One More Night.mp3").write_bytes(b"real audio data")

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

        playlists.save(
            Playlist(id="p1", name="Test", track_count=1), connection,
        )
        playlists.set_destination("p1", location.id, None, connection)

        tracks.save(
            Track(
                id="t1", title="ONE MORE NIGHT", artist="Prdk",
                album="Album", duration_ms=200_000,
            ),
            connection,
        )
        tracks.save_playlist_track("p1", "t1", connection)

        download_requests.add(
            DownloadRequest(
                track_id="t1",
                username="musicmasterrdjpool",
                filename="Prdk - One More Night.mp3",
                format="mp3",
                quality_descriptor="mp3",
                role="settled",
                status="locked",
                transfer_id="old-1",
                size=1_000,
                requested_at="2026-01-01",
            ),
            connection,
        )

    service = DownloadService(
        database,
        FakeSoulseekClient(
            states={"new-1": "Completed, Succeeded"},
            retry_results={"Prdk - One More Night.mp3": "new-1"},
        ),
        playlists, tracks, locations, download_requests, track_matches,
        local_files, SoulseekReviewCandidateRepository(database),
        str(slskd_dir),
    )

    counts = service.poll_downloads()

    assert counts["completed"] == 1
    assert counts["failed"] == 0

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM download_requests WHERE track_id = 't1'"
        ).fetchone()

    assert row["status"] == "completed"
    assert (lib_root / "Prdk - One More Night.mp3").exists()
    assert _ready_for_review_count(service) == 0


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


def test_retry_loop_dedupes_stale_duplicate_locked_rows(tmp_path):
    # Real, live-observed shape (CLAUDE.md item 24 follow-up,
    # 2026-08-28): item 16's creation-time dedup guard only prevents
    # NEW duplicate rows going forward — rows already created before it
    # was fully effective (e.g. "Balron, Audio - Breach" ids 5/7/9,
    # 3 rows for the identical peer+file) get retried independently,
    # every cycle, against the same real peer, unless the retry loop
    # itself also dedupes. Only the most-recently-requested duplicate
    # should actually be retried; the rest become 'superseded'.
    service = make_service(
        tmp_path,
        states={"new-1": "InProgress"},
        retry_results={"Breach.flac": "new-1"},
    )
    seed_pending_request(
        service, "old-1", role="upgrade", status="locked",
        filename="Breach.flac", username="long25",
        requested_at="2026-08-27T13:15:47+00:00",
    )
    seed_pending_request(
        service, "old-2", role="upgrade", status="locked",
        filename="Breach.flac", username="long25",
        requested_at="2026-08-27T17:41:05+00:00",
    )

    counts = service.poll_downloads()

    # Only ONE real request_download call — for the more recent
    # duplicate — not one per stale row against the same real peer.
    assert service.soulseek.request_download_calls == [
        ("long25", "Breach.flac", 1_000_000),
    ]
    assert counts["locked"] == 0

    with service.database.transaction() as connection:
        rows = {
            row["transfer_id"]: row["status"]
            for row in connection.execute(
                "SELECT transfer_id, status FROM download_requests "
                "WHERE filename = 'Breach.flac'"
            ).fetchall()
        }

    assert rows["old-1"] == "superseded"
    assert rows["new-1"] == "downloading"


def test_retry_loop_never_collapses_distinct_candidates(tmp_path):
    # The exact case the dedup above must NOT touch: two genuinely
    # different real candidates for the same track (different peers) —
    # a legitimate Phase 4 shortlist shape, not a stale duplicate. Both
    # must be retried independently, and neither should be superseded
    # by this check.
    service = make_service(
        tmp_path,
        states={"new-a": "InProgress", "new-b": "InProgress"},
        retry_results={
            "candidate-a.flac": "new-a", "candidate-b.flac": "new-b",
        },
    )
    seed_pending_request(
        service, "old-a", role="upgrade", status="locked",
        filename="candidate-a.flac", username="peerA",
        requested_at="2026-08-28T10:00:00+00:00",
    )
    seed_pending_request(
        service, "old-b", role="upgrade", status="locked",
        filename="candidate-b.flac", username="peerB",
        requested_at="2026-08-28T10:00:00+00:00",
    )

    counts = service.poll_downloads()

    assert sorted(service.soulseek.request_download_calls) == [
        ("peerA", "candidate-a.flac", 1_000_000),
        ("peerB", "candidate-b.flac", 1_000_000),
    ]
    assert counts["locked"] == 0

    with service.database.transaction() as connection:
        statuses = [
            row["status"]
            for row in connection.execute(
                "SELECT status FROM download_requests"
            ).fetchall()
        ]

    assert "superseded" not in statuses


def test_retry_loop_single_locked_row_unaffected_by_dedup_check(tmp_path):
    # No duplicates at all — the new dedup-before-retry check must be a
    # complete no-op, matching the exact pre-existing Phase 3 contract
    # (test_locked_request_succeeds_on_retry_transitions_to_downloading
    # already covers the transition itself; this asserts the dedup
    # check specifically never touches a lone row's status).
    service = make_service(
        tmp_path,
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
            "SELECT status FROM download_requests "
            "WHERE filename = 'Dom Dolla - Rhyme Dust.mp3'"
        ).fetchone()

    assert row["status"] == "downloading"


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


def test_retry_locked_request_recognizes_real_peer_offline_rejection(
        tmp_path, monkeypatch, capsys,
):
    # Real, confirmed-live rejection shape (2026-08-28, the Balron/
    # long25 investigation): a peer-offline 404 straight off the
    # enqueue POST is now wrapped into SoulseekDownloadError by
    # request_download itself (see client.py's
    # RECOGNIZED_REJECTION_PATTERNS) — this simulates that fixed client
    # behavior at the service-layer boundary. Before the fix, this
    # exact message arrived as an unwrapped httpx.HTTPStatusError,
    # which this method's `except SoulseekDownloadError` couldn't
    # catch — it escaped to poll_downloads' outer per-request handler
    # and printed "Failed to retry locked ...". That escape is exactly
    # what this test asserts is now gone.
    service = make_service(
        tmp_path,
        states={},
        retry_results={
            "NeuroFunk26\\Balron, Audio - Breach.flac": SoulseekDownloadError(
                "slskd rejected the download of "
                "'NeuroFunk26\\Balron, Audio - Breach.flac' from "
                "'long25': User long25 appears to be offline"
            ),
        },
    )
    seed_pending_request(
        service, "old-transfer-1", track_id="t1", role="upgrade",
        status="locked", username="long25",
        filename="NeuroFunk26\\Balron, Audio - Breach.flac",
        size=37_691_256,
    )

    original = DownloadRequestRepository.update_transfer_id_and_status
    update_calls = []

    def spy(self, request_id, transfer_id, status, connection):
        update_calls.append((request_id, transfer_id, status))
        return original(self, request_id, transfer_id, status, connection)

    monkeypatch.setattr(
        DownloadRequestRepository, "update_transfer_id_and_status", spy,
    )

    counts = service.poll_downloads()

    output = capsys.readouterr().out
    # The designed, silent contract — not the accidental escape into
    # the outer per-request handler that printed this before the fix.
    assert "Failed to retry locked" not in output

    assert counts["failed"] == 0
    assert counts["locked"] == 1

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status, transfer_id FROM download_requests "
            "WHERE track_id = 't1'"
        ).fetchone()

    assert row["status"] == "locked"
    # The retry was rejected synchronously — no new transfer_id was
    # ever issued, so there's nothing new to persist. This is a clean
    # no-op via `except SoulseekDownloadError: return`, confirmed
    # directly: update_transfer_id_and_status is never called for this
    # row (unlike the async-rejection retry case, where a real new
    # transfer_id genuinely does get recorded — see
    # test_locked_request_rejected_again_stays_locked_not_failed).
    assert row["transfer_id"] == "old-transfer-1"
    assert update_calls == []


def test_cascade_activation_recognizes_peer_offline_and_locks_not_stuck(
        tmp_path, capsys,
):
    # The real bug case: before the fix, a peer-offline 404 during
    # cascade activation propagated a bare httpx.HTTPStatusError out of
    # _activate_shortlisted_entry, up through _cascade_upgrade, into
    # poll_downloads' main-loop outer per-request handler — leaving the
    # row stuck at 'shortlisted' forever, never touched by mark_status,
    # since the classification code (is_recognized_rejection) was never
    # reached at all. This is the path that was never exercised live —
    # simulates the fixed request_download's wrapped SoulseekDownloadError
    # using the exact real message confirmed live (2026-08-28).
    service = make_service(
        tmp_path,
        states={"active-1": "Completed, Rejected"},
        exceptions={"active-1": "Transfer rejected: File not shared."},
        retry_results={
            "NeuroFunk26\\Balron, Audio - Breach.flac": SoulseekDownloadError(
                "slskd rejected the download of "
                "'NeuroFunk26\\Balron, Audio - Breach.flac' from "
                "'long25': User long25 appears to be offline"
            ),
        },
    )

    seed_pending_request(
        service, "active-1", track_id="t1", role="upgrade",
        status="queued", rank=1, username="peerX",
        filename="cascade-rank1.flac", size=1_000,
    )
    seed_pending_request(
        service, None, track_id="t1", role="upgrade",
        status="shortlisted", rank=2, username="long25",
        filename="NeuroFunk26\\Balron, Audio - Breach.flac",
        size=37_691_256,
    )

    counts = service.poll_downloads()

    output = capsys.readouterr().out
    assert "Failed to poll" not in output

    assert counts["failed"] == 0
    # Both rank 1 (async "not shared" rejection) and the cascaded rank 2
    # (sync "appears to be offline" rejection) correctly classify as
    # 'locked', not 'failed' and not stuck at 'shortlisted'.
    assert counts["locked"] == 2

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT status FROM download_requests "
            "WHERE filename LIKE '%Balron%'"
        ).fetchone()

    assert row["status"] == "locked"


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


def test_update_progress_writes_progress_without_disturbing_other_columns(
        tmp_path,
):
    # Repository-level, direct — mirrors update_analysis's own
    # non-disturbance guarantee (a routine poll must not risk touching
    # any unrelated column on the row).
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    repository = DownloadRequestRepository(database)

    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO tracks (id, title, artist, album, duration_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            ("track-1", "Rhyme Dust", "MK, Dom Dolla", "Rhyme Dust", 215_000),
        )
        repository.add(
            DownloadRequest(
                track_id="track-1",
                username="real-peer",
                filename="Rhyme Dust.flac",
                format="flac",
                quality_descriptor="flac 1000kbps",
                role="settled",
                status="downloading",
                transfer_id="real-transfer-id",
                size=52_428_800,
                requested_at="2026-08-28T00:00:00+00:00",
            ),
            connection,
        )
        request_id = connection.execute(
            "SELECT id FROM download_requests WHERE track_id = 'track-1'"
        ).fetchone()[0]

    with database.transaction() as connection:
        repository.update_progress(
            request_id, 26_214_400, 52_428_800, connection,
        )

    with database.transaction() as connection:
        row = repository.get_by_id(request_id, connection)

    assert row is not None
    assert row.bytes_transferred == 26_214_400
    assert row.total_bytes == 52_428_800
    # Every other column is untouched.
    assert row.username == "real-peer"
    assert row.filename == "Rhyme Dust.flac"
    assert row.status == "downloading"
    assert row.transfer_id == "real-transfer-id"
    assert row.size == 52_428_800
    assert row.role == "settled"


def test_poll_downloads_updates_progress_for_in_flight_request(tmp_path):
    # State stays "downloading" (still InProgress) across this poll, but
    # bytes move every poll regardless of whether status transitions —
    # progress must update unconditionally alongside the state check.
    service = make_service(
        tmp_path,
        {"t1": "InProgress"},
        progress={"t1": (26_214_400, 52_428_800)},
    )
    seed_pending_request(service, "t1", size=52_428_800)

    service.poll_downloads()

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT bytes_transferred, total_bytes FROM download_requests "
            "WHERE transfer_id = 't1'"
        ).fetchone()

    assert row["bytes_transferred"] == 26_214_400
    assert row["total_bytes"] == 52_428_800


def test_poll_downloads_settled_completion_reaches_total_equals_transferred(
        tmp_path, monkeypatch,
):
    # Real, confirmed-live edge case: a genuinely completed transfer
    # reports bytes_transferred == total_bytes (see
    # soulseek/client.py's TransferStatus docstring) — assert that's
    # what actually lands in the DB once poll_downloads processes it,
    # not just that the client parses it correctly in isolation.
    monkeypatch.setattr(
        "seeker.soulseek.download_service.DownloadService._move_completed_file",
        lambda self, request: (
            LibraryLocation(id=1, name="main", path="/music", added_at="x"),
            "song.flac",
        ),
    )

    service = make_service(
        tmp_path,
        {"t1": "Completed, Succeeded"},
        progress={"t1": (79_776_980, 79_776_980)},
    )
    seed_pending_request(service, "t1", size=79_776_980)

    service.poll_downloads()

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT bytes_transferred, total_bytes FROM download_requests "
            "WHERE transfer_id = 't1'"
        ).fetchone()

    assert row["bytes_transferred"] == 79_776_980
    assert row["total_bytes"] == 79_776_980
    assert row["bytes_transferred"] == row["total_bytes"]


def test_poll_downloads_rejection_leaves_progress_unset_not_zeroed(
        tmp_path,
):
    # Real, confirmed-live edge case: a locked file rejected before any
    # bytes moved reports bytes_transferred=0 in slskd's own payload —
    # but recording that would misleadingly imply a real 0%-complete
    # attempt. progress fields must stay NULL, never persisted as 0.
    service = make_service(
        tmp_path,
        {"t1": "Completed, Rejected"},
        exceptions={"t1": "Transfer rejected: File not shared."},
        progress={"t1": (0, 55_144_573)},
    )
    seed_pending_request(
        service, "t1", role="upgrade", size=55_144_573,
    )

    service.poll_downloads()

    with service.database.transaction() as connection:
        row = connection.execute(
            "SELECT bytes_transferred, total_bytes FROM download_requests "
            "WHERE transfer_id = 't1'"
        ).fetchone()

    assert row["bytes_transferred"] is None
    assert row["total_bytes"] is None


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


def _get_ready_for_review_request_id(service: DownloadService) -> int:
    request = service._get_ready_for_review()[0]
    assert request.id is not None
    return request.id


def test_get_upgrade_review_details_resolves_current_file_and_old_path(
        tmp_path,
):
    # The extracted read-only accessor both the CLI wrapper and the
    # future Review screen build their display/prompts from.
    service, lib_root = _seed_upgrade_scenario(tmp_path)
    request_id = _get_ready_for_review_request_id(service)

    details = service.get_upgrade_review_details(request_id)

    assert details is not None
    assert details.track.id == "t1"
    assert details.current_description == "mp3"
    assert details.old_file_path == str(lib_root / "old.mp3")


def test_get_upgrade_review_details_none_for_missing_request(tmp_path):
    service = make_service(tmp_path, {})

    assert service.get_upgrade_review_details(999) is None


def test_get_pending_upgrade_reviews_lists_ready_for_review_details(tmp_path):
    # The Review screen's listing call for its upgrade-confirmation
    # section (Step 6 §2) — same resolution get_upgrade_review_details
    # does per-row, just fetching every ready_for_review row up front.
    service, lib_root = _seed_upgrade_scenario(tmp_path)

    results = service.get_pending_upgrade_reviews()

    assert len(results) == 1
    assert results[0].track.id == "t1"
    assert results[0].current_description == "mp3"
    assert results[0].old_file_path == str(lib_root / "old.mp3")


def test_get_pending_upgrade_reviews_empty_when_nothing_ready(tmp_path):
    service = make_service(tmp_path, {})

    assert service.get_pending_upgrade_reviews() == []


def test_apply_upgrade_decision_replace_and_delete_old(tmp_path):
    # §1's explicit-decision function, called directly with both
    # booleans already resolved — no input() anywhere in this path.
    service, lib_root = _seed_upgrade_scenario(tmp_path)
    request_id = _get_ready_for_review_request_id(service)

    message = service.apply_upgrade_decision(
        request_id, replace=True, delete_old=True,
    )

    assert message is not None
    assert "Replaced with" in message
    assert "Deleted" in message
    assert not (lib_root / "old.mp3").exists()
    assert (lib_root / "Dom Dolla - Rhyme Dust.flac").exists()
    assert _ready_for_review_count(service) == 0


def test_apply_upgrade_decision_replace_and_keep_old(tmp_path):
    service, lib_root = _seed_upgrade_scenario(tmp_path)
    request_id = _get_ready_for_review_request_id(service)

    message = service.apply_upgrade_decision(
        request_id, replace=True, delete_old=False,
    )

    assert message is not None
    assert "Replaced with" in message
    assert "Leaving" in message
    assert (lib_root / "old.mp3").exists()
    assert (lib_root / "Dom Dolla - Rhyme Dust.flac").exists()
    assert _ready_for_review_count(service) == 0


def test_apply_upgrade_decision_decline_is_a_no_op(tmp_path):
    service, lib_root = _seed_upgrade_scenario(tmp_path)
    request_id = _get_ready_for_review_request_id(service)

    message = service.apply_upgrade_decision(request_id, replace=False)

    assert message is None
    assert _ready_for_review_count(service) == 1
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


def test_poll_downloads_never_calls_update_progress_for_never_transferring_requests(
        tmp_path, monkeypatch,
):
    # locked/shortlisted/superseded requests were never actually
    # transferring — same style as the existing input() guardrail
    # above, but asserting update_progress specifically is never
    # attempted for any of these three statuses, even when a locked
    # request goes through its own retry cycle and a shortlisted one
    # gets cascade-activated in the same run.
    service = make_service(
        tmp_path,
        {
            "in-progress-1": "InProgress",
            "cascade-active-1": "Completed, Rejected",
        },
        exceptions={
            "cascade-active-1": "Transfer rejected: File not shared.",
        },
        retry_results={"already-locked.mp3": Exception("still locked")},
        progress={"in-progress-1": (500, 1_000)},
    )

    seed_pending_request(
        service, "in-progress-1", track_id="p1", role="settled",
    )
    seed_pending_request(
        service, "already-locked-1", track_id="al1", role="upgrade",
        status="locked", filename="already-locked.mp3",
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
    seed_pending_request(
        service, "superseded-1", track_id="sup1", role="upgrade",
        status="superseded", filename="superseded.flac",
    )

    with service.database.transaction() as connection:
        locked_id = service.download_requests.get_locked(connection)[0].id
        shortlisted_id = service.download_requests.get_shortlisted(
            connection
        )[0].id
        superseded_id = connection.execute(
            "SELECT id FROM download_requests WHERE track_id = 'sup1'"
        ).fetchone()[0]

    forbidden_ids = {locked_id, shortlisted_id, superseded_id}

    original_update_progress = DownloadRequestRepository.update_progress

    def guarded_update_progress(
            self, request_id, bytes_transferred, total_bytes, connection,
    ):
        assert request_id not in forbidden_ids, (
            f"update_progress must never be attempted for a locked/"
            f"shortlisted/superseded request (id={request_id})"
        )
        return original_update_progress(
            self, request_id, bytes_transferred, total_bytes, connection,
        )

    monkeypatch.setattr(
        DownloadRequestRepository, "update_progress", guarded_update_progress,
    )

    service.poll_downloads()

    with service.database.transaction() as connection:
        in_progress_row = connection.execute(
            "SELECT bytes_transferred, total_bytes FROM download_requests "
            "WHERE transfer_id = 'in-progress-1'"
        ).fetchone()

    # The one genuinely in-flight request still got its real update.
    assert in_progress_row["bytes_transferred"] == 500
    assert in_progress_row["total_bytes"] == 1_000

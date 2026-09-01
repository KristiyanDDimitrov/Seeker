from datetime import datetime, timezone

import numpy as np
import pytest
import soundfile as sf

from seeker.audio_fingerprint import FingerprintingUnavailableError
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
)
from seeker.database.repositories.local_file_repository import (
    LocalFileRepository,
)
from seeker.database.repositories.track_match_repository import (
    TrackMatchRepository,
)
from seeker.database.repositories.track_repository import TrackRepository
from seeker.library.duplicate_service import (
    DuplicateService,
    LibraryLocationNotFoundError,
    _cluster_by_similarity,
    _quality_sort_key,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch
from seeker.soulseek.quality import LocalFileQuality


def make_database(tmp_path) -> Database:
    database = Database(tmp_path / "seeker.db")
    database.initialize()
    return database


def register_location(database: Database, path) -> LibraryLocation:
    repo = LibraryLocationRepository(database)
    location = LibraryLocation(
        name="Main", path=str(path),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with database.transaction() as connection:
        repo.add(location, connection)
        return repo.get_by_name("Main", connection)


def add_local_file(
        database: Database,
        location: LibraryLocation,
        relative_path: str,
        format: str,
        duration_ms: int,
) -> LocalFile:
    repo = LocalFileRepository(database)
    local_file = LocalFile(
        location_id=location.id,
        relative_path=relative_path,
        filename=relative_path,
        format=format,
        size_bytes=1000,
        mtime=0.0,
        scanned_at=datetime.now(timezone.utc).isoformat(),
        duration_ms=duration_ms,
    )
    with database.transaction() as connection:
        repo.upsert(local_file, connection)
        return repo.get_by_location_and_relative_path(
            location.id, relative_path, connection,
        )


def _write_tone(path, frequency: float, duration_seconds: float = 3.0):
    sample_rate = 44_100
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
    samples = (np.sin(2 * np.pi * frequency * t) * 0.3).astype(np.float32)
    sf.write(str(path), samples, sample_rate)


def make_service(database: Database) -> DuplicateService:
    return DuplicateService(
        database,
        LibraryLocationRepository(database),
        LocalFileRepository(database),
        TrackMatchRepository(database),
    )


# --- Real end-to-end: real generated audio, real libchromaprint -----------

def test_compute_and_find_duplicates_real_audio_end_to_end(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    # Two real copies of the identical tone (a real duplicate pair) plus
    # one clearly different tone (must not be grouped with them).
    _write_tone(music_dir / "dupe_a.wav", frequency=440.0)
    _write_tone(music_dir / "dupe_b.wav", frequency=440.0)
    _write_tone(music_dir / "unique.wav", frequency=1200.0)

    add_local_file(database, location, "dupe_a.wav", "wav", 3000)
    add_local_file(database, location, "dupe_b.wav", "wav", 3000)
    add_local_file(database, location, "unique.wav", "wav", 3000)

    service = make_service(database)

    result = service.compute_fingerprints("Main")
    assert result["computed"] == 3
    assert result["failed"] == 0

    groups = service.find_duplicate_groups("Main")

    assert len(groups) == 1
    filenames = {f.local_file.filename for f in groups[0].files}
    assert filenames == {"dupe_a.wav", "dupe_b.wav"}
    assert groups[0].similarity > 0.95


def test_compute_fingerprints_skips_already_computed_files(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    _write_tone(music_dir / "a.wav", frequency=440.0)
    add_local_file(database, location, "a.wav", "wav", 3000)

    service = make_service(database)
    first = service.compute_fingerprints("Main")
    assert first["computed"] == 1

    second = service.compute_fingerprints("Main")
    assert second["computed"] == 0
    assert second["skipped_already_computed"] == 1


def test_compute_fingerprints_force_recomputes(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    _write_tone(music_dir / "a.wav", frequency=440.0)
    add_local_file(database, location, "a.wav", "wav", 3000)

    service = make_service(database)
    service.compute_fingerprints("Main")

    result = service.compute_fingerprints("Main", force=True)
    assert result["computed"] == 1
    assert result["skipped_already_computed"] == 0


def test_compute_fingerprints_unknown_location_raises(tmp_path):
    database = make_database(tmp_path)
    service = make_service(database)

    with pytest.raises(LibraryLocationNotFoundError):
        service.compute_fingerprints("Nonexistent")


def test_find_duplicate_groups_unknown_location_raises(tmp_path):
    database = make_database(tmp_path)
    service = make_service(database)

    with pytest.raises(LibraryLocationNotFoundError):
        service.find_duplicate_groups("Nonexistent")


def test_find_duplicate_groups_excludes_files_with_no_fingerprint_yet(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    _write_tone(music_dir / "a.wav", frequency=440.0)
    add_local_file(database, location, "a.wav", "wav", 3000)

    service = make_service(database)
    # Never called compute_fingerprints() — every file's fingerprint is
    # still NULL, a completely normal, expected state.

    groups = service.find_duplicate_groups("Main")

    assert groups == []


def test_compute_fingerprints_raises_when_chromaprint_unavailable(
        tmp_path, monkeypatch,
):
    import seeker.library.duplicate_service as duplicate_service_module

    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    register_location(database, music_dir)

    monkeypatch.setattr(
        duplicate_service_module, "fingerprinting_is_available", lambda: False,
    )

    service = make_service(database)

    with pytest.raises(FingerprintingUnavailableError):
        service.compute_fingerprints("Main")


# --- Pure clustering/scoring logic: synthetic data, no real audio ---------

def _fake_local_file(id: int, fingerprint: str, duration_ms: int) -> LocalFile:
    return LocalFile(
        id=id,
        location_id=1,
        relative_path=f"file{id}.mp3",
        filename=f"file{id}.mp3",
        format="mp3",
        size_bytes=1000,
        mtime=0.0,
        scanned_at="2026-01-01T00:00:00+00:00",
        duration_ms=duration_ms,
        fingerprint=fingerprint,
    )


def test_cluster_by_similarity_groups_files_within_duration_tolerance():
    # Real, pure similarity_from_decoded() underneath — no monkeypatch
    # needed. Files 1/2 differ by a single bit across 96 total bits
    # (>99% similar, above the real threshold); file 3 is the exact
    # bitwise complement of file 1 (0% similar).
    files = [
        _fake_local_file(1, "AAA", duration_ms=200_000),
        _fake_local_file(2, "AAB", duration_ms=200_500),
        _fake_local_file(3, "ZZZ", duration_ms=200_100),
    ]
    decoded = {
        1: np.array([0, 0, 0], dtype=np.uint32),
        2: np.array([0, 0, 1], dtype=np.uint32),
        3: np.array([0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF], dtype=np.uint32),
    }

    clusters = _cluster_by_similarity(files, decoded)

    assert len(clusters) == 1
    assert {f.id for f in clusters[0]} == {1, 2}


def test_cluster_by_similarity_respects_duration_tolerance_pre_filter():
    # Identical decoded fingerprints (100% similarity) but a genuinely
    # different duration must still block clustering — the cheap
    # pre-filter exists precisely to catch this case before the real
    # (here, trivially matching) comparison ever runs.
    files = [
        _fake_local_file(1, "AAA", duration_ms=200_000),
        _fake_local_file(2, "AAA", duration_ms=400_000),
    ]
    decoded = {
        1: np.array([0, 1, 2], dtype=np.uint32),
        2: np.array([0, 1, 2], dtype=np.uint32),
    }

    clusters = _cluster_by_similarity(files, decoded)

    assert clusters == []


def test_quality_sort_key_prefers_lossless_then_higher_bitrate():
    lossless = LocalFileQuality(
        tier=2, bitrate_kbps=1000, bit_depth=16, sample_rate=44_100,
        clipping_ratio=0.0, integrated_loudness_lufs=None,
    )
    lossy_high = LocalFileQuality(
        tier=1, bitrate_kbps=320, bit_depth=None, sample_rate=44_100,
        clipping_ratio=0.0, integrated_loudness_lufs=None,
    )
    lossy_low = LocalFileQuality(
        tier=1, bitrate_kbps=128, bit_depth=None, sample_rate=44_100,
        clipping_ratio=0.0, integrated_loudness_lufs=None,
    )

    ranked = sorted(
        [lossy_low, lossless, lossy_high],
        key=_quality_sort_key,
        reverse=True,
    )

    assert ranked == [lossless, lossy_high, lossy_low]


# --- delete_local_files (roadmap item 40) — real tmp_path files only,
# never a real library, matching this project's own standing rule
# against ever touching a file without confirmation and never running a
# destructive test outside a disposable fixture directory. -------------

def test_delete_local_files_removes_db_row_and_real_file(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    file_path = music_dir / "dupe.wav"
    file_path.write_bytes(b"fake audio data")
    local_file = add_local_file(database, location, "dupe.wav", "wav", 3000)

    service = make_service(database)
    result = service.delete_local_files([local_file.id])

    assert result == {
        "deleted": 1, "failed": 0, "details": [],
        # Roadmap item 56 Phase 6.4 — the real, stat()-measured size of
        # the real file just deleted (b"fake audio data" is 15 bytes).
        "bytes_freed": 15,
    }
    assert not file_path.exists()

    with database.transaction() as connection:
        assert LocalFileRepository(database).get_by_id(
            local_file.id, connection,
        ) is None


def test_delete_local_files_cascades_track_match_to_unmatched(tmp_path):
    # Confirms the schema's own ON DELETE SET NULL actually fires under
    # PRAGMA foreign_keys = ON, rather than assuming it does -- a track
    # matched to a deleted duplicate must come back as unmatched
    # (local_file_id NULL), never left pointing at a deleted row.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    file_path = music_dir / "dupe.wav"
    file_path.write_bytes(b"fake audio data")
    local_file = add_local_file(database, location, "dupe.wav", "wav", 3000)

    track_repo = TrackRepository(database)
    match_repo = TrackMatchRepository(database)
    with database.transaction() as connection:
        track_repo.save(
            Track(
                id="t1", title="Title", artist="Artist", album="Album",
                duration_ms=200_000,
            ),
            connection,
        )
        match_repo.upsert(
            TrackMatch(
                track_id="t1",
                local_file_id=local_file.id,
                match_method="auto",
                score=100.0,
                matched_at=datetime.now(timezone.utc).isoformat(),
            ),
            connection,
        )

    service = make_service(database)
    service.delete_local_files([local_file.id])

    with database.transaction() as connection:
        match = match_repo.get_by_track_id("t1", connection)

    assert match is not None
    assert match.local_file_id is None


def test_delete_local_files_repoints_match_to_the_kept_file(tmp_path):
    # The real bug this guards against: without keep_local_file_id, the
    # ON DELETE SET NULL cascade leaves match_method='auto' with
    # local_file_id=NULL, which DashboardService._compute_status reports
    # as NOT_FOUND even though the group's other, still-present copy is
    # a fingerprint-confirmed duplicate of the exact same track. Passing
    # keep_local_file_id must re-point the match there instead, and
    # preserve the original match_method/score (no re-evaluation).
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    (music_dir / "low_quality.wav").write_bytes(b"fake audio data")
    (music_dir / "high_quality.wav").write_bytes(b"fake audio data")
    low_quality = add_local_file(database, location, "low_quality.wav", "wav", 3000)
    high_quality = add_local_file(database, location, "high_quality.wav", "wav", 3000)

    track_repo = TrackRepository(database)
    match_repo = TrackMatchRepository(database)
    original_matched_at = "2020-01-01T00:00:00+00:00"
    with database.transaction() as connection:
        track_repo.save(
            Track(
                id="t1", title="Title", artist="Artist", album="Album",
                duration_ms=200_000,
            ),
            connection,
        )
        match_repo.upsert(
            TrackMatch(
                track_id="t1",
                local_file_id=low_quality.id,
                match_method="auto",
                score=87.5,
                matched_at=original_matched_at,
            ),
            connection,
        )

    service = make_service(database)
    result = service.delete_local_files(
        [low_quality.id], keep_local_file_id=high_quality.id,
    )

    assert result["deleted"] == 1
    assert result["failed"] == 0

    with database.transaction() as connection:
        match = match_repo.get_by_track_id("t1", connection)

    assert match is not None
    assert match.local_file_id == high_quality.id
    assert match.match_method == "auto"
    assert match.score == 87.5
    assert match.matched_at != original_matched_at


def test_delete_local_files_already_missing_id_counts_as_deleted(tmp_path):
    # The desired end state (no such row, no such tracked file) is
    # already true -- not a failure.
    database = make_database(tmp_path)
    register_location(database, tmp_path / "music")
    service = make_service(database)

    result = service.delete_local_files([999])

    # Nothing was ever really there — 0 real bytes freed, not a
    # missing/error value.
    assert result == {
        "deleted": 1, "failed": 0, "details": [], "bytes_freed": 0,
    }


def test_delete_local_files_reports_failure_when_file_already_gone_from_disk(
        tmp_path,
):
    # DB row exists but the real file underneath it was already removed
    # out from under it (e.g. moved, or deleted by something else) --
    # the DB row is still correctly removed (see the method's own
    # docstring for why that ordering is deliberate), but the failure
    # to delete a file that isn't there must be reported, not silently
    # treated as a clean success.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    local_file = add_local_file(database, location, "gone.wav", "wav", 3000)
    # Deliberately never write gone.wav to disk.

    service = make_service(database)
    result = service.delete_local_files([local_file.id])

    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert "gone.wav" in result["details"][0]["message"]

    with database.transaction() as connection:
        assert LocalFileRepository(database).get_by_id(
            local_file.id, connection,
        ) is None


def test_delete_local_files_one_failure_does_not_abort_the_batch(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    good_path = music_dir / "good.wav"
    good_path.write_bytes(b"fake audio data")
    good_file = add_local_file(database, location, "good.wav", "wav", 3000)
    # missing.wav is registered but never written to disk -- deleting it
    # fails, and must not stop good.wav from still being deleted.
    missing_file = add_local_file(database, location, "missing.wav", "wav", 3000)

    service = make_service(database)
    result = service.delete_local_files([missing_file.id, good_file.id])

    assert result["deleted"] == 1
    assert result["failed"] == 1
    assert not good_path.exists()


# --- Roadmap item 56 Phase 6.4: reclaimed-space milestone -----------------

def test_delete_local_files_records_a_real_cleanup(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    (music_dir / "a.wav").write_bytes(b"12345")
    (music_dir / "b.wav").write_bytes(b"1234567890")
    file_a = add_local_file(database, location, "a.wav", "wav", 3000)
    file_b = add_local_file(database, location, "b.wav", "wav", 3000)

    service = make_service(database)
    result = service.delete_local_files(
        [file_a.id, file_b.id], location_id=location.id,
    )

    assert result["bytes_freed"] == 15  # 5 + 10 real bytes
    assert service.get_cleanup_totals() == (2, 15)

    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT files_deleted, bytes_freed, location_id "
            "FROM duplicate_cleanups"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["files_deleted"] == 2
    assert rows[0]["bytes_freed"] == 15
    assert rows[0]["location_id"] == location.id


def test_delete_local_files_records_nothing_when_everything_fails(tmp_path):
    # "An empty milestone is worse than no milestone" — a batch that
    # deleted nothing real must not create a zero-value cleanup row.
    database = make_database(tmp_path)
    location = register_location(database, tmp_path / "music")
    missing_file = add_local_file(
        database, location, "missing.wav", "wav", 3000,
    )

    service = make_service(database)
    result = service.delete_local_files([missing_file.id])

    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert service.get_cleanup_totals() == (0, 0)


def test_get_cleanup_totals_sums_across_multiple_real_cleanups(tmp_path):
    database = make_database(tmp_path)
    service = make_service(database)

    assert service.get_cleanup_totals() == (0, 0)

    service.record_cleanup(3, 1_000)
    service.record_cleanup(2, 500)

    assert service.get_cleanup_totals() == (5, 1_500)


def test_delete_one_local_file_falls_back_to_stored_size_when_stat_fails(
        tmp_path, monkeypatch,
):
    # Roadmap item 56 Phase 6.4 — the documented fallback path,
    # isolated directly: a real stat() failure on the file about to be
    # measured (not necessarily "the file is fully gone" — any OSError)
    # must still record the real, previously-known size_bytes rather
    # than silently reporting 0 bytes freed for a real deletion.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    real_path = music_dir / "a.wav"
    real_path.write_bytes(b"real bytes on disk")
    local_file = add_local_file(database, location, "a.wav", "wav", 3000)

    from pathlib import Path as PathlibPath
    original_stat = PathlibPath.stat

    def failing_stat(self, *args, **kwargs):
        if self.name == "a.wav":
            raise OSError("simulated stat failure")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(PathlibPath, "stat", failing_stat)

    service = make_service(database)
    bytes_freed = service._delete_one_local_file(local_file.id, None)

    # local_file's own stored size_bytes, set by add_local_file above.
    assert bytes_freed == 1000

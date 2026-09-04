import os
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
    DuplicateFolderScope,
    DuplicateService,
    LibraryLocationNotFoundError,
    _cluster_by_similarity,
    _path_within_folder,
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


def register_location(database: Database, path, name: str = "Main") -> LibraryLocation:
    repo = LibraryLocationRepository(database)
    location = LibraryLocation(
        name=name, path=str(path),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    with database.transaction() as connection:
        repo.add(location, connection)
        return repo.get_by_name(name, connection)


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


def test_compute_fingerprints_classifies_a_missing_file(tmp_path):
    # Roadmap item 68 (Phase 8.2/8.3) — a local_files row whose real
    # file is gone (moved/deleted outside a rescan) gets its own
    # reason, not a generic "failed".
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    add_local_file(database, location, "gone.wav", "wav", 3000)

    service = make_service(database)
    result = service.compute_fingerprints("Main")

    assert result["failed"] == 1
    assert result["details"][0]["reason"] == "file_missing"


def test_compute_fingerprints_classifies_a_0_byte_file(tmp_path):
    # Roadmap item 68 (Phase 8.3) — flagged distinctly from a real
    # decode failure; it can never succeed a fingerprint attempt, so it
    # can also never enter a duplicate group and be offered for delete.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    (music_dir / "empty.wav").write_bytes(b"")
    add_local_file(database, location, "empty.wav", "wav", 3000)

    service = make_service(database)
    result = service.compute_fingerprints("Main")

    assert result["failed"] == 1
    assert result["details"][0]["reason"] == "empty_file"


def test_compute_fingerprints_classifies_an_undecodable_file(tmp_path):
    # A real, non-empty, non-missing file that just isn't real audio —
    # both soundfile and (if present) the ffmpeg fallback genuinely
    # can't decode it, so this is the "decode_unsupported" reason.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)
    (music_dir / "garbage.wav").write_bytes(b"not actually audio data")
    add_local_file(database, location, "garbage.wav", "wav", 3000)

    service = make_service(database)
    result = service.compute_fingerprints("Main")

    assert result["failed"] == 1
    assert result["details"][0]["reason"] == "decode_unsupported"


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


def test_find_duplicate_groups_skips_a_stale_row_instead_of_crashing(
        tmp_path,
):
    # Roadmap item 93 (B3.5) — a real, previously-uncaught crash: a file
    # can have a cached fingerprint (so it clusters) while its
    # local_files row no longer resolves to a real file on disk (a
    # rename that updated one location's row but not an overlapping
    # location's own copy of the same physical file — item 76's
    # documented drift class). Reproduced directly: fingerprint two
    # real duplicate files, then remove one from disk without touching
    # its DB row.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    _write_tone(music_dir / "dupe_a.wav", frequency=440.0)
    _write_tone(music_dir / "dupe_b.wav", frequency=440.0)
    add_local_file(database, location, "dupe_a.wav", "wav", 3000)
    add_local_file(database, location, "dupe_b.wav", "wav", 3000)

    service = make_service(database)
    service.compute_fingerprints("Main")

    # Simulate the stale-row shape: the real file is gone (renamed via
    # a different, overlapping location's row), but this row's
    # fingerprint stays cached.
    (music_dir / "dupe_b.wav").unlink()

    groups = service.find_duplicate_groups("Main")  # must not raise

    # Only one real file remains present -- not a "duplicate" of
    # anything any more, matches the same "silently excluded" precedent
    # this function already applies to files with no fingerprint at all.
    assert groups == []


def test_find_duplicate_groups_drops_only_the_stale_file_from_a_larger_group(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    _write_tone(music_dir / "dupe_a.wav", frequency=440.0)
    _write_tone(music_dir / "dupe_b.wav", frequency=440.0)
    _write_tone(music_dir / "dupe_c.wav", frequency=440.0)
    add_local_file(database, location, "dupe_a.wav", "wav", 3000)
    add_local_file(database, location, "dupe_b.wav", "wav", 3000)
    add_local_file(database, location, "dupe_c.wav", "wav", 3000)

    service = make_service(database)
    service.compute_fingerprints("Main")

    (music_dir / "dupe_c.wav").unlink()

    groups = service.find_duplicate_groups("Main")

    assert len(groups) == 1
    filenames = {f.local_file.filename for f in groups[0].files}
    assert filenames == {"dupe_a.wav", "dupe_b.wav"}


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
        "deleted": 1, "failed": 0, "skipped_same_physical_file": 0,
        "details": [],
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
        "deleted": 1, "failed": 0, "skipped_same_physical_file": 0,
        "details": [], "bytes_freed": 0,
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


# --- Roadmap item 93 (R3.3): same-physical-file delete guard --------------
#
# Overlapping registered library locations (item 77's own documented
# nesting: a location registered at a parent path and another at a
# child path both cover the same real folder) can produce two distinct
# local_files rows for the identical real file on disk. A hard link is
# the reproducible stand-in here for "two rows, one real inode" —
# exactly what same_file()/Path.samefile() actually checks, without
# needing two real overlapping locations wired up in a test.

def test_delete_local_files_refuses_when_target_is_same_physical_file_as_kept(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    real_file = music_dir / "keep.wav"
    real_file.write_bytes(b"real-audio-bytes")
    aliased_path = music_dir / "duplicate_row.wav"
    os.link(real_file, aliased_path)

    keep = add_local_file(database, location, "keep.wav", "wav", 3000)
    duplicate_row = add_local_file(
        database, location, "duplicate_row.wav", "wav", 3000,
    )

    service = make_service(database)
    result = service.delete_local_files(
        [duplicate_row.id], keep_local_file_id=keep.id,
    )

    assert result["deleted"] == 0
    assert result["failed"] == 0
    assert result["skipped_same_physical_file"] == 1
    # Neither the kept file NOR the "duplicate" row's own file was
    # touched -- deleting either would have deleted both, since they
    # are the same real inode.
    assert real_file.exists()
    assert aliased_path.exists()

    with database.transaction() as connection:
        assert LocalFileRepository(database).get_by_id(
            duplicate_row.id, connection,
        ) is not None


def test_delete_local_files_deletes_normally_when_files_are_genuinely_different(
        tmp_path,
):
    # The guard must not misfire on two REAL, different files that just
    # happen to be in the same delete_local_files() call.
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    (music_dir / "keep.wav").write_bytes(b"real-content-a")
    (music_dir / "other.wav").write_bytes(b"real-content-b")

    keep = add_local_file(database, location, "keep.wav", "wav", 3000)
    other = add_local_file(database, location, "other.wav", "wav", 3000)

    service = make_service(database)
    result = service.delete_local_files(
        [other.id], keep_local_file_id=keep.id,
    )

    assert result["deleted"] == 1
    assert result["skipped_same_physical_file"] == 0
    assert not (music_dir / "other.wav").exists()
    assert (music_dir / "keep.wav").exists()


def test_resolve_groups_reports_same_physical_file_skips(tmp_path):
    from seeker.library.duplicate_service import GroupResolutionPlan

    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    real_file = music_dir / "keep.wav"
    real_file.write_bytes(b"real-audio-bytes")
    aliased_path = music_dir / "duplicate_row.wav"
    os.link(real_file, aliased_path)

    keep = add_local_file(database, location, "keep.wav", "wav", 3000)
    duplicate_row = add_local_file(
        database, location, "duplicate_row.wav", "wav", 3000,
    )

    service = make_service(database)
    result = service.resolve_groups(
        [
            GroupResolutionPlan(
                keep_local_file_id=keep.id,
                delete_local_file_ids=[duplicate_row.id],
                location_id=location.id,
            ),
        ]
    )

    assert result.files_deleted == 0
    assert result.files_failed == 0
    assert result.files_skipped_same_physical_file == 1
    # Not a failure -- the safety check working correctly.
    assert result.groups_resolved == 1
    assert result.groups_failed == 0
    assert real_file.exists()


# --- Roadmap item R3.2: "Resolve all groups" ------------------------------

def test_resolve_groups_resolves_multiple_plans(tmp_path):
    from seeker.library.duplicate_service import GroupResolutionPlan

    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    (music_dir / "a1.wav").write_bytes(b"12345")
    (music_dir / "a2.wav").write_bytes(b"1234567890")
    (music_dir / "b1.wav").write_bytes(b"123")
    (music_dir / "b2.wav").write_bytes(b"12345678")
    a1 = add_local_file(database, location, "a1.wav", "wav", 3000)
    a2 = add_local_file(database, location, "a2.wav", "wav", 3000)
    b1 = add_local_file(database, location, "b1.wav", "wav", 3000)
    b2 = add_local_file(database, location, "b2.wav", "wav", 3000)

    service = make_service(database)
    plans = [
        GroupResolutionPlan(
            delete_local_file_ids=[a2.id], keep_local_file_id=a1.id,
            location_id=location.id,
        ),
        GroupResolutionPlan(
            delete_local_file_ids=[b2.id], keep_local_file_id=b1.id,
            location_id=location.id,
        ),
    ]

    result = service.resolve_groups(plans)

    assert result.groups_resolved == 2
    assert result.groups_failed == 0
    assert result.files_deleted == 2
    assert result.files_failed == 0
    assert result.bytes_freed == 18  # 10 (a2) + 8 (b2)
    assert result.details == []
    assert result.plan_outcomes == [True, True]
    assert (music_dir / "a1.wav").exists()
    assert not (music_dir / "a2.wav").exists()
    assert (music_dir / "b1.wav").exists()
    assert not (music_dir / "b2.wav").exists()
    assert service.get_cleanup_totals() == (2, 18)


def test_resolve_groups_one_group_failing_does_not_abort_the_rest(tmp_path):
    from seeker.library.duplicate_service import GroupResolutionPlan

    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    (music_dir / "good1.wav").write_bytes(b"12345")
    (music_dir / "good2.wav").write_bytes(b"1234567890")
    good1 = add_local_file(database, location, "good1.wav", "wav", 3000)
    good2 = add_local_file(database, location, "good2.wav", "wav", 3000)
    # missing.wav is registered but never written to disk -- its own
    # group's delete fails, but must not stop the good group.
    missing = add_local_file(database, location, "missing.wav", "wav", 3000)

    service = make_service(database)
    plans = [
        GroupResolutionPlan(
            delete_local_file_ids=[missing.id], keep_local_file_id=good1.id,
            location_id=location.id,
        ),
        GroupResolutionPlan(
            delete_local_file_ids=[good2.id], keep_local_file_id=good1.id,
            location_id=location.id,
        ),
    ]

    result = service.resolve_groups(plans)

    assert result.groups_resolved == 1
    assert result.groups_failed == 1
    assert result.files_deleted == 1
    assert result.files_failed == 1
    assert len(result.details) == 1
    # Order matches the plans list -- the missing-file plan (index 0)
    # failed, the good plan (index 1) succeeded.
    assert result.plan_outcomes == [False, True]
    assert not (music_dir / "good2.wav").exists()


def test_resolve_groups_empty_plans_is_a_no_op(tmp_path):
    database = make_database(tmp_path)
    service = make_service(database)

    result = service.resolve_groups([])

    assert result.groups_resolved == 0
    assert result.groups_failed == 0
    assert result.files_deleted == 0
    assert result.bytes_freed == 0
    assert result.details == []


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


# --- Folder scoping (roadmap item 68, Phase 7.2) ----------------------

def test_path_within_folder_respects_separator_boundaries():
    # The real, explicit gotcha the brief calls out: "Trance" must never
    # match "TranceX" via a naive str.startswith().
    assert _path_within_folder("Trance/song.mp3", "Trance")
    assert not _path_within_folder("TranceX/song.mp3", "Trance")
    assert _path_within_folder("A/B/song.mp3", "A/B")
    assert not _path_within_folder("A/BC/song.mp3", "A/B")


def test_path_within_folder_empty_folder_means_whole_location():
    assert _path_within_folder("anything/song.mp3", "")


def test_resolve_folder_scopes_maps_a_real_absolute_path(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    (music_dir / "Trance").mkdir(parents=True)
    location = register_location(database, music_dir)

    service = make_service(database)
    scopes = service.resolve_folder_scopes([str(music_dir / "Trance")])

    assert len(scopes) == 1
    assert scopes[0].location.name == location.name
    assert scopes[0].folder_relative_path == "Trance"


def test_resolve_folder_scopes_whole_location_path_gives_empty_relative(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    register_location(database, music_dir)

    service = make_service(database)
    scopes = service.resolve_folder_scopes([str(music_dir)])

    assert scopes[0].folder_relative_path == ""


def test_resolve_folder_scopes_rejects_a_folder_outside_every_location(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    register_location(database, music_dir)
    outside = tmp_path / "not_registered"
    outside.mkdir()

    service = make_service(database)

    with pytest.raises(LibraryLocationNotFoundError):
        service.resolve_folder_scopes([str(outside)])


def test_resolve_folder_scopes_prefers_the_most_specific_nested_location(
        tmp_path,
):
    # Roadmap item 77 (P8.2) — real, live-confirmed bug: two registered
    # locations where one is nested inside the other. A folder equal to
    # the NESTED location's own path used to match whichever location
    # happened to sort first alphabetically (get_all()'s ORDER BY
    # name), not the most specific one. "Music" sorts before "Test"
    # alphabetically but "Test" is the correct (nested, more specific)
    # match — reproducing the exact real production shape from the
    # brief (a "Test" location nested inside a "Music" location nested
    # inside "x9-pro").
    database = make_database(tmp_path)
    outer_dir = tmp_path / "outer"
    inner_dir = outer_dir / "Music"
    nested_dir = inner_dir / "Test"
    nested_dir.mkdir(parents=True)
    register_location(database, outer_dir, name="x9-pro")
    register_location(database, inner_dir, name="Music")
    nested_location = register_location(database, nested_dir, name="Test")

    service = make_service(database)
    scopes = service.resolve_folder_scopes([str(nested_dir)])

    assert len(scopes) == 1
    assert scopes[0].location.name == nested_location.name
    assert scopes[0].folder_relative_path == ""


def test_resolve_folder_scopes_tiebreak_uses_preferred_location_id(
        tmp_path,
):
    # A genuine specificity tie: `library_locations.path` is UNIQUE at
    # the DB level, so two locations can never be registered at the
    # exact same string path — but two DIFFERENT registered paths can
    # still resolve() to the identical real directory (e.g. a symlink,
    # or the same volume reachable via two mount points), which is
    # exactly what Path.resolve() collapses here. preferred_location_id
    # (the UI's own selected location combo, P9) breaks that real tie;
    # omitting it falls back to get_all()'s stable alphabetical order.
    database = make_database(tmp_path)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    link_dir.symlink_to(real_dir)
    register_location(database, real_dir, name="A")
    location_b = register_location(database, link_dir, name="B")

    service = make_service(database)

    default_scopes = service.resolve_folder_scopes([str(real_dir)])
    assert default_scopes[0].location.name == "A"

    preferred_scopes = service.resolve_folder_scopes(
        [str(real_dir)], preferred_location_id=location_b.id,
    )
    assert preferred_scopes[0].location.name == "B"

    # A preference that ISN'T among the tied candidates never overrides
    # a strictly more specific match, and is simply ignored when it
    # doesn't apply to this folder at all.
    unrelated_scopes = service.resolve_folder_scopes(
        [str(real_dir)], preferred_location_id=999999,
    )
    assert unrelated_scopes[0].location.name == "A"


def test_summarize_scopes_reports_resolved_location_names(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    (music_dir / "A").mkdir(parents=True)
    location = register_location(database, music_dir)
    add_local_file(database, location, "A/one.mp3", "mp3", 1000)

    service = make_service(database)
    scopes = service.resolve_folder_scopes([str(music_dir / "A")])
    summary = service.summarize_scopes(scopes)

    assert summary.file_count == 1
    assert summary.resolved_location_names == [location.name]
    assert summary.empty_locations == []


def test_summarize_scopes_flags_a_location_with_no_scanned_files(tmp_path):
    # Roadmap item 77 (P8.4) — a location that resolves correctly but
    # has never been scanned reads as an honest "no scanned files yet",
    # not a bare, unexplained "0 files in scope."
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    service = make_service(database)
    scopes = service.resolve_folder_scopes([str(music_dir)])
    summary = service.summarize_scopes(scopes)

    assert summary.file_count == 0
    assert summary.resolved_location_names == [location.name]
    assert summary.empty_locations == [location.name]


def test_compute_fingerprints_scoped_to_a_folder(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    (music_dir / "InScope").mkdir(parents=True)
    (music_dir / "OutOfScope").mkdir(parents=True)
    location = register_location(database, music_dir)

    _write_tone(music_dir / "InScope" / "a.wav", frequency=440.0)
    _write_tone(music_dir / "OutOfScope" / "b.wav", frequency=880.0)
    add_local_file(database, location, "InScope/a.wav", "wav", 3000)
    add_local_file(database, location, "OutOfScope/b.wav", "wav", 3000)

    service = make_service(database)
    result = service.compute_fingerprints("Main", folders=["InScope"])

    assert result["computed"] == 1

    with database.transaction() as connection:
        repo = LocalFileRepository(database)
        in_scope = repo.get_by_location_and_relative_path(
            location.id, "InScope/a.wav", connection,
        )
        out_of_scope = repo.get_by_location_and_relative_path(
            location.id, "OutOfScope/b.wav", connection,
        )

    assert in_scope.fingerprint is not None
    assert out_of_scope.fingerprint is None


def test_find_duplicate_groups_scoped_to_a_folder_excludes_outside_matches(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    (music_dir / "FolderA").mkdir(parents=True)
    (music_dir / "FolderB").mkdir(parents=True)
    location = register_location(database, music_dir)

    # An identical real duplicate pair split across two folders.
    _write_tone(music_dir / "FolderA" / "dupe.wav", frequency=440.0)
    _write_tone(music_dir / "FolderB" / "dupe.wav", frequency=440.0)
    add_local_file(database, location, "FolderA/dupe.wav", "wav", 3000)
    add_local_file(database, location, "FolderB/dupe.wav", "wav", 3000)

    service = make_service(database)
    service.compute_fingerprints("Main")

    # Scoped to FolderA alone -- the real duplicate in FolderB is out of
    # scope, so no group should be found (nothing to compare against).
    groups = service.find_duplicate_groups("Main", folders=["FolderA"])
    assert groups == []

    # Both folders pooled -- the real cross-folder duplicate IS found.
    groups_both = service.find_duplicate_groups(
        "Main", folders=["FolderA", "FolderB"],
    )
    assert len(groups_both) == 1


def test_find_duplicate_groups_across_scopes_pools_across_two_real_locations(
        tmp_path,
):
    database = make_database(tmp_path)
    music_dir_a = tmp_path / "music_a"
    music_dir_b = tmp_path / "music_b"
    music_dir_a.mkdir()
    music_dir_b.mkdir()

    location_a = register_location(database, music_dir_a)
    repo = LibraryLocationRepository(database)
    with database.transaction() as connection:
        repo.add(
            LibraryLocation(
                name="Other", path=str(music_dir_b),
                added_at=datetime.now(timezone.utc).isoformat(),
            ),
            connection,
        )
        location_b = repo.get_by_name("Other", connection)

    # A real duplicate pair, one file in each of two DIFFERENT real
    # registered locations -- deliberately allowed per the brief.
    _write_tone(music_dir_a / "dupe.wav", frequency=440.0)
    _write_tone(music_dir_b / "dupe.wav", frequency=440.0)
    add_local_file(database, location_a, "dupe.wav", "wav", 3000)
    add_local_file(database, location_b, "dupe.wav", "wav", 3000)

    service = make_service(database)
    service.compute_fingerprints("Main")
    service.compute_fingerprints("Other")

    scopes = [
        DuplicateFolderScope(location=location_a, folder_relative_path=""),
        DuplicateFolderScope(location=location_b, folder_relative_path=""),
    ]
    groups = service.find_duplicate_groups_across_scopes(scopes)

    assert len(groups) == 1
    assert len(groups[0].files) == 2


def test_compute_fingerprints_reports_real_progress(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    for i in range(3):
        _write_tone(music_dir / f"{i}.wav", frequency=440.0 + i * 10)
        add_local_file(database, location, f"{i}.wav", "wav", 3000)

    reported = []
    service = make_service(database)
    service.compute_fingerprints(
        "Main",
        progress=lambda stage, current, total: reported.append(
            (stage, current, total),
        ),
    )

    assert reported[-1] == ("Fingerprinting", 3, 3)
    assert all(stage == "Fingerprinting" for stage, _, _ in reported)


def test_find_duplicate_groups_reports_both_real_stages(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    location = register_location(database, music_dir)

    _write_tone(music_dir / "a.wav", frequency=440.0)
    _write_tone(music_dir / "b.wav", frequency=440.0)
    add_local_file(database, location, "a.wav", "wav", 3000)
    add_local_file(database, location, "b.wav", "wav", 3000)

    service = make_service(database)
    service.compute_fingerprints("Main")

    reported = []
    service.find_duplicate_groups(
        "Main",
        progress=lambda stage, current, total: reported.append(
            (stage, current, total),
        ),
    )

    stages = {stage for stage, _, _ in reported}
    assert stages == {"Decoding fingerprints", "Comparing"}
    decode_events = [e for e in reported if e[0] == "Decoding fingerprints"]
    assert decode_events[-1] == ("Decoding fingerprints", 2, 2)


def test_count_files_for_scopes_real_count_before_a_real_run(tmp_path):
    database = make_database(tmp_path)
    music_dir = tmp_path / "music"
    (music_dir / "A").mkdir(parents=True)
    (music_dir / "B").mkdir(parents=True)
    location = register_location(database, music_dir)

    add_local_file(database, location, "A/one.mp3", "mp3", 1000)
    add_local_file(database, location, "A/two.mp3", "mp3", 1000)
    add_local_file(database, location, "B/three.mp3", "mp3", 1000)

    service = make_service(database)

    count_a = service.count_files_for_scopes(
        [DuplicateFolderScope(location=location, folder_relative_path="A")],
    )
    count_whole = service.count_files_for_scopes(
        [DuplicateFolderScope(location=location, folder_relative_path="")],
    )

    assert count_a == 2
    assert count_whole == 3

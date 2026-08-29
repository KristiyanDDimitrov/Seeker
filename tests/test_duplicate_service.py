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
from seeker.library.duplicate_service import (
    DuplicateService,
    LibraryLocationNotFoundError,
    _cluster_by_similarity,
    _quality_sort_key,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
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

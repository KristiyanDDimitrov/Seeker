import shutil
import wave
from pathlib import Path

import httpx
import pytest
from mutagen import File as MutagenFile

from seeker.audio_analysis import CAMELOT_MAP
from seeker.database.connection import Database
from seeker.database.repositories.library_location_repository import (
    LibraryLocationRepository,
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
from seeker.library.metadata_service import MetadataService
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.track import Track
from seeker.models.track_match import TrackMatch

X9_PRO_ROOT = Path("/Volumes/X9 Pro")
REAL_WAV = X9_PRO_ROOT / "Music/240KMH/3AMDISCO - Get Back.wav"

requires_x9_pro = pytest.mark.skipif(
    not X9_PRO_ROOT.is_dir(),
    reason="x9-pro drive not mounted",
)

FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 256


def make_synthetic_wav(path: Path) -> None:
    # A real, valid (if silent) WAV — enough for mutagen to recognize and
    # write tags into, without depending on any real library file.
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44_100)
        handle.writeframes(b"\x00\x00" * 44_100)


def make_service(tmp_path) -> MetadataService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return MetadataService(
        database,
        TrackRepository(database),
        TrackMatchRepository(database),
        LocalFileRepository(database),
        LibraryLocationRepository(database),
        PlaylistRepository(database),
    )


def seed_location(service: MetadataService, root: Path) -> LibraryLocation:
    with service.database.transaction() as connection:
        service.locations.add(
            LibraryLocation(
                name="main", path=str(root), added_at="2026-01-01"
            ),
            connection,
        )
        return service.locations.get_by_name("main", connection)


def seed_matched_track(
        service: MetadataService,
        location: LibraryLocation,
        track_id: str,
        relative_path: str,
        artist: str = "Test Artist",
        title: str = "Test Title",
        album: str = "Test Album",
        album_art_url: str | None = None,
) -> None:
    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id=track_id,
                title=title,
                artist=artist,
                album=album,
                duration_ms=200_000,
                album_art_url=album_art_url,
            ),
            connection,
        )

        service.local_files.upsert(
            LocalFile(
                location_id=location.id,
                relative_path=relative_path,
                filename=relative_path,
                format=Path(relative_path).suffix.lstrip("."),
                size_bytes=Path(location.path, relative_path).stat().st_size,
                mtime=1.0,
                scanned_at="2026-01-01",
            ),
            connection,
        )
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, relative_path, connection
        )

        service.track_matches.upsert(
            TrackMatch(
                track_id=track_id,
                local_file_id=local_file.id,
                match_method="auto",
                score=95.0,
                matched_at="2026-01-01",
            ),
            connection,
        )


def test_tag_tracks_skips_track_with_no_match(tmp_path):
    service = make_service(tmp_path)

    with service.database.transaction() as connection:
        service.tracks.save(
            Track(
                id="t1",
                title="Unmatched Track",
                artist="Nobody",
                album="Nothing",
                duration_ms=1000,
            ),
            connection,
        )

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 0
    assert counts["skipped_no_match"] == 1
    assert counts["skipped_format_unsupported"] == 0
    assert counts["failed"] == 0
    assert counts["details"][0]["reason"] == "skipped_no_match"


def test_tag_tracks_skips_unrecognized_format(tmp_path, monkeypatch):
    root = tmp_path / "music"
    root.mkdir()
    (root / "song.mp3").write_bytes(b"fake mp3 bytes, not real audio")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "t1", "song.mp3")

    # Simulate an audio format mutagen can open but that write_text_tags
    # doesn't know how to write to (e.g. a real .ogg/.aac file) — not
    # reproducible with a real file in this library, since mp3/flac/wav/
    # mp4 all turned out to be supported (see CLAUDE.md).
    class FakeUnsupportedFile:
        def __init__(self):
            self.tags = object()

        def save(self):
            raise AssertionError("save() must not be called on a skip")

    monkeypatch.setattr(
        "seeker.library.metadata_service.MutagenFile",
        lambda path: FakeUnsupportedFile(),
    )

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 0
    assert counts["skipped_format_unsupported"] == 1
    assert counts["failed"] == 0
    assert counts["details"][0]["reason"] == "skipped_format_unsupported"


def _fake_jpeg_response(url, timeout=None):
    return httpx.Response(
        200,
        content=FAKE_JPEG_BYTES,
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", url),
    )


def test_tag_tracks_tags_successfully_with_mocked_art_download(
        tmp_path, monkeypatch,
):
    # Portable happy-path test — a real, synthetic (silent) WAV, not
    # dependent on the x9-pro drive being mounted. The drive-dependent
    # integration check below covers the real 3amdisco file specifically.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service,
        location,
        "t1",
        "song.wav",
        artist="Test Artist",
        title="Test Title",
        album="Test Album",
        album_art_url="https://i.scdn.co/image/fake",
    )

    monkeypatch.setattr(httpx, "get", _fake_jpeg_response)

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 1
    assert counts["skipped_no_match"] == 0
    assert counts["skipped_format_unsupported"] == 0
    assert counts["failed"] == 0

    reopened = MutagenFile(dest)
    assert str(reopened.tags["TIT2"]) == "Test Title"
    assert str(reopened.tags["TPE1"]) == "Test Artist"
    assert str(reopened.tags["TALB"]) == "Test Album"
    assert reopened.tags["APIC:Cover"].data == FAKE_JPEG_BYTES


def test_tag_tracks_analyze_audio_false_is_completely_inert(
        tmp_path, monkeypatch,
):
    # The default (analyze_audio=False) must be a genuinely independent
    # toggle, not just "the analysis columns happen to stay None" — this
    # asserts the expensive analysis call itself is never even invoked,
    # and that TBPM/TKEY never get written, when the flag is off.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "t1", "song.wav")

    def fail_if_called(file_path):
        raise AssertionError(
            "analyze_audio must not run when analyze_audio=False"
        )

    monkeypatch.setattr(
        "seeker.library.metadata_service.run_audio_analysis",
        fail_if_called,
    )

    with service.database.transaction() as connection:
        before = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 1
    assert counts["failed"] == 0

    with service.database.transaction() as connection:
        after = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )

    assert after.bpm is None
    assert after.camelot_key is None
    assert after.key_confidence is None
    assert before.bpm == after.bpm
    assert before.camelot_key == after.camelot_key
    assert before.key_confidence == after.key_confidence

    reopened = MutagenFile(dest)
    assert reopened.tags.get("TBPM") is None
    assert reopened.tags.get("TKEY") is None


@requires_x9_pro
def test_tag_tracks_real_wav_round_trips(tmp_path, monkeypatch):
    # Integration check against the real 240KM/H match — a COPY of the
    # real file, never the original on the x9-pro drive. The original
    # was itself intentionally tagged for real in an earlier session, so
    # the invariant this test can actually assert is "this test run
    # didn't touch it" (a stable mtime/size), not "it has no tags" —
    # that was only ever incidentally true before it was tagged for real.
    original_stat_before = REAL_WAV.stat()

    root = tmp_path / "music"
    root.mkdir()
    dest = root / "3AMDISCO - Get Back.wav"
    shutil.copy(REAL_WAV, dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service,
        location,
        "t1",
        "3AMDISCO - Get Back.wav",
        artist="3amdisco",
        title="Get Back",
        album="Get Back EP",
        album_art_url="https://i.scdn.co/image/fake",
    )

    monkeypatch.setattr(httpx, "get", _fake_jpeg_response)

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 1
    assert counts["failed"] == 0

    reopened = MutagenFile(dest)
    assert str(reopened.tags["TIT2"]) == "Get Back"
    assert str(reopened.tags["TPE1"]) == "3amdisco"
    assert str(reopened.tags["TALB"]) == "Get Back EP"
    assert reopened.tags["APIC:Cover"].data == FAKE_JPEG_BYTES

    # The original real file on the x9-pro drive must be untouched by
    # this test run — same size and mtime as before.
    original_stat_after = REAL_WAV.stat()
    assert original_stat_after.st_size == original_stat_before.st_size
    assert original_stat_after.st_mtime == original_stat_before.st_mtime


@requires_x9_pro
def test_tag_tracks_analyze_audio_true_writes_and_persists_real_analysis(
        tmp_path, monkeypatch,
):
    # Same real 3amdisco copy, this time with analyze_audio=True — the
    # True-path counterpart to the inert-when-False guardrail above.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "3AMDISCO - Get Back.wav"
    shutil.copy(REAL_WAV, dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service,
        location,
        "t1",
        "3AMDISCO - Get Back.wav",
        artist="3amdisco",
        title="Get Back",
        album="Get Back EP",
    )

    counts = service.tag_tracks(["t1"], analyze_audio=True)

    assert counts["tagged"] == 1
    assert counts["failed"] == 0

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "3AMDISCO - Get Back.wav", connection
        )

    assert local_file.bpm is not None
    assert 60 <= local_file.bpm <= 200
    assert local_file.camelot_key in CAMELOT_MAP.values()
    assert local_file.key_confidence is not None

    reopened = MutagenFile(dest)
    assert reopened.tags.get("TBPM") is not None
    assert str(reopened.tags["TKEY"]) == local_file.camelot_key

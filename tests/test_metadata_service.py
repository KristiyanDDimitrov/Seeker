import shutil
import wave
from pathlib import Path

import httpx
import pytest
from mutagen import File as MutagenFile

from seeker.album_art_cache import AlbumArtCache
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
from seeker.library.metadata_service import (
    MetadataService,
    PlaylistNotFoundError,
)
from seeker.models.library_location import LibraryLocation
from seeker.models.local_file import LocalFile
from seeker.models.playlist import Playlist
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


def make_service(tmp_path, get_config=None) -> MetadataService:
    database = Database(tmp_path / "seeker.db")
    database.initialize()

    return MetadataService(
        database,
        TrackRepository(database),
        TrackMatchRepository(database),
        LocalFileRepository(database),
        LibraryLocationRepository(database),
        PlaylistRepository(database),
        # An isolated, per-test cache dir — the default MetadataService()
        # constructor otherwise points at the REAL, persistent
        # platformdirs cache path, which would let one test's cached
        # art silently satisfy another test's "was this genuinely
        # re-downloaded" assertion.
        album_art_cache=AlbumArtCache(tmp_path / "art_cache"),
        get_config=get_config,
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


def test_tag_tracks_track_not_found_reports_clear_failure(tmp_path):
    # A stale/nonexistent track_id — previously would have crashed with
    # a raw AttributeError ('NoneType' has no attribute 'artist') caught
    # generically by tag_tracks()'s outer try/except; now gets a clear,
    # specific message instead.
    service = make_service(tmp_path)

    counts = service.tag_tracks(["nonexistent-track"])

    assert counts["tagged"] == 0
    assert counts["failed"] == 1
    assert counts["details"][0]["reason"] == "failed"
    assert "not found" in counts["details"][0]["message"]


def test_tag_playlist_raises_when_playlist_not_synced(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(PlaylistNotFoundError, match="never-synced"):
        service.tag_playlist("never-synced")


def test_tag_playlist_tags_only_auto_matched_tracks(tmp_path, monkeypatch):
    # tag_playlist must filter to auto-matched tracks before delegating
    # to tag_tracks — a needs_review/unmatched track has no confirmed
    # local file, so it must never even be attempted.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "auto-track", "song.wav")

    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="Test Playlist", track_count=2),
            connection,
        )
        service.tracks.save(
            Track(
                id="unmatched-track",
                title="No Match",
                artist="Nobody",
                album="Nothing",
                duration_ms=1000,
            ),
            connection,
        )
        service.tracks.save_playlist_track("p1", "auto-track", connection)
        service.tracks.save_playlist_track(
            "p1", "unmatched-track", connection
        )

    counts = service.tag_playlist("Test Playlist")

    assert counts["tagged"] == 1
    tagged_ids = {d["track_id"] for d in counts["details"]}
    assert "unmatched-track" not in tagged_ids


def test_tag_tracks_mid_batch_exception_does_not_abort_remaining_tracks(
        tmp_path, monkeypatch,
):
    # Same "one bad item must not abort the batch" guarantee verified
    # for download_playlist/poll_downloads (see CLAUDE.md STEP 4) —
    # tag_tracks wraps _tag_one_track per-track for the same reason.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "good-track", "song.wav")

    original = MetadataService._tag_one_track
    call_count = {"n": 0}

    def flaky_tag_one_track(self, track_id, *args, **kwargs):
        call_count["n"] += 1
        if track_id == "bad-track":
            raise RuntimeError("simulated failure")
        return original(self, track_id, *args, **kwargs)

    monkeypatch.setattr(
        MetadataService, "_tag_one_track", flaky_tag_one_track
    )

    counts = service.tag_tracks(["bad-track", "good-track"])

    assert call_count["n"] == 2
    assert counts["failed"] == 1
    assert counts["tagged"] == 1
    failed_detail = next(
        d for d in counts["details"] if d["track_id"] == "bad-track"
    )
    assert failed_detail["reason"] == "failed"
    assert "simulated failure" in failed_detail["message"]


def test_tag_tracks_skips_when_mutagen_cannot_identify_file(tmp_path):
    # Distinct from skips_unrecognized_format above: this is mutagen
    # failing to identify the file at all (File() returns None), not
    # identifying it but write_text_tags lacking support for the type.
    # Confirmed live: unlike most formats, mutagen's .m4a/.ogg parsers
    # return None for unparseable content rather than raising, so those
    # are the only extensions that can genuinely reach this branch — a
    # garbage .mp3/.flac/.wav/.aac raises instead and is caught by
    # tag_tracks()'s outer per-track exception handler as "failed".
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "not-audio.m4a"
    dest.write_bytes(b"this is not a real audio file")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "t1", "not-audio.m4a")

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 0
    assert counts["skipped_format_unsupported"] == 1
    assert counts["details"][0]["reason"] == "skipped_format_unsupported"


def test_tag_tracks_album_art_failure_does_not_block_text_tags(
        tmp_path, monkeypatch,
):
    # Art is explicitly best-effort — a download/embed failure must not
    # sink an otherwise-successful text-tag write.
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
        album_art_url="https://i.scdn.co/image/fake",
    )

    def failing_get(url, timeout=None):
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(httpx, "get", failing_get)

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 1
    assert counts["failed"] == 0
    # Roadmap item 56 Phase 4.2 — the real fix: this used to be
    # completely invisible (the track just silently counted as plain
    # "tagged", identical to a genuine full success).
    assert counts["tagged_without_art"] == 1
    art_details = [
        d for d in counts["details"]
        if d["reason"] == "tagged_without_art_download_failed"
    ]
    assert len(art_details) == 1
    assert "simulated network failure" in art_details[0]["message"]

    reopened = MutagenFile(dest)
    assert str(reopened.tags["TIT2"]) == "Test Title"
    assert reopened.tags.get("APIC:Cover") is None


def test_tag_tracks_no_album_art_url_reports_actionable_reason(tmp_path):
    # Roadmap item 56 Phase 4.2 — a track whose album_art_url was never
    # populated (e.g. synced before item 10, or by a code path that
    # doesn't set it) must not just silently skip art with no
    # explanation; the message must point at the real fix (re-sync).
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "song.wav", album_art_url=None,
    )

    counts = service.tag_tracks(["t1"])

    assert counts["tagged"] == 1
    assert counts["tagged_without_art"] == 1
    art_details = [
        d for d in counts["details"]
        if d["reason"] == "tagged_without_art_no_url"
    ]
    assert len(art_details) == 1
    assert "sync-tracks" in art_details[0]["message"]


def test_tag_tracks_analyze_audio_failure_does_not_block_text_tags(
        tmp_path, monkeypatch,
):
    # Same best-effort treatment as album art: an analysis failure must
    # not undo the text-tag write that already happened.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "t1", "song.wav")

    def failing_analysis(file_path, expected_bpm_range=None):
        raise RuntimeError("simulated analysis failure")

    monkeypatch.setattr(
        "seeker.library.metadata_service.run_audio_analysis",
        failing_analysis,
    )

    counts = service.tag_tracks(["t1"], analyze_audio=True)

    assert counts["tagged"] == 1
    assert counts["failed"] == 0

    reopened = MutagenFile(dest)
    assert str(reopened.tags["TIT2"]) == "Test Title"
    assert reopened.tags.get("TBPM") is None

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
    assert local_file.bpm is None


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
    assert counts["tagged_without_art"] == 0
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


def test_tag_tracks_detail_message_names_the_location_relative_path(
        tmp_path,
):
    # Roadmap item 93 (B3.3) — a per-track detail message named only by
    # artist/title was indistinguishable from the same track/title
    # matched to a DIFFERENT file elsewhere in the library (the real B3
    # report, applied to the tagging result panel this time). Skipping
    # via already-tagged is the cheapest real path to a details entry.
    root = tmp_path / "music"
    dest = root / "Neuro" / "Real Artist - Real Title.mp3"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"fake-audio-bytes")

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "Neuro/Real Artist - Real Title.mp3",
        artist="Real Artist", title="Real Title",
    )

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "Neuro/Real Artist - Real Title.mp3", connection,
        )
        service.local_files.mark_tagged(
            local_file.id, "2026-08-27T00:00:00+00:00", connection,
        )

    result = service.tag_tracks(["t1"])

    assert result["skipped_already_tagged"] == 1
    message = result["details"][0]["message"]
    assert "Neuro/Real Artist - Real Title.mp3" in message
    assert "Real Artist - Real Title" in message


def test_tag_tracks_already_tagged_skips_art_download_but_still_analyzes(
        tmp_path, monkeypatch,
):
    # tagged_at already set -> the deterministic text/art write (and
    # specifically the album art re-download, the original motivation
    # for this check) must be skipped; --analyze-audio with bpm still
    # null must still run, independent of the tag-write skip.
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
        album_art_url="https://i.scdn.co/image/fake",
    )

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
        service.local_files.mark_tagged(
            local_file.id, "2026-08-27T00:00:00+00:00", connection
        )

    def fail_if_called(url, timeout=None):
        raise AssertionError(
            "album art must not be downloaded when already tagged"
        )

    monkeypatch.setattr(httpx, "get", fail_if_called)

    counts = service.tag_tracks(["t1"], analyze_audio=True)

    assert counts["tagged"] == 0
    assert counts["skipped_already_tagged"] == 1
    assert counts["skipped_already_analyzed"] == 0
    assert counts["failed"] == 0

    with service.database.transaction() as connection:
        after = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
    assert after.bpm is not None

    reopened = MutagenFile(dest)
    assert reopened.tags.get("TBPM") is not None
    # Text tags were never written this run — the synthetic WAV starts
    # with no tags at all, and the skip means write_text_tags is never
    # even called.
    assert reopened.tags.get("TIT2") is None


def test_tag_tracks_already_analyzed_skips_analysis_but_still_retags(
        tmp_path, monkeypatch,
):
    # bpm already set -> analysis specifically must be skipped, but the
    # deterministic text/art write (tagged_at still null) must still
    # happen normally.
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
        album_art_url="https://i.scdn.co/image/fake",
    )

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
        service.local_files.update_analysis(
            local_file.id, 161.499, "3A", 0.477, connection
        )

    monkeypatch.setattr(httpx, "get", _fake_jpeg_response)

    def fail_if_called(file_path, expected_bpm_range=None):
        raise AssertionError(
            "audio analysis must not run when bpm is already set"
        )

    monkeypatch.setattr(
        "seeker.library.metadata_service.run_audio_analysis",
        fail_if_called,
    )

    counts = service.tag_tracks(["t1"], analyze_audio=True)

    assert counts["tagged"] == 1
    assert counts["skipped_already_tagged"] == 0
    assert counts["skipped_already_analyzed"] == 1
    assert counts["failed"] == 0

    with service.database.transaction() as connection:
        after = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
    # Analysis was skipped, so the pre-existing values are untouched.
    assert after.bpm == 161.499
    assert after.camelot_key == "3A"
    assert after.tagged_at is not None

    reopened = MutagenFile(dest)
    assert str(reopened.tags["TIT2"]) == "Test Title"
    assert reopened.tags["APIC:Cover"].data == FAKE_JPEG_BYTES


def test_tag_tracks_force_bypasses_both_skip_checks_independently(
        tmp_path, monkeypatch,
):
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
        album_art_url="https://i.scdn.co/image/fake",
    )

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
        service.local_files.mark_tagged(
            local_file.id, "2026-08-27T00:00:00+00:00", connection
        )
        service.local_files.update_analysis(
            local_file.id, 161.499, "3A", 0.477, connection
        )

    art_calls = {"n": 0}

    def counting_get(url, timeout=None):
        art_calls["n"] += 1
        return _fake_jpeg_response(url, timeout)

    monkeypatch.setattr(httpx, "get", counting_get)

    counts = service.tag_tracks(["t1"], analyze_audio=True, force=True)

    assert counts["tagged"] == 1
    assert counts["skipped_already_tagged"] == 0
    assert counts["skipped_already_analyzed"] == 0
    assert art_calls["n"] == 1

    with service.database.transaction() as connection:
        after = service.local_files.get_by_location_and_relative_path(
            location.id, "song.wav", connection
        )
    # Force re-ran analysis for real — a genuinely fresh bpm (synthetic
    # silent audio), not the stale 161.499 seeded above.
    assert after.bpm != 161.499

    reopened = MutagenFile(dest)
    assert str(reopened.tags["TIT2"]) == "Test Title"
    assert reopened.tags["APIC:Cover"].data == FAKE_JPEG_BYTES


def test_tag_tracks_real_already_tagged_track_is_skipped_not_reprocessed(
        tmp_path, monkeypatch,
):
    # Base case from the real, already-tagged 240KM/H run (see
    # CLAUDE.md item 10/11): the real 3amdisco WAV was tagged for real
    # earlier today with TIT2/TPE1/TALB="Get Back"/"3amdisco"/"Get Back
    # EP" and analyzed to bpm=161.499/camelot_key="3A". A copy of that
    # already-fully-processed file, with tagged_at/bpm set to match,
    # must now be skipped entirely on a normal re-run rather than
    # silently re-tagged and re-analyzed.
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "3AMDISCO - Get Back.wav"
    make_synthetic_wav(dest)

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

    with service.database.transaction() as connection:
        local_file = service.local_files.get_by_location_and_relative_path(
            location.id, "3AMDISCO - Get Back.wav", connection
        )
        service.local_files.mark_tagged(
            local_file.id, "2026-08-27T00:00:00+00:00", connection
        )
        service.local_files.update_analysis(
            local_file.id, 161.499, "3A", 0.477, connection
        )

    def fail_if_art_called(url, timeout=None):
        raise AssertionError("must not re-download art on a skipped track")

    def fail_if_analysis_called(file_path, expected_bpm_range=None):
        raise AssertionError("must not re-analyze a skipped track")

    monkeypatch.setattr(httpx, "get", fail_if_art_called)
    monkeypatch.setattr(
        "seeker.library.metadata_service.run_audio_analysis",
        fail_if_analysis_called,
    )

    counts = service.tag_tracks(["t1"], analyze_audio=True)

    assert counts["tagged"] == 0
    assert counts["skipped_already_tagged"] == 1
    assert counts["skipped_already_analyzed"] == 1
    assert counts["failed"] == 0


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


# --- fix_missing_art_for_playlist (roadmap item 66, Phase 5.2) ------------

def _seed_playlist_with_track(service: MetadataService, track_id: str) -> None:
    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="Test Playlist", track_count=1),
            connection,
        )
        service.tracks.save_playlist_track("p1", track_id, connection)


def test_fix_missing_art_raises_when_playlist_not_synced(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(PlaylistNotFoundError, match="never-synced"):
        service.fix_missing_art_for_playlist("never-synced")


def test_fix_missing_art_embeds_when_none_exists(tmp_path, monkeypatch):
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "song.wav",
        album_art_url="https://i.scdn.co/image/fake",
    )
    _seed_playlist_with_track(service, "t1")

    monkeypatch.setattr(httpx, "get", _fake_jpeg_response)

    counts = service.fix_missing_art_for_playlist("Test Playlist")

    # Roadmap item 75 (P6, 6.4) — a WAV file's art gets embedded for
    # real (confirmed below via a real re-read), but counted in its own
    # honest bucket, not plain "fixed" — essentially no real DJ
    # software reads embedded art from WAV.
    assert counts["fixed"] == 0
    assert counts["fixed_wav_rarely_supported"] == 1
    assert counts["already_correct"] == 0
    assert counts["failed"] == 0

    reopened = MutagenFile(dest)
    assert reopened.tags["APIC:Cover"].data == FAKE_JPEG_BYTES


def test_fix_missing_art_skips_when_already_byte_correct_and_never_touches_text(
        tmp_path, monkeypatch,
):
    # The actual point of this action: a file whose embedded art
    # already matches the real current CDN bytes gets no write at all
    # -- proven here by seeding a WRONG text tag first and confirming
    # it's still wrong afterward (text tags are never touched by this
    # action, only art).
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    mutagen_file = MutagenFile(dest)
    mutagen_file.add_tags()
    from mutagen.id3 import APIC, TIT2
    mutagen_file.tags.setall(
        "APIC",
        [
            APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=FAKE_JPEG_BYTES,
            ),
        ],
    )
    mutagen_file.tags.setall(
            "TIT2",
            [TIT2(encoding=3, text=["Untouched Title"])],
    )
    mutagen_file.save()

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(
        service, location, "t1", "song.wav",
        title="Real Spotify Title",
        album_art_url="https://i.scdn.co/image/fake",
    )
    _seed_playlist_with_track(service, "t1")

    def fail_if_called(url, timeout=None):
        raise AssertionError(
            "should not re-download art that's already byte-correct"
        )

    monkeypatch.setattr(httpx, "get", _fake_jpeg_response)
    # First call is allowed (to compare against); patch a counting
    # wrapper so a SECOND real fix run makes no further real call.
    calls = {"n": 0}

    def counting_get(url, timeout=None):
        calls["n"] += 1
        return _fake_jpeg_response(url, timeout)

    monkeypatch.setattr(httpx, "get", counting_get)

    counts = service.fix_missing_art_for_playlist("Test Playlist")

    assert counts["fixed"] == 0
    assert counts["already_correct"] == 1

    reopened = MutagenFile(dest)
    # Text tag is exactly what was seeded, NOT the real Spotify title --
    # proof this action never rewrites text tags.
    assert str(reopened.tags["TIT2"]) == "Untouched Title"
    assert reopened.tags["APIC:Cover"].data == FAKE_JPEG_BYTES


def test_fix_missing_art_reports_no_url(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    dest = root / "song.wav"
    make_synthetic_wav(dest)

    service = make_service(tmp_path)
    location = seed_location(service, root)
    seed_matched_track(service, location, "t1", "song.wav", album_art_url=None)
    _seed_playlist_with_track(service, "t1")

    counts = service.fix_missing_art_for_playlist("Test Playlist")

    assert counts["fixed"] == 0
    assert counts["no_url"] == 1
    assert counts["details"][0]["reason"] == "no_url"


def test_fix_missing_art_only_touches_auto_matched_tracks(tmp_path):
    # get_auto_matched_for_playlist already filters to match_method=
    # 'auto' at the SQL level -- a needs_review track is structurally
    # never even returned, not just skipped at runtime.
    root = tmp_path / "music"
    root.mkdir()

    service = make_service(tmp_path)
    with service.database.transaction() as connection:
        service.playlists.save(
            Playlist(id="p1", name="Test Playlist", track_count=1),
            connection,
        )
        service.tracks.save(
            Track(
                id="needs-review-track", title="T", artist="A", album="Al",
                duration_ms=1000, album_art_url="https://i.scdn.co/image/fake",
            ),
            connection,
        )
        service.tracks.save_playlist_track(
            "p1", "needs-review-track", connection
        )
        service.track_matches.upsert(
            TrackMatch(
                track_id="needs-review-track",
                local_file_id=None,
                match_method="needs_review",
                score=75.0,
                matched_at="2026-01-01",
            ),
            connection,
        )

    counts = service.fix_missing_art_for_playlist("Test Playlist")

    assert counts["fixed"] == 0
    assert counts["no_url"] == 0
    assert counts["skipped_no_match"] == 0
    assert counts["details"] == []

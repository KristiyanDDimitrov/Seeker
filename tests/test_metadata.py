import shutil
from pathlib import Path

import pytest
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from seeker.metadata import embed_album_art, write_text_tags


# Real files from the scanned x9-pro library, used to test tag-writing
# against genuine format quirks rather than hand-rolled fixtures. Always
# copied to tmp_path before being touched — the originals are never
# opened for writing. Skipped (not failed) when the drive isn't mounted,
# the same way the rest of the app treats an unreachable library location.
X9_PRO_ROOT = Path("/Volumes/X9 Pro")
REAL_MP3 = (
    X9_PRO_ROOT
    / "Music/Psytrance/ Eye Contact - Juliet Fox, Giorgia Angiuli"
      " (Extended Mix).mp3"
)
REAL_FLAC = (
    X9_PRO_ROOT / "Music/Psytrance/Giorgia Angiuli - Lux (Original Mix).flac"
)
REAL_M4A = X9_PRO_ROOT / "Music/DnB/ChaseR - Prolegomenon.m4a"

requires_x9_pro = pytest.mark.skipif(
    not X9_PRO_ROOT.is_dir(),
    reason="x9-pro drive not mounted",
)

FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 256


@requires_x9_pro
def test_embed_album_art_mp3_round_trips(tmp_path):
    dest = tmp_path / "test.mp3"
    shutil.copy(REAL_MP3, dest)

    audio = MutagenFile(dest)
    embedded = embed_album_art(audio, FAKE_JPEG_BYTES, "image/jpeg")
    audio.save()

    assert embedded is True

    reopened = MutagenFile(dest)
    apic = reopened.tags.get("APIC:Cover")

    assert apic is not None
    assert apic.data == FAKE_JPEG_BYTES
    assert apic.mime == "image/jpeg"


@requires_x9_pro
def test_embed_album_art_flac_round_trips(tmp_path):
    dest = tmp_path / "test.flac"
    shutil.copy(REAL_FLAC, dest)

    audio = FLAC(dest)
    embedded = embed_album_art(audio, FAKE_JPEG_BYTES, "image/jpeg")
    audio.save()

    assert embedded is True

    reopened = FLAC(dest)

    assert len(reopened.pictures) == 1
    assert reopened.pictures[0].data == FAKE_JPEG_BYTES
    assert reopened.pictures[0].mime == "image/jpeg"


@requires_x9_pro
def test_embed_album_art_mp4_round_trips(tmp_path):
    dest = tmp_path / "test.m4a"
    shutil.copy(REAL_M4A, dest)

    audio = MP4(dest)
    embedded = embed_album_art(audio, FAKE_JPEG_BYTES, "image/jpeg")
    audio.save()

    assert embedded is True

    reopened = MP4(dest)
    covr = reopened.tags.get("covr")

    assert covr is not None
    assert bytes(covr[0]) == FAKE_JPEG_BYTES


@requires_x9_pro
def test_write_text_tags_mp3_round_trips(tmp_path):
    dest = tmp_path / "test.mp3"
    shutil.copy(REAL_MP3, dest)

    audio = MutagenFile(dest)
    write_text_tags(audio, "Test Artist", "Test Title", "Test Album")
    audio.save()

    reopened = MutagenFile(dest)

    assert str(reopened.tags["TIT2"]) == "Test Title"
    assert str(reopened.tags["TPE1"]) == "Test Artist"
    assert str(reopened.tags["TALB"]) == "Test Album"


@requires_x9_pro
def test_write_text_tags_flac_round_trips(tmp_path):
    dest = tmp_path / "test.flac"
    shutil.copy(REAL_FLAC, dest)

    audio = FLAC(dest)
    write_text_tags(audio, "Test Artist", "Test Title", "Test Album")
    audio.save()

    reopened = FLAC(dest)

    assert reopened["title"] == ["Test Title"]
    assert reopened["artist"] == ["Test Artist"]
    assert reopened["album"] == ["Test Album"]


class _FakeUnsupportedFile:
    def __init__(self):
        self.tags = object()


def test_embed_album_art_returns_false_for_unsupported_format():
    result = embed_album_art(
        _FakeUnsupportedFile(), FAKE_JPEG_BYTES, "image/jpeg"
    )

    assert result is False


def test_write_text_tags_raises_for_unsupported_format():
    with pytest.raises(ValueError):
        write_text_tags(_FakeUnsupportedFile(), "Artist", "Title", "Album")

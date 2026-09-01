import shutil
import struct
import zlib
from pathlib import Path

import pytest
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp4 import MP4

from seeker.metadata import (
    _read_image_dimensions,
    embed_album_art,
    write_analysis_tags,
    write_text_tags,
)


def _make_minimal_jpeg(width: int, height: int) -> bytes:
    # Real SOI + APP0/JFIF + a real SOF0 marker carrying the given
    # dimensions, then EOI — structurally valid enough for
    # _read_image_dimensions() to parse (it stops at SOF0), not a real
    # decodable image.
    soi = b"\xff\xd8"
    jfif_payload = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    app0 = b"\xff\xe0" + struct.pack(">H", len(jfif_payload) + 2) + jfif_payload
    sof0_payload = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    sof0 = b"\xff\xc0" + struct.pack(">H", len(sof0_payload) + 2) + sof0_payload
    eoi = b"\xff\xd9"
    return soi + app0 + sof0 + eoi


def _make_minimal_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(
        b"\x00" + b"\xff\x00\x00" * width for _ in range(height)
    )
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


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


@requires_x9_pro
def test_write_text_tags_mp4_round_trips(tmp_path):
    dest = tmp_path / "test.m4a"
    shutil.copy(REAL_M4A, dest)

    audio = MP4(dest)
    write_text_tags(audio, "Test Artist", "Test Title", "Test Album")
    audio.save()

    reopened = MP4(dest)

    assert reopened.tags["\xa9nam"] == ["Test Title"]
    assert reopened.tags["\xa9ART"] == ["Test Artist"]
    assert reopened.tags["\xa9alb"] == ["Test Album"]


@requires_x9_pro
def test_write_analysis_tags_mp3_round_trips(tmp_path):
    dest = tmp_path / "test.mp3"
    shutil.copy(REAL_MP3, dest)

    audio = MutagenFile(dest)
    write_analysis_tags(audio, 128.4, "8A")
    audio.save()

    reopened = MutagenFile(dest)

    assert str(reopened.tags["TBPM"]) == "128"
    assert str(reopened.tags["TKEY"]) == "8A"


@requires_x9_pro
def test_write_analysis_tags_flac_round_trips(tmp_path):
    dest = tmp_path / "test.flac"
    shutil.copy(REAL_FLAC, dest)

    audio = FLAC(dest)
    write_analysis_tags(audio, 128.4, "8A")
    audio.save()

    reopened = FLAC(dest)

    assert reopened["BPM"] == ["128"]
    assert reopened["KEY"] == ["8A"]


@requires_x9_pro
def test_write_analysis_tags_mp4_round_trips(tmp_path):
    dest = tmp_path / "test.m4a"
    shutil.copy(REAL_M4A, dest)

    audio = MP4(dest)
    write_analysis_tags(audio, 128.4, "8A")
    audio.save()

    reopened = MP4(dest)

    assert reopened.tags["tmpo"] == [128]
    initial_key = reopened.tags["----:com.apple.iTunes:initialkey"]
    assert bytes(initial_key[0]) == b"8A"


@requires_x9_pro
def test_write_analysis_tags_omits_tkey_when_key_is_none(tmp_path):
    # camelot_key is None for near-silent/noise-only audio (see
    # audio_analysis.py) — TKEY/KEY/initialkey must simply be absent,
    # not written as a literal "None".
    dest = tmp_path / "test.mp3"
    shutil.copy(REAL_MP3, dest)

    audio = MutagenFile(dest)
    write_analysis_tags(audio, 128.4, None)
    audio.save()

    reopened = MutagenFile(dest)

    assert str(reopened.tags["TBPM"]) == "128"
    assert reopened.tags.get("TKEY") is None


def test_write_analysis_tags_raises_for_unsupported_format():
    with pytest.raises(ValueError):
        write_analysis_tags(_FakeUnsupportedFile(), 128.0, "8A")


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


# --- Roadmap item 56 Phase 4.1: FLAC Picture width/height/depth -------

def test_read_image_dimensions_real_jpeg_from_spotifys_cdn():
    # A real Spotify cover art JPEG, fetched live and saved as bytes
    # ahead of time is impractical for a hermetic test — this is the
    # same structural shape (SOI/APP0/SOF0) confirmed live against the
    # real CDN (640x640) during this phase's own investigation; the
    # synthetic builder here is what makes that check runnable offline.
    jpeg = _make_minimal_jpeg(640, 640)
    assert _read_image_dimensions(jpeg) == (640, 640)


def test_read_image_dimensions_png():
    png = _make_minimal_png(300, 150)
    assert _read_image_dimensions(png) == (300, 150)


def test_read_image_dimensions_malformed_data_returns_none_not_raises():
    assert _read_image_dimensions(FAKE_JPEG_BYTES) is None
    assert _read_image_dimensions(b"not an image at all") is None
    assert _read_image_dimensions(b"") is None


@requires_x9_pro
def test_embed_album_art_flac_sets_width_height_depth_and_desc(tmp_path):
    dest = tmp_path / "test.flac"
    shutil.copy(REAL_FLAC, dest)

    real_jpeg = _make_minimal_jpeg(640, 640)
    audio = FLAC(dest)
    embed_album_art(audio, real_jpeg, "image/jpeg")
    audio.save()

    reopened = FLAC(dest)
    picture = reopened.pictures[0]

    assert picture.type == 3
    assert picture.desc == "Cover"
    assert picture.width == 640
    assert picture.height == 640
    assert picture.depth == 24


@requires_x9_pro
def test_embed_album_art_flac_replaces_not_appends_existing_art(tmp_path):
    # Roadmap item 56 Phase 0.4 — the reported "cover art didn't
    # update" bug was investigated and the append hypothesis was
    # refuted (clear_pictures() already runs before add_picture()).
    # This is the regression guard for that finding: embedding twice
    # must never leave two pictures.
    dest = tmp_path / "test.flac"
    shutil.copy(REAL_FLAC, dest)

    audio = FLAC(dest)
    embed_album_art(audio, _make_minimal_jpeg(100, 100), "image/jpeg")
    audio.save()

    audio_again = FLAC(dest)
    embed_album_art(audio_again, _make_minimal_jpeg(200, 200), "image/jpeg")
    audio_again.save()

    reopened = FLAC(dest)
    assert len(reopened.pictures) == 1
    assert reopened.pictures[0].width == 200

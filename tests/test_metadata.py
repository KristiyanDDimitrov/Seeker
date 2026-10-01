import shutil
import struct
import wave
import zlib
from pathlib import Path

import mutagen.id3
import pytest
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.mp4 import MP4, MP4Cover

from seeker.audio.tags import (
    _read_image_dimensions,
    embed_album_art,
    read_embedded_art,
    save_tags,
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
    app0 = b"\xff\xe0" + struct.pack(
            ">H",
            len(jfif_payload) + 2,
    ) + jfif_payload
    sof0_payload = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    sof0 = b"\xff\xc0" + struct.pack(
            ">H",
            len(sof0_payload) + 2,
    ) + sof0_payload
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
    return sig + chunk(
            b"IHDR",
            ihdr,
    ) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


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
# Roadmap item R1.6 -- the exact real folder the brief's own diagnosis
# named ("beatport_tracks_2023-11 copy"), confirmed live on this machine
# to contain real .aiff files.
REAL_AIFF = (
    X9_PRO_ROOT
    / "Music/beatport_tracks_2023-11 copy/8Kays - Morning After The Rave.aiff"
)

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


# --- Roadmap item 75 (P6, 6.3): save_tags writes ID3v2.3, not mutagen's
# default v2.4 (real DJ software is markedly more reliable with v2.3) ---

def _make_synthetic_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44_100)
        handle.writeframes(b"\x00\x00" * 44_100)


def test_save_tags_writes_id3v23_for_wav(tmp_path):
    # WAV's _WaveID3 is a genuine ID3 subclass (see embed_album_art's
    # own docstring) -- save_tags must dispatch it through the same
    # v2_version=3 path as a real MP3, not fall through to plain
    # save().
    dest = tmp_path / "test.wav"
    _make_synthetic_wav(dest)

    audio = MutagenFile(dest)
    write_text_tags(audio, "Artist", "Title", "Album")
    save_tags(audio)

    # A WAV's ID3 chunk lives inside the RIFF container, not at byte 0
    # -- mutagen.id3.ID3() (a plain ID3-at-offset-0 reader) can't parse
    # it; re-open via the same auto-detecting File() the rest of this
    # module uses, whose .tags is the real _WaveID3.
    reopened = MutagenFile(dest)
    assert reopened.tags.version == (2, 3, 0)


@requires_x9_pro
def test_save_tags_writes_id3v23_for_aiff(tmp_path):
    # Roadmap item R1.6 -- live-verified against a real file from the
    # exact folder the brief's diagnosis named. AIFF's _IFFID3 is a
    # genuine ID3 subclass (mutagen/aiff.py -- confirmed live, mutagen
    # 1.48.1), same shape as WAV's _WaveID3 above.
    dest = tmp_path / "test.aiff"
    shutil.copy(REAL_AIFF, dest)

    audio = MutagenFile(dest)
    write_text_tags(audio, "Artist", "Title", "Album")
    save_tags(audio)

    reopened = MutagenFile(dest)
    assert reopened.tags.version == (2, 3, 0)
    assert reopened.tags.get("TIT2").text == ["Title"]


@requires_x9_pro
def test_embed_album_art_aiff_round_trips(tmp_path):
    dest = tmp_path / "test.aiff"
    shutil.copy(REAL_AIFF, dest)

    audio = MutagenFile(dest)
    embedded = embed_album_art(audio, FAKE_JPEG_BYTES, "image/jpeg")
    save_tags(audio)

    assert embedded is True

    reopened = MutagenFile(dest)
    apic = reopened.tags.get("APIC:Cover")

    assert apic is not None
    assert apic.data == FAKE_JPEG_BYTES
    assert apic.mime == "image/jpeg"


@requires_x9_pro
def test_save_tags_writes_id3v23_for_mp3(tmp_path):
    dest = tmp_path / "test.mp3"
    shutil.copy(REAL_MP3, dest)

    audio = MutagenFile(dest)
    write_text_tags(audio, "Artist", "Title", "Album")
    save_tags(audio)

    reopened = mutagen.id3.ID3(dest)
    assert reopened.version == (2, 3, 0)


@requires_x9_pro
def test_save_tags_leaves_flac_save_untouched(tmp_path):
    # save_tags dispatches on isinstance(tags, ID3) -- a FLAC file's
    # save() takes no v2_version kwarg at all, so this must fall
    # through to a plain save() rather than raise.
    dest = tmp_path / "test.flac"
    shutil.copy(REAL_FLAC, dest)

    audio = FLAC(dest)
    write_text_tags(audio, "Artist", "Title", "Album")
    save_tags(audio)  # must not raise

    reopened = FLAC(dest)
    assert reopened["title"] == ["Title"]


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
    # audio/analysis.py) — TKEY/KEY/initialkey must simply be absent,
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


# --- Every format, on files generated per test ---------------------------
#
# The x9-pro tests above exercise real files' quirks but skip wherever
# the drive isn't mounted, CI included. These run everywhere: soundfile
# writes MP3, FLAC, AIFF and WAV; it has no MP4 writer, so M4A copies
# `fixtures/silent.m4a` (0.5 s of silent AAC, tag-free, made with
# ffmpeg — see HISTORY §167). Every file starts with no tags, so the
# first write also exercises each format's tag creation.

M4A_FIXTURE = Path(__file__).parent / "fixtures" / "silent.m4a"

ALL_FORMATS = ["mp3", "flac", "aiff", "wav", "m4a"]
ID3_FORMATS = ["mp3", "aiff", "wav"]

# Where each format keeps title, artist and album — the frame and atom
# names from the ID3v2, Vorbis comment and iTunes MP4 conventions.
TEXT_TAG_KEYS = {
    "mp3": ("TIT2", "TPE1", "TALB"),
    "aiff": ("TIT2", "TPE1", "TALB"),
    "wav": ("TIT2", "TPE1", "TALB"),
    "flac": ("title", "artist", "album"),
    "m4a": ("\xa9nam", "\xa9ART", "\xa9alb"),
}


@pytest.fixture
def generated_audio(request, tmp_path) -> Path:
    import numpy as np
    import soundfile as sf

    extension = request.param
    path = tmp_path / f"generated.{extension}"

    if extension == "m4a":
        shutil.copy(M4A_FIXTURE, path)
    else:
        sf.write(
            path, np.zeros(22_050, dtype="float32"), 44_100,
            format=extension.upper(),
        )

    return path


def _tag_text(audio, key: str) -> str:
    value = audio.tags[key]
    if isinstance(value, list):
        return value[0]
    return str(value)


@pytest.mark.parametrize("generated_audio", ALL_FORMATS, indirect=True)
def test_text_tags_round_trip(generated_audio):
    audio = MutagenFile(generated_audio)
    write_text_tags(audio, "Test Artist", "Test Title", "Test Album")
    save_tags(audio)

    reopened = MutagenFile(generated_audio)
    title_key, artist_key, album_key = TEXT_TAG_KEYS[
        generated_audio.suffix[1:]
    ]

    assert _tag_text(reopened, title_key) == "Test Title"
    assert _tag_text(reopened, artist_key) == "Test Artist"
    assert _tag_text(reopened, album_key) == "Test Album"


@pytest.mark.parametrize("generated_audio", ALL_FORMATS, indirect=True)
def test_untagged_file_has_no_embedded_art(generated_audio):
    assert read_embedded_art(MutagenFile(generated_audio)) is None


@pytest.mark.parametrize("generated_audio", ALL_FORMATS, indirect=True)
@pytest.mark.parametrize(
    ("image", "mime_type"),
    [
        (_make_minimal_jpeg(64, 64), "image/jpeg"),
        (_make_minimal_png(64, 64), "image/png"),
    ],
    ids=["jpeg", "png"],
)
def test_album_art_round_trips(generated_audio, image, mime_type):
    audio = MutagenFile(generated_audio)
    write_text_tags(audio, "Artist", "Title", "Album")
    assert embed_album_art(audio, image, mime_type) is True
    save_tags(audio)

    assert read_embedded_art(MutagenFile(generated_audio)) == image


@pytest.mark.parametrize("generated_audio", ["m4a"], indirect=True)
def test_mp4_cover_records_its_image_format(generated_audio):
    audio = MutagenFile(generated_audio)
    embed_album_art(audio, _make_minimal_png(8, 8), "image/png")
    save_tags(audio)

    cover = MutagenFile(generated_audio).tags["covr"][0]
    assert cover.imageformat == MP4Cover.FORMAT_PNG


# BPM and key: ID3's TBPM/TKEY, the Vorbis comments BPM/KEY, and the
# MP4 `tmpo` atom plus iTunes' `initialkey` freeform atom.
def _analysis_values(audio, extension: str) -> tuple[str, str | None]:
    if extension in ID3_FORMATS:
        key = audio.tags.get("TKEY")
        return str(audio.tags["TBPM"]), str(key) if key else None
    if extension == "flac":
        return audio["BPM"][0], (audio.get("KEY") or [None])[0]
    initial_key = audio.tags.get("----:com.apple.iTunes:initialkey")
    return (
        str(audio.tags["tmpo"][0]),
        bytes(initial_key[0]).decode() if initial_key else None,
    )


@pytest.mark.parametrize("generated_audio", ALL_FORMATS, indirect=True)
@pytest.mark.parametrize("camelot_key", ["8A", None])
def test_analysis_tags_round_trip(generated_audio, camelot_key):
    audio = MutagenFile(generated_audio)
    write_analysis_tags(audio, 127.6, camelot_key)
    save_tags(audio)

    reopened = MutagenFile(generated_audio)

    assert _analysis_values(reopened, generated_audio.suffix[1:]) == (
        "128", camelot_key,
    )


@pytest.mark.parametrize("generated_audio", ID3_FORMATS, indirect=True)
def test_save_tags_writes_id3v23(generated_audio):
    audio = MutagenFile(generated_audio)
    write_text_tags(audio, "Artist", "Title", "Album")
    save_tags(audio)

    assert MutagenFile(generated_audio).tags.version == (2, 3, 0)


@pytest.mark.parametrize("generated_audio", ["flac", "m4a"], indirect=True)
def test_save_tags_keeps_the_audio_readable(generated_audio):
    # FLAC and MP4 have no ID3 version to choose: save_tags must take
    # the plain save() and leave a file that still opens as audio.
    audio = MutagenFile(generated_audio)
    write_text_tags(audio, "Artist", "Title", "Album")
    embed_album_art(audio, _make_minimal_jpeg(640, 640), "image/jpeg")
    save_tags(audio)

    reopened = MutagenFile(generated_audio)
    assert reopened.info.length == pytest.approx(0.5, abs=0.05)


def test_read_image_dimensions_png_without_ihdr_returns_none():
    png = _make_minimal_png(10, 10)
    assert _read_image_dimensions(png[:12] + b"JUNK" + png[16:]) is None


def test_read_image_dimensions_skips_padding_and_standalone_markers():
    jpeg = _make_minimal_jpeg(320, 200)
    # A fill byte and a standalone RST0 marker between SOI and APP0
    # carry no length field; the reader must step over both.
    padded = jpeg[:2] + b"\x00" + b"\xff\xd0" + jpeg[2:]
    assert _read_image_dimensions(padded) == (320, 200)


def test_read_image_dimensions_truncated_sof_returns_none():
    jpeg = _make_minimal_jpeg(320, 200)
    sof_offset = jpeg.index(b"\xff\xc0")
    assert _read_image_dimensions(jpeg[:sof_offset + 6]) is None


@pytest.mark.parametrize("generated_audio", ["flac"], indirect=True)
def test_flac_picture_records_dimensions_only_when_readable(
        generated_audio,
):
    audio = MutagenFile(generated_audio)
    embed_album_art(audio, _make_minimal_jpeg(640, 480), "image/jpeg")
    save_tags(audio)
    picture = MutagenFile(generated_audio).pictures[0]
    assert (picture.type, picture.desc) == (3, "Cover")
    assert (picture.width, picture.height, picture.depth) == (640, 480, 24)

    audio = MutagenFile(generated_audio)
    embed_album_art(audio, FAKE_JPEG_BYTES, "image/jpeg")
    save_tags(audio)
    pictures = MutagenFile(generated_audio).pictures
    assert len(pictures) == 1
    assert (pictures[0].width, pictures[0].height) == (0, 0)


@pytest.mark.parametrize("generated_audio", ["flac"], indirect=True)
def test_flac_key_is_written_to_initialkey_and_key(generated_audio):
    # Vorbis comments have no standard key field. INITIALKEY is the
    # one TagLib-based software maps ID3's TKEY to, and Mixxx's
    # recommended field; KEY is the alternative Mixxx also reads and
    # MusicBrainz Picard writes. Both, so every DJ tool finds it.
    audio = MutagenFile(generated_audio)
    write_analysis_tags(audio, 124.0, "5A")
    save_tags(audio)

    reopened = MutagenFile(generated_audio)

    assert reopened["INITIALKEY"] == ["5A"]
    assert reopened["KEY"] == ["5A"]


@pytest.mark.parametrize("generated_audio", ["flac"], indirect=True)
def test_flac_without_a_key_writes_no_key_field(generated_audio):
    audio = MutagenFile(generated_audio)
    write_analysis_tags(audio, 124.0, None)
    save_tags(audio)

    reopened = MutagenFile(generated_audio)

    assert "INITIALKEY" not in reopened
    assert "KEY" not in reopened

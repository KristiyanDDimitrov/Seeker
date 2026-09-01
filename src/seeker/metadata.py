import struct
from typing import Any

from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC, TALB, TBPM, TIT2, TKEY, TPE1
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm


# Tag-writing helpers for Phase B (writing canonical Spotify metadata onto
# matched local files). Dispatches on the mutagen object's actual tag type
# rather than the file extension — confirmed live (mutagen 1.48.1) that
# WAVE's tag class (`_WaveID3`) is a genuine `ID3` subclass, so a WAV file
# uses the exact same APIC mechanism as an MP3 and round-trips a real
# embedded JPEG byte-exact. WAV is therefore NOT excluded from art
# embedding — it was assumed unsupported before this was checked directly;
# it isn't. See CLAUDE.md.
#
# `mutagen_file` is typed `Any` throughout, and mypy's disallow_untyped_calls
# is disabled for this module specifically (see pyproject.toml) — mutagen
# ships no type annotations at all (no py.typed marker, no types-mutagen
# package on PyPI, confirmed), so every call into it (TIT2(...), .setall(...),
# Picture(), etc.) would otherwise need its own per-line ignore. That's a
# real, acknowledged gap at this module's third-party boundary, not a silent
# one.


def write_text_tags(
        mutagen_file: Any,
        artist: str,
        title: str,
        album: str,
) -> None:
    if mutagen_file.tags is None:
        mutagen_file.add_tags()

    if isinstance(mutagen_file.tags, ID3):
        mutagen_file.tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
        mutagen_file.tags.setall("TPE1", [TPE1(encoding=3, text=[artist])])
        mutagen_file.tags.setall("TALB", [TALB(encoding=3, text=[album])])
        return

    if isinstance(mutagen_file, FLAC):
        mutagen_file["title"] = [title]
        mutagen_file["artist"] = [artist]
        mutagen_file["album"] = [album]
        return

    if isinstance(mutagen_file, MP4):
        mutagen_file.tags["\xa9nam"] = [title]
        mutagen_file.tags["\xa9ART"] = [artist]
        mutagen_file.tags["\xa9alb"] = [album]
        return

    raise ValueError(
        f"Unsupported tag format for text tags: "
        f"{type(mutagen_file).__name__}"
    )


def _read_image_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    """A minimal, dependency-free JPEG/PNG width/height reader — item
    56 Phase 4.1's "width/height where derivable" for FLAC Picture
    fields. No image library is a project dependency (Pillow would be a
    heavy addition for three metadata fields most players don't even
    require), and both formats' header layouts are small and stable
    enough to read directly. Returns None for anything else (or a
    malformed/truncated header) — best-effort, never raised.
    """
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        # IHDR is always the first chunk: 4-byte length, 4-byte type
        # "IHDR", then width/height as 4-byte big-endian ints.
        if len(image_bytes) >= 24 and image_bytes[12:16] == b"IHDR":
            width, height = struct.unpack(">II", image_bytes[16:24])
            return width, height
        return None

    if image_bytes[:2] == b"\xff\xd8":
        # JPEG: walk the marker stream for a real Start-Of-Frame marker
        # (0xC0-0xCF, excluding 0xC4/0xC8/0xCC which aren't SOF at all)
        # — its payload holds height then width as 2-byte big-endian
        # ints, right after a 1-byte sample precision.
        offset = 2
        length = len(image_bytes)

        while offset + 4 <= length:
            if image_bytes[offset] != 0xFF:
                offset += 1
                continue

            marker = image_bytes[offset + 1]

            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if offset + 9 > length:
                    return None
                height, width = struct.unpack(
                    ">HH", image_bytes[offset + 5:offset + 9]
                )
                return width, height

            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                offset += 2
                continue

            if offset + 4 > length:
                return None

            segment_length = struct.unpack(
                ">H", image_bytes[offset + 2:offset + 4]
            )[0]
            offset += 2 + segment_length

        return None

    return None


def embed_album_art(
        mutagen_file: Any,
        image_bytes: bytes,
        mime_type: str,
) -> bool:
    """Embed album art into an already-open mutagen file object, in
    whatever form its format actually supports. Returns True if
    embedded, False if this format has no known art mechanism — the
    caller should treat that as a partial-success skip (log and move on)
    rather than failing the whole track's tag write over one field.
    """
    if isinstance(mutagen_file.tags, ID3):
        mutagen_file.tags.setall(
            "APIC",
            [
                APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,  # front cover
                    desc="Cover",
                    data=image_bytes,
                )
            ],
        )
        return True

    if isinstance(mutagen_file, FLAC):
        picture = Picture()
        picture.type = 3
        picture.mime = mime_type
        picture.desc = "Cover"
        picture.data = image_bytes

        dimensions = _read_image_dimensions(image_bytes)
        if dimensions is not None:
            picture.width, picture.height = dimensions
            # Not independently derived — real-world cover art from
            # Spotify's CDN (and PNG/JPEG covers generally) is
            # overwhelmingly 24-bit RGB; a genuinely different depth
            # would need a real per-format color-type parse this
            # lightweight reader doesn't do. An honest, documented
            # assumption, not a computed fact.
            picture.depth = 24

        mutagen_file.clear_pictures()
        mutagen_file.add_picture(picture)
        return True

    if isinstance(mutagen_file, MP4):
        cover_format = (
            MP4Cover.FORMAT_PNG
            if mime_type == "image/png"
            else MP4Cover.FORMAT_JPEG
        )
        mutagen_file.tags["covr"] = [
            MP4Cover(image_bytes, imageformat=cover_format)
        ]
        return True

    print(
        f"  Skipping album art: unsupported tag format "
        f"({type(mutagen_file).__name__})."
    )
    return False


def write_analysis_tags(
        mutagen_file: Any,
        bpm: float,
        camelot_key: str | None,
) -> None:
    """Write BPM and (Camelot-notation) initial key onto an already-open
    mutagen file object — the actual standard frames/atoms DJ software
    reads. TKEY conventionally holds standard key notation per the
    ID3v2 spec, but stores the Camelot value here instead, matching what
    real-world DJ tagging tools commonly do since Camelot is the
    practical DJ-facing convention. Same unsupported-format contract as
    write_text_tags (raises ValueError) — analysis tags are core data
    when this is called, not a best-effort extra like album art.
    """
    if mutagen_file.tags is None:
        mutagen_file.add_tags()

    bpm_text = str(round(bpm))

    if isinstance(mutagen_file.tags, ID3):
        mutagen_file.tags.setall("TBPM", [TBPM(encoding=3, text=[bpm_text])])

        if camelot_key is not None:
            mutagen_file.tags.setall(
                "TKEY", [TKEY(encoding=3, text=[camelot_key])]
            )
        return

    if isinstance(mutagen_file, FLAC):
        mutagen_file["BPM"] = [bpm_text]

        if camelot_key is not None:
            mutagen_file["KEY"] = [camelot_key]
        return

    if isinstance(mutagen_file, MP4):
        mutagen_file.tags["tmpo"] = [round(bpm)]

        if camelot_key is not None:
            mutagen_file.tags["----:com.apple.iTunes:initialkey"] = [
                MP4FreeForm(camelot_key.encode("utf-8"))
            ]
        return

    raise ValueError(
        f"Unsupported tag format for analysis tags: "
        f"{type(mutagen_file).__name__}"
    )

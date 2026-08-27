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
        picture.data = image_bytes

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

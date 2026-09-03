from seeker.audio_formats import AUDIO_EXTENSIONS


def test_audio_extensions_includes_aiff_variants():
    # Roadmap item R1.1 — .aiff/.aif/.aifc were entirely invisible to
    # the app before this (library/scanner.py filters on this set, so
    # an unlisted extension is never indexed at all).
    assert ".aiff" in AUDIO_EXTENSIONS
    assert ".aif" in AUDIO_EXTENSIONS
    assert ".aifc" in AUDIO_EXTENSIONS


def test_audio_extensions_unchanged_for_pre_existing_formats():
    assert AUDIO_EXTENSIONS >= {
        ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg",
    }

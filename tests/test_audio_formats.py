from seeker.audio_formats import AUDIO_EXTENSIONS, quality_tier_for_format


def test_audio_extensions_includes_aiff_variants():
    # Roadmap item R1.1 — .aiff/.aif/.aifc were entirely invisible to
    # the app before this (library/scanner.py filters on this set, so
    # an unlisted extension is never indexed at all).
    assert ".aiff" in AUDIO_EXTENSIONS
    assert ".aif" in AUDIO_EXTENSIONS
    assert ".aifc" in AUDIO_EXTENSIONS


def test_audio_extensions_unchanged_for_pre_existing_formats():
    assert {
        ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg",
    } <= AUDIO_EXTENSIONS


def test_quality_tier_for_format_matches_lossless_lossy_unknown():
    assert quality_tier_for_format("flac") == 2
    assert quality_tier_for_format(".WAV") == 2
    assert quality_tier_for_format("mp3") == 1
    assert quality_tier_for_format(".M4A") == 1
    assert quality_tier_for_format("xyz") == 0


def test_quality_tier_for_format_aiff_is_lossless_aifc_is_not():
    # .aiff/.aif are genuinely uncompressed PCM; .aifc is a container
    # that CAN hold compressed audio, so it deliberately stays out of
    # LOSSLESS_EXTENSIONS (scores unknown/0 rather than falsely claiming
    # a lossless tier).
    assert quality_tier_for_format("aiff") == 2
    assert quality_tier_for_format(".AIF") == 2
    assert quality_tier_for_format("aifc") == 0

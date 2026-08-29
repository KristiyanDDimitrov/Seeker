import shutil
from pathlib import Path

import numpy as np
import pytest

from seeker import audio_fingerprint
from seeker.audio_fingerprint import (
    FingerprintingUnavailableError,
    compute_fingerprint,
    hamming_similarity,
    similarity_from_decoded,
)

X9_PRO_ROOT = Path("/Volumes/X9 Pro")

requires_x9_pro = pytest.mark.skipif(
    not X9_PRO_ROOT.is_dir(),
    reason="x9-pro drive not mounted",
)

requires_chromaprint = pytest.mark.skipif(
    audio_fingerprint._load_library() is None,
    reason="libchromaprint isn't installed on this machine",
)

# Two real duplicate pairs identified live against the real library
# during item 5's Phase 0 spike (see docs/HISTORY.md §38) — a
# same-format pair (two real MP3 copies of the same track, found
# across different Beatport-chart folders) and a cross-format pair
# (a real FLAC vs. a real lossy MP3 re-encode of the same track).
FISHER_COPY_1 = (
    X9_PRO_ROOT
    / "Music/Pop House/Beatport Tech House Top 100 March 2024"
    / "94. fisher (oz) - losing it (extended).mp3"
)
FISHER_COPY_2 = (
    X9_PRO_ROOT
    / "Music/Pop House/BEATPORT Top 100 Tech House September 2023"
    / "FISHER (OZ) - Losing It (Extended).mp3"
)
NEW_GOLD_FLAC = (
    X9_PRO_ROOT
    / "Music/House"
    / "Bootie Brown, Tame Impala, Gorillaz - New Gold (feat. Tame "
      "Impala and Bootie Brown) (Dom Dolla Remix Extended).flac"
)
NEW_GOLD_MP3 = (
    X9_PRO_ROOT
    / "Music/Pop House/Beatport Tech House Top 100 March 2024"
    / "69. bootie brown, tame impala, gorillaz - new gold (feat. "
      "tame impala and bootie brown) (dom dolla remix extended).mp3"
)


# --- Pure clustering logic: synthetic vectors, no real audio needed ------

def test_similarity_from_decoded_identical_arrays_is_one():
    a = np.array([0x12345678, 0xABCDEF01, 0x0], dtype=np.uint32)

    assert similarity_from_decoded(a, a.copy()) == 1.0


def test_similarity_from_decoded_fully_inverted_bits_is_zero():
    a = np.array([0x00000000, 0xFFFFFFFF], dtype=np.uint32)
    b = np.array([0xFFFFFFFF, 0x00000000], dtype=np.uint32)

    assert similarity_from_decoded(a, b) == 0.0


def test_similarity_from_decoded_known_partial_difference():
    # A single bit differs out of 32 total bits in a one-element array
    # -> similarity is exactly 31/32.
    a = np.array([0b0000], dtype=np.uint32)
    b = np.array([0b0001], dtype=np.uint32)

    assert similarity_from_decoded(a, b) == pytest.approx(31 / 32)


def test_similarity_from_decoded_empty_arrays_is_zero():
    empty = np.array([], dtype=np.uint32)

    assert similarity_from_decoded(empty, empty) == 0.0


def test_similarity_from_decoded_compares_over_shorter_length_only():
    # Real fingerprints from two files of slightly different length
    # (e.g. a few extra silent frames) won't be exactly the same size —
    # comparison must be bounded to the shorter one, not raise or
    # silently pad.
    a = np.array([1, 1, 1, 1], dtype=np.uint32)
    b = np.array([1, 1], dtype=np.uint32)

    assert similarity_from_decoded(a, b) == 1.0


# --- Lazy-loading contract: never raises at import time -------------------

def test_get_library_raises_clearly_when_library_not_found(monkeypatch):
    monkeypatch.setattr(audio_fingerprint, "_libchromaprint", None)
    monkeypatch.setattr(audio_fingerprint, "_load_attempted", False)
    monkeypatch.setattr(audio_fingerprint, "_load_library", lambda: None)

    with pytest.raises(FingerprintingUnavailableError):
        audio_fingerprint._get_library()


def test_compute_fingerprint_raises_the_unavailable_error_not_a_crash(
        monkeypatch, tmp_path,
):
    # A real, valid (if trivial) audio file — sf.info()/SoundFile() run
    # before the library is ever touched, so a nonexistent path would
    # fail there instead of exercising the thing this test is actually
    # about: a missing libchromaprint surfacing as our own clear error.
    import soundfile as sf

    path = tmp_path / "silence.wav"
    sf.write(str(path), np.zeros(1000, dtype=np.int16), 44100)

    monkeypatch.setattr(audio_fingerprint, "_libchromaprint", None)
    monkeypatch.setattr(audio_fingerprint, "_load_attempted", False)
    monkeypatch.setattr(audio_fingerprint, "_load_library", lambda: None)

    with pytest.raises(FingerprintingUnavailableError):
        compute_fingerprint(path)


# --- Real integration: real audio, real libchromaprint --------------------

@requires_x9_pro
@requires_chromaprint
def test_real_same_format_duplicates_score_high_similarity(tmp_path):
    copy_1 = tmp_path / "copy1.mp3"
    copy_2 = tmp_path / "copy2.mp3"
    shutil.copy(FISHER_COPY_1, copy_1)
    shutil.copy(FISHER_COPY_2, copy_2)

    fp1 = compute_fingerprint(copy_1)
    fp2 = compute_fingerprint(copy_2)

    assert hamming_similarity(fp1.data, fp2.data) > 0.95


@requires_x9_pro
@requires_chromaprint
def test_real_cross_format_duplicates_score_high_similarity(tmp_path):
    flac_copy = tmp_path / "copy.flac"
    mp3_copy = tmp_path / "copy.mp3"
    shutil.copy(NEW_GOLD_FLAC, flac_copy)
    shutil.copy(NEW_GOLD_MP3, mp3_copy)

    flac_fp = compute_fingerprint(flac_copy)
    mp3_fp = compute_fingerprint(mp3_copy)

    assert hamming_similarity(flac_fp.data, mp3_fp.data) > 0.95


@requires_x9_pro
@requires_chromaprint
def test_real_unrelated_tracks_score_well_below_duplicate_threshold(
        tmp_path,
):
    fisher_copy = tmp_path / "fisher.mp3"
    new_gold_copy = tmp_path / "new_gold.mp3"
    shutil.copy(FISHER_COPY_1, fisher_copy)
    shutil.copy(NEW_GOLD_MP3, new_gold_copy)

    fisher_fp = compute_fingerprint(fisher_copy)
    new_gold_fp = compute_fingerprint(new_gold_copy)

    assert hamming_similarity(fisher_fp.data, new_gold_fp.data) < 0.90


@requires_x9_pro
@requires_chromaprint
def test_compute_fingerprint_is_deterministic(tmp_path):
    dest = tmp_path / "test.mp3"
    shutil.copy(FISHER_COPY_1, dest)

    first = compute_fingerprint(dest)
    second = compute_fingerprint(dest)

    assert first.data == second.data
    assert first.duration_seconds == second.duration_seconds

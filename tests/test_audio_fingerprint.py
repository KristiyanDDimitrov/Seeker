import shutil
from pathlib import Path

import numpy as np
import pytest

from seeker import audio_fingerprint
from seeker.audio_fingerprint import (
    Fingerprint,
    FingerprintError,
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

requires_ffmpeg = pytest.mark.skipif(
    not audio_fingerprint._ffmpeg_available(),
    reason="ffmpeg isn't installed on this machine",
)

# Roadmap item 68 (Phase 8.1) — a real production file confirmed live to
# fail via soundfile ("bad data offset", libsndfile's MP3 frame-table
# parser rejecting it) but decode with zero errors via ffmpeg — one of
# 76 real failures found running `library fingerprint x9-pro` for real
# (see CLAUDE.md item 68 / docs/HISTORY.md for the full real breakdown).
REAL_SOUNDFILE_FAILS_FFMPEG_RESCUES = (
    X9_PRO_ROOT / "Music/Sinthesis/HiveMind.mp3"
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


# --- ffmpeg fallback orchestration: monkeypatched, no real ffmpeg/audio
# needed -- see the real end-to-end tests below for proof the fallback
# actually rescues real files (roadmap item 68, Phase 8.1). ------------

def test_compute_fingerprint_falls_back_to_ffmpeg_when_soundfile_fails(
        monkeypatch, tmp_path,
):
    sentinel = Fingerprint(data="ffmpeg-fingerprint", duration_seconds=12.0)

    def raise_soundfile_error(path):
        raise RuntimeError("bad data offset")

    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_soundfile",
        raise_soundfile_error,
    )
    monkeypatch.setattr(audio_fingerprint, "_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_ffmpeg",
        lambda path: sentinel,
    )

    result = compute_fingerprint(tmp_path / "broken.mp3")

    assert result is sentinel


def test_compute_fingerprint_reraises_original_error_when_ffmpeg_absent(
        monkeypatch, tmp_path,
):
    def raise_soundfile_error(path):
        raise RuntimeError("bad data offset")

    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_soundfile",
        raise_soundfile_error,
    )
    monkeypatch.setattr(audio_fingerprint, "_ffmpeg_available", lambda: False)

    with pytest.raises(RuntimeError, match="bad data offset"):
        compute_fingerprint(tmp_path / "broken.mp3")


def test_compute_fingerprint_raises_when_both_soundfile_and_ffmpeg_fail(
        monkeypatch, tmp_path,
):
    def raise_soundfile_error(path):
        raise RuntimeError("bad data offset")

    def raise_ffmpeg_error(path):
        raise FingerprintError("ffmpeg produced no audio data")

    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_soundfile",
        raise_soundfile_error,
    )
    monkeypatch.setattr(audio_fingerprint, "_ffmpeg_available", lambda: True)
    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_ffmpeg",
        raise_ffmpeg_error,
    )

    with pytest.raises(FingerprintError, match="soundfile failed.*ffmpeg"):
        compute_fingerprint(tmp_path / "broken.mp3")


def test_compute_fingerprint_never_tries_ffmpeg_when_chromaprint_missing(
        monkeypatch, tmp_path,
):
    # A missing libchromaprint is a config problem no fallback decoder
    # can fix -- must propagate immediately, not waste a real ffmpeg
    # subprocess call first.
    def raise_unavailable(path):
        raise FingerprintingUnavailableError("libchromaprint missing")

    ffmpeg_called = False

    def fake_ffmpeg_available():
        nonlocal ffmpeg_called
        ffmpeg_called = True
        return True

    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_soundfile",
        raise_unavailable,
    )
    monkeypatch.setattr(
        audio_fingerprint, "_ffmpeg_available", fake_ffmpeg_available,
    )

    with pytest.raises(FingerprintingUnavailableError):
        compute_fingerprint(tmp_path / "broken.mp3")

    assert not ffmpeg_called


def test_compute_fingerprint_succeeds_normally_without_touching_ffmpeg(
        monkeypatch, tmp_path,
):
    # The common case -- soundfile succeeds -- must never even check for
    # ffmpeg's presence.
    sentinel = Fingerprint(data="soundfile-fingerprint", duration_seconds=5.0)
    ffmpeg_checked = False

    def fake_ffmpeg_available():
        nonlocal ffmpeg_checked
        ffmpeg_checked = True
        return True

    monkeypatch.setattr(
        audio_fingerprint, "_compute_fingerprint_via_soundfile",
        lambda path: sentinel,
    )
    monkeypatch.setattr(
        audio_fingerprint, "_ffmpeg_available", fake_ffmpeg_available,
    )

    result = compute_fingerprint(tmp_path / "fine.wav")

    assert result is sentinel
    assert not ffmpeg_checked


# --- ffmpeg fallback, real end-to-end -------------------------------------

@requires_ffmpeg
@requires_chromaprint
def test_compute_fingerprint_via_ffmpeg_does_not_deadlock_on_heavy_stderr(
        tmp_path,
):
    # Roadmap item 68 (Phase 8.1) -- a REAL bug caught live building this
    # fallback, not a hypothetical: stderr was originally piped
    # (subprocess.PIPE) but never drained while the stdout-decode loop
    # ran. A file whose corruption produces one ffmpeg error line PER
    # BAD FRAME can log megabytes of stderr for a real multi-minute
    # track -- once that filled the OS's fixed-size pipe buffer (64KB
    # on macOS), ffmpeg blocked writing more stderr while this loop
    # was simultaneously blocked reading stdout, which ffmpeg could
    # never produce more of. Confirmed live: the fix's predecessor hung
    # indefinitely on one of the real 76-failure-set files. Fixed by
    # giving stderr a real tempfile instead of a pipe (a file write
    # never blocks on a reader keeping up) -- this test locks that in
    # with a synthetic file confirmed to reproduce >2MB of stderr
    # output (well over the 64KB pipe buffer that triggered the real
    # hang), run on a background thread with a bounded join() so a
    # regression fails the test instead of hanging the suite forever.
    import random
    import threading

    path = tmp_path / "heavy_stderr.mp3"
    rng = random.Random(42)
    with open(path, "wb") as f:
        # A real mp3 frame-sync byte pair followed by garbage, repeated
        # -- ffmpeg's mp3 probe treats this as mp3 and logs a decode
        # error per bad frame it finds, which is what produces the
        # heavy stderr volume this test needs.
        for _ in range(200_000):
            f.write(bytes([0xFF, 0xFB]) + bytes(rng.getrandbits(8) for _ in range(30)))

    result: dict = {}

    def run() -> None:
        try:
            result["fingerprint"] = (
                audio_fingerprint._compute_fingerprint_via_ffmpeg(path)
            )
        except Exception as error:
            result["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=30)

    assert not thread.is_alive(), (
        "compute_fingerprint_via_ffmpeg deadlocked on heavy stderr "
        "output -- the stderr-pipe fix regressed"
    )
    assert "fingerprint" in result or "error" in result


@requires_ffmpeg
@requires_chromaprint
def test_compute_fingerprint_via_ffmpeg_produces_a_usable_fingerprint(
        tmp_path,
):
    # A real, valid tone soundfile could ALSO decode -- this only proves
    # the ffmpeg decode path itself (chunked PCM read -> chromaprint feed
    # -> finish) produces a real, non-empty fingerprint end to end,
    # independent of the real production rescue case below (which needs
    # the real X9 Pro drive).
    import soundfile as sf

    path = tmp_path / "tone.wav"
    sample_rate = 44_100
    t = np.linspace(0, 2.0, int(sample_rate * 2.0))
    samples = (np.sin(2 * np.pi * 440.0 * t) * 0.3).astype(np.float32)
    sf.write(str(path), samples, sample_rate)

    result = audio_fingerprint._compute_fingerprint_via_ffmpeg(path)

    assert result.data
    assert result.duration_seconds == pytest.approx(2.0, abs=0.1)


@requires_x9_pro
@requires_chromaprint
@requires_ffmpeg
def test_real_production_file_soundfile_fails_but_ffmpeg_rescues_it():
    # Roadmap item 68 (Phase 8.1) -- the actual bug this phase exists to
    # fix, proven against the real file, not a synthetic stand-in.
    #
    # Deliberately NOT copied to tmp_path first (every other real test
    # in this file copies its fixture) -- a real, live-confirmed finding
    # while building this test: an identical byte-for-byte copy of this
    # exact file onto the local SSD decodes fine via plain soundfile.
    # The failure is reproducible only reading from the real X9 Pro
    # mount itself -- something about libsndfile's read/seek pattern
    # against this drive, not corruption in the audio data (`cmp`
    # confirmed the copy is byte-identical). Root cause not pursued
    # further, mirroring CLAUDE.md item 63's own "fix verified working,
    # exact trigger still open" precedent -- what matters here is that
    # ffmpeg, reading the same real original path, decodes it with zero
    # errors, and the fallback picks that decode up correctly.
    import soundfile as sf

    with pytest.raises(Exception):
        sf.info(str(REAL_SOUNDFILE_FAILS_FFMPEG_RESCUES))

    result = compute_fingerprint(REAL_SOUNDFILE_FAILS_FFMPEG_RESCUES)

    assert result.data
    assert result.duration_seconds > 0

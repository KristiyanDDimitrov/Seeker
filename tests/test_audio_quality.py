import numpy as np
import pytest
import soundfile as sf

from seeker.library.audio_quality import analyze_local_file_quality


def _write_wav(
        path,
        samples: np.ndarray,
        sample_rate: int = 44_100,
        subtype: str = "PCM_16",
) -> None:
    sf.write(str(path), samples, sample_rate, subtype=subtype)


def test_analyze_local_file_quality_reports_lossless_tier_and_real_format_info(
        tmp_path,
):
    path = tmp_path / "test.wav"
    samples = (np.sin(np.linspace(0, 100, 44_100)) * 0.1).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.tier == 2
    assert result.sample_rate == 44_100
    assert result.bit_depth == 16
    # Confirmed live, not assumed: mutagen DOES report a real bitrate
    # for uncompressed WAV PCM (sample_rate * bit_depth * channels =
    # 44100 * 16 * 1 = 705,600 bps = 705 kbps) — an initial draft of
    # this test wrongly assumed lossless meant "no bitrate concept."
    assert result.bitrate_kbps == 705


def test_analyze_local_file_quality_reports_lossless_tier_for_real_aiff(
        tmp_path,
):
    # Roadmap item R1.4 — live-verified (see docs/HISTORY.md item R1):
    # mutagen 1.48.1's AIFFInfo already computes
    # bitrate = channels * sample_size * sample_rate internally, so no
    # AIFF-specific derivation branch was needed in
    # analyze_local_file_quality — this is that verification made a
    # permanent regression test, same shape as the WAV test above.
    path = tmp_path / "test.aiff"
    samples = (np.sin(np.linspace(0, 100, 44_100)) * 0.1).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.tier == 2
    assert result.sample_rate == 44_100
    assert result.bit_depth == 16
    assert result.bitrate_kbps == 705


def test_analyze_local_file_quality_detects_real_clipping(tmp_path):
    path = tmp_path / "clipped.wav"
    full_scale = np.iinfo(np.int16).max
    # Half the samples pinned to full-scale (genuinely clipped), half a
    # quiet, unclipped tone.
    clipped_half = np.full(22_050, full_scale, dtype=np.int16)
    quiet_half = (np.sin(np.linspace(0, 100, 22_050)) * 1000).astype(
        np.int16
    )
    samples = np.concatenate([clipped_half, quiet_half])
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.clipping_ratio == pytest.approx(0.5, abs=0.01)


def test_analyze_local_file_quality_reports_near_zero_clipping_when_clean(
        tmp_path,
):
    path = tmp_path / "clean.wav"
    samples = (np.sin(np.linspace(0, 100, 44_100)) * 0.1).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.clipping_ratio < 0.01


def test_analyze_local_file_quality_measures_real_integrated_loudness(
        tmp_path,
):
    path = tmp_path / "loud_enough.wav"
    # pyloudnorm's gated ITU-R BS.1770 measurement needs a real-enough
    # signal (long/loud enough) to produce a value at all — a few
    # seconds of an audible tone, not silence.
    duration_seconds = 5
    t = np.linspace(0, duration_seconds, 44_100 * duration_seconds)
    samples = (np.sin(2 * np.pi * 440 * t) * 0.5).astype(np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.integrated_loudness_lufs is not None
    assert isinstance(result.integrated_loudness_lufs, float)


def test_analyze_local_file_quality_returns_none_loudness_for_silence(
        tmp_path,
):
    path = tmp_path / "silence.wav"
    samples = np.zeros(44_100, dtype=np.float32)
    _write_wav(path, samples)

    result = analyze_local_file_quality(path)

    assert result.integrated_loudness_lufs is None

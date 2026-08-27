import shutil
from pathlib import Path

import pytest

from seeker.audio_analysis import (
    CAMELOT_MAP,
    analyze_audio,
    correct_octave_error,
)

# Real file from the scanned x9-pro library — copied to tmp_path before
# being touched; the original is never opened. Skipped (not failed) when
# the drive isn't mounted, same treatment as the rest of the test suite
# gives an unreachable library location.
X9_PRO_ROOT = Path("/Volumes/X9 Pro")
REAL_WAV = X9_PRO_ROOT / "Music/240KMH/3AMDISCO - Get Back.wav"

requires_x9_pro = pytest.mark.skipif(
    not X9_PRO_ROOT.is_dir(),
    reason="x9-pro drive not mounted",
)


@requires_x9_pro
def test_analyze_audio_bpm_in_sane_range(tmp_path):
    dest = tmp_path / "test.wav"
    shutil.copy(REAL_WAV, dest)

    result = analyze_audio(dest)

    assert 60 <= result.bpm <= 200


@requires_x9_pro
def test_analyze_audio_is_deterministic(tmp_path):
    dest = tmp_path / "test.wav"
    shutil.copy(REAL_WAV, dest)

    first = analyze_audio(dest)
    second = analyze_audio(dest)

    assert first.bpm == second.bpm
    assert first.camelot_key == second.camelot_key
    assert first.key_confidence == second.key_confidence


@requires_x9_pro
def test_analyze_audio_reports_a_valid_camelot_key(tmp_path):
    dest = tmp_path / "test.wav"
    shutil.copy(REAL_WAV, dest)

    result = analyze_audio(dest)

    assert result.camelot_key in CAMELOT_MAP.values()
    assert 0.0 <= result.key_confidence <= 1.0


def test_camelot_map_has_all_24_standard_keys():
    assert len(CAMELOT_MAP) == 24

    majors = [key for key in CAMELOT_MAP if key.endswith("major")]
    minors = [key for key in CAMELOT_MAP if key.endswith("minor")]

    assert len(majors) == 12
    assert len(minors) == 12

    # Every Camelot code 1-12 must appear exactly once as A (minor) and
    # once as B (major).
    codes = sorted(CAMELOT_MAP.values())
    expected = sorted(
        f"{n}{letter}" for n in range(1, 13) for letter in ("A", "B")
    )
    assert codes == expected


def test_camelot_map_pairs_relative_major_minor_correctly():
    # Spot-check well-known relative pairs (share the same key
    # signature) — a random renumbering would still pass the "24 unique
    # codes" check above but would pair the wrong major/minor together.
    assert CAMELOT_MAP["A minor"] == "8A"
    assert CAMELOT_MAP["C major"] == "8B"
    assert CAMELOT_MAP["A minor"][:-1] == CAMELOT_MAP["C major"][:-1]

    assert CAMELOT_MAP["G# minor"] == "1A"
    assert CAMELOT_MAP["B major"] == "1B"

    assert CAMELOT_MAP["C# minor"] == "12A"
    assert CAMELOT_MAP["E major"] == "12B"


def test_correct_octave_error_fixes_half_tempo_detection():
    bpm, was_corrected = correct_octave_error(87, (160, 180))

    assert bpm == 174
    assert was_corrected is True


def test_correct_octave_error_leaves_in_range_bpm_untouched():
    bpm, was_corrected = correct_octave_error(170, (160, 180))

    assert bpm == 170
    assert was_corrected is False


def test_correct_octave_error_does_not_force_a_bad_correction():
    # Neither *2, *0.5, *3, nor *1.5 of 100 lands in (160, 180) —
    # correcting anyway would be a guess, not a fix.
    bpm, was_corrected = correct_octave_error(100, (160, 180))

    assert bpm == 100
    assert was_corrected is False


def test_correct_octave_error_does_not_correct_on_ambiguity():
    # A wide enough range that more than one candidate multiplier could
    # land inside it is genuinely ambiguous — don't guess which one.
    bpm, was_corrected = correct_octave_error(50, (90, 160))

    # 50*2=100 and 50*3=150 both land in (90, 160).
    assert bpm == 50
    assert was_corrected is False


@requires_x9_pro
def test_analyze_audio_expected_bpm_range_none_is_unchanged_behavior(
        tmp_path,
):
    # Regression check against the exact real value verified when this
    # parameter didn't exist yet (see CLAUDE.md) — not just "didn't
    # crash".
    dest = tmp_path / "test.wav"
    shutil.copy(REAL_WAV, dest)

    result = analyze_audio(dest)

    assert result.bpm == pytest.approx(161.4990234375)
    assert result.camelot_key == "3A"
    assert result.key_confidence == pytest.approx(0.47723346627317165)


@requires_x9_pro
def test_analyze_audio_expected_bpm_range_corrects_real_octave_error(
        tmp_path,
):
    dest = tmp_path / "test.wav"
    shutil.copy(REAL_WAV, dest)

    # The real unbiased detection is 161.5 BPM; biasing toward 70-90
    # (half-tempo) is confirmed live to change the raw detection to
    # 80.75 (exactly half) — this also exercises the belt-and-suspenders
    # correct_octave_error() pass, though it's already in range by then.
    result = analyze_audio(dest, expected_bpm_range=(70.0, 90.0))

    assert 70.0 <= result.bpm <= 90.0
    assert result.bpm == pytest.approx(80.74951171875)

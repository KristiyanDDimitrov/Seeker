from dataclasses import dataclass
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import scipy.stats


# Krumhansl-Schmuckler key profiles — standard, well-established empirical
# pitch-class weightings for major/minor tonality perception. Index 0 is
# C, matching librosa's chroma bin convention (chroma bin 0 is always C —
# a stable, documented convention, unlike the tempo/chroma function names
# themselves, which have shifted across librosa versions; see CLAUDE.md).
_MAJOR_PROFILE = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
)
_MINOR_PROFILE = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
)

_PITCH_CLASSES = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
]

# Standard Camelot wheel — fixed, well-documented DJ convention, not
# derived from analysis. Keyed by "<pitch class> major"/"<pitch class>
# minor" using sharps only, matching _PITCH_CLASSES' notation.
#
# Each number (1-12) groups a relative major/minor pair — the major and
# minor key that share the same key signature (e.g. 8B "C major" and 8A
# "A minor" both have zero sharps/flats) — and the letter says which:
# B = major, A = minor. Two keys sharing a number, or adjacent numbers,
# mix harmonically for DJs; that's the entire point of the notation. The
# number/letter pairing itself is fixed by music theory (relative major/
# minor), not a choice made here — this table just encodes it.
CAMELOT_MAP = {
    "C major": "8B", "C# major": "3B", "D major": "10B", "D# major": "5B",
    "E major": "12B", "F major": "7B", "F# major": "2B", "G major": "9B",
    "G# major": "4B", "A major": "11B", "A# major": "6B", "B major": "1B",
    "A minor": "8A", "A# minor": "3A", "B minor": "10A", "C minor": "5A",
    "C# minor": "12A", "D minor": "7A", "D# minor": "2A", "E minor": "9A",
    "F minor": "4A", "F# minor": "11A", "G minor": "6A", "G# minor": "1A",
}


@dataclass
class AudioAnalysis:
    bpm: float
    camelot_key: str | None
    key_confidence: float


def analyze_audio(
        file_path: str | Path,
        expected_bpm_range: tuple[float, float] | None = None,
) -> AudioAnalysis:
    # librosa.load resamples to a fixed rate regardless of the source
    # format (wav/mp3/flac/m4a all go through the same path via
    # soundfile/audioread), so this needs no per-format branching, unlike
    # metadata.py's tag writers.
    y, sr = librosa.load(str(file_path), sr=22050, mono=True)

    # beat_track accepts a `prior` — a scipy.stats.rv_continuous over BPM
    # — to bias its internal tempo search, confirmed live on this
    # version (1.0.0): a uniform prior over 70-90 BPM changed a real
    # 161.5 BPM detection to 80.75 (exactly half). When no range is
    # given, prior stays None — the exact same call as before this
    # feature existed, so behavior is unchanged. scipy.stats.uniform's
    # signature is (loc, scale) meaning the range [loc, loc+scale], NOT
    # [loc, scale] — a real gotcha confirmed against this version's
    # actual behavior, not assumed from the parameter names.
    # Typed Any: scipy.stats.uniform(...) returns a frozen
    # rv_continuous_frozen instance, not literally an rv_continuous —
    # librosa's stub expects the latter, but the frozen distribution is
    # duck-type compatible and confirmed working at runtime (live-
    # verified: this exact call changed a real 161.5 BPM detection to
    # 80.75). An acceptable, checked exception to the stub, not a guess.
    prior: Any = None
    if expected_bpm_range is not None:
        low, high = expected_bpm_range
        prior = scipy.stats.uniform(low, high - low)

    # beat_track's tempo return has shifted shape across librosa versions
    # (bare scalar vs. a length-1 array depending on version/channel
    # count) — confirmed live on this version (1.0.0) that it's a
    # length-1 ndarray; np.atleast_1d handles either shape without
    # guessing which one we'll get.
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, prior=prior)
    bpm = float(np.atleast_1d(tempo)[0])

    # Belt-and-suspenders: run the pure range check regardless of
    # whether the internal `prior` biasing already fixed it — this
    # check is cheap and doesn't depend on the biasing having worked.
    if expected_bpm_range is not None:
        bpm, _ = correct_octave_error(bpm, expected_bpm_range)

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    mean_chroma = chroma.mean(axis=1)

    best_key = None
    best_score = -1.0

    for i, pitch_class in enumerate(_PITCH_CLASSES):
        for mode, profile in (
                ("major", _MAJOR_PROFILE),
                ("minor", _MINOR_PROFILE),
        ):
            score = _correlate(mean_chroma, np.roll(profile, i))

            if score > best_score:
                best_score = score
                best_key = f"{pitch_class} {mode}"

    # Only report a key when the best candidate is genuinely
    # (positively) correlated — near-silent or noise-only audio can
    # otherwise "win" an arbitrary key at zero real confidence.
    camelot_key: str | None = None

    if best_score > 0:
        # best_key and best_score are always updated together above, and
        # best_score starting at -1.0 guarantees at least one update for
        # any real correlation score — so best_score > 0 implies
        # best_key was set.
        assert best_key is not None
        camelot_key = CAMELOT_MAP[best_key]

    return AudioAnalysis(
        bpm=bpm,
        camelot_key=camelot_key,
        key_confidence=max(best_score, 0.0),
    )


def correct_octave_error(
        bpm: float,
        expected_range: tuple[float, float],
) -> tuple[float, bool]:
    """Fix systematic half/double-tempo (and triplet-feel) detection
    errors — common on genres like DnB, where a beat tracker often locks
    onto half or double the perceived tempo. Pure and independently
    testable: no audio, no librosa. If `bpm` already falls in
    `expected_range`, it's returned unchanged. Otherwise, exactly one of
    2x/0.5x/3x/1.5x landing in range is taken as the correction;
    anything else (zero or multiple candidates in range) is genuinely
    ambiguous, so the original raw value is returned unchanged rather
    than forcing a guess.
    """
    low, high = expected_range

    if low <= bpm <= high:
        return bpm, False

    candidates = [bpm * 2, bpm * 0.5, bpm * 3, bpm * 1.5]
    in_range = [
        candidate for candidate in candidates if low <= candidate <= high
    ]

    if len(in_range) == 1:
        return in_range[0], True

    return bpm, False


def _correlate(vector: np.ndarray, profile: np.ndarray) -> float:
    vector = vector - vector.mean()
    profile = profile - profile.mean()

    denominator = np.linalg.norm(vector) * np.linalg.norm(profile)

    if denominator == 0:
        return 0.0

    return float(np.dot(vector, profile) / denominator)

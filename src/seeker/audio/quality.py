"""Quality of a file already on disk, for the duplicate finder to rank
copies by. A SoulseekFile's peer-reported bitrate doesn't exist for a
local file, so the file itself is opened: bitrate and bit depth via
mutagen, plus a clipping heuristic and integrated loudness."""
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mutagen
import numpy as np

from seeker.audio.formats import quality_tier_for_format

# Untuned heuristic threshold, flagged the same as every other constant
# in this codebase — a sample at or above this fraction of full-scale
# (16-bit) counts toward clipping_ratio. Revisit once this sees more
# real library data than item 5's own small real spot-check.
CLIPPING_AMPLITUDE_THRESHOLD = 0.999


@dataclass
class LocalFileQuality:
    tier: int
    bitrate_kbps: int | None
    bit_depth: int | None
    sample_rate: int | None
    # Fraction of samples at/near full-scale amplitude — a heuristic
    # signal that a lossy source was over-compressed/limited before
    # encoding, not a certainty (some masters are legitimately loud).
    clipping_ratio: float
    # Informational only, per the task's own scoping — never a primary
    # signal in any ranking decision. None when pyloudnorm can't
    # measure it (e.g. audio too short/silent for a real ITU-R BS.1770
    # gated measurement).
    integrated_loudness_lufs: float | None


def analyze_local_file_quality(path: str | Path) -> LocalFileQuality:
    extension = Path(path).suffix
    tier = quality_tier_for_format(extension)

    bitrate_kbps: int | None = None
    bit_depth: int | None = None
    sample_rate: int | None = None

    # mutagen ships no type annotations at all (no py.typed marker, no
    # types-mutagen package on PyPI — same real gap audio/tags.py's own
    # module docstring already documents); mutagen_file/info are typed
    # Any here rather than scattering per-line ignores across this one
    # small, self-contained function.
    mutagen_file: Any = mutagen.File(str(path))

    if mutagen_file is not None and mutagen_file.info is not None:
        info = mutagen_file.info
        sample_rate = getattr(info, "sample_rate", None)

        # Confirmed live: mutagen 1.48.1's AIFFInfo already computes
        # `bitrate = channels * sample_size * sample_rate` in its own
        # __init__ and exposes it as `.bitrate` — no AIFF-specific
        # branch needed here. HISTORY §85.
        raw_bitrate = getattr(info, "bitrate", None)
        if raw_bitrate:
            bitrate_kbps = int(raw_bitrate // 1000)

        bit_depth = getattr(info, "bits_per_sample", None)

    return LocalFileQuality(
        tier=tier,
        bitrate_kbps=bitrate_kbps,
        bit_depth=bit_depth,
        sample_rate=sample_rate,
        clipping_ratio=_measure_clipping_ratio(path),
        integrated_loudness_lufs=_measure_integrated_loudness(path),
    )


def _measure_clipping_ratio(path: str | Path) -> float:
    # Deferred (PLC0415, suppressed): soundfile is a heavy scientific
    # dependency this module only needs for the rare candidate that
    # reaches quality measurement at all — importing it at module level
    # would put it on every startup path that merely imports this module.
    import soundfile as sf  # noqa: PLC0415

    data, _ = sf.read(str(path), dtype="int16", always_2d=True)

    if data.size == 0:
        return 0.0

    full_scale = np.iinfo(np.int16).max
    threshold = CLIPPING_AMPLITUDE_THRESHOLD * full_scale
    clipped_samples = np.abs(data) >= threshold

    return float(clipped_samples.sum()) / float(data.size)


def _measure_integrated_loudness(path: str | Path) -> float | None:
    # Deferred (PLC0415, suppressed) for the same reason as
    # _measure_clipping_ratio above: pyloudnorm/soundfile are heavy
    # scientific dependencies this module only needs this deep in the
    # rare quality-measurement path, not on every import of this module.
    import pyloudnorm  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    data, rate = sf.read(str(path))

    try:
        meter = pyloudnorm.Meter(rate)
        loudness = float(meter.integrated_loudness(data))
    except ValueError:
        # pyloudnorm raises on audio too short for a real ITU-R
        # BS.1770 gated measurement — informational-only, so a missing
        # value here is fine, not an error worth surfacing.
        return None

    # Confirmed live, not assumed: digital silence doesn't raise —
    # it returns a real, mathematically-correct -inf (ln(0) diverging),
    # which isn't a meaningful value to show or compare against other
    # files. NaN is the same "not meaningful" case for any other
    # degenerate input.
    if not math.isfinite(loudness):
        return None

    return loudness

"""Audio fingerprinting via libchromaprint, for the duplicate/quality
detector. Own, project-owned ctypes binding rather than depending on
`pyacoustid`'s bundled `chromaprint.py` as-is, for two reasons: (1)
that binding does a bare `ctypes.CDLL("libchromaprint.1.dylib")` with
no explicit path, which fails to find a real Homebrew install on Apple
Silicon (dyld's default fallback search path doesn't include
`/opt/homebrew/lib`) — confirmed live; (2) it raises at *import* time
when the library can't be found, which would crash this whole app just
for existing on a machine without it installed. Fingerprinting is an
optional feature (same "checked before use, never eagerly constructed"
precedent as `Application.soulseek_configured` /
`DownloadService.soulseek`), so the search happens lazily — only
`compute_fingerprint()`/`decode_fingerprint()` can raise
`FingerprintingUnavailableError`; importing this module never can. See
HISTORY §38.

The core `Fingerprinter` ctypes bindings below are adapted from
pyacoustid's own `chromaprint.py` (Copyright (C) 2011 Lukas Lalinsky,
MIT licensed) — same real C API, just with real cross-platform library
discovery in place of a bare name lookup, and a call-time rather than
import-time failure mode. The underlying `libchromaprint` C library
itself is LGPL-2.1-or-later (confirmed via `brew info chromaprint` and
its own bundled LICENSE.md) — loaded here dynamically via `ctypes`,
never statically linked, which is the standard, low-risk way to stay
LGPL-compliant while bundling the real shared library inside a
PyInstaller build later.
"""

import ctypes
import ctypes.util
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import numpy as np
import soundfile as sf

from seeker.errors import SeekerError

logger = logging.getLogger(__name__)

# chromaprint's own default algorithm (matches fpcalc's default and
# pyacoustid's ALGORITHM_DEFAULT) — not exposed as a caller-facing
# choice here since there's no reason yet for this app to pick a
# different one.
_ALGORITHM_DEFAULT = 1

# Untuned constant, same convention as every other threshold in this
# codebase — how much decoded PCM to feed the fingerprinter per
# streaming chunk. One second's worth keeps memory bounded for a large
# file without the overhead of feeding sample-by-sample.
_CHUNK_SECONDS = 1

# The fixed format ffmpeg is asked to decode every fallback file to.
# Chromaprint normalizes internally regardless of the input rate/channel
# count it's told about (it's not trying to preserve the source audio,
# just compute a comparable fingerprint) — so this doesn't need to match
# a file's real native rate to produce a fingerprint that clusters
# correctly against ones computed via the primary soundfile path.
# Untuned; 44.1kHz mono is a common, safe default.
_FFMPEG_DECODE_SAMPLE_RATE = 44_100
_FFMPEG_DECODE_CHANNELS = 1


class FingerprintingUnavailableError(SeekerError):
    """Raised only when fingerprinting is actually attempted and
    libchromaprint genuinely can't be found — never at import time."""


class FingerprintError(SeekerError):
    """Raised when a real libchromaprint call itself fails, or when
    neither the primary soundfile decode nor the ffmpeg fallback could
    produce any usable audio from a real, non-empty file."""


@dataclass
class Fingerprint:
    # Base64-encoded, compressed chromaprint fingerprint — the same
    # text form fpcalc/AcoustID exchange, chosen so it stores cleanly
    # in a TEXT column (see local_files.fingerprint) without needing a
    # BLOB/bytes round-trip.
    data: str
    duration_seconds: float


def _candidate_library_names() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return ("libchromaprint.1.dylib", "libchromaprint.dylib")
    if sys.platform == "win32":
        return ("chromaprint.dll", "libchromaprint.dll")
    return ("libchromaprint.so.1", "libchromaprint.so")


def _candidate_search_dirs() -> list[Path]:
    dirs: list[Path] = []

    # A frozen PyInstaller build's own bundled-resource root — mirrors
    # soulseek/docker_setup.py::compose_template_path()'s already-established
    # sys._MEIPASS pattern. Checked first so a bundled copy always
    # takes precedence if packaging ever bundles one.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))

    if sys.platform == "darwin":
        # Homebrew's two real install prefixes. Confirmed live that
        # dyld's own default fallback search path does NOT include
        # either of these on a real, fully-updated Homebrew install —
        # a bare ctypes.CDLL(name) call fails without one of these
        # explicit paths (HISTORY §38).
        dirs.append(Path("/opt/homebrew/lib"))  # Apple Silicon
        dirs.append(Path("/usr/local/lib"))  # Intel

    return dirs


def _load_library() -> ctypes.CDLL | None:
    names = _candidate_library_names()

    for directory in _candidate_search_dirs():
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                try:
                    return ctypes.CDLL(str(candidate))
                except OSError:
                    logger.debug(
                        "Could not load candidate library %s", candidate,
                        exc_info=True,
                    )
                    continue

    # Falls through to the system's own default search behavior —
    # works out of the box on a Linux distro that installs to a
    # directory already on the dynamic linker's default path, or for
    # anyone who's already set DYLD_LIBRARY_PATH/LD_LIBRARY_PATH.
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            logger.debug(
                "Could not load library by name %s", name, exc_info=True,
            )
            continue

    found = ctypes.util.find_library("chromaprint")
    if found:
        try:
            return ctypes.CDLL(found)
        except OSError:
            logger.debug(
                "Could not load discovered library %s", found,
                exc_info=True,
            )

    return None


def _configure_prototypes(lib: ctypes.CDLL) -> None:
    lib.chromaprint_new.argtypes = (ctypes.c_int,)
    lib.chromaprint_new.restype = ctypes.c_void_p

    lib.chromaprint_free.argtypes = (ctypes.c_void_p,)
    lib.chromaprint_free.restype = None

    lib.chromaprint_start.argtypes = (
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
    )
    lib.chromaprint_start.restype = ctypes.c_int

    lib.chromaprint_feed.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_int,
    )
    lib.chromaprint_feed.restype = ctypes.c_int

    lib.chromaprint_finish.argtypes = (ctypes.c_void_p,)
    lib.chromaprint_finish.restype = ctypes.c_int

    lib.chromaprint_get_fingerprint.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p),
    )
    lib.chromaprint_get_fingerprint.restype = ctypes.c_int

    lib.chromaprint_dealloc.argtypes = (ctypes.c_void_p,)
    lib.chromaprint_dealloc.restype = None

    lib.chromaprint_decode_fingerprint.argtypes = (
        ctypes.POINTER(ctypes.c_char),
        ctypes.c_int,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint32)),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
    )
    lib.chromaprint_decode_fingerprint.restype = ctypes.c_int


_libchromaprint: ctypes.CDLL | None = None
_load_attempted = False


def _get_library() -> ctypes.CDLL:
    # Lazy, cached, call-time-only — see the module docstring for why
    # this must never run at import time. `global` is the correct,
    # idiomatic shape for a module-level lazy singleton cache — not
    # worth a class wrapper for its own sake (PLW0603, suppressed).
    global _libchromaprint, _load_attempted  # noqa: PLW0603

    if not _load_attempted:
        _libchromaprint = _load_library()
        _load_attempted = True

        if _libchromaprint is not None:
            _configure_prototypes(_libchromaprint)

    if _libchromaprint is None:
        raise FingerprintingUnavailableError(
            "libchromaprint isn't installed or couldn't be found. "
            "Install it to use duplicate detection — e.g. "
            "`brew install chromaprint` on macOS, "
            "`apt install libchromaprint1` on Debian/Ubuntu, or the "
            "Chromaprint installer on Windows."
        )

    return _libchromaprint


def _check(result: int) -> None:
    if result != 1:
        raise FingerprintError("libchromaprint call failed")


class _StreamingFingerprinter:
    """Thin ctypes wrapper around one chromaprint context, used as a
    context manager: `with` allocates it and frees it on the way out,
    error or not. Inside, start() once, feed() repeatedly, finish()
    once. Not exposed outside this module; compute_fingerprint() below
    is the public entry point."""

    def __init__(self, algorithm: int = _ALGORITHM_DEFAULT):
        self._lib = _get_library()
        self._algorithm = algorithm
        self._ctx: int | None = None

    def __enter__(self) -> Self:
        # restype c_void_p: ctypes returns None for a NULL pointer.
        ctx = self._lib.chromaprint_new(self._algorithm)

        if not ctx:
            raise FingerprintError(
                "libchromaprint couldn't create a fingerprinting context"
            )

        self._ctx = ctx
        return self

    def __exit__(self, *_exc_info: object) -> None:
        ctx, self._ctx = self._ctx, None

        if ctx:
            self._lib.chromaprint_free(ctx)

    @property
    def _context(self) -> int:
        assert self._ctx is not None, "used outside its `with` block"
        return self._ctx

    def start(self, sample_rate: int, channels: int) -> None:
        _check(
            self._lib.chromaprint_start(self._context, sample_rate, channels)
        )

    def feed(self, pcm_bytes: bytes) -> None:
        # 16-bit PCM -> 2 bytes per sample, matching chromaprint's own
        # real requirement (confirmed live, HISTORY §38).
        _check(
            self._lib.chromaprint_feed(
                self._context, pcm_bytes, len(pcm_bytes) // 2,
            )
        )

    def finish(self) -> bytes:
        _check(self._lib.chromaprint_finish(self._context))

        fingerprint_ptr = ctypes.c_char_p()
        _check(
            self._lib.chromaprint_get_fingerprint(
                self._context, ctypes.byref(fingerprint_ptr),
            )
        )
        result = fingerprint_ptr.value
        self._lib.chromaprint_dealloc(fingerprint_ptr)

        assert result is not None
        return result


def is_available() -> bool:
    """Cheap, non-raising check for whether libchromaprint can be
    found on this system — mirrors Application.soulseek_configured's
    own "checked before use, not eagerly constructed" pattern (item
    28), so a caller (DuplicateService) can surface one clear message
    instead of a failure per file when it's simply not installed."""
    try:
        _get_library()
        return True
    except FingerprintingUnavailableError:
        return False


def _compute_fingerprint_via_soundfile(path: str | Path) -> Fingerprint:
    info = sf.info(str(path))
    chunk_frames = max(int(info.samplerate * _CHUNK_SECONDS), 1)

    with (
            _StreamingFingerprinter() as fingerprinter,
            sf.SoundFile(str(path)) as audio_file,
    ):
        fingerprinter.start(info.samplerate, info.channels)

        while True:
            block = audio_file.read(
                chunk_frames, dtype="int16", always_2d=True,
            )
            if len(block) == 0:
                break
            fingerprinter.feed(block.tobytes())

        fingerprint_bytes = fingerprinter.finish()

    duration_seconds = (
            info.frames / info.samplerate if info.samplerate else 0.0
    )

    return Fingerprint(
        data=fingerprint_bytes.decode("ascii"),
        duration_seconds=duration_seconds,
    )


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _compute_fingerprint_via_ffmpeg(path: Path) -> Fingerprint:
    # Rescue path for a confirmed soundfile/libsndfile gap: a genuine
    # production sample showed soundfile failing on real, non-empty,
    # non-corrupt-looking MP3s with "bad data offset" (libsndfile's MP3
    # frame-table parser rejecting files ffmpeg decodes with zero
    # errors) as well as on genuinely damaged files (a handful of real
    # FLACs/MP3s with mid-stream frame corruption) where ffmpeg logs
    # decode warnings but still recovers the large majority of real
    # audio frames — enough for a usable fingerprint. `librosa` was
    # tried first and ruled out live: this project's pinned librosa
    # (1.0.0) dropped its old audioread fallback entirely —
    # `librosa.load` now calls soundfile directly with no alternate
    # decoder, so it fails identically to the primary path for every one
    # of these files and would rescue exactly zero of them. ffmpeg is
    # external and optional (no new hard dependency) — only attempted
    # when already on PATH.
    #
    # stderr goes to a real file, never `subprocess.PIPE`: a corrupt
    # file makes ffmpeg log one decode-error line PER bad frame, easily
    # tens of thousands of lines, and once that fills the fixed-size OS
    # pipe (64KB on macOS) ffmpeg blocks writing stderr while this loop
    # blocks reading stdout — a two-pipe deadlock, reproduced live (hung
    # indefinitely). A file write never blocks on a reader keeping up.
    # See HISTORY §69.
    with (
            tempfile.TemporaryFile() as stderr_file,
            _StreamingFingerprinter() as fingerprinter,
    ):
        process = subprocess.Popen(
            [
                "ffmpeg", "-v", "error", "-i", str(path),
                "-f", "s16le",
                "-ac", str(_FFMPEG_DECODE_CHANNELS),
                "-ar", str(_FFMPEG_DECODE_SAMPLE_RATE),
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=stderr_file,
        )
        assert process.stdout is not None

        fingerprinter.start(
            _FFMPEG_DECODE_SAMPLE_RATE, _FFMPEG_DECODE_CHANNELS,
        )

        # 16-bit samples = 2 bytes each; mono, so this is bytes/second.
        chunk_bytes = _FFMPEG_DECODE_SAMPLE_RATE * _CHUNK_SECONDS * 2
        total_samples = 0

        try:
            while True:
                block = process.stdout.read(chunk_bytes)
                if not block:
                    break
                fingerprinter.feed(block)
                total_samples += len(block) // 2
        finally:
            process.stdout.close()
            process.wait()
            stderr_file.seek(0)
            stderr_output = stderr_file.read().decode(
                "utf-8", errors="replace",
            )

        if total_samples == 0:
            # A real, non-zero exit with no decoded samples at all (as
            # opposed to the "decodes with warnings" case above, which
            # DOES produce usable samples) — genuinely undecodable, not
            # rescued.
            detail = stderr_output.strip()
            raise FingerprintError(
                f"ffmpeg produced no audio data for {path}"
                + (f": {detail}" if detail else "")
            )

        fingerprint_bytes = fingerprinter.finish()

    duration_seconds = total_samples / _FFMPEG_DECODE_SAMPLE_RATE

    return Fingerprint(
        data=fingerprint_bytes.decode("ascii"),
        duration_seconds=duration_seconds,
    )


def compute_fingerprint(path: str | Path) -> Fingerprint:
    """Decode `path` and stream it through libchromaprint. Raises
    FingerprintingUnavailableError if libchromaprint can't be found, or
    FingerprintError if decoding genuinely fails on every path tried.

    Primary decode is via soundfile (not the fpcalc subprocess path). On
    ANY soundfile failure, falls back to ffmpeg if it's present on PATH
    — real production files exist that soundfile's libsndfile backend
    can't open at all but ffmpeg decodes cleanly (or with recoverable
    warnings; see `_compute_fingerprint_via_ffmpeg`'s comment).
    ffmpeg absent, or itself failing, re-raises the ORIGINAL soundfile
    error (not the ffmpeg one) when ffmpeg was never attempted, so
    callers see the same error shape as before this fallback existed.
    """
    try:
        return _compute_fingerprint_via_soundfile(path)
    except FingerprintingUnavailableError:
        raise
    except Exception as soundfile_error:
        if not _ffmpeg_available():
            raise

        try:
            return _compute_fingerprint_via_ffmpeg(Path(path))
        except FingerprintingUnavailableError:
            raise
        except Exception as ffmpeg_error:
            raise FingerprintError(
                f"soundfile failed ({soundfile_error}); ffmpeg fallback "
                f"also failed ({ffmpeg_error})"
            ) from ffmpeg_error


def decode_fingerprint(data: str) -> np.ndarray:
    """Decode a compute_fingerprint() string into its raw uint32
    sub-fingerprint array, for use with similarity_from_decoded().
    Separate from similarity_from_decoded() so a caller comparing one
    file against MANY others (DuplicateService's O(n^2) clustering)
    can decode each file's fingerprint once and
    reuse the decoded array across every comparison, rather than
    re-decoding it on every pairwise call — measured to matter: a real
    clustering pass over ~3,100 real fingerprinted files was multiple
    minutes slower and used several GB more memory without this
    caching. See HISTORY §39."""
    lib = _get_library()
    encoded = data.encode("ascii")

    result_ptr = ctypes.POINTER(ctypes.c_uint32)()
    result_size = ctypes.c_int()
    algorithm = ctypes.c_int()

    _check(
        lib.chromaprint_decode_fingerprint(
            encoded,
            len(encoded),
            ctypes.byref(result_ptr),
            ctypes.byref(result_size),
            ctypes.byref(algorithm),
            1,  # base64-decode the input first
        )
    )

    values = np.ctypeslib.as_array(
            result_ptr,
            shape=(result_size.value,),
    ).copy()
    lib.chromaprint_dealloc(result_ptr)

    return values.astype(np.uint32)


# Byte-wise popcount lookup table — turns a full uint32-array Hamming
# distance into a handful of vectorized numpy operations instead of a
# per-subfingerprint Python loop, which matters here: clustering a
# location's files is an O(n^2) pairwise comparison (see
# library/duplicate_service.py), and a real fingerprint is ~10,000
# uint32 values long (confirmed live, HISTORY §38).
_POPCOUNT_TABLE = np.array(
        [i.bit_count() for i in range(256)],
        dtype=np.uint8,
)


def _popcount_uint32(values: np.ndarray) -> np.ndarray:
    byte_view = values.view(np.uint8).reshape(-1, 4)
    return _POPCOUNT_TABLE[byte_view].sum(axis=1, dtype=np.uint32)


def similarity_from_decoded(a: np.ndarray, b: np.ndarray) -> float:
    """Pure Hamming-distance similarity between two already-decoded
    uint32 sub-fingerprint arrays — no ctypes, no libchromaprint, no
    I/O. Deliberately separate from decode_fingerprint() so the
    clustering logic that calls this (library/duplicate_service.py)
    can be unit-tested against synthetic arrays without needing
    libchromaprint installed, per this project's own established
    testing convention for the X9-Pro-drive-dependent tests.

    Aligned from the start (no offset search) — confirmed live
    (HISTORY §38) that this is already sufficient to separate real
    duplicates (~99.9% similarity, including a real cross-format
    FLAC/MP3 pair) from an unrelated real track pair (~58%) by a wide
    margin. A future revision could add sliding-window offset
    alignment (the way pyacoustid's own compare_fingerprints does) if
    real files with leading silence/offset differences are ever found
    not to cluster correctly — not attempted here since no such case
    was found in this project's own real library.
    """
    n = min(len(a), len(b))
    if n == 0:
        return 0.0

    xored = np.bitwise_xor(a[:n], b[:n])
    bit_errors = int(_popcount_uint32(xored).sum())

    return 1.0 - (bit_errors / (n * 32))

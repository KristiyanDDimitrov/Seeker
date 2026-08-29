"""Audio fingerprinting via libchromaprint, for the duplicate/quality
detector (roadmap item 5). Own, project-owned ctypes binding rather
than depending on `pyacoustid`'s bundled `chromaprint.py` as-is — see
CLAUDE.md/docs/HISTORY.md's Phase 0 spike entry for the two real
reasons why: (1) that binding does a bare `ctypes.CDLL("libchromaprint
.1.dylib")` with no explicit path, which fails to find a real Homebrew
install on Apple Silicon (dyld's default fallback search path doesn't
include `/opt/homebrew/lib`) — confirmed live; (2) it raises at
*import* time when the library can't be found, which would crash this
whole app just for existing on a machine without it installed.
Fingerprinting is an optional feature (same "checked before use, never
eagerly constructed" precedent as `Application.soulseek_configured` /
`DownloadService.soulseek`, item 28), so the search happens lazily —
only `compute_fingerprint()`/`hamming_similarity()` can raise
`FingerprintingUnavailableError`; importing this module never can.

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
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

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


class FingerprintingUnavailableError(RuntimeError):
    """Raised only when fingerprinting is actually attempted and
    libchromaprint genuinely can't be found — never at import time."""


class FingerprintError(RuntimeError):
    """Raised when a real libchromaprint call itself fails."""


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
    # docker_setup.py::compose_file_path()'s already-established
    # sys._MEIPASS pattern. Checked first so a bundled copy always
    # takes precedence once packaging actually bundles one (not done
    # as of this module's initial version — see CLAUDE.md item 5/38).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass))

    if sys.platform == "darwin":
        # Homebrew's two real install prefixes. Confirmed live (item
        # 38's spike) that dyld's own default fallback search path
        # does NOT include either of these on a real, fully-updated
        # Homebrew install — a bare ctypes.CDLL(name) call fails
        # without one of these explicit paths.
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
                    continue

    # Falls through to the system's own default search behavior —
    # works out of the box on a Linux distro that installs to a
    # directory already on the dynamic linker's default path, or for
    # anyone who's already set DYLD_LIBRARY_PATH/LD_LIBRARY_PATH.
    for name in names:
        try:
            return ctypes.CDLL(name)
        except OSError:
            continue

    found = ctypes.util.find_library("chromaprint")
    if found:
        try:
            return ctypes.CDLL(found)
        except OSError:
            pass

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
    # this must never run at import time.
    global _libchromaprint, _load_attempted

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
    """Thin, real ctypes wrapper around one chromaprint context —
    start() once, feed() repeatedly, finish() once. Not exposed
    outside this module; compute_fingerprint() below is the public
    entry point."""

    def __init__(self, algorithm: int = _ALGORITHM_DEFAULT):
        self._lib = _get_library()
        self._ctx = self._lib.chromaprint_new(algorithm)

    def __del__(self) -> None:
        ctx = getattr(self, "_ctx", None)
        if ctx:
            self._lib.chromaprint_free(ctx)

    def start(self, sample_rate: int, channels: int) -> None:
        _check(self._lib.chromaprint_start(self._ctx, sample_rate, channels))

    def feed(self, pcm_bytes: bytes) -> None:
        # 16-bit PCM -> 2 bytes per sample, matching chromaprint's own
        # real requirement (confirmed live, item 38's spike).
        _check(
            self._lib.chromaprint_feed(
                self._ctx, pcm_bytes, len(pcm_bytes) // 2,
            )
        )

    def finish(self) -> bytes:
        _check(self._lib.chromaprint_finish(self._ctx))

        fingerprint_ptr = ctypes.c_char_p()
        _check(
            self._lib.chromaprint_get_fingerprint(
                self._ctx, ctypes.byref(fingerprint_ptr),
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


def compute_fingerprint(path: str | Path) -> Fingerprint:
    """Decode `path` via soundfile (not the fpcalc subprocess path)
    and stream it through libchromaprint. Raises
    FingerprintingUnavailableError if the library can't be found, or
    FingerprintError/a soundfile error if the real call/decode fails.
    """
    info = sf.info(str(path))
    fingerprinter = _StreamingFingerprinter()
    fingerprinter.start(info.samplerate, info.channels)

    chunk_frames = max(int(info.samplerate * _CHUNK_SECONDS), 1)

    with sf.SoundFile(str(path)) as audio_file:
        while True:
            block = audio_file.read(
                chunk_frames, dtype="int16", always_2d=True,
            )
            if len(block) == 0:
                break
            fingerprinter.feed(block.tobytes())

    fingerprint_bytes = fingerprinter.finish()
    duration_seconds = info.frames / info.samplerate if info.samplerate else 0.0

    return Fingerprint(
        data=fingerprint_bytes.decode("ascii"),
        duration_seconds=duration_seconds,
    )


def decode_fingerprint(data: str) -> np.ndarray:
    """Decode a compute_fingerprint() string into its raw uint32
    sub-fingerprint array, for use with similarity_from_decoded().
    Public (not just an internal hamming_similarity() helper) so a
    caller comparing one file against MANY others (DuplicateService's
    O(n^2) clustering) can decode each file's fingerprint once and
    reuse the decoded array across every comparison, rather than
    re-decoding it on every pairwise call — confirmed live to matter in
    practice: a real clustering pass over ~3,100 real fingerprinted
    files was multiple minutes slower and used several GB more memory
    before this caching was added (item 5's live verification, see
    docs/HISTORY.md)."""
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

    values = np.ctypeslib.as_array(result_ptr, shape=(result_size.value,)).copy()
    lib.chromaprint_dealloc(result_ptr)

    return values.astype(np.uint32)


# Byte-wise popcount lookup table — turns a full uint32-array Hamming
# distance into a handful of vectorized numpy operations instead of a
# per-subfingerprint Python loop, which matters here: clustering a
# location's files is an O(n^2) pairwise comparison (see
# library/duplicate_service.py), and a real fingerprint is ~10,000
# uint32 values long (confirmed live, item 38's spike).
_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def _popcount_uint32(values: np.ndarray) -> np.ndarray:
    byte_view = values.view(np.uint8).reshape(-1, 4)
    return _POPCOUNT_TABLE[byte_view].sum(axis=1, dtype=np.uint32)


def similarity_from_decoded(a: np.ndarray, b: np.ndarray) -> float:
    """Pure Hamming-distance similarity between two already-decoded
    uint32 sub-fingerprint arrays — no ctypes, no libchromaprint, no
    I/O. Deliberately factored out from hamming_similarity() below so
    the clustering logic that calls this (library/duplicate_service.py)
    can be unit-tested against synthetic arrays without needing
    libchromaprint installed, per this project's own established
    testing convention for the X9-Pro-drive-dependent tests.

    Aligned from the start (no offset search) — confirmed live (item
    38's spike) that this is already sufficient to separate real
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


def hamming_similarity(fingerprint_a: str, fingerprint_b: str) -> float:
    """Compare two fingerprints from compute_fingerprint() — decodes
    both via the real libchromaprint call, then delegates to the pure
    similarity_from_decoded() above."""
    a = decode_fingerprint(fingerprint_a)
    b = decode_fingerprint(fingerprint_b)

    return similarity_from_decoded(a, b)

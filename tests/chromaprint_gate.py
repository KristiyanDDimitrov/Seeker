"""One skip condition for every test that needs a real libchromaprint.

A skip on "no library loads" also hides a lookup bug (a wrong search
path on Intel, say). The runner that must have the library sets
`SEEKER_REQUIRE_CHROMAPRINT=1`: the test then runs and fails with the
real `FingerprintingUnavailableError`. HISTORY §257.
"""

import os
from collections.abc import Mapping

import pytest

from seeker.audio import fingerprint as audio_fingerprint

REQUIRE_VARIABLE = "SEEKER_REQUIRE_CHROMAPRINT"


def skip_reason(*, loads: bool, environ: Mapping[str, str]) -> str | None:
    """Why a chromaprint test is skipped, or None to run it."""
    if loads or environ.get(REQUIRE_VARIABLE) == "1":
        return None
    return (
        "libchromaprint doesn't load here (not installed, or built for "
        f"another architecture); {REQUIRE_VARIABLE}=1 turns this skip "
        "into a failure"
    )


_reason = skip_reason(
    loads=audio_fingerprint._load_library() is not None,
    environ=os.environ,
)

requires_chromaprint = pytest.mark.skipif(
    _reason is not None, reason=_reason or "",
)

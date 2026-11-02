"""Which processor architecture this process runs as, in the words Help
and About show.

Two macOS builds exist, one per architecture, so "which one is
installed?" is a support question; and the Intel build also runs on
Apple silicon, translated by Rosetta and slower, with nothing else to
say so. `describe_architecture()` answers both without a subprocess:
macOS reports translation through the `sysctl.proc_translated` key,
read here with `sysctlbyname` over `ctypes` (observed on Apple
silicon, 2026-11-02: 0 natively, 1 under `arch -x86_64`; Apple
documents the key as missing, ENOENT, where Rosetta does not exist;
an Intel Mac is UNVERIFIED). Any failure reads as "not translated".

Windows and Linux report `platform.machine()` as it is.
"""
import ctypes
import platform
import sys

from seeker.update_check import RELEASES_PAGE_URL

__all__ = [
    "APPLE_SILICON",
    "INTEL",
    "ROSETTA",
    "ROSETTA_ADVICE",
    "describe_architecture",
    "is_translated",
]

APPLE_SILICON = "Apple silicon"
INTEL = "Intel"
ROSETTA = "Intel build on Apple silicon (Rosetta)"
# `Seeker.dmg` is the Apple silicon image's asset name in every release.
ROSETTA_ADVICE = (
    "Download Seeker.dmg, the Apple silicon build, from "
    f"{RELEASES_PAGE_URL}/latest to run natively and faster on this Mac."
)
_UNKNOWN = "unknown"
_PROC_TRANSLATED = b"sysctl.proc_translated"


def describe_architecture() -> str:
    """What Help and About show: "Apple silicon", "Intel", or, for the
    Intel build translated on Apple silicon, "Intel build on Apple
    silicon (Rosetta)" and one sentence pointing at the Apple silicon
    download. Elsewhere, `platform.machine()` as it is ("unknown"
    when that is empty)."""
    machine = platform.machine() or _UNKNOWN
    if sys.platform != "darwin":
        return machine
    if machine == "arm64":
        return APPLE_SILICON
    if machine == "x86_64":
        if is_translated():
            return f"{ROSETTA}. {ROSETTA_ADVICE}"
        return INTEL
    return machine


def is_translated() -> bool:
    """Whether macOS runs this process through Rosetta. False off
    macOS, and whenever the key can't be read."""
    if sys.platform != "darwin":
        return False
    return _read_sysctl_int(_PROC_TRANSLATED) == 1


def _read_sysctl_int(name: bytes) -> int | None:
    """An integer `sysctlbyname` value, or None when libc, the call or
    the key isn't there."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        sysctlbyname = libc.sysctlbyname
    except (OSError, AttributeError):
        return None
    value = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    result = sysctlbyname(
        name, ctypes.byref(value), ctypes.byref(size), None,
        ctypes.c_size_t(0),
    )
    if result != 0:
        return None
    return value.value

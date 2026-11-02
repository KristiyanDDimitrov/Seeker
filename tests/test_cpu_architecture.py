"""`cpu_architecture`: what Help and About say about the running
architecture. Each test patches the module's own inputs
(`sys.platform`, `platform.machine`, `_read_sysctl_int`), never the
machine it runs on; the real `sysctlbyname` read runs only on macOS."""
import sys

import pytest

from seeker import cpu_architecture
from seeker.cpu_architecture import (
    APPLE_SILICON,
    INTEL,
    ROSETTA,
    ROSETTA_ADVICE,
    describe_architecture,
    is_translated,
)
from seeker.update_check import RELEASES_PAGE_URL


@pytest.fixture
def on_mac(monkeypatch: pytest.MonkeyPatch):
    """A macOS process on the given machine, translated or not."""

    def configure(machine: str, translated: int | None) -> None:
        monkeypatch.setattr(cpu_architecture.sys, "platform", "darwin")
        monkeypatch.setattr(
            cpu_architecture.platform, "machine", lambda: machine,
        )
        monkeypatch.setattr(
            cpu_architecture, "_read_sysctl_int", lambda name: translated,
        )

    return configure


def test_an_arm64_mac_is_apple_silicon(on_mac):
    on_mac("arm64", 0)

    assert describe_architecture() == APPLE_SILICON == "Apple silicon"


def test_a_native_x86_64_mac_is_intel(on_mac):
    on_mac("x86_64", 0)

    assert describe_architecture() == INTEL == "Intel"


def test_an_intel_mac_without_the_sysctl_key_is_intel(on_mac):
    # Apple documents ENOENT for the key where Rosetta doesn't exist;
    # `_read_sysctl_int` turns any failed read into None.
    on_mac("x86_64", None)

    assert describe_architecture() == INTEL


def test_a_translated_process_names_rosetta_and_the_apple_silicon_download(
        on_mac,
):
    on_mac("x86_64", 1)

    text = describe_architecture()

    assert text.startswith("Intel build on Apple silicon (Rosetta)")
    assert text == f"{ROSETTA}. {ROSETTA_ADVICE}"
    # One sentence of advice, naming the Apple silicon image (the
    # asset name `Seeker.dmg` keeps, BRIEF §0.7) and where to get it.
    assert ROSETTA_ADVICE.count(". ") == 0
    assert ROSETTA_ADVICE.endswith(".")
    assert "Seeker.dmg" in ROSETTA_ADVICE
    assert f"{RELEASES_PAGE_URL}/latest" in ROSETTA_ADVICE


def test_an_unknown_mac_machine_is_reported_as_is(on_mac):
    on_mac("ppc", 0)

    assert describe_architecture() == "ppc"


@pytest.mark.parametrize(
    ("platform_name", "machine"),
    [("win32", "AMD64"), ("win32", "ARM64"), ("linux", "x86_64")],
)
def test_other_platforms_report_platform_machine_as_is(
        monkeypatch, platform_name, machine,
):
    monkeypatch.setattr(cpu_architecture.sys, "platform", platform_name)
    monkeypatch.setattr(cpu_architecture.platform, "machine", lambda: machine)

    def no_sysctl(name: bytes) -> int | None:
        raise AssertionError("sysctl is macOS-only")

    monkeypatch.setattr(cpu_architecture, "_read_sysctl_int", no_sysctl)

    assert describe_architecture() == machine


def test_an_empty_machine_string_reads_unknown(monkeypatch):
    # platform.machine() returns "" when the platform can't tell.
    monkeypatch.setattr(cpu_architecture.sys, "platform", "linux")
    monkeypatch.setattr(cpu_architecture.platform, "machine", lambda: "")

    assert describe_architecture() == "unknown"


def test_is_translated_only_for_a_sysctl_value_of_one(monkeypatch):
    monkeypatch.setattr(cpu_architecture.sys, "platform", "darwin")
    for value, expected in ((1, True), (0, False), (None, False), (2, False)):
        monkeypatch.setattr(
            cpu_architecture, "_read_sysctl_int", lambda name, v=value: v,
        )
        assert is_translated() is expected


def test_is_translated_never_reads_sysctl_off_macos(monkeypatch):
    monkeypatch.setattr(cpu_architecture.sys, "platform", "win32")

    def no_sysctl(name: bytes) -> int | None:
        raise AssertionError("sysctl is macOS-only")

    monkeypatch.setattr(cpu_architecture, "_read_sysctl_int", no_sysctl)

    assert is_translated() is False


def test_a_libc_that_cannot_load_reads_as_no_value(monkeypatch):
    def unloadable(name: object, **kwargs: object) -> object:
        raise OSError("no libc")

    monkeypatch.setattr(cpu_architecture.ctypes, "CDLL", unloadable)

    assert cpu_architecture._read_sysctl_int(b"sysctl.proc_translated") is None


def test_a_libc_without_sysctlbyname_reads_as_no_value(monkeypatch):
    class NoSysctl:
        def __getattr__(self, name: str) -> object:
            raise AttributeError(name)

    monkeypatch.setattr(
        cpu_architecture.ctypes, "CDLL", lambda name, **kwargs: NoSysctl(),
    )

    assert cpu_architecture._read_sysctl_int(b"sysctl.proc_translated") is None


@pytest.mark.skipif(sys.platform != "darwin", reason="sysctlbyname is macOS's")
def test_the_real_sysctl_read_on_this_mac():
    # 0 natively, 1 under Rosetta (both observed through this read on
    # Apple silicon, 2026-11-02); a key that doesn't exist reads None.
    assert cpu_architecture._read_sysctl_int(b"sysctl.proc_translated") in (0, 1)
    assert cpu_architecture._read_sysctl_int(b"hw.ncpu") > 0
    assert cpu_architecture._read_sysctl_int(b"seeker.no.such.key") is None

"""Tests for seeker.processes, the one way Seeker starts a program."""

import subprocess
import sys

import pytest

from seeker import processes

_windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="only Windows gives a console program a window of its own",
)

# A child that prints its console window's handle: 0 when it has none.
_CONSOLE_WINDOW_PROBE = [
    sys.executable, "-c",
    "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow())",
]

# A child that writes UTF-8 and then a byte UTF-8 never uses. Its own
# source is ASCII, so no command-line encoding stands between it and
# the bytes. The UTF-8 of U+6771 holds 0x9D, which cp1252, a Western
# Windows code page, cannot decode at all.
_UTF8_THEN_A_BAD_BYTE = (
    "import sys; "
    "sys.stdout.buffer.write('Caf\\u00e9 \\u6771\\u4eac'.encode() + b'\\xff'); "
    "sys.stderr.buffer.write('\\u00dcber'.encode() + b'\\xfe')"
)


class _StandInPopen:
    """Takes `subprocess.Popen`'s place: starts nothing, keeps what it
    was handed, and ends at once with the class's `returncode` and
    `output`. `subprocess.run` drives it as it drives the real class."""

    started: list["_StandInPopen"]
    returncode = 0
    output: tuple[object, object] = (None, None)

    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.timeout = None
        self.started.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def communicate(self, stdin_data=None, timeout=None):
        self.timeout = timeout
        return self.output

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


@pytest.fixture
def stand_in(monkeypatch):
    """A fresh `_StandInPopen` subclass in `subprocess.Popen`'s place;
    its `started` lists each program the test started."""
    cls = type("StandInPopen", (_StandInPopen,), {"started": []})
    monkeypatch.setattr(subprocess, "Popen", cls)
    return cls


@pytest.mark.parametrize(
    ("platform", "flags"),
    [("win32", 0x08000000), ("darwin", 0), ("linux", 0)],
)
def test_only_windows_starts_a_program_with_no_console_window(
        stand_in, monkeypatch, platform, flags,
):
    # 0x08000000 is CREATE_NO_WINDOW, as winbase.h defines it. POSIX's
    # `Popen` refuses any other value than 0 (CPython 3.13: "creationflags
    # is only supported on Windows platforms", observed 2026-11-04).
    monkeypatch.setattr("seeker.processes.sys.platform", platform)

    processes.run(["program"], check=False)
    processes.popen(["program"])

    assert [process.kwargs["creationflags"] for process in stand_in.started] == [
        flags, flags,
    ]


def test_text_mode_reads_utf8_and_replaces_a_byte_that_is_not(stand_in):
    processes.run(["program"], check=False, text=True)

    (process,) = stand_in.started
    assert {key: process.kwargs[key] for key in ("text", "encoding", "errors")} == {
        "text": True, "encoding": "utf-8", "errors": "replace",
    }


def test_binary_mode_stays_bytes(stand_in):
    processes.run(["program"], check=False)
    processes.popen(["program"])

    for process in stand_in.started:
        assert not process.kwargs.get("text")
        assert not process.kwargs.get("universal_newlines")
        assert process.kwargs.get("encoding") is None
        assert process.kwargs.get("errors") is None


def test_run_hands_on_what_its_caller_asks_for(stand_in):
    env = {"PATH": "/nowhere"}

    processes.run(
        ["program", "--flag"], check=False, capture_output=True,
        timeout=7, env=env,
    )

    (process,) = stand_in.started
    assert process.args == ["program", "--flag"]
    assert process.kwargs["env"] is env
    assert (process.kwargs["stdout"], process.kwargs["stderr"]) == (
        subprocess.PIPE, subprocess.PIPE,
    )
    assert process.timeout == 7


def test_a_checked_failure_raises_and_an_unchecked_one_returns(stand_in):
    stand_in.returncode = 3
    stand_in.output = ("out", "err")

    with pytest.raises(subprocess.CalledProcessError) as raised:
        processes.run(["program"], check=True, capture_output=True, text=True)
    result = processes.run(
        ["program"], check=False, capture_output=True, text=True,
    )

    assert (raised.value.returncode, raised.value.stderr) == (3, "err")
    assert (result.returncode, result.stdout, result.stderr) == (3, "out", "err")


def test_popen_hands_on_its_streams(stand_in, tmp_path):
    with (tmp_path / "stderr").open("wb") as stderr_file:
        processes.popen(["program"], stdout=subprocess.PIPE, stderr=stderr_file)

    (process,) = stand_in.started
    assert process.kwargs["stdout"] == subprocess.PIPE
    assert process.kwargs["stderr"] is stderr_file


def test_a_real_programs_utf8_reads_whole_and_a_bad_byte_is_replaced():
    result = processes.run(
        [sys.executable, "-c", _UTF8_THEN_A_BAD_BYTE],
        check=True, capture_output=True, text=True, timeout=30,
    )

    assert (result.stdout, result.stderr) == (
        "Caf\u00e9 \u6771\u4eac\ufffd", "\u00dcber\ufffd",
    )


def test_a_real_program_started_by_popen_hands_back_bytes():
    with processes.popen(
            [sys.executable, "-c", "print('started')"], stdout=subprocess.PIPE,
    ) as process:
        output, _ = process.communicate(timeout=30)

    assert output.strip() == b"started"


@_windows_only
def test_the_flag_is_windows_own():
    assert subprocess.CREATE_NO_WINDOW == processes.CREATE_NO_WINDOW


@_windows_only
def test_on_windows_a_real_program_has_no_console_window():
    """A child started through the helper reads no console window. That
    shows the flag at work only where the control below runs: a child
    started without it reads none either when it shares a console that
    has no window (UNVERIFIED)."""
    result = processes.run(
        _CONSOLE_WINDOW_PROBE, check=True, capture_output=True, text=True,
        timeout=30,
    )
    with processes.popen(_CONSOLE_WINDOW_PROBE, stdout=subprocess.PIPE) as process:
        output, _ = process.communicate(timeout=30)

    assert (result.stdout.strip(), output.strip()) == ("0", b"0")


@_windows_only
def test_on_windows_the_probe_sees_a_console_window_it_shares():
    # Shows the probe above can see a window at all: started without the
    # flag, a console program shares its parent's console (Microsoft's
    # documentation, UNVERIFIED). It skips where pytest reads no console
    # window, and that covers two cases it cannot tell apart, both
    # UNVERIFIED: pytest has no console, so a child without the flag
    # would open a new window, which no test may do; or pytest has a
    # console with no window, which such a child shares and reads 0
    # from, as a child started with the flag does. check-windows skipped
    # it (run 42812791705), so the probe above shows nothing there about
    # the flag itself.
    import ctypes

    if not ctypes.windll.kernel32.GetConsoleWindow():
        pytest.skip("pytest has no console window for a child to share")

    result = subprocess.run(
        _CONSOLE_WINDOW_PROBE, check=True, capture_output=True, text=True,
        timeout=30,
    )

    assert result.stdout.strip() != "0"

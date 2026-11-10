"""Every program Seeker starts, started one way.

`run()` and `popen()` take the arguments Seeker's call sites use and
add what a bare `subprocess` call leaves to the platform:

- On Windows, `CREATE_NO_WINDOW`. A console program (`docker`,
  `ffmpeg`, `cmd`) started from the windowed app otherwise opens a
  console window of its own for as long as it runs (UNVERIFIED on
  hardware); `tests/test_processes.py` shows on `check-windows` that a
  child started here has none. Windows ignores the flag for a GUI
  program such as `explorer` (Microsoft's documentation, UNVERIFIED).
- In text mode, UTF-8 with `errors="replace"`. Text mode otherwise
  decodes with the locale's encoding, which on Windows is its ANSI code
  page (cp1252 on a Western install, UNVERIFIED), and fails the whole
  call on one byte it cannot decode: cp1252 has no character for 0x9D,
  which the UTF-8 of 東京 holds. macOS decodes UTF-8 already, under no
  locale too (Python's UTF-8 mode; observed 2026-11-04 with `env -i`
  and `LC_ALL=C`), so there only the replacement is new.

Both look `subprocess.run` and `subprocess.Popen` up on the module when
called, never at import, so a test's fake of either, and the suite's
spawn guard, still see every call.

No other module names a spawn (`subprocess`'s, `os.system`,
`os.popen`): `tests/test_subprocess_sweep.py` fails the build.
"""

import subprocess
import sys
from collections.abc import Mapping
from typing import IO, Any, Literal, overload

# winbase.h's value. `subprocess` defines its own only on Windows, and a
# test patches `sys.platform` on the Mac it runs on.
CREATE_NO_WINDOW = 0x08000000


def _creation_flags() -> int:
    # POSIX's `Popen` refuses any other value than 0 ("creationflags is
    # only supported on Windows platforms"; observed 2026-11-04).
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


@overload
def run(
        args: list[str],
        *,
        check: bool,
        text: Literal[True],
        capture_output: bool = ...,
        timeout: float | None = ...,
        env: Mapping[str, str] | None = ...,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run(
        args: list[str],
        *,
        check: bool,
        text: Literal[False] = ...,
        capture_output: bool = ...,
        timeout: float | None = ...,
        env: Mapping[str, str] | None = ...,
) -> subprocess.CompletedProcess[bytes]: ...


def run(
        args: list[str],
        *,
        check: bool,
        text: bool = False,
        capture_output: bool = False,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """`subprocess.run(args, ...)`, with no console window on Windows and,
    when `text`, output decoded as UTF-8.

    `check` has no default: each caller says whether a failure raises,
    as ruff's PLW1510 asks of a bare `subprocess.run`.
    """
    return subprocess.run(
        args,
        check=check,
        capture_output=capture_output,
        timeout=timeout,
        env=env,
        creationflags=_creation_flags(),
        text=text,
        encoding="utf-8" if text else None,
        errors="replace" if text else None,
    )


def popen(
        args: list[str],
        *,
        stdout: int | IO[Any] | None = None,
        stderr: int | IO[Any] | None = None,
) -> subprocess.Popen[bytes]:
    """`subprocess.Popen(args, ...)` in binary mode, with no console
    window on Windows."""
    return subprocess.Popen(
        args,
        stdout=stdout,
        stderr=stderr,
        creationflags=_creation_flags(),
    )

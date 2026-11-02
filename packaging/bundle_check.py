"""The post-build check of a macOS bundle, run by build_dmg.py after
PyInstaller: every Mach-O in the bundle carries the target architecture,
the main executable is thin, and no binary's `minos` is above
`bundle_info.MINIMUM_SYSTEM_VERSION`. It repeats, on every build, the
one-off `otool -l` measurement of HISTORY §214.

A tool runner is a callable taking a command list and returning stdout,
so a test can stand in for `lipo` and `otool`.
"""

import re
import struct
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path

ToolRunner = Callable[[list[str]], str]

# The first four bytes of a thin Mach-O (either byte order, 32 or 64
# bit) and of a fat file; a fat file's magic is big-endian on disk.
_MACHO_MAGICS = {
    bytes.fromhex(magic)
    for magic in (
        "feedface", "feedfacf", "cefaedfe", "cffaedfe",
        "cafebabe", "cafebabf", "bebafeca", "bfbafeca",
    )
}

# A fat file's magic is also a Java class file's; there bytes 4-8 are
# the class version (45 and up), here the slice count. No fat file in a
# bundle has this many slices.
_MAX_FAT_SLICES = 20
_FAT_MAGICS = {
    bytes.fromhex("cafebabe"): ">I", bytes.fromhex("cafebabf"): ">I",
    bytes.fromhex("bebafeca"): "<I", bytes.fromhex("bfbafeca"): "<I",
}

# One load command of `otool -l`. LC_SOURCE_VERSION also prints a
# `version`, so only the two deployment-target commands are read.
_DEPLOYMENT_TARGET = re.compile(
    r"cmd (?:LC_BUILD_VERSION|LC_VERSION_MIN_MACOSX)\b"
    r"(?:(?!Load command).)*?^\s*(?:minos|version)\s+(\d+(?:\.\d+)*)\s*$",
    re.MULTILINE | re.DOTALL,
)

MAIN_EXECUTABLE = Path("Contents") / "MacOS" / "Seeker"


def run_tool(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True,
    ).stdout


def dmg_name(architecture: str) -> str:
    """`Seeker.dmg` stays the Apple silicon image (BRIEF §0.7)."""
    return "Seeker.dmg" if architecture == "arm64" else "Seeker-Intel.dmg"


def macho_files(app: Path) -> Iterator[Path]:
    """Every regular file in the bundle whose magic says Mach-O."""
    for path in sorted(app.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            head = handle.read(8)
        magic = head[:4]
        if magic not in _MACHO_MAGICS:
            continue
        if magic in _FAT_MAGICS:
            if len(head) < 8:
                continue
            (slices,) = struct.unpack(_FAT_MAGICS[magic], head[4:])
            if not 0 < slices <= _MAX_FAT_SLICES:
                continue
        yield path


def parse_minos(otool_output: str) -> tuple[int, ...] | None:
    """The deployment target of `otool -l` output: `minos` of an
    LC_BUILD_VERSION, `version` of an LC_VERSION_MIN_MACOSX. The
    highest of several, or None when the output has neither."""
    found = [
        tuple(int(part) for part in match.split("."))
        for match in _DEPLOYMENT_TARGET.findall(otool_output)
    ]
    return max(found) if found else None


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _above(version: tuple[int, ...], ceiling: tuple[int, ...]) -> bool:
    """`15.0.0` is not above `15.0`: tuples compare after padding."""
    width = max(len(version), len(ceiling))
    pad = (0,) * width
    return (version + pad)[:width] > (ceiling + pad)[:width]


def _why(error: subprocess.CalledProcessError) -> str:
    return (error.stderr or "").strip() or f"exit {error.returncode}"


def check_bundle(
    app: Path,
    architecture: str,
    minimum_system_version: str,
    run: ToolRunner = run_tool,
) -> list[str]:
    """Every way `app` fails the check, as sentences; empty when it
    passes."""
    problems: list[str] = []
    ceiling = _version(minimum_system_version)
    main_executable = app / MAIN_EXECUTABLE
    for path in macho_files(app):
        relative = path.relative_to(app)
        try:
            archs = run(["lipo", "-archs", str(path)]).split()
        except subprocess.CalledProcessError as error:
            problems.append(f"lipo could not read {relative}: {_why(error)}.")
            continue
        if architecture not in archs:
            problems.append(
                f"{relative} has {' '.join(archs) or 'no architecture'}, "
                f"not {architecture}."
            )
            continue
        if path == main_executable and archs != [architecture]:
            problems.append(
                f"{relative} is not thin: {' '.join(archs)}."
            )
        try:
            minos = parse_minos(
                run(["otool", "-arch", architecture, "-l", str(path)]),
            )
        except subprocess.CalledProcessError as error:
            problems.append(f"otool could not read {relative}: {_why(error)}.")
            continue
        if minos is not None and _above(minos, ceiling):
            problems.append(
                f"{relative} needs macOS {'.'.join(map(str, minos))}, "
                f"above the bundle's {minimum_system_version}."
            )
    if not main_executable.is_file():
        problems.append(f"{MAIN_EXECUTABLE} is missing from the bundle.")
    return problems

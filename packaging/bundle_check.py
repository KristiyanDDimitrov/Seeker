"""The post-build check of a macOS bundle, run by build_dmg.py after
PyInstaller: every Mach-O in the bundle carries the target architecture,
the main executable is thin, and no binary's `minos` is above
`bundle_info.MINIMUM_SYSTEM_VERSION`. It repeats, on every build, the
one-off `otool -l` measurement of HISTORY §214.

A tool runner is a callable taking a command list and returning stdout,
so a test can stand in for `lipo` and `otool`.
"""

import re
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
            if handle.read(4) in _MACHO_MAGICS:
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
        archs = run(["lipo", "-archs", str(path)]).split()
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
        minos = parse_minos(
            run(["otool", "-arch", architecture, "-l", str(path)]),
        )
        if minos is not None and minos > ceiling:
            problems.append(
                f"{relative} needs macOS {'.'.join(map(str, minos))}, "
                f"above the bundle's {minimum_system_version}."
            )
    if not main_executable.is_file():
        problems.append(f"{MAIN_EXECUTABLE} is missing from the bundle.")
    return problems

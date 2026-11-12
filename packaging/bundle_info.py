"""The macOS bundle's identity and Info.plist, beside seeker.spec rather
than inside it so a test can read them (tests/test_bundle_info.py).

Each value has one source: the version is pyproject.toml's, the
copyright LICENSE's own line, a licence text the wheel's own.
"""

import os
import platform
import re
import shutil
import sys
import sysconfig
import tomllib
from importlib import metadata
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

# Decided before the first release and never changed after it: the
# login item, notification permission and Launch Services key on it.
BUNDLE_IDENTIFIER = "io.github.kristiyanddimitrov.seeker"

# The highest `minos` among the binaries the bundle ships: PySide6's
# and shiboken6's own libraries declare 15.0 (measured with `otool -l`
# against PySide6 6.11.2, whose wheel tag says 13.0; Qt's frameworks
# declare 13.0, scipy's arm64 wheel 14.0). Whether it would run on 14
# anyway is UNVERIFIED; this makes Launch Services refuse it plainly.
# Re-measure after a PySide6, scipy or Python upgrade (HISTORY §214).
MINIMUM_SYSTEM_VERSION = "15.0"

SUPPORTED_ARCHITECTURES = ("arm64", "x86_64")


def target_architecture(machine: str | None = None) -> str:
    """The architecture this build targets: the building interpreter's,
    passed to PyInstaller's `target_arch` so each bundle is one
    architecture on purpose, never by default. `machine` is
    `platform.machine()`'s value (macOS says `arm64` or `x86_64`).
    """
    machine = platform.machine() if machine is None else machine
    if machine not in SUPPORTED_ARCHITECTURES:
        raise ValueError(
            f"Cannot build for {machine!r}: the macOS app is built for "
            f"{' or '.join(SUPPORTED_ARCHITECTURES)}."
        )
    return machine


def project_version(project_root: Path) -> str:
    with (project_root / "pyproject.toml").open("rb") as pyproject:
        version: str = tomllib.load(pyproject)["project"]["version"]
    return version


def copyright_line(project_root: Path) -> str:
    for line in (project_root / "LICENSE").read_text(encoding="utf-8").splitlines():
        if line.startswith("Copyright"):
            return line
    raise ValueError("LICENSE has no Copyright line.")


def info_plist(project_root: Path) -> dict[str, object]:
    version = project_version(project_root)
    return {
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHumanReadableCopyright": copyright_line(project_root),
        "LSApplicationCategoryType": "public.app-category.music",
        "LSMinimumSystemVersion": MINIMUM_SYSTEM_VERSION,
    }


# The bundle's folder of licence texts: licenses/<distribution>/.
LICENSES_DIR = "licenses"

VENDORED_LICENSES_DIR = Path(__file__).resolve().parent / "licenses"

# Runtime distributions whose wheels carry no licence text, and the
# texts in VENDORED_LICENSES_DIR the bundle ships for them instead.
# PySide6 and shiboken6 are LGPL-3.0-only OR GPL-2.0-only OR
# GPL-3.0-only (their METADATA); the LGPL-3.0 is a set of permissions
# on top of the GPL-3.0, so it ships with it. pyobjc-core's MIT text is
# the one PyObjC's framework wheels carry (HISTORY §215).
VENDORED_LICENSES: dict[str, tuple[str, ...]] = {
    "pyside6": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "pyside6-addons": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "pyside6-essentials": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "shiboken6": ("LGPL-3.0.txt", "GPL-3.0.txt"),
    "pyobjc-core": ("PyObjC-MIT.txt",),
}

# A licence file an older wheel keeps beside METADATA rather than in
# the licenses/ folder PEP 639 defines.
_LICENSE_NAME = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)


def runtime_distributions(root: str = "seeker") -> dict[str, metadata.Distribution]:
    """`root` and every installed distribution it needs at run time, by
    canonical name: requirements followed through each one's markers
    for this machine, with the extras its dependent asked for."""
    found: dict[str, metadata.Distribution] = {}
    walked: set[tuple[str, frozenset[str]]] = set()
    pending: list[tuple[str, frozenset[str]]] = [(root, frozenset())]
    while pending:
        name, extras = pending.pop()
        key = canonicalize_name(name)
        if (key, extras) in walked:
            continue
        walked.add((key, extras))
        distribution = found.setdefault(key, metadata.distribution(name))
        for line in distribution.requires or []:
            requirement = Requirement(line)
            if requirement.marker is None or any(
                    requirement.marker.evaluate({"extra": extra})
                    for extra in extras or {""}
            ):
                pending.append(
                    (requirement.name, frozenset(requirement.extras)),
                )
    return found


def own_license_files(
        distribution: metadata.Distribution,
) -> list[tuple[Path, PurePosixPath]]:
    """The licence files a wheel carries in its .dist-info, each with
    its path inside the distribution's licence folder."""
    files = []
    for file in distribution.files or []:
        parts = PurePosixPath(file).parts
        if not parts[0].endswith(".dist-info"):
            continue
        if len(parts) > 2 and parts[1] == "licenses":
            relative = PurePosixPath(*parts[2:])
        elif len(parts) == 2 and _LICENSE_NAME.match(parts[1]):
            relative = PurePosixPath(parts[1])
        else:
            continue
        files.append((Path(str(distribution.locate_file(file))), relative))
    return files


def python_license() -> Path:
    """The interpreter's own LICENSE.txt, which the bundle embeds: in
    the standard library's folder on macOS (observed), at the prefix
    on Windows (UNVERIFIED)."""
    for candidate in (
            Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
            Path(sys.base_prefix) / "LICENSE.txt",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("This Python ships no LICENSE.txt.")


def license_datas(project_root: Path) -> list[tuple[str, str]]:
    """PyInstaller `datas` for the bundle's licence folder: Seeker's
    LICENSE, Python's, and each runtime distribution's own texts, or
    the vendored ones for a wheel that carries none.

    Raises ValueError for a distribution with neither, so a new
    dependency cannot ship without its text, and for one with both, so
    a vendored entry goes once its wheel carries the real one.
    """
    datas = [
        (str(project_root / "LICENSE"), f"{LICENSES_DIR}/seeker"),
        (str(python_license()), f"{LICENSES_DIR}/python"),
    ]
    for name, distribution in sorted(runtime_distributions().items()):
        if name == "seeker":
            continue
        folder = PurePosixPath(LICENSES_DIR, name)
        own = own_license_files(distribution)
        vendored = VENDORED_LICENSES.get(name, ())
        if own and vendored:
            raise ValueError(
                f"{name} now ships its own licence text; remove its "
                f"VENDORED_LICENSES entry."
            )
        if not own and not vendored:
            raise ValueError(
                f"{name} ships no licence text: vendor one under "
                f"packaging/licenses/ and name it in VENDORED_LICENSES."
            )
        datas += [
            (str(source), str(folder / relative.parent))
            for source, relative in own
        ]
        datas += [
            (str(VENDORED_LICENSES_DIR / text), str(folder))
            for text in vendored
        ]
    return datas


# The Intel bundle ships libchromaprint; the arm64 one finds the user's
# Homebrew copy (audio/fingerprint.py searches _MEIPASS first, then the
# Homebrew prefixes). The build stages the copy from
# SEEKER_CHROMAPRINT_DIR when that names a folder, else from
# /usr/local/lib, the prefix Intel Homebrew used and where
# packaging/build_chromaprint.sh installs by default. A Mac with no
# /usr/local/lib builds into a folder of its own and sets the variable
# to that folder's lib/.
CHROMAPRINT_LIBRARY = "libchromaprint.1.dylib"
CHROMAPRINT_DIR_VARIABLE = "SEEKER_CHROMAPRINT_DIR"
INTEL_HOMEBREW_LIB = Path("/usr/local/lib")
CHROMAPRINT_LICENSE_TEXTS = ("Chromaprint-LICENSE.md", "LGPL-2.1.txt")


def chromaprint_library_dir() -> Path:
    """The folder the Intel build stages libchromaprint from: the
    environment's choice when it is set and not empty."""
    chosen = os.environ.get(CHROMAPRINT_DIR_VARIABLE)
    return Path(chosen) if chosen else INTEL_HOMEBREW_LIB


def chromaprint_binaries(
    architecture: str,
    staging_dir: Path,
    library_dir: Path | None = None,
) -> list[tuple[str, str]]:
    """PyInstaller `binaries` for libchromaprint: the Intel build's
    copy, staged under the soname fingerprint.py loads (Homebrew keeps
    the real file under a versioned name), or nothing for arm64.

    `library_dir` None means `chromaprint_library_dir()`. Raises
    FileNotFoundError when the Intel build has no library to ship, so a
    build never silently loses fingerprinting.
    """
    if architecture != "x86_64":
        return []
    if library_dir is None:
        library_dir = chromaprint_library_dir()
    source = library_dir / CHROMAPRINT_LIBRARY
    if not source.is_file():
        raise FileNotFoundError(
            f"{CHROMAPRINT_LIBRARY} is not in {library_dir.absolute()}. "
            f"Build it with packaging/build_chromaprint.sh <prefix>, "
            f"which installs to <prefix>/lib, then build the app with "
            f"{CHROMAPRINT_DIR_VARIABLE}=<prefix>/lib (without the "
            f"variable the build looks in {INTEL_HOMEBREW_LIB})."
        )
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged = staging_dir / CHROMAPRINT_LIBRARY
    shutil.copyfile(source, staged)  # follows the symlink
    return [(str(staged), ".")]


def chromaprint_license_datas(architecture: str) -> list[tuple[str, str]]:
    """PyInstaller `datas` for the texts that go with the library: its
    own MIT-and-LGPL-2.1 notice and the LGPL-2.1 itself."""
    if architecture != "x86_64":
        return []
    return [
        (str(VENDORED_LICENSES_DIR / text), f"{LICENSES_DIR}/chromaprint")
        for text in CHROMAPRINT_LICENSE_TEXTS
    ]

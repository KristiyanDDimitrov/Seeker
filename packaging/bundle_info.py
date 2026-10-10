"""The macOS bundle's identity and Info.plist, beside seeker.spec rather
than inside it so a test can read them (tests/test_bundle_info.py).

Each value has one source: the version is pyproject.toml's, the
copyright LICENSE's own line, a licence text the wheel's own.
"""

import re
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


def project_version(project_root: Path) -> str:
    with (project_root / "pyproject.toml").open("rb") as pyproject:
        version: str = tomllib.load(pyproject)["project"]["version"]
    return version


def copyright_line(project_root: Path) -> str:
    for line in (project_root / "LICENSE").read_text().splitlines():
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

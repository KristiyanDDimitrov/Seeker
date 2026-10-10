"""The macOS bundle's identity and Info.plist, beside seeker.spec rather
than inside it so a test can read them (tests/test_bundle_info.py).

Each value has one source: the version is pyproject.toml's, the
copyright LICENSE's own line.
"""

import tomllib
from pathlib import Path

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

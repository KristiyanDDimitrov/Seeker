"""Convenience wrapper chaining packaging/seeker.spec's PyInstaller
build with packaging/seeker.iss's Inno Setup compile step — the
Windows equivalent of packaging/build_dmg.py:

    uv run python packaging/build_windows_installer.py

Produces dist/Seeker/ (via PyInstaller) and dist/SeekerSetup.exe (via
Inno Setup) in one call. Either step can still be run on its own:

    uv run pyinstaller --noconfirm --clean packaging/seeker.spec
    ISCC.exe packaging/seeker.iss

Requires Inno Setup (https://jrsoftware.org/isinfo.php) installed
separately — unlike dmgbuild, there's no Python package that compiles
.iss files, so ISCC.exe (Inno Setup's command-line compiler) needs to
already be on PATH, or its full path passed via --iscc. This mirrors
this project's existing precedent of a real external prerequisite
(Docker, for slskd) that uv-managed dependencies can't install for you.

WRITTEN BUT NOT VERIFIED ON A REAL WINDOWS MACHINE — no such
environment exists in this project's development session. See
CLAUDE.md roadmap item 36 and README's packaging section.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = PROJECT_ROOT / "packaging"
DIST_DIR = PROJECT_ROOT / "dist"
APP_DIR = DIST_DIR / "Seeker"
INSTALLER_PATH = DIST_DIR / "SeekerSetup.exe"


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit(
            "packaging/build_windows_installer.py only makes sense on "
            "Windows — Inno Setup itself is a Windows-only tool."
        )

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--iscc",
        default="ISCC.exe",
        help=(
            "Path to Inno Setup's command-line compiler "
            "(default: assumes it's on PATH)."
        ),
    )
    args = parser.parse_args()

    iscc_path = shutil.which(args.iscc) or args.iscc

    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            str(PACKAGING_DIR / "seeker.spec"),
        ],
        check=True,
        cwd=PROJECT_ROOT,
    )

    if not APP_DIR.is_dir():
        raise SystemExit(
            f"Expected {APP_DIR} after the PyInstaller build but it "
            "doesn't exist — check seeker.spec's COLLECT() step."
        )

    if INSTALLER_PATH.exists():
        INSTALLER_PATH.unlink()

    subprocess.run(
        [iscc_path, str(PACKAGING_DIR / "seeker.iss")],
        check=True,
        cwd=PROJECT_ROOT,
    )

    print(f"Built {INSTALLER_PATH}")


if __name__ == "__main__":
    main()

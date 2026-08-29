"""Convenience wrapper chaining packaging/seeker.spec's PyInstaller
build with packaging/dmg_settings.py's dmgbuild step — the two
commands documented in README's "Building a standalone app" section,
run back to back:

    uv run python packaging/build_dmg.py

Produces dist/Seeker.app (via PyInstaller) and dist/Seeker.dmg (via
dmgbuild) in one call. Either step can still be run on its own with
the commands in the README — this is a convenience, not a
replacement.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = PROJECT_ROOT / "packaging"
DIST_DIR = PROJECT_ROOT / "dist"
APP_PATH = DIST_DIR / "Seeker.app"
DMG_PATH = DIST_DIR / "Seeker.dmg"


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "packaging/build_dmg.py only makes sense on macOS — "
            "dmgbuild and .app bundling are both darwin-only."
        )

    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            str(PACKAGING_DIR / "seeker.spec"),
        ],
        check=True,
        cwd=PROJECT_ROOT,
    )

    if not APP_PATH.is_dir():
        raise SystemExit(
            f"Expected {APP_PATH} after the PyInstaller build but it "
            "doesn't exist — check seeker.spec's BUNDLE() step."
        )

    if DMG_PATH.exists():
        DMG_PATH.unlink()

    subprocess.run(
        [
            sys.executable, "-m", "dmgbuild",
            "-s", str(PACKAGING_DIR / "dmg_settings.py"),
            "-D", f"app={APP_PATH}",
            "Seeker",
            str(DMG_PATH),
        ],
        check=True,
        cwd=PROJECT_ROOT,
    )

    print(f"Built {DMG_PATH}")


if __name__ == "__main__":
    main()

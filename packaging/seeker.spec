# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for seeker-ui (the desktop app), one-folder/
`.app` mode.

De-risked first (see docs/HISTORY.md's packaging entry, roadmap item
30): librosa/numba/llvmlite/soundfile all freeze cleanly with ZERO
custom hidden-import/collect-all directives here — `pyinstaller-hooks-
contrib` (a declared dev dependency) already ships hooks for all four
that PyInstaller auto-discovers via entry points, confirmed live by
building a minimal frozen binary that actually calls
`audio_analysis.analyze_audio()` against a real WAV and got the exact
same BPM/key/confidence numbers as the unfrozen run. Don't add
`--collect-all`-equivalent directives for these back in speculatively —
the spike confirmed they're not needed and only bloat the build
(pulling in numba's own test suite, for example).

One-folder (COLLECT), not one-file: verified live, not assumed —
numba's JIT cache lives in a stable on-disk location and is genuinely
reused across runs of a one-folder build (a warm second run dropped
from ~3.5s to ~1.0s wall-clock in the spike). A one-file build
re-extracts to a fresh temp directory on every launch, so the JIT
cache never persists — the same spike's one-file build took ~21s cold
and stayed ~18s warm, 15-20x slower for no benefit to this app (no
single-file-distribution requirement exists here).

Docker is explicitly NOT bundled — this spec packages the Python/Qt
app only. The onboarding wizard's existing Docker detection/bring-up
flow (docker_setup.py) is unchanged and still expects a real, separate
Docker install.

Code signing / notarization: explicitly out of scope (needs a paid
Apple Developer account this environment doesn't have). The hook point
for it is `codesign_identity=`/`entitlements_file=` on the `EXE(...)`
call below, and a real notarization step would run against the built
`.app` afterward (`xcrun notarytool` / `stapler`) — left as a clear,
documented no-op rather than attempted. This build is unsigned;
Gatekeeper will warn on first launch on a machine that isn't this one
— expected, not a bug to route around.
"""

import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 — injected into spec globals by PyInstaller
PROJECT_ROOT = SPEC_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

APP_NAME = "Seeker"

# The only bundled non-Python resource this app currently needs at
# runtime — see seeker/docker_setup.py::compose_file_path(), which
# resolves this same file via sys._MEIPASS in a frozen build. Placed
# at the bundle root ('.') so that resolution is a flat, one-level
# lookup on both sides.
datas = [
    (str(PROJECT_ROOT / "docker-compose.yml"), "."),
]

a = Analysis(
    [str(SPEC_DIR / "entrypoint.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    # Signing hook point (out of scope here, see module docstring):
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# macOS-only: wrap the one-folder COLLECT output in a real .app bundle.
# On Windows/Linux the COLLECT output above (an "Seeker/" folder with
# Seeker.exe / Seeker inside) is the actual deliverable — there's no
# equivalent BUNDLE() step on those platforms. Unverified on real
# Windows/Linux machines — see README's "Building a standalone app"
# section.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.seeker.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHumanReadableCopyright": "",
        },
    )

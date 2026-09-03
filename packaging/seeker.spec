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

Code signing / notarization: real notarization is explicitly out of
scope (needs a paid Apple Developer account this environment doesn't
have). The hook point for a real signing identity is
`codesign_identity=`/`entitlements_file=` on the `EXE(...)` call below
(currently `None`), and a real notarization step would run against the
built `.app` afterward (`xcrun notarytool` / `stapler`) — left as a
clear, documented no-op rather than attempted.

**Confirmed live (item 4, packaging polish task): the build is NOT
fully unsigned even with `codesign_identity=None`.** PyInstaller's own
`osxutils.sign_binary()` defaults to ad-hoc signing (`codesign -s -`)
whenever no real identity is given, and applies this to both the
individual frozen executable (during `EXE`) and the whole `.app`
bundle, `--deep` (during `BUNDLE`) — verified directly against a real
build: `codesign -dvvv dist/Seeker.app` shows `flags=0x2(adhoc)` /
`Signature=adhoc`, and `codesign --verify --deep --strict
dist/Seeker.app` exits 0. This is real and already happening — no
extra build step was needed to add it. It does NOT satisfy Gatekeeper
(`spctl --assess` still reports "rejected", as expected — ad-hoc
signing isn't notarization), so first-launch-on-another-Mac still needs
the right-click → Open workaround, which is why `packaging/Read Me
First.txt` (bundled into the `.dmg` — see dmg_settings.py) exists.
"""

import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 — injected into spec globals by PyInstaller
PROJECT_ROOT = SPEC_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

APP_NAME = "Seeker"

ICONS_DIR = SPEC_DIR / "icons"
ICON_ICNS = ICONS_DIR / "seeker_icon.icns"
ICON_ICO = ICONS_DIR / "seeker_icon.ico"

# EXE()'s icon is only actually applied on Windows (embeds it in
# Seeker.exe, which the Inno Setup shortcuts then inherit) and macOS
# (rarely visible — BUNDLE()'s own icon= below is what Finder/Dock
# actually show); ignored on Linux. Pick the format each platform
# understands rather than passing one file everywhere.
if sys.platform == "win32":
    EXE_ICON: str | None = str(ICON_ICO)
elif sys.platform == "darwin":
    EXE_ICON = str(ICON_ICNS)
else:
    EXE_ICON = None

# Bundled non-Python resources needed at runtime, not just at build
# time — see seeker/docker_setup.py::compose_file_path(), which
# resolves docker-compose.yml via sys._MEIPASS in a frozen build.
# Roadmap item R7.2 — the menu-bar tray icon needs the SAME treatment:
# ICONS_DIR above is otherwise only ever read here, at build time, to
# set EXE()/BUNDLE()'s own icon= (which macOS/Windows apply to the
# app bundle/executable, not something the running process can read
# back out) — without this entry, ui/main_window.py's own
# sys._MEIPASS-gated resolution would find nothing in a real packaged
# build and fall back to a blank tray icon. Bundled as a whole
# directory (not a single file, unlike docker-compose.yml above) so
# both .icns/.ico ship together at "icons/" and resolve with the exact
# same relative path this repo's own dev-mode tree already has.
datas = [
    (str(PROJECT_ROOT / "docker-compose.yml"), "."),
    (str(ICONS_DIR), "icons"),
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
    icon=EXE_ICON,
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
        icon=str(ICON_ICNS),
        bundle_identifier="com.seeker.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHumanReadableCopyright": "",
        },
    )

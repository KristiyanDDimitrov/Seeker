# Building Seeker

`seeker-ui` packages into a self-contained desktop app with
[PyInstaller](https://pyinstaller.org/): no Python or `uv` needed on the
machine that runs it. Docker is **not** bundled, and is not meant to
be. slskd still runs in a separate Docker install, which the onboarding
wizard detects and starts.

| Platform | Status |
|---|---|
| macOS | Built and verified on real hardware: the `.app`, the `.dmg`, and the app launched after being copied to `/Applications`. |
| Windows | **Written, never verified on real hardware.** `seeker.spec` is cross-platform and `packaging/seeker.iss` is a complete Inno Setup script, but neither has run on a Windows machine. |
| Linux | **Written, never verified on real hardware.** The same `seeker.spec`; no installer format (AppImage, `.deb`) is scoped. |

Treat the Windows and Linux rows as unverified until someone runs the
build on those platforms.

## The app

```
uv sync --group dev                     # pulls in PyInstaller and dmgbuild
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
```

Output lands in `dist/`: a one-folder build (`dist/Seeker/`) on every
platform, plus `dist/Seeker.app` on macOS.

- **Bundled resources:** `docker-compose.yml` (the template the wizard
  copies before starting slskd), `packaging/icons/` and
  `packaging/fonts/` (Barlow Semi Condensed, with its OFL licence).
  A frozen build finds them through `sys._MEIPASS`; `sys.frozen` gates
  every such lookup, and nothing else about a frozen run differs from
  `uv run seeker-ui`.
- **One folder, not one file, on purpose.** librosa's numba JIT cache
  persists across runs only in a one-folder build: about 1 s warm
  against 18–21 s on every launch of a one-file build, which
  re-extracts to a fresh temporary directory each time.
  [HISTORY §30](history/025-031.md#30)
- **Runtime dependencies only.** A built app contains no pytest, mypy
  or ruff files (checked in the bundle, not assumed).
- **Build identity.** `packaging/build_dmg.py` writes the gitignored
  `src/seeker/_build_info_generated.py` (the git SHA, `git describe`
  and the build time), which About and Help show, and deletes it once
  the build ends, failed or not. The tracked `_build_info.py` imports
  it only when frozen, falling back to `"dev"`; never write the
  tracked file. The wheel excludes it too.
  [HISTORY §83](history/072-107.md#83)
- **Info.plist** comes from `packaging/bundle_info.py`: the version is
  `pyproject.toml`'s, the copyright `LICENSE`'s line, the category
  Music, and the minimum macOS 15.0, the highest `minos` among the
  bundled binaries (PySide6's own; re-measure after an upgrade).
  [HISTORY §214](history/211-240.md#214)

## The macOS `.dmg`

```
uv run python packaging/build_dmg.py
```

This runs the PyInstaller build, then
[`dmgbuild`](https://dmgbuild.readthedocs.io/) with
`packaging/dmg_settings.py`, producing `dist/Seeker.dmg`. The two steps
can also run on their own:

```
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
uv run dmgbuild -s packaging/dmg_settings.py -Dapp=dist/Seeker.app Seeker dist/Seeker.dmg
```

The volume holds the app, an `/Applications` link and
`Read Me First.txt`, in a sized window with no toolbar, sidebar or
status bar. The custom icon (`packaging/icons/seeker_icon.icns`) is set
on both the `.app` (`seeker.spec`'s `BUNDLE()`) and the volume
(`dmg_settings.py`), and was confirmed to render on both.
[HISTORY §31](history/025-031.md#31), [§42](history/032-046.md#42)

### What was verified

On 2026-08-29 the real `.app` was launched with `open dist/Seeker.app`
against a real configuration, then a throwaway frozen build with the
same `Analysis` was driven under `QT_QPA_PLATFORM=offscreen` (Qt's
headless platform, so no Screen Recording or Accessibility permission
was needed). The wizard opened at its Spotify step, Connect built a
real PKCE authorization URL, Sync, Scan and Match completed against the
real library, "Set up later" finished onboarding without Docker, and
Settings showed the real configuration.

The `.dmg` was then mounted and the app copied to `/Applications`,
a different path from the build directory, and launched from there:
17 of 17 checks passed, including the one a `.dmg` puts at risk, that
`docker_setup.compose_file_path()` finds the bundled
`docker-compose.yml` relative to wherever the running binary lives.
The copies were removed afterwards.
[HISTORY §30](history/025-031.md#30), [§31](history/025-031.md#31)

### Signing and Gatekeeper

The build is **ad-hoc signed, not notarized**, which is not the same
as unsigned. PyInstaller ad-hoc-signs the executable and the bundle by
default: `codesign -dvvv` shows `Signature=adhoc`, and
`codesign --verify --deep --strict` passes. Gatekeeper still rejects
it (`spctl --assess`), as it does every non-notarized build, so the
first launch on any other Mac needs Control-click → Open, then Open
again. `Read Me First.txt` on the volume says so.
[HISTORY §36](history/032-046.md#36)

Notarization needs a paid Apple Developer account. The hooks for it
are marked in `packaging/seeker.spec`: `codesign_identity=` and
`entitlements_file=` on `EXE(...)`, followed by `xcrun notarytool` and
`stapler` on the built `.app`.

### Native libraries

CI's audit job (`tools/audit_dependencies.py`) runs pip-audit over
`uv.lock`. pip-audit reads Python package metadata, so it cannot see
the native code bundled inside wheels or the interpreter. Those
versions are recorded here instead. At each release, re-read them,
compare, and check each one that changed or has a new advisory
against its upstream security notes.

| Library | Version (2026-10-09) | Arrives with | Reads peer files? |
|---|---|---|---|
| libsndfile | 1.2.2 | soundfile 0.14.0's wheel | yes: BPM, key, loudness |
| Qt | 6.11.2 | PySide6 6.11.2 | no |
| OpenSSL | 3.5.7 | Python 3.13.15 | no |
| SQLite | 3.53.1 | Python 3.13.15 | no |
| ffmpeg | 9.0.1 | Homebrew, not bundled | yes: fingerprints |
| libchromaprint | 1.6.1 | Homebrew, not bundled | decoded audio only |

The bundled four, from the environment the build uses:

```
uv run python -c "import ssl, sqlite3, soundfile; from PySide6 import QtCore; print(ssl.OPENSSL_VERSION, sqlite3.sqlite_version, soundfile.__libsndfile_version__, QtCore.qVersion())"
```

`ffmpeg -version` and `brew list --versions chromaprint` read the
other two.

**Tracked, because they decode peer files unsandboxed (AUDIT S-03,
accepted):** open against libsndfile 1.2.2 on 2026-10-09 are
CVE-2026-37555 (IMA ADPCM), CVE-2025-56226 (an mpeg_l3 leak) and
CVE-2024-50612 (ogg_vorbis, encoder-side). At each release, take the
first soundfile wheel or ffmpeg that fixes one, and update this list. The bundled four match the security audit's reading of
the `dist/Seeker.app` built on 2026-10-08 (`docs/rounds/round-12/
AUDIT.md` §9).
[HISTORY §199](history/181-210.md#199)

## The Windows installer

**Written, never verified on real hardware.**

`packaging/seeker.iss` is an [Inno Setup](https://jrsoftware.org/isinfo.php)
script wrapping the same one-folder build: a `Setup.exe` with Start
Menu and Desktop shortcuts, an uninstall entry, and the icon
`packaging/icons/seeker_icon.ico`. Inno Setup is a separate Windows
tool that `uv` cannot install; put its compiler, `ISCC.exe`, on `PATH`
(or pass `--iscc`).

```
uv run python packaging/build_windows_installer.py
```

or the two steps by hand:

```
uv run pyinstaller --noconfirm --clean packaging/seeker.spec
ISCC.exe packaging\seeker.iss
```

Either produces `dist/SeekerSetup.exe`. The script's `AppId` is a
fixed GUID that lets Inno Setup recognise an upgrade as the same app;
never regenerate it. No code signing is configured, so SmartScreen will
likely warn about the installer.
[HISTORY §36](history/032-046.md#36)

# Changelog

All notable changes to Seeker are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Seeker
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
`RELEASING.md` says how a release is cut.

## [Unreleased]

### Changed

- **CI type-checks the Windows code paths:** `check` also runs
  `mypy --strict --platform win32 src/`; a run on macOS never checks
  what sits under `if sys.platform == "win32":`.
- **CI runs the suite on Windows:** a `check-windows` job on
  `windows-2025`, which does not fail the run until the suite passes
  there.
- **On Windows, the programs Seeker starts open no console window**,
  and their output reads as UTF-8 (a byte that is not UTF-8 reads as
  U+FFFD instead of failing the call, on macOS too).

## [0.2.0] - 2026-11-04

### Added

- **An Intel Mac build, `Seeker-Intel.dmg`,** beside `Seeker.dmg`, which
  stays the Apple silicon image. Both need macOS 15 or later; the
  README's Install section says which to download. The Intel app carries
  its own copy of libchromaprint 1.6.2, built from source (Homebrew
  builds no Intel bottles), so Duplicates needs no `brew install
  chromaprint` there. An M4A or AAC file still needs ffmpeg, in either
  app: the bundled audio library cannot open it. A smoke test of the
  built app found libchromaprint on GitHub's Intel runner after the job
  deleted the build machine's own copy (Build run 41537431447), though
  not yet on an Intel Mac of anyone's own. The Apple silicon app still
  uses Homebrew's. Every build now checks its own bundle: each binary
  carries the build's architecture and none needs a newer macOS than
  15.0.
- **Help and About name the architecture Seeker runs as:** Apple
  silicon, Intel, or the Intel build on Apple silicon (Rosetta), with
  a pointer to the faster Apple silicon download.
- **`seeker-ui --smoke-test [REPORT]` checks a build and exits:** it
  checks a frozen build carries its identity, imports every module and
  the macOS frameworks the spec bundles by hand, finds the native Qt
  platform plugin, applies both themes offscreen and loads the bundled
  fonts (each weight from its own file), icons and Compose template,
  times two analyses of a generated click track and says whether
  chromaprint loads, then prints a JSON report (also written to
  `REPORT`) and exits 0, or 1 naming what failed or the report it
  could not write. It touches no settings, database or library.

### Changed

- **CI runs the suite on an Intel Mac too:** a blocking `check-intel` job
  on `macos-15-intel` beside `check`; both fail, not skip, the
  real-chromaprint tests when the library is missing.
- **CI builds and smoke-tests both apps:** a `Build` workflow (on
  dispatch, `v*` tags and changes to the build inputs) builds
  `Seeker.dmg` on `macos-26` and `Seeker-Intel.dmg` on `macos-15-intel`,
  runs each frozen app's `--smoke-test` and uploads the image and report
  for a week. It never publishes. The Intel job builds libchromaprint
  from a pinned source with `packaging/build_chromaprint.sh`, since
  Homebrew no longer builds Intel bottles.
- **Spotify Premium is named up front.** Spotify runs an app in
  Development Mode, which every Seeker user's own Spotify app is, only
  while its owner has Premium. The setup wizard's Spotify step and the
  README's Install section now say so.
- **The lock pins Intel Mac wheels.** numba publishes no Intel macOS
  wheels after 0.62.1, so for Intel Macs the lock pins numba 0.62.1,
  llvmlite 0.45.1 and numpy 2.3, each with a macOS x86_64 wheel;
  Apple silicon and Windows keep their versions.
- **A new SoulSeek setup runs slskd 0.26.2** (0.26.0 before). An
  existing setup keeps the slskd version it was set up with. Seeker
  reads slskd's log where 0.26.2 keeps it, falling back to 0.26.0's
  place, so a wrong SoulSeek password or a login from elsewhere is
  still reported with either version.

## [0.1.1] - 2026-10-26

A security release; nothing else changes.

### Security

- **Certificate authorities updated** (certifi 2026.10.23,
  PYSEC-2026-4320). 0.1.0 still trusted the emSign ECC Root CA - G3,
  whose revoked intermediate certificates had compromised keys:
  someone holding one of those keys and sitting on your network path
  could have impersonated Spotify or GitHub to Seeker. Its
  connections now reject that root.
- **Build tooling updated** (setuptools 84.2.1, GHSA-xmj3-9gf7-h52w):
  a Windows-only flaw in the tool that builds the app. Nothing in the
  installed macOS app used it.

## [0.1.0] - 2026-10-14

The first public release: a macOS desktop app (`Seeker.dmg`) and a
command-line tool (`seeker`) over one shared core.

### Added

- **Spotify playlist sync** into a local SQLite cache. A playlist's
  tracks are read again only when Spotify reports that it changed, to
  spare the API's rate limits.
- **Matching against your library.** Library folders are scanned and
  each track is fuzzy-matched to your files: matched, needs review or
  missing. A match you confirm stays confirmed; a file you reject is
  never suggested again. Review confirms one track at a time, or a
  whole section at once after asking.
- **SoulSeek downloads through slskd**, a self-hosted daemon that
  Seeker sets up in Docker, and starts again from Settings →
  Connections if its container is removed. Candidates are ranked by format, bitrate
  and the peer's queue; up to three backups stand behind the chosen
  file and take over if it fails. A better file that isn't available
  yet is kept as an upgrade to accept later.
- **Placement that never overwrites.** A finished download is moved
  to its playlist's destination folder, indexed and matched, and
  never lands on an existing file.
- **Downloads page** with Retry, Cancel and a cleanup of leftover
  files in slskd's download folder, which lists what it would delete
  before it deletes anything.
- **An optional daily sweep** that searches again for tracks still
  missing from loaded playlists, at most once a day, and reports one
  summary. Off by default.
- **Tagging** with Spotify's artist, title, album and cover art, with
  optional BPM and Camelot key analysis and `Artist - Title` renames.
- **Duplicates by sound:** audio fingerprints find the same recording
  under different names, and you choose which copy to keep.
- **Sharing back, opt-in:** nothing is shared until you choose a
  folder, at setup or later. Then what your slskd shares, who is
  downloading from you, and adding a library folder to the share.
- **Light, dark and follow-system themes**, a menu-bar icon, and an
  optional start at login.
- **An optional update check** against GitHub releases, at most once a
  day. Off by default; Help → "Check for updates…" asks on demand.
  Seeker never downloads or installs anything itself.

### Known limitations

- The macOS build is ad-hoc signed, not notarized: the first launch
  needs System Settings → Privacy & Security → Open Anyway (see
  `Read Me First.txt` on the disk image). It needs macOS 15 or later
  on Apple silicon.
- SoulSeek needs Docker Desktop. Duplicate detection needs
  `brew install chromaprint`.
- Windows and Linux packaging is written but has never run on real
  hardware.

[Unreleased]: https://github.com/KristiyanDDimitrov/Seeker/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/KristiyanDDimitrov/Seeker/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/KristiyanDDimitrov/Seeker/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KristiyanDDimitrov/Seeker/releases/tag/v0.1.0

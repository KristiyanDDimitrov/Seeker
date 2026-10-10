# Changelog

All notable changes to Seeker are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Seeker
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
`RELEASING.md` says how a release is cut.

## [Unreleased]

## [0.1.0] - Unreleased

The first public release: a macOS desktop app (`Seeker.dmg`) and a
command-line tool (`seeker`) over one shared core.

### Added

- **Spotify playlist sync** into a local SQLite cache. A playlist's
  tracks are read again only when Spotify reports that it changed, to
  spare the API's rate limits.
- **Matching against your library.** Library folders are scanned and
  each track is fuzzy-matched to your files: matched, needs review or
  missing. A match you confirm stays confirmed; a file you reject is
  never suggested again.
- **SoulSeek downloads through slskd**, a self-hosted daemon that
  Seeker sets up in Docker. Candidates are ranked by format, bitrate
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
- **Sharing back:** what your slskd shares, who is downloading from
  you, and adding a library folder to the share.
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

[Unreleased]: https://github.com/KristiyanDDimitrov/Seeker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KristiyanDDimitrov/Seeker/releases/tag/v0.1.0

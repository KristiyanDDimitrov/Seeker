# Round 13 — release-candidate acceptance (S9)

The checklist for v0.2.0's two images: BRIEF §9, Code's half done
below, Kris's half to do. Tick a box and write what you saw beside it;
a failure becomes a fix row before S10 (never shipped around), and the
local tag is deleted and remade after the fix (RELEASING §3).

## The candidates

Both built 2026-11-04 from the tag, in a clean worktree, on the M4 Pro.

| | |
|---|---|
| Tag | `v0.2.0`, annotated (`3ff929d`), local only, not pushed |
| Commit | `5d3c5e3` ("release: 0.2.0 dated 2026-11-04") |
| CI on it | run `41742930471`: `check`, `check-intel`, `audit` green (`check-windows` failed, non-blocking) |
| Build workflow | run `41649408206` green on `8a1ef65`; `pyproject.toml`, `uv.lock` and `packaging/` unchanged since |
| Images | `.git/autodev/release/v0.2.0/` in the main checkout, each beside its `.sha256` |

| | Apple silicon | Intel |
|---|---|---|
| Disk image | `Seeker.dmg`, 111,871,935 bytes | `Seeker-Intel.dmg`, 123,243,941 bytes |
| SHA-256 | `f30f3d686a94747d7b79180ee778fb503051f96878cb340185f28af2b6b9dfb7` | `9009a6ef436d98ed1f9840dac18a7cfdac09095782007e0d7f912e43cacac025` |
| Help → Build should read | `v0.2.0 — built` 2026-11-04, about 02:26 local (00:26 UTC) | `v0.2.0 — built` 2026-11-04, about 02:30 local (00:30 UTC) |
| Help → Architecture should read | "Apple silicon" | on this Mac, text beginning "Intel build on Apple silicon (Rosetta)" |

## Code checked (2026-11-04, without launching the app)

- [x] The tree at the tag: `git describe` reads `v0.2.0`, clean before
      and after each build. `uv sync --locked`, and the x86_64
      environment from CLAUDE.md → Commands. `2632 passed, 29 skipped`;
      `mypy --strict` clean native and `--platform win32` (149 files);
      `ruff` 0.
- [x] RELEASING §3, Apple silicon app, before the Intel build replaced
      it: `Identifier=io.github.kristiyanddimitrov.seeker`,
      `Signature=adhoc`; `signature ok`; `spctl` rejects (exit 3,
      expected); version `0.2.0` twice, `LSMinimumSystemVersion` 15.0;
      `lipo -archs` `arm64`; no `libchromaprint*` in the bundle. Smoke
      test exit 0: all nine checks pass, `frozen`, build `v0.2.0`,
      architecture "Apple silicon", `chromaprint_available` true
      (Homebrew's arm64 copy; the bundle holds none), analysis 123.05
      BPM cold in 3.4 s, warm in 0.03 s.
- [x] RELEASING §3, Intel app: the same identity, `signature ok`,
      `spctl` rejects, version `0.2.0` twice; `lipo -archs` `x86_64`;
      `Frameworks/libchromaprint.1.dylib` (x86_64, 1.6.2) and its
      `Resources/` symlink, nothing else. Smoke test under `arch
      -x86_64` exit 0: all nine pass, `frozen`, build `v0.2.0`,
      architecture "Intel build on Apple silicon (Rosetta). Download
      Seeker.dmg, the Apple silicon build, from …",
      `chromaprint_available` true, analysis cold in 35.8 s, warm in
      0.05 s.
- [x] **The bundled libchromaprint, proved.** This Mac has an x86_64
      copy in `/usr/local/lib` (HISTORY §266), so the run above proves
      nothing about the bundle. RELEASING says to move that copy aside;
      it is root-owned, so instead the smoke test ran again under
      `sandbox-exec` with a profile denying reads of
      `/usr/local/lib/libchromaprint*`, `/opt/homebrew/lib/libchromaprint*`
      and Homebrew's Cellar copy (no sudo, nothing on disk changed). It
      passed with `chromaprint_available` true. The same profile made
      the x86_64 Python refuse both system copies, by path and by bare
      name, and still load `.chromaprint/lib`'s (observed). `lsof`
      polled through that run listed no libchromaprint for the Rosetta
      process (observed), so `lsof` cannot show which copy a Rosetta
      app loaded.
- [x] Each image mounted read-only with `hdiutil attach -nobrowse`:
      `Seeker.dmg` holds an arm64 app with no libchromaprint,
      `Seeker-Intel.dmg` an x86_64 app with `libchromaprint.1.dylib`,
      both `codesign --verify --deep --strict` ok. `shasum -a 256 -c`
      OK beside the images in `dist/`, and again on the copies in
      `.git/autodev/release/v0.2.0/`. The release notes' two
      placeholders hold these checksum lines.
- [x] **A build-host finding, not a defect in the images.** The first
      Apple silicon build failed its own bundle check: "dist/Seeker.app
      failed the arm64 check: Contents/Frameworks/libchromaprint.dylib
      has x86_64, not arm64". PyInstaller's ctypes scan resolves
      `ctypes.util.find_library("chromaprint")` in
      `audio/fingerprint.py` while building, and on this Mac that finds
      `/usr/local/lib`'s x86_64 copy. The check stopped the build before
      the image. Both builds then ran under `sandbox-exec` with a profile
      denying reads of `/usr/local/lib/libchromaprint*` only. Under it
      `find_library` returns None, so each bundle holds only what the
      spec stages: nothing for Apple silicon, `libchromaprint.1.dylib`
      for Intel. Until the spec or RELEASING handles it, a Mac with that
      copy cannot build the Apple silicon app as RELEASING §2 is
      written.

Code did not open either app: Help's two lines (RELEASING §3's last
step) are below, in the test account, where launching touches no real
data.

## Kris, in the test account on the M4 Pro

**No slskd bring-up here.** At the wizard's SoulSeek step choose "Set
up later": the container name `slskd` is global to this Mac's Docker,
so a bring-up from this account recreates your real container.

**Install into `~/Applications`, not `/Applications`.** `/Applications`
is shared by every account, so dragging there replaces your own
`Seeker.app`. Create `~/Applications` in the test account if it is
missing.

**Getting a quarantined copy.** Gatekeeper's flow needs the quarantine
flag a browser sets on a download, and the images in `.git/autodev/`
carry none (built locally; `xattr` lists no `com.apple.quarantine`).
Serve them on this Mac and download them in a browser:

1. In your own account: `mkdir -p /Users/Shared/Seeker-0.2.0`, then
   `cp /Users/sinthesis/PycharmProjects/Seeker/.git/autodev/release/v0.2.0/Seeker*.dmg* /Users/Shared/Seeker-0.2.0/`.
2. In the test account's Terminal: `cd /Users/Shared/Seeker-0.2.0 &&
   python3 -m http.server 8765 --bind 127.0.0.1` (`/usr/bin/python3`;
   the Command Line Tools are installed system-wide). Leave it running.
3. In Safari, in the test account, open
   `http://127.0.0.1:8765/Seeker-Intel.dmg`, then
   `http://127.0.0.1:8765/Seeker-Intel.dmg.sha256`; the same for
   `Seeker.dmg` and its `.sha256` (the comparison app). Ctrl-C stops
   the server.
4. `cd ~/Downloads && xattr -p com.apple.quarantine Seeker-Intel.dmg`
   prints a line naming Safari. UNVERIFIED that Safari flags a download
   from `127.0.0.1` as it does one from GitHub: if this prints "No such
   xattr", the Gatekeeper box below tests nothing; record that under
   Results and leave the box for the post-release download (S10).
5. `shasum -a 256 -c Seeker-Intel.dmg.sha256` and `shasum -a 256 -c
   Seeker.dmg.sha256`, both in `~/Downloads`: each prints `OK`.

**The Intel app** (`Seeker-Intel.dmg`):

- [ ] Open the image, read `Read Me First.txt`, drag `Seeker.app` to
      `~/Applications`. First launch through Privacy & Security → "Open
      Anyway". Are its steps true on macOS 26?
- [ ] Help → Build reads the Intel line above; Help → Architecture
      begins "Intel build on Apple silicon (Rosetta)" and points at
      `Seeker.dmg`.
- [ ] The wizard with a test Spotify account (the Spotify app's owner
      needs Premium, Spotify's Development Mode rule); SoulSeek → "Set
      up later".
- [ ] Sync, then scan a test folder: put a few MP3 or FLAC files that
      match the test playlist in `/Users/Shared/SeekerTest` (readable
      from your own account too), including one file twice under two
      names for Duplicates. An M4A or AAC file needs ffmpeg; leave
      those out.
- [ ] Library → Tag options → "Analyze audio (BPM/Key)" → "Tag
      selected" on the matched files. Note each file's BPM and key:
      from your own account, `uv run mutagen-inspect
      /Users/Shared/SeekerTest/<file>` in the repository.
- [ ] Duplicates: Compute fingerprints, then "Find duplicates" finds the
      pair. The app searches its own bundle for libchromaprint first,
      and Code proved the bundled copy loads with every other copy
      hidden; `/usr/local/lib`'s x86_64 copy is still visible to this
      account, and nothing short of moving it aside (sudo) shows which
      copy loaded here. Optional: `sudo mkdir /usr/local/lib/aside &&
      sudo mv /usr/local/lib/libchromaprint* /usr/local/lib/aside/`
      before the run, and move them back after.
- [ ] The tray: the icon and its menu; close the window and bring it
      back with the menu's "Open Seeker".
- [ ] Quit with a task running (tray → Quit during Compute fingerprints
      or a scan): the app exits within seconds, no beach ball.

**The comparison** (`Seeker.dmg`, the Apple silicon app):

- [ ] Quit the Intel app. Open `Seeker.dmg` and run `Seeker.app` from
      the mounted image (no install; the two share the test account's
      one Seeker folder, so run one at a time). Help → Build reads the
      Apple silicon line, Architecture "Apple silicon".
- [ ] Tag the same files with "Analyze audio (BPM/Key)" and "Re-tag
      already tagged files" ticked (without it, a file with a BPM is
      skipped). The BPM and key match the Intel app's for each file.

Afterwards: quit both, eject the images, delete
`/Users/Shared/Seeker-0.2.0` and `/Users/Shared/SeekerTest`.

## Kris, on a real Intel Mac, if you find one

The same list, with the Intel image installed into `/Applications`
there, plus: an ffmpeg of its own for an M4A or AAC file (Homebrew
builds no Intel bottles, so it is the Mac owner's own build), and a
slskd bring-up with a test Soulseek account (one login per username:
yours would kick your Mac's session off). Help → Architecture reads
"Intel".

## Results

Record failures here with what you saw; each becomes a fix row.

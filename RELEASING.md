# Releasing Seeker

How a macOS release is cut, checked, published and, if need be,
withdrawn. `X.Y.Z` stands for the version throughout. Every outward
step (pushing a tag, creating or deleting a release) is the
maintainer's to approve; the exact commands are shown first.

A release has two images, one for each kind of Mac, each with its
SHA-256 beside it: `Seeker.dmg` (Apple silicon) and `Seeker-Intel.dmg`
(Intel), four files in all. Both are built on the maintainer's Mac from
the same commit, the Intel one in an x86_64 environment under Rosetta 2
(`docs/packaging.md` → "The Intel app").

## 1. Prepare

1. On `main`, with a clean tree (`git status` shows nothing to commit)
   and CI green on `HEAD`: `check`, `check-intel` and `audit` in
   `ci.yml`, and the latest `build.yml` run (both apps built and
   smoke-tested on their runners) on a commit that has the same
   `pyproject.toml`, `uv.lock` and `packaging/` as `HEAD`.
2. `pyproject.toml`'s `version` is `X.Y.Z`; `uv lock` has run and
   `uv.lock` is committed with it. The bundle's version comes from
   `pyproject.toml` (`packaging/bundle_info.py`); there is no second
   copy to edit.
3. `CHANGELOG.md`: move the release's entries from `[Unreleased]` into
   `## [X.Y.Z] - YYYY-MM-DD`, with today's date, and add its compare
   link at the bottom. Commit.
4. The three checks pass locally:

   ```
   uv run pytest -q
   uv run mypy --strict src/
   uv run ruff check src tests tools
   ```

5. The Intel build's two prerequisites are in place:
   `.venv-x86_64` (`uv sync --locked` for the x86_64 interpreter,
   `docs/packaging.md` → "The Intel app") and the Intel libchromaprint,
   which the build copies into the app and fails without. Seeker builds
   it from a pinned, checksummed source (chromaprint 1.6.2; Homebrew
   builds no Intel bottles), into the checkout, with no `sudo` and no
   Intel Homebrew:

   ```
   packaging/build_chromaprint.sh "$PWD/build/chromaprint-x86_64"
   ```

   The script fails if the result links anything outside macOS. On an
   Intel Mac it needs no argument: it installs into `/usr/local/lib`,
   where the build looks by default.

## 2. Tag locally, then build both

Tag first, so `git describe` inside each bundle reads `vX.Y.Z` rather
than a bare SHA. Nothing leaves the machine yet.

```
git tag -a vX.Y.Z -m "Seeker X.Y.Z"
uv run python packaging/build_dmg.py                # Apple silicon
```

This writes `dist/Seeker.app` and `dist/Seeker.dmg`. **Check this app
(step 3) before building the other:** both builds write
`dist/Seeker.app`, so the Intel build replaces it (the images have
different names and both stay).

```
SEEKER_CHROMAPRINT_DIR="$PWD/build/chromaprint-x86_64/lib" \
    .venv-x86_64/bin/python packaging/build_dmg.py   # Intel, under Rosetta
```

The variable names the folder the build stages libchromaprint from
(default `/usr/local/lib`: leave it out on an Intel Mac that installed
there). This writes `dist/Seeker.app` again, now the Intel app, and
`dist/Seeker-Intel.dmg`; check it too. Each build ends by checking its
bundle: every Mach-O carries the build's architecture, the main
executable is thin, and no binary needs a newer macOS than 15.0. A
failure stops the build before the image. A build deletes its generated
build-identity module afterwards, so `git status` stays clean
(`docs/packaging.md` → "Build identity").

## 3. Verify each build

Once per app, right after its build, with `ARCH` set to `arm64` for the
Apple silicon app and `x86_64` for the Intel one:

```
ARCH=arm64          # x86_64 for the Intel app
codesign -dvvv dist/Seeker.app 2>&1 | grep -E "Identifier|Signature"
codesign --verify --deep --strict dist/Seeker.app && echo signature ok
spctl -a -vv dist/Seeker.app
plutil -p dist/Seeker.app/Contents/Info.plist | grep -E "Version|Identifier"
lipo -archs dist/Seeker.app/Contents/MacOS/Seeker
arch -$ARCH dist/Seeker.app/Contents/MacOS/Seeker --smoke-test "$PWD/dist/smoke-$ARCH.json"; echo exit $?
git status --short
```

Expected:
- `Identifier=io.github.kristiyanddimitrov.seeker` and
  `Signature=adhoc`: ad-hoc signed, not notarized.
- `signature ok`.
- `spctl` **rejects** the app. That is correct for a build that isn't
  notarized; acceptance would mean something unexpected signed it.
- `CFBundleShortVersionString` and `CFBundleVersion` are `X.Y.Z`.
- `lipo -archs` prints exactly `ARCH`: the executable is thin.
- The smoke test exits 0 (`exit 0`). In its report, `architecture` is
  "Apple silicon" for the Apple silicon app and "Intel build on Apple
  silicon (Rosetta)" for the Intel app; `chromaprint_available` is true
  (for the Apple silicon app that needs Homebrew's chromaprint on this
  Mac, and says nothing about the bundle, which holds none). The smoke
  test touches no settings, database or library, so it is safe on any
  Mac. The first cold analysis takes tens of seconds under Rosetta
  (37 s measured, `docs/packaging.md`).
- **For the Intel app, `chromaprint_available: true` proves the bundled
  library only if no other x86_64 copy can load on this Mac.**
  `audio/fingerprint.py` searches the bundle, then `/opt/homebrew/lib`,
  then `/usr/local/lib`. On an Apple silicon Mac with no Intel Homebrew
  and the library built into `build/` as in step 1, there is none
  (Homebrew's arm64 copy cannot load into an x86_64 process), so `true`
  proves it. If `/usr/local/lib/libchromaprint*` exists (Intel Homebrew,
  or the script run with its default prefix), move it aside for the run
  and put it back after, as `build.yml` deletes it before its smoke test.
  `find dist/Seeker.app -name 'libchromaprint*'` should list one file for
  the Intel app and none for the Apple silicon one. This proves the
  library loads in an x86_64 process on this Mac, from the app in
  `dist/`. It does not prove a download's first launch after Gatekeeper
  (step 5), or a Mac that has never had the library.
- No modified files.

Then open each app from `dist/` and check Help → Build: it reads
`vX.Y.Z — built <today>` and names the architecture. Launching it reads
and migrates that Mac's real Seeker data, so do it only on a machine
where that is intended, and quit one app before opening the other.

Write both checksums next to the images:

```
cd dist
shasum -a 256 Seeker.dmg > Seeker.dmg.sha256
shasum -a 256 Seeker-Intel.dmg > Seeker-Intel.dmg.sha256
shasum -a 256 -c Seeker.dmg.sha256 && shasum -a 256 -c Seeker-Intel.dmg.sha256
cd ..
```

Each checksum file names its image by its bare name, so `-c` runs
beside them: from the repository root it reports `FAILED open or read`.

If any check fails, delete the local tag (`git tag -d vX.Y.Z`), fix,
and start again from step 1.

## 4. Publish

Release notes: the version's `CHANGELOG.md` section; which image is
for which Mac (`Seeker.dmg` for Apple silicon, where About This Mac
shows a Chip; `Seeker-Intel.dmg` for Intel, where it shows a Processor;
both need macOS 15 or later); the SHA-256 from each `.sha256` file, with
its image's name; the Intel app's bundled library, "libchromaprint 1.6.2"
(`grep '^VERSION=' packaging/build_chromaprint.sh`; the version README →
License points a recipient to for its source); the first-launch steps from `packaging/Read Me
First.txt`; and README → License's second paragraph, with "the
release's tag" naming this one (`vX.Y.Z`). Save them to a file outside
the repository.

```
git push origin vX.Y.Z
gh release create vX.Y.Z dist/Seeker.dmg dist/Seeker.dmg.sha256 \
    dist/Seeker-Intel.dmg dist/Seeker-Intel.dmg.sha256 \
    --title "Seeker X.Y.Z" --notes-file <notes file> --verify-tag
```

`--verify-tag` refuses to create the release if the tag isn't on
GitHub, so the release can't silently tag a different commit.

## 5. Verify the release

1. `gh release view vX.Y.Z` lists four assets: `Seeker.dmg`,
   `Seeker.dmg.sha256`, `Seeker-Intel.dmg` and `Seeker-Intel.dmg.sha256`.
2. Download each `.dmg` in a browser (so it is quarantined), check it
   with `shasum -a 256 -c`, install the one that matches the Mac in
   front of you, and follow `Read Me First.txt` to the first launch.
   The other image runs only where it can: the Intel app under Rosetta
   on Apple silicon (and Help → Build says so); the Apple silicon app
   not at all on an Intel Mac.
3. In each app that ran, Help → "Check for updates…" says Seeker is up
   to date. An older build says an update is available and links to
   this release's page (the link is the release's page, not an asset,
   so a second image needs no change there).

## 6. Roll back

- **The release is wrong, the tag is right** (bad notes, a missing
  asset, one image of the two wrong): edit it with `gh release edit
  vX.Y.Z` or `gh release upload vX.Y.Z <file> --clobber`, a file at a
  time. Nothing else changes.
- **The build is wrong:** withdraw the release and keep the tag, so
  the record of what was published stays:

  ```
  gh release delete vX.Y.Z --yes
  ```

  Then fix and release `X.Y.(Z+1)`. Never move a published tag: anyone
  who downloaded `vX.Y.Z` must be able to find its exact source.
  Once the release is gone, GitHub's latest release is the previous
  one again, which is what every installed copy's update check sees.
- **The tag itself is wrong** (it points at the wrong commit and
  nobody can have used it yet): delete it on both sides, then re-tag.

  ```
  gh release delete vX.Y.Z --yes
  git push --delete origin vX.Y.Z
  git tag -d vX.Y.Z
  ```

## 7. When Intel ends

The Intel image lasts as long as it can be built and tested. The last
release that still builds on Intel and passes `check-intel` (or, once
GitHub's last Intel runner retires in fall 2027, the suite under
Rosetta) is Intel's final version. For that release:

- its notes and README → Install say "the final Intel version";
- every later release ships `Seeker.dmg` alone: steps 2 to 5 lose the
  Intel build, the Intel checksum and the third and fourth asset;
- the Intel row in `docs/packaging.md`'s platform table says which
  version was last.

What sets the date, from `docs/phase-02/README.md` → "The clock":
numba and llvmlite publish no Intel macOS wheels after 0.62.1 and
0.45.1, so Intel's pins are permanent; macOS 26 is the last release
for Intel Macs; Rosetta's full support continues through macOS 27 and
shrinks after; Homebrew, the source of the Intel app's libchromaprint,
stopped building Intel bottles in September 2026 and ends Intel
support in or after September 2027
([Homebrew](https://docs.brew.sh/Support-Tiers), read 2026-11-03).

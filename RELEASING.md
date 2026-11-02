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
   packaging/build_chromaprint.sh "$PWD/.chromaprint"
   ```

   The library lands in `.chromaprint/lib` (gitignored, so the tree stays
   clean), not under `build/`: `build_dmg.py` runs PyInstaller with
   `--clean`, which empties `build/` first. The script fails if the
   result links anything outside macOS. On an Intel Mac it needs no
   argument: it installs into `/usr/local/lib`, where the build looks by
   default.

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
SEEKER_CHROMAPRINT_DIR="$PWD/.chromaprint/lib" \
    .venv-x86_64/bin/python packaging/build_dmg.py   # Intel, under Rosetta
```

The variable names the folder the build stages libchromaprint from
(default `/usr/local/lib`: leave it out on an Intel Mac that installed
there). Set it on this command itself, as an absolute path: the spec
reads it when it runs, and a relative one resolves against the
repository root. This writes `dist/Seeker.app` again, now the Intel app, and
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
  "Apple silicon" for the Apple silicon app and, for the Intel app, text
  that begins "Intel build on Apple silicon (Rosetta)" (a sentence
  pointing at `Seeker.dmg` follows) or, on an Intel Mac, "Intel".
  `chromaprint_available` is true; for the Apple silicon app that needs
  Homebrew's chromaprint on this Mac and says nothing about the bundle,
  which holds none. The smoke test touches no settings, database or
  library, so it is safe on any Mac. The first cold analysis takes tens
  of seconds under Rosetta (37 s measured, `docs/packaging.md`).
- **For the Intel app, `chromaprint_available: true` proves the bundled
  library only if no other x86_64 copy can load on this Mac.**
  `audio/fingerprint.py` searches the bundle, then `/opt/homebrew/lib`,
  then `/usr/local/lib`. On an Apple silicon Mac with no Intel Homebrew
  and the library built into `.chromaprint/` as in step 1, there is none
  (Homebrew's arm64 copy cannot load into an x86_64 process), so `true`
  proves it. If `/usr/local/lib/libchromaprint*` exists (Intel Homebrew,
  or the script run with its default prefix), move it aside for the run
  and put it back after, as `build.yml` deletes it before its smoke
  test. `find dist/Seeker.app -name 'libchromaprint*'` lists
  `libchromaprint.1.dylib` for the Intel app and nothing for the Apple
  silicon one (the spec stages none there). Together they show the
  library loads in an x86_64 process on this Mac, from the app in
  `dist/`. They do not show a download's first launch after Gatekeeper
  (step 5), or a Mac that has never had the library.
- No modified files.

Then, before another build replaces `dist/Seeker.app`, open this app
(`open dist/Seeker.app`) and check Help: the Build line reads
`vX.Y.Z — built <today>`, and the Architecture line below it names the
build. It reads "Apple silicon" for the Apple silicon app, and for the
Intel app "Intel" on an Intel Mac or, under Rosetta, text that begins
"Intel build on Apple silicon (Rosetta)". Launching an app reads and
migrates that Mac's real Seeker data, so do it only on a machine where
that is intended, and quit it before the next build. After both builds,
`dist/Seeker.app` is whichever built last: open the other from its
mounted image instead.

After both apps are checked, write both checksums next to the images:

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
release's tag" naming this one (`vX.Y.Z`); after Intel's end, the
warning in step 7. Save them to a file outside the repository.

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
   The other image runs only where it can: the Intel app should run
   under Rosetta on Apple silicon (its headless smoke test did; Help's
   Architecture line then begins "Intel build on Apple silicon
   (Rosetta)"); the Apple silicon app, which is arm64 code, cannot run
   on an Intel Mac.
3. In each app that ran, Help → "Check for updates…" says Seeker is up
   to date. An older build says an update is available and links to
   this release's page (the link is the release's page, not an asset,
   so a second image needs no change there).

## 6. Roll back

- **The release is wrong, the tag is right** (bad notes, a missing
  asset, one image of the two wrong): edit it with `gh release edit
  vX.Y.Z` or `gh release upload vX.Y.Z <file> --clobber`, a file at a
  time. Nothing else changes, with one exception: a replaced image is
  a new file with its own SHA-256. Rewrite that image's `.sha256` (step 3), upload the
  image and its `.sha256` together with `--clobber`, put the new
  checksum in the release notes (`gh release edit vX.Y.Z --notes-file
  <notes file>`, the other image's line untouched) and repeat step 5.2
  for that image.
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
- the notes of every later release start with a warning, because
  Seeker's update check cannot know about images: it compares the latest
  release's tag with the installed version and nothing else
  (`update_check.py`), so an Intel Mac on the final version is told that
  an update is available, from Help or at startup when Settings → General
  → Updates is on, and linked to a release page whose only download,
  `Seeker.dmg`, does not run on it. The warning says Intel Macs stay on
  version X.Y.Z, and that the update notice does not apply to them. Only
  a check shipped inside the final Intel version could stay quiet (by
  reading the release's assets: not built), so that is decided before
  the final Intel version is built, not after;
- every later release ships `Seeker.dmg` alone: steps 2 to 5 lose the
  Intel build, the Intel checksum and the third and fourth asset;
- the Intel row in `docs/packaging.md`'s platform table says which
  version was last.

What sets the date, from `docs/phase-02/README.md` → "The clock":
numba and llvmlite publish no Intel macOS wheels after 0.62.1 and
0.45.1, so Intel's pins are permanent; macOS 26 is the last release
for Intel Macs; Rosetta's full support continues through macOS 27 and
shrinks after; Homebrew stopped building Intel bottles in September
2026 and ends Intel support in or after September 2027
([Homebrew](https://docs.brew.sh/Support-Tiers), read 2026-11-03). That
no longer touches the Intel app's libchromaprint, which Seeker builds
from source, only ffmpeg, the decode fallback a user installs from
Homebrew.

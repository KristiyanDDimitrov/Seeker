# Releasing Seeker

How a macOS release is cut, checked, published and, if need be,
withdrawn. `X.Y.Z` stands for the version throughout. Every outward
step (pushing a tag, creating or deleting a release) is the
maintainer's to approve; the exact commands are shown first.

## 1. Prepare

1. On `main`, with a clean tree (`git status` shows nothing to commit)
   and CI green on `HEAD`.
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

## 2. Tag locally, then build

Tag first, so `git describe` inside the bundle reads `vX.Y.Z` rather
than a bare SHA. Nothing leaves the machine yet.

```
git tag -a vX.Y.Z -m "Seeker X.Y.Z"
uv run python packaging/build_dmg.py
```

This writes `dist/Seeker.app` and `dist/Seeker.dmg`. The build deletes
its generated build-identity module afterwards, so `git status` stays
clean (`docs/packaging.md` → "Build identity").

## 3. Verify the build

```
codesign -dvvv dist/Seeker.app 2>&1 | grep -E "Identifier|Signature"
codesign --verify --deep --strict dist/Seeker.app && echo signature ok
spctl -a -vv dist/Seeker.app
plutil -p dist/Seeker.app/Contents/Info.plist | grep -E "Version|Identifier"
git status --short
```

Expected:
- `Identifier=io.github.kristiyanddimitrov.seeker` and
  `Signature=adhoc`: ad-hoc signed, not notarized.
- `signature ok`.
- `spctl` **rejects** the app. That is correct for a build that isn't
  notarized; acceptance would mean something unexpected signed it.
- `CFBundleShortVersionString` and `CFBundleVersion` are `X.Y.Z`.
- No modified files.

Then open the app from `dist/` and check Help → Build: it reads
`vX.Y.Z — built <today>`. Launching it reads and migrates that Mac's
real Seeker data, so do it only on a machine where that is intended.

Write the checksum next to the disk image:

```
cd dist && shasum -a 256 Seeker.dmg > Seeker.dmg.sha256 && cd ..
shasum -a 256 -c dist/Seeker.dmg.sha256
```

If any check fails, delete the local tag (`git tag -d vX.Y.Z`), fix,
and start again from step 1.

## 4. Publish

Release notes: the version's `CHANGELOG.md` section, then the SHA-256
from `dist/Seeker.dmg.sha256`, the first-launch steps from
`packaging/Read Me First.txt`, and README → License's second
paragraph, with "the release's tag" naming this one (`vX.Y.Z`). Save
them to a file outside the repository.

```
git push origin vX.Y.Z
gh release create vX.Y.Z dist/Seeker.dmg dist/Seeker.dmg.sha256 \
    --title "Seeker X.Y.Z" --notes-file <notes file> --verify-tag
```

`--verify-tag` refuses to create the release if the tag isn't on
GitHub, so the release can't silently tag a different commit.

## 5. Verify the release

1. `gh release view vX.Y.Z` lists `Seeker.dmg` and
   `Seeker.dmg.sha256`.
2. Download the `.dmg` in a browser (so it is quarantined), check it
   with `shasum -a 256 -c`, install it, and follow `Read Me First.txt`
   to the first launch.
3. In that app, Help → "Check for updates…" says Seeker is up to date.
   An older build says an update is available and links to this
   release's page.

## 6. Roll back

- **The release is wrong, the tag is right** (bad notes, a missing
  asset): edit it with `gh release edit vX.Y.Z` or `gh release upload
  vX.Y.Z <file> --clobber`. Nothing else changes.
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

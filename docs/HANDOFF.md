# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S16's close-out (HISTORY §214). Tree clean apart from the
  untracked `Claude outputs/`. `dist/Seeker.app` and `dist/Seeker.dmg`
  are a fresh build of `28d5ecd` (gitignored).
- **Local (Cocoa):** pytest `2248 passed, 1 skipped`, 0 failed (+8
  tests); only the stress test skipped (CI skips 29). `mypy --strict
  src/` clean, 144 files; `ruff check src tests tools` 0; `uvx radon
  cc -n D -s src/seeker` nothing.
- **CI: green on the re-run.** `5fd8d2c`'s run `38063506444`:
  attempt 1 failed (`check`: 1 failed, 2219 passed, 29 skipped; §6
  below), attempt 2 green, `check` and `audit` both.

## 2. Where we are

**S16 is done except S-04, now its own row, S16b** (SESSION-PLAN).
**Next: S16b, an [ASK] row.** Kris approves the GPL wording first;
the bundled licence texts may be built before the yes. Then S17.

## 3. Session report (S16)

Evidence for each is in HISTORY §214.
- `760038e` §39.1: the build identity is "dev" from source (the
  generated module is imported only when frozen), `build_dmg.py`
  deletes it in a `finally`, the wheel excludes it.
- `4a28212` §39.2: `packaging/bundle_info.py` builds the Info.plist:
  `pyproject.toml`'s version, `LICENSE`'s copyright, Music,
  minimum macOS 15.0 (PySide6's binaries declare `minos` 15.0).
- `604f07a`: §39.1's import made type-clean without the generated
  module (it failed mypy once the build deleted the file).
- `28d5ecd` §39.3: bundle ID `io.github.kristiyanddimitrov.seeker`.
  A real build checked §39.1–§39.3 (plist, codesign, the PYZ).
- `2647f41` §39.4: Open Anyway replaces Control-click → Open.
- `5442582` §39.5: `CHANGELOG.md`, `RELEASING.md`.

## 4. Key context for S16b

- **What to bundle (measured, §214):** mutagen's `COPYING`; soxr's
  four licence files; scipy's `METADATA` (libgfortran's GPL-3.0 with
  the GCC exception); PySide6, its addons and essentials, and
  shiboken6 ship **no** text, so vendor LGPL-3.0 and GPL-3.0 from
  gnu.org into `packaging/licenses/`. A sweep test over the runtime
  closure keeps a new GPL dependency from shipping without its text.
- **The wording to approve:** AUDIT S-04's fix. The macOS binary is
  distributed under GPL-2.0-or-later as a combined work (mutagen),
  and its source is at the tagged commit. It goes in the README, the
  release notes (RELEASING.md step 4 already names it) and About.
- **Kris's slskd container no longer exists;** S17 needs a bring-up
  first (Settings → Connections, by Kris).
- **Carried:** Sharing's 20 s per-row rebuild; R11's carried list
  (`git show 1b415a4:docs/HANDOFF.md` §9). Run the full suite in the
  background (~5 min). Never touch slskd or real data, and never
  launch the built app (it migrates the real data).

## 5. Decisions made

- **Tag locally, then build** (RELEASING.md): the bundle's `git
  describe` then reads the version. Push only after verification.
- **The minimum macOS is the highest `minos` in the bundle,** not a
  wheel tag; re-measure after a PySide6, scipy or Python upgrade.
- **S-04 split out:** larger than estimated (four licences, two texts
  absent), and its wording waits on Kris.

## 6. Blockers

- **A new CI flake, first:**
  `test_library_track_list_keeps_the_latest_load_when_an_older_one_lands_last`
  (`tests/pages/test_library_page.py:1154`, §213's own test) timed
  out once on CI. The lead is in HISTORY §214 → "CI": its fake
  answers exactly two loads. Make it fail deterministically on HEAD,
  then fix the test (or the page, if a third load is a real bug)
  before S16b.
- S16b's wording waits on Kris.

## 7. Files in progress

None uncommitted.

## 8. Waiting on Kris

- **New (S16):** approve or edit S-04's wording (§4 above), so S16b
  can finish; after S17's build, turn "Start Seeker at login" on
  again once (the bundle ID changed).
- **From S15 part three:** veto, if wanted, "2 of its 8 tracks are
  in your library" in Library's header.
- **From S15 part two:** veto, if wanted, "Available"/"Not found"
  and the faint ring for an unplugged drive.
- **From S15 part one:** the tooltip and the Runner-up wording ("scored
  64.0, from peer").
- **From S14:** turn on Settings → General → Updates and relaunch.
- **From S13 and §213:** bring slskd up again (its container is
  gone), then the first real cleanup, yours to click: Downloads →
  "Clean up leftover files…".
- **From S10–S12b:** the decisions in HISTORY §202–§207 and BRIEF
  §12b's "Code's calls"; the first live Cancel, at the keyboard; the
  real `tracks.last_searched_at` migration runs on the next launch.
- **Still open:** the live checks of
  §193–§196; the S5 wording veto; the wordmark's brows (`9ff777b`);
  BRIEF §17; S8's visible peer-filename change; `git show
  1b415a4:docs/HANDOFF.md` §8; the three nested locations in the real
  DB.

## 9. Open questions

- Should Sharing hide or disable "Add to share" for a location whose
  folder isn't there?
- Should Search list files a playlist download would take (scored)
  above unscored ones, or say what "—" means?
- Should "Queued as backup" rows count in the Downloads header's
  "queued (no estimate)"?
- Should a superseded row's transfer be cancelled in slskd, so its
  file never becomes a leftover?
- Should the cleanup also offer slskd's own "remove finished
  transfers"?
- How long may a settled file sit in a remote queue before Seeker
  gives up or falls back?
- Should an activated backup's row say it is a backup? Should a
  downloading row get Cancel too? Should Downloads get "Retry all"?
- Should the sweep skip a track whose needs-review candidate is still
  waiting on a person? Should a GUI sweep and a cron sweep guard
  against running at once? (UNVERIFIED how they interleave.)
- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED.) Does Dependabot bump a `tag@digest` pair?
- Should the callback handler get a socket timeout?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**No round is open:** round 12 (and round 11 with it) closed with the
v0.1.0 release; its plan is `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **Released: v0.1.0** (2026-10-14),
  https://github.com/KristiyanDDimitrov/Seeker/releases/tag/v0.1.0.
  Tag `v0.1.0` on `35f6ba7`; `Seeker.dmg` 111,788,167 bytes, SHA-256
  `5691a25609cc9d054cd95f1f1ddfab44f362ac33fa4c9d7784ee312dab2a2943`.
- **HEAD:** S18's close-out (HISTORY §245). Tree clean.
- **Local (Cocoa):** pytest `2418 passed, 1 skipped`, 0 failed (the
  X9 Pro mounted; CI skips 29). `mypy --strict src/` clean, 146
  files; `ruff check src tests tools` 0; radon D 0.
- **CI:** run `38570802975` green on `35f6ba7`, the release commit
  (`2390 passed, 29 skipped`, coverage 94.68 %); the close-out's run
  is recorded in its follow-up commit.

## 2. Where we are

**Rounds 11 and 12 are complete.** No round 13 is planned. A new
round starts with a new BRIEF and SESSION-PLAN under `docs/rounds/`.

## 3. Session report (S18, with §243–§244)

Evidence in HISTORY §243–§245.
- Committed the stress test's `docker inspect` opt-in (§243).
- The ten failing X9 Pro tests now read files that are still on the
  drive: Lux moved, and §38's pairs were replaced by pairs measured on
  scratch copies (§244).
- Dated `[0.1.0]` in the changelog and gave Confirm all a line.
  Recorded Kris's acceptance, with the unticked boxes waived.
- CI broke on Python 3.15.0, which the runner now offers and numba
  refuses. `.python-version` pins 3.13 (`35f6ba7`).
- RELEASING.md steps 1–5: tag, build, verify, checksum, the notes.
  Kris approved, then push and release. Code verified the release:
  the downloaded assets pass `shasum -c`, and the update check
  returns `UP_TO_DATE`.
- Skills: none loaded; RELEASING.md is the runbook, as in §222/§242.

## 4. Key context for the next session

- **A release:** RELEASING.md end to end; §245 is the worked example.
  Bump `pyproject.toml`'s version and `uv lock`, then move
  `[Unreleased]` in the changelog.
- **Never move a published tag** (RELEASING.md → Roll back): a bad
  build is withdrawn and released as `0.1.1`.
- **`.python-version` pins 3.13.** Moving to 3.14/3.15 waits for numba
  (and librosa) to support it. A bump is a reviewed commit.
- Never touch slskd or real data, and never launch the built app.

## 5. Decisions made

- **Release with the acceptance partly waived** (Kris, 2026-10-14):
  the important checks were done, and the rest stay open as
  post-release checks, not passes.
- **The notes are the changelog section plus RELEASING.md step 4's
  parts, unwrapped** for GitHub's line breaks.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

- RELEASING.md step 5.2–5.3: download the DMG in a browser, install
  it, and Help → "Check for updates…" says up to date.
- The waived ACCEPTANCE.md boxes, as post-release checks: the fresh
  account, the first live Retry/Cancel/Clean up, start at login again,
  the sweep, window paths, the X9 Pro Fix… (CLAUDE.md → Open issues),
  and S17d on the packaged build.
- Item 125 is narrowed, not closed (§245 → Exit criteria).

## 9. Open questions

- S17l (§238 → "Not done"): when a playlist download's or sweep's
  settled enqueue stays busy, should the pick be recorded for a later
  poll rather than failing the track after its search? Should a busy
  slskd end Review's Confirm all, as an outage does?

- S17m (§239 → "Not done"): Resolve all still opens its dialog
  when every group is on "Keep all" (it says 0 groups; its button
  stays disabled). Return before it instead?
- S17o (§241): in dark mode the system's question icon on the quit
  confirmation (shell and wizard alike) is barely visible. Leave it,
  or draw our own?

- "Match tracks" stays enabled while a scan runs, so a match can start
  beside `scan_and_match`'s own (§223). Disable it during a scan?
- Should a CLI command start slskd (`restart_slskd` has none)? Not in
  the BRIEF; left out.
- Should Sharing hide or disable "Add to share" for a location whose
  folder isn't there? Should `start_slskd` itself refuse a share not
  on disk (only the form guards it; the wizard passes a location it
  has just registered)?
- Should the wizard's share checkbox start ticked? (Unticked, to
  match Settings; Kris's call.)
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

- `measure_signal()` (clipping, loudness) has no caller now. Show it
  on the Duplicates page, on demand, or delete it with pyloudnorm?
- Should a template bump (a new slskd digest) reach an existing
  install's per-user Compose copy? It is never re-seeded, so Kris's
  copy still names the unpinned tag (§222).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

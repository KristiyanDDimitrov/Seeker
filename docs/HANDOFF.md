# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S16b's close-out (HISTORY §215). Tree clean apart from the
  untracked `Claude outputs/`. `dist/Seeker.app` and `dist/Seeker.dmg`
  are a build of `a227ed0` plus S16b's uncommitted licence work
  (identical to `e45eed4`; gitignored).
- **Local (Cocoa):** pytest `2256 passed, 1 skipped`, 0 failed (+8
  tests); only the stress test skipped (CI skips 29). `mypy --strict
  src/` clean, 144 files; `ruff check src tests tools` 0; `uvx radon
  cc -n D -s src/seeker` nothing.
- **CI:** recorded after the push (see the next commit).

## 2. Where we are

**S16b is done** (SESSION-PLAN): the CI flake fixed first, every
licence text in the bundle, and the GPL-3.0 statement Kris approved.
**Next: S17, release-candidate acceptance (Kris and Code).**

## 3. Session report (S16b)

Evidence for each is in HISTORY §215.
- `a227ed0`: the Library load-recency flake. Two loads' workers took
  the fake's answers in reverse (CI's log: no Library
  `StopIteration`). Reproduced with a 0.3 s delay; the test now
  answers by load and stops `poll_timer`. No page change.
- `e45eed4` S-04: `bundle_info.license_datas()` bundles all 41
  runtime distributions' texts, Seeker's and Python's, at
  `Contents/Resources/licenses/<name>/`; `packaging/licenses/`
  vendors LGPL-3.0, GPL-3.0 (PySide6, shiboken6) and PyObjC's MIT
  text (pyobjc-core). It raises (build and test) for a dependency
  with no text. Checked on a real build: 71 files, byte-identical.
- `1a1f867` S-04 wording: README, About and RELEASING.md say the app
  ships under the GNU GPL, version 3 (not the audit's 2-or-later: Qt
  is LGPL-3.0-only). Kris approved it in session.

## 4. Key context for S17

- **BRIEF §17** is the acceptance list; R11's real-desktop checks
  (`git show 1b415a4:docs/HANDOFF.md` §8) fold into it. RELEASING.md
  is the runbook: tag locally, then build.
- **Kris's slskd container no longer exists;** S17 needs a bring-up
  first (Settings → Connections, by Kris).
- **Gatekeeper's Open Anyway flow is UNVERIFIED** until S17 tries it
  on a quarantined download (`docs/packaging.md`).
- **Release notes' licence paragraph** is README → License's second
  paragraph with the tag named (RELEASING.md step 4).
- **Carried:** Sharing's 20 s per-row rebuild. Run the full suite in
  the background (~5 min). Never touch slskd or real data, and never
  launch the built app (it migrates the real data); in S17 Kris
  launches it.

## 5. Decisions made

- **GPL-3.0 for the combined app** (Kris, 2026-10-10), over the
  audit's GPL-2.0-or-later: Qt's LGPL-3.0-only rules out version 2.
- **Every runtime distribution's licence ships, not only copyleft
  ones** (MIT/BSD ask for their notice in binaries too).
- **A flaky worker test answers by the order loads were started,
  never by the order workers arrive,** and stops the shell's poll
  when the Dashboard shares its fake.

## 6. Blockers

None.

## 7. Files in progress

None uncommitted.

## 8. Waiting on Kris

- **From S16:** after S17's build, turn "Start Seeker at login" on
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

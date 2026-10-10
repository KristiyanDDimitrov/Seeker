# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S16c part one's close-out (HISTORY §216). Tree clean apart
  from the untracked `Claude outputs/`. `dist/` is still S16b's build.
- **Local (Cocoa):** pytest `2275 passed, 1 skipped`, 0 failed (+19
  tests); only the stress test skipped (CI skips 29). `mypy --strict
  src/` clean, 144 files; `ruff check src tests tools` 0; `uvx radon
  cc -n D -s src/seeker` nothing.
- **CI:** pending for this push (recorded in the next commit).

## 2. Where we are

**S16c is half done:** stopped at its split point (after §16c.2) on
budget. **Next: S16c part two**, BRIEF §16c item 3, the UI way back.
Then S17, release-candidate acceptance (Kris and Code).

## 3. Session report (S16c, part one)

Evidence for each is in HISTORY §216.
- `97b942a` §16c.1: `SeekerConfig.slskd_share_path`/`slskd_data_dir`,
  absolute, written after every successful bring-up: `start_slskd`
  (persist or not) and Sharing's recreate (`record_bring_up`).
- `aaf2a72` §16c.2: `SharingService.container_presence()` (exact name
  over `docker ps -a --format {{.Names}}`; Docker failing → UNKNOWN).
  `restart_slskd`: present → the live share as before; absent → the
  recorded share and data folder plus the saved login, naming every
  missing fact in one `SlskdStartRefusedError` and refusing a folder
  not on disk; unknown → refuse. `start_slskd(..., data_dir=)` must
  be absolute.

## 4. Key context for S16c part two, then S17

- **BRIEF §17** is the acceptance list; R11's real-desktop checks
  (`git show 1b415a4:docs/HANDOFF.md` §8) fold into it. RELEASING.md
  is the runbook: tag locally, then build.
- **Part two's job (BRIEF §16c item 3):** when Start slskd is refused
  for missing facts, the notice offers Settings → Connections, where a
  "Start slskd" form (or the existing "Update SoulSeek credentials"
  section, renamed) takes the login (saved values prefilled), the
  folder to share (recorded first) and the data folder (recorded, else
  `slskd_data_dir()`, with "Choose…"; Kris's old one is the repo's
  `slskd-data/`), then calls `start_slskd(..., persist=True,
  data_dir=)`. Say what happens to slskd's state. Read
  `src/seeker/ui/CLAUDE.md` first; screenshots per BRIEF §0.13. The
  refusal comes from `Application.restart_slskd`, shown by
  `ui/slskd_status.py` and the Dashboard/Downloads Start buttons.
- **Kris's install today:** nothing recorded, login `null`, so Start
  slskd refuses naming all three until part two's form exists.
- **Gatekeeper's Open Anyway flow is UNVERIFIED** until S17 tries it
  on a quarantined download (`docs/packaging.md`).
- **Release notes' licence paragraph** is README → License's second
  paragraph with the tag named (RELEASING.md step 4).
- **Carried:** Sharing's 20 s per-row rebuild. Run the full suite in
  the background (~5 min). Never touch slskd or real data, and never
  launch the built app (it migrates the real data); in S17 Kris
  launches it.

## 5. Decisions made

- **Folders are recorded at every successful bring-up, even the
  wizard's unconfirmed one:** they describe the container that now
  exists, whatever its login turns out to be.
- **A recorded folder not on disk is refused, not created:** Compose
  would make an empty bind source (an unplugged drive's path).
- **Container presence compares exact names** over `docker ps -a`,
  not `--filter name=` (a substring match).

## 6. Blockers

None.

## 7. Files in progress

None uncommitted. S16c stopped after §16c.2 (its split point); item 3
not started.

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

- Should a CLI command start slskd (`restart_slskd` has none)? Not in
  the BRIEF; left out.
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

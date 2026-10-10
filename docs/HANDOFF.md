# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S16c part two's close-out (HISTORY §217). Tree clean apart
  from the untracked `Claude outputs/`. `dist/` is still S16b's build.
- **Local (Cocoa):** pytest `2287 passed, 1 skipped`, 0 failed (+12
  tests); only the stress test skipped (CI skips 29). `mypy --strict
  src/` clean, 144 files; `ruff check src tests tools` 0; `uvx radon
  cc -n D -s src/seeker` nothing.
- **CI: green.** `86c9d3e`'s run `38073243710`: `check` and `audit`
  both passed on the first attempt.

## 2. Where we are

**S16c is done** (§216, §217). **Next: S17**, release-candidate
acceptance (Kris and Code), which starts with Kris's bring-up.

## 3. Session report (S16c, part two)

Evidence for each is in HISTORY §217.
- `5cb71c3` §16c.3a: `SlskdSetupNeededError` (a
  `SlskdStartRefusedError`) for the four refusals Settings resolves;
  `Application.slskd_start_defaults()` (live folders, else recorded;
  saved login) and `slskd_data_folder_state()`; `start_slskd` never
  creates a named data folder but the per-user default.
- `4a047bd` §16c.3b: Settings → Connections' last section is **Start
  slskd** (login prefilled, share combo with unconnected locations
  disabled, data folder with Choose… and a sentence on what slskd
  keeps); it reads Docker only when the tab is shown. A
  `SlskdSetupNeededError` from Start slskd shows its text with **Open
  Settings** (`PageContext.open_settings`).

## 4. Key context for S17

- **BRIEF §17** is the acceptance list; R11's real-desktop checks
  (`git show 1b415a4:docs/HANDOFF.md` §8) fold into it. RELEASING.md
  is the runbook: tag locally, then build.
- **Kris's bring-up first:** Start slskd refuses (nothing recorded,
  login `null`) → Open Settings → fill the login, pick the share,
  Choose… the repository's `slskd-data/` (the sentence should read
  "carries on with the settings…") or keep the app-data default
  (fresh) → Start slskd. Code never clicks it.
- **Gatekeeper's Open Anyway flow is UNVERIFIED** until S17 tries it
  on a quarantined download (`docs/packaging.md`).
- **Release notes' licence paragraph** is README → License's second
  paragraph with the tag named (RELEASING.md step 4).
- **Carried:** Sharing's 20 s per-row rebuild; the Start slskd card's
  ~13 px of extra top spacing (§217). Run the full suite in the
  background (~5 min). Never touch slskd or real data, and never
  launch the built app (it migrates the real data); in S17 Kris
  launches it.

## 5. Decisions made

- **The old "SoulSeek credentials" section became the Start slskd
  form,** not a second form beside it; it changes the login too.
- **The form names no found data folder:** a `.app` can't know where
  an old repository sits; the state sentence describes the one shown.
- **An unconnected location is listed but disabled:** Compose would
  create its folder, empty, where the drive mounts.
- **The form reads Docker on show, never at construction.**

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
- **From S16c and §213:** bring slskd up again through Settings →
  Connections → Start slskd (choose the repository's `slskd-data/` or
  a fresh one), then the first real cleanup, yours to click:
  Downloads → "Clean up leftover files…".
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
  folder isn't there? Should `start_slskd` itself refuse a share not
  on disk (only the form guards it; the wizard passes a location)?
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

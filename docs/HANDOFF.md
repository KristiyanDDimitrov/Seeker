# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S16d's close-out (HISTORY §220). Tree clean apart from
  the untracked `Claude outputs/`. `dist/` is still S16b's build.
- **Local (Cocoa):** pytest `2298 passed, 1 skipped`, 0 failed (+5
  since §219); only the stress test skipped (CI skips 29). `mypy
  --strict src/` clean, 144 files; `ruff check src tests tools` 0.
- **CI:** run `38153654828` green (`ab3772a`, check and audit); it
  covers S16c's follow-ups and S16d, pushed together.

## 2. Where we are

**S16c is done** (§216, §217), with two follow-ups from Kris's
reports: sharing a folder is optional in Settings' Start slskd form
(§218) and in the setup wizard (§219). **S16d** (§220, Kris's report)
pins each Settings tab's notices above its scroll area. **Next: S17**,
release-candidate acceptance (Kris and Code), which starts with
Kris's bring-up. Push first and confirm CI.

## 3. Session report (S16d)

Evidence in HISTORY §220.
- `edf9db2`: Start slskd's outcome showed scrolled out of view at the
  default size. Each Settings tab's notices now sit in a `NoticeStrip`
  above its scroll area (`notice.pinned_notices`), shown only while a
  notice is; Library's Save destination had the same gap. A shell
  sweep fails the build on a page notice inside a scroll area.

Before it, the S16c follow-ups (§218, §219):
- `53c7a62`: `start_slskd(share_path=None)` shares nothing by
  mounting `slskd_empty_share_dir()` (the template requires a share
  mount); recorded like any share, recreated by `restart_slskd`, read
  back as None. Settings' combo opens on "Nothing for now" when no
  live or recorded share exists and needs no library location.
- `988604b`: the wizard's SoulSeek step offers "Share <location> with
  other SoulSeek users", unticked, only for a folder chosen in this
  run; a resumed wizard shares nothing instead of refusing.

## 4. Key context for S17

- **BRIEF §17** is the acceptance list; R11's real-desktop checks
  (`git show 1b415a4:docs/HANDOFF.md` §8) fold into it. RELEASING.md
  is the runbook: tag locally, then build.
- **Kris's bring-up first:** Start slskd refuses (nothing recorded,
  login `null`) → Open Settings → fill the login; the folder to share
  is optional ("Nothing for now" unless a share is live or recorded);
  Choose… the repository's `slskd-data/` (the sentence should read
  "carries on with the settings…") or keep the app-data default
  (fresh) → Start slskd. Code never clicks it.
- **The wizard's share checkbox** is worth a look on a fresh profile
  in S17 (unticked by default; Kris may prefer it ticked).
- **Gatekeeper's Open Anyway flow is UNVERIFIED** until S17 tries it
  on a quarantined download (`docs/packaging.md`).
- **Release notes' licence paragraph** is README → License's second
  paragraph with the tag named (RELEASING.md step 4).
- **Carried:** Library's pinned notice reaches ~8 px past the cards
  over the scroll bar's column (§220); Sharing's 20 s per-row rebuild; the Start slskd card's
  ~13 px of extra top spacing (§217); `tools/screenshots.py` draws the
  wizard's SoulSeek step resumed, so without the share checkbox
  (§219). Run the full suite in the background (~5 min). Never touch
  slskd or real data, and never launch the built app (it migrates the
  real data); in S17 Kris launches it.

## 5. Decisions made

- **The old "SoulSeek credentials" section became the Start slskd
  form,** not a second form beside it; it changes the login too.
- **The form names no found data folder:** a `.app` can't know where
  an old repository sits; the state sentence describes the one shown.
- **An unconnected location is listed but disabled:** Compose would
  create its folder, empty, where the drive mounts.
- **The form reads Docker on show, never at construction.**
- **Sharing is opt-in everywhere:** Settings opens on "Nothing for now"
  when nothing is shared yet, and the wizard's checkbox starts
  unticked (§218, §219).

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
  Connections → Start slskd (a share is optional; choose the
  repository's `slskd-data/` or a fresh one), then the first real cleanup, yours to click:
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

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

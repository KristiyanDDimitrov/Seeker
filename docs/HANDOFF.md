# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S16e's close-out (HISTORY §221). Tree clean (`Claude
  outputs/` is now ignored). `dist/` is still S16b's build, older
  than S16c–S16e: S17 rebuilds it.
- **Local (Cocoa):** pytest `2306 passed, 1 skipped`, 0 failed (+8
  since §220); only the stress test skipped (CI
  skips 29). `mypy --strict src/` clean, 144 files; `ruff check src
  tests tools` 0.
- **CI:** pending for the close-out push; the next commit records it.

## 2. Where we are

**S16e is done** (§221): every carried nit Code could fix before
acceptance. **Next: S17**, release-candidate acceptance (Kris and
Code), which starts with Kris's bring-up. Nothing in Code's hands
blocks it.

## 3. Session report (S16e)

Evidence in HISTORY §221.
- `624c394`: a pinned notice no longer overhangs the scroll bar
  (Library's reached 8 px past the cards); the strip's row takes the
  bar's column as a right margin, on every viewport resize.
- `b1af323`: the Start slskd data folder sentence was a line too tall
  (a `QFormLayout` row floors at a wrapped label's size hint); an
  `Ignored` vertical policy leaves it to `heightForWidth`.
- `e6198b9` (refactor) and `cf1f458`: `wizard.offer_library_share()`;
  `tools/screenshots.py` draws the SoulSeek step with its checkbox.
- `b7ec1aa`: Sharing's 20 s poll keeps an unchanged location's button
  (rows plus palette as the key).
- `d24d628`: the changelog says sharing is opt-in and slskd starts
  again from Settings. `a809410`: `Claude outputs/` ignored.

## 4. Key context for S17

- **BRIEF §17** is the acceptance list; R11's real-desktop checks
  (`git show 1b415a4:docs/HANDOFF.md` §8) fold into it. RELEASING.md
  is the runbook: tag locally, then build.
- **First, Code builds the release candidate from the tip**, with its
  SHA-256 (R11 §41 "Code prepares"); the current `dist/` predates
  S16c–S16e. **Open (Kris's call):** RELEASING.md tags `v0.1.0` before
  the build so `git describe` reads the tag; for a candidate that may
  still need a fix row, Code recommends building untagged (a bare SHA)
  and tagging in S18.
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
- Run the full suite in the background (~5 min). Never touch slskd or
  real data, and never launch the built app (it migrates the real
  data); in S17 Kris launches it.

## 5. Decisions made

- **The data folder sentence stays in the form,** aligned with the
  fields; an `Ignored` vertical policy fixes its height rather than
  moving it out to the card's width.
- **The inset follows the viewport's width,** not the bar's
  Show/Hide, which also fires while the page is destroyed.
- **The screenshots show a new user's wizard:** the SoulSeek step
  offers to share the demo's first location.
- **`Claude outputs/` goes in the tracked `.gitignore`,** so a release
  checkout's clean-tree check holds on any clone of Kris's.

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

- Tag `v0.1.0` before the release-candidate build (RELEASING.md), or
  build untagged and tag in S18? (Code recommends untagged.)
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

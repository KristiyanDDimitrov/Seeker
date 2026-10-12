# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S17's close-out (HISTORY §222). Tree clean.
- **Release candidate:** `dist/Seeker.dmg`, built untagged at
  `e10aa87`, SHA-256 `b373f7ae5ae8809c3f507d363529011d89c1b025f7970f3c2dfa0c90700f1e1e`
  (`dist/Seeker.dmg.sha256`). Commits after it touch only `tools/`
  and `docs/`.
- **Local (Cocoa):** pytest `2306 passed, 1 skipped`, 0 failed
  (unchanged; only the stress test skipped, CI skips 29). `mypy
  --strict src/` clean, 144 files; `ruff check src tests tools` 0.
- **CI:** run `38162346352` green (`a29ed7f`, check and audit); it
  covers all of S17's commits.

## 2. Where we are

**S17, Code's half is done** (§222). Kris's run on the test account
(2026-10-12) failed six checks (ACCEPTANCE.md → Results), which are
now fix rows **S17a–S17f** (BRIEF §17a–§17f, read-only diagnosis
included). Then S17g builds a new candidate and Kris re-runs the
checklist. **Next: S17a**, the Dashboard's next step during a scan.

## 3. Session report (S17, Code's half)

Evidence in HISTORY §222.
- The candidate: RELEASING.md step 3 as written, all as expected
  (ad-hoc, `spctl` rejects, `0.1.0`, clean tree, `shasum -c` OK).
- slskd read-only: Kris's bring-up is done (the app-data default, the
  empty share); the web UI on loopback only; the per-user Compose copy
  is valid but predates the digest pin, while the running image is the
  pinned digest.
- `57dc527`: `tools/window_checks.py`, the three reopen paths measured
  against a running app (Kris clicks what AX hides).
- `7dd745e`: `ACCEPTANCE.md`, the single checklist.

## 4. Key context for whoever runs S17a–S17g or S18

- **Each S17x row's BRIEF section separates what is established from
  what is a hypothesis.** §17b's 3589 is arithmetic over the progress
  throttle (25 × 288 = 7200 = 3611 + 3589), not where the work stops.
  §17d's lead (per-row re-measuring on every resize) is a hypothesis
  until the resize storm is timed at `HEAD` and at `eacdfc1`.
- **The test account's data and log are unreadable from here**
  (`/Users/test`: permission denied). S17c starts from the log Kris
  copies to `/Users/Shared/`.
- **`dist/Seeker.dmg` was rebuilt 2026-10-12 12:10** and no longer
  matches `dist/Seeker.dmg.sha256` (`b373f7ae…`, the candidate's).
  S17g rebuilds it from the fixed tree anyway.

- **The checklist is `ACCEPTANCE.md`;** results go in its Results
  section. Install the candidate into `/Applications` first (no other
  copy exists); its first launch runs the `last_searched_at`
  migration.
- **`tools/window_checks.py` has never run against Seeker** (only its
  queries, against Finder). A bug in it is a tool fix, not an app
  failure.
- **The sweep check has no scratch-config route:** enable it and wait
  a day (§222 explains why not `HOME`).
- **S18:** RELEASING.md from step 1 on the release commit: date the
  changelog's `[0.1.0]`, tag locally, rebuild (the checksum changes),
  then show Kris the push and `gh release create` commands.
- Never touch slskd or real data, and never launch the built app.

## 5. Decisions made

- **The candidate is untagged** (Kris, 2026-10-11): Help → Build shows
  `e10aa87`; S18 tags.
- **The checklist lives in its own file,** linked from here, not in
  the handoff (R11 §41 said "in the handoff"): one place to tick.
- **The window script uses `/usr/bin` paths** and a per-file `S603`
  ignore with its reason.

## 6. Blockers

None for S17a, S17b, S17d or S17f. S17c waits on the test account's
log, and S17e on Kris reproducing the problem with logging on.
S18 waits on S17g's re-run.

## 7. Files in progress

None uncommitted.

## 8. Waiting on Kris

For the S17x rows (SESSION-PLAN → "Waiting on Kris" → "Acceptance
failures"): the test account's `seeker.log*` in `/Users/Shared/`
(S17c); vetoes on quit-stops-work (S17c) and Confirm all per section
(S17f); live fullscreen checks (S17d, S17e). After S17g, the rest of
`docs/rounds/round-12/ACCEPTANCE.md`: the fresh
account, the live Retry/Cancel/Clean up, start at login again, the
sweep, the window paths, the Fix…, the stress test, and the vetoes
(S5, the wordmark, S15's wordings, S8's peer filenames, the wizard's
share checkbox). Then S18's outward commands.

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

- Should a template bump (a new slskd digest) reach an existing
  install's per-user Compose copy? It is never re-seeded, so Kris's
  copy still names the unpinned tag (§222).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

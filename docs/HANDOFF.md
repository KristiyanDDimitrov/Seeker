# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S17h part one's close-out (HISTORY §227). Tree clean.
- **Release candidate:** `dist/Seeker.dmg`, built untagged at
  `e10aa87`, SHA-256 `b373f7ae5ae8809c3f507d363529011d89c1b025f7970f3c2dfa0c90700f1e1e`
  (`dist/Seeker.dmg.sha256`). It predates every S17x fix; S17g
  rebuilds it.
- **Local (Cocoa):** pytest `2323 passed, 1 skipped`, 0 failed (was 2320; S17h.1 added
  three; only the stress test skipped, CI skips 29). `mypy --strict
  src/` clean, 144 files; `ruff check src tests tools` 0.
- **CI:** see the close-out commit's run (recorded in the final report).

## 2. Where we are

**S17h stopped at its split point** (§227): §17h.1 is done, so a
deleted button no longer skips a task's finish. **Next: §17h.2**, the
call sites, then S17i, S17j, S17k, then S17f; S17e waits on Kris's
run with logging. Then S17g's new candidate and Kris's re-run.

## 3. Session report (S17h, part one)

Evidence in HISTORY §227.
- The log ties the crashes to Review: task 3663, a Review Confirm,
  failed on slskd's `429` 0.5 s before the 18:58:41 CRITICAL; Review's
  tables rebuild on every row change, which a running download makes
  every ~20 s.
- `abdeba6` (§17h.1): `run_worker`'s finish and error handlers and
  `BusyActionRegistry.end` skip a button `shiboken6` reports deleted,
  then run the callback and free the worker. Failed on `HEAD`: the
  callback never ran (`assert [] == ['done']`), the registry raised.
- Stopped at the split point: §17h.2 touches Review's three tables,
  Tag, Search and Duplicates plus a sweep test, more than the row's
  remaining budget.
- Skills: `tdd`. Divergence, as in S17c: `tdd` asks to confirm the
  seams with the user; BRIEF §17h names them (`run_worker`'s
  handlers), so they were taken as agreed.

## 4. Key context for whoever runs S17h.2–S17k, S17e–S17g or S18

- **§17h.2's call sites are listed in HISTORY §227 → "Not done"**
  (an AST scan; the script is a dozen lines over `ast.Call` named
  `run_worker`/`run_busy_worker`, `button=` keyword or positional).
  Review's five are the confirmed site, the Dashboard's per-row Tag
  (`tagging_panel.tag_track`) the BRIEF's hypothesis. Downloads'
  `_ROW_ACTION_KEYS` is the precedent; Review's rows are per track,
  so its key is likely the set of track ids in flight. A sweep test
  could fail any `button=` that is not a `self.` attribute, its
  exceptions named (working agreement 5).
- **Each S17x row's BRIEF section separates what is established from
  what is a hypothesis.** Measure before fixing, as §224–§226 did.
- **Long work that should stop on quit takes `stop:
  threading.Event | None`** and a page passes `self._context.quitting`.
  The scan, match, tagging and merge take none yet (§226 → "Not
  done").
- **The test account's files are unreadable from here**
  (`/Users/test`); Kris copies them to `/Users/Shared/`.
- **Timing at scale without touching real data:** copy the DB with
  `sqlite3 -readonly … ".backup '<scratchpad>/seeker.db'"` and run
  the service against the copy with the X9 Pro mounted (§224).
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
- **A quit stops running work at once, and what finished stays**
  (BRIEF §17c's default; not vetoed). No new quit confirmation for it.
- **No hard exit after the quit's bound** (§226: no measured reason;
  a tag write in place could be cut).
- **The checklist lives in its own file,** linked from here.

## 6. Blockers

None for S17h–S17k or S17f. S17e waits on Kris reproducing the
problem with logging on. S18 waits on S17g's re-run.

## 7. Files in progress

None uncommitted. §17h.2 not started.

## 8. Waiting on Kris

For the S17x rows (SESSION-PLAN → "Waiting on Kris" → "Acceptance
failures"): the veto on Confirm all per section (S17f); live
fullscreen checks (S17d on the S17g build: Dashboard, Library,
Duplicates, fullscreen and back; S17e); on the S17g build, quit while
Compute fingerprints runs and confirm the app exits within seconds.
After S17g, the rest of `docs/rounds/round-12/ACCEPTANCE.md`: the
fresh account, the live Retry/Cancel/Clean up, start at login again,
the sweep, the window paths, the Fix…, the stress test, and the vetoes
(S5, the wordmark, S15's wordings, S8's peer filenames, the wizard's
share checkbox). Then S18's outward commands.

## 9. Open questions

- The test account's log has slskd answering `429 Too Many Requests`
  on `POST /api/v0/transfers/downloads/batches` during a playlist
  download (2026-10-08 18:58). Item 63's lead is a `500` on the same
  endpoint: is a 429 handled as a recognized rejection, or does it
  feed the locked-retry loop?

- Duplicates' table repositions 5,400 cell widgets on every resize
  (~67 ms a step at 1,800 groups, unchanged since round 11; §225).
  Worth a cheaper delegate `updateEditorGeometry`, or fewer cell
  widgets, if Kris's fullscreen check still stutters there?

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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S17l's close-out (HISTORY §238). Tree clean.
- **Release candidate:** `dist/Seeker.dmg`, built untagged at
  `e10aa87`, SHA-256 `b373f7ae5ae8809c3f507d363529011d89c1b025f7970f3c2dfa0c90700f1e1e`
  (`dist/Seeker.dmg.sha256`). It predates every S17x fix; S17g
  rebuilds it.
- **Local (Cocoa):** pytest `2405 passed, 1 skipped`, 0 failed (+9 on
  S17e's 2396; the X9 Pro mounted, so its 28 ran; CI skips 29).
  `mypy --strict src/` clean, 146 files; `ruff check src tests tools` 0.
- **CI:** see §7 for the push's run.

## 2. Where we are

**S17l is done** (§238): one slskd enqueue at a time per process; a
`429` is sent again after 0.5/1/2 s, then `SlskdBusyError` (no
locked-retry budget spent); BRIEF §17l's hypothesis (a backup left
stranded when slskd interrupts the poll's fallback) was confirmed by
test, for an outage too, and fixed. **Next: S17m** (Review's
Replace; the bulk buttons' enabled state), then S17n, S17o, then
**S17g**.

## 3. Session report (S17l)

Evidence in HISTORY §238. Each commit's tests failed first.
- `1989d1a` a module-level `_ENQUEUE_LOCK` around the batch POST.
- `eb47120` `ENQUEUE_BUSY_WAITS`, `SlskdBusyError`; the locked retry
  spends nothing on it and the poll's locked loop stops at it.
- `5bbf8a0` `_resume_interrupted_fallbacks` (new sets
  `STARTS_A_FALLBACK`, `HOLDS_A_FALLBACK`); a fallback entry whose
  enqueue errors otherwise is failed; an accepted transfer is
  recorded before its status check.
- Skills: `tdd` was not invoked as a skill; its red-green order was
  followed by hand (every test failed first, quoted in §238).

## 4. Key context for whoever runs S17g or S18

- **S17g:** RELEASING.md's build steps on the current HEAD, untagged
  (as `e10aa87` was); record the new SHA-256 in
  `dist/Seeker.dmg.sha256` and ACCEPTANCE.md, then hand Kris the six
  failed checks first. Never launch the built app.
- **Review's bulk actions** all take the rows on screen and refuse a
  row that changed since (§76, §88, §235, §236). A new one follows
  `_render_confirm_all_button` and a busy key in
  `main_window._BUSY_ACTION_LABELS`.
- **A per-row action takes a `RunningRows`, never `button=`**
  (`ui/CLAUDE.md`; the sweep fails the build). Duplicates shows the
  variant for a button whose enabled state also has a rule of its
  own: keep the rule per row and reapply it at start and end.
- **Each S17x row's BRIEF section separates what is established from
  what is a hypothesis.** Measure before fixing, as §224–§226 did.
- **A quit waits for a slskd bring-up by design** (§232): never
  kill Compose mid-recreate. `Application.is_starting_slskd()` is
  the one way to ask; a new bring-up path must go through
  `bring_up_slskd` or the quit confirmation misses it.
- **Settings and the wizard still run their own `QThreadPool`s**,
  whose destructors hold the exit (measured, §231). The login wait
  now cancels on quit; their other tasks (the bring-up, health
  checks) do not, and `cleanup_before_quit`'s bounded wait and its
  log never see them. Moving Settings onto `MainWindow.thread_pool`
  (CLAUDE.md's rule) is still open (§232 → "Not done").
- **Long work that should stop on quit takes `stop:
  threading.Event | None`** and a page passes `self._context.quitting`;
  a new pool call without one goes in `TAKES_NO_STOP`
  (`tests/test_quit_stop_sweep.py`) with a measured reason, or the
  build fails. Scratch timing with the real code: a scratch `HOME`
  holding a DB copy (platformdirs reads `HOME`; assert the resolved
  dir first), §233.
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

None for S17m. S17g waits on S17m–S17o; S18 waits on S17g's re-run.

## 7. Files in progress

None uncommitted. S17l done. CI: PUSH_PENDING

## 8. Waiting on Kris

For the S17x rows (SESSION-PLAN → "Waiting on Kris" → "Acceptance
failures"): the veto on Confirm all per section (S17f; both buttons
and their questions are in Review's screenshots); live
fullscreen checks (S17d on the S17g build: Dashboard, Library,
Duplicates, fullscreen and back; if the tray menu closes again
there, §237 says how to bring the trace back); on the S17g build, quit while
Compute fingerprints runs and confirm the app exits within seconds.
After S17g, the rest of `docs/rounds/round-12/ACCEPTANCE.md`: the
fresh account, the live Retry/Cancel/Clean up, start at login again,
the sweep, the window paths, the Fix…, the stress test, and the vetoes
(S5, the wordmark, S15's wordings, S8's peer filenames, the wizard's
share checkbox). Then S18's outward commands.

## 9. Open questions

- S17l (§238 → "Not done"): when a playlist download's or sweep's
  settled enqueue stays busy, should the pick be recorded for a later
  poll rather than failing the track after its search? Should a busy
  slskd end Review's Confirm all, as an outage does?

- Answered 2026-10-14 (the pools, the wizard's quit confirmation,
  the test segfault, Replace all/Resolve all, slskd's `429`): see
  SESSION-PLAN → "Waiting on Kris" and rows S17l–S17o.

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

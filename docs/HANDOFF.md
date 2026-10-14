# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S17g's close-out (HISTORY §242). Tree clean.
- **Release candidate:** `dist/Seeker.dmg`, built untagged at
  `6f49319`, 111,784,988 bytes, SHA-256
  `b203e98dd9764b3d27ddbb0a5707148fb555ed28bbe1db4e2a215871febeda07`
  (`dist/Seeker.dmg.sha256`, `shasum -c` OK beside it). It carries
  every S17a–S17o fix; the commits after it touch only docs.
- **Local (Cocoa):** pytest `2417 passed, 1 skipped`, 0 failed
  (unchanged; the X9 Pro mounted, so its 28 ran; CI skips 29).
  `mypy --strict src/` clean, 146 files; `ruff check src tests tools` 0.
- **CI:** run `38549671669` green on `6f49319`, the candidate's commit;
  run `38552915783` green on the close-out (`c9ffc01`).

## 2. Where we are

**S17g, Code's half, is done** (§242): the second candidate, built and
checked without launching it. **Next: Kris** re-runs the six
2026-10-12 failures on it, at the top of
`docs/rounds/round-12/ACCEPTANCE.md`, then the rest of that file. A
failure there becomes a fix row; otherwise **S18**.

## 3. Session report (S17g)

Evidence in HISTORY §242.
- The three checks, then `packaging/build_dmg.py` at `6f49319`
  (~48 s), then RELEASING.md step 3 as written: all expected.
- `92e7d1c`: RELEASING.md's `shasum -c` ran from the repository root,
  where the bare name in the `.sha256` file does not resolve
  (`FAILED open or read`); it now runs inside `dist/`.
- ACCEPTANCE.md: the new candidate, the first one's checks kept under
  their own heading, the six failures first with their rows and
  HISTORY entries.
- Skills: none loaded (`changelog-generator`, `runbook-generator`,
  `ship-gate` are named for S16–S18; RELEASING.md is the runbook and
  the checklist the gate, as in §222). No `self-eval`.

## 4. Key context for whoever runs S18 or a fix row

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
- **Only the wizard runs its own `QThreadPool`** (no shell exists
  yet), whose destructor holds the exit (measured, §231); Settings
  is on `MainWindow.thread_pool` (§240). The wizard asks before a
  close or quit while slskd starts (§241), through
  `window_lifecycle.ask_to_quit`, the shell's own words.
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
- **The checklist is `ACCEPTANCE.md`;** results go in its Results
  section. A fix row after a failure means a third candidate: rebuild
  as §242 did (untagged) and update the candidate table.
- **`tools/window_checks.py` has never run against Seeker** (only its
  queries, against Finder). A bug in it is a tool fix, not an app
  failure.
- **The sweep check has no scratch-config route:** enable it and wait
  a day (§222 explains why not `HOME`).
- **S18:** RELEASING.md from step 1 on the release commit: date the
  changelog's `[0.1.0]` (and decide whether S17f's "Confirm all" gets
  a line), tag locally, rebuild (the checksum changes), then show Kris
  the push and `gh release create` commands.
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

S18 waits on Kris's re-run of the six failures and the rest of
ACCEPTANCE.md.

## 7. Files in progress

None uncommitted. S17g's Code half done.

## 8. Waiting on Kris

`docs/rounds/round-12/ACCEPTANCE.md`, from the top: the six
2026-10-12 failures on the `6f49319` candidate (Scan's next step,
Find duplicates to the end, quit during fingerprints and duplicates,
fullscreen and back, the tray menu in fullscreen, Confirm all), with
the S17c and S17f vetoes beside them. Then the rest: the fresh
account, the live Retry/Cancel/Clean up, start at login again, the
sweep, the window paths, the Fix…, the stress test, and the vetoes
(S5, the wordmark, S15's wordings, S8's peer filenames, the wizard's
share checkbox). Then S18's outward commands.

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

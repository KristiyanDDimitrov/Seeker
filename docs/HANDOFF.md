# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** S17f part two's close-out (HISTORY §236). Tree clean.
- **Release candidate:** `dist/Seeker.dmg`, built untagged at
  `e10aa87`, SHA-256 `b373f7ae5ae8809c3f507d363529011d89c1b025f7970f3c2dfa0c90700f1e1e`
  (`dist/Seeker.dmg.sha256`). It predates every S17x fix; S17g
  rebuilds it.
- **Local (Cocoa):** pytest `2396 passed, 1 skipped`, 0 failed (was 2386; ten
  new tests; the X9 Pro mounted, so its 28 ran; CI skips 29). `radon
  cc -n D` nothing. `mypy --strict src/` clean, 146 files; `ruff
  check src tests tools` 0.
- **CI:** run `38453497494` green (`1484d8c`); it covers `cdb2a1a`, `e619b51`, `2274290` and the close-out.

## 2. Where we are

**S17f is done** (§235, §236): each of Review's three sections has
its bulk action; the SoulSeek candidates' "Confirm all (N)" asks
first, requests each row only as shown, and an slskd outage ends the
batch. S17e waits on Kris. **Next: S17g**, a new candidate from the
fixed tree, then Kris's re-run of the six failed checks (§9 lists
small rows Kris may want first).

## 3. Session report (S17f, part two)

Evidence in HISTORY §236.
- `cdb2a1a` refactor: `ReviewService._request_candidate`, one
  confirm's enqueue, shared by the single row and the batch.
- `e619b51` `ReviewService.confirm_review_candidates(candidates,
  stop=)` over the shown `(track, candidate)` pairs; a changed
  candidate or a refused enqueue is a failure left for review; an
  `httpx.TransportError` ends the batch as `ConfirmAllResult.outage`.
- `2274290` the button, question ("N downloads will start"), notice
  (success, warning, or error on an outage).
- Every new test failed first (4 service, 6 page); the running guard
  mutation-checked for both sections.
- Screenshots: Review, both themes, both sizes; the three header
  buttons align.
- Skills: `tdd`. Divergence: the batch takes the shown rows, not bare
  track ids.

## 4. Key context for whoever runs S17g, S17e or S18

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

None for S17g. S17e waits on Kris reproducing the problem with
logging on. S18 waits on S17g's re-run.

## 7. Files in progress

None uncommitted. S17f done.

## 8. Waiting on Kris

For the S17x rows (SESSION-PLAN → "Waiting on Kris" → "Acceptance
failures"): the veto on Confirm all per section (S17f; both buttons
and their questions are in Review's screenshots); live
fullscreen checks (S17d on the S17g build: Dashboard, Library,
Duplicates, fullscreen and back; S17e); on the S17g build, quit while
Compute fingerprints runs and confirm the app exits within seconds.
After S17g, the rest of `docs/rounds/round-12/ACCEPTANCE.md`: the
fresh account, the live Retry/Cancel/Clean up, start at login again,
the sweep, the window paths, the Fix…, the stress test, and the vetoes
(S5, the wordmark, S15's wordings, S8's peer filenames, the wizard's
share checkbox). Then S18's outward commands.

## 9. Open questions

- Move Settings' and the wizard's tasks onto `MainWindow.thread_pool`
  (§231–§233: their destructors hold the exit outside the bounded
  wait)? The last piece of item 125 besides a hung slskd.

- The wizard has no quit confirmation: closing it mid-bring-up waits
  for Compose (≤ 120 s) with no word, though its page shows the
  bring-up running (§232). Ask before closing, or leave it?

- **A pre-existing test segfault** (§231): "Garbage-collecting"
  inside `ui/wordmark.py`'s `_Brows.paintEvent` during a
  `test_wizard.py` test, about 1 run in 25 of `test_main_ui.py
  test_wizard.py test_settings_window.py` at `c8a0045`. Not seen in a
  full run or CI yet. A small row of its own before S17g (could the
  same GC-in-paint crash reach the real app)?

- Review's "Replace all" and Duplicates' "Resolve all groups" pass
  `button=` with a render-decided enabled state (the §145 rule), and
  an upgrade's Replace has no `on_error` (§228 → "Not done"). Fix in
  a small row before S17g?

- The test account's log has slskd answering `429 Too Many Requests`
  on `POST /api/v0/transfers/downloads/batches` during a playlist
  download (2026-10-08 18:58). Item 63's lead is a `500` on the same
  endpoint: is a 429 handled as a recognized rejection, or does it
  feed the locked-retry loop?

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

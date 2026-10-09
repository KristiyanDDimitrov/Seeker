# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S11 close-out (HISTORY §203). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2129 passed, 1 skipped`, 0 failed (+14
  tests). `mypy --strict src/` clean, 141 files; `ruff check src tests
  tools` 0; `radon cc -n D` nothing.
- **CI:** see §3's last line (the close-out push).

## 2. Where we are

**Round 12 S11 is done** (daily sweep II: the Settings toggle, the
shell's scheduler, the tray summary). **Next: S12**, X2: Retry and
Cancel on the Downloads page, BRIEF §12. The live Cancel needs Kris at
the keyboard (plan → "Waiting on Kris").

## 3. Session report (S11)

Evidence for each is in HISTORY §203.
- `48e7051` §11.1: Settings → General → "Daily sweep" card, its
  checkbox off by default, saved on toggle; `docs/cli.md`'s GUI map.
- `21651ec`: `run_sweep(stop)`, a `threading.Event` read before every
  search; `SweepResult.stopped`. Without it a quit mid-sweep kept the
  process alive up to ~40 min (the pool's destructor waits).
- `2e8fc50` §11.2: `ui/sweep_scheduler.py` (`SweepScheduler`,
  `SWEEP_KEY`, hourly `MainWindow.sweep_timer`); first check after
  the first poll that reaches slskd; `BusyActionRegistry.begin` and
  `_run_busy_worker` accept `button=None`.
- `6afbec0` §11.3: `TrayController.notify_sweep_requested`, under
  "Downloads finished"; silence when nothing was requested.
- The close-out: HISTORY §203, CLAUDE.md's sweep fact, the plan tick,
  this file. CI: recorded in the final message of the S11 session
  (`git log` the push; `gh run list --limit 1`).

## 4. Key context for S12

- **Retry** on `failed`/`unavailable` rows: one track through
  `DownloadService.search_and_request(track, thresholds)` with
  `current_thresholds()` (S10's extraction). The 30-day
  `UNAVAILABLE_COOLDOWN` already skips the peer and file that failed.
- **Cancel** on `queued` rows: verify slskd's transfer-cancel endpoint
  read-only first (the pinned version's API docs, `docker inspect`);
  a `DELETE` on a real transfer waits for Kris's yes. The row becomes
  `failed` with `failure_reason="Cancelled by you"`. Every slskd path
  segment is `quote(…, safe="")`d.
- **Downloads' buttons:** `cell_widget(..., row_label=)`. A button
  whose enabled state a render decides is never `run_worker`'s
  `button=` (ui/CLAUDE.md). A polled table rebuilds only on change.
- **Carried:** `test_library_track_list_refreshes_after_a_tag_run`'s
  one CI timeout (no row owns it); the callback handler has no socket
  timeout; Sharing's 20 s per-row rebuild (S15); `uv build --wheel`
  picks up a gitignored `_build_info_generated.py` (S16). Run the
  full suite in the foreground (~5 min). Never touch slskd or real
  data.

## 5. Decisions made

- **The sweep's tray notice uses "Downloads finished"**, not a new
  toggle; that tooltip says so. Kris can ask for a fourth toggle.
- **Turning the sweep on starts the first sweep within the hour**
  (the next hourly check), not at once.
- **A failed sweep is logged at WARNING only**; an outage already
  gets the backend poll's one notice.
- **After an outage the sweep waits for the next hourly check**; only
  the very first good poll after launch triggers one.
- **Skills:** `tdd`; `observability-designer` for log levels only.
  `frontend-design` was not loaded: one card in the existing
  `section_card` idiom, checked in screenshots in both themes.

## 6. Blockers

None for S12. Its live Cancel needs Kris present.

## 7. Files in progress

None: S11 is committed whole.

## 8. Waiting on Kris

- **New:** veto, if wanted, the four §5 decisions above; see the
  "Daily sweep" card on screen (Settings → General).
- **From S10:** the cooldown's reach into manual Download, the 30-day
  and 50-search numbers; the real `tracks.last_searched_at` migration
  runs on the next launch.
- **Still open:** S-04's GPL wording (S16); the live checks of
  §193–§196; the S5 wording veto; the wordmark's brows (`9ff777b`);
  BRIEF §17; S8's visible peer-filename change; `git show
  1b415a4:docs/HANDOFF.md` §8; the three nested locations in the real
  DB.

## 9. Open questions

- Should the sweep skip a track whose needs-review candidate is still
  waiting on a person? Today it searches it again (as `download_playlist`
  does), which can find an auto-tier candidate.
- Should a GUI sweep and a cron `seeker downloads sweep` guard against
  running at the same time? Nothing stops both today (UNVERIFIED how
  the two would interleave over `last_searched_at`).
- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED.)
- Does Dependabot's `docker-compose` ecosystem bump a `tag@digest`
  line as a pair?
- Should the callback handler get a socket timeout?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S10 close-out (HISTORY §202). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2115 passed, 1 skipped`, 0 failed (+27
  tests). `mypy --strict src/` clean, 140 files; `ruff check src tests
  tools` 0; `radon cc -n D` nothing.
- **CI:** `abef38b`'s run `37951603982` green: `check` `2087 passed,
  29 skipped`, coverage 94.75 % (floor 92 %); `audit`, no known
  vulnerabilities.

## 2. Where we are

**Round 12 S10 is done** (daily sweep I: config, service, `sweep_due`,
CLI). **Next: S11**, daily sweep II (the Settings toggle, the shell's
scheduler, the tray summary), BRIEF §11.

## 3. Session report (S10)

Evidence for each is in HISTORY §202.
- `57c28e9` §10.1: `auto_sweep_enabled` (off) and `last_sweep_at`.
- `2380005`: a track whose upgrade peer refused at enqueue was counted
  requested *and* failed; now requested only (red first).
- `167dfec`, refactor: `DownloadService.search_and_request(track,
  thresholds) -> TrackSearchOutcome`; `current_thresholds()`.
- `6ac1c9a`: a search skips a (peer, file) that went `unavailable` for
  the track within 30 days (`UNAVAILABLE_COOLDOWN`), in
  `download_playlist` too.
- `0d5e437` §10.2: `SweepService.run_sweep() -> SweepResult`;
  `tracks.last_searched_at` (migration rehearsed, counts unchanged);
  `Application.sweep_service`, whose `record_sweep` saves
  `last_sweep_at`.
- `fd36252` §10.3: `sweep_due(now, last_sweep_at, enabled)`.
- `ceaa3ad` §10.4: `seeker downloads sweep`; `docs/cli.md`.
- The close-out: the poller's "daily cadence" comment, HISTORY §202,
  CLAUDE.md (SoulSeek: the sweep fact), the plan tick, this file.

## 4. Key context for S11

- **What S11 calls:** `application.sweep_service.run_sweep()` (blocks
  for minutes: ≤ 50 searches of ≤ ~47 s each), on
  `MainWindow.thread_pool` through `run_worker`. It raises
  `SlskdUnreachableError` on an outage and records nothing; it
  returns `SweepResult(paused=True)` when paused. `sweep_due(now,
  application.settings.last_sweep_at, application.settings.
  auto_sweep_enabled)` decides. `run_sweep` already stamps
  `last_sweep_at` itself through `update_settings`, so the UI must
  not stamp it again.
- **The tray summary's "found something"** is `bool(result.requested)`
  (BRIEF §11.3). `still_missing` includes needs-review outcomes.
- **`tests/fakes.py` has no sweep fake yet**; S11 adds a
  `FakeSweepService` (and a `sweep_service` on `FakeApplication`).
- **`docs/cli.md`'s GUI map** says the sweep's screen is "planned";
  S11 replaces it with Settings → General.
- **Carried:** `test_library_track_list_refreshes_after_a_tag_run`'s
  one CI timeout (lead: no recency guard on `refresh_tracks`; no row
  owns it); the callback handler has no socket timeout; Sharing's
  20 s per-row rebuild (S15); `uv build --wheel` picks up a gitignored
  `_build_info_generated.py` (S16). Run the full suite in the
  foreground: a `&` background run from a finished shell stalled at
  3 % this session. Never touch slskd or real data.

## 5. Decisions made

- **The 30-day cooldown also applies to `download_playlist`**, not only
  the sweep: it is the documented intent of `unavailable` ("look for
  the same track from a different peer"). Kris can veto it.
- **`last_searched_at` is stamped before the search**, so a track whose
  search keeps failing still rotates to the back.
- **A pause mid-sweep stops it unrecorded**, like an outage: the next
  due check resumes it, oldest tracks first.
- **A CLI run records `last_sweep_at`** too: a sweep is a sweep.
- **Skills:** `tdd` (seams taken from the brief, as in S8/S9);
  `observability-designer` for log levels only (its dashboards and
  SLOs don't fit a desktop app).

## 6. Blockers

None for S11.

## 7. Files in progress

None: S10 is committed whole.

## 8. Waiting on Kris

- **New:** veto, if wanted, the cooldown's reach into manual Download
  (§5 above), or the 30-day / 50-search numbers.
- **The real migration** (`tracks.last_searched_at`, additive, all
  NULL) runs on Kris's next launch.
- **Still open:** S-04's GPL wording (S16); the live checks of
  §193–§196; the S5 wording veto; the wordmark's brows (`9ff777b`);
  BRIEF §17; S8's visible peer-filename change; `git show
  1b415a4:docs/HANDOFF.md` §8; the three nested locations in the real
  DB.

## 9. Open questions

- Should the sweep skip a track whose needs-review candidate is still
  waiting on a person? Today it searches it again (as `download_playlist`
  does), which can find an auto-tier candidate.
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

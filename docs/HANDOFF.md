# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S22 part 1 close-out commit (HISTORY §165, this
  handoff, the plan note). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-10-01, at `3f4bb33`): `1579 passed, 1
  skipped`, no warnings.
- **`mypy --strict src/`:** clean, 127 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** run `36835786591` on `37c5041` (the close-out commit):
  success, `1551 passed, 29 skipped`, branch coverage 92.83 % (floor
  89). It took ~25 min to be created after the push; GitHub was slow,
  not the workflow.

## 2. Where we are

S1–S21 ticked; **S22 part 1 done** (§22.1–§22.2, the row's named split
point; the session hit its budget). **Next: S22 part 2** — §22.3
(indexes), §22.4 (lazy `scipy.stats`), §22.5 (art-cache LRU), §22.6
(Dashboard re-render). Then S23.

## 3. Session report (S22 part 1)

Evidence for every line, with the before/after table, is in HISTORY §165.
- `516ed57` §22.1: default `local_files` reads leave fingerprints out;
  `get_all_for_location_with_fingerprints` for `duplicate_service`.
- `3f4bb33` §22.2: the Dashboard poll reads one playlist's rows
  (`get_all_for_playlist` ×3, `get_matched_in_playlist`): 28.0 ms /
  40.5 MB → 0.24 ms / 0.03 MB.

## 4. Key context

- **Measure with §165's pasted `bench_poll.py`** on a fresh
  `sqlite3 -readonly … ".backup <scratchpad>/copy.db"` each run
  (`initialize()` migrates the copy). The before numbers for §22.3 (the
  `EXPLAIN QUERY PLAN` output) and §22.4 (import times) are already in
  §165 — measure only the after.
- **§22.3 test shape, written and run red this session, then dropped
  to keep the tree clean:** a parametrized test in
  `tests/test_performance.py` running `EXPLAIN QUERY PLAN` on a fresh
  `Database` and asserting `USING INDEX idx_<table>_<cols>` and no
  `TEMP B-TREE`, for the four lookups (`playlist_tracks` one without
  its `ORDER BY p.name`, which always sorts). All four indexed columns
  are base columns, so `CREATE INDEX IF NOT EXISTS` in `SCHEMA` is safe
  on an old DB (it runs before `_migrate`; no migration rebuilds a
  table).
- **History is now the expensive poll:** `get_recent_events` (every
  20 s, even hidden) is an N+1, one `get_by_local_file_id` per local
  file — 6,921 queries, 49 ms. §22.3's `track_matches(local_file_id)`
  index helps; only files with `tagged_at` need the lookup. Not in the
  brief's list: decide in part 2 whether it is §22.3's measurement or
  its own commit.
- **A light `LocalFile` has `fingerprint is None`** whether or not one
  was computed (commented on the model). A test asserting a fingerprint
  must read through the fingerprint variant, or it passes vacuously.
- Carried: radon not in the env; coverage margin ~3.8 points. Never
  touch slskd or real data. zsh does not word-split `$var`; BSD `sed`
  lacks `\b`.

## 5. Decisions made

- **No whole-table `get_all_with_fingerprints`** (the brief named it):
  nothing would call it. Only the per-location variant exists.
- **§22.2 is four scoped queries, not one join:** four model types out
  of one join would need its own row decoder; each query goes through
  `playlist_tracks` and stays in its own repository.

## 6. Blockers

None.

## 7. Files in progress

None committed half-done; the split point is clean. Part 2 starts
§22.3 from scratch (see Key context).

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's decision (carried):** keep or discard `./slskd-data` (§140).

**Run the stress test** — CLAUDE.md requires it after any lifecycle
change, and S20 is one: `SEEKER_RUN_STRESS_TEST=1 uv run pytest
tests/test_stress_e2e.py` (X9 Pro mounted, Spotify and slskd up).

**Live checks:** S41's checklist, plus carried: S6 Refresh playlists;
S7 drift Scan; S8 Reject-then-Scan, failure reason; S9 mistyped Client
ID → Cancel; S11 Scan summary, Docker-stopped Download, Qt warning in
`seeker.log`, app menu "Seeker"; S12 slskd-stopped outage; S14
one-failing-track Download notice, Tag and Fix cover art summaries;
S15 `seeker downloads review`; S17 Review Confirm/Reject/Replace and a
locked download retrying (`SEEKER_DEBUG_POLL=1`). New for S20: close
to tray → reopen from the tray and from the Dock; fullscreen close →
reopen (comes back filled); quit with a download running (the
confirmation); "start hidden".

## 9. Open questions

- **§18.6 leftovers** (S23 is the natural home):
  `test_next_step_notice_hidden_when_nothing_selected_and_all_set_up`
  (asserts the initial hidden state 50 ms in; wait on the render, e.g.
  the Download button's disable); `test_load_tracks_shows_no_notice_
  when_nothing_was_skipped` and Settings'
  `test_remove_location_cancelled_removes_nothing` (negative after a
  bare wait; wait on completion or `wait_for_workers`).
- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). Not lifecycle
  in S20's sense; still unowned.
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
- Settings shows results and rejections on status labels, not notices,
  as does Duplicates' `_render_fingerprint_result`: S28/S29.
- CLI (carried): print `download`'s failure reasons; catch
  `httpx.HTTPStatusError`; bidi controls in `printable()`; the
  one-by-one upgrade review skips `printable()` (§156).
- `DownloadPoller._activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the transfer id is
  never recorded; the next cascade re-requests it. S22 part 2 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S22 close-out commit (HISTORY §166, this handoff, the
  plan tick, CLAUDE.md). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-10-01, at `c96418f`): `1593 passed, 1
  skipped`, no warnings.
- **`mypy --strict src/`:** clean, 127 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the push note at the end of this section.

## 2. Where we are

S1–S22 ticked (S22 part 2: §22.3–§22.6 plus the history poll). **Next:
S23 — test gaps** (§23; split point after §23.1, `metadata.py`).

## 3. Session report (S22 part 2)

Evidence for every line, with before/after tables, is in HISTORY §166.
- `b72b650` §22.3: four indexes in `SCHEMA`; `EXPLAIN QUERY PLAN`
  test.
- `8a2d65f` history poll: `LocalFileRepository.get_tagged`; 42.2 ms /
  7.25 MB → 1.83 ms / 0.10 MB, identical events.
- `99f0ac6` §22.4: lazy `scipy.stats`; `import seeker.cli` ~363 →
  ~77 ms, `seeker.main_ui` ~558 → ~188 ms.
- `00db2c7` §22.5: `AlbumArtCache` memory is a 64-entry LRU, locked.
- `c96418f` §22.6: Dashboard skips unchanged renders; progress updates
  in place; no blank cell widgets. 500 tracks: 131 → 0.2 ms
  (unchanged), 4.9 ms (progress-only).

## 4. Key context

- **`QTableWidget.setItem` costs ~2.4 ms a call** at 500 rows (cProfile,
  offscreen). Any hot-path table update should mutate existing items.
  The S27–S35 table rows will touch this.
- **Anything a Dashboard row bakes in must join `_RenderedRows`**
  (now in CLAUDE.md). The visual refresh (S31–S34) changes colors: a
  new baked color left out of the key will not repaint on a theme
  switch. `test_a_theme_change_recolors_the_review_link` guards the
  accent.
- Benchmarks: §165's `bench_poll.py`; §166 describes the render
  script. The §27.0 harness does not exist yet.
- Carried: radon not in the env; coverage margin ~3.8 points. Never
  touch slskd or real data. zsh does not word-split `$var`; BSD `sed`
  lacks `\b`.

## 5. Decisions made

- **The history poll fix is its own commit, not §22.3's measurement:**
  indexes alone saved only 6.5 of 49 ms; the cost was reading every
  file to find 27 tagged ones.
- **§22.6 compares whole `TrackStatus`es, not the brief's (id, state,
  progress) signature:** the actions cell also depends on `tagged_at`,
  and the status text on `soulseek_candidate`; dataclass equality is
  ~3 ms at 500 rows and cannot miss a field.
- **The in-place sort key is mutated, not replaced** (`setItem`
  cost); a test checks the re-sort.

## 6. Blockers

None.

## 7. Files in progress

None.

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
  Rarer since §166, still reachable when a Dashboard row's state
  changes while its Tag task runs (the row rebuilds).
- Settings shows results and rejections on status labels, not notices,
  as does Duplicates' `_render_fingerprint_result`: S28/S29.
- CLI (carried): print `download`'s failure reasons; catch
  `httpx.HTTPStatusError`; bidi controls in `printable()`; the
  one-by-one upgrade review skips `printable()` (§156).
- `DownloadPoller._activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the transfer id is
  never recorded; the next cascade re-requests it. Not performance, so
  not S22; X1 is the natural home.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

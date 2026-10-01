# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S18 close-out commit (HISTORY §161, this handoff,
  CLAUDE.md). Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (2026-10-01): `1576 passed, 1 skipped` — no
  warnings now (was 9). X9 Pro mounted.
- **`mypy --strict src/`:** clean, 123 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** pending for the close-out push; see the follow-up commit.

## 2. Where we are

S1–S18 ticked. **Next: S19** (MainWindow I: Dashboard flows move to
DashboardPage, BRIEF §19; split point after the sync, scan and match
flows move).

## 3. Session report (S18)

Evidence for every line is in HISTORY §161.
- `d9c179b` §18.1: fakes and shared builders → `tests/fakes.py`.
- `fb84686` §18.1: `FakeSharingService`'s default is a real `ShareStatus`.
- `7f7a49a` §18.2: six repro scripts → `tests/repro/`, names kept.
- `3712928` §18.2: step-4 repro's `sys.path` follows the move.
- `837a042` §18.3: `test_ui_smoke.py` split by concern (154 tests,
  names identical).
- `0a74582` §18.4: `tests/test_layering.py`.
- `3552077` §18.5: synthetic WAVs analyse without warnings.
- `bbe6bf4` §18.6: seven vacuous or racy asserts fixed, incl. the CI flake.

## 4. Key context

- **For S19:** the Dashboard-flow tests it moves are all in
  `tests/shell/test_dashboard_flows.py` (scan, download, destination
  dialog, result notices, backend-poll refresh, double-click to
  Review); move them to `tests/pages/test_dashboard_page.py` with the
  code. **For S20:** `tests/shell/test_window_lifecycle.py` and
  `test_quit.py`.
- **Test layout:** `tests/fakes.py` (import as `from fakes import …`;
  builders have no leading underscore: `make_track`, `make_location`,
  `confirm_yes`, `force_tray_available`, `wait_for_workers`),
  `tests/pages/`, `tests/shell/`, `tests/repro/`. **Basenames must be
  unique across test dirs** (no `__init__.py`: "import file mismatch",
  reproduced). CLAUDE.md → Testing.
- **`wait_for_workers(window)`** before asserting a click called
  nothing: `waitForDone` with no event processing. Where a stray worker
  would end in a modal (`plain_text.information`), stub it too, or the
  regression hangs instead of failing (seen: SIGALRM).
- Carried: radon D-or-worse in `src/` is 2; `poll_downloads` C (19).
  Coverage margin ~2.7 points (floor 89). Never touch slskd or real data.
- **Shell:** zsh does not word-split `$var`; BSD `sed` lacks `\b`/`\|`.
  Slice moved code by AST ranges in a script, then `ruff check --fix`
  on just the new files; never on `docs/screenshots/generate.py`
  (unlinted; it rewrites its imports).

## 5. Decisions made

- **The smoke file is gone, not slimmed:** what isn't the shell went
  top-level (`test_workers.py`, `test_ui_source_sweeps.py`).
- **Brief divergence (§18.5):** "long enough" alone cannot clear the
  tuning warning; the fix is length *and* a tone. Recorded in §161.

## 6. Blockers

None.

## 7. Files in progress

None. §18.6 stopped at the budget with three candidates read but not
fixed (Open questions).

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's decision (carried):** keep or discard `./slskd-data` (§140).

**Live checks:** S41's checklist, plus carried: S6 Refresh playlists;
S7 drift Scan; S8 Reject-then-Scan, failure reason; S9 mistyped Client
ID → Cancel; S11 Scan summary, Docker-stopped Download, Qt warning in
`seeker.log`, app menu "Seeker"; S12 slskd-stopped outage; S14
one-failing-track Download notice, Tag and Fix cover art summaries;
S15 `seeker downloads review`; S17 Review Confirm/Reject/Replace and a
locked download retrying (`SEEKER_DEBUG_POLL=1`). The stress test
(`SEEKER_RUN_STRESS_TEST=1`) now imports `fakes`; worth running with
S20's lifecycle move.

## 9. Open questions

- **§18.6 leftovers** (S23 is the natural home):
  `test_next_step_notice_hidden_when_nothing_selected_and_all_set_up`
  (asserts the initial hidden state 50 ms in; wait on the render, e.g.
  the Download button's disable); `test_load_tracks_shows_no_notice_
  when_nothing_was_skipped` and Settings'
  `test_remove_location_cancelled_removes_nothing` (negative after a
  bare wait; wait on completion or `wait_for_workers`).
- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
- Settings shows results and rejections on status labels, not notices,
  as does Duplicates' `_render_fingerprint_result`: S28/S29.
- CLI (carried): print `download`'s failure reasons; catch
  `httpx.HTTPStatusError`; bidi controls in `printable()`; the
  one-by-one upgrade review skips `printable()` (§156).
- `DownloadPoller._activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the transfer id is
  never recorded; the next cascade re-requests it. S22 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

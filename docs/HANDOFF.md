# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S19 close-out commit (HISTORY §162, this handoff, the
  plan tick). Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (2026-10-01): `1576 passed, 1 skipped`, no
  warnings. X9 Pro mounted.
- **`mypy --strict src/`:** clean, 123 files. **`ruff check src
  tests`:** 0 findings (now including `SLF001`).
- **CI:** run `36823511637` on `a503ad1` (the close-out commit): success.

## 2. Where we are

S1–S19 ticked. **Next: S20** (MainWindow II: extract the window
lifecycle, BRIEF §20; split point after geometry and close move).

## 3. Session report (S19)

Evidence for every line is in HISTORY §162.
- `f68834b` §19.1: Dashboard flows → `DashboardPage`; `DashboardHost`
  10 → 5 callables; flow tests → `tests/pages/test_dashboard_page.py`.
- `c93baa6` §19.2: the shell calls only public page methods.
- `184f558` §19.3: `SLF001` enforced over `src/` (46 → 0 in
  `main_window.py`).

## 4. Key context

- **For S20:** its tests are `tests/shell/test_window_lifecycle.py`
  and `test_quit.py`. `TrayHost` still takes four `poll_*` lambdas
  (deferred: the tray is built before the pages); now public calls,
  a candidate to fold into one `refresh_pages` callable if S20 touches
  it.
- **`SLF001` is live in `src/`:** a shell or page reaching another
  object's `_member` fails `ruff check`. Add a public method on the
  owner instead; tests are exempt.
- **Shell-facing page API** (HISTORY §162): Dashboard
  `refresh_playlists`, `poll_selected_playlist`, `poll_next_step`,
  `load_playlists`; Review `focus_track`, `poll_review_items`,
  `needs_review_count`; Sharing `on_shown`, `poll_sharing`; Library
  `tag_track`/`retag_track`/`tag_playlist`; `TrayController.has_icon`.
- **Test layout:** `tests/fakes.py` (import `from fakes import …`),
  `tests/pages/`, `tests/shell/` (backend poll now
  `test_backend_poll.py`), `tests/repro/`. Basenames unique across
  dirs. `wait_for_workers(window)` before asserting a click called
  nothing.
- Carried: radon D-or-worse in `src/` was 2 (not re-measured: radon is
  not in the env); coverage margin ~2.7 points (floor 89). Never touch
  slskd or real data.
- **Shell:** zsh does not word-split `$var`; BSD `sed` lacks `\b`.
  Slice moved code by AST ranges in a script (worked again here), then
  `ruff check --fix` on just the touched files.

## 5. Decisions made

- **`DashboardHost` shrinks, not disappears:** its five callables all
  land on another page (Settings tab, Review focus, Library tagging).
- **Flows live on the page itself**, not a `dashboard_actions.py`:
  every one drives the page's own buttons and notices.
- **`SLF001` enforced project-wide** (tests exempt), recorded in
  CLAUDE.md → Conventions.

## 6. Blockers

None.

## 7. Files in progress

None.

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

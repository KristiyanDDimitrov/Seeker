# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S20 close-out commit (HISTORY §163, this handoff, the
  plan tick, CLAUDE.md). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-10-01): `1576 passed, 1 skipped`, no
  warnings; 10 consecutive full runs at
  `3b951a2`, all `1576 passed, 1 skipped`.
- **`mypy --strict src/`:** clean, 125 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** CI_SUMMARY

## 2. Where we are

S1–S20 ticked. **Next: S21** — **[ASK]** package regrouping (BRIEF
§21). It needs Kris's explicit yes before any work; if the answer is
no or not yet, S22 (Performance) can go first.

## 3. Session report (S20)

Evidence for every line is in HISTORY §163.
- `a3aaa11` §20.1: `WindowLifecycleController` (`ui/window_lifecycle.py`)
  owns geometry, hide-to-tray, Dock icon, quit; MainWindow delegates.
- `8e47efd` §20.2: `ThemeToggleButton` → `ui/widgets.py`.
- `3b951a2` §20.3: `MainWindow.__init__` is 28 lines of named steps.

## 4. Key context

- **Lifecycle state lives on `window._lifecycle`** (tests:
  `window._lifecycle._hidden_to_tray`, `._reopen_filled`,
  `._hide_request_id`, `.confirm_quit_if_downloads_active`). Pages
  still read it through `PageContext.is_hidden_to_tray`.
- **Patch the Dock icon at `seeker.ui.window_lifecycle.
  _set_dock_icon_visible`**; `main_window` no longer imports it (nor
  `sys`). The quit log lines come from logger
  `seeker.ui.window_lifecycle`.
- **The tray reopens through `MainWindow.reopen()`;** `TrayHost` no
  longer has `set_hidden_to_tray`/`bump_hide_request_id`/
  `set_dock_icon_visible`. It still has the four `poll_*` lambdas (the
  tray is built before the pages).
- **`main_window.py` is 1,283 lines, not ~1,100:** 390 are comments.
  S25 (comment hygiene `ui/`) closes the gap; `window_lifecycle.py`
  carries the moved comments verbatim and is in S25's scope too.
- Carried: radon not in the env (D-or-worse was 2); coverage margin
  ~2.7 points (floor 89). Never touch slskd or real data.
- **Shell:** zsh does not word-split `$var`; BSD `sed` lacks `\b`.
  Slicing moved code by line range in a Python script, then `ruff check
  --fix` on the touched files, worked again.

## 5. Decisions made

- **Reopen moved from the tray to the lifecycle,** so one class writes
  the hidden-to-tray state; recorded in CLAUDE.md (Qt section).
- **`cleanup_before_quit` runs the shell's teardown first**
  (`release_shell`), then the geometry backstop; the two settings
  writes touch different keys (HISTORY §163).
- **Comment text was not trimmed to hit the line target** (S25 owns
  it).

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping (next row); S30 visual
direction; S39 bundle identifier; S42 publishing commands; X1 and X2
(optional).

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
  never recorded; the next cascade re-requests it. S22 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

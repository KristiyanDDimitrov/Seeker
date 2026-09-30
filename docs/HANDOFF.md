# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S17 part 2 close-out commit (HISTORY §160, this
  handoff, CLAUDE.md layout). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-10-01): `1558 passed, 1 skipped, 9 warnings`
  (X9 Pro mounted).
- **`mypy --strict src/`:** clean, 123 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the follow-up commit that records the close-out's run.

## 2. Where we are

S1–S17 ticked. **Next: S18** (test infrastructure, BRIEF §18; split
point after §18.2, the smoke-file split can stand alone).

## 3. Session report (S17 part 2)

Evidence for every line, radon and the debt scanner before and after,
is in HISTORY §160.
- `5eeb48d` §17.3: `_retry_locked_request` as named steps, D (24) →
  B (7).
- `32dceba` the line ceiling: `soulseek/poller.py`, `DownloadPoller`;
  `download_service.py` 1,421 → 729 lines.

## 4. Key context

- **Polling lives in `DownloadPoller`** (`DownloadService.poller`);
  `DownloadService.poll_downloads()` delegates and stays the one
  public entry. Its private helpers are now `service.poller._…`.
- **`SEEKER_DEBUG_POLL` now raises `seeker.soulseek.poller`'s logger**
  (the trace's two lines moved with the code). Anything filtering the
  trace by logger name uses that name.
- radon D-or-worse in `src/` is now 2: `_insert_slskd_share_directory`
  D (26) and `_decide_next_step` D (21). `poll_downloads` is C (19),
  two short of D; S22's poll work should not push it over.
- **For S18:** the smoke file's fakes include `FakeReviewService`
  (split from `FakeDownloadService` in S17 part 1) and
  `FakeApplication.review_service`; `tests/service_seams.py` builds a
  real `ReviewService` for a `DownloadService`. Move them with the
  others in §18.1.
- **Carried:** fakes of `get_download_status` return
  `TransferStatus(..., exception=...)`. TRY400/G201 lint-enforced.
  Coverage margin ~2.7 points (floor 89). No `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; never touch slskd or real
  data; tests `monkeypatch.setenv`. `_fix_one_track_art` mutates the
  shared `FixArtResult`; `delete_local_files` and
  `generate_match_report` still return dicts.
- **Shell:** zsh `echo ======` and unquoted `--include=*.py` fail;
  BSD `sed` lacks `\b`/`\|`; write edit scripts with the Write tool.
  A moved block goes through a script that slices by markers, then
  `ruff check --fix` on just those files (full rule set) for imports.

## 5. Decisions made

- **`DownloadPoller` reaches slskd through a callable** (`lambda:
  self.soulseek`), as `ReviewService` does: a test swapping
  `service._soulseek_client` still reaches it, and the unconfigured
  error stays the download service's.
- **`DownloadService.poll_downloads` delegates** rather than
  `Application` exposing the poller: the UI, CLI and hundreds of test
  calls stay unchanged, and nothing outside `soulseek/` needs polling
  internals.
- **`poller.py` at 801 lines meets "about 800"**; splitting the retry
  out again would scatter one state machine over two files.
- Carried: help text's "Roadmap item" strings wait for S24.

## 6. Blockers

None.

## 7. Files in progress

None; S17 is complete.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's decision (carried):** keep or discard `./slskd-data` (§140).

**Live checks:** S41's checklist, plus carried: S6 Refresh playlists;
S7 drift Scan; S8 Reject-then-Scan, failure reason; S9 mistyped Client
ID → Cancel; S11 Scan summary, Docker-stopped Download, Qt warning in
`seeker.log`, app menu "Seeker"; S12 slskd-stopped outage (CLI exit 1;
Dashboard, Downloads, tray once; clears ~20 s after Start slskd); S14
one-failing-track Download notice, Tag and Fix cover art summaries;
S15 a real `seeker downloads review` prompts as before; S17 a Review
page Confirm, Reject and Replace behave as before, and a locked
download still retries and completes (`SEEKER_DEBUG_POLL=1` shows the
trace).

## 9. Open questions

- **CI-only flake:** `test_download_button_disabled_with_no_playlist_selected`
  (run `36758864929` attempt 1). Asserts after a bare `qtbot.wait(50)`;
  UNVERIFIED guess: a timer-driven render enabling the button. §18.6
  is the natural place.
- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
  S18?
- Settings shows results and rejections on status labels, not notices,
  as does Duplicates' `_render_fingerprint_result`: S28/S29.
- CLI (carried): print `download`'s failure reasons; catch
  `httpx.HTTPStatusError`; bidi controls in `printable()`; the
  one-by-one upgrade review skips `printable()` (see §156).
- S19 or S29: `DestinationDialog`'s unchecked "Remember this" drops the
  typed subfolder. S29: should a rejection be undoable?
- `DownloadPoller._activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the enqueued transfer
  id is never recorded, so the next cascade re-requests it. S22 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md`,
`main_window.py` or `test_ui_smoke.py`; `grep -n`, then a range.
pytest: summary line plus named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

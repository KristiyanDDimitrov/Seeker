# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S14 part-1 close-out commit (HISTORY §154, session
  plan, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1532 passed, 1 skipped, 6 warnings`
  (X9 Pro mounted; S14 part 1 adds 4 tests).
- **`mypy --strict src/`:** clean, 116 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** close-out `79e16cd` → run `36758864929`. Attempt 1
  **failure**: `1 failed, 1503 passed, 29 skipped`, the one being
  `tests/pages/test_dashboard_page.py::test_download_button_disabled_with_no_playlist_selected`
  (`assert not download_button.isEnabled()`). Attempt 2 (failed job
  rerun) **success**: `1504 passed, 29 skipped`, coverage 91.77 %.

## 2. Where we are

S1–S13 ticked; **S14 half done**, stopped at its named split point
("after the download and poll results") because context reached the
150 K ceiling. **Next: S14 part 2** — the rest of §14.1 (scan, match,
tag, art, fingerprint results), §14.2 `DownloadSelection`, §14.3
`_tag_one_track`. Then S15.

## 3. Session report (S14 part 1)

Evidence for both is in HISTORY §154.
- `0033510` §14.1 (refactor): `models/download_result.py` —
  `PlaylistDownloadResult`, `ManualDownloadResult`, `PollResult`.
- `ec93642` §14.1 (behaviour, brief's listed exception):
  `PlaylistDownloadResult.failures` (`TrackFailure(track, reason)`);
  the Dashboard notice lists up to five and turns into a warning.

## 4. Key context

- **For S14 part 2, still dicts:** `LibraryService.scan_all`/
  `scan_and_match` (`library/service.py:297`, `:323`),
  `LibraryScanner.scan` (`scanner.py:46`, feeds `scan_all`),
  `TrackMatcher.match_all` (`matcher.py:191`), `MetadataService.
  tag_tracks` (`:345`) and `fix_missing_art_for_playlist` (`:714`),
  `DuplicateService.compute_fingerprints` (`:258`). Not in the brief:
  `metadata_service.py:314`, `generate_match_report`,
  `duplicate_service.py:596`; `spotify/client.py:160` is raw JSON.
- **Test churn for part 2:** `test_metadata_service.py` reads
  `counts["tagged"]`/`["failed"]`/`["details"]` ~60 times;
  `test_ui_smoke.py:543` has `_EMPTY_TAG_RESULT` as a dict. A regex
  over `(result|counts)\["key"\]` → `.key` did part 1's 110 sites
  cleanly; then fix the stragglers the run names.
- **Placement decision (part 1):** results shared by CLI and UI go in
  `models/`; `TagResult`/`FixArtResult` may sit beside `RenameResult`
  in `metadata_service.py` (the brief's precedent). Record whichever.
- **radon:** `_tag_one_track` E (32), `select_downloads` C (14):
  `uv run --with radon radon cc -s <file> -n C`.
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin ~2.7 points (floor 89). Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; never touch slskd or real data;
  `config.*()` are functions (tests use `monkeypatch.setenv`). Outage
  state has one writer (`_trigger_backend_poll`).
  `RETRYING_IN_BACKGROUND`, not `RETRYING`. For S16:
  `DownloadRequestRepository.get_active_for_track` has no caller.
- **zsh:** `echo ======` fails (use `'---'`); BSD `sed` lacks `\b`.

## 5. Decisions made

- **Download results live in `models/download_result.py`**, not in
  `download_service.py`: CLI and UI both import them, and S17 splits
  the service.
- **`failed` became a property** (`len(failures)`), so a count and its
  list cannot disagree.
- **The Dashboard lists at most five failures**, then "and N more
  (details in the log)"; any failure makes the notice a warning.
- **The CLI still prints only the failure count** — parity is S15's
  call (see open questions).

## 6. Blockers

None.

## 7. Files in progress

None mid-edit. Stopped at a split point: the rest of §14.1, §14.2
and §14.3 are `not_started`.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).
Private vulnerability reporting: **done** (confirmed enabled).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's own decision (carried):** keep or discard `./slskd-data`
(HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists, S7's
drift Scan, S8's Reject-then-Scan and failure reason, S9 part 2's
mistyped Client ID → Cancel, S11's Scan summary / Docker-stopped
Download / Qt warning in `seeker.log` / app menu "Seeker", S12's
slskd-stopped outage (CLI exit 1; Dashboard, Downloads, tray once;
cleared within ~20 s of Start slskd). S14 adds: a playlist Download
with one track failing shows a warning notice naming it.

## 9. Open questions

- **New CI-only flake:** `test_download_button_disabled_with_no_playlist_selected`
  failed once on CI (run `36758864929` attempt 1), passes locally 5/5
  and on the rerun. It never clicks Download, so S14's changes are not
  on its path. It asserts after a bare `qtbot.wait(50)`; a first
  guess, UNVERIFIED, is a timer-driven render enabling the button. If
  it recurs, diagnose it (S18's test-infrastructure row fits).

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
  S18?
- Settings shows results and rejections on status labels, not notices:
  S29.
- S15 (CLI): print `download`'s failed tracks with their reasons, as
  the Dashboard now does? Catch `httpx.HTTPStatusError` too (S13 left it: a
  behaviour change the brief doesn't ask for)? Should `printable()`
  strip bidi controls, and `downloads status` print failure reasons?
- S19 or S29: `DestinationDialog`'s unchecked "Remember this" drops the
  typed subfolder. S29: should a rejection be undoable?
- `_activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the enqueued transfer
  id is never recorded, so the next cascade re-requests it. Rare; not
  taken. S17 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md`,
`main_window.py` or `test_ui_smoke.py`; `grep -n`, then a range.
pytest: summary line plus named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

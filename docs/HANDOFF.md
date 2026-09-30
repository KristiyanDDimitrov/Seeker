# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S13 close-out commit (HISTORY §153, CLAUDE.md, session
  plan, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1528 passed, 1 skipped, 6 warnings`
  (X9 Pro mounted; S13 adds 12 tests).
- **`mypy --strict src/`:** clean, 115 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** close-out `c1c42e7` → run `36732283322`, **success**,
  `1500 passed, 29 skipped`, branch coverage 91.70 % (floor 89).

## 2. Where we are

S1–S13 ticked. **Next: S14, typed service results (§14).** Phase F
continues: behaviour-neutral refactors only.

## 3. Session report (S13)

Evidence for all three is in HISTORY §153.
- `e943858` §13.1 (refactor): `seeker/errors.py` (`SeekerError`, one
  `PlaylistNotFoundError`, one `LibraryLocationNotFoundError`); every
  public error subclasses it; the format list derives from
  `DOWNLOADABLE_EXTENSIONS_IN_ORDER`.
- `244eda4` §13.1 (behaviour): `cli.run` catches `SeekerError`.
- `71d9943` §13.2 (refactor): `DownloadStatus`/`DownloadRole` and eight
  named status sets in `models/download_request.py`; SQL takes status
  values as parameters.

## 4. Key context

- **For S14:** the status words still in `src/` are result-dict keys:
  `poll_downloads`' `counts` (one key per status, plus `"failed"`
  bumped by hand), `download_playlist`'s `result["settled"]`/
  `["failed"]`, metadata and duplicate `counts["failed"]`. Typed
  results replace them; a per-status count can key on
  `DownloadStatus`.
- **`RETRYING_IN_BACKGROUND`, not `RETRYING`:** `track_status.RETRYING`
  is a Dashboard track state and `dashboard_service` imports both.
- **`_row_to_download_request` raises on an unknown status/role.** The
  real DB's 21 rows are all members (checked read-only, §153).
- **Tests may pass plain strings** to `DownloadRequest(status=…)`:
  equal and hash-equal to the members.
- **For S16:** `DownloadRequestRepository.get_active_for_track` has no
  caller and counts `unavailable` as active. Delete it there.
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin about 2.7 points (CI 91.68 %, floor 89). deptry: `uv
  run --with deptry deptry src`. Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; fakes of `connect_spotify`
  accept `cancel=`; `FakeApplication.restart_slskd` has
  `restart_slskd_calls`/`restart_slskd_error`; never touch slskd or
  real data; `config.*()` are functions (tests use
  `monkeypatch.setenv`). Outage state has one writer
  (`_trigger_backend_poll`).
- **zsh:** `echo ======` fails (use `'---'`); BSD `sed` lacks `\b`.

## 5. Decisions made

- **Errors move into `errors.py` only when more than one module raises
  them.** The brief allowed "moved in or subclassed"; moving all of
  them would separate each from the code that raises it.
- **The unsupported-format message now lists "aif".** Derived from the
  set, as the brief asked; the hand-written list had dropped it.
- **The rate-limit and library-unavailable CLI branches fold into the
  `SeekerError` one** (same sentence, now through `printable()`).
- **SQL status values are parameters** built by `_status_in`, not
  literals repeated in SQL: the sets are then defined once.
- Promoted to CLAUDE.md: the `SeekerError` rule, the named-status-set
  rule, `errors.py` in the layout.

## 6. Blockers

None.

## 7. Files in progress

None.

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
cleared within ~20 s of Start slskd). S13 adds none (refactor).

## 9. Open questions

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
  S18?
- Settings shows results and rejections on status labels, not notices:
  S29.
- S15 (CLI): catch `httpx.HTTPStatusError` too (S13 left it: a
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

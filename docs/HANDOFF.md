# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S14 part-2 close-out commit (HISTORY §155, session
  plan, CLAUDE.md, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1538 passed, 1 skipped, 9 warnings`
  (X9 Pro mounted; part 2 adds 6 tests; the 3 new warnings are
  librosa `UserWarning`s from the new metadata test's real analysis).
- **`mypy --strict src/`:** clean, 119 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** close-out `86d84e7` → run `36763618382` **success**:
  `1510 passed, 29 skipped, 9 warnings`, coverage 91.86 %.

## 2. Where we are

S1–S14 ticked. **Next: S15** (CLI structure, BRIEF §15; split point
after §15.1). Then S16.

## 3. Session report (S14 part 2)

Evidence for every line is in HISTORY §155.
- `a0a1fdd` §14.1: `ScanResult`, `MatchResult`, `ScanAndMatchResult`.
- `1905c4b` §14.1: `TagResult`, `FixArtResult`; rename formatters take
  `RenameResult`.
- `537ed5d` fix (behaviour): fix-art summary counts WAV fixes in "of N".
- `99b5ab7` §14.1: `FingerprintResult`.
- `8c86d7b` §14.2: `DownloadSelection`, `NeedsReviewCandidate`.
- `19d9769` §14.3: `_tag_one_track` E (32) → B (9), named steps.
- `ed52146` review: CLI test fakes return the typed scan results.

## 4. Key context

- **For S15:** `cli.handle_library` is radon **F (54)**, the worst
  function in `src/` (`uv run --with radon radon cc -s src/ -n D`).
  The `tag`/`fix-art`/`fingerprint` branches now name their results
  `tag_result`/`art_result`/`fingerprint_result`: one `result` reused
  across `elif` branches fails mypy once the types differ.
- **For S16:** `_fix_one_track_art` (C, 15) still mutates the shared
  `FixArtResult` it is passed, the pattern §14.3 removed from tagging;
  `TagResult.record`/`_TagNote` is the model. Still dicts, not in the
  brief: `DuplicateService.delete_local_files`,
  `TrackMatcher.generate_match_report`. Carried:
  `DownloadRequestRepository.get_active_for_track` has no caller.
- **Neutrality detail:** a tagged-but-unanalysed track whose later step
  raises counts as `skipped_already_tagged` *and* `failed` (old and new
  code alike; pinned by a test). So `summarize_tag_result`'s "of N"
  can over-count. Not changed.
- **For S28/S29:** Duplicates' `_render_fingerprint_result` writes the
  fingerprint result to `duplicates_status_label`, which CLAUDE.md
  reserves for disposable progress text; a result belongs on a notice.
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin ~2.7 points (floor 89). Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; never touch slskd or real data;
  `config.*()` are functions (tests use `monkeypatch.setenv`). Outage
  state has one writer (`_trigger_backend_poll`).
  `RETRYING_IN_BACKGROUND`, not `RETRYING`.
- **Shell:** zsh `echo ======` fails (use `'---'`); BSD `sed` lacks
  `\b` and `\|` (use `sed -E`). A bare `cat > file` with no stdin
  blocks until timeout: write edit scripts with the Write tool.

## 5. Decisions made

- **Every typed result shared by CLI and UI lives in `models/`**;
  `DownloadSelection` stays in `quality.py` (only the soulseek package
  reads it); `RenameResult` stays in `metadata_service.py` (moving it
  was not asked). Promoted to CLAUDE.md as a standing rule.
- **Detail rows stay `{track_id, reason, message}` dicts**, matching
  `RenameResult.details`; typing them would touch every formatter and
  the retry panel for no behaviour gain.
- **`ScanAndMatchResult` nests** `scan` and `match` instead of
  flattening the seven fields.
- **`_tag_one_track` is a generator**, to keep the skip-then-fail
  counting exact (HISTORY §155).

## 6. Blockers

None.

## 7. Files in progress

None. S14 is complete.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's own decision (carried):** keep or discard `./slskd-data`
(HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists, S7's
drift Scan, S8's Reject-then-Scan and failure reason, S9 part 2's
mistyped Client ID → Cancel, S11's Scan summary / Docker-stopped
Download / Qt warning in `seeker.log` / app menu "Seeker", S12's
slskd-stopped outage (CLI exit 1; Dashboard, Downloads, tray once;
cleared within ~20 s of Start slskd), S14's playlist Download with one
failing track (warning notice naming it). S14 part 2 adds: Tag playlist
and Fix missing cover art on a real playlist show the same summaries
and notices as before.

## 9. Open questions

- **CI-only flake:** `test_download_button_disabled_with_no_playlist_selected`
  (run `36758864929` attempt 1). Asserts after a bare `qtbot.wait(50)`;
  UNVERIFIED guess: a timer-driven render enabling the button. S18?
- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
  S18?
- Settings shows results and rejections on status labels, not notices:
  S29 (Duplicates' fingerprint result too, see §4).
- S15 (CLI): print `download`'s failed tracks with their reasons, as
  the Dashboard does? Catch `httpx.HTTPStatusError` too? Should
  `printable()` strip bidi controls, and `downloads status` print
  failure reasons?
- S19 or S29: `DestinationDialog`'s unchecked "Remember this" drops the
  typed subfolder. S29: should a rejection be undoable?
- `_activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the enqueued transfer
  id is never recorded, so the next cascade re-requests it. S17 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md`,
`main_window.py` or `test_ui_smoke.py`; `grep -n`, then a range.
pytest: summary line plus named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

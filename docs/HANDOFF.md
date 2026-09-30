# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S16 close-out commit (HISTORY §158, session plan,
  this handoff). Tree clean apart from the untracked `Claude
  outputs/`.
- **Local pytest** (2026-09-30): `1556 passed, 1 skipped, 9 warnings`
  (X9 Pro mounted; per-commit counts in §158).
- **`mypy --strict src/`:** clean, 120 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** recorded by the follow-up commit after the close-out push.

## 2. Where we are

S1–S16 ticked. **Next: S17**, splitting `download_service.py` (BRIEF
§17, split point after §17.1). Then S18.

## 3. Session report (S16 part 2)

Evidence for every line is in HISTORY §158.
- `b70d270` §16.3: legacy path migrations and their tests go.
- `0d3647b` §16.4: client Sharing getters; one status GET per refresh.
- `a8be33a` §16.4: `add_location_to_share` as phases, D (24) → A (2).
- `a83a909` §16.4: `TransferStatus.exception`; one GET per rejection.
- `450b25d` §16.5: `library/audio_quality.py` (refactor).
- `bf95b33` §16.6: chromaprint context manager; NULL context raises.

## 4. Key context

- **For S17:** radon D-or-worse in `src/` is 3:
  `DownloadService._retry_locked_request` D (24) (S17's file),
  `_insert_slskd_share_directory` D (26), `_decide_next_step` D (21).
  `_classify_failed_transfer` is now a `@staticmethod` taking a
  `TransferStatus`; fakes of `get_download_status` must return
  `TransferStatus(..., exception=...)` (`FakeSoulseekClient` in
  `test_download_service.py` reads it from `exceptions=`).
- **slskd REST:** Sharing's calls go through `SoulseekClient`; a 401
  there raises `soulseek.client.SlskdUnauthorizedError`.
  `docker_setup` still calls slskd directly for health and login
  checks (not in §16's scope).
- **Test gotcha:** proving something is freed while a traceback is
  alive needs `pytest.raises(...) as raised`; the unnamed form drops
  it at once and hides a `__del__`-only cleanup (§158).
- Carried: `_fix_one_track_art` (C, 15) mutates the shared
  `FixArtResult`; `DuplicateService.delete_local_files` and
  `TrackMatcher.generate_match_report` still return dicts.
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin ~2.7 points (floor 89). Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; never touch slskd or real data;
  `config.*()` are functions (tests use `monkeypatch.setenv`). Outage
  state has one writer (`_trigger_backend_poll`).
  `RETRYING_IN_BACKGROUND`, not `RETRYING`.
- **Shell:** zsh `echo ======` and unquoted `--include=*.py` fail;
  BSD `sed` lacks `\b`/`\|`; write edit scripts with the Write tool.

## 5. Decisions made

- **`quality_tier_for_format` lives in `audio_formats.py`**, not
  `soulseek/quality.py`: both rankers import it, and `library/` must
  not import from `soulseek/`.
- **The client's Sharing getters return raw JSON**; `sharing_service`
  owns the shapes.
- **`get_reconciliation` requires the status**: an optional argument
  would let the double GET come back silently.
- **The chromaprint context is allocated in `__enter__`**, so a
  wrapper that is never entered holds nothing.
- Carried: help text's "Roadmap item" strings wait for S24.

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
`seeker.log`, app menu "Seeker"; S12 slskd-stopped outage (CLI exit 1;
Dashboard, Downloads, tray once; clears ~20 s after Start slskd); S14
one-failing-track Download notice, Tag and Fix cover art summaries;
S15 a real `seeker downloads review` prompts as before.

## 9. Open questions

- **CI-only flake:** `test_download_button_disabled_with_no_playlist_selected`
  (run `36758864929` attempt 1). Asserts after a bare `qtbot.wait(50)`;
  UNVERIFIED guess: a timer-driven render enabling the button. S18?
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
- `_activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the enqueued transfer
  id is never recorded, so the next cascade re-requests it. S17 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md`,
`main_window.py` or `test_ui_smoke.py`; `grep -n`, then a range.
pytest: summary line plus named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

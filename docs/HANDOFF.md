# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S16 part-1 close-out commit (HISTORY §157, session
  plan, this handoff). Tree clean apart from the untracked `Claude
  outputs/`.
- **Local pytest** (2026-09-30): `1557 passed, 1 skipped, 9 warnings`
  (X9 Pro mounted). 1559 → 1557 is `format_speed`'s two tests,
  deleted with it.
- **`mypy --strict src/`:** clean, 119 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the handoff-CI commit that follows this one.

## 2. Where we are

S1–S15 ticked; **S16 stopped at its split point** (§16.1–§16.2 done,
marked ◐ in the session plan). **Next: S16 part 2** — §16.3 legacy
path migrations, §16.4 `SoulseekClient` getters + Sharing phases +
one status GET, §16.5 `library/audio_quality.py`, §16.6 the
fingerprinter as a context manager. Then S17.

## 3. Session report (S16 part 1)

Evidence for every line is in HISTORY §157.
- `05f3349` §16.1: repositories take no `Database`; `SpotifySyncService`
  receives its repositories.
- `c13cace` §16.2: dead code deleted (incl. `delete_missing`, not in
  the brief); four test-only helpers leave `src/`; PIE790, RSE102,
  FURB161 gated.

## 4. Key context

- **For S16 part 2:** radon D-or-worse in `src/` is 4:
  `_insert_slskd_share_directory` D (26),
  `SharingService.add_location_to_share` D (24, §16.4 targets it),
  `DownloadService._retry_locked_request` D (24), `_decide_next_step`
  D (21). vulture/A.9 results are in §157; A.9 is ~50 lines of
  `tokenize` + `ast`, re-created from BRIEF A.9. Repositories are now built bare (`TrackRepository()`); a
  test seeding one playlist track uses `tests/db_seed.
  add_playlist_track` (S18's `tests/fakes.py` may absorb it).
  Carried from S14: `_fix_one_track_art` (C, 15) still mutates the
  shared `FixArtResult`; still dicts, not in the brief:
  `DuplicateService.delete_local_files`,
  `TrackMatcher.generate_match_report`.
- **CLI shape** (S15): see HISTORY §156; every handler takes
  `(application, parsed)`.
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin ~2.7 points (floor 89). Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; never touch slskd or real data;
  `config.*()` are functions (tests use `monkeypatch.setenv`). Outage
  state has one writer (`_trigger_backend_poll`).
  `RETRYING_IN_BACKGROUND`, not `RETRYING`.
- **Shell:** zsh `echo ======` and unquoted `--include=*.py` fail;
  BSD `sed` lacks `\b`/`\|` (`sed -E`); a `cat > file` with no stdin
  blocks: write edit scripts with the Write tool.

## 5. Decisions made

- **`delete_missing` deleted, not kept for its tests**: the scanner
  deletes by id since S7; its tests moved onto `delete_by_ids`, the
  path the scanner actually takes past SQLite's variable limit.
- **`format_speed` deleted with its tests** rather than moved: the
  tests exercised nothing but the function itself.
- **PIE790, RSE102, FURB161 selected by exact code** so the §16.2
  fixes stay fixed (explicit-preview-rules; see CLAUDE.md).
- **Result-dataclass fields only tests read stay** (`index_failed`,
  `tagged_art_rarely_supported_format`): the §16 acceptance excludes
  dataclass fields.
- Carried: help text's "Roadmap item" strings wait for S24.

## 6. Blockers

None.

## 7. Files in progress

None mid-edit. S16 stopped cleanly at its split point; §16.3–§16.6
not started.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's own decision (carried):** keep or discard `./slskd-data`
(HISTORY §140).

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
- CLI (not in §15, carried): print `download`'s failed tracks with
  their reasons, as the Dashboard does? Catch `httpx.HTTPStatusError`
  too? Should `printable()` strip bidi controls, and `downloads status`
  print failure reasons? The one-by-one upgrade review prints
  `apply_upgrade_decision`'s message raw where `--all` uses
  `printable()`.
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

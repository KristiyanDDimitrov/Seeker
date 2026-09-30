# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S15 close-out commit (HISTORY §156, session plan,
  this handoff). Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (2026-09-30): `1559 passed, 1 skipped, 9 warnings`
  (X9 Pro mounted; S15 adds 21 tests).
- **`mypy --strict src/`:** clean, 119 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the handoff-CI commit that follows this one.

## 2. Where we are

S1–S15 ticked. **Next: S16** (service-layer cleanup and dead code,
BRIEF §16; split point after §16.2). Then S17.

## 3. Session report (S15)

Evidence for every line is in HISTORY §156.
- `c9bc0f0` §15.1 fix (behaviour): a command group needs its subcommand.
- `cb01c8d` tests: CLI rename/tag/fix-art/routing output pinned.
- `381d8b8` §15.1: one handler per subcommand (`handle_library` F 54 → gone).
- `3726703` §15.4 fix (behaviour): `--help` never opens the database.
- `11ac23f` §15.2: `seeker/formatting.py`; layering sweep test.
- `6e0596b` §15.3: no `print`/`input` in a service; poll trace is
  `logger.debug`.

## 4. Key context

- **For S16:** radon D-or-worse in `src/` is now 4:
  `_insert_slskd_share_directory` D (26),
  `SharingService.add_location_to_share` D (24),
  `DownloadService._retry_locked_request` D (24), `_decide_next_step`
  D (21). Carried from S14: `_fix_one_track_art` (C, 15) still mutates
  the shared `FixArtResult` it is passed (`TagResult.record` is the
  model); still dicts, not in the brief:
  `DuplicateService.delete_local_files`,
  `TrackMatcher.generate_match_report`;
  `DownloadRequestRepository.get_active_for_track` has no caller.
- **CLI shape now:** `cli.parse_args` (exits for help/usage/no
  command) → `main()` builds `Application` → `cli.dispatch`. Tests use
  `cli.run(app, argv)`, which composes the two. A new subcommand is a
  subparser plus `set_defaults(handler=handle_<group>_<name>)`, and
  every handler takes `(application, parsed)`. A test that
  monkeypatches `cli.handle_x` still works: `build_parser` runs inside
  `run`, after the patch.
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

- **`seeker playlists` stays an optional group**: its no-subcommand
  behaviour is the listing. The other three groups became required;
  a bare `seeker` still prints full help, exit 0 (as `git` does).
- **`ui/formatting.py` moved whole, no re-export** (the brief allowed
  either): every function in it was pure, so one home beats an alias.
- **`SEEKER_DEBUG_POLL` is read once at startup**, not per call:
  logging levels are an entry-point concern, like handlers. Promoted
  to CLAUDE.md with the "no print or input in a service" rule.
- **Help text still carries "Roadmap item R3.1/R3.4" and "(roadmap
  item 56)"** (`downloads review --all`, `library scan --match`):
  left for S24, since §15's acceptance is byte-identical help.

## 6. Blockers

None.

## 7. Files in progress

None. S15 is complete.

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

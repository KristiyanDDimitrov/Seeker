# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S10 close-out commit (HISTORY §149, S10 ticked,
  CLAUDE.md CI rule, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1460 passed, 1 skipped, 6 warnings in 90.27s`
  (X9 Pro mounted; S10 adds no tests).
- **`mypy --strict src/`:** clean, 111 files. **`ruff check src
  tests`:** 0 findings, now including E301–E306, G201 and TRY400.
- **CI:** `bf3cf9e` → run `36697998670`, **success** (branch coverage
  91.47 %, floor 89). Close-out `c722bf1` → run `36698538324`,
  **success**, `1432 passed, 29 skipped`, 91.46 %.

## 2. Where we are

S1–S10 ticked. **Next: S11, readable errors, logs that catch
everything, and Dashboard outcomes that stay readable (BRIEF §11).**

## 3. Session report (S10)

Evidence for all of these is in HISTORY §149.
- `bd01d15` §10.1: workflow permissions, concurrency, timeout,
  SHA-pinned actions, uv cache, `--locked`, branch coverage floor 89.
- `79540a1` §10.2: `.github/dependabot.yml` (weekly: actions and uv),
  `SECURITY.md`.
- `8852ca8` §10.3: `shiboken6` declared; patch-only lock bumps (8).
- `bf3cf9e` §10.4: E301–E306, G201, TRY400; 22 findings fixed.
- Close-out: §149, S10 ticked, CLAUDE.md rule, this handoff.

## 4. Key context

- **Your HISTORY entry is §150**, the last in `docs/history/121-150.md`.
  §151 opens `151-180.md`; `docs/history/README.md` says how.
- **S11 note:** `logger.exception` is now lint-enforced. Inside an
  `except`, `logger.error(...)` without a traceback fails TRY400, and
  `error(..., exc_info=True)` fails G201. This matters for §11's
  logging work.
- **Coverage margin is about 2.5 points** (CI 91.47 %, floor 89); a
  large untested module can trip it. CI counts fewer statements than a
  local run (10,599 vs 10,844), cause not investigated.
- **Run deptry with `uv run --with deptry deptry src`**, not bare
  `uvx`: bare `uvx` cannot see the project's environment and reports
  58 false import-name issues.
- **Held-back minor upgrades** (listed in §149) and the action majors
  will arrive as Dependabot PRs; nothing merges them automatically.
- **Carried:** never `QLabel(...)` or `QMessageBox.question(...)` in
  `ui/` (use `PlainLabel`/`RichLabel` and `plain_text.*`); fakes of
  `connect_spotify` and friends accept `cancel=`;
  `from PySide6.QtGui import Qt` for `Qt.convertFromPlainText`. Three
  `LibraryLocationNotFoundError` classes, plus
  `AuthorizationCancelledError`, go into S13's hierarchy;
  `SoulseekDownloadError` takes `reason=`; one extra GET per failed
  transfer (S22); never touch slskd or real data;
  `config.spotify_client_id()` etc. are functions (tests use
  `monkeypatch.setenv`).
- **zsh:** `echo ======` fails (use `'---'`); BSD `sed` lacks `\b`.

## 5. Decisions made

- **Kept `runs-on: macos-26`**, for reproducibility: a runner-image
  change arrives as a reviewed commit. The comment now says this.
- **Actions pinned on their current majors** (checkout v5.1.0, setup-uv
  v7.6.0), not bumped to v7/v10. Dependabot proposes the majors
  separately, so this row changes no action behaviour.
- **Divergence from the brief (§10.4):** listed E301–E306 by exact code
  instead of `extend-select = ["E30"]`, which selects nothing under
  `explicit-preview-rules`. Also converted a fifth call (TRY400,
  `duplicate_service.py`) that the brief's count of four missed.
- **Divergence (§10.3):** stopped the full upgrade as instructed,
  then applied the eight patch-only bumps with `--upgrade-package`.
- **Skills:** `ci-cd-pipeline-builder`'s validation checklist
  (actionlint); `dependency-auditor`'s advice to use live `pip-audit`.

## 6. Blockers

None.

## 7. Files in progress

None. S10 is complete.

## 8. Waiting on Kris

**Approval gates:** **new:** turn on private vulnerability reporting
(repo Settings → Security), without which `SECURITY.md`'s link leads
nowhere; S21 package regrouping; S30 visual direction; S39 bundle
identifier; S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed on a copy,
§144 and §145). S10 changes no schema.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists
check, S7's drift Scan, S8's Reject-then-Scan and failure reason on
Downloads, S9 part 2's Connect with a mistyped Client ID, then Cancel,
then Connect with the right one.

## 9. Open questions

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S11 or S20?
- The late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task; a 0.3 s fake delay reproduces it (§148
  addendum). S11 or S18? CLAUDE.md items 63, 70, 125 stay open.
- Settings → Destinations shows a rejected subfolder on its
  `status_label`, not an `InlineNotice`. S11.
- S15 (CLI): should `printable()` strip bidi controls, and should
  `seeker downloads status` print failure reasons?
- S19 or S29: `DestinationDialog`'s unchecked "Remember this" drops the
  typed subfolder. S29: should a rejection be undoable?

---

**Read discipline:** never read a whole `docs/history/*.md`,
`main_window.py` or `test_ui_smoke.py`; `grep -n`, then a range.
pytest: summary line plus named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

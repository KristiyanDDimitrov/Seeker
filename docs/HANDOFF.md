# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S12 part 2 close-out commit (HISTORY §152, CLAUDE.md,
  session plan, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1516 passed, 1 skipped, 6 warnings`
  (X9 Pro mounted; S12 part 2 adds 10 tests).
- **`mypy --strict src/`:** clean, 114 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the line appended below after the push.

## 2. Where we are

S1–S12 ticked. **Next: S13, one exception hierarchy; typed download
states (§13).** Phase F starts: behaviour-neutral refactors only.

## 3. Session report (S12 part 2)

Evidence for both is in HISTORY §152.
- `1b86ebc` §12.5: an empty history seeds the tray's download cutoff
  to now, so a fresh install's first download notifies.
- `c9014cf` §12.3: `ui/slskd_status.py` (`SlskdStatus` on
  `PageContext`, `start_slskd` helper); Dashboard next step first,
  Downloads' outage notice, tray once per outage, cleared on the first
  good poll.

## 4. Key context

- **For S13's hierarchy:** `SlskdUnreachableError`
  (`soulseek/client.py`), `SlskdStartRefusedError` and
  `SlskdBringUpError` (`docker_setup.py`), three
  `LibraryLocationNotFoundError`s and `AuthorizationCancelledError`
  all subclass `RuntimeError` today. `cli.run`'s caught tuple becomes
  `SeekerError` there. `MainWindow._trigger_backend_poll`'s `poll()`
  closure catches `SlskdUnreachableError` by type; keep it narrower
  than any new base class.
- **Outage state has one writer.** Only `_trigger_backend_poll` calls
  `SlskdStatus.mark_*`. A second writer (say, a health check) would
  need to keep the edge semantics, or the tray would notify twice.
- **`InlineNotice.action_button` is public now**, so a notice's action
  can be handed to `run_busy_worker`. `BusyActionRegistry.end` restores
  the text from `begin`; with the Dashboard's shared next-step button
  that can show a stale label for up to one 2 s tick (HISTORY §152).
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin about 2.5 points (CI 91.63 %, floor 89). deptry: `uv
  run --with deptry deptry src`. Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; fakes of `connect_spotify`
  accept `cancel=`; `FakeApplication.restart_slskd` has
  `restart_slskd_calls`/`restart_slskd_error`; never touch slskd or
  real data; `config.*()` are functions (tests use
  `monkeypatch.setenv`).
- **zsh:** `echo ======` fails (use `'---'`); BSD `sed` lacks `\b`.

## 5. Decisions made

- **The outage notification bypasses `notify_error`'s cooldown**
  (`TrayController.notify_outage`): the edge already bounds it to once
  per outage, and a cooldown shared with other errors could swallow it.
  It still honours "notify errors".
- **No tray notification on recovery.** The brief asks for "again only
  after a recovery"; read as re-arming. The notices clearing is the
  recovery signal.
- **Start slskd does not clear the outage.** Its success message says
  slskd is starting; the next good poll (at most 20 s) clears it,
  since the container answers only after Compose returns.
- **Other poll errors now show `describe_error` text** in the tray,
  not the fixed "couldn't reach slskd" sentence, which would be wrong
  for them.
- Promoted to CLAUDE.md: the `SlskdStatus` sentence on the outage
  bullet, and `slskd_status.py` in the layout tree.

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
drift Scan, S8's Reject-then-Scan and Downloads failure reason, S9
part 2's mistyped Client ID → Cancel → correct one, S11's Dashboard
Scan summary / Docker-stopped Download message / Qt warning in
`seeker.log` / app menu "Seeker". **S12:** with slskd stopped,
`uv run seeker downloads status` prints the outage sentence and exits
1; in the app, Dashboard and Downloads show it with Start slskd, the
tray notifies once, and a started container clears it within ~20 s.

## 9. Open questions

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
  S18?
- Settings shows results and rejections on status labels, not notices:
  S29.
- `cli.run` catches `httpx.TransportError` but not
  `httpx.HTTPStatusError`. S13 or S15?
- S15 (CLI): should `printable()` strip bidi controls, and should
  `seeker downloads status` print failure reasons?
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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S12 part 1 close-out commit (HISTORY §151, CLAUDE.md,
  session plan, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1506 passed, 1 skipped, 6 warnings`
  (X9 Pro mounted; S12 part 1 adds 9 tests).
- **`mypy --strict src/`:** clean, 113 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see §151's close-out push; the run id is recorded in the
  commit after the close-out, if one was needed.

## 2. Where we are

S1–S11 ticked. **S12 stopped at its split point (after §12.2).** Done:
§12.1, §12.2, §12.4. **Next: S12 part 2, §12.3 (UI) and §12.5
(first-session download notifications).** S12 stays unticked until
then.

## 3. Session report (S12 part 1)

Evidence for all of these is in HISTORY §151.
- `ab23d51` §12.1–§12.2: `SlskdUnreachableError`; the poll aborts on a
  transport error; no locked-retry budget spent.
- `95a344a` §12.4: `seeker downloads status` prints the sentence and
  exits 1.
- `fa4a1e7` §12.2: `Application.restart_slskd()`, refusing through
  `SlskdStartRefusedError`.
- Close-out: §151 (opens `docs/history/151-180.md`), CLAUDE.md, plan,
  this handoff.

## 4. Key context

- **Plan for §12.3.** `run_worker`'s `on_error` receives only text, so
  do not match on the message. In `MainWindow._trigger_backend_poll`,
  run a worker closure that calls `poll_downloads` and *returns* the
  caught `SlskdUnreachableError` (or its message). `on_finished` then
  branches on it. Shared outage state belongs on `PageContext` (a
  small QObject with `changed`, like `PlaylistSelection`): MainWindow
  writes it, Dashboard and Downloads read it. Its methods should
  report the edge (returns True only on up→down / down→up) so the tray
  notifies once per outage.
- **Dashboard:** add a `_NextStepFacts` field (say
  `slskd_unreachable_message: str | None`) and check it **first** in
  `_decide_next_step`. Add an action key (`"start_slskd"`) to
  `_on_next_step_action`. Connect the status's `changed` signal to
  `_poll_next_step` so the notice appears at once, not on the next 2 s
  tick.
- **Downloads** has no notice or status label yet. Give it a
  persistent outage `InlineNotice` driven by the status, plus a
  `FeedbackTarget` (`status_label` + `notice`) for the Start slskd
  outcome. The action reports on the page it was started from (the
  CLAUDE.md rule).
- **Start slskd** runs `application.restart_slskd` on a worker. Its
  `SlskdStartRefusedError` / `SlskdBringUpError` messages are already
  sentences, and `describe_error` keeps them.
- **The old `on_poll_error` tray text** ("Seeker couldn't reach slskd
  — check that it's running.") now fires during an outage, still
  rate-limited by `TrayController.notify_error`'s cooldown. §12.3
  replaces it with the edge-triggered notice and leaves `on_poll_error`
  for errors that are not outages (`describe_error` text).
- **§12.5:** `TrayController.seed_notification_cutoff` /
  `check_for_download_notifications` in `ui/tray.py`. The brief
  already has the fix; keep "seeding in flight" distinct from
  "seeded, empty".
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin about 2.5 points (CI 91.59 %, floor 89). deptry: `uv
  run --with deptry deptry src`. Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; fakes of `connect_spotify`
  accept `cancel=`; three `LibraryLocationNotFoundError`s,
  `AuthorizationCancelledError` and now `SlskdUnreachableError` /
  `SlskdStartRefusedError` go into S13's hierarchy (and `cli.run`'s
  caught tuple becomes `SeekerError` there); never touch slskd or real
  data; `config.*()` are functions (tests use `monkeypatch.setenv`).
- **zsh:** `echo ======` fails (use `'---'`); BSD `sed` lacks `\b`.
- **Tooling:** the auto-mode Bash safety check failed transiently
  several times this session; the Read tool worked throughout.

## 5. Decisions made

- **A transport error to slskd is an outage, including a timeout.**
  One refusal aborts the whole poll: every later request would fail the
  same way. Promoted to CLAUDE.md.
- **Beyond the brief:** a locked retry no longer spends its budget when
  slskd itself is unreachable. Otherwise, an outage longer than the
  backoff sum could mark locked files `unavailable`.
- **`restart_slskd` refuses rather than guesses** when the share cannot
  be read, when the container is not Seeker's (`is_self_managed`), when
  Docker is down, or when no login is saved. It does not open Docker
  Desktop. Settings → Connection stays the place that asks which
  location to share. Promoted to CLAUDE.md (the bring-up bullet).
- **Stopped at the split point** because of context budget. §12.4 (a
  one-line catch) was pulled forward, since without it the §12.2 change
  would print a traceback in the CLI.
- **Skills:** `observability-designer` again targets server fleets;
  what applied was alert discipline: edge-triggered, auto-resolving,
  actionable (a Start slskd action), with dependent failures suppressed
  (no per-request "failed" during an outage).

## 6. Blockers

None.

## 7. Files in progress

None mid-edit. S12 part 2 is untouched: `ui/main_window.py`
(`_trigger_backend_poll`), `ui/pages/context.py`,
`ui/pages/dashboard_page.py`, `ui/pages/downloads_page.py` and
`ui/tray.py` are all still at HEAD.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).
Private vulnerability reporting: **done** (confirmed enabled).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).
S12 changes no schema.

**Kris's own decision (carried):** keep or discard `./slskd-data`
(HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists, S7's
drift Scan, S8's Reject-then-Scan and Downloads failure reason, S9
part 2's mistyped Client ID → Cancel → correct one, S11's Dashboard
Scan summary / Docker-stopped Download message / Qt warning in
`seeker.log` / app menu "Seeker". **New (S12):** with slskd stopped,
`uv run seeker downloads status` prints the outage sentence and exits
1 (`echo $?`).

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

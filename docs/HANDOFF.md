# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S11 close-out commit (HISTORY §150, S11 ticked,
  CLAUDE.md rules, this handoff). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-09-30): `1497 passed, 1 skipped, 6 warnings`
  (X9 Pro mounted; S11 adds 37 tests).
- **`mypy --strict src/`:** clean, 113 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the "CI" line at the end of this file (recorded after
  the push).

## 2. Where we are

S1–S11 ticked. **Next: S12, say when slskd is down; first-session
download notifications (BRIEF §12).**

## 3. Session report (S11)

Evidence for all of these is in HISTORY §150.
- `bf1c2f3` §11.1: `seeker/error_text.py`, `describe_error()`.
- `2eadc96` §11.2: workers emit it; render bugs show a log pointer.
- `f0b9b14` §11.3: `ui/error_hooks.py`: excepthooks, Qt message handler.
- `9499643` §11.4: app name, display name, version.
- `87968db` §11.4: typed `_OpenWindows` holder (refactor).
- `a7bfdc2` §11.5: CLI catches transport and database errors.
- `471b301` §11.6: Dashboard outcomes on `dashboard_notice` via
  `FeedbackTarget`; cross-page Tag reports on the Dashboard.
- Close-out: §150, S11 ticked, CLAUDE.md, this handoff.

## 4. Key context

- **Your HISTORY entry is §151, and it opens a new file,
  `docs/history/151-180.md`.** `121-150.md` is full. Add a section for
  the new file in `docs/history/README.md` (its "Adding an entry"
  paragraph says how), and change that paragraph's "last file" name.
- **For S12:** `describe_error` already names slskd for any transport
  error to a non-Spotify, non-GitHub host and asks "Is Docker
  running?". Reuse it rather than writing new slskd-down text. The
  backend poll's `on_poll_error` (MainWindow `_trigger_backend_poll`)
  still ignores the message and posts its own tray text.
- **`FeedbackTarget` (`ui/notice.py`)** is the pattern for any page
  whose action may be started elsewhere: `show_progress` / 
  `show_outcome` / `show_error`. `DashboardPage.feedback` exists; S19
  moving Dashboard flows should keep using it.
- **Testing an excepthook** needs `@pytest.mark.qt_no_exception_capture`
  (pytest-qt replaces `sys.excepthook` per test). See
  `tests/test_error_hooks.py`.
- **A false lead:** `matcher.py` ~line 396's `"auto_count"` dict is
  `generate_match_report`, not `match_all`; `match_all` returns
  `auto`/`needs_review`/`unmatched` counts.
- **Carried:** `logger.exception` is lint-enforced (TRY400, G201).
  Coverage margin about 2.5 points (CI 91.47 %, floor 89). deptry: `uv
  run --with deptry deptry src`. Never `QLabel(...)` or
  `QMessageBox.question(...)` in `ui/`; fakes of `connect_spotify`
  accept `cancel=`; three `LibraryLocationNotFoundError`s plus
  `AuthorizationCancelledError` go into S13's hierarchy (and
  `cli.run`'s caught tuple becomes `SeekerError` there, §11.5);
  `SoulseekDownloadError` takes `reason=`; never touch slskd or real
  data; `config.*()` are functions (tests use `monkeypatch.setenv`).
- **zsh:** `echo ======` fails (use `'---'`); BSD `sed` lacks `\b`.

## 5. Decisions made

- **Divergence (§11.1):** `describe_error` takes a keyword-only
  `details_hint`, so the CLI (no log folder) prints "Details: <raw
  message>" where the UI points at Help → Open Log Folder.
- **Builtin programming errors hide their raw text** (`KeyError`,
  `TypeError`, …): none is raised on purpose in `src/` (grep), so on
  screen one is always a bug; other builtins (`ValueError`,
  `RuntimeError`) keep domain messages.
- **Only one Qt message dropped** (offscreen `propagateSizeHints`,
  reproduced); the offscreen font-alias warning stays logged.
- **Qt warnings go to the log, not the terminal**, in dev runs too.
- **Match now reports counts on the notice** (it showed nothing).
- **Skills:** `observability-designer` is aimed at server fleets
  (SLOs, dashboards, alert routing); only its log-level discipline
  applied (uncaught → CRITICAL, nothing unlogged).
- Promoted to CLAUDE.md: `describe_error` for all failure text;
  `FeedbackTarget` of the originating page; no `status_label` on a
  timer-driven worker; the slot-excepthook fact.

## 6. Blockers

None.

## 7. Files in progress

None. S11 is complete.

## 8. Waiting on Kris

**Approval gates:** turn on private vulnerability reporting (repo
Settings → Security) for `SECURITY.md`'s link; S21 package regrouping;
S30 visual direction; S39 bundle identifier; S42 publishing commands;
X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).
S11 changes no schema.

**Kris's own decision (carried):** keep or discard `./slskd-data`
(HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists, S7's
drift Scan, S8's Reject-then-Scan and Downloads failure reason, S9
part 2's mistyped Client ID → Cancel → correct one. **New (S11):**
Scan from the Dashboard and read the summary on the notice; stop
Docker, click Download, read the slskd/Docker message; confirm
`seeker.log` records a Qt warning (any) and the app menu says "Seeker".

## 9. Open questions

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). S20?
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (0.3 s fake delay reproduces it, §148 addendum).
  Not taken in S11 (outside §11's scope); since §11.3 the raise is at
  least logged at CRITICAL. S18?
- Settings shows results and rejections (e.g. a rejected Destinations
  subfolder) on status labels, not notices. No timer wipes them there,
  so it is layout, not data loss: S29.
- `cli.run` catches `httpx.TransportError` but not
  `httpx.HTTPStatusError` (the brief named only the former);
  `describe_error` handles both. S13 or S15?
- S15 (CLI): should `printable()` strip bidi controls, and should
  `seeker downloads status` print failure reasons?
- S19 or S29: `DestinationDialog`'s unchecked "Remember this" drops the
  typed subfolder. S29: should a rejection be undoable?

---

**Read discipline:** never read a whole `docs/history/*.md`,
`main_window.py` or `test_ui_smoke.py`; `grep -n`, then a range.
pytest: summary line plus named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S9 part 3 close-out commit (HISTORY §148, S9 ticked,
  CLAUDE.md rule, this handoff), pushed. Tree clean apart from the
  untracked `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-30): `1460 passed, 1 skipped, 6 warnings in 89.90s`
  (X9 Pro mounted; part 2's 1444 plus 16 new).
- **`mypy --strict src/`:** clean, 111 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** see the follow-up commit recording the run for this push.

## 2. Where we are

S1–S9 ticked. **Next: S10, CI and supply chain (BRIEF §10).**

## 3. Session report (S9 part 3)

Reds and evidence are in HISTORY §148.
- `2f1e866` §9.7: `ui/plain_text.py` (`PlainLabel`, `RichLabel`,
  `plain_tooltip`, `question`/`information`/`warning`); all 81 labels
  converted; 8 dynamic tooltips wrapped; the update check escaped;
  `cli.printable()`. Three `ast` sweeps in `tests/test_plain_text.py`.
- `9e3c6ea` review fix: `Retry-After: ²` crashed §9.8's parser.
- `bfd0248` review follow-up: a fourth sweep for hand-built
  `QMessageBox(...)`; two docstrings reflowed.
- Close-out: §148, S9 ticked, CLAUDE.md rule, this handoff.

## 4. Key context

- **Your HISTORY entry is §149**: `docs/history/121-150.md` plus its
  README line. §150 is this file's last; §151 opens `151-180.md`
  (`docs/history/README.md` says how).
- **New UI rule (CLAUDE.md):** never `QLabel(...)` in `ui/`; use
  `PlainLabel`/`RichLabel`. Never `QMessageBox.question(...)`; use
  `plain_text.question(...)`. Tests that fake a confirmation patch
  `plain_text.question`/`information`, not `QMessageBox`. A dynamic
  tooltip's test compares against `plain_tooltip(expected)` or decodes
  it with `QTextDocument.setHtml(...).toPlainText()`.
- **`from PySide6.QtGui import Qt`** is needed for
  `Qt.convertFromPlainText` under mypy (QtCore's `Qt` stub lacks it).
- **`connect_spotify` and friends take `cancel=`**: any new fake of
  `connect_spotify`, `get_valid_token`, `_authorize` or
  `serve_until_callback` must accept it (`**kwargs` is fine).
- **Carried:** nested destination subfolders are real data;
  `_repoint_or_clear_match` drops `confirmed_at` (unowned); the
  `platformdirs.user_data_dir` / `slskd-data` test hazard; three
  `LibraryLocationNotFoundError` classes (S13; add
  `AuthorizationCancelledError` to that hierarchy too);
  `SoulseekDownloadError` takes `reason=` (S13 keeps it); one extra GET
  per failed transfer (S22); never touch slskd or real data;
  `config.spotify_client_id()` etc. are functions; tests use
  `monkeypatch.setenv`.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`. BSD `sed`
  has no `\b`; use `perl -pi -e`.

## 5. Decisions made

- **`ast` sweeps, not a runtime widget sweep**, for §9.7: labels built
  at render time (table cells, notices) are covered, and a new file
  is covered without anyone registering it.
- **`plain_tooltip` converts, it does not just escape**: Qt's rich-text
  guess treats an early `&lt;` as HTML, so escaping alone renders
  inconsistently (HISTORY §148).
- **`printable()` strips C0/C1 only**, as the brief scoped it; bidi
  controls are recorded in §148 as a known, low-risk gap.
- **Skill use:** `adversarial-reviewer` ran once over all of S9, as
  planned; two findings fixed, three recorded.

## 6. Blockers

None.

## 7. Files in progress

None. S9 is complete.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Next launch will migrate the real DB** (S8 part 1 and §8.3, both
rehearsed on a copy, §144 and §145). S9 changes no schema.

**Behaviour you may notice:** tooltips built from data (a failure
reason, a runner-up filename) now wrap like rich text instead of
running on one line.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists
check, S7's drift Scan, S8's Reject-then-Scan and failure reason on
Downloads, S9 part 2's Connect with a mistyped Client ID, then Cancel,
then Connect with the right one.

## 9. Open questions

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait; the worker holds port 8888 and the token lock for up to 300 s.
  Cancel on the widget's destruction? S11 or S20.
- Should `printable()` also strip bidi controls? Cheap; S15 (CLI) could
  take it.
- **Carried from S7:** `DestinationDialog`'s unchecked "Remember this
  for this playlist" drops the typed subfolder. S19 or S29?
- Settings → Destinations shows a rejected subfolder on its
  `status_label`, not an `InlineNotice`. S11.
- CLAUDE.md items 63, 70 and 125 remain open. Which row owns the
  late-worker defect (S11 or S18)?
- Should a rejection be undoable (a "Rejected" list on Review)? S29.
- Should `seeker downloads status` print failure reasons? S15.

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

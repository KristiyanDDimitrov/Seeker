# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S9 part 2 close-out commit (HISTORY §147, S9 row
  annotated, this handoff), pushed. Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-30): `1444 passed, 1 skipped, 6 warnings in 88.98s`
  (X9 Pro mounted; part 1's 1436 plus 8 new).
- **`mypy --strict src/`:** clean, 110 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** push `bbcdeee` → run `36686689743`, **success**.

## 2. Where we are

S1–S8 ticked. S9 parts 1 and 2 done. **Next: S9 part 3, §9.7 (peer
strings render as text), then the S9-wide `adversarial-reviewer` pass,
then tick S9.** Then S10.

## 3. Session report (S9 part 2)

Reds and the HEAD probe are in HISTORY §147.
- `35b14a7` §9.5: the callback page tells cancelled/failed apart from
  complete, with no-store/CSP/no-referrer headers on every response;
  `serve_until_callback(cancel=)`; `SpotifyAuthorizationWait` (Cancel,
  hint, trigger kept disabled) shared by the wizard and Settings.
- Close-out: §147, S9 row annotated, this handoff.

## 4. Key context

- **Your HISTORY entry is §148**: `docs/history/121-150.md` plus its
  README line.
- **§9.7 survey, done this session (not yet acted on):** 81 `QLabel(`
  constructions across 17 files in `src/seeker/ui/`; 26 start empty
  (dynamic by construction). Only deliberately rich labels set a format
  today (`dialogs.py` About, `pages/static_pages.py`,
  `pages/sharing_page.py`'s framing label, the update-check box in
  `main_window.py` ~line 1348). Everything else is `AutoText`.
  Recommended shape: a runtime sweep test over the constructed windows
  (MainWindow's pages, SettingsPage, the wizard) that fails on any
  `QLabel` left at `AutoText`, then explicit formats everywhere. Labels
  `QFormLayout.addRow("literal", w)` creates are `AutoText` and never
  hold dynamic text; a sweep that excludes them must say why in a
  comment (working agreement 5).
- **§9.7 targets already located:** `InlineNotice`'s `_message_label`
  (`ui/notice.py` ~line 70); the update-check RichText `QMessageBox`
  (`main_window.py` `_on_update_check_finished`, `latest_version` and
  `release_url` unescaped); Downloads' Status tooltip (slskd's
  `failure_reason`); the wizard's `soulseek_status_label.setToolTip(
  result.detail)` (`wizard.py` ~lines 625 and 661, slskd log text);
  Review's runner-up filename tooltip; `cli.handle_search` prints
  `file.username`/`file.filename` raw.
- **`connect_spotify` and friends now take `cancel=`**: any new fake of
  `connect_spotify`, `get_valid_token`, `_authorize` or
  `serve_until_callback` must accept it (`**kwargs` is fine).
- **Carried:** nested destination subfolders are real data;
  `_repoint_or_clear_match` drops `confirmed_at` (unowned); the
  `platformdirs.user_data_dir` / `slskd-data` test hazard; three
  `LibraryLocationNotFoundError` classes (S13; add
  `AuthorizationCancelledError` to that hierarchy too); `SoulseekDownloadError`
  takes `reason=` (S13 keeps it); one extra GET per failed transfer
  (S22); never touch slskd or real data; `config.spotify_client_id()`
  etc. are functions; tests use `monkeypatch.setenv`.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`.

## 5. Decisions made

- **Stopped after §9.5 at an item boundary**: §9.7 touches ~17 UI files
  plus the CLI and needs a sweep test; it would not fit alongside a
  close-out in the remaining budget.
- **The cancel is a `threading.Event` passed down**, not a method on the
  auth manager: `Application` replaces the manager on every connect.
- **The cancel raises `AuthorizationCancelledError`** rather than a 5th
  tuple element, so `serve_until_callback`'s return shape is unchanged
  and the exception unwinds `_TOKEN_LOCK` on its own.
- **`SpotifyAuthorizationWait` does not use `run_worker`'s `button=`**
  (HISTORY §145 rule): it owns the trigger's enabled state.
- **Skill divergence:** `adversarial-reviewer` deferred to S9 part 3 so
  it reviews all of S9 once.

## 6. Blockers

None.

## 7. Files in progress

None mid-edit. Row state: `§9.7` not started.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Next launch will migrate the real DB** (S8 part 1 and §8.3, both
rehearsed on a copy, §144 and §145). S9 changes no schema.

**Behaviour you may notice:** Connect (wizard) and Re-authorize
(Settings) now show "Waiting for approval in your browser…" with a
Cancel button; the browser tab after a Cancel on Spotify's page says
the authorization was cancelled.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists
check, S7's drift Scan, S8's Reject-then-Scan and failure reason on
Downloads. New: a real Connect with a mistyped Client ID, then Cancel,
then Connect with the right one.

## 9. Open questions

- **New:** closing the wizard or Settings mid-wait does not cancel it;
  the worker holds port 8888 and the token lock for up to 300 s.
  Cancel on the widget's destruction? S11 or S20.
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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S9 part 1 close-out commit (HISTORY §146, three
  CLAUDE.md rules, S9 row annotated, this handoff), pushed. Tree clean
  apart from the untracked `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-30): `1436 passed, 1 skipped, 6 warnings in 114.91s`
  (X9 Pro mounted; S8's 1397 plus 39 new).
- **`mypy --strict src/`:** clean, 109 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** push `59af866` → run `36684593551`, **success**.

## 2. Where we are

S1–S8 ticked. **S9 part 1 done; next: S9 part 2, §9.5 (OAuth callback
page and a cancellable wait) and §9.7 (peer strings render as text)**.
Both are UI work, and each is about one session's worth. Then S10.

## 3. Session report (S9 part 1)

Every red and the GUI `.env` probe are in HISTORY §146.
- `2dab02d` §9.1: credential temp file 0600 from `os.open(O_EXCL)`,
  fsync, dir fsync, cleanup on failure.
- `d5caae5` §9.2: process-wide token lock plus a re-read under it.
- `653ce64` §9.3: slskd username/transfer id/search id percent-encoded.
- `5ea0ea7` §9.4: album art only from `*.scdn.co`/`*.spotifycdn.com`
  over https; release link only into this repo, else the releases page.
- `207a44e` §9.8: 429 with an empty body or an HTTP-date Retry-After.
- `01f96c7` §9.6: generic, type-checked `load_config`; `.env` loaded by
  the entry points, not at import.
- Close-out: §146, CLAUDE.md rules, S9 row annotated.

## 4. Key context

- **Your HISTORY entry is §147**: `docs/history/121-150.md` plus its
  README line.
- **§9.7 must cover the update-check dialog.** `main_window.py`
  `_on_update_check_finished` (around line 1340) builds a **RichText**
  `QMessageBox` from `result.latest_version` (GitHub's `tag_name`) and
  `result.release_url` without `html.escape`. The URL is now
  prefix-checked (§9.4) but can still hold a `"`; escape both.
- **§9.7, carried from S8:** Downloads' Status cell and its tooltip
  show slskd's `failure_reason` (peer text). The cell is a plain
  `QTableWidgetItem`; the tooltip auto-detects rich text, so escape it.
- **§9.5 starting points:** `callback_server.serve_until_callback`
  (returns `code, state, error, timed_out`; closes the server itself),
  `SpotifyAuthManager._authorize`, the wizard's
  `_on_connect_spotify_clicked` / `_update_connect_button_state`, and
  Settings' Re-authorize. `_authorize` now runs **inside**
  `_TOKEN_LOCK`: a cancel must release it promptly, or a concurrent
  sync waits the full 300 s.
- **`config.SPOTIFY_CLIENT_ID` etc. no longer exist**: they are
  `config.spotify_client_id()` and so on. Tests use
  `monkeypatch.setenv`/`delenv` (CLAUDE.md).
- **`load_config` now drops wrongly typed values** with a warning. A
  new `SeekerConfig` field needs nothing in `load_config`, but its
  annotation must be a plain type or `X | None`.
- **Carried:** nested destination subfolders are real data;
  `_repoint_or_clear_match` drops `confirmed_at` (unowned); the
  `platformdirs.user_data_dir` / `slskd-data` test hazard; three
  `LibraryLocationNotFoundError` classes (S13); `SoulseekDownloadError`
  takes `reason=` (S13 keeps it); one extra GET per failed transfer
  (S22); never touch slskd or real data.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`.

## 5. Decisions made

- **Stopped after §9.6, past the split point**, at an item boundary:
  the context was near the ceiling, and §9.5 and §9.7 are each a
  multi-file UI change.
- **The token lock is module-level, not per manager**: Application
  replaces the manager on every connect, and all share one file.
- **`config.py` became five call-time functions** rather than PEP 562
  `__getattr__`: `monkeypatch.setattr` on a lazy module attribute
  leaves a real attribute behind on undo, which would freeze it.
- **The GUI keeps reading a `.env`** in development (`main_ui.main()`
  calls `load_env_file()` too); a frozen app never does. The brief said
  "the CLI entry point"; reading it only there would silently drop the
  GUI's dev fallback.
- **The wrong-type warning logs the value's type, not the value**
  (credentials live in the same file).
- **Skill divergence:** `env-secrets-manager` and `adversarial-reviewer`
  not loaded (budget). Run `adversarial-reviewer` over all of S9 before
  part 2's close-out.

## 6. Blockers

None.

## 7. Files in progress

None mid-edit. Row state: `§9.5` not started; `§9.7` not started.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Next launch will migrate the real DB** (S8 part 1 and §8.3, both
rehearsed on a copy, §144 and §145). S9 part 1 changes no schema.

**Behaviour you may notice:** `uv run seeker-ui` launched from outside
the checkout no longer reads the project `.env` (from inside it still
does). Your `config.json` already holds those values, so nothing
should change.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried: S6's Refresh playlists
check, S7's drift Scan, S8's Reject-then-Scan and failure reason on
Downloads.

## 9. Open questions

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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S7 close-out commit (HISTORY §143, CLAUDE.md rule, S7
  ticked, this handoff), pushed. Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-30): `1363 passed, 1 skipped, 6 warnings in 114.38s`
  (X9 Pro mounted; S7 part 1's 1332 plus 31 new). No new `slskd-data`
  (the repo's own is from Sep 10, untouched).
- **`mypy --strict src/`:** clean, 108 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** S7 part 1's push `d1bcb04` → run `36606608838`, **success**.
  This push: see `gh run list --limit 1`.

## 2. Where we are

S1–S7 ticked. **Next: S8, "Review decisions stick; failures stay
visible"** (BRIEF §8; split point after §8.2).

## 3. Session report (S7 part 2)

Evidence (every red, the real-data checks) is in HISTORY §143.
- `1fcbcd6` §7.5: `clean_path_component` replaces each leading dot
  with `_`, so renames and per-playlist folders are never hidden.
- `8ea78c1` §7.6: `validate_destination_subfolder` is the one rule,
  used by `set_destination`, resolution, the dialog and (via the
  service) the CLI and Settings. A stored `../x` no longer moves a
  download outside its location.
- Close-out: §143, a CLAUDE.md rule under SoulSeek / slskd, S7 ticked.

## 4. Key context

- **Your HISTORY entry is §144**: `docs/history/121-150.md` plus its
  README line.
- **Nested destination subfolders are real data**, not a hypothetical:
  the real DB holds `Music/240KMH` and `Music/Test` (plus `32 Zel`,
  `Under Pressure (Deluxe)`). All four validate unchanged. Any later
  change to destination rules must keep them valid.
- **A stored unsafe subfolder resolves to `None`**, which the UI and
  CLI treat as "no destination configured". That is deliberate (the
  set-a-destination dialog is the recovery path), but the CLI's
  wording is then "no destination is configured". None exists in real
  data.
- **S8 starting point (carried):** `_repoint_or_clear_match` drops
  `confirmed_at`.
- **Test helpers:** `tests/test_destination_subfolder.py` imports
  `test_cli`'s `FakeApplication`/`FakeSyncService`/`make_matcher` and
  `test_download_service`'s `_seed_default_destination_scenario` (bare
  module names, not `tests.`).
- **Carried:** the `platformdirs.user_data_dir`/`slskd-data` test
  hazard (checked clean this run); S9's `_write_atomic` umask fix; three
  `LibraryLocationNotFoundError` classes (S13); never touch slskd or
  real data.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`. `grep
  --include=*.py` needs quoting in zsh.

## 5. Decisions made

- **Leading dots → `_`, one for one** (not stripped): the name stays
  recognisable and can never empty out. It runs after the trailing
  strip, so `"..."` still falls back to `"Untitled"`.
- **Nested subfolders allowed, every component must already be
  sanitized; reject, never rewrite.** The error suggests the safe form
  (`'Bad:Name' … Try 'Bad-Name'`). A trailing `/` and surrounding
  whitespace are the only normalisation.
- **Stored invalid values resolve to `None`** rather than raising (four
  callers, one of them the poll loop) or falling back to the default
  (that would silently put the file somewhere the user did not pick).
- **The dialog's default prefill is `sanitize_path_component(playlist
  name)`**, the default rule's own folder, so a raw `240KM/H` is not
  offered as a nested path.
- **Skill divergence:** `focused-fix`, `tdd` not loaded;
  failing-test-first was followed by hand (§143 has every red).

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried from S6: edit a loaded
playlist on Spotify, then Refresh playlists → "Updated tracks for 1".
Carried from S7: the real library has drifted since the last scan (a
copy re-scan found 261 added, 60 updated, 25 removed); the next real
Scan applies that.

## 9. Open questions

- **Found in S7, not fixed:** in `DestinationDialog`, unchecking
  "Remember this for this playlist" makes `MainWindow` save only the
  app-wide default (per-playlist folders on) and drop the typed
  subfolder (`main_window.py`, `do_persist`'s `else` branch). The
  preview can show a folder the download will not use. Which row owns
  it: S19 (this flow moves to DashboardPage, but that row is
  behaviour-neutral) or S29 (information architecture)? It needs its own
  behaviour commit either way.
- Settings → Destinations shows a rejected subfolder as `Error: …` on
  its ephemeral `status_label`, not an `InlineNotice`. S11 (readable
  errors) should cover it.
- CLAUDE.md items 63, 70 and 125 remain open. Which row owns the
  late-worker defect (S11 or S18)? It has failed CI twice
  (`36570098069`, `36580274797`).

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

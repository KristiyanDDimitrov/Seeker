# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S7 part-1 close-out commit plus this handoff, pushed.
  Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-29): `1332 passed, 1 skipped, 6 warnings in 86.91s`
  (X9 Pro mounted; S6's 1318 plus 14 new). No `slskd-data` created.
- **`mypy --strict src/`:** clean, 108 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** S6's handoff push `f2e7852` → run `36589804219`, **success**. This push: see `gh run list --limit 1`.

## 2. Where we are

S1–S6 ticked. **S7 is partial (◐):** §7.1–§7.4 and §7.7 done;
**next: finish S7 with §7.5 (never create hidden names) and §7.6 (the
destination subfolder the user sees is the one used)**, BRIEF §7. Then
S8.

## 3. Session report (S7 part 1)

Evidence (every red, the lock measurement, the timing table) is in
HISTORY §142.
- `b4f4030` §7.1: `delete_missing` past SQLite's 32,766-variable
  limit; new `delete_by_ids` (chunks of 500).
- `398e076` §7.2: scanner reads outside the write lock, upserts in
  batches of 200, prunes hidden directories, logs bad tags at DEBUG,
  keeps a row indexed mid-scan.
- `a1e49a3` §7.3: `match_all` read/compute/write split; keeps a
  confirmation made mid-compute; a file deleted mid-compute → unmatched;
  bisect duration index (identical results on the real data).
- `1819eef` §7.4: add-location paths `expanduser().resolve()`; drive
  hint only under `/Volumes`.
- Close-out: §142, CLAUDE.md "no slow work inside a write transaction",
  S7 row marked ◐.

## 4. Key context

- **Your HISTORY entry is §143**, "S7, part 2 (§7.5–§7.6)":
  `docs/history/121-150.md` plus its README line. Then tick S7.
- **The lock hypothesis is confirmed, not assumed:** pre-S7, a cold
  scan made concurrent writers fail with "database is locked" (3 of 5,
  5.23 s wait). The measurement script is described in §142; it copies
  the real DB with `sqlite3.backup` from a `mode=ro` connection.
- **Two `match_all` races were real on HEAD** (a plain `SELECT` holds
  no lock): a confirmation made mid-run was wiped, and a file deleted
  mid-run failed the whole write on the FK. Both fixed and tested.
- **`LocalFileRepository` gained `delete_by_ids` and `get_ids`.**
  `delete_by_id` delegates to `delete_by_ids`.
- **§7.6 starting points (from BRIEF, unverified this session):**
  `DestinationDialog.selected_subfolder()` returns raw text;
  `set_destination` persists it; `_move_completed_file` joins it
  unsanitized; `seeker playlists set-destination --subfolder` has the
  same gap. Validate once at the service boundary.
- **Test helpers:** `tests/test_library_scale.py` imports
  `test_library_integrity`'s `make_scenario` etc. as `from
  test_library_integrity import …` (not `tests.`).
- **Carried:** the `platformdirs.user_data_dir`/`slskd-data` test
  hazard (checked clean this run); S9's `_write_atomic` umask fix; three
  `LibraryLocationNotFoundError` classes (S13); `_repoint_or_clear_match`
  drops `confirmed_at` (S8); never touch slskd or real data.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`.

## 5. Decisions made

- **Chunked `IN (…)` of 500, not `executemany`** (BRIEF §7.1 said
  `executemany`): `track_matches.local_file_id` has no index, so
  per-id `UPDATE`s would scan that table once per deleted file.
- **The scan deletes only rows that existed when it started** and were
  not seen, so a download placed mid-scan survives. A row renamed
  mid-scan is still treated as missing, and the next scan re-indexes it.
  Accepted.
- **`match_all`'s write re-reads confirmations and file ids.** A newly
  confirmed track is kept and counted as auto. A vanished file becomes
  unmatched, with no score.
- **Stopped before §7.5–§7.6** at ~136 K context (target 120 K). This
  is not the plan's named split point, which also includes §7.5–§7.6.
  Both are independent of everything done here.
- **Skill divergence:** `focused-fix`, `tdd`, `database-designer` not
  loaded; failing-test-first was followed by hand (§142 has every red).

## 6. Blockers

None.

## 7. Files in progress

None. §7.5 and §7.6 are not started; no partial edits exist.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried from S6: edit a loaded
playlist on Spotify, then Refresh playlists → "Updated tracks for 1".
New from S7: note that the real library has drifted since the last
scan (a copy re-scan found 261 added, 60 updated, 25 removed). The next
real Scan will apply that.

## 9. Open questions

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

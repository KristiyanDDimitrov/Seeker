# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S8 close-out commit (HISTORY §145, two CLAUDE.md rules,
  S8 ticked, this handoff), pushed. Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-30): `1397 passed, 1 skipped, 6 warnings in 112.85s`
  (X9 Pro mounted; S8 part 1's 1374 plus 23 new).
- **`mypy --strict src/`:** clean, 109 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** push `b72c0ad` → run `36681713075`, **success**.

## 2. Where we are

S1–S8 ticked. **Next: S9, application hardening, including
peer-string escaping** (BRIEF §9; split point after §9.3). Then S10.

## 3. Session report (S8 part 2)

Evidence (the 22 reds, the race repro, the rehearsal counts) is in
HISTORY §145.
- `ed94323` §8.3: `failure_reason` and `dismissed_at` on
  `download_requests`; every failed/unavailable transition records a
  readable reason; Downloads keeps failures until "Clear finished";
  reason in the Status cell and tooltip; Downloads and History copy.
- Close-out: §145, two CLAUDE.md rules, S8 ticked.

## 4. Key context

- **Your HISTORY entry is §146**: `docs/history/121-150.md` plus its
  README line.
- **The Status cell now shows slskd's own text** (`failure_reason`,
  from the peer's `exception` string). S9's peer-string escaping must
  cover it: the cell is a plain `QTableWidgetItem` (not rich text), and
  the tooltip is set from the same text. Check whether Qt renders a
  tooltip beginning with `<` as rich text before calling it safe.
- **`SoulseekDownloadError` now takes `reason=`** (slskd's message
  without the framing). Both raise sites in `client.py` pass it; S13's
  exception hierarchy should keep it.
- **`_classify_failed_transfer` fetches the `exception` text for every
  failed state**, one extra GET per failure (§145). S22 (performance)
  may count it.
- **`run_worker(button=...)` re-enables the button before
  `on_finished`**, so a render-owned button must not use it (CLAUDE.md,
  §145). "Clear finished" dismisses, never deletes (CLAUDE.md).
- **Carried:** nested destination subfolders are real data; a stored
  unsafe subfolder resolves to `None`; `_repoint_or_clear_match` drops
  `confirmed_at` (still unowned); the `platformdirs.user_data_dir` /
  `slskd-data` test hazard; **S9's `_write_atomic` umask fix**; three
  `LibraryLocationNotFoundError` classes (S13); never touch slskd or
  real data.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`. A
  `--include=*.py` glob fails unquoted; grep the directory instead.

## 5. Decisions made

- **"Clear finished" also dismisses completed rows**, not only
  failures: the button's name promises it, and a completed row already
  leaves after 60 seconds.
- **The 12 identical SELECT column lists in
  `download_request_repository.py` were extended, not refactored into
  a constant**: that is a refactor commit, and an f-string SQL constant
  needs 12 `noqa: S608`. S16 can decide.
- **Skill divergence:** `focused-fix` and `tdd` not loaded (budget);
  failing-test-first followed by hand (§145 has every red).

## 6. Blockers

None.

## 7. Files in progress

None. S8 is complete.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Next launch will migrate the real DB:** S8 part 1's (deletes the one
orphan manual track and its incidental match; adds the two rejection
tables) and §8.3's (adds `failure_reason` and `dismissed_at`). Both
rehearsed on a copy (§144, §145). After it, the Downloads page shows
the 9 historical failures (5 failed, 4 unavailable) without a reason,
until you click Clear finished.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried from S6: edit a loaded
playlist on Spotify, then Refresh playlists → "Updated tracks for 1".
Carried from S7: the next real Scan applies the library's drift.
Carried from S8 part 1: on Review, Reject a local match, Scan, confirm
it does not come back. New: a real failed download shows its reason on
Downloads and stays until Clear finished.

## 9. Open questions

- **Carried from S7:** `DestinationDialog`'s unchecked "Remember this
  for this playlist" drops the typed subfolder (`main_window.py`,
  `do_persist`'s `else` branch). S19 or S29?
- Settings → Destinations shows a rejected subfolder on its ephemeral
  `status_label`, not an `InlineNotice`. S11 should cover it.
- CLAUDE.md items 63, 70 and 125 remain open. Which row owns the
  late-worker defect (S11 or S18)? It has failed CI twice
  (`36570098069`, `36580274797`).
- Should a rejection be undoable (a "Rejected" list on Review)? S29.
- Should `seeker downloads status` (CLI) print failure reasons? Not in
  the brief; S15 (CLI structure) is the natural home.

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

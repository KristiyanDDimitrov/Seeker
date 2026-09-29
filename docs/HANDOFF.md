# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** `c98b77f` (round 11 S4 close-out) plus this handoff commit,
  pushed. Tree clean apart from the untracked `Claude outputs/` (left
  as is: Kris's answer to §1.6).
- **Local pytest** (offscreen Qt, 2026-09-29):
  `1268 passed, 1 skipped, 6 warnings in 113.89s` (X9 Pro mounted;
  S3's 1245 plus 23 new).
- **`mypy --strict src/`:** clean, 106 files. **`ruff check src
  tests`:** 0 findings.
- **CI on `c98b77f`:** run `36579783924`, `success` (`1240 passed,
  29 skipped`: 1268 + 1 locally = 1269 = 1240 + 29 on CI).

## 2. Where we are

Phase A done (S1, S2). Phase B: S3 and **S4 done. Next row: S5**
(a portable Compose template, the release blocker, and Settings never
changing what is shared; BRIEF §5). Then S6.

## 3. Session report (S4)

All evidence is in HISTORY §139: red output per item, the rehearsal
counts, and the numbers.
- `c362d6a` §4.2: every `local_files` delete resets its matches
  (`_release_matches`). Probe A.3 inverted.
- `ad38d29` §4.3: limbo is tolerated in `match_all`,
  `get_unmatched_for_playlist` and `get_auto_matched_for_playlist`,
  plus an idempotent repair in `_migrate`. Rehearsed on a DB copy:
  2 → 0.
- `541f2f1` §4.4: `remove_location` runs in one transaction, returns
  `LocationRemovalSummary` and raises `LibraryLocationNotFoundError`.
  `Application.remove_location` clears the default. Probe A.4 inverted.
- `1a38ec0` §4.5: `preview_remove_location`; a Settings confirm dialog;
  outcome and errors go on `locations_notice`; the CLI prints the
  summary.
- `c98b77f` close-out: §139, row ticked, a CLAUDE.md standing fact
  (a match pointing at no file is unmatched) and the models layout
  line.

## 4. Key context

- **Your HISTORY entry is §140: append it to `docs/history/121-150.md`**
  with `<a name="140"></a>` directly above `### 140 — …`, then its line
  at the end of `docs/history/README.md`.
- **Found, not fixed:** `DuplicateService._repoint_or_clear_match`
  (`library/duplicate_service.py`) upserts the re-pointed match without
  `confirmed_at`, so resolving a duplicate drops a human confirmation.
  No row owns it. It fits S8 (review decisions stick) as a one-test fix.
- **Three `LibraryLocationNotFoundError` classes now exist**
  (`library/service.py`, new; `library/duplicate_service.py`;
  `soulseek/download_service.py`). `cli.py` imports all three under
  aliases. S13 (one exception hierarchy) should merge them.
- **Never delete `local_files` rows with raw SQL.** Go through
  `LocalFileRepository`, which resets matches first. The CLAUDE.md
  standing fact records this.
- **Settings' `locations_status_label` is gone.** Location feedback is
  `locations_notice` only.
- **`tests/test_library_integrity.py::make_scenario`** gives location
  `Lib` (id 1) with `A/3AMDISCO - Get Back.wav`, which auto-matches
  track `t1` in playlist `p1`. `test_download_placement.py` has the
  download-side equivalent.
- **Settings tests never show the page:** wait on `not
  widget.isHidden()`, never `isVisible()`.
- **Carried:** the round-10 CI late-worker `SETUP ERROR`
  (`_handle_task_finished` → a deleted `QTableWidget`, run
  `36570098069`) is still unowned. S11 or S18 should take it.
  `download_requests.size` gates location (S3). Pytest's skip count
  depends on the X9 Pro (1 mounted, 29 not). Never start, stop or
  recreate Kris's slskd container, and never write real data
  (BRIEF §0.7).

## 5. Decisions made

- **The match reset lives in `LocalFileRepository`**, as one private
  helper called explicitly by each delete method. Every delete path,
  current or future, gets it without a trigger, and callers need no
  second repository.
- **`get_auto_matched_for_playlist` was fixed as well,** beyond the
  brief's two queries, because "tolerate limbo everywhere" covers it: a
  limbo `auto` row was offered to `tag_playlist`.
- **`was_default` is computed by the service from an id the caller
  passes;** only `Application` owns config, so only it clears the
  default.
- **The CLI does not ask before `library remove`:** it prints the
  summary. The brief asked only for the summary, and the command is
  explicit.
- **Skill divergence:** `focused-fix`, `tdd` and `database-designer`
  were not loaded. The brief specified the fix and the tests, and
  red-then-green was done by hand (red output in §139).

## 6. Blockers

None for S5.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim caution until its fix lands:** no Settings → **Update
SoulSeek credentials** until S5.

**Live checks:** consolidated into S41's checklist
(`SESSION-PLAN.md` → "Waiting on Kris"). New from S4: after the next
launch plus a Scan, the two Denzel Curry tracks are re-evaluated, and
Settings → Remove shows the confirmation with real counts.

## 9. Open questions

- CLAUDE.md open items 63 (retry storm), 70 (stress hang; S22 has a
  lead) and 125 (quit hang) remain open.
- The late-worker `SETUP ERROR`: which row fixes it (S11 or S18).

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

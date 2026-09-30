# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S8 part 1 close-out commit (HISTORY §144, CLAUDE.md
  rule, this handoff), pushed. Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-30): `1374 passed, 1 skipped, 6 warnings in 112.39s`
  (X9 Pro mounted; S7's 1363 plus 12 new, minus 1 replaced).
- **`mypy --strict src/`:** clean, 109 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** S7 close-out push → see `gh run list`. This push: see
  `gh run list --limit 1`.

## 2. Where we are

S1–S7 ticked. **S8 stopped at its split point (after §8.2); S8 is not
ticked.** **Next: S8 part 2, §8.3 "Failures stay visible"** (BRIEF §8).
Then S9.

## 3. Session report (S8 part 1)

Evidence (every red, the rehearsal counts) is in HISTORY §144.
- `c905476` §8.1: `rejected_local_matches` / `rejected_soulseek_candidates`
  + `RejectionRepository`; `match_all` and `download_playlist` skip
  rejected pairs and fall through; tooltips and CLI help updated.
- `abf7a93` §8.2: a manual track is saved just before its first
  request and removed if it fails; `_migrate` deletes `manual:` tracks
  with no request. Rehearsed on a copy: 1 → 0.
- Close-out: §144, a CLAUDE.md rule under Database and migrations.

## 4. Key context

- **Your HISTORY entry is §145**: `docs/history/121-150.md` plus its
  README line. Tick S8 in SESSION-PLAN only when §8.3 lands.
- **§8.3 starting points:** the poll classifies slskd state and
  exception text in `poll_downloads` (`download_service.py`, grep
  `is_recognized_rejection` / `"failed"`); `FakeSoulseekClient` in
  `tests/test_download_service.py` already takes `states=` and
  `exceptions=` per transfer id, so a failure-reason test needs no new
  fake. Both new columns (`failure_reason`, `dismissed_at`) go through
  `_add_column_if_missing` in `database/connection.py::_migrate`.
- **`match_all` matches manual tracks too.** That is why the real
  orphan had an auto match. Any "is this manual track real" check must
  key on `download_requests`, never on `track_matches`.
- **Nothing in `src/` deletes `download_requests` rows.** §8.2's
  migration relies on it; §8.3's "Clear finished" must set
  `dismissed_at`, never delete, or completed manual tracks become
  eligible for that migration.
- **`DownloadService` and `TrackMatcher` take
  `rejection_repository=` as an optional keyword** (defaults to a new
  one on the same database), so the many positional test constructors
  did not change. `Application` passes it explicitly.
- **Carried:** nested destination subfolders are real data (`Music/240KMH`,
  `Music/Test`); a stored unsafe subfolder resolves to `None`;
  `_repoint_or_clear_match` drops `confirmed_at` (still unowned by a row
  that touches it; S8's brief did not name it); the
  `platformdirs.user_data_dir`/`slskd-data` test hazard; S9's
  `_write_atomic` umask fix; three `LibraryLocationNotFoundError`
  classes (S13); never touch slskd or real data.
- **zsh gotcha:** `echo ======` fails; use `echo '---'`.

## 5. Decisions made

- **Orphan predicate is "no `download_requests` row", not the brief's
  "no requests and no matches".** Evidence in §144: the real orphan has
  an incidental auto match, and no code deletes requests. The file is
  never touched; only the orphan's own match cascades.
- **One `RejectionRepository` for both tables**: one concept (a
  human's Reject), two shapes; keeps the service constructors to one
  new keyword each.
- **A pair rejected while `match_all` computes is stored unmatched**
  (write-phase re-check, §142's shape), not re-resolved to the next
  best; the next run falls through.
- **`reject_review_candidate` with no candidate row still clears
  silently** (unchanged behaviour); it records nothing.
- **Skill divergence:** `focused-fix`, `tdd`, `database-designer` not
  loaded (budget); failing-test-first followed by hand (§144 has every
  red).

## 6. Blockers

None.

## 7. Files in progress

None: stopped cleanly at the split point. §8.3 has not been started.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Next launch will migrate the real DB:** deletes the one orphan manual
track ("Amen Brother" / "The Winstons", no download request) and its
incidental match; adds the two empty rejection tables. Rehearsed on a
copy (§144).

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (see HISTORY §140).

**Live checks:** S41's checklist. Carried from S6: edit a loaded
playlist on Spotify, then Refresh playlists → "Updated tracks for 1".
Carried from S7: the real library has drifted since the last scan; the
next real Scan applies that. New: on Review, Reject a local match, Scan,
and confirm it does not come back.

## 9. Open questions

- **Carried from S7:** `DestinationDialog`'s unchecked "Remember this
  for this playlist" drops the typed subfolder (`main_window.py`,
  `do_persist`'s `else` branch). S19 or S29? Needs its own behaviour
  commit either way.
- Settings → Destinations shows a rejected subfolder on its ephemeral
  `status_label`, not an `InlineNotice`. S11 should cover it.
- CLAUDE.md items 63, 70 and 125 remain open. Which row owns the
  late-worker defect (S11 or S18)? It has failed CI twice
  (`36570098069`, `36580274797`).
- Should a rejection be undoable (a "Rejected" list on Review)? Not in
  the brief; S29 (Review information architecture) is the natural home.

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

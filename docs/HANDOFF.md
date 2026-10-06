# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S26 part-1 handoff commit, after the close-out
  `abbe594` (HISTORY §171, handoff, plan row). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local** (at `c154af8`, X9 Pro not mounted): pytest `1674 passed,
  29 skipped`; `mypy --strict src/` clean, 129 files; `ruff check src
  tests` 0.
- **CI:** run `37501083676` (at `abbe594`): **success**, `1674
  passed, 29 skipped`, coverage 94.10 % (floor 92 %).

## 2. Where we are

S1–S25 ticked. **S26 stopped at its split point (after §26.2)** on
budget. **Next: S26 part 2**: §26.3 merge, then §26.4 rehearsal on a
DB copy. S26's box stays unticked until part 2 lands.

## 3. Session report (S26 part 1)

Evidence and the real-DB counts are in HISTORY §171.
- `51cb8db` §26.1: both add paths refuse a folder inside or around a
  location (resolved path plus on-disk identity; APFS is
  case-insensitive). `LibraryLocationOverlapError`; `get_by_path`
  removed.
- `c154af8` §26.2: `LibraryService.find_nested_locations()` →
  `NestedLocation(inner, outer)`; Settings `nesting_notice` (warning);
  `seeker library check`.

## 4. Key context

- **The merge must carry analysis, not just matches.** In the real DB
  `Music` (the one to keep) has 0 matches and 494 fingerprints; `x9-pro`
  has 37 matches and 3,157 fingerprints, `Test` 6 matches. 5 rows have
  no counterpart under `Music`, none matched (§171 table).
- **§26.3 design, decided (not yet built):**
  - Map each redundant row to the kept row for the same file: find
    the prefix between the two roots with `nesting.same_directory`
    over parents. Inner redundant: `kept_key = str(Path(prefix,
    rel))`. Outer redundant: strip the prefix's parts, else
    unmapped. Keys must match the scanner's `str(path.relative_to(root))`.
    Confirm with `same_file`, outside any transaction (§142). Refuse
    unless both roots are reachable and nested.
  - New `LocationMergeRepository`: a temp `merge_pairs(redundant_id
    PRIMARY KEY, kept_id)` table, staged per connection
    (`transaction()` opens a new one each time) and pruned to rows
    that still exist. It moves matches (`UPDATE … SET local_file_id`)
    and rejections (`INSERT OR IGNORE … SELECT`; old ones cascade).
    It carries analysis with `UPDATE … FROM` (SQLite 3.53.1) in three
    groups: (bpm, camelot_key, key_confidence),
    (fingerprint, fingerprint_duration, fingerprint_computed_at) and
    tagged_at. A group is copied only into an empty kept group, and
    only when size_bytes and mtime agree. Duplicate cleanups move too.
  - Playlist destinations are re-expressed against the kept root
    (`x9-pro` + `Music/240KMH` → `Music` + `240KMH`; `Test` +
    `Music/Test` → `Music` + `Test/Music/Test`). Any not under the
    kept root are cleared and counted.
  - The redundant location then goes through `remove_location`'s
    three deletes; extract them first in a refactor-only commit.
    `was_default` → `Application` clears the default, as removal does
    (moving it would change the destination folder).
  - `LocationMergeSummary` (models/): merged, forgotten, matches
    moved and cleared, analyses kept, playlists moved and cleared,
    `was_default`. Preview and merge use the same counting code.
  - Names, not ids, as `remove_location` does (a divergence from the
    brief's `merge_nested_location(redundant_id, keep_id)`; record
    it).
  - UI: the `nesting_notice` gets a "Fix…" action. Flow:
    `QInputDialog.getItem` "keep which?" → worker previews merging
    every location nested with it → `plain_text.question` with the
    counts → worker merges → `locations_notice` result. CLI: `seeker
    library merge REDUNDANT KEEP`; update `library check`'s hint line.
- **§26.4 without the drive:** the X9 Pro is not mounted, so
  `same_file` would fail every row. Rehearse on a DB copy with paths
  rewritten to a scratchpad tree of empty files mirroring every
  `relative_path` (nesting is physical, so the inner location's files
  are the outer's). Or ask Kris to mount the drive (stat only).
- **A shared fake missing a method stalls the suite, not fails it**
  (§171): add each new service call's fake method in the same commit.
- Carried: radon not in the env; never touch slskd or real data; zsh
  does not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` (800×800) first.

## 5. Decisions made

- **Stopped at the split point** (plan rule 3): past ~120 K.
- **`database-designer` not loaded;** `migration-architect` was. Its
  useful parts were reconciliation counts and a one-transaction merge
  (the transaction is the rollback). Its schema tooling does not apply:
  no schema change.
- **Exact duplicates now raise `LibraryLocationPathAlreadyRegistered
  Error` on the CLI path too,** instead of the repository's
  UNIQUE-constraint `RuntimeError`; the message still says "already
  registered".

## 6. Blockers

None.

## 7. Files in progress

None; part 2 starts from the design in §4.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Optional for S26 part 2:** mount the X9 Pro so §26.4 can rehearse
against the real files (read-only stat calls on the drive, the DB a
scratchpad copy).

**Carried:** next launch migrates the real DB (S8, §144, §145);
keep or discard `./slskd-data` (§140); run the stress test
(`SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
X9 Pro mounted, Spotify and slskd up).

**Live checks:** S41's checklist plus the carried per-row checks
(full list in the S25 handoff, `git show 5db1162:docs/HANDOFF.md`).
**New for S26:** Settings → Library Locations warns `Music`⊂`x9-pro`,
`Test`⊂`x9-pro`, `Test`⊂`Music`; adding `/Volumes/X9 Pro/Music/House`
is refused, naming `Music`.

## 9. Open questions

- Carried unchanged from the S25 handoff: the Spotify wait not
  cancelled on close; the late-worker button defect (§148); Settings
  and Duplicates results on status labels (S28/S29); four CLI items
  (§156); the unrecorded transfer id and leftover `.tmp` files (X1).
- Why a shared fake's missing method stalls the suite instead of
  failing it (§171). UNVERIFIED.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

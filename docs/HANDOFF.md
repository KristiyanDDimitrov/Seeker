# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S26 part-2 handoff commit, after the close-out
  `66124ac` (HISTORY §172, handoff, plan row). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local** (at `68e5f85`, X9 Pro not mounted): pytest `1698 passed,
  29 skipped`; `mypy --strict src/` clean, 131 files; `ruff check src
  tests` 0.
- **CI:** run `37503807018` (at `66124ac`): **success**, `1698
  passed, 29 skipped`, coverage 94.11 % (floor 92 %).

## 2. Where we are

S1–S26 ticked; Phase I is done. **Next: S27** (Phase J, UI
consistency): the screenshot harness (§27.0), theme root causes,
focus and accessibility. Split point after §27.1.

## 3. Session report (S26 part 2)

Evidence, the rehearsal table and the real-DB checks are in HISTORY
§172.
- `ef47736` §26.3 refactor: `remove_location`'s deletes →
  `_forget_location`. No behaviour change.
- `dd07692` §26.3: `LibraryService.merge_location` /
  `preview_merge_location`, `LocationMergeRepository`,
  `LocationMergeSummary`, `nesting.nested_path_map`;
  `Application.merge_location` clears a merged default.
- `68e5f85` §26.3: Settings **Fix…** on the nesting warning; `seeker
  library merge NAME KEEP`; README rows for `library check`/`merge`.
- §26.4: rehearsed on a scratchpad copy (no commit; script and log
  in the session scratchpad, results in §172): 43 matches before and
  after, 0 on another file or lost; nested pairs 3 → 0.

## 4. Key context

- **The real merge needs the X9 Pro mounted:** `merge_location`
  refuses an unreachable root (`same_file` cannot confirm a pair
  otherwise). Keep `Music`; expect the §172 counts (x9-pro: 3,454
  merged, 4 forgotten, 37 matches moved; Test: 8, 1, 6).
- **Three fingerprints the rehearsal "lost" are correct to lose:**
  stale `x9-pro` rows for files that later moved under `Music/Pop
  House/`, not indexed by `Music` (§172).
- **For S27's harness:** Settings now has a `nesting_notice` with a
  Fix… action button (an `InlineNotice` action); the demo
  `FakeLibraryService.find_nested_locations` returns `[]`, so the
  warning only renders if a fake returns pairs.
- Carried: radon not in the env; never touch slskd or real data; zsh
  does not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` (800×800) first; a shared fake missing a
  method stalls the suite instead of failing it (§171).

## 5. Decisions made

- **Names, not ids,** for `merge_location(merged_name, kept_name)`,
  diverging from the brief's `merge_nested_location(redundant_id,
  keep_id)`: it matches `remove_location`, the CLI and the UI.
- **Analysis moves only into an empty group and only on equal size
  and mtime;** a kept row's own analysis is never overwritten.
- **A merged default destination is cleared, not moved** (as removal
  does): moving it would change the folder downloads land in.
- **The CLI merge does not prompt,** consistent with `library
  remove`; the UI confirms with the preview's counts.
- **Fix… merges every location inside or around the one kept,** one
  `merge_location` per location; the preview's per-location
  summaries are totalled (analysis counts may overlap when two
  merged locations cover one file; the result reports the truth).
- **Standing rule promoted to CLAUDE.md:** "Library locations never
  nest" (Database and migrations); the open-issue bullet now says
  only the real click remains.
- **Skills:** `database-designer`/`migration-architect` not reloaded;
  part 1 already applied migration-architect's useful parts
  (reconciliation counts; the one transaction is the rollback). No
  schema change.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**New live check (S41 checklist):** with the X9 Pro mounted,
Settings → Library Locations → Fix…, keep `Music`; compare with
§172's counts. The next launch also runs the pending S8 migrations
(rehearsed again here on the copy, clean).

**Carried:** keep or discard `./slskd-data` (§140); run the stress
test (`SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`,
X9 Pro mounted, Spotify and slskd up). Live checks: S41's checklist
plus the carried per-row checks (full list in the S25 handoff, `git
show 5db1162:docs/HANDOFF.md`); S26 part 1's (the warning names the
three pairs; adding `/Volumes/X9 Pro/Music/House` is refused).

## 9. Open questions

- Carried unchanged from the S25 handoff: the Spotify wait not
  cancelled on close; the late-worker button defect (§148); Settings
  and Duplicates results on status labels (S28/S29); four CLI items
  (§156); the unrecorded transfer id and leftover `.tmp` files (X1).
- Why a shared fake's missing method stalls the suite instead of
  failing it (§171). UNVERIFIED.
- A location whose stored path differs in case from the folder on
  disk maps no files in a merge (paths compare as text after the
  prefix; the files would be forgotten, not mispaired). Not seen in
  the real DB; the preview would show it as forgotten files.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

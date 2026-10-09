# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S9 close-out (HISTORY §201). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2088 passed, 1 skipped`, 0 failed for the first time since S37 (+2 tests). `mypy --strict
  src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** `04f8f04`'s run `37933912241` green: `check` `2060 passed,
  29 skipped`, coverage 94.60 % (floor 92 %); `audit`, no known
  vulnerabilities. The run before it (`37932732255`, `1c994eb`) failed
  one new, intermittent test, with no code change between the two. See §4.

## 2. Where we are

**Round 12 S9 is done**, and so is Phase B. `uvx radon cc -n D -s
src/seeker` reports nothing (an exit criterion), and both of CLAUDE.md's
"undiagnosed failures" are diagnosed and fixed. **Next: S10**, daily
sweep I (config, service, `sweep_due`, CLI), BRIEF §10.

## 3. Session report (S9)

Evidence for each is in HISTORY §201.
- `4939e22` §9.1: `_decide_next_step` D 21 → A 5 (`_setup_step`,
  `_playlist_step` C 12, `_download_step`).
- `3a88615` §9.2: two characterization tests (empty `directories:`, a
  continuation line). `87f7213`: `_insert_slskd_share_directory` D 26
  → C 11 (`_find_directories_key`, `_directories_insert_point`).
- `a1d209a` §9.3: `FakeDownloadService._download_manual_gate`; the
  Search download-best test holds the fake and waits on the notice.
- `d724d2a` §9.4: the cell-background test's table is `NoFocus`.
- `82823e7` §9.4: the selection-contrast test no longer waits on
  `hasFocus()`.
- The close-out: HISTORY §201, CLAUDE.md (Testing gains the activation
  rule; Open issues and Roadmap lose the closed items), the plan tick
  and this file.

## 4. Key context

- **New CI failure, undiagnosed:**
  `test_library_track_list_refreshes_after_a_tag_run` timed out on CI
  `37932732255` (Python 3.14.7 under coverage). Locally it passes 10/10
  alone offscreen, its module offscreen, and both Cocoa full runs. S9
  touched no Library or tagging code. Lead, UNVERIFIED:
  `LibraryPage.refresh_tracks()` starts a worker per call, and
  `_on_tracks_loaded` checks the playlist id, not recency. So an
  earlier load still in flight could land after the post-tag refresh
  and repaint pre-tag statuses. If so, it's a product bug (a stale
  response wins). Test first: hold the first load's fake call and
  release it after the second. No row owns it yet; it's listed in
  CLAUDE.md → Open issues.

- **The Cocoa theme flip-flop was window activation.** Whether a test
  window becomes active is timing-dependent; a second pytest process
  can take activation. Active: a table gets keyboard focus and Fusion
  tints its current item. Inactive: `hasFocus()` never comes. Now in
  CLAUDE.md → Testing. A full local run should now be all green;
  any theme failure is a new one.
- **A probe that pins the inactive state:** `card.setWindowFlag(Qt.
  WindowType.WindowDoesNotAcceptFocus)` before `show()`.
- **`QApplication.setActiveWindow` is deprecated** in PySide6 6.11, and
  pyproject turns a `DeprecationWarning` into an error. Don't use it to
  force activation.
- **`FakeDownloadService._download_manual_gate`** is there for any
  test that needs the window between the worker's call record and
  the finish handler. Always `set()` it in a `finally`, or the
  thread pool's destructor hangs teardown (§125).
- **Carried:** the callback handler has no socket timeout (S8 review
  note); Sharing's 20 s per-row rebuild (S15); `uv build --wheel`
  picks up a gitignored `_build_info_generated.py` (S16). Set `set -o
  pipefail` before `pytest … | tail && git commit`. Never touch slskd
  or real data.

## 5. Decisions made

- **§9.4 fixes the tests, not the product.** The focus frame on a
  focused table's current item is intended (visible keyboard focus,
  §175). Unfocused selection paints the same colours, and the test
  still catches its bug in both states (probed).
- **Skills:** `tdd` was loaded. Its "confirm the seams" step was taken
  as met by BRIEF §9, which names each test (the S8 divergence again).
  `tech-debt-tracker` was loaded, but radon measured the drop, since
  the brief's criterion is radon's (the skill's how, the brief's
  what).

## 6. Blockers

None for S10.

## 7. Files in progress

None: S9 is committed whole.

## 8. Waiting on Kris

- **§9.4, optional:** the brief asked for a rerun on the built-in
  display only. The Mac is in clamshell with only the LG 5K attached,
  and the mechanism doesn't involve the display, so this is a
  confirmation, not a need.
- **S-04:** the GPL wording for the DMG (S16).
- **Still open from S1–S8:** the live checks of §193–§196, the S5
  wording veto, the wordmark's brows (`9ff777b`), BRIEF §17, S8's
  visible peer-filename change, and `git show 1b415a4:docs/HANDOFF.md`
  §8. The real DB still has the three nested locations.

## 9. Open questions

- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED; it needs a throwaway container.)
- Does Dependabot's `docker-compose` ecosystem bump a `tag@digest`
  line as a pair? The first PR will show.
- Should the callback handler get a socket timeout? Small, but no row
  owns it.
- Unchanged from S36: `git show 1b415a4:docs/HANDOFF.md` §9.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

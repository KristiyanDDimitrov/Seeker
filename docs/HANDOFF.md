# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S12b close-out (HISTORY §207). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2172 passed, 1 skipped`, 0 failed (+10
  tests). `mypy --strict src/` clean, 141 files; `ruff check src tests
  tools` 0; `uvx radon cc -n D -s src/seeker` nothing.
- **CI:** pending at the close-out commit; see the commit after it.

## 2. Where we are

**Round 12 S12b is complete** (☑). A settled download falls back to
up to three backups: in the poll, at enqueue, and a placed settled
file supersedes the rest; a re-search skips a file that failed within
30 days. **Next: S13, X1: clean up leftover slskd downloads** (BRIEF
§13). The first live Cancel and the first real cleanup both wait for
Kris at the keyboard.

## 3. Session report (S12b, §12b.3–§12b.6)

Evidence for each is in HISTORY §207.
- `56cbd13` refactor: `_record_unrequested(…, status, rank=None)`.
- `6ada558` §12b.3: a peer offline at enqueue records the settled row
  `locked`, then `DownloadPoller.fall_back` requests its backup at
  once; the track counts requested. An unrecognized HTTP error stays
  loud.
- `c77576f` refactor: `supersede_other_active_for_track` takes a role.
- `c594075` §12b.4: a placed settled file (pending loop or locked
  retry) supersedes the other settled rows, never upgrades; a cancel
  supersedes the other rows of its role.
- `bb4588e` §12b.5: the cooldown covers `FAILED_OUTCOMES`; `0ffa46b`
  renames it `FAILED_CANDIDATE_COOLDOWN` / `get_failed_candidates_since`.
- Close-out: `schema.py` comments, CLAUDE.md (sweep line, a
  settled-fallback fact), the screenshot fixture's two backup rows,
  HISTORY §207, the plan tick, this file.

## 4. Key context for S13

- BRIEF §13: list files in slskd's download and incomplete folders
  that no pending or ready-for-review request references; show sizes;
  explicit confirmation; never delete what an active transfer uses.
  **Test against a scratch tree only;** the real slskd folders are
  read-only to the session.
- **New since planning (S12b):** a superseded row's transfer is never
  cancelled in slskd, so a superseded settled backup's file (and a
  superseded upgrade's) becomes a leftover. A `shortlisted` row has no
  file; a `locked` row's last attempt may have left a partial one in
  the incomplete folder.
- Downloads already has an Actions column and the
  `_action_button`/`_ROW_ACTION_KEYS` idiom; a page-level action goes
  in the header row beside "Clear finished" (`theme.action_row()`).
- Placement facts (CLAUDE.md → SoulSeek): slskd writes `<remote
  parent>/<basename>` or `<stem>_<ticks><suffix>`;
  `_locate_completed_file` matches by exact byte size. A
  `ready_for_review` upgrade's file waits in slskd's folder, so it is
  referenced and must never be listed.
- **Carried:** `test_library_track_list_refreshes_after_a_tag_run`'s
  one CI timeout; the callback handler has no socket timeout;
  Sharing's 20 s per-row rebuild (S15); `uv build --wheel` picks up a
  gitignored `_build_info_generated.py` (S16). Run the full suite in
  the foreground (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **An unrecognized `SoulseekDownloadError` at enqueue still fails
  the track**: the brief named only the offline peer.
- **A cancel supersedes by the cancelled row's role**, so cancelling a
  running backup also ends the settled row still in its locked retry
  loop.
- **Hypothesis 2 needs no change:** "… is already downloading, or
  already downloaded" is true beside a running backup. **Hypothesis
  3 recorded:** with every settled file failed, a landed upgrade
  waits in Review and the track has no file.
- **Skills:** `tdd`, red first per behaviour commit; refactors in
  their own commits ahead of the behaviour. Divergence, as in S12:
  the seams came from the brief Kris approved, not a fresh
  confirmation.

S12b's earlier decisions: HISTORY §206; S12's Cancel: §205.

## 6. Blockers

None for S13's code. S13's first real deletion is Kris's to click.

## 7. Files in progress

None uncommitted. S12b is closed at its row boundary.

## 8. Waiting on Kris

- **New (S12b):** veto, if wanted, §5's decisions, HISTORY §206's
  backup decisions and BRIEF §12b's "Code's calls" (3 backups; none
  for a person's choice).
- **From S12:** the first live Cancel, at the keyboard; HISTORY
  §204's retry and §205's Cancel decisions.
- **From S11:** the four sweep decisions (HISTORY §203); the "Daily
  sweep" card.
- **From S10:** the cooldown's reach into manual Download, the 30-day
  and 50-search numbers; the real `tracks.last_searched_at` migration
  runs on the next launch.
- **Still open:** S-04's GPL wording (S16); the live checks of
  §193–§196; the S5 wording veto; the wordmark's brows (`9ff777b`);
  BRIEF §17; S8's visible peer-filename change; `git show
  1b415a4:docs/HANDOFF.md` §8; the three nested locations in the real
  DB.

## 9. Open questions

- How long may a settled file sit in a remote queue before Seeker
  gives up or falls back? There is no limit today (BRIEF §12b → "Not
  in this row").
- Should an activated backup's row say it is a backup? Once
  requested it reads plain "Downloading" (HISTORY §207 → Screens).
- Should a downloading row get Cancel too (a transfer stuck at a few
  per cent)?
- Should Downloads get a "Retry all" for many failures?
- Should the sweep skip a track whose needs-review candidate is still
  waiting on a person?
- Should a GUI sweep and a cron `seeker downloads sweep` guard against
  running at the same time? (UNVERIFIED how they interleave.)
- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED.)
- Does Dependabot's `docker-compose` ecosystem bump a `tag@digest`
  line as a pair?
- Should the callback handler get a socket timeout?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S12 close-out (HISTORY §205). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2152 passed, 1 skipped`, 0 failed (+12
  tests). `mypy --strict src/` clean, 141 files; `ruff check src tests
  tools` 0; `radon cc -n D` nothing.
- **CI:** see §3's last line for the close-out's run.

## 2. Where we are

**Round 12 S12 is complete** (☑): Retry (§204) and Cancel (§205) on
the Downloads page. **Next: S13, X1, "Clean up leftover slskd
downloads"** (BRIEF §13; split point "After the listing (no
delete)"). The first live Cancel and the first real cleanup both wait
for Kris at the keyboard.

## 3. Session report (S12, Cancel)

Evidence for each is in HISTORY §205.
- `1c1f775`: `SoulseekClient.cancel_download` (`DELETE
  …/downloads/{user}/{id}?remove=false`) and
  `DownloadService.cancel_download(id)` → `CancelOutcome`: reads
  slskd's state after the `DELETE`; `Succeeded` is left to the poll,
  anything else is `failed`, "Cancelled by you", only if still
  `IN_FLIGHT`; a cancelled upgrade supersedes its backups.
- `a4180d1`, refactor: `_action_button` and `_ROW_ACTION_KEYS` in
  `downloads_page.py`; tooltips stay at the call site (the plain-text
  sweep needs to see fixed text).
- `992a972` §12: Cancel on queued rows, busy key `cancel_download`,
  one at a time, outcome in the notice.
- Close-out: HISTORY §205, CLAUDE.md (slskd cancel fact),
  `ui/CLAUDE.md`, the plan's ☑, this file, a comment's citation fixed
  (§205 → §204 in `client.py`). CI: recorded in the push commit.

## 4. Key context for S13

- BRIEF §13: list files in slskd's download and incomplete folders
  that no pending or ready-for-review request references; show sizes;
  explicit confirmation; never delete what an active transfer uses.
  **Test against a scratch tree only;** the real slskd folders are
  read-only to the session.
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

- **A cancelled upgrade ends:** its locked and shortlisted backups are
  superseded, never cascaded to (answers §204's open question).
- **Cancel is on `queued` rows only**, as the brief says; a
  downloading row has no button.
- **No confirmation dialog for Cancel**; the tooltip says the queue
  place is lost, and Retry is on the row it leaves.
- **Skills:** `tdd`, red first for each behaviour commit. Divergence:
  the seams came from the brief and §204's handoff, not a fresh
  confirmation with Kris (HISTORY §205). `frontend-design` not loaded:
  one more button in an existing column, checked in screenshots in
  both themes at both sizes.

## 6. Blockers

None for S13's code. Its first real deletion is Kris's to click.

## 7. Files in progress

None: S12 is committed whole. S13 has no code yet.

## 8. Waiting on Kris

- **New:** the first live Cancel, at the keyboard (the plan's S12
  gate); veto, if wanted, §5's Cancel decisions.
- **From S12 Retry:** HISTORY §204's retry decisions.
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

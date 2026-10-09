# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S12 close-out (HISTORY §204). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2140 passed, 1 skipped`, 0 failed (+11
  tests). `mypy --strict src/` clean, 141 files; `ruff check src tests
  tools` 0; `radon cc -n D` nothing.
- **CI:** `a8d6327`'s run `37961766546` green: `check` `2112 passed,
  29 skipped`, coverage 94.71 % (floor 92 %); `audit`, no known
  vulnerabilities.

## 2. Where we are

**Round 12 S12 stopped at its split point, "After Retry"** (the
session reached its budget). Retry is built; **Cancel is next**, and
it is still S12 (the plan's row is marked ◐). BRIEF §12. The first
live Cancel needs Kris at the keyboard.

## 3. Session report (S12, Retry)

Evidence for each is in HISTORY §204.
- `352055b`: Downloads rebuilds its table only when its rows change;
  a progress-only tick updates meters, ETA, percentage and sort keys
  in place.
- `a54b5df`: `DownloadService.retry_download(id)`: `search_and_request`
  for the row's track; dismisses the row once something is requested;
  `DownloadNotRetryableError` otherwise.
- `e7e9d07`: `elided_text.label_floor`: a noted column in a
  read-in-full view is never cut below its widest label (Downloads'
  new column and the Dashboard's "Candidate to review" elided).
- `8bb9e7d` §12: the Actions column and Retry (busy key
  `retry_download`, one search at a time, outcome in the notice).
- Close-out: HISTORY §204, `ui/CLAUDE.md` (two facts), the plan's ◐,
  this file. CI run `37961766546` green (§1).

## 4. Key context for Cancel (the rest of S12)

- **Endpoint, verified read-only against the 0.26.0 tag's source:**
  `DELETE /api/v0/transfers/downloads/{username}/{id}?remove=false`;
  build it with `SoulseekClient._transfer_url` (already quotes both
  segments). It answers `204` even for an unknown id or a finished
  transfer; a stuck unfinished record becomes `Completed, Cancelled`.
  So after the `DELETE`, read `get_download_status`: a `Succeeded`
  transfer is left to the poll; otherwise mark the row `failed` with
  `failure_reason="Cancelled by you"`, re-reading the row in the same
  transaction and only if it is still `IN_FLIGHT`.
- **Race:** a poll that read the row before the cancel may itself
  mark it `failed` "Cancelled" (`FAILED_STATE_MARKERS`); harmless.
- **An upgrade row:** its `shortlisted` siblings are only chased when
  it fails in the poll (`_cascade_upgrade`). A user-cancelled upgrade
  would strand them as "Queued as backup"; decide (supersede them, or
  cascade) and say which in HISTORY.
- **UI:** Cancel goes in the same Actions cell on `queued` rows, the
  Retry idiom (render owns enabled state; the busy key in
  `_RenderedRows`). A `DELETE` against the real slskd waits for Kris.
- **Carried:** `test_library_track_list_refreshes_after_a_tag_run`'s
  one CI timeout; the callback handler has no socket timeout;
  Sharing's 20 s per-row rebuild (S15); `uv build --wheel` picks up a
  gitignored `_build_info_generated.py` (S16). Run the full suite in
  the foreground (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **One retry searches at a time**; every Retry button waits.
- **A retried row is dismissed only when the retry requested
  something**; a retry finding nothing, or only a needs-review
  candidate, leaves the failure listed.
- **A `failed` row's own peer is not skipped** on retry (the 30-day
  cooldown covers `unavailable` only).
- **The label floor applies to every read-in-full table** (Dashboard,
  Library, History, Downloads); only Dashboard's and Downloads'
  screens changed (Library and History byte-identical).
- **Skills:** `tdd` (red first for each commit); `frontend-design` not
  loaded: one button column in the existing `cell_widget` idiom,
  checked in screenshots in both themes at both sizes.

## 6. Blockers

None for Cancel's code. Its first live `DELETE` needs Kris present.

## 7. Files in progress

None: Retry is committed whole. Cancel has no code yet.

## 8. Waiting on Kris

- **New:** veto, if wanted, §5's retry decisions; see Retry on the
  Downloads page.
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

- Should a cancelled upgrade supersede its shortlisted siblings, or
  cascade to the next one (§4)?
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

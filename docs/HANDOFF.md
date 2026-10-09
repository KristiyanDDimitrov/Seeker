# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S12b split-point close-out (HISTORY §206). Tree clean
  apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2162 passed, 1 skipped`, 0 failed (+10
  tests). `mypy --strict src/` clean, 141 files; `ruff check src tests
  tools` 0.
- **CI:** see §3 for this push's run.

## 2. Where we are

**Round 12 S12b stopped at its split point, after §12b.2** (☐, not
ticked): a failed or locked settled row now falls back to its next
backup in the same poll. **Next: S12b continued, §12b.3–§12b.6**
(BRIEF §12b), then S13, X1 (BRIEF §13). The first live Cancel and the
first real cleanup both wait for Kris at the keyboard.

## 3. Session report (S12b, to §12b.2)

Evidence for each is in HISTORY §206.
- `660428e`: planning's uncommitted documents (BRIEF §12b, plan row,
  handoff).
- `08295e1` §12b.1: `DownloadSelection.settled_backups` (≤ 3,
  `MAX_SETTLED_BACKUPS`): unlocked files behind settled, practical
  first, then slow.
- `d992b3f` §12b.2: backups recorded as `shortlisted` settled rows,
  ranks 2–4; `get_next_shortlisted` takes a role; the poll's
  `_cascade(track_id, role, …)` replaces `_cascade_upgrade` and runs
  for every failed or locked row. An at-once `Succeeded` backup stays
  `downloading` and is placed by the next poll (BRIEF hypothesis 1,
  confirmed with a two-poll placement test and a one-line revert).
- Close-out: HISTORY §206, the plan row's progress note, this file.
  CI: pushed with this commit; run id below if recorded.

## 4. Key context for the rest of S12b

- **New tests live in `tests/test_settled_fallback.py`**, importing
  `make_service`/`seed_pending_request`/`get_status`/
  `FakeSoulseekClient` from `test_download_service.py` (precedent:
  `test_download_placement.py`). `_seed_settled_with_backups` and
  `_placing_service` are there to reuse.
- **Fake states:** `_in_flight_status` maps only `"Requested"` to
  `queued`; every other in-flight state is `downloading`.
- **§12b.3:** `search_and_request` (`download_service.py`, after the
  `settled is None` block) calls `_request_and_record` for settled; a
  `SoulseekDownloadError` propagates and the track counts failed. Use
  the classification in `poller._activate_shortlisted_entry`
  (`is_recognized_rejection`) — record the settled row `locked`, then
  request backup rank 2 at once. Backups are currently recorded only
  after settled succeeds, so the order has to change.
- **§12b.4:** `supersede_other_active_for_track` is hard-scoped to
  `role='upgrade'`; parameterize by role. A settled completion is in
  `poller.poll_downloads` (`move_result is not None`) **and**
  `_classify_retry_state` (a locked settled row succeeding on retry).
  `cancel_download` already supersedes an upgrade's backups (§205);
  extend to settled.
- **§12b.5:** `_without_rejected` + `get_unavailable_candidates_since`;
  rename both to cover `FAILED_OUTCOMES`.
- **§12b.6:** CLAUDE.md (sweep line's "went `unavailable`"; a
  settled-fallback fact), `schema.py`'s `shortlisted` comment,
  screenshots of Downloads with a backup row (§0.13), HISTORY.
- **Unchecked:** BRIEF §12b hypotheses 2 (Retry on a failed settled
  row while its backup runs answers `ALREADY_IN_PROGRESS`: check the
  notice's wording on screen) and 3 (all backups fail while an upgrade
  lands: record, don't change).
- **S13 context** is unchanged from `git show 660428e:docs/HANDOFF.md`
  §4.

## 5. Decisions made

- **Backups never include a file ranked ahead of settled**: that file
  is an upgrade already; recording it twice would request it twice.
- **The settled row keeps `rank` NULL**; backups start at 2, as an
  upgrade shortlist does after its rank-1 request.
- **Skills:** `tdd`, red first per commit. Divergence, as in S12: the
  seams came from the brief Kris approved, not a fresh confirmation.

S12's Cancel decisions: HISTORY §205.

## 6. Blockers

None for S12b's remaining items or S13's code. S13's first real
deletion is Kris's to click.

## 7. Files in progress

None uncommitted. **Stopped at S12b's named split point, after
§12b.2** (session budget: ~135 K at the split). §12b.3–§12b.6 have no
code yet. Until §12b.4, a locked settled row that succeeds on retry
while its backup also finished leaves the second file to the §56
safety net (Review), never a second library file.

## 8. Waiting on Kris

- **New (S12b):** veto, if wanted, §5's backup decisions and BRIEF
  §12b's "Code's calls" (3 backups; none for a person's choice).
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

- How long may a settled file sit in a remote queue before Seeker
  gives up or falls back? There is no limit today (BRIEF §12b → "Not
  in this row").
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

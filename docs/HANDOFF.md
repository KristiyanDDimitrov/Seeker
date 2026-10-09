# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S13 close-out (HISTORY §208). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2206 passed, 1 skipped`, 0 failed (+34
  tests). `mypy --strict src/` clean, 143 files; `ruff check src tests
  tools` 0; `uvx radon cc -n D -s src/seeker` nothing.
- **CI:** `1fe6eb7`'s run `37983354387` green: `check` `2178 passed,
  29 skipped`, coverage 94.71 % (floor 92 %); `audit`, no known
  vulnerabilities.

## 2. Where we are

**Round 12 S13 is complete** (☑). Downloads → "Clean up leftover
files…" and `seeker downloads cleanup [--delete]` list the files in
slskd's `downloads/` and `incomplete/` that nothing claims, and delete
confirmed ones that are still unchanged. **Next: S14, the automatic
app-update check** (BRIEF §14, R11 §40), reusing S11's due-check
pattern.

## 3. Session report (S13)

Evidence for each is in HISTORY §208.
- `2700cbd` §13.1: `LeftoverService`, `models/leftover_result.py`,
  `SoulseekClient.get_downloads`, `Application.leftover_service`.
- `084c756` §13.2: `seeker downloads cleanup`; `2f95a30` updates the
  usage test it missed.
- `07be846` §13.3: the Downloads button, `LeftoverCleanupDialog`,
  `LeftoverFile.relative_path` (the dialog's first version elided
  every filename away).
- Close-out: HISTORY §208, a CLAUDE.md fact, `docs/cli.md`, the plan
  tick, this file.
- Dry run (no delete) over the dev tree in the repository and a DB
  copy: 27 files, 728 MB, the A-52 figure.

## 4. Key context for S14

- BRIEF §14 and R11 §40. S11's `sweep_due`/`ui/sweep_scheduler.py` is
  the due-check pattern to reuse; the shell's pool and
  `busy_actions` run it.
- **Carried:** `test_library_track_list_refreshes_after_a_tag_run`'s
  CI timeouts; the callback handler has no socket timeout; Sharing's
  20 s per-row rebuild (S15); `uv build --wheel` picks up a
  gitignored `_build_info_generated.py` (S16). Run the full suite in
  the foreground (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **Claims match by name, loosely** (letters and digits, `_<ticks>`
  stripped), never by path: slskd's sanitizing is not replicated, and
  a looser match only protects more.
- **slskd must answer.** No transfer list, no listing: a superseded
  backup's transfer can still be writing, and only slskd knows.
- **Only slskd's own folder:** `downloads` beside `slskd.yml`, its
  sibling `incomplete/` the other root. Anything else is refused.
- **A 10-minute hold-back** for a file whose transfer the names miss.
- **Skills:** `tdd`, red first per behaviour commit (the service's red
  was its missing module, so a mutation run backs its tests).

## 6. Blockers

**Kris's slskd container was recreated by a test run** (HISTORY §208
→ "Observed"). `docker inspect slskd`: created 2026-10-07 13:03 UTC,
during S33; `/app` and `/shared/music` are bound to deleted pytest
temp directories, and it answers Seeker's saved API key `401`. So the
real app cannot reach slskd now, and slskd's state lives nowhere real.
The sessions must not restart or recreate the container; Kris does
that (Settings → SoulSeek, or `docker compose up` from the per-user
copy). Then a row should find which test reached the real
`bring_up_slskd` (the mounts name `test_wizard_content_is_one_centred_column`
and `test_bring_up_soulseek_real_compose_failure_surfaces_stderr`;
a late worker after monkeypatch teardown is the first guess,
UNVERIFIED) and add a guard so no test can run `docker compose`.

## 7. Files in progress

None uncommitted. S13 is closed at its row boundary.

## 8. Waiting on Kris

- **New (S13):** recreate slskd (§6). Then the first real cleanup,
  yours to click: Downloads → "Clean up leftover files…". The
  configured `SLSKD_DOWNLOAD_DIR` in `.env` is relative
  (`./slskd-data/downloads`), so it resolves against the launch
  directory; Settings' saved value wins when set. Veto, if wanted,
  §5's decisions.
- **From S12b:** HISTORY §206/§207's backup decisions; BRIEF §12b's
  "Code's calls".
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

- Should a superseded row's transfer be cancelled in slskd, so its
  file never becomes a leftover?
- Should the cleanup also offer slskd's own "remove finished
  transfers" (its transfer list grows too)?
- How long may a settled file sit in a remote queue before Seeker
  gives up or falls back?
- Should an activated backup's row say it is a backup?
- Should a downloading row get Cancel too?
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

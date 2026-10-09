# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S14 close-out (HISTORY §209). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2224 passed, 1 skipped`, 0 failed (+18
  tests). `mypy --strict src/` clean, 145 files; `ruff check src tests
  tools` 0; `uvx radon cc -n D -s src/seeker` nothing.
- **CI:** `d7a8681`'s run `37988070262` green: `check` `2196 passed,
  29 skipped`, coverage 94.71 % (floor 92 %); `audit`, no known
  vulnerabilities.

## 2. Where we are

**Round 12 S14 is complete** (☑), and with it Phase C. Settings →
General → "Updates" turns on a check at startup, at most once a day;
a newer release gets one tray notice and a Help entry, "Update
available: X…". **Next: S15, the fresh-eyes QA sweep** over every
screen (BRIEF §15).

## 3. Session report (S14)

Evidence for each is in HISTORY §209.
- `c91085a` §14.1 (refactor): `seeker/due.py`'s `is_due`; `sweep_due`
  delegates to it.
- `22cb652` §14.2: `auto_update_check`, `last_update_check_at`; the
  "Updates" card.
- `71b6bb2` §14.3: `ui/update_scheduler.py`, the tray notice, the Help
  entry; six mutations back the 11 new tests.
- Close-out: HISTORY §209, a CLAUDE.md fact (Packaging), the module
  map, the plan tick, this file.

## 4. Key context for S15

- BRIEF §15. `uv run python tools/screenshots.py` writes every screen
  to `tools/.screens/` in about two minutes. Settings → General now
  has five cards and scrolls at both harness sizes. The Help menu's
  "Update available" entry is not in any screenshot (it is hidden
  until a check finds a release).
- **Carried:** `test_library_track_list_refreshes_after_a_tag_run`'s
  CI timeouts; the callback handler has no socket timeout; Sharing's
  20 s per-row rebuild (S15); `uv build --wheel` picks up a
  gitignored `_build_info_generated.py` (S16). Run the full suite in
  the foreground (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **The stamp goes down before the request:** at most one check a
  day, even offline or rate-limited.
- **Turning it on takes effect at the next launch** (startup only).
- **The tray notice has no notification toggle**; the check is
  opt-in on its own.
- **The badge is a Help menu entry**, not a changed menu title
  (macOS treats "Help" specially; UNVERIFIED what a rename loses).
- **A manual check neither stamps nor shows the entry.**
- **Skills:** none is listed for S14; red first per behaviour item.

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

None uncommitted. S14 is closed at its row boundary.

## 8. Waiting on Kris

- **New (S14):** turn on Settings → General → Updates and relaunch.
  Until v0.1.0 is published, the check logs `NO_RELEASES_PUBLISHED`
  and shows nothing. Veto, if wanted, §5's decisions.
- **From S13:** recreate slskd (§6). Then the first real cleanup,
  yours to click: Downloads → "Clean up leftover files…" (a relative
  `SLSKD_DOWNLOAD_DIR` in `.env` resolves against the launch
  directory; Settings' saved value wins). HISTORY §208's decisions.
- **From S10–S12b:** the decisions in HISTORY §202–§207 and BRIEF
  §12b's "Code's calls"; the first live Cancel, at the keyboard; the
  real `tracks.last_searched_at` migration runs on the next launch.
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

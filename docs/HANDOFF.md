# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S21 close-out commit (HISTORY §164, this handoff, the
  plan tick). Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (2026-10-01): `1576 passed, 1 skipped`, no
  warnings, at every S21 commit.
- **`mypy --strict src/`:** clean, 127 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** run `36831279172` on `effc191` (the close-out commit):
  success, `1548 passed, 29 skipped`, branch coverage 92.82 % (floor
  89).

## 2. Where we are

S1–S21 ticked. **Next: S22** — Performance (BRIEF §22), split point
after §22.1–§22.2 (the poll).

## 3. Session report (S21)

Evidence for every line is in HISTORY §164 (the rewrite script is
pasted there).
- `c652138`: `files/{atomic,deletion,placement,sanitize,naming}.py`.
- `714a12e`: `audio/{analysis,fingerprint,formats,tags,quality}.py`
  (`metadata.py` → `audio/tags.py`; `library/audio_quality.py` →
  `audio/quality.py`).
- `e72f1c1`: `soulseek/docker_setup.py`, `soulseek/sharing_service.py`;
  `compose_template_path()` now `parents[3]`.

## 4. Key context

- **New import paths** (old ones are gone, no shims): `seeker.files.*`,
  `seeker.audio.*`, `seeker.soulseek.docker_setup`,
  `seeker.soulseek.sharing_service`. Patch targets follow, e.g.
  `"seeker.soulseek.docker_setup.platformdirs.user_data_dir"`. The mypy
  mutagen override is now `module = "seeker.audio.tags"`.
- **Logger names changed** for `audio/fingerprint.py`, `audio/tags.py`
  and `soulseek/docker_setup.py` (`__name__`); nothing names them.
- **Moved comments now say `soulseek/docker_setup.py`, `audio/tags.py`
  etc.**, including a few self-references inside the moved files; S24
  (comment hygiene: core) can turn those into "this module".
- Carried: radon not in the env (D-or-worse was 2); coverage margin
  ~3.8 points (CI 92.80 %, floor 89). Never touch slskd or real data.
- **Shell:** zsh does not word-split `$var` and treats a bare `===` as
  a filename expansion; BSD `sed` lacks `\b`.

## 5. Decisions made

- **Modules drop the package's prefix** (`audio/analysis.py`, not
  `audio/audio_analysis.py`); `metadata.py` became `audio/tags.py` so
  it no longer reads as a twin of `library/metadata_service.py`.
- **`migration-architect` diverged on how:** its scripts target
  schema/API migrations; the row took its phase-gate-rollback shape
  only (HISTORY §164).

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's decision (carried):** keep or discard `./slskd-data` (§140).

**Run the stress test** — CLAUDE.md requires it after any lifecycle
change, and S20 is one: `SEEKER_RUN_STRESS_TEST=1 uv run pytest
tests/test_stress_e2e.py` (X9 Pro mounted, Spotify and slskd up).

**Live checks:** S41's checklist, plus carried: S6 Refresh playlists;
S7 drift Scan; S8 Reject-then-Scan, failure reason; S9 mistyped Client
ID → Cancel; S11 Scan summary, Docker-stopped Download, Qt warning in
`seeker.log`, app menu "Seeker"; S12 slskd-stopped outage; S14
one-failing-track Download notice, Tag and Fix cover art summaries;
S15 `seeker downloads review`; S17 Review Confirm/Reject/Replace and a
locked download retrying (`SEEKER_DEBUG_POLL=1`). New for S20: close
to tray → reopen from the tray and from the Dock; fullscreen close →
reopen (comes back filled); quit with a download running (the
confirmation); "start hidden".

## 9. Open questions

- **§18.6 leftovers** (S23 is the natural home):
  `test_next_step_notice_hidden_when_nothing_selected_and_all_set_up`
  (asserts the initial hidden state 50 ms in; wait on the render, e.g.
  the Download button's disable); `test_load_tracks_shows_no_notice_
  when_nothing_was_skipped` and Settings'
  `test_remove_location_cancelled_removes_nothing` (negative after a
  bare wait; wait on completion or `wait_for_workers`).
- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). Not lifecycle
  in S20's sense; still unowned.
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
- Settings shows results and rejections on status labels, not notices,
  as does Duplicates' `_render_fingerprint_result`: S28/S29.
- CLI (carried): print `download`'s failure reasons; catch
  `httpx.HTTPStatusError`; bidi controls in `printable()`; the
  one-by-one upgrade review skips `printable()` (§156).
- `DownloadPoller._activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the transfer id is
  never recorded; the next cascade re-requests it. S22 or X1?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

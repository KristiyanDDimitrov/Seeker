# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S23 close-out commit (HISTORY §167, this handoff, the
  plan tick, CLAUDE.md). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-10-01, at `d31e132`): `1681 passed, 1
  skipped`, no warnings.
- **`mypy --strict src/`:** clean, 127 files. **`ruff check src
  tests`:** 0 findings.
- **Coverage:** 93.79 % branch, measured as CI runs (X9 Pro tests
  deselected). CI floor now 92 %.
- **CI:** run `36843176493` (close-out) failed one test, CI-only
  (offscreen screen size, see §4); coverage there 94.10 %. Fixed in
  `791fb6c`; the run for this push is noted below.

## 2. Where we are

S1–S23 ticked. **Next: S24 — comment and config hygiene: core** (§24;
split point after the services half).

## 3. Session report (S23)

Evidence for every line, with before/after tables, is in HISTORY §167.
- `39392b8`, `9582a8f` §23.1: generated-file tag tests plus
  `tests/fixtures/silent.m4a`; `tags.py` 100 % on CI.
- `d4d084d` §23.2 CLI (96 %); `d379add` §23.3 entry points (100 %);
  `6ab9307` §23.4 Review splitter round trip.
- `cf8bfd1` §23.6: FLAC key written to `INITIALKEY` and `KEY`.
- `8f73b4d` §23.6: a tag save that outgrows the padding goes through
  `files.atomic.rewrite_via_copy`.
- `9523d38` §18.6 leftovers wait on completion; `9a2b873`
  `UploadEtaTracker` tests (55 → 100 %).
- `d31e132` §23.5: `--cov-fail-under` 89 → 92.

## 4. Key context

- **mutagen grows a tag by moving the audio in place** (`insert_bytes`
  → `move_bytes`, same inode). A simulated crash corrupted MP3, FLAC
  and faststart M4A; WAV, AIFF and `moov`-last M4A keep tags at the
  end. mutagen's `padding=` callback runs before any write in all six
  layouts, which is how `save_tags` decides (now in CLAUDE.md).
- **The first save of an untagged file is a resizing save** (padding
  −39 to −84 bytes), so it takes the copy path, as does the first
  cover embed. Later text/analysis re-saves stay in place.
- **Local pytest uses Cocoa, CI offscreen (800×800 screen).**
  Reproduce a CI-only UI failure with `QT_QPA_PLATFORM=offscreen`
  first (now in CLAUDE.md). The open focus-search CI flake may be the
  same class; untested.
- **CI-equivalent coverage:** `pytest -p no_x9` with a 7-line
  `pytest_collection_modifyitems` plugin that deselects items whose
  `skipif` reason mentions x9-pro (§167). Local runs with the drive
  mounted overstate CI by up to a few points per module.
- Carried: radon not in the env. Never touch slskd or real data. zsh
  does not word-split `$var`; BSD `sed` lacks `\b`.

## 5. Decisions made

- **Seams came from the brief, not a new ask.** The `tdd` skill wants
  seams confirmed with the user; §23 already names them
  (pre-approved), so the brief's list stood in. Recorded divergence.
- **Copy only on a resizing save, not on every save:** copying a
  50 MB WAV for a text tag that fits the padding is wasted I/O on an
  external drive; the padding callback makes the distinction exact.
- **The X9 Pro tag tests stay:** the only coverage of real files'
  existing tags. **Floor 92, not 92.79:** rounded down, as before.
- **`upload_eta` and the §18.6 leftovers joined this row:** the first
  is in §23's gap table; the last handoff named S23 for the second.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S30 visual direction; S39 bundle identifier;
S42 publishing commands; X1 and X2 (optional).

**Next launch will migrate the real DB** (S8, rehearsed, §144, §145).

**Kris's decision (carried):** keep or discard `./slskd-data` (§140).

**Run the stress test** (after S20's lifecycle change):
`SEEKER_RUN_STRESS_TEST=1 uv run pytest tests/test_stress_e2e.py`
(X9 Pro mounted, Spotify and slskd up).

**Live checks:** S41's checklist, plus carried: S6 Refresh playlists;
S7 drift Scan; S8 Reject-then-Scan, failure reason; S9 mistyped Client
ID → Cancel; S11 Scan summary, Docker-stopped Download, Qt warning in
`seeker.log`, app menu "Seeker"; S12 slskd-stopped outage; S14
one-failing-track Download notice, Tag and Fix cover art summaries;
S15 `seeker downloads review`; S17 Review Confirm/Reject/Replace and a
locked download retrying; S20 tray/Dock reopen, fullscreen close,
quit with a download running, "start hidden". **New for S23:** Tag a
FLAC and check its key appears in Rekordbox, Traktor and Serato
(the field choice rests on TagLib and Mixxx; UNVERIFIED for those
three, whose docs never name the field); Tag a file with no cover
yet on the X9 Pro (the copy path on exFAT).

## 9. Open questions

- Closing the wizard or Settings mid-wait does not cancel the Spotify
  wait (port 8888 and the token lock held up to 300 s). Still unowned.
- Late-worker defect: `_handle_task_finished` raises on a button
  destroyed mid-task (§148 addendum); logged at CRITICAL since §11.3.
- Settings shows results and rejections on status labels, not notices,
  as does Duplicates' `_render_fingerprint_result`: S28/S29.
- CLI (carried): print `download`'s failure reasons; catch
  `httpx.HTTPStatusError`; bidi controls in `printable()`; the
  one-by-one upgrade review skips `printable()` (§156).
- `DownloadPoller._activate_shortlisted_entry`: if slskd dies between
  `request_download` and `get_download_status`, the transfer id is
  never recorded; X1 is the natural home.
- A leftover `<name>.<uuid>.tmp` beside a track after a real crash is
  never cleaned up (the scanner ignores it). Rare; X1-adjacent.

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

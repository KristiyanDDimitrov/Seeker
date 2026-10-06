# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S24 close-out commit (HISTORY §169, this handoff, the
  plan row). Tree clean apart from the untracked `Claude outputs/`.
- **Local** (at `e003f92`, X9 Pro not mounted): pytest `1654 passed,
  29 skipped`; `mypy --strict src/` clean, 127 files; `ruff check src
  tests` 0.
- **CI:** run `37484932869` (at `e60a71d`): **success**, `1654
  passed, 29 skipped`, coverage 94.09 % (floor 92 %).

## 2. Where we are

S1–S24 ticked. **Next: S25**, comment hygiene in `src/seeker/ui/`
(648 A.10 matches; split point after `main_window.py` and
`theme.py`).

## 3. Session report (S24 part 2)

Evidence, with before/after counts, is in HISTORY §169.
- `95369e0` §24 the rest: 25 files' comments (core modules, config
  and packaging files); history references outside `ui/` that are
  not `HISTORY §N` pointers 72 → 0. AST check: no code change.
- `e003f92` §24: two `--help` strings printed roadmap item numbers;
  new sweep test `test_no_help_text_carries_development_history`
  (failed on HEAD, passes now).

## 4. Key context

- **Old "item N" numbers are not always HISTORY §N.** Mappings found
  so far: item 5/38 → §38–§40; item 66's status split → §56, its
  bounded retry → §66; item 68 (ffmpeg) → §69; item 77/P8 → §78;
  item 81 → §81, §83. Check `docs/history/README.md` (or `awk` the
  entry for a keyword) before writing a pointer; drop it when unsure.
- **Keep `HISTORY` and `§N` on one line** — a wrap between them
  counts as a leftover.
- **Count used:** `P='(HISTORY §[0-9]+((, | and |/)§[0-9]+)*)|<A.10
  pattern>'; grep -rhoE "$P" src/seeker/ui | grep -vc '^HISTORY §'`.
- **Proving "no code change":** blank every docstring, compare
  `ast.dump` at HEAD and in the tree (~25 lines; HISTORY §169).
- **Rewrapping pitfalls:** a "same comment prefix" paragraph joiner
  merges paragraphs with no blank comment line between them and
  turns a line-final hyphen into "mid- stream"; partial-line edits
  leave overlong lines (ruff E501 finds them). Grep the diff after.
- **User-facing strings are code, not comments:** a history leak in
  `--help`, a label or a tooltip is its own behaviour commit with a
  failing test first (as `e003f92`). Expect the same in `ui/`
  (`help_text.py` has 20 matches).
- Carried: radon not in the env. Never touch slskd or real data. zsh
  does not word-split `$var`; BSD `sed` lacks `\b`. CI runs
  offscreen (800×800); reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first.

## 5. Decisions made

- **Platform observations stay in comments** (working agreement 4
  outranks §24's "delete confirmed live" rule); only their dates go.
- **Comments naming moved code were corrected in the same pass**
  (`DownloadPoller`, `settle_target`, `ui/tray.py`): a stale name is
  the same kind of rot as a stale date.
- **The A.10 count is the measure**, not tech-debt-tracker (run:
  4,451 → 4,443 items), which has no category for this debt.

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

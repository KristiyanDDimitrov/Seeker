# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S24 part-1 close-out commit (HISTORY §168, this
  handoff, the plan row). Tree clean apart from the untracked
  `Claude outputs/`.
- **Local pytest** (2026-10-06, at `2fe4768`): `1653 passed, 29
  skipped` — the X9 Pro was not mounted, so its 28 tests skipped as
  on CI (with it mounted the count is `1681 passed, 1 skipped`).
- **`mypy --strict src/`:** clean, 127 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** run `37459977454` (at `028e73f`): **success**, `1653
  passed, 29 skipped`, coverage 94.10 % (floor 92 %).

## 2. Where we are

S1–S23 ticked. **S24 stopped at its split point** (services half
done; the session passed the 150 K ceiling at ~200 K). **Next: S24
part 2**, the rest of §24 (see §7), then S25.

## 3. Session report (S24 part 1)

Evidence, with the before/after counts, is in HISTORY §168.
- `2fe4768` §24 services half: 21 files' comments and docstrings;
  history references outside `ui/` that are not `HISTORY §N`
  pointers 250 → 72; pointers 66 → 106. AST check: no code change.


## 4. Key context

- **Old "item N" numbers are not always HISTORY §N.** The duplicate
  detector's "item 5" is §38–§40; "item 77/P8" is §78; "item 62" is
  §56's Phase 7 plus §62. Check `docs/history/README.md` before
  writing a pointer; drop the reference when unsure.
- **Keep `HISTORY` and `§N` on one line.** The count treats a `§N`
  not preceded by `HISTORY ` (or in a list like `HISTORY §63, §66`)
  as a leftover, and a wrap between them makes a false leftover.
- **Count used** (A.10's pattern, then pointers excluded):
  `grep -rhoE "(HISTORY §[0-9]+((, | and |/)§[0-9]+)*)|<A.10 pattern>"
  src/ --exclude-dir=ui | grep -vc '^HISTORY §'` → 72 now.
- **Proving "no code change":** parse each changed file at HEAD and in
  the tree, blank every docstring, compare `ast.dump` (~15 lines).
  The tech-debt-tracker scanner has no category for this debt; the
  A.10 count is the measure.
- **Partial-line edits leave ragged or overlong lines**: ruff E501
  finds the long ones; grep the diff for `:: `/`/ ` after a rewrap.
- Carried: radon not in the env. Never touch slskd or real data. zsh
  does not word-split `$var`; BSD `sed` lacks `\b`. CI runs
  offscreen (800×800); reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first.

## 5. Decisions made

- **Stopped at the split point rather than finishing §24:** plan rule
  3 (the row overran the 150 K ceiling).
- **Platform observations stay in comments** (working agreement 4
  outranks §24's "delete confirmed live" rule): `login_item.py` keeps
  its macOS observation, the date dropped, the packaged-build claim
  marked UNVERIFIED.
- **A real peer username in a comment became `<name>`**
  (`soulseek/client.py`).

## 6. Blockers

None.

## 7. Files in progress

S24 part 2 (`partially_done`, none edited yet): the 72 leftovers in
`audio/`, `models/`, `database/`, `files/`, `cli.py`, `main.py`,
`main_ui.py`, `_build_info.py` (top five in HISTORY §168; the rest 1–5 each), and
§24's config files (`pyproject.toml`, `packaging/*`,
`docker-compose.yml`). Narrative without a number needs a wider grep:
`grep -nE "20[0-9]{2}-[0-9]{2}-[0-9]{2}|[Cc]onfirmed live|real bug|Phase [0-9]|CLAUDE\.md|[Bb]rief|[Rr]oadmap"`.

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

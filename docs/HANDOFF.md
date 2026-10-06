# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S25 close-out commit (HISTORY §170, this handoff, the
  plan row). Tree clean apart from the untracked `Claude outputs/`.
- **Local** (at `94ac488`, X9 Pro not mounted): pytest `1655 passed,
  29 skipped`; `mypy --strict src/` clean, 127 files; `ruff check src
  tests` 0.
- **CI:** see section 3's last line for the run id at the close-out.

## 2. Where we are

S1–S25 ticked. **Next: S26**, guard nested locations and guided
cleanup (§26; split point after §26.2). It migrates data: rehearse on
a copy of the real DB (§0.7) and ask before anything destructive at
scale (memory: destructive-test scope).

## 3. Session report (S25)

Evidence, with before/after counts, is in HISTORY §170.
- `e9aec6c` §25 split point: `main_window.py` and `theme.py`
  comments, docstrings and QSS comments.
- `51d384e` §25 behaviour: the Scan tooltip said "roadmap item R1";
  new `test_no_help_text_constant_carries_development_history`
  (failed on HEAD, passes now).
- `94ac488` §25 the rest of `ui/` (27 files). History references in
  `src/` that are not `HISTORY §N` pointers: 0 (`ui/` 499 → 0). AST
  check (docstrings blanked, QSS comments stripped): no code change.

## 4. Key context

- **Phase H is done:** the round's exit criterion "`grep -rcE
  "Roadmap item|round [0-9]+|§[0-9]"` over `src/` reports 0 outside
  `HISTORY §N` pointers" holds now. New comments must keep it (§0.9).
- **QSS comments are string data.** theme.py's `/* … */` comments sit
  inside the stylesheet f-strings, so an AST "no code change" check
  must strip them; the stylesheet text shrinks, nothing else.
- **Old labels map unevenly to entries;** §170 lists every mapping
  used (C5 → §107, R7 → §90, round 9 §7.1 → §133, …). `§97` is not
  in the index.
- **Rewrap pitfalls (added to §169's):** join `/`-ended lines with no
  space; never split a dotted name (`QApplication.setStyleSheet()`)
  or `WA_DeleteOnClose`; check paragraphs did not merge.
- Carried: radon not in the env; never touch slskd or real data;
  zsh does not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` (800×800) first.

## 5. Decisions made

- **`pr-review-expert` not run for S25:** the comment commits are
  proven code-identical by the AST check, and the one behaviour
  commit is a one-string change with its own sweep test. Recorded as
  a divergence from the plan's skills table.
- **Platform observations stay in comments** (working agreement 4);
  their dates and round labels went, "confirmed live" stayed.
- **Unmappable labels were dropped, not guessed** (round 8 §12.x,
  round 9 §3.1, item 56/62/64/65 phases).

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
yet on the X9 Pro (the copy path on exFAT). **New for S25:** the
Scan button's tooltip ends at the format list.

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

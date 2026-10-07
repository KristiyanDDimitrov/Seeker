# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S35b part 1 close-out (HISTORY §187). Tree clean apart
  from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2002 passed, 1 skipped` (+15). `mypy --strict src/` clean,
  138 files; `ruff check src tests tools` 0.
- **CI:** pending for the close-out push; see the follow-up handoff commit.

## 2. Where we are

S1–S35a ticked; **S35b part 1 done** (Review, Sharing), stopped at the
row's per-page split point on budget. **Next: S35b part 2** (BRIEF §35,
second bullet): Help and Support, then Settings. Tick S35b when part 2
lands.

## 3. Session report (S35b part 1)

Evidence in HISTORY §187.
- `a45607e`: Review — section titles in `sectionHeaderLabel`, read as
  tasks; a subtitle covering all three sections on one line.
- `73aafeb`: Sharing — counts and tables first; "How sharing works"
  behind `ui/disclosure.Disclosure`, remembered in
  `SeekerConfig.sharing_explainer_open`; errors on the notice (test
  first); harness screen `sharing-explained`.
- `ee85270`: Sharing — Shared/Not shared lamps; upload states as
  Queued/Uploading/Sent/Failed with lamps; `refresh_lamps()` on a
  theme switch.

## 4. Key context

- **Part 2's known defect:** Support's links paint pure #0000FF in
  dark (unreadable). Likely `QPalette.Link`/`LinkVisited` unset in
  `theme.build_qpalette`; a `RichLabel` link takes the palette's Link
  colour. Write the failing test first (sample the link colour or
  assert the palette role), and check Help's links too.
- **Settings still puts results on labels** (`settings_window.py`
  ~:577–1161) — the channel recipe below applies; the wizard's Spotify
  and Library steps likewise (outside §35's list: note, don't take).
- **Settings visual gaps seen in the harness:** `QGroupBox` titles in
  the system font (Library's cards use `sectionHeaderLabel` inside
  `theme.make_card`); fields run the full ~930 px width (Client ID);
  the subtitle wraps at 1280; "About Seeker" floats under the tab
  widget. Help's body runs the full width (~140 chars a line): give
  it a reading measure, as Sharing's explainer has (80 chars).
- **Channel fix recipe** (unchanged): `InlineNotice` at the top of the
  content, `FeedbackTarget(status_label, notice)`,
  `on_error=self.feedback.show_error` on every worker.
- **A lamp bakes the palette in at render**: a table that renders only
  on a slow poll needs a repaint hook in `MainWindow.on_theme_changed`
  (Sharing's `refresh_lamps` repaints the last snapshot).
- **A disclosure body that is a plain label crushes the tables** at
  960×640; scroll it and give it stretch while open.
- Carried: `set -o pipefail` before `pytest … | tail && git commit`;
  never touch slskd or real data; the full suite takes ~4 min, run it
  in the background; `run_busy_worker` has no double-start guard;
  judge fine detail on a 2× Cocoa grab.

## 5. Decisions made

- **Sharing's explainer sits last and closed** ("counts and tables
  first"); open, it scrolls within a table's share of the height.
  Promoted to CLAUDE.md (Disclosure bullet).
- **Review keeps its Runner-up column at 960**: it says what Reject
  falls through to; the elided Candidate has its full text on hover.
- **Upload states stay forgiving**: an unknown slskd state reads raw,
  and the raw string is always the tooltip, since a populated upload
  is still unconfirmed live (HISTORY §62).
- **Review's "FLAC, 1050kbps" descriptors left as stored**: unifying
  with "MP3, 320 kbps" changes stored data, not a restyle.

## 6. Blockers

None.

## 7. Files in progress

None: part 1 is committed whole at a page boundary. Part 2 starts
fresh on `src/seeker/ui/pages/static_pages.py`, `help_text.py` and
`settings_window.py`.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** a real upload on Sharing (does
slskd's state read as Queued/Uploading/Sent?), plus S35a's (Downloads
lamps, meter and busy bar; the dark Duplicates band), S34's (Library's
Cover art column, the first scan's time on the X9 Pro, the Dashboard's
lamps and meter, playlist counts) and everything carried in
`git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account wizard with
Docker, nested-location Fix…, the stress test, `qsvg`, Barlow and nav
icons in the packaged app, keyboard focus and VoiceOver).

## 9. Open questions

- **Refresh playlists drops the Dashboard's selection** (pre-existing:
  `_populate_playlists`' `clear()` fires `currentItemChanged(None)`).
  A test-first fix of its own; not part of §35.
- Carried from S35a: a Downloads failure reason elides at 960; a
  Duplicates group's first row is taller; History says "MP3 320kbps"
  where Search says "MP3, 320 kbps" (Review too, see §5); the
  Dashboard's table does not show a Library selection;
  `poll_selected_playlist` renders a pre-switch result for one tick.
- Carried unchanged: `git show cd3ba1a:docs/HANDOFF.md` §9 and
  `git show 8eee663:docs/HANDOFF.md` §9 (Settings' subtitle wrap, the
  wizard's empty progress row).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

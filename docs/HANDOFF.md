# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S35b part 2 close-out (HISTORY §188). Tree clean apart
  from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2006 passed, 1 skipped`:
  `test_a_cell_widget_paints_the_rows_own_background[dark]` and
  `[light]`, failing identically on the pre-session `4cd9329`
  (`2 failed, 2000 passed`); environmental, see §4. `mypy --strict src/` clean,
  138 files; `ruff check src tests tools` 0.
- **CI:** `aea4ccc`'s run `37685387304` green.

## 2. Where we are

S1–S35a ticked; **S35b parts 1 and 2 done** (Review, Sharing; Help,
Support), stopped at the row's per-page split point on budget.
**Next: S35b part 3, Settings** (BRIEF §35, last bullet: §29's tabs,
restyled). Tick S35b when it lands.

## 3. Session report (S35b part 2)

Evidence in HISTORY §188.
- `59e92bd`: links read in both themes — `QPalette.Link`/`LinkVisited`
  = `ACCENT` (test first; failed on `HEAD` both platforms).
- `df11bc6`: `theme.set_reading_measure` replaces Sharing's own cap
  (refactor).
- `571e105`: Help — panel-lettering sections, `theme.reading_column`,
  paths and build in one card, sentence-case buttons; clipping guard.
- `404c2c4`: Support — Donate / Other ways to help, the subtitle no
  longer repeated; the column grows to its cap.

## 4. Key context

- **Never cap one wrapped label inside a wider layout row** — it is
  measured at the row's width and clips (186 px for 192 needed). Cap
  the column: `theme.reading_column` (now in CLAUDE.md).
- **Settings, part 3, what the harness shows:** `QGroupBox` titles in
  the system font (Library's cards: `sectionHeaderLabel` inside
  `theme.make_card`; `tagging_panel._job_card` is the pattern: title,
  one muted sentence, controls); the Client ID field and destination
  combos run the full width; the subtitle wraps at 1280 (shorten it);
  "About Seeker" floats under the tab widget (the Help menu has About
  too). A reading column suits General, Connections and Matching;
  Library's locations table wants the width.
- **Settings' channel bug, test first:** five result labels
  (`default_destination_status_label`, `destinations_status_label`,
  `spotify_status_label`, `test_connection_status_label`,
  `update_credentials_status_label`) carry outcomes and errors that
  `run_worker` wipes. Recipe: `InlineNotice` at the top of the
  content, `FeedbackTarget(status_label, notice)`,
  `on_error=self.feedback.show_error`. `start_at_login_status_label`
  is a standing note, not a result: leave it.
- **Offscreen spin boxes show "90,0"** (the machine's locale), not a
  Settings bug.
- **`test_a_cell_widget_paints_the_rows_own_background` (dark,
  light) fails on Cocoa, full suite and alone, on this session's HEAD
  and on `4cd9329` alike** (same code passed in part 1): one channel
  value off on a Cocoa grab; passes offscreen. Suspect: a display
  colour-profile change, UNVERIFIED. Re-check before believing a
  count; HISTORY §188.
- Carried: a lamp bakes the palette in at render (a slow-poll table
  needs a repaint hook in `on_theme_changed`); `set -o pipefail`
  before `pytest … | tail && git commit`; never touch slskd or real
  data; the full suite takes ~4 min, run it in the background;
  judge fine detail on a 2× Cocoa grab.

## 5. Decisions made

- **Help and Support read as a column, not a full-width page**: 80
  characters, the card and buttons inside it. Promoted to CLAUDE.md.
- **Buttons are sentence case** ("Open data folder"), as the rest of
  the app; `error_text.DETAILS_HINT` names the button and follows.
- **Support drops its "Support Seeker" paragraph**: it said what the
  subtitle says. "no telemetry"/"no paid tier" live in the subtitle.

## 6. Blockers

None.

## 7. Files in progress

None: part 2 is committed whole at a page boundary. Part 3 starts
fresh on `src/seeker/ui/settings_window.py` (1,517 lines: grep, read
by range).

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** Support's links in both themes on a
real display; a real upload on Sharing (does slskd's state read as
Queued/Uploading/Sent?); S35a's (Downloads lamps, meter and busy bar;
the dark Duplicates band), S34's (Library's Cover art column, the
first scan's time on the X9 Pro, the Dashboard's lamps and meter,
playlist counts) and everything carried in
`git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account wizard with
Docker, nested-location Fix…, the stress test, `qsvg`, Barlow and nav
icons in the packaged app, keyboard focus and VoiceOver).

## 9. Open questions

- **Refresh playlists drops the Dashboard's selection** (pre-existing:
  `_populate_playlists`' `clear()` fires `currentItemChanged(None)`).
  A test-first fix of its own; not part of §35.
- Carried from S35a/S35b part 1: a Downloads failure reason elides at
  960; a Duplicates group's first row is taller; History says "MP3
  320kbps" where Search says "MP3, 320 kbps" (Review too: stored
  `quality_descriptor`); the Dashboard's table does not show a Library
  selection; `poll_selected_playlist` renders a pre-switch result for
  one tick.
- Carried unchanged: `git show cd3ba1a:docs/HANDOFF.md` §9 and
  `git show 8eee663:docs/HANDOFF.md` §9 (the wizard's empty progress
  row).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

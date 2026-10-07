# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S35b part 3 close-out (HISTORY §189). Tree clean apart
  from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2012 passed, 1 skipped`, no failures.
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** see the close-out's push (recorded in the follow-up commit).

## 2. Where we are

S1–S35b ticked (S35b closed: Review, Sharing; Help, Support;
Settings). **Next: S36, README images and final visual QA** (BRIEF
§36): `tools/screenshots.py --readme`, commit the images, then sweep
every page in both themes at both sizes. Small nits are fixed in
the row; larger ones become new rows here.

## 3. Session report (S35b part 3)

Evidence in HISTORY §189.
- `7e22087`: refactor — `locations_notice` → `library_notice`, at the
  Library tab's top.
- `ff72275`: Settings outcomes on the tab's notice (test first: five
  tests timed out on `HEAD`); `connections_notice`;
  `SpotifyAuthorizationWait.start(on_error=)`.
- `1f1b6f9`: refactor — `tagging_panel._action_group` →
  `theme.section_card`.
- `28eb690`: Settings restyle — titled cards, reading column on
  General/Connections/Matching, SoulSeek split from its credentials,
  short subtitle, combos at a name's width.
- `e711c7c`: the floating "About Seeker" button removed (Help menu
  keeps About).

## 4. Key context

- **A `QFormLayout` row `addRow("", widget)` makes a visible empty
  label that still takes a line**, even when `widget` is hidden. Put
  progress text beside its button (`theme.action_row(button, label)`)
  and span an optional widget with `addRow(widget)`.
- **`test_a_cell_widget_paints_the_rows_own_background` passed on
  Cocoa this session** (failed in part 2 on two commits). Consistent
  with part 2's display-profile suspicion, still UNVERIFIED; if it
  fails again in S36, compare against offscreen before believing it.
- **For a tall grab of one screen**, temporarily set `SIZES` in
  `tools/screenshots.py` (e.g. `((1280, 1300),)`), render with
  `--page`/`--theme`, then `git checkout tools/screenshots.py`. There
  is no CLI flag for it; S36 could add one if it needs it twice.
- **Offscreen spin boxes show "90,0"** (the machine's locale), not a
  Settings bug.
- Carried: a lamp bakes the palette in at render (a slow-poll table
  needs a repaint hook in `on_theme_changed`); `set -o pipefail`
  before `pytest … | tail && git commit`; never touch slskd or real
  data; the full suite takes ~4.5 min, run it in the background (and
  wait on pytest's ` in N.NNs` line, not "passed": ruff prints "All
  checks passed!"); judge fine detail on a 2× Cocoa grab.

## 5. Decisions made

- **A titled section is `theme.section_card`, never a `QGroupBox`**
  (system-font title). None is left in `src/`. Promoted to CLAUDE.md.
- **Each Settings tab reports on one notice at its top**
  (`library_notice`, `connections_notice`, `thresholds_notice`);
  a status label beside a button carries progress only. A cancelled
  Spotify authorization stays in the status label: it answers the
  user's own click, so it is not raised as an error.
- **About lives only in the Help menu.** It is not a setting.
- **Save default destination is no longer primary**: it was the only
  primary save on the page.
- **SoulSeek button text unchanged** ("Update SoulSeek credentials"):
  `application.py` and test comments name it; the card is titled
  "SoulSeek credentials" to match.

## 6. Blockers

None.

## 7. Files in progress

None: S35b is committed whole.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`).

**Live checks (S41 checklist):** Settings on a real display, both
themes (cards, the reading column, a real Re-authorize's progress
beside its button); Support's links in both themes; a real upload on
Sharing (does slskd's state read as Queued/Uploading/Sent?); S35a's
(Downloads lamps, meter and busy bar; the dark Duplicates band),
S34's (Library's Cover art column, the first scan's time on the X9
Pro, the Dashboard's lamps and meter, playlist counts) and everything
carried in `git show cd3ba1a:docs/HANDOFF.md` §8 (fresh-account
wizard with Docker, nested-location Fix… — now Settings → Library →
Fix…, the stress test, `qsvg`, Barlow and nav icons in the packaged
app, keyboard focus and VoiceOver).

## 9. Open questions

- **Refresh playlists drops the Dashboard's selection** (pre-existing:
  `_populate_playlists`' `clear()` fires `currentItemChanged(None)`).
  A test-first fix of its own; not part of §35.
- Settings' locations table keeps a minimum height that shows empty
  space under three rows; Playlist destinations' list is tall for four
  playlists. Cosmetic: S36's sweep can judge them against the rest.
- Carried from S35a/S35b: a Downloads failure reason elides at 960; a
  Duplicates group's first row is taller; History says "MP3 320kbps"
  where Search says "MP3, 320 kbps" (Review too: stored
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

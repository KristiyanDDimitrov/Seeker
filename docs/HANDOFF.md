# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S33 close-out (HISTORY §183). Tree clean apart from the
  untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `1944 passed, 1 skipped` (+12, S33's new
  tests). The Cocoa-only pair
  `test_a_cell_widget_paints_the_rows_own_background[dark]`/`[light]`
  passed this full run and failed once in a narrower run: still
  order-dependent (§181). `mypy --strict src/` clean, 137 files;
  `ruff check src tests tools` 0.
- **CI:** see the S33 handoff commit (filled in after the push).

## 2. Where we are

S1–S33 ticked. **Next: S34, Dashboard and Library** (BRIEF §34).

## 3. Session report (S33)

Evidence in HISTORY §183.
- `f77ab07`: the wizard as one centred 560 px column with the
  wordmark, `#pageTitleLabel` titles and `ui/step_indicator.py`.
- `01e403b`: three numbered Spotify registration steps; the Redirect
  URI is a read-only field beside Copy.
- `68ae035`: `status_lamp.StatusChip` for the Docker and SoulSeek
  states; fixes the busy bar left running after a failed bring-up.
- `8e52af0`: one primary action per step; form regrouped.
- `75f3cdb`: SoulSeek outcomes on `soulseek_notice`; the status line
  is progress only.

## 4. Key context

- **New reusable pieces for S34/S35:** `StatusChip(lamp, text)` with
  `set_state(lamp, text)` (a standalone state, e.g. Sharing's slskd
  state); `StepIndicator(names)` with `set_current`/`mark_skipped`;
  `StatusLamp.set_lamp`. QSS lives in `theme._status_qss`
  (`QFrame#statusChip`, `QLabel[stepState]`, `QLabel#stepNumber`,
  `QFrame#stepConnector`); `CHIP_HEIGHT`/`CHIP_RADIUS` are tokens.
- **The plain-text sweep wants `setToolTip(plain_tooltip(...))`
  literally**: a conditional around the call fails
  `test_every_dynamic_tooltip_goes_through_plain_tooltip`.
- **A `QStackedWidget` is as tall as its tallest page** unless the
  hidden pages are `QSizePolicy.Ignored` (the wizard's
  `_on_step_changed`).
- **`set -o pipefail` before `pytest … | tail && git commit`**: without
  it a failing run still commits (it happened once this session; the
  failures were the known Cocoa pair, nothing new).
- From S32, still open: the strip's progress bar is the accent (S34's
  segmented amber meter should cover `activity_strip_bar`); lamps are
  not yet in table cells (S34, S35a), and `fit_widths` and
  `ElidedTextDelegate` must count the icon's width.
- Carried gotchas (unchanged, full list in `git show 8eee663:docs/HANDOFF.md`
  §4): never touch slskd or real data; zsh does not word-split `$var`;
  CI-only UI failures reproduce with `QT_QPA_PLATFORM=offscreen`; a
  shared fake missing a method stalls the suite (§171); judge fine
  detail on a 2× Cocoa grab, the harness writes 1×.

## 5. Decisions made

- **The current wizard step is an amber ring, not the accent.** The
  step waits on the user, which is what a ring means everywhere else;
  the accent stays for selection, focus and the primary action.
- **No numbers on the step indicator.** The lamps' order carries the
  sequence; numbers appear only where the content is a sequence of
  instructions (the Spotify steps).
- **Only the SoulSeek step's outcomes moved to a notice.** Spotify's
  and Library's status labels are written by helpers shared with
  Settings; moving them belongs with Settings' own status-label work
  (S35b).
- **The wizard's title is plain text in the title role**, so
  `DONE_PAGE_TITLE_HTML` became `DONE_PAGE_TITLE`.

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** the S39 bundle identifier
(`io.github.kristiyanddimitrov.seeker`), the S42 publishing commands,
X1 and X2 (optional).

**A cheap veto:** the brows over "ee" in the wordmark (`9ff777b`),
now also at the top of the wizard. Deleting the overlay is a
one-commit revert.

**Live checks (S41 checklist):** the wizard on a fresh account now
also shows the chips' live states against a real Docker (not running
→ Launch → running; connecting → connected); the nested-location
Fix… with the X9 Pro mounted (keep `Music`, compare §172's counts);
the stress test; the packaged app's combo chevron and checkbox tick
(`qsvg`), Barlow in the titles, and the nav icons (`icons/lucide/`
must reach `_MEIPASS`; QtSvg collected); keyboard focus and VoiceOver
on a real Mac (VoiceOver should read the step indicator as "Step 1 of
3: Spotify"); hover tooltips on elided cells; the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- **The cell-widget pixel test on Cocoa** is order-dependent (§181):
  hover from the cursor? It does not affect CI.
- **Result messages still on status labels:** `settings_window.py`
  ~:577–1161, 12 sites in `duplicates_page.py` :440–979, and the
  wizard's Spotify and Library steps (shared helpers); fold into
  S35a/S35b or its own commit.
- The wizard's empty progress line still takes a row above the
  SoulSeek notice (a ~20 px gap); hide it when empty if it bothers.
- Settings' subtitle leaves "thresholds." alone on its second line at
  the 90-character measure (copy, S35b).
- Carried unchanged: see `git show 8eee663:docs/HANDOFF.md` §9 (the
  Spotify wait on close, §148's late-worker button, §156's CLI items,
  X1's leftovers, the Dashboard Status links clipping (S34), Review's
  column budget at 960 (S35b), and the rest).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** the S30 close-out (HISTORY §180), after `17bfc32`. Tree
  clean apart from the untracked `Claude outputs/`. No `src/` change
  this session: docs, screenshots and a scratch module only.
- **Local (Cocoa):** pytest `1825 passed, 1 skipped`. `mypy --strict src/`
  clean, 133 files; `ruff check src tests tools` 0.
- **CI:** `10af293`'s run `37602884021` green.

## 2. Where we are

S1–S29 ticked. **S30 stopped at §30.3, its hard stop.** §30.1 and
§30.2 are done; the box stays unticked until Kris picks. **Next: record
Kris's answer in `docs/design/visual-direction.md` → "Decision" (with
the date), tick S30, then S31.** S31–S36 must not start before that.

## 3. Session report (S30)

Evidence in HISTORY §180.
- `8442297` §30.1: Booth and Harmonic rendered over the real widgets
  (Dashboard, Review, Settings, wizard; both themes), plus the current
  Dashboard and a sheet of every key pill. 19 images in
  `docs/design/visual-direction/`, and the scratch module that
  rendered them in `scratch/`.
- `17bfc32` §30.2: `docs/design/visual-direction.md` holds tokens,
  type, spacing and radius, the contrast table, Lucide, the real-data
  finding and the recommendation. Linked from `docs/README.md`.

## 4. Key context

- **The decision document holds every value S31 needs.** Each token
  for both directions and both themes, the type roles and scale, and
  the wheel algorithm. `scratch/direction.py` is the executable form
  (`SEEKER_SCRATCH_DIRECTION=booth|harmonic`, through
  `scratch/render.py <out-dir>`). It reaches into private names and
  needs the Barlow TTFs in `scratch/fonts/`, which are not committed.
  S31 bundles the face properly.
- **Booth's `ON_ACCENT` is dark text in dark mode** (`#0A1422`): white
  on the lit blue is 2.82:1. `Palette.ON_ACCENT`'s "always white"
  comment and `TwoToneProgressBar`'s docstring change with it.
- **The segmented meter is per-instance QSS** (`::chunk { width: 5px;
  margin: 1px }`) through `style_determinate_progress_bar`. A global
  `::chunk` rule would still kill the indeterminate animation (the
  standing comment in `_progress_qss`). The mockup set the bar's
  format to "" and showed the percentage as `SECONDARY_ROLE` on the
  status cell, because the label overprinted the segments.
- **A decoration icon is invisible to `fit_widths` and to
  `ElidedTextDelegate`'s secondary budget** (observed, §180). S34
  must count the icon's width, or the Status column elides at 1280.
- **Real data:** 3 of 6,921 `local_files` carry a key or BPM.
  Analysis runs only on tagging with `analyze_audio` on.
- The wizard's headings are `<h2>` rich text in 9 px margins (§33).
- Carried: `MainWindow` does not apply the theme, `main_ui.py` does;
  radon is not in the env; never touch slskd or real data; zsh does
  not word-split `$var`; reproduce CI-only UI failures with
  `QT_QPA_PLATFORM=offscreen` first; a shared fake missing a method
  stalls the suite (§171); a palette change must update the chevron
  SVGs (S31); old-commit checks run in a `git worktree` with
  `PYTHONPATH=<wt>/src:<wt>/tests uv run --project <repo> pytest …`.

## 5. Decisions made

- **Recommendation: Booth, without BPM and key on the Dashboard.**
  Its boldness lands on the status column, which is the primary job.
  Harmonic's lands on data that is blank for every missing track and
  for 99.96 % of the real library. A straight mix is not recommended,
  because it puts two colour systems on one row.
- **Equal-contrast wheel hues** (every fill 7.0:1 against the pill
  text) rather than fixed HSL lightness, which failed AA on keys 10
  and 11.
- **Lucide (ISC)** over Phosphor (MIT): one weight and one grid; the
  page-to-icon names are to be confirmed at S32.
- **The mockup module is committed under `docs/`, not `tools/`.** It
  is reference material, not a tool (§0.10: scratch work outside the
  repo is lost).

## 6. Blockers

S31–S36 wait on Kris's pick (§30.3). Nothing else.

## 7. Files in progress

None. `docs/design/visual-direction.md` → "Decision" is intentionally
empty until Kris answers.

## 8. Waiting on Kris

**Approval gates:** **S30, the pick:** Booth, Harmonic, a mix, or
neither, and whether the Dashboard shows BPM and key. Then the S39
bundle identifier, the S42 publishing commands, and X1 and X2
(optional).

**Live checks (S41 checklist):** the nested-location Fix… with the X9
Pro mounted (keep `Music`, compare §172's counts); the stress test;
the packaged app's combo chevron; keyboard focus and VoiceOver on a
real Mac; hover tooltips on elided cells; the carried list in
`git show 5db1162:docs/HANDOFF.md`.

## 9. Open questions

- If Booth is chosen: are two weights of Barlow enough (Medium for
  section headers, SemiBold for titles)? The mockup used SemiBold
  only.
- **Result messages still on status labels:** Settings' destinations,
  Spotify, Test connection and credentials (`settings_window.py`
  ~:577–1161), and 12 sites on Duplicates (`duplicates_page.py`
  :440–979). One channel migration; fold it into S35a/S35b or give it
  its own commit.
- Carried unchanged: the Spotify wait not cancelled on close; the
  late-worker button defect (§148); four CLI items (§156); the
  unrecorded transfer id and leftover `.tmp` files (X1); why a shared
  fake's missing method stalls the suite (§171, UNVERIFIED); a
  location whose stored path differs in case from disk maps no files
  in a merge; should item views get a themed focus indicator (§175);
  the Dashboard's Status links clip instead of eliding (S34); why the
  cell-widget background test fails on this display, intermittently
  (§177); Review's column budget at 960 (S35b); three copies of the
  basename logic in `soulseek/` (a refactor commit).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

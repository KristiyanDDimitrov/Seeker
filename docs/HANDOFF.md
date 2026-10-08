# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S5 handoff, after the close-out (HISTORY §197). Tree clean apart from
  the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2 failed, 2052 passed, 1 skipped`.
  Failing: `tests/test_theme.py::test_a_cell_widget_paints_the_rows_own_background`
  `[dark]` and `[light]`, the same as S1–S4 and S37/S38 (S9 owns it).
  `mypy --strict src/` clean, 138 files; `ruff check src tests tools` 0.
- **CI:** the close-out's run is pending; the next commit records it.

## 2. Where we are

**Round 12 S5 is done, and with it Phase A.** **Next: S6**, the
security re-audit, read-only, which writes `AUDIT.md` (BRIEF §6;
skills `security-review`, `security-pen-testing`,
`dependency-auditor`, `adversarial-reviewer`). Its split point is
after the threat model and items 1–6. S7/S8 are [ASK]: they wait for
Kris to read `AUDIT.md`.

## 3. Session report (S5)

- `c4623f6`, §5.1: the contact email is `kristiyanddimitrov@proton.me`
  (the About dialog's author line, also on Support). The test pins the
  mailto, the visible text and the old address's absence.
- `00d3afa`, §5.2: Support leads with "Support the artists", the
  brief's draft verbatim, above Donate. One new test (first in
  on-screen order; the body is the constant, as rich text).
- The close-out: HISTORY §197 with a before/after image, the plan
  tick, this file.

## 4. Key context

- **The Support page's sections are `static_pages._section`**, not
  `theme.section_card` (the brief said "section_card-style, as the
  page's other sections have"; they are `_section`, so the new one
  is too).
- **A rich-text list in a `QLabel`** packs its items tighter than the
  page's paragraphs; `<li style="margin-bottom: 4px">` matched them
  (read in the screenshots, both themes).
- **Sharing's locations table** still rebuilds its per-row "Add to my
  SoulSeek share" button (with a tooltip) on every 20 s backend poll.
  **For S15**, or a row of its own.
- **For S16: `uv build --wheel` packages whatever is in
  `src/seeker/`,** including a gitignored `_build_info_generated.py`
  left by a local DMG build. `wheel-exclude` already drops
  `CLAUDE.md`.
- **S9 owns:** the two radon-D functions and the two undiagnosed
  tests (the CI flake
  `test_search_download_best_passes_the_already_fetched_results`,
  `37599402903`; the Cocoa-only theme failure, whose first untried
  check is a rerun with only the built-in display).
- **Planning found, for later rows:** the "daily" retry never existed
  (S10). `urllib3 2.7.0` has three advisories, fixed in 2.8.0, and CI
  has no dependency audit (S7).
- **Carried:** set `set -o pipefail` before `pytest … | tail && git
  commit`. Never touch slskd or real data. The full suite takes
  ~4.5 min, so run it in the background, and never stash `src/` while
  it runs. `git stash push -- <paths>` to test HEAD's `src/` with the
  new tests.

## 5. Decisions made

- **The draft wording stands,** verbatim; the one change is of form
  (item spacing). Typographic quotes around "track ID?".
- **`SUPPORT_TAB_SUBTITLE` kept:** it frames the whole page and reads
  straight into the artists' section, so it still leads.
- **The history image is full colour (219 KB).** A palettized copy
  was 62 KB but turned dark mode navy and light mode white, which
  would misrecord the look.
- **Skills:** `frontend-design` (the screenshot critique that found
  the list spacing) and `tdd` (both items failed first for the stated
  reason). No skill contradicted the brief.

## 6. Blockers

None.

## 7. Files in progress

None: S5 is committed whole.

## 8. Waiting on Kris

**The S5 wording veto:** open Support (or see HISTORY §197's image)
and veto or edit "Support the artists" if you want to.

**Live checks from S1–S4, still open:** the new colours (HISTORY
§193), the spin arrows and `90.0` (§194), "Follow system" applying at
once, a Review tooltip staying up for 5 s under a still pointer
(§195), and clicking the Status header on the Dashboard and Downloads
(finished rows first, §196).

**Open gates:** reading `AUDIT.md` after S6, the first live Cancel
(S12) and cleanup (S13), and the S18 publishing commands. Also the
wordmark's brows over "ee" (`9ff777b`).

**Live checks:** round 12 BRIEF §17, plus the carried list in
`git show 1b415a4:docs/HANDOFF.md` §8. The real DB still has the
three nested locations.

## 9. Open questions

- Should Sharing's 20 s rebuild get the same fix in S15, or a row of
  its own? (§4 above.)
- Unchanged from S36: see `git show 1b415a4:docs/HANDOFF.md` §9 (the
  Downloads first-poll header, Settings' Reachable lamp, Duplicates'
  Quality at 960, and the carried items).

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

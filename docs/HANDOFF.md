# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S15 part-one close-out (HISTORY §210). Tree clean
  apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2230 passed, 1 skipped`, 0 failed (+6
  tests). `mypy --strict src/` clean, 145 files; `ruff check src tests
  tools` 0; `uvx radon cc -n D -s src/seeker` nothing.
- **CI:** pending for the close-out push (recorded in the follow-up
  commit).

## 2. Where we are

**Round 12 S15 is half done** (☐, not ticked). Four of BRIEF §15's
planning-time findings are fixed. The session stopped at the 150 K
budget ceiling, short of its split point ("after the planning-time
findings"). **Next: S15 part two**, which starts with §4's first two
bullets.

## 3. Session report (S15, part one)

Evidence for each is in HISTORY §210.
- `1485c81` §15.1: Dashboard's "Candidate fo…" moves to the row's
  tooltip (`TOOLTIP_NEEDS_REVIEW_WITH_CANDIDATE`).
- `e4402d4` §15.2: a selected radio gets an ON_ACCENT dot
  (`radio_dot_path`, `packaging/icons/radio_dot_*.svg`).
- `e8402c1` §15.3: Review's Runner-up shows a file name with "scored
  N, from peer", and stretches with Track and Candidate.
- `bf26c75` §15.4: the Downloads header counts a row that already
  holds bytes as transferring; "Estimating time remaining" until a
  speed exists. This was a real bug, not only the harness's state.

## 4. Key context for S15 part two

- **Still from the planning list:** Settings → Library's Reachable
  column, a bare Yes/No that should be a lamp (`PLAY`, `STANDBY` for
  an unmounted drive; it needs a theme-repaint hook like Sharing's
  `refresh_lamps`); Duplicates at 960 elides Quality to "MP3, …".
- **Then the sweep proper:** all 78 screens, both themes, both sizes.
  Read images through a crop (Qt's `QImage.copy`, in the scratchpad):
  a full 1280×820 PNG costs ~1.4 K tokens, and 78 of them would
  exceed the budget. Only Dashboard, Settings → General, Review and
  Downloads have been looked at so far.
- **Seen, not fixed:** Downloads' Progress cell elides "Calculating…"
  at 1280.
- **Carried:** Sharing's 20 s per-row rebuild; R11's carried list
  (`git show 1b415a4:docs/HANDOFF.md` §9: the Dashboard selection lost
  on Refresh, the locations table's empty space, "MP3 320kbps" against
  "MP3, 320 kbps", a taller first Duplicates row);
  `test_library_track_list_refreshes_after_a_tag_run`'s CI timeouts;
  `uv build --wheel` picks up `_build_info_generated.py` (S16). Run the
  full suite in the foreground (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **Detail that elides goes to the tooltip**, not the cell (§15.1):
  the Status cell holds the state.
- **A file-name column stretches** (§15.3); fit-content is for short
  values.
- **The header's estimate still uses measured speeds only** (§15.4).
  A row with bytes but no speed is counted, never estimated.
- **Skills:** `frontend-design` was loaded; it is web-oriented, so
  only its self-critique applied.

## 6. Blockers

**Kris's slskd container was recreated by a test run** (HISTORY §208
→ "Observed"). It is bound to deleted pytest temp directories and
answers Seeker's saved API key `401`. Sessions must not restart or
recreate it; Kris does (Settings → SoulSeek, or `docker compose up`
from the per-user copy). A row should then find which test reached
the real `bring_up_slskd` and add a guard so no test can run `docker
compose`.

## 7. Files in progress

None uncommitted. S15 stopped between findings, not mid-change: the
Reachable lamp has not been started.

## 8. Waiting on Kris

- **New (S15):** veto, if wanted, §5's first two decisions (the
  tooltip, the Runner-up wording "scored 64.0, from peer").
- **From S14:** turn on Settings → General → Updates and relaunch.
- **From S13:** recreate slskd (§6), then the first real cleanup,
  yours to click: Downloads → "Clean up leftover files…".
- **From S10–S12b:** the decisions in HISTORY §202–§207 and BRIEF
  §12b's "Code's calls"; the first live Cancel, at the keyboard; the
  real `tracks.last_searched_at` migration runs on the next launch.
- **Still open:** S-04's GPL wording (S16); the live checks of
  §193–§196; the S5 wording veto; the wordmark's brows (`9ff777b`);
  BRIEF §17; S8's visible peer-filename change; `git show
  1b415a4:docs/HANDOFF.md` §8; the three nested locations in the real
  DB.

## 9. Open questions

- Should "Queued as backup" rows count in the Downloads header's
  "queued (no estimate)"? They wait on another file, not on a peer.
- Should a superseded row's transfer be cancelled in slskd, so its
  file never becomes a leftover?
- Should the cleanup also offer slskd's own "remove finished
  transfers"?
- How long may a settled file sit in a remote queue before Seeker
  gives up or falls back?
- Should an activated backup's row say it is a backup? Should a
  downloading row get Cancel too? Should Downloads get "Retry all"?
- Should the sweep skip a track whose needs-review candidate is still
  waiting on a person? Should a GUI sweep and a cron sweep guard
  against running at once? (UNVERIFIED how they interleave.)
- Does slskd 0.26.0 share anything by default on a fresh container?
  (AUDIT §8, UNVERIFIED.) Does Dependabot bump a `tag@digest` pair?
- Should the callback handler get a socket timeout?

---

**Read discipline:** never read a whole `docs/history/*.md` or
`main_window.py`; `grep -n`, then a range. pytest: summary line plus
named failures. BRIEF: §0 plus your row.
**Ending:** `SESSION-PLAN.md` → "Session protocol" → "Ending".

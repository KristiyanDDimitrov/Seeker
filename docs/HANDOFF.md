# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S15 part-two close-out (HISTORY §211). Tree clean
  apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2206 passed, 29 skipped`, 0 failed (+4
  tests). The skips are CI's 29: the X9 Pro was not mounted this
  session, so its 28 tests skipped as well. `mypy --strict src/`
  clean, 145 files; `ruff check src tests tools` 0; `uvx radon cc -n
  D -s src/seeker` nothing.
- **CI:** recorded in the follow-up handoff commit (§2). Before this
  session: `37994812022`'s third attempt passed (the Library flake,
  intermittent), and `cabdaee`'s run `37996502114` was green.

## 2. Where we are

**Round 12 S15 is still open** (☐). Part two fixed the last two
planning-time findings (the row's split point) and read about half
of the remaining screens. **Next: S15 part three**, the rest of the
sweep (§4), then the small fixes it turns up.

## 3. Session report (S15, part two)

Evidence for each is in HISTORY §211, the first entry in the new
`docs/history/211-240.md`.
- `64da7a2` §15.5: Settings → Library's Reachable column is now
  Status: a `PLAY` lamp with "Available", or a `STANDBY` lamp with
  "Not found" and a tooltip. `SettingsPage.refresh_lamps()` repaints
  it on a theme switch. The harness's Archive drive is unplugged, so
  the screen shows both states.
- `12214e4` §15.6: `ColumnLayout.whole`. Duplicates' Quality reads in
  full at 960 px, and Path elides instead.

## 4. Key context for S15 part three

- **Not yet read:** `help`, `sharing-explained`, the four wizard
  steps, and the 1280 px and other-theme twins of `library`,
  `search`, `sharing`, `history`, `settings-connections`,
  `settings-matching` and `support`. Crop through
  `QImage.copy` in the scratchpad, past the 165 px sidebar: about 1 K
  tokens a screen. `settings-library-light-1280x1300.png` in
  `tools/.screens/` is stale (the harness writes 76 images now).
- **Seen, not fixed (HISTORY §211 has detail):** Sharing offers "Add
  to my SoulSeek share" for a folder that isn't there (it touches the
  slskd recreate path, so it is its own row); History's stored "MP3
  320kbps" (needs a display formatter or a migration); Search's "—"
  scores and their unranked order; Library's "8 tracks" above two rows
  (perhaps the harness); the harness's unconfigured Connections tab;
  "3180 files" with no separator; Support's tight bullets.
- **From part one:** Downloads' Progress cell elides "Calculating…"
  at 1280.
- **Carried:** Sharing's 20 s per-row rebuild; R11's carried list
  (`git show 1b415a4:docs/HANDOFF.md` §9: the Dashboard selection lost
  on Refresh, the locations table's empty space, a taller first
  Duplicates row); `uv build --wheel` picks up
  `_build_info_generated.py` (S16). Run the full suite in the
  background (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **An unreachable location stands by; it is not a fault** (§15.5).
  An unplugged drive is normal for a DJ's external library.
- **A value a person chooses a row by never elides** (§15.6). The
  path gives way, and its full text is on hover.
- **Skills:** `frontend-design` was not loaded again; §210 found only
  its self-critique applies to Qt.

## 6. Blockers

None for S15. **Kris's slskd container** is still bound to deleted
pytest temp directories (HISTORY §208 → "Observed"). Sessions must
not restart or recreate it; Kris does. A later row should find which
test reached the real `bring_up_slskd` and add a guard.

## 7. Files in progress

None uncommitted. S15 stopped between screens, not mid-change.

## 8. Waiting on Kris

- **New (S15 part two):** veto, if wanted, "Available"/"Not found"
  and the faint ring for an unplugged drive.
- **From S15 part one:** the tooltip and the Runner-up wording ("scored
  64.0, from peer").
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

- Should Sharing hide or disable "Add to share" for a location whose
  folder isn't there?
- Should "Queued as backup" rows count in the Downloads header's
  "queued (no estimate)"?
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

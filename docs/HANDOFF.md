# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the S15 part-three close-out (HISTORY §212). Tree clean
  apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2238 passed, 1 skipped`, 0 failed (+4
  tests). The X9 Pro was mounted, so only the stress test skipped
  (CI skips 29). `mypy --strict src/` clean, 145 files; `ruff check
  src tests tools` 0; `uvx radon cc -n D -s src/seeker` nothing.
- **CI:** see §6 for this push's run.

## 2. Where we are

**Round 12 S15 is done** (☑). Part three read the rest of the sweep
and fixed three small findings. **Next: S16, release engineering**
(BRIEF §16, R11 §39; the bundle ID is decided). The Library flake
(§6) may deserve a row of its own first; that is Kris's call.

## 3. Session report (S15, part three)

Evidence for each is in HISTORY §212.
- `e7d8c66` §15.7: `ElidedTextDelegate`'s size hint counted a lamp
  and label 6 px narrower than its paint, so a column sized to its
  hint elided its secondary text (Library's "Get from Spo…" at 1280).
  `_primary_width` now serves both.
- `18af077` §15.8: Sharing's counts read "3,180 files", "1
  directory" (`help_text.share_counts`).
- `1e2c459` §15.9: Library's header reads "2 of its 8 tracks are in
  your library" once the list loads (`help_text.library_acting_on`).
- Not a bug: Downloads' "Calculating…" is whole (78 px of 78).

## 4. Key context for S16

- **Every harness screen has now been read** in both themes and at
  both sizes. `settings-library-light-1280x1300.png` in
  `tools/.screens/` is stale (the harness writes 76 images).
- **Seen, not fixed (HISTORY §211 and §212 have detail):** Sharing
  offers "Add to my SoulSeek share" for a missing folder (touches the
  recreate path); History's stored "MP3 320kbps"; Search's "—" means
  the filename doesn't name the artist, yet `rank_candidates` sorts by
  quality alone, so such a file can top the list; Settings →
  Connections' cards each align their own label column; Support's
  tight bullets; the harness's unconfigured Connections tab.
- **Carried:** Sharing's 20 s per-row rebuild; R11's carried list
  (`git show 1b415a4:docs/HANDOFF.md` §9); `uv build --wheel` picks up
  `_build_info_generated.py` (S16). Run the full suite in the
  background (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **A size hint is what the paint needs** (§15.7). One measure for
  both, never two that agree by luck.
- **A header counts what its list shows** (§15.9).
- **Skills:** `frontend-design` was not loaded; §210 found only its
  self-critique applies to Qt.

## 6. Blockers

**The Library flake** (`test_library_track_list_refreshes_after_a_tag_run`)
failed 3 of the 6 CI attempts before this session, and never locally.
Its lead: `LibraryPage.refresh_tracks()` drops a load for another
playlist but not an older load for the same one, so an earlier load
landing last repaints stale statuses (UNVERIFIED). A fix is
test-first and its own commit. §15.9 touched `_on_tracks_loaded` but
not that ordering.

**Kris's slskd container** is still bound to deleted pytest temp
directories (HISTORY §208 → "Observed"). Sessions must not restart or
recreate it; Kris does. A later row should find which test reached
the real `bring_up_slskd` and add a guard.

## 7. Files in progress

None uncommitted. S15 is closed.

## 8. Waiting on Kris

- **New (S15 part three):** veto, if wanted, "2 of its 8 tracks are
  in your library" in Library's header.
- **From S15 part two:** veto, if wanted, "Available"/"Not found"
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
- Should Search list files a playlist download would take (scored)
  above unscored ones, or say what "—" means?
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

# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.
**The current round is 12:** `docs/rounds/round-12/SESSION-PLAN.md`.

---

## 1. Current state

- **HEAD:** the pre-S16 clean-up's close-out (HISTORY §213). Tree
  clean apart from the untracked `Claude outputs/`.
- **Local (Cocoa):** pytest `2240 passed, 1 skipped`, 0 failed (+2
  tests). The X9 Pro was mounted, so only the stress test skipped
  (CI skips 29). `mypy --strict src/` clean, 145 files; `ruff check
  src tests tools` 0; `uvx radon cc -n D -s src/seeker` nothing.
- **CI:** see the follow-up commit for the close-out's run.

## 2. Where we are

**S15 and the pre-release clean-up (S15b, §213) are done.** Nothing
from S15's handoff blocks release: both §6 blockers are closed.
**Next: S16, release engineering** (BRIEF §16, R11 §39; the bundle ID
is decided).

## 3. Session report (S15b)

Evidence for each is in HISTORY §213.
- `8d51517`: the Library flake's real cause. A tag run never reloaded
  Library's track list (`_render_tag_result` never called
  `refresh_track_table`); the test passed only when a second initial
  load landed after its mutation. It now drains those loads first and
  failed 3/3 on HEAD.
- `caaf9ca`: the old lead, real but not the cause. Only the latest
  track-list load renders (`_tracks_load`).
- `314a14f`: `conftest.py` refuses any `docker` spawn for the whole
  session and fails the test that tried. The current suite reaches
  docker nowhere.

## 4. Key context for S16

- **Kris's slskd container no longer exists** (`docker ps -a` is empty
  in both contexts; removed outside Seeker). S17's acceptance needs a
  bring-up first: Settings → Connections, by Kris.
- **Seen, not fixed (HISTORY §211 and §212):** Sharing offers "Add to
  my SoulSeek share" for a missing folder; History's stored "MP3
  320kbps"; Search's "—" scores; Settings → Connections' label
  columns; Support's tight bullets; the harness's unconfigured
  Connections tab. Each is a question in §9, none a release blocker.
- **Carried:** Sharing's 20 s per-row rebuild; R11's carried list
  (`git show 1b415a4:docs/HANDOFF.md` §9); `uv build --wheel` picks up
  `_build_info_generated.py` (S16). Run the full suite in the
  background (~5 min). Never touch slskd or real data.

## 5. Decisions made

- **A flake's test fails on HEAD deterministically first:** it drains
  what it does not test rather than relying on timing (§213).
- **Refuse docker at `Popen`, not at `bring_up_slskd`:** read-only
  probes too, so no outcome depends on the machine running Docker.

## 6. Blockers

None.

## 7. Files in progress

None uncommitted.

## 8. Waiting on Kris

- **New (S15 part three):** veto, if wanted, "2 of its 8 tracks are
  in your library" in Library's header.
- **From S15 part two:** veto, if wanted, "Available"/"Not found"
  and the faint ring for an unplugged drive.
- **From S15 part one:** the tooltip and the Runner-up wording ("scored
  64.0, from peer").
- **From S14:** turn on Settings → General → Updates and relaunch.
- **From S13 and §213:** bring slskd up again (its container is
  gone), then the first real cleanup, yours to click: Downloads →
  "Clean up leftover files…".
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

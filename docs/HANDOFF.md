# Seeker — session handoff

**Entry point for every new Claude Code session on this project. Read it
first. Overwrite it last.** Keep it under about 120 lines: a baton, not a
log. The log is `docs/history/` (index: `docs/history/README.md`). The
nine fields below follow the contract in
`docs/rounds/round-11/SESSION-PLAN.md`. Every document: `docs/README.md`.

---

## 1. Current state

- **HEAD:** `02d6424` (S6 close-out) plus this handoff commit, pushed.
  Tree clean apart from the untracked `Claude outputs/`.
- **Local pytest** (offscreen Qt, 2026-09-29):
  `1318 passed, 1 skipped, 6 warnings in 90.49s` (X9 Pro mounted;
  S5's 1297 plus 21 new).
- **`mypy --strict src/`:** clean, 108 files. **`ruff check src
  tests`:** 0 findings.
- **CI:** S5 close-out `29a901a` → run `36588330478`, **success**. S6's
  push: see the handoff commit's own CI run (`gh run list --limit 1`).

## 2. Where we are

Phases A and B done; Phase C started: S1–S6 ticked. **Next: S7**
(Scale: big locations, short transactions, real and visible paths;
BRIEF §7).

## 3. Session report (S6, plus S5's close-out)

This session first committed S5's close-out, which the previous
session had left uncommitted (`29a901a`), and pushed it. S6's evidence
(every red output, the migration rehearsal table) is in HISTORY §141.
- `7a8ba7d` §6.2: parser skips Spotify local files and null ids;
  service keeps a repeated track's first listing; `TrackSyncResult`;
  Load tracks warns about skipped local files; CLI prints counts.
- `1b70995` §6.3: `playlists.tracks_snapshot_id` + migration
  (rehearsed on a copy: 215 playlists, 6 loaded → 6 current, 0 stale).
- `971fd03` §6.4: `refresh_playlists()` re-syncs stale loaded
  playlists; UI (with progress) and `seeker sync` use it; stale banner.
- `02d6424` close-out: §141, CLAUDE.md staleness bullet, S6 ticked.
- §6.1's red tests landed with each fix, per the one-commit-per-item
  rule.

## 4. Key context

- **Your HISTORY entry is §142**: `docs/history/121-150.md` plus its
  README line.
- **`SpotifyClient.get_playlist_tracks` now returns `PlaylistItems`,
  not `list[Track]`.** Any new stub needs `.tracks`
  (`tests/test_sync_service.py`'s `StubSpotifyClient` is the model).
- **`sync_playlist_tracks` returns `TrackSyncResult`,
  `refresh_playlists` returns `PlaylistRefreshResult`**, both in
  `models/spotify_sync.py`. S14 (typed service results) can count
  these as done.
- **`_add_column_if_missing` returns `True` when it added the
  column.** Use that for any one-time backfill that must not re-run
  (S7, S8 and S26 migrations).
- **The real database will migrate on Kris's next launch:** 6 loaded
  playlists become "current", none stale. Nothing else changes.
- **Test hazard (carried):** anything reaching `start_slskd` or a
  default `SharingService` must patch `platformdirs.user_data_dir` and
  fake `seeker.sharing_service._get_live_container_mounts`. After
  each full run, check `~/Library/Application Support/Seeker/` has no
  `slskd-data`.
- **Carried:** S9 fixes `atomic_file._write_atomic`'s umask-mode temp
  file (`os.open(..., O_EXCL, 0o600)`); three
  `LibraryLocationNotFoundError` classes (S13);
  `_repoint_or_clear_match` drops `confirmed_at` (S8). Never touch
  slskd or real data (BRIEF §0.7).
- **zsh gotcha:** `echo ======` fails (`=` expansion); use
  `echo '---'`.

## 5. Decisions made

- **A failed track sync inside `refresh_playlists` propagates** rather
  than being caught per playlist. Playlists already re-synced stay
  committed, and the rest stay stale for the banner. There's no broad
  `except` in the service, and S11 owns readable errors.
- **Staleness is read back from the database**, not from
  `sync_playlists()`'s return value, so a playlist left stale by an
  earlier failure is retried on the next refresh.
- **The banner's stale check comes before "Load tracks"** for the
  selected playlist, and another playlist being stale never hides the
  selected one's own step. With nothing selected, the banner now names
  stale playlists; before, it was hidden.
- **Null-id entries that aren't local files are skipped uncounted**:
  only local files get the DJ-facing warning.
- **Skill divergence:** `focused-fix` and `tdd` were not loaded; the
  failing-test-first discipline was followed by hand (§141 has every
  red).

## 6. Blockers

None.

## 7. Files in progress

None.

## 8. Waiting on Kris

**Approval gates:** S21 package regrouping; S30 visual direction; S39
bundle identifier; S42 publishing commands; X1 and X2 (optional).

**Interim cautions:** none.

**Kris's own decision (carried):** keep or discard the repo's
`./slskd-data` (slskd state, 728 MB of downloads, the `Test` share).
See HISTORY §140's data-directory trace.

**Live checks:** S41's checklist. New from S6: after the next launch,
edit a loaded playlist on Spotify, then Refresh playlists. The notice
should say "Updated tracks for 1", and the new track should appear.

## 9. Open questions

- CLAUDE.md items 63, 70 and 125 remain open. Which row owns the
  late-worker defect (S11 or S18)? It has failed CI twice
  (`36570098069`, `36580274797`).

---

**Read discipline (still why sessions blow their budget):** never read
a whole `docs/history/*.md` file, `main_window.py` or
`test_ui_smoke.py`; `grep -n`, then read a range. Report only pytest's
summary line plus named failures. Read only BRIEF §0 plus your row's §.

**Ending a session:** follow `SESSION-PLAN.md` → "Session protocol" →
"Ending" (HISTORY entry, commit, three numbers, tick, rewrite this file,
push, record CI).

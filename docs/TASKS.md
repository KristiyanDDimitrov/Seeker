# Task ledger — work block: docs/BRIEF-2026-09-02.md (P1-P6, six user-reported bugs)

Working ledger for this block only (not a permanent doc). Every item from
the brief, one line each, ticked only when done *and* verified, with a
one-line result + commit sha. Items not done as briefed are marked
`NOT DONE — <reason>`, never silently dropped.

Commit order per the brief: P3 → P1 → P4 → P5 → P6 → P2.

## Phase 0 — Live reproduction (read-only except 0.2, see below)

- [x] 0.1 CONFIRMED live, real numbers, worse than the brief's estimate.
  Real `x9-pro` duplicate groups (25 groups, DnB vs. "Where The Chaos
  Lies" album overlap) rendered into a real `MainWindow` at 960×640:
  `sectionSize(ACTIONS)=230`, but the Actions widget's
  `visibleRegion().boundingRect()` is `(0,0,0,0)` — fully invisible, not
  merely clipped. At 1600×900 it's fully visible (610px wide). Confirmed
  via grep: `clearSpans`/`setSectionResizeMode`/`setColumnWidth`/etc.
  appear nowhere in `src/seeker/ui/`.
- [x] 0.2 Ran the real dry-run (`seeker library rename Test`) against the
  real production DB/library. Found a real, live, **already-existing**
  DB/disk desync predating this session: 5 of 7 previously-proposed
  renames were already applied to real files on disk (confirmed via the
  user: applied through Seeker's own Rename feature), but
  `local_files.relative_path` for all 5 still held the pre-rename name —
  no rescan had reconciled it. Root cause of the DB write not landing
  (or not landing durably) was **not conclusively identified** — the
  code path (`_apply_one_rename`) reads correctly on inspection (renames
  the file back if the DB write raises), no stale `-wal`/`-journal` file,
  `PRAGMA journal_mode` is `delete` (no WAL). Recorded as unresolved,
  same as this project's own precedent for a handful of prior real,
  confirmed-but-not-root-caused findings (items 63, 68's stale-span,
  70). **Real production DB written**: per user's explicit direction,
  backed up `seeker.db` first
  (`seeker.db.bak-pre-rescan-20260903T011231`), then ran a normal
  `seeker library scan` + `seeker library match` (DB-only, no real file
  touched) to reconcile — confirmed via a follow-up dry run that the 5
  rows now read correctly and no false collision remains. Also
  surfaced (not pursued — out of scope for this brief): the "Test"
  library location and part of the `x9-pro` location contain real,
  literal duplicate copies of several tracks in different folders,
  independent of P2 — real matcher/rename behavior can shift which
  physical copy a track resolves to across rescans.
- [x] 0.3 CONFIRMED: real `slskd.yml` inside the currently-running
  container's live `/app` mount (via `docker inspect`) is the **repo's**
  `slskd-data/slskd.yml` (item 13's hand-edited copy, active `shares:`
  block already present) — this container was brought up via a plain
  dev-mode `docker compose up`, not the wizard's `bring_up_slskd()`.
  `~/Library/Application Support/Seeker/slskd-data/` does not exist on
  this machine at all. Live-confirms 5.3 is real right now, not just
  hypothetical: `is_self_managed()` would return `False` against this
  exact container if the packaged `.app` were used (its bundled
  `compose_file_path()` can never match the container's real
  `com.docker.compose.project.config_files` label).
- [x] 0.4 CONFIRMED sound, matches the brief's "already ruled out"
  section. 4 real, currently-reachable auto-matched Test tracks (1 mp3
  nested-location, 1 flac, 1 mp3, 1 flac) all have byte-exact embedded
  art vs. the current Spotify CDN bytes. Both real MP3s tested write
  **ID3v2.4**. Library-wide format counts: mp3 2027, flac 1165, wav 70,
  m4a 12 (~2% wav — real, not "materially wav").
- [x] 0.5 CONFIRMED via source: `_render_next_step` calls
  `next_step_notice.show_message()` unconditionally every 2s poll tick;
  `InlineNotice.dismiss()` only `hide()`s, no memory of the dismissal.
  Checked the other two `InlineNotice` instances
  (`dashboard_notice`/`locations_notice`): both are only ever shown from
  action-result callbacks (worker `on_finished`/`on_error`), never from
  a poll-tick render method — confirmed they do NOT share this bug, no
  second copy to fix (3.4).

**Reported all five before implementing anything (phase gate) — including
asking the user 3 clarifying questions given 0.2's real-file discovery,
answered before proceeding.**

## P3 — "You're all set" reappears after being dismissed

- [x] 3.1 `InlineNotice` gains a real `dismissed = Signal()`, emitted
  from `dismiss()` (covers both the X button and any programmatic
  dismiss call).
- [x] 3.2 `MainWindow` gains `_dismissed_next_step_key`/
  `_current_next_step_key` (tuple of playlist name + step message +
  step action). `_render_next_step` computes the current key, checks it
  against the dismissed key BEFORE clearing, keeps the notice hidden
  when they match, and clears the stored dismissed key the moment the
  computed key differs (so a genuinely different step — or the same
  step recurring later — still surfaces).
- [x] 3.3 4 new tests: `test_notice.py` gets 2 (dismiss emits the
  signal, both via direct call and the real button click);
  `test_ui_smoke.py` gets 2 (dismissed stays hidden across 3 direct
  `_render_next_step` "ticks", then a genuinely different step still
  shows; a dismissed step recurring after something else was shown in
  between is NOT suppressed by the stale dismissal).
- [x] 3.4 Done as part of Phase 0.5 above — confirmed no second copy of
  this bug exists.

`mypy --strict` clean on both touched files. Full suite after adding the
4 new tests: 878 passed, 1 skipped (0 failures).

**Commit boundary — commit 7e1b612.**

## P1 — Tagging button row squeezes the playlist panel

- [x] 1.1 New `src/seeker/ui/flow_layout.py::FlowLayout` (the standard
  Qt reflowing-row pattern, ported to PySide6). `_build_tagging_controls`
  now returns/builds a `FlowLayout` instead of a `QHBoxLayout`.
- [x] 1.2 `playlist_list.setMinimumWidth()` sized via
  `QFontMetrics.horizontalAdvance()` against an explicitly-flagged
  untuned sample string ("A pretty long playlist name (2026)") + theme
  spacing.
- [x] 1.3 SKIPPED (judgement call, as the brief allowed) — the
  `QSplitter` replacement. FlowLayout + the new minimum width already
  resolve both symptoms structurally; a splitter would touch every
  existing dashboard-layout test for no further benefit.
- [x] 1.4 9 new tests: `test_flow_layout.py` (5, unit-level: minimum
  size is the widest item not the sum, `hasHeightForWidth`, height
  grows as width shrinks, `takeAt`/`itemAt` bounds) + `test_ui_smoke.py`
  (4: `dashboard_content.minimumSizeHint().width() < 960` at the app's
  real 960×640 minimum, `playlist_list` keeps its floor, the tagging
  row collapses to 1 row at 1600 wide and grows to 2+ rows at 320,
  `tagging_controls_layout.minimumSize()` is the widest item not the
  sum). Live-confirmed via a real offscreen `MainWindow` at 960×640:
  `dashboard_content.minimumSizeHint().width()` is 445px (was ~900-
  1000px+ before, per the brief's own arithmetic).

`mypy --strict src/` clean (82 files). Full suite: 887 passed, 1
skipped (0 failures) — 9 new, 0 regressions.

**Commit boundary — commit a868139.**

## P4 — Duplicates "Actions" column shows nothing (4th report)

- [x] 4.1 `self.duplicates_table.clearSpans()` at the top of
  `_render_duplicate_groups`, before `setRowCount()`. Audited every
  other table in the app for the same omission (grepped every
  `.setSpan(` call site — only one other exists,
  `_render_sharing_uploads_table`'s no-uploads banner). **Found a real,
  second, live instance of the SAME bug there**: that branch spans row
  0 across all 4 columns when `uploads` is empty, but `setRowCount()`
  doesn't clear it — confirmed live that a transition from empty to a
  real upload left the stale span active, visually swallowing the new
  row's filename/state/progress cells into column 0 (the underlying
  `QTableWidgetItem` data was set correctly; only the visual merge was
  wrong). Fixed with the same `clearSpans()` call; 1 new regression
  test (`test_sharing_uploads_table_clears_stale_span_after_empty_
  state`).
- [x] 4.2 New `_size_duplicates_columns()`: ACTIONS gets
  `ResizeMode.Fixed` + an explicit width derived from
  `max(sizeHint().width() for widget in action_widgets)` across every
  real widget built that render. PATH gets `Stretch`. Everything else
  gets `ResizeToContents`.
- [x] 4.3 `header.setMinimumSectionSize(40)` (untuned, flagged) +
  `setStretchLastSection(False)` (the exact mechanism that caused the
  bug — stretching whichever column happens to be last).
- [x] 4.4 3 new tests in `test_ui_smoke.py`: real geometry at 960×640
  (`sectionSize(ACTIONS) >= sizeHint().width()` and
  `visibleRegion().boundingRect().width() >= sizeHint().width() - 2`),
  ACTIONS is genuinely `Fixed` at a width equal to its `sizeHint()`,
  and the stale-span regression (4-file group then two differently-
  shaped 2-file groups — the shape actually has to CHANGE between
  renders to exercise this, unlike every prior investigation's test).
- [x] 4.5 Rewrote (not deleted) the item 56 §6.2 "could not reproduce"
  test — its real pipeline (real `DuplicateService`, real
  fingerprinting) was good, its assertions weren't. Now resizes to
  960×640 and asserts real `sectionSize`/`visibleRegion` geometry, not
  just `isVisible()`, on both a first render and a full re-render.

Live-confirmed against real production duplicate groups (25 groups,
`x9-pro`): Actions went from a real `(0,0,0,0)` visibleRegion at
960×640 (before) to a real 285px-wide fully-visible widget (after).

`mypy --strict src/` clean (82 files). Full suite: 891 passed, 1
skipped (0 failures) — 4 net new (3 duplicates + 1 sharing-uploads),
0 regressions.

**Commit boundary — commit (see next `git log`, made right after this
entry).**

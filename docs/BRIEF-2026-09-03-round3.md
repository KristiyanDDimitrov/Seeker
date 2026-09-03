# Brief for Claude Code — round 3

Base commit `a6af037`. Everything below was diagnosed by reading the
real repo and the real `.venv` (mutagen/soundfile sources). PySide6
still can't be installed in the diagnosing environment, so Qt-behaviour
claims are marked as such and carry an experiment.

Round-2 note: the user confirmed **cover art is correct in Rekordbox** —
item 75 (P6) genuinely landed. See R4 for why it still looks wrong in
Finder, which is a different question with a different answer.

---

## R1 — AIFF files are invisible to the whole app

**Confirmed, and the user's hunch was exactly right.**

`src/seeker/audio_formats.py` is the entire cause:

```python
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg"}
```

`library/scanner.py` filters on this set, so `.aiff` files are never
indexed into `local_files` at all. Fingerprinting then has nothing to
find, which is precisely what "beatport_tracks_2023-11 copy" showed.
`grep -rin "aiff" src/` returns **nothing** — the format has never been
considered anywhere in the codebase.

**Supporting it is cheap, and almost all of the work is already done.**
Verified against the real installed libraries, not assumed:

- **Tagging needs no new code at all.** `mutagen/aiff.py:177` defines
  `class _IFFID3(IffID3)`, and `mutagen/_iff.py:353` defines
  `class IffID3(ID3)`. So an AIFF file's `.tags` **is an `ID3`
  instance** — exactly like WAV's `_WaveID3`. `metadata.py`'s existing
  `isinstance(mutagen_file.tags, ID3)` branch therefore already handles
  AIFF text tags, APIC cover art, and TBPM/TKEY. Zero changes there.
- **Fingerprinting already works.** libsndfile supports AIFF natively
  (`soundfile.py:48`, `:514`), so `compute_fingerprint`'s primary
  soundfile path decodes it, with item 69's ffmpeg fallback behind it.

Tasks:

- [ ] **R1.1** Add `".aiff"` and `".aif"` to `AUDIO_EXTENSIONS`.
- [ ] **R1.2** Add `"aiff"` and `"aif"` to `quality.LOSSLESS_EXTENSIONS`
  (note the set uses bare, undotted strings — `AUDIO_EXTENSIONS` uses
  dotted ones; don't mix them up).
- [ ] **R1.3 — decide `.aifc` deliberately and say why in a comment.**
  AIFF-C is a *container* that can hold compressed audio, so it is not
  automatically lossless the way `.aiff`/`.aif` are. Recommendation:
  include it in `AUDIO_EXTENSIONS` (so it is at least indexed and
  visible) but leave it out of `LOSSLESS_EXTENSIONS`, where
  `quality_tier_for_format` will score it `0`/unknown rather than
  claiming a lossless tier it may not have. Flag as an untuned
  judgement call, per this project's standing rule.
- [ ] **R1.4** Check `analyze_local_file_quality` handles AIFF: mutagen's
  `AIFFInfo` exposes `sample_rate`/`bits_per_sample`/`channels` but
  **`bitrate` may be absent** where the FLAC/MP3 paths expect it.
  Derive it (`sample_rate × bits × channels`) rather than letting the
  Duplicates table show a bare `—` for every AIFF.
- [ ] **R1.5** Existing AIFF files need a real rescan to enter the
  database — adding the extension alone changes nothing retroactively.
  Say so in the UI notice after this ships (a one-line hint on the
  Duplicates/Dashboard status is enough).
- [ ] **R1.6 — verify live** against real files in that Beatport
  folder, read-only first: scan → fingerprint → a tag round-trip on a
  **copy** → embed art and read it back byte-exact. Same discipline
  item 10 used when it verified WAV wasn't actually unsupported.

---

## R2 — The 2-second poll destroys every checkbox and radio in a table

**Root cause confirmed in source. This is not "deleting one unchecks the
others" — every checkbox in that table is destroyed and recreated every
two seconds, whatever you do.**

`poll_timer` (`main_window.py:1014`) → `_poll_review_items` →
`_render_review_items` → `_render_pending_upgrades`, which calls
`setRowCount(len(upgrades))` and then builds a **brand-new** `QCheckBox`
per row via `_build_upgrade_actions`. Nothing carries the checked state
across that rebuild. The user notices it at the moment they click
Delete only because that is when they happen to be looking.

The codebase already predicted this. `main_window.py`'s own poll_timer
comment says: *"a checkbox toggled mid-interval can get reset by the
next tick's rebuild, same accepted tradeoff as everywhere else."* The
tradeoff has stopped being acceptable — it is now a reported bug.

- [ ] **R2.1** Preserve transient selection state across re-renders,
  keyed by a **stable row identity**, not row index:
  `self._upgrade_delete_checked: set[int]` keyed by
  `details.request_id`. Wire each checkbox's `toggled` signal to add/
  discard from the set; restore `setChecked(...)` from it on render.
- [ ] **R2.2** Same treatment for the Duplicates "keep" radio selection,
  keyed by `local_file.id`, so a user's choice survives the local
  re-render after a delete (`_on_delete_duplicates_finished`) — the
  user reports the same symptom there.
- [ ] **R2.3** Prune keys whose rows no longer exist on each render, so
  the set can't grow unbounded across a long session.
- [ ] **R2.4** Audit every other polled table for the same pattern —
  anything interactive rebuilt inside a `_poll_*` path.
- [ ] **R2.5** Note in the poll_timer comment that the "accepted
  tradeoff" is now only accepted for *display* state, never for user
  input. The real long-term fix is diffing rows instead of rebuilding
  them; the state map is the honest scoped fix, so say that plainly
  rather than implying the underlying pattern is now safe.
- [ ] **R2.6** Test: render, check two boxes, run three poll ticks,
  assert both still checked; remove a row, assert its key is pruned.

---

## R3 — Bulk actions: "Replace all" and "Resolve all duplicates"

Requested, and a genuine workflow win — but these are the two most
destructive actions in the app, so they inherit the project's standing
rule in full: **never modify or delete a real user file without explicit
confirmation.**

- [ ] **R3.1 — Upgrades: "Replace all".** One button above the table.
  Opens a modal listing every pending upgrade as `Track — mp3 → flac`,
  with a single "Delete the old files" checkbox governing the whole
  batch (defaulting **off**), and a confirm button labelled with the
  real count. Applies `apply_upgrade_decision(request_id, True,
  delete_old)` per row through the existing worker, and reports a real
  per-row result — `Replaced: N, Failed: M` plus a detail line each,
  the same honest-reporting shape `format_rename_result_message` uses.
  A partial failure must leave the failed rows visible and pending.
- [ ] **R3.2 — Duplicates: "Resolve all groups".** Same shape, but the
  modal must list **real absolute paths** of every file that would be
  deleted and every file that would be kept, because this deletes user
  files. Honour each group's current keep-radio selection (which R2.2
  now preserves), and **skip any group set to "Keep all"** rather than
  silently overriding it. Explicit confirm checkbox, off by default.
- [ ] **R3.3** Neither bulk action may reuse a single confirmation for a
  later, different set — recompute the plan at click time and show what
  will actually happen now, the same lesson item 76 (P2) learned when
  the rename preview and the applied result were allowed to diverge.
- [ ] **R3.4** CLI parity where it's cheap; if it isn't, say so
  explicitly rather than half-adding it.
- [ ] **R3.5** Tests: all-success, partial-failure, "Keep all" groups
  skipped, and an empty-selection no-op. Real files in `tmp_path`, not
  mocks, matching the existing duplicate-delete tests.

---

## R4 — Why cover art shows in Rekordbox but not in Finder

**Answer: it is a macOS limitation per file format, not a Seeker bug —
and it is mostly not fixable. Rekordbox working is the proof that item
75's embedding is correct.**

macOS reads embedded cover art through AVFoundation/Core Audio, which
covers **MP3, M4A/AAC and AIFF**. It does **not** read cover art from:

- **FLAC** — macOS has no native FLAC metadata/QuickLook support, so
  the embedded `Picture` block is simply never looked at.
- **WAV** — macOS does not read ID3 chunks from a RIFF container at
  all, so the APIC frame is invisible to it.

Rekordbox ships its own decoders and metadata readers, which is exactly
why the same files look right there. Nothing Seeker writes can change
what Finder is willing to parse.

- [ ] **R4.1 — First, check the MP3s specifically.** Item 75 now writes
  **ID3v2.3** (`metadata.py:271`, `save(v2_version=3)`), which is the
  version macOS reads most reliably. If MP3 files still show no art in
  Finder, that is a real bug worth chasing; if they do show art and only
  FLAC/WAV don't, the format explanation above is confirmed and the
  question is closed. Report which it is.
  Note when testing: **Finder caches thumbnails aggressively.** Force a
  refresh with `qlmanage -r cache` before concluding anything.
- [ ] **R4.2 — Implement `cover.jpg` sidecars, opt-in.** The one useful
  thing Seeker can do: write the already-downloaded art as `cover.jpg`
  in each album/track folder (the near-universal convention — Plex,
  Jellyfin, foobar2000, Traktor and many others read it, and the folder
  itself gets a recognisable image). Reuse `AlbumArtCache` so it costs
  no extra download. Make it a Settings toggle, default **off**, since
  it writes new files into the user's library — and never overwrite an
  existing `cover.jpg`.
- [ ] **R4.3 — Do NOT implement per-file custom Finder icons.**
  It is technically possible (`NSWorkspace.setIcon:forFile:` via
  pyobjc) and would work for FLAC and WAV too, but: it adds a
  macOS-only dependency; it writes a resource fork to every real user
  file; and on a non-HFS/APFS volume — the user's `/Volumes/X9 Pro`
  external drive is almost certainly exFAT, and the library already
  carries AppleDouble `._` sidecars, which is the tell — those resource
  forks are stored as hundreds of extra `._` files that break on any
  non-Mac system. Record this as a deliberate decision with the
  reasoning, not an oversight.

---

## R5 — Global table chrome: black columns, square corners, clipped text

Three distinct defects, all global, all confirmed by grep. Item 80 (P10)
fixed the *card border* problem but left these.

### 5a — The black column and the black corner square

`grep -n "verticalHeader" src/seeker/ui/main_window.py` returns
**nothing**: every table shows Qt's vertical (row-number) header, and
`theme.py` styles only `QHeaderView::section` (`:364`), never
`QHeaderView` itself or `QTableCornerButton::section`. So:

- the area of the vertical header **below the last row** has no section
  to style and paints the default palette colour → the black column
  down the left edge, visible in both screenshots;
- the top-left corner button between the two headers is unstyled → the
  black square that cuts into the card's rounded corner.

- [ ] **5a.1** Hide the vertical header on every table
  (`table.verticalHeader().setVisible(False)`). Row numbers add nothing
  here — Duplicates already has its own Group column — and this removes
  both artifacts outright.
- [ ] **5a.2** Belt and braces, since a future table may want it back:
  add `QHeaderView {{ background-color: {BG_SURFACE}; border: none; }}`
  and `QTableCornerButton::section {{ background-color: {BG_SURFACE};
  border: none; }}` to the stylesheet.

### 5b — "Confirm" clipped on the left, "Replace"/"Decline" clipped at the bottom

This is **P4 again, in eight more tables**. Only two tables ever got a
real derived sizing pass — `_size_duplicates_columns` (`:3568`) and
`_size_search_columns` (`:1668`). Every other table still does a bare
`setStretchLastSection(True)` with no width derived from its Actions
widget:

`track_table` (:1458), `downloads_table` (:1774), `history_table`
(:1825), `sharing_locations_table` (:1920), `sharing_uploads_table`
(:1934), `review_needs_table` (:2913), `review_upgrades_table` (:2922),
`review_local_table` (:2935).

That is the horizontal clipping ("Confirm" → "onfirm"). The vertical
clipping is separate: `grep` finds **no** `resizeRowsToContents`,
`setDefaultSectionSize` or row-height call anywhere, so rows keep Qt's
default height, which is now shorter than a `theme.cell_widget`
container (button + the margins item 80 added). Hence buttons sliced off
at the bottom.

- [ ] **5b.1** Extract the working logic out of
  `_size_duplicates_columns` into a shared
  `theme.size_action_column(table, column, action_widgets)` and apply it
  to **all eight** tables above. One implementation, not ten.
- [ ] **5b.2** Add a shared `theme.apply_table_defaults(table)` called
  at every table's construction: hides the vertical header (5a.1), sets
  a minimum row height derived from a representative
  `theme.cell_widget(...).sizeHint().height()` (derived, never a magic
  number), and sets `setMinimumSectionSize`. Call
  `resizeRowsToContents()` after each render that inserts cell widgets.
- [ ] **5b.3 — verify with pixels, not properties.** Item 77 proved
  introspection isn't enough here. For each page, grab a real screenshot
  (`window.grab().save(...)`) at the app's 960×640 minimum **and** at
  the default size, and confirm no text is cut. Attach before/after.
- [ ] **5b.4** Regression test: for every table with an Actions column,
  assert `sectionSize(actions) >= widget.sizeHint().width()` and
  `rowHeight(0) >= widget.sizeHint().height()`.

---

## R6 — Sharing: `401 Unauthorized` on `/api/v0/application`

**Strong root cause; confirm with one command, then fix.**

The Sharing flow recreates the slskd container itself
(`sharing_service.py`, `add_location_to_share`):

```python
env = {"SLSKD_DATA_DIR": data_dir}
if original_share_host_path is not None:
    env["SLSKD_SHARE_PATH"] = original_share_host_path
subprocess.run(["docker", "compose", "-f", ..., "up", "-d"],
               env={**_inherited_env(), **env}, ...)
```

`docker-compose.yml` passes four credentials into the container:
`SLSKD_SLSK_USERNAME`, `SLSKD_SLSK_PASSWORD`, `SLSKD_API_KEY`, and the
two paths. **This recreate supplies only the paths.** The SoulSeek
username/password are only ever passed transiently by
`docker_setup.bring_up_slskd` at wizard time and are never in
`os.environ` afterwards; `SLSKD_API_KEY` is in `os.environ` only in a
dev run that loaded `.env`, and **not at all in a packaged `.app`**
(no `.env`, and `load_dotenv()` finds nothing).

Compose substitutes a missing variable as an **empty string**, not as
unset. `docker-compose.yml`'s own comment claims this is safe because
"slskd falls through to whatever's already persisted in slskd.yml when
an env var override is empty" — but that was verified for a *manual*
`docker compose up` before item 74 started rewriting `slskd.yml`, and an
explicitly-empty `SLSKD_API_KEY` is a different input from an absent
one. The result is a container that no longer accepts Seeker's API key —
exactly the 401 on `/api/v0/application`, which is the first call
`get_status()` makes.

Everything needed to fix it is already persisted: `config_store.py` holds
`slskd_api_key`, `slskd_username` and `slskd_password` (`:11-23`).
`SharingService` simply isn't given them.

- [ ] **R6.1 — confirm first**, and report the real output:
  `docker inspect slskd --format '{{json .Config.Env}}'` (is
  `SLSKD_API_KEY` empty or missing?) and `grep -n "api_keys" -A4
  <data_dir>/slskd.yml` compared against the configured key. Also check
  whether the SoulSeek *network* credentials survived — if they were
  blanked too, the container is not just unauthorised to Seeker, it is
  logged out of SoulSeek entirely, which is the more serious half.
- [ ] **R6.2 — one env contract, not two.** Have `add_location_to_share`
  call `docker_setup.bring_up_slskd()` with the real credentials read
  from the config store, instead of its own bespoke `docker compose up
  -d`. One code path that knows the full contract; a future compose
  variable can then never be forgotten in one of two places.
- [ ] **R6.3** If a bespoke call must stay, it must pass all five
  variables explicitly and **fail loudly** when any credential is
  missing, rather than recreating the container with blanks — a
  recreate that silently de-authenticates the container is worse than
  refusing to recreate.
- [ ] **R6.4** Make a 401 readable. `get_status()` should catch
  `httpx.HTTPStatusError` 401 and surface "slskd rejected Seeker's API
  key — the container may have been recreated without it. Re-run
  SoulSeek setup in Settings." Raw `httpx` text in a UI panel (the
  screenshot) is not an error message.
- [ ] **R6.5** After fixing, re-verify against a **disposable throwaway
  container**, never the production one — item 62's discipline. Confirm
  the API key and the SoulSeek login both survive a real recreate.

---

## R7 — Run in the background from the macOS menu bar

Nothing exists yet: no `QSystemTrayIcon`, no `closeEvent` override, and
`main_ui.py` leaves `setQuitOnLastWindowClosed` at its default `True`.

**Design decisions — confirmed with the user, do not re-litigate:**

| Decision | Answer |
|---|---|
| Closing the window | **Hides to the menu bar, app keeps running.** Quit only via ⌘Q or the menu-bar Quit item. |
| Quitting the app | **Leaves the slskd container running** — shares stay online. Seeker never stops infrastructure on quit. |
| Menu contents | **All four**: live status summary, pause/resume downloads, items needing you, and open/check-now/quit. |
| Notifications | **All three**: download finished, needs your decision, and errors. |

- [ ] **R7.1 — Lifecycle.** `qt_app.setQuitOnLastWindowClosed(False)`,
  a `closeEvent` on `MainWindow` that hides instead of closing, and a
  real Quit path that actually exits. **The first time the window is
  hidden, show a one-off macOS notification** ("Seeker is still running
  in the menu bar") persisted as a `shown_once` config flag — a window
  that vanishes with no explanation is the single most common complaint
  about this pattern.
- [ ] **R7.2 — `QSystemTrayIcon`** with a template-style monochrome icon
  so it renders correctly in both light and dark menu bars (macOS
  expects a template image; a colour icon looks wrong). Reuse
  `packaging/icons/` and add a menu-bar variant. Guard on
  `QSystemTrayIcon.isSystemTrayAvailable()` and fall back to
  today's quit-on-close behaviour when it isn't.
- [ ] **R7.3 — Menu.** Header line with live status ("3 downloading ·
  1 uploading" / "Idle"), then: Pause downloads (checkable), Review
  (N) and Upgrades (N) opening the main window on that page, Check now
  (a real `poll_downloads`), Open Seeker, Quit. Build the counts from
  the **existing** `dashboard_service` / `_poll_*` data — do not add a
  third source of truth for "what's happening".
- [ ] **R7.4 — Pause/resume is a real service-level flag**, not just a
  UI state: it must stop `poll_downloads` issuing new requests and stop
  the backend poll timer, and survive being toggled from either the menu
  or the main window. Persist it in the config store so it isn't
  silently lost on restart — and surface it in the main window too, so
  a paused app never looks merely broken.
- [ ] **R7.5 — Notifications** via `QSystemTrayIcon.showMessage()`
  (native Notification Center on macOS). **Batch aggressively**:
  downloads coalesce into one message per playlist per settle window
  ("Playlist X: 12 tracks downloaded"), never one per track. Errors are
  rate-limited — an unreachable slskd must not emit a notification every
  poll. Add per-category on/off toggles in Settings, all defaulting on.
- [ ] **R7.6 — Cost of running headless.** The 2s `poll_timer` and the
  backend poll keep firing while hidden. Audit what actually needs to
  run with no window visible: UI re-render work (`_render_*`) should be
  skipped while hidden, while the real backend poll continues. This is
  both a battery/CPU question and a correctness one — re-rendering
  tables nobody can see is pure waste, and R2's state map must survive
  a hide/show cycle.
- [ ] **R7.7** `Application`/Docker teardown must be genuinely clean on
  real quit: worker threads joined, timers stopped, no orphaned
  `QRunnable`. This app already has an open, unresolved shutdown-related
  hang (roadmap item 70) — **do not** treat this task as an opportunity
  to fix that, but do check the new quit path doesn't make it easier to
  hit, and say what you observed.
- [ ] **R7.8** Tests: offscreen tests for the menu's contents and the
  pause flag; a real manual check of hide → menu-bar → reopen → quit,
  with a screenshot of the menu. Confirm the app genuinely exits (no
  lingering process) after Quit.

---

## Ordering

1. **R6** (Sharing is currently broken — the user's slskd may be
   de-authenticated right now).
2. **R1** (AIFF — small, self-contained, unblocks a real chunk of the
   library).
3. **R2** then **R5** (both are correctness-of-the-existing-UI, and R3
   depends on R2's preserved state).
4. **R3** (bulk actions).
5. **R4** (mostly an answer plus one small opt-in feature).
6. **R7** (the large new feature, on a clean base).

`mypy --strict src/` clean and the full suite green before each commit,
one commit per R-item. Still open and untouched for three rounds:
**roadmap item 70**, the stress-test hang.

# Task ledger — work block: docs/BRIEF-2026-09-03-round3.md (round 3)

Working ledger for this block only (not a permanent doc). One line per
brief item, ticked when done and verified. Commit order followed the
brief's own stated ordering: R6 → R1 → R2 → R5 → R3 → R4 → R7.

## R6 — Sharing `401 Unauthorized`

- [x] Root cause confirmed live on this real machine (`config.json`'s
  `slskd_username`/`slskd_password` genuinely `null`), fixed by routing
  `add_location_to_share` through the shared `bring_up_slskd()` instead
  of a bespoke 2-of-5-variable recreate. New `SlskdCredentialsMissingError`
  (refuses before touching any file) and `SlskdUnauthorizedError` (a
  real 401 becomes actionable text). **R6.1's live `docker inspect`
  check and R6.5's disposable-container re-verification are blocked in
  this sandboxed session** (Docker Desktop's privileged-port-mapping
  helper needs a real macOS admin-password GUI dialog this session
  can't answer) — left for the user.
  Commit `d4d5f9d`. [HISTORY §84](HISTORY.md#84)

## R1 — AIFF files invisible to the whole app

- [x] `.aiff`/`.aif`/`.aifc` added to `AUDIO_EXTENSIONS`; `.aiff`/`.aif`
  only added to `quality.LOSSLESS_EXTENSIONS` (`.aifc` can hold
  compressed audio). Live-verified against a real file from the exact
  Beatport folder the brief named — tagging/art/fingerprinting all
  needed zero code changes beyond the extension lists.
  Commit `cca2b66`. [HISTORY §85](HISTORY.md#85)

## R2 — 2-second poll destroyed checkbox/radio state

- [x] `_upgrade_delete_checked`/`_duplicates_keep_selection` state maps,
  keyed by stable identity (never row index), restored on render and
  pruned when the row/group is gone. Audited every other polled table —
  no other affected control exists.
  Commit `75582bd`. [HISTORY §86](HISTORY.md#86)

## R5 — Global table chrome: black columns/corners, clipped text

- [x] New `theme.apply_table_defaults()` (hides the vertical header,
  floors row height) applied to every real `QTableWidget`; new
  `theme.size_action_column()` extracted from item 73's own fix, now
  shared by 7 tables instead of 2. Pixel-verified via real offscreen
  screenshots at 960×640 and 1280×800.
  Commit `3ad8ce4`. [HISTORY §87](HISTORY.md#87)

## R3 — Bulk actions: "Replace all" / "Resolve all groups"

- [x] `DownloadService.apply_upgrade_decisions_batch()`/
  `DuplicateService.resolve_groups()` wrap the existing single-row
  mutations; new `BulkReplaceUpgradesDialog`/`BulkResolveDuplicatesDialog`
  mirror `RenamePreviewDialog`'s shape, built fresh at click time, with
  a default-off confirm checkbox for both. CLI parity via `seeker
  downloads review --all` only — Duplicates bulk-delete has none,
  stated explicitly (the CLI has never had any duplicate-delete
  capability to extend).
  Commit `5edc530`. [HISTORY §88](HISTORY.md#88)

## R4 — Cover art in Finder

- [x] R4.1: byte-level re-confirmed a real MP3's ID3v2.3 embedded art
  is correct, supporting the format-based explanation. **The actual
  Finder visual check is blocked in this session** (AppleScript
  control of Finder times out, no Automation permission) — left for
  the user (force a Finder thumbnail refresh with `qlmanage -r cache`,
  already run once here, then look).
  R4.2: new opt-in `SeekerConfig.write_cover_jpg_sidecars` (default
  off, Settings), writes `cover.jpg` from already-downloaded art bytes,
  never overwrites an existing one.
  R4.3: per-file custom Finder icons deliberately not implemented
  (exFAT + AppleDouble sidecar concerns), recorded as a decision.
  Commit `1bb2b84`. [HISTORY §89](HISTORY.md#89)

## R7 — Run in the background from the macOS menu bar

- [x] `QSystemTrayIcon`-guarded background operation with a real
  fallback when unavailable; closing hides to the tray (one-off
  notice), Quit is a real `QApplication.quit()` → `aboutToQuit` →
  `cleanup_before_quit()` path shared by every quit route. New
  `SeekerConfig.downloads_paused` checked inside `poll_downloads()`
  itself, authoritative regardless of caller. Menu status/counts built
  from data the existing poll methods already fetch; table re-render
  skipped while hidden, reopening catches up immediately. Batched/
  rate-limited notifications (downloads-finished/needs-decision/
  errors), each toggleable in Settings, all defaulting on. Found and
  fixed a real packaging gap along the way: `packaging/icons/` was
  never bundled as a runtime resource — a real packaged build's tray
  icon would have been blank. Live-verified end to end with a real
  offscreen script: hide → tray Quit → the Qt event loop genuinely
  returns, both timers stopped. **Real macOS menu bar interaction
  (actual tray click, Notification Center banner, light/dark
  template-icon rendering) is left for the user** — same
  Automation/Screen-Recording permission gap as R4/R6.
  Commit `5a06744`. [HISTORY §90](HISTORY.md#90)

---

## Brief closed

All seven items (R1–R7) addressed. `mypy --strict src/` clean (one
pre-existing, unrelated `_build_info.py` error present on the base
commit, confirmed via `git stash`) and the full suite green (same 3
pre-existing failures on the unmodified tree throughout) before every
commit, one commit per R-item, per the brief's own instruction.

**Left open, deliberately, blocked by this sandboxed session's own
permission gaps (not attempted-and-failed, genuinely inaccessible
here):**
- R6.1/R6.5 — live `docker inspect`/disposable-container Sharing
  re-verification (Docker Desktop needs a real admin-password dialog).
- R4.1 — the actual Finder visual cover-art check (AppleScript/Finder
  control needs real Automation permission).
- R7.8 — real macOS menu bar interaction beyond what a real offscreen
  Qt render and a real headless event-loop exit check can prove.

**Still open, untouched for four rounds now, per every brief's own
explicit instruction not to treat it as in scope:** roadmap item 70,
the Duplicates-page stress-test hang. R7.7 confirmed by reasoning
(not by reproducing item 70 itself) that the new quit-cleanup path
doesn't touch fingerprinting and so shouldn't make it easier to hit.

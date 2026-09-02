# Task ledger — work block: action feedback, status truthfulness, tagging art, filenames, duplicates scope & progress, Support page

Working ledger for this block only (not a permanent doc). Every item from
the brief, one line each, ticked only when done *and* verified, with a
one-line result + commit sha. Items not done as briefed are marked
`NOT DONE — <reason>`, never silently dropped.

Re-read this file at every phase boundary before starting the next phase.

## Phase 0 — Task ledger + recon (read-only, report before implementing)

- [x] 0.0 Build this ledger — done, this file.
- [x] 0.1 CONFIRMED live (offscreen MainWindow, artificially-slowed scan_and_match): `_render_next_step` (main_window.py:2658-2665) unconditionally `.setEnabled()`s all 4 action-row buttons on every 2s poll_timer tick, fighting `run_worker(button=...)`'s busy-disable and the manual `_set_download_button_busy`/`_reset_download_button` pair. Real log: button re-enabled at t=2.0s while scan still running until t=6s.
- [x] 0.2 CONFIRMED by code (dashboard_service.py `_compute_status`): a `soulseek_review_candidates` row with no `download_requests` row is only ever a secondary tag on NEEDS_REVIEW/NOT_FOUND, never a primary state — by construction, matching the brief exactly.
- [x] 0.3 CONFIRMED by code + real DB: `_AWAITING_REVIEW_STATUSES={ready_for_review,locked,shortlisted}`, `_DOWNLOADING_STATUSES={queued,downloading}`. `_retry_locked_request` can transiently write 'downloading' before the async rejection manifests, then flip back to 'locked' next poll — real oscillation. No retry_count/backoff/terminal state exists anywhere — real DB has 3 locked rows stuck since 2026-08-27/28 (5+ days), confirming no bound.
- [x] 0.4 Primary hypothesis (append-not-replace) already refuted in item 56 Phase 0.4/Phase 4. Re-confirmed live: all 8 currently-tagged real files have byte-exact CDN-matching art (0 mismatches). Real, still-open gap found: `_show_tag_result_notice` has no branch for tagged=0/without_art=0/failed=0-but-skipped_already_tagged>0 — a fully-already-tagged re-run produces zero InlineNotice, only the easy-to-miss small results panel.
- [x] 0.5 NOT reproducible, even at real scale (15 groups / 45 rows, real default 1180x760 window). Column indices verified correct both statically and by resolving via header text at runtime (Actions=7, matches code exactly). `setStretchLastSection` makes the Actions column's right edge exactly equal the viewport width — cannot scroll off-screen. Matches item 61 Phase 6.2's own "could not reproduce."
- [x] 0.6 Real numbers: 110 never-fingerprinted rows, 34 succeed (new files), 76 genuine failures (identical to item 39's original 76, same 2 confirmed 0-byte files still 0 bytes). librosa fallback: only 11/76 succeed (65/76 fail identically — librosa routes through the same libsndfile/soundfile backend). ffmpeg IS on PATH (`/opt/homebrew/bin/ffmpeg`) and successfully decodes a real "bad data offset" MP3 that both soundfile and librosa failed on.

**Report all six before implementing anything (phase gate).**

## Phase 1 — Support page

- [x] 1.1 Real sidebar Support page, directly below Help, `_build_page` pattern, built eagerly like Help (nothing to lazy-load — purely static copy, no DB/service call at all; noted as a deliberate deviation from "lazy-loaded like Duplicates/History" since there's no fetch to defer).
- [x] 1.2 SUPPORT_LINKS already had both Revolut and PayPal live (PayPal went live 2026-09-01, per existing comment) — no reconciliation needed. Extracted `_build_support_links_row()` shared by AboutDialog and the new Support page so the loop lives once, not twice.
- [x] 1.3 Help menu/About dialog/wizard done page confirmed unchanged (28/28 wizard tests, About dialog tests all pass). Added 4 new Support-page smoke tests + updated the nav-buttons-enumeration test for the new "support" key. Extended `test_stress_e2e.py`'s interleaved loop with a Support page visit.

**Commit boundary.**

## Phase 2 — Make long-running actions visibly running

- [ ] 2.1 Busy-action registry the poll cannot fight
- [ ] 2.2 Global activity strip in window shell
- [ ] 2.3 Progress channel on shared worker dispatcher (throttled, primitives-only)
- [ ] 2.4 Verify: instrumented repro, stress test with progress-heavy worker, 3x smoke run

**Commit boundary.**

## Phase 3 — Ask where downloads should go

- [ ] 3.1 Explain the "found my folder" coincidence (report only)
- [ ] 3.2 Prompt on first download per playlist (extend DestinationDialog)
- [ ] 3.3 Verify: prompts once, persists, CLI untouched

**Commit boundary.**

## Phase 4 — Statuses that tell the truth, bounded retry

- [ ] 4.1 Split TrackStatus: REVIEW_CANDIDATE, RETRYING, narrowed AWAITING_REVIEW
- [ ] 4.2 Count review candidates separately in download_playlist result
- [ ] 4.3 Bound the locked-retry loop: retry_count/next_retry_at, backoff, `unavailable` terminal status
- [ ] 4.4 Verify: real timestamps, unavailable excludes redownload block, CLI/UI vocab parity

**Commit boundary.**

## Phase 5 — Cover art that actually lands

(Scope depends on 0.4 findings.)

- [ ] 5.1 Never silently skip — skipped_already_tagged + other skip reasons surfaced
- [ ] 5.2 Re-tag reachable/meaningful: force=True audit, explicit re-tag option, "Fix missing cover art"
- [ ] 5.3 One-click fix for `album_art_url IS NULL` (re-run sync-tracks from tagging panel)
- [ ] 5.4 Verify: round-trip on copies per format; ask before touching real files; real before/after

**Commit boundary.**

## Phase 6 — Filenames that match the metadata

- [ ] 6.1 `seeker/filename_format.py::build_track_filename` — pure function + tests
- [ ] 6.2 Case-insensitive-volume two-step rename gotcha, tested on real volume
- [ ] 6.3 MetadataService.plan_renames / apply_renames (dry-run by default, DB-row ordering documented)
- [ ] 6.4 UI preview dialog + CLI `seeker library rename <playlist> [--apply]`
- [ ] 6.5 Verify: round-trip on copies; ask before touching real files; real dry-run shown to user

**Commit boundary.**

## Phase 7 — Duplicates: scope, progress, empty Actions column

- [ ] 7.1 Fix Actions column bug class (named constants, header-text-resolved test)
- [ ] 7.2 Scope duplicate detection + fingerprinting to folders (pooled, cross-location allowed)
- [ ] 7.3 Real staged progress for fingerprinting + duplicate search (CLI + UI, throttled)
- [ ] 7.4 Verify: real scale run, timings, folder-scoped vs whole-location counts

**Commit boundary.**

## Phase 8 — Fingerprint failures: fall back, then report

- [ ] 8.1 librosa fallback (then optional ffmpeg-if-present) in fingerprint decode path
- [ ] 8.2 Per-file failure reason surfaced in UI/CLI
- [ ] 8.3 Flag genuinely broken (0-byte) files separately, no delete offered

**Commit boundary.**

## Closing out

- [ ] Full audit of this file — every line ticked or `NOT DONE —` with reason
- [ ] mypy --strict clean; pytest green x3, flaky tests reported
- [ ] Opt-in stress test run, RSS/fd/thread growth reported
- [ ] README.md updated (Support page, Duplicates no longer single-location, new CLI commands, destination prompt)
- [ ] CLAUDE.md roadmap items 64+ added (≤8 lines each), HISTORY.md entries for investigations/refuted hypotheses
- [ ] Item 63 entry updated (backoff as structural bound, diagnostic print gated)
- [ ] Item 22 entry updated (TrackStatus vocabulary changed)

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

**Commit boundary — commit 234ac4b.**

## Phase 2 — Make long-running actions visibly running

- [x] 2.1 `ui/busy_actions.py::BusyActionRegistry` (module in `ui/`, kept OUT of `ui/workers.py` deliberately — no cross-thread/signal machinery needed, and that file already has 3 documented crash/deadlock histories). Wired into sync/scan/match/download/sync_tracks/tag_selected/tag_playlist/compute_fingerprints/find_duplicates/sharing_refresh/history_refresh via a new `_run_busy_worker` helper. Per-row/per-item dynamic actions (per-track Tag, per-group Delete, Review confirm/reject, per-location Add-to-share) deliberately scoped OUT — not fought by any poll (verified), and a global strip label for "which of N rows" adds no value. `_render_next_step` now guards every button touch with `is_running()`. Also fixed the user-flagged `download_button.setVisible()` mid-download hiding bug in the same guard.
- [x] 2.2 Global activity strip: new column between sidebar and `stacked_widget`, hidden at zero, label + progress bar (indeterminate by default, determinate once Phase 7 wires real progress). Shows a count, not a merged number, when >1 action running.
- [x] 2.3 `task_progress` signal added to the existing, already-permanently-connected `_dispatcher` (3rd signal, same "primitives only, connect once" pattern as the other two). `run_worker(..., on_progress=...)` optional; when omitted, `fn` called with zero args exactly as before (verified: every pre-existing call site untouched). Throttled at the SOURCE (inside `Worker._report_progress`, on the worker thread) — `PROGRESS_EMIT_MIN_INTERVAL_S=0.25` OR `PROGRESS_EMIT_EVERY_N=25`, whichever first; first report always emits (`_progress_last_emit` init to `-inf`, a real fix found by my own test using a monkeypatched clock at 0.0).
- [x] 2.4 Verified: live async repro re-run — scan button stayed busy across 5+ real 2s poll ticks (t=0 through t=5s), restored exactly once at real completion (t=6s). Deadlock regression suite 3x clean. Full fast suite 3x: 789-790/790, one pre-existing flaky test (documented, not a regression — reproduces 1/5 in isolation too). `test_ui_smoke.py` timing: ~5.0-5.4s across runs, no hang/slowdown. Progress-heavy worker (3,000 throttled reports over several seconds) added to the opt-in stress test's interleaved loop with real assertions on delivered event count/first/last — actual RUN deferred to closing-out (real ~5+ min against real infra; will cover every phase's cumulative changes in one pass, per the brief's own closing-out step).

**Commit boundary — commit 81dfb5a.**

## Phase 3 — Ask where downloads should go

- [x] 3.1 Confirmed against real code: no folder-name detection exists. `_resolve_destination` picked the configured default location + subfolder-per-playlist (playlist name sanitized); the user's existing "Psytrance" folder matched "PsyTrance" purely because macOS's default filesystem is case-insensitive. Coincidental, not a feature.
- [x] 3.2 `_on_download_clicked` now checks `playlist.download_location_id is not None` (already loaded on the Playlist itself — no extra query) to decide skip-vs-prompt, replacing the old "anything resolvable skips it" rule. `DestinationDialog` extended (not duplicated) with `initial_subfolder` (pre-fills the REAL current fallback via `get_resolved_destination`, not just the raw playlist name) and a live `location_path_preview` label (`help_text.format_destination_preview`) showing the exact absolute path, whether it exists, and a real audio-file count via `AUDIO_EXTENSIONS`.
- [x] 3.3 Verified: CLI's `handle_download`/`download_playlist`/`_resolve_destination` completely untouched (confirmed by reading — zero changes outside `ui/main_window.py`/`ui/help_text.py`), 73 CLI/download-service tests pass unmodified. A playlist with its own destination never prompts (regression test), one without always prompts once pre-filled with the real fallback (new test), and the dialog's live preview updates correctly across 3 new tests (new-folder case, real audio-file count, live field-change updates).

**Commit boundary — commit c1e4034.**

## Phase 4 — Statuses that tell the truth, bounded retry

- [x] 4.1 `TrackStatus` split 5->7 states (RETRYING, REVIEW_CANDIDATE added); precedence `IN_LIBRARY > DOWNLOADING > AWAITING_REVIEW > RETRYING > NEEDS_REVIEW > REVIEW_CANDIDATE > NOT_FOUND` (confirmed correct against real code, no case found where it's wrong). Secondary "SoulSeek candidate found" tag confirmed rendered (was live in the UI) — kept only for NEEDS_REVIEW (redundant for REVIEW_CANDIDATE, whose own label already says it). Double-click-to-review + its Review-page focus (`_focus_pending_review_row`) extended to REVIEW_CANDIDATE rows (a real, previously-missing 3rd search branch added). CLI checked and confirmed to never use `TrackStatus`/`dashboard_service` at all — nothing to reconcile there.
- [x] 4.2 `download_playlist()` result gains `needs_review: list[str]`. New `help_text.format_download_result_message()` names requested/sent-to-review/already-in-progress/no-candidate-found separately (never via subtraction from `total`). CLI's `handle_download` updated to match, same non-subtraction principle.
- [x] 4.3 `download_requests.retry_count`/`next_retry_at` (guarded migration, verified against real production DB — 14 rows unchanged, all 3 real pre-existing locked rows now retry_count=0). Exponential backoff (60s/120s/240s.../cap 3600s), terminal `unavailable` after 8 attempts, excluded from `get_requests_blocking_redownload`. **Real bug found and fixed via live verification against production slskd**: a genuinely unrecognized error (a real `500 Internal Server Error` on `/api/v0/transfers/downloads/batches` — the exact endpoint item 63 flagged as its one concrete lead) escaped the original `except SoulseekDownloadError` handling entirely, never advancing retry_count — reproducing the exact unbounded-retry shape this phase exists to fix. Fixed with broader exception handling around both `request_download` and `get_download_status` that always advances the retry budget before re-raising. Diagnostic print gated behind `SEEKER_DEBUG_POLL=1`.
- [x] 4.4 Verified live against real production slskd (2026-09-02): retry_count/next_retry_at advanced correctly across 2 real consecutive polls (0→1→2 for one row, with real backoff timestamps ~60-70s apart); the 500-error gap above found AND fixed live, re-verified fixed with a second real poll. Full exhaustion-to-unavailable path (8 attempts, hours of real backoff) verified via mocked-clock-free but count-seeded unit tests instead — reaching it live would take hours, disclosed as the one gap. `unavailable` added to `TERMINAL_STATUSES`, `_DOWNLOAD_TERMINAL_STATUSES`, `_is_visible`'s recently-finished window, and a new `seeker downloads status`/UI "Unavailable: N" count. Full audit of every status-consuming query in the codebase (11 in the repository, plus dashboard_service.py/main_window.py/download_service.py) — full list in the phase report.

**Commit boundary — commit b3d59c6.**

## Phase 5 — Cover art that actually lands

(Scope adjusted by user: force=True item dropped — already correct per item 46. 5.1's missing-notice branch is primary. 5.4 simplified per user instruction.)

- [x] 5.1 Fixed the real gap: `_show_tag_result_notice`/`help_text.format_tag_result_notice` now handles tagged=0/without_art=0/failed=0-but-skipped_already_tagged>0 — previously produced ZERO notice, only the small results panel.
- [x] 5.2 New `MetadataService.fix_missing_art_for_playlist()` — re-embeds art only (never text tags), for auto-matched tracks whose embedded art is missing or byte-mismatches the real current `album_art_url` (authoritative SHA comparison, same method as Phase 0.4's own investigation). New `metadata.py::read_embedded_art()`. UI button + CLI `seeker library fix-art <playlist>`.
- [x] 5.3 `sync_service.sync_playlist_tracks()` now returns a real count of art URLs filled in (captured before/after the save). New "Fill missing art URLs" button + notice.
- [x] 5.4 (simplified) Verified the new notices render via 12 new tests (service-layer + UI). **Two real bugs found by my own tests, not review** — (1) a fresh untagged file has `mutagen_file.tags is None`, so `embed_album_art`'s `isinstance(..., ID3)` check silently no-ops without an explicit `add_tags()` first (missing in the new method, present in `_tag_one_track`); fixed. (2) confirmed via a deliberately-wrong-seeded-text-tag test that "already correct" art genuinely skips the write with zero text-tag mutation. **Asked user, confirmed target: real "Test" playlist.** Real before-state (read-only): 3/9 auto-matched tracks had genuinely mismatched embedded art (Breach, Bit Perfect, Jade Venom — real SoulSeek-download art, not Spotify's), 6/9 already correct. Ran `seeker library fix-art Test` for real — `Fixed: 3, Already correct: 6, everything else: 0`. Real after-state: **9/9 byte-exact CDN match**, confirmed via direct re-read. Text tags/audio integrity spot-checked intact on all 3 fixed files (one, "Breach," had never been text-tagged at all — its tag still reads the pre-Spotify "Balron & Audio," proving text tags were genuinely never touched).

**Commit boundary.**

## Phase 6 — Filenames that match the metadata

- [x] 6.1 `seeker/filename_format.py::build_track_filename` — pure function, `Artist1, Artist2 - Title.ext`, feat-dedupe heuristic, 255-UTF8-byte cap (title truncated, never extension, never mid-character). Refactored `filename_sanitize.py` to expose `clean_path_component` (char-cleaning only, no length cap) so the two modules' genuinely different length rules (200 chars vs 255 bytes) don't fight — confirmed behavior-preserving (13 existing tests unchanged). 17 new tests, all pass.
- [x] 6.2 Two-step temp-name rename (`_rename_via_temp`) for case-only changes on a case-insensitive volume — tested on the REAL filesystem (tmp_path, same default case-insensitive APFS as the rest of this machine), not simulated.
- [x] 6.3 `MetadataService.plan_renames`/`apply_renames` + `RenamePlan`/`RenameResult`. DB-row-AFTER-file ordering (opposite of item 40's delete rule, documented why). Re-verifies still-auto-matched at apply time (refuses, not silent skip). DB-write failure rolls the file back. **Real design gap found by my own tests**: my first draft only auto-resolved collisions at PLAN time and then refused them at APPLY time — the brief actually wants apply_renames to resolve them for real (numbered suffix), with "collision" only informational in the preview; fixed.
- [x] 6.4 `RenamePreviewDialog` (grouped by action, confirm gated, item 27's non-gate precedent explicitly does NOT extend here) + CLI `seeker library rename <playlist> [--apply]` (y/N confirm). CLI has no dedicated unit tests, matching this project's own established precedent (`tag`/`fix-art` don't either — service layer already covers the logic).
- [x] 6.5 14 service-layer tests + 6 UI tests, all real filesystem operations in `tmp_path` (not mocked) — multi-artist + feat-dedupe + accented + byte-cap in one combined round-trip, plus separate case-only and real-collision round-trips. DB row followed the file and `track_matches` still resolved in every case. **Asking user before the real dry-run against a real playlist next** (see phase report).

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

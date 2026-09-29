# Round 11 audit — Seeker at `378646a`

**Date:** 2026-09-29. **Scope:** the whole repository — `src/` (104 modules,
30.7 K lines), `tests/` (71 modules, 35.1 K lines), packaging, CI, docs,
and the running UI. **Purpose:** decide what stands between this codebase
and a polished, released v0.1.0. The executable instructions are in
`BRIEF.md`; the session order is in `SESSION-PLAN.md`. This file is the
human-readable summary.

## Verdict

**Not ready to release.** Two confirmed bugs can destroy files in a
user's music library, and the packaged app ships a Docker Compose file
that mounts paths from the developer's own external drive. A fourth
finding is a privacy bug: one Settings action would publish the wrong
folder (on this machine, `~/Desktop`) to the Soulseek network. All four
are fixed early in this round (S3, S5). Everything else is correctness,
hardening, structure and polish.

## How this was checked

- **Skills:** `ship-gate` (its scanner ran 56 automated checks; all 7 of
  its "critical" hits turned out to be false positives or web-only checks,
  each adjudicated by hand), `tech-debt-tracker` (debt scan), `dependency-auditor`
  method (deptry + pip-audit), `codebase-onboarding`, `database-designer`
  method (schema, `EXPLAIN QUERY PLAN`), `tc-tracker` (handoff format),
  `frontend-design` (UI review).
- **Tools:** radon (complexity), vulture plus a token-level reference
  count (dead code), deptry, pip-audit (184 locked packages), a ruff
  survey of rule families the project does not enable, branch coverage,
  `python -X importtime`.
- **Probes:** every "confirmed" bug below was reproduced with the real
  service code against a throwaway database and throwaway files, never
  the real library.
- **Real data:** read-only queries (`sqlite3 -readonly`) against the real
  database, and one timing measurement against a copy of it. Nothing
  real was written.
- **UI:** every page rendered offscreen with demo data, both themes, at
  1280×820 and at the 960×640 minimum size (48 screenshots).

## Baseline

| Check | Result |
|---|---|
| `uv run pytest -q` | `1204 passed, 29 skipped, 6 warnings in 74.33s` |
| Branch coverage | 90.3 % (10,030 statements, 751 missed) |
| `uv run mypy --strict src/` | clean, 104 files |
| `uv run ruff check src tests` | 0 findings |
| CI on `378646a` (run `35906721903`) | success; 8 consecutive green runs since `ddc1f6e` |
| pip-audit, 184 locked packages | no known vulnerabilities |
| deptry | one transitive import (`shiboken6`), no unused dependencies |
| Import cycles / layer violations | none |

## What is already in good shape

- **Layering holds.** No module in `ui/`, `cli.py` or the entry points
  imports a repository; no service imports Qt; `models/` imports nothing.
  No import cycles.
- **Typing and lint are genuinely clean**, under `mypy --strict` and a
  broad ruff selection that includes bandit (`S`).
- **SQL is parameterized everywhere.** The one dynamic placeholder list is
  built from `?` only.
- **OAuth is done right.** PKCE S256, a 128-character verifier, a 32-byte
  state, and a loopback-only callback with a bounded wait and a static
  response page.
- **Credentials** are stored 0600 and masked in the UI. Generated secrets
  use the `secrets` module.
- **Styling is centralized.** There are zero per-widget stylesheets and
  zero hard-coded colours outside `theme.py`, so a visual refresh is
  mostly one file.
- **Tests are extensive.** 1,204 tests at 90 % branch coverage, with
  deterministic repros for past races.

## Findings

Severity: **C** critical (data loss or release blocker) · **H** high ·
**M** medium · **L** low/polish. "Row" is the session in
`SESSION-PLAN.md` that fixes it.

### Critical

| ID | Finding | Evidence | Row |
|---|---|---|---|
| A-01 | Replacing a track with a same-named upgrade while "Delete old file" is checked deletes **both** versions, and the database still says the track is in the library. | End-to-end probe with the real `DownloadService`: the service reports "Replaced with X / Deleted X" for the same path, and no file remains. | S3 |
| A-02 | A finished download silently **overwrites a different file** of the same name in the destination folder (for example `01 - Intro.mp3`). | Probe: the existing library file's contents were replaced. | S3 |
| A-03 | The Compose file bundled into `dist/Seeker.app` mounts `/Volumes/X9 Pro/Music/Test` and defaults the share path to `/Volumes/X9 Pro/Music`. It is copied into every user's data folder on first run. The root cause: in dev, the Sharing feature edits the tracked `docker-compose.yml` in place (committed in `bffb21b`). | Present in `Contents/Resources/` and `Contents/Frameworks/` of the built app. What this does on another Mac is unverified; a fresh-account install checks it (S41). | S5 |

### High

| ID | Finding | Evidence | Row |
|---|---|---|---|
| A-04 | When two downloads share a basename, the wrong one can be moved into the library (`rglob(...)[0]`). | Probe. The dev slskd download folder holds 11 `_<ticks>` duplicates, which slskd writes on a name clash (728 MB left behind in total). | S3 |
| A-05 | If a matched file is moved or deleted outside Seeker, its match is left in limbo. The track shows as missing forever, Download never retries it, and the "Download N missing" banner never clears. Human-confirmed matches are affected too. | Probe with `scan_and_match`. The real database has 2 such rows now. | S4 |
| A-06 | Removing a library location that any playlist downloads into crashes with a foreign-key error. The error text shows raw on an ephemeral label, and the removal has no confirmation even though it cascades. | Probe: `IntegrityError: FOREIGN KEY constraint failed`. | S4 |
| A-07 | A Spotify playlist that contains the same track twice can never load its tracks. | Probe: `UNIQUE constraint failed: playlist_tracks…`. | S6 |
| A-08 | A Spotify playlist that contains a Spotify "local file" can never load its tracks. | Probe: `NOT NULL constraint failed: playlist_tracks.track_id`. | S6 |
| A-09 | "Refresh playlists" updates each playlist's snapshot but never its tracks, and nothing detects the difference. A playlist that gained tracks on Spotify still reads "You're all set". | Both callers of `sync_playlists()` discard its list of changed playlists. | S6 |
| A-10 | Scanning fails permanently for any location with more than 32,765 audio files. | Probe on SQLite 3.53.1: `too many SQL variables`. | S7 |
| A-11 | When slskd is down, the app says nothing. Every per-request network error is swallowed, so the "couldn't reach slskd" notification cannot fire for that case. | Code reading of `poll_downloads`, plus the fact that health checks exist only in the wizard and Settings. | S12 |
| A-12 | Review never shows the SoulSeek candidate's filename (the one thing needed to judge it), and never shows the tags behind a local-file match. | Screenshots and code. | S29 |
| A-13 | Writing tags to FLAC and MP4/M4A (the formats Seeker prefers) has no test coverage at all. | `metadata.py` is at 58 %; every FLAC and MP4 branch is missed. | S23 |
| A-54 | **Privacy:** Settings → "Update SoulSeek credentials" recreates slskd sharing the *alphabetically first* library location, not the one currently shared. The code comment claims the opposite. With the real locations, that is `/Users/sinthesis/Desktop`, which would be published read-only to the Soulseek network in place of the music library. It has not happened yet; it would on the next credential update. | Code (`list(self._locations_by_name.values())[0]`, fed by `ORDER BY name`), plus a read-only query of the real locations and `slskd.yml` sharing `/shared/music`. | S5 |
| A-56 | Every Dashboard action (Refresh playlists, Load tracks, Rescan, Re-match, Download) reports errors on a label the 2-second poll clears, so a Spotify rate limit or auth error is visible for 2 seconds at most. The scan-and-match summary is wiped the instant it is written. This is round 10's Review defect, still present on the Dashboard. A Dashboard row's Tag and Re-tag report their outcome on the *Library* page's notice. | Code, plus a probe: the label reads `''` right after the scan finishes. | S11 |

### Medium

| ID | Finding | Evidence | Row |
|---|---|---|---|
| A-14 | The credential-file writer creates its temp file readable by other users, then chmods it, and never fsyncs. | Code reading of `atomic_file.py`. | S9 |
| A-15 | Two concurrent Spotify token refreshes can race; Spotify rotates refresh tokens, and the loser falls back to a surprise browser re-authorization. | Code reading: no lock in `SpotifyAuthManager`. | S9 |
| A-16 | Peer usernames go into slskd URL paths unencoded. `?` and `#` truncate the path; `../` is normalized into a different, authenticated endpoint. | httpx URL probe. | S9 |
| A-17 | Background errors reach the user as raw exception text (`[Errno 61]…`, `FOREIGN KEY constraint failed`, or an empty "Error:"). | Code, and a rendered Sharing page. | S11 |
| A-18 | Exceptions raised on the Qt main thread never reach `seeker.log` in the packaged app. | No `sys.excepthook` or Qt message handler is installed. | S11 |
| A-19 | The 2-second Dashboard poll reads every `local_files` row, including 32.6 MB of fingerprints, to render one playlist. This may also be behind open item 70 (unconfirmed). | Measured on a copy of the real database: 28.7 ms median per poll. | S22 |
| A-20 | There are no secondary indexes. Every foreign-key and status lookup is a full scan. | `EXPLAIN QUERY PLAN`. | S22 |
| A-21 | Rejecting a local match or a SoulSeek candidate does not stick; the same suggestion comes back on the next scan or download. | Code: both rejections only delete a row. | S8 |
| A-22 | A failed download disappears after about a minute, History excludes failures, and no failure reason is ever shown. | Screenshots and page copy. | S8 |
| A-23 | `seeker library add` stores relative paths and does not expand `~`. | Probe: `./Music` is stored as `Music`. | S7 |
| A-24 | A library scan and a re-match each hold one write transaction for their whole IO- or CPU-bound pass. | Code reading. Whether concurrent writers then hit "database is locked" is a hypothesis. | S7 |
| A-25 | Sharing does not roll back its `slskd.yml` edit when the container recreate fails, and its file writes are not atomic. | Code reading. | S5 |
| A-26 | Runs from source report a stale build identity (the Help page says `d38d80f` at HEAD `378646a`). | A leftover `_build_info_generated.py` from the last packaging build. | S39 |
| A-27 | The first-launch Gatekeeper instructions (right-click → Open) are likely obsolete on macOS 15 and later. | Unverified; S41 checks it on a quarantined download. | S39, S41 |
| A-28 | The bundle identifier `com.seeker.app` is a domain the project does not own. It can only be changed painlessly before the first release. | `packaging/seeker.spec`. | S39 [ASK] |
| A-29 | Table cells render two-tone, checkbox and radio labels sit on dark boxes, and combo boxes have no arrow. One root cause: a global `QWidget { background }` rule. | Screenshots. | S27 |
| A-30 | Appearance, Notifications and Startup live under the "Thresholds" settings tab, and the thresholds are free-text fields. | Screenshots. | S29 |
| A-31 | The album-art cache keeps every image in memory for the app's lifetime. | Code reading. | S22 |
| A-32 | 454 ms of the 724 ms GUI import time is `scipy.stats`, used for one optional BPM prior. | `python -X importtime`. | S22 |
| A-33 | A manual search that finds nothing leaves an orphan track row behind. | The real database has 1. | S8 |
| A-34 | CI actions are pinned by tag rather than by commit, there is no `permissions:` block, `uv sync` runs without `--locked`, there is no coverage floor, no update automation, and the slskd image is unpinned. | `.github/workflows/ci.yml`, `docker-compose.yml`. | S10, S5 |
| A-55 | Peer-controlled strings are rendered without escaping. A SoulSeek filename or username containing HTML turns single-line notices and status labels (Qt's default AutoText) and tooltips into rich text, so a crafted `<a href=…>` renders as a link-styled "Update Seeker". `seeker search` prints peer strings to the terminal raw, escape sequences included. The destructive delete dialog is safe only because its first line is plain text. | PySide6 probe: `mightBeRichText` returns `True` for such a filename and `False` for real titles like "Love & <Hate>"; `cli.handle_search` prints `file.username` and `file.filename` verbatim. | S9 |
| A-57 | The rename feature and the per-playlist download folder can create **hidden** names: a leading dot is never stripped (an artist such as "...And You Will Know Us by the Trail of Dead", a playlist named ".late night mix"), so the file or folder disappears from Finder and many DJ file browsers. | Probe of `build_track_filename` and `sanitize_path_component`. Kris's data has no such paths today. | S7 |
| A-58 | On a fresh install (or any launch with empty history), "downloads finished" tray notifications never fire for the whole session: the notification cutoff is seeded only from an existing history event, and the check skips while it is unset. | Code reading of `TrayController.seed_notification_cutoff` and `check_for_download_notifications`, including its own "(or found nothing) — skip" comment. | S12 |
| A-59 | The destination dialog previews a sanitized subfolder, but the raw text is what gets persisted and used. `240KM/H` becomes nested folders, and `../Elsewhere` sends downloads outside the library location while the preview shows a harmless name. The CLI's `--subfolder` has the same gap. | Code reading of `DestinationDialog._update_preview` versus `selected_subfolder`, `set_destination` and `_move_completed_file`. | S7 |
| A-60 | Spotify authorization cannot be cancelled. A mistyped Client ID (Spotify's page never redirects back) leaves the wizard waiting 5 minutes. Typing a correction re-enables Connect, whose second attempt fails with a raw "Address already in use" because the first callback server still holds port 8888. | Code reading of the wizard's connect handler, `_update_connect_button_state` and `serve_until_callback`. | S9 |

### Low, structure and polish

| ID | Finding | Row |
|---|---|---|
| A-35 | Four separate `PlaylistNotFoundError` classes and two `LibraryLocationNotFoundError` classes; the CLI catches each one. | S13 |
| A-36 | The download state machine is about 300 string literals, and "terminal status" is defined three different ways. | S13 |
| A-37 | Service results are `dict[str, Any]` (download, poll, scan, match, tag), which defeats `--strict` at the UI boundary. | S14 |
| A-38 | `cli.handle_library` has complexity 52; the usage string is stale; the CLI imports from `seeker.ui`; interactive CLI code lives inside `download_service`. | S15 |
| A-39 | All 8 repositories store a `Database` they never use. There is dead code, legacy migrations for an already-migrated dev install, and `sharing_service` bypasses `SoulseekClient`. | S16 |
| A-40 | `download_service.py` is 1,902 lines, the only module below maintainability grade A. | S17 |
| A-41 | `main_window.py` is 2,281 lines, with 46 private-member reaches into pages. | S19, S20 |
| A-42 | Test fakes live inside a test module that 13 other modules import. Investigation scripts sit beside the tests, and the smoke-test file is 4,786 lines. | S18 |
| A-43 | About 1,025 history references in source comments ("Roadmap item 116 (round 8, §6.1.1)"). | S24, S25 |
| A-44 | `HISTORY.md` is 900 KB. 62 of its entries have titled headings whose short `#N` anchors do not resolve on GitHub, so 24 of CLAUDE.md's 43 numeric HISTORY links land at the top of the file. | S2 |
| A-45 | The `docs/` top level holds 11 briefs and a stale ledger. CLAUDE.md contains stale facts. | S1, S38 |
| A-46 | Nested library locations double-index 3,454 files (6,921 rows); one of the locations is a volume root. Fix approved. | S26 |
| A-47 | No widget has an accessible name, and keyboard focus is invisible on buttons. | S27 |
| A-48 | Internal jargon in the UI copy ("Settled", "art URLs", "same as the CLI", "Retrying (locked/queued)"). | S28 |
| A-49 | Empty states are missing, table columns are misallocated, and long playlist names are clipped behind a horizontal scrollbar. | S28 |
| A-50 | The README is 741 lines, with a stale test-count badge and stale screenshots; the project layout is duplicated between README and CLAUDE.md. | S36, S37 |
| A-51 | The theme is a generic "near-black with one violet accent"; its own docstring calls the light palette untuned. Visual refresh approved. | S30–S35 |
| A-52 | Files from superseded and duplicate downloads are never cleaned up (728 MB in the dev slskd folder). | X1 [ASK] |
| A-53 | The Downloads page has no retry or cancel. | X2 [ASK] |

## Stale statements corrected by this audit

- CLAUDE.md's open issue that `test_callback_server.py` fails on CI is
  **resolved**. All five of its tests run and pass on CI run
  `35906721903`.
- **Round 10 S2 cannot run as written.** The stuck review candidate it
  depends on no longer exists; the real database has 0 SoulSeek review
  candidates. The size-less legacy path cannot recur, because every
  candidate recorded since item 26 stores its size. S1 closes it as
  superseded.
- CLAUDE.md records `main_window.py` at 1,842 lines after Phase 6. It is
  2,281 lines.

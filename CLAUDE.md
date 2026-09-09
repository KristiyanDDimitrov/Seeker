# seeker

Personal DJ music library management assistant. Syncs Spotify playlists to a
local SQLite cache (to minimize API calls against Spotify's rate/quota
limits), matches cached tracks against a scanned local library, and — for
whatever's missing — searches SoulSeek (via a self-hosted `slskd` daemon)
to identify and download the highest-quality available file for each
track, then tags matched files with Spotify's canonical metadata. Ships
both a CLI (`seeker`) and a desktop GUI (`seeker-ui`, PySide6) over the
same service layer — see README.md for the full command/screen reference.

This is a portfolio project. Code quality, structure, and test coverage
matter as much as functionality — prefer the idiomatic/correct approach over
the fastest one.

## Architecture

Strict layering, always respected:

```
Presentation layer (cli.py, ui/*)
  -> Application / services (application.py, spotify/sync_service.py, dashboard_service.py)
    -> Repositories (database/repositories/*)
      -> Database (database/connection.py, database/schema.py)
```

Rule: presentation-layer code (CLI *or* UI) must never import or call a
repository directly. Every CLI handler and every Qt widget goes through
`Application` (or a service it exposes), the same way `handle_sync` goes
through `application.sync_service` and `MainWindow` goes through
`application.dashboard_service`. If a screen or command needs data,
add/extend a method on the service layer rather than reaching past it —
this is what `dashboard_service.py` exists for (see HISTORY §22):
the dashboard's playlist-scoped track status was a real gap in the
service layer, not something to assemble ad hoc from Qt code by calling
multiple repositories directly.

## Current layout

Regenerated against the real tree (S14) — Phase 6 (`ui/pages/*`) folded in.

```
src/seeker/
├── database/                 # connection.py, schema.py,
│                              #   repositories/{playlist,track,track_match,
│                              #   local_file,library_location,download_request,
│                              #   duplicate_cleanup,soulseek_review_candidate}
│                              #   _repository.py
├── spotify/                   # auth*.py, token*.py, callback_server.py,
│                              #   client.py (raw Web API calls), sync_service.py
├── soulseek/                   # client.py (slskd REST wrapper), quality.py
│                              #   (candidate filtering/selection),
│                              #   download_service.py (destinations,
│                              #   download_playlist, poll_downloads)
├── library/                     # scanner.py, matcher.py, service.py,
│                              #   metadata_service.py (writes Spotify tags/art),
│                              #   duplicate_service.py (fingerprint clustering)
├── ui/                          # seeker-ui (PySide6)
│   ├── main_window.py           #   shell only, post-Phase-6: sidebar nav,
│   │                          #   timers, tray wiring (6,882 -> 1,842 lines)
│   ├── pages/                    #   PageContext (context.py) is the seam —
│   │                          #   dashboard_page.py, tagging_panel.py,
│   │                          #   search_page.py, downloads_page.py,
│   │                          #   review_page.py, duplicates_page.py,
│   │                          #   sharing_page.py, history_page.py,
│   │                          #   static_pages.py (Help + Support)
│   ├── dialogs.py                 #   About, Destination, RenamePreview,
│   │                          #   BulkReplaceUpgrades, BulkResolveDuplicates
│   ├── tray.py                     #   tray icon, menu, notifications
│   └── settings_window.py, wizard.py, theme.py, notice.py, flow_layout.py,
│       busy_actions.py, workers.py (run_worker()), help_text.py,
│       formatting.py, download_eta.py, upload_eta.py,
│       library_location_picker.py
├── models/                     # dataclasses — playlist, track, track_match,
│                              #   local_file, library_location, soulseek_file,
│                              #   download_request, soulseek_review_candidate,
│                              #   active_download, track_status, upgrade_review,
│                              #   history_event, data_locations,
│                              #   duplicate_cleanup, needs_review_match
├── matching.py                 # shared fuzzy artist/title matching — used by
│                              #   BOTH library/matcher.py and soulseek/
│                              #   quality.py, neither has its own copy
├── metadata.py                  # write_text_tags/embed_album_art/
│                              #   write_analysis_tags — format dispatch
│                              #   (ID3/FLAC/MP4), used by metadata_service.py
├── destination_resolution.py    # resolve_playlist_destination — shared by
│                              #   metadata_service.py and download_service.py
├── audio_analysis.py            # analyze_audio (librosa BPM + Krumhansl-
│                              #   Schmuckler key estimate)
├── audio_fingerprint.py         # project-owned libchromaprint ctypes binding
├── audio_formats.py             # AUDIO_EXTENSIONS, DOWNLOADABLE_EXTENSIONS
├── dashboard_service.py, history_service.py, sharing_service.py
├── config_store.py              # SeekerConfig — the UI-editable JSON store;
│                              #   .env/config.py is the fallback when unset
├── docker_setup.py              # Docker/slskd detection, bring-up, health
│                              #   checks — shared by wizard.py/settings_window.py
├── download_dedup.py, file_deletion.py, filename_sanitize.py,
│   filename_format.py, update_check.py, album_art_cache.py
├── atomic_file.py               # write_text_locked() — 0600 + atomic writes
│                              #   for any credential/token file
├── config.py                     # .env-sourced fallback values
├── application.py, cli.py
├── main.py                       # `seeker` entry point
└── main_ui.py                     # `seeker-ui` entry point
```

## Conventions

- Python 3.13, `uv` for env/build (not pip/poetry).
- Type hints on everything; run mypy before considering work done.
- Models are dataclasses (see `models/track.py`, `models/playlist.py`) —
  keep it that way, no getter/setter classes.
- The SoulSeek integration runs against `slskd` (self-hosted daemon, REST
  API), not a raw protocol library. `SoulseekClient` is synchronous
  `httpx`, matching `SpotifyClient` exactly — same pattern, same testing
  approach (mock the HTTP layer).
- DB access is raw SQL via the repository pattern (see `schema.py` /
  `*_repository.py`), not an ORM. Keep new tables/queries consistent with
  that style unless explicitly deciding to add SQLAlchemy.
- Tests: pytest, mock all external HTTP (Spotify, SoulSeek) — never hit
  real APIs in tests.
- **Read discipline — never read a large file whole.** `docs/HISTORY.md`
  (~800 KB), `tests/test_ui_smoke.py`, `src/seeker/ui/main_window.py`
  each blow a session's budget alone if read in full — `grep -n` for
  the symbol/section and read that range instead. `uv run pytest -q`,
  report only the summary line plus named failures. `git diff --stat`
  by default. Don't re-read a file just edited — Edit/Write error on
  failure already.
- **Lint yes, format no — `ruff format` is deliberately not adopted.**
  This codebase's hand-written house style doesn't match `ruff
  format`'s output (confirmed via `ruff format --diff`: 4-space hang vs.
  this project's 8-space compound-header hang) — reformatting the whole
  tree would destroy `git blame` project-wide for no gain. `ruff check`
  is the enforced gate. [HISTORY §115](docs/HISTORY.md#115)
- **Hanging indent, verified by sampling, not assumed: 8 spaces for a
  compound statement header that wraps** (`def`/`if`/`while`/`for`/
  `with`/`class`/etc. — anything ending `:` with an indented body
  next), **4 spaces for everything else** (calls, `return`/`raise`/
  `assert`, assignments, comprehensions, imports) — the header's own
  body is already +4, so its continuation goes +8 to stay visually
  distinct. Trailing commas before a closing bracket; ~72-column prose
  wrapping. [HISTORY §115 §4.8.1](docs/HISTORY.md#115)
- **Line length: `ruff`'s enforced ceiling is 88, but ~72-79 stays the
  house habit** for hand-wrapped prose/comments — 79 was tried as the
  enforced ceiling and reverted (341 real violations, not the 106
  first estimated; 88 is a ceiling the codebase can actually sit
  near-zero on). [HISTORY §115](docs/HISTORY.md#115)
- **`assert` in `src/` narrows types/logic invariants; it never
  validates user input or an external response** — `S101` is ignored
  project-wide on this basis, every real finding read individually. A
  new `assert` validating something user/externally controlled needs a
  real `if`/`raise` instead. [HISTORY §115](docs/HISTORY.md#115)
- **Never run `ruff check --fix` with a narrowed `--select`, especially
  not `--select RUF100` alone** — `RUF100` flags a `noqa` as unused
  against only the rules *enabled in that invocation*; narrowing to
  `RUF100` makes every other rule's directive read as unused and
  `--fix` deletes them all. Confirmed by direct reproduction.
  [HISTORY §115](docs/HISTORY.md#115)
- **Credential files (config.json, the Spotify token cache) go through
  `seeker/atomic_file.py::write_text_locked()`** — 0600 + atomic
  temp-file-then-replace, never a bare `write_text()`.
  [HISTORY §116](docs/HISTORY.md#116)
- **Not using the macOS Keychain for the Spotify token — deliberate,
  not an omission.** It would add a dependency, a platform-specific
  path, and a migration, to protect a file that's already 0600 in the
  user's own per-account home directory. Revisit only if this stops
  being a single-user local app. [HISTORY §116](docs/HISTORY.md#116)
- **`.env` was committed twice in this repo's history, assessed, not a
  live secret.** The Spotify client ID it held is PKCE-public by design
  (this app has no client secret at all); the one field that could have
  been secret was always the literal placeholder `your_…`. Decision: no
  history rewrite.
- **A comment earns its place by telling the next person something the
  code cannot.** One that tells them what *happened* belongs in
  `docs/HISTORY.md` instead. Test is shelf life, not length: is this
  still true and load-bearing next year, or a record of a decision?
  Applied across S12/S13's comment triage — see [HISTORY
  §119](docs/HISTORY.md#119) for the largest single example, the whole
  Phase 6 extraction story moved out of the page modules' docstrings.
- **Services use `logging`, never `print` — `print` is the CLI's own
  output channel, nothing else's.** Each service module gets its own
  `logger = logging.getLogger(__name__)`; handlers are configured in
  exactly two places, `main.py` (a `StreamHandler`) and `main_ui.py` (a
  `RotatingFileHandler` under `platformdirs.user_log_dir("Seeker")`) —
  never in library code. Where a message is both user-facing and
  diagnostic, the service logs and returns a structured result, and
  `cli.py` does the printing from that result. A `print` call
  surviving in a service (`soulseek/download_service.py`'s two) is
  either opt-in debug output gated on an env var, or genuinely
  CLI-only code that happens to live there — check the call site
  before assuming it is a leftover.
- **`ui/` never reads or writes `Application`'s private
  (underscore-prefixed) attributes** — go through a public method
  (`application.settings`, `application.update_settings(...)`, a
  service) instead, so `Application` can invalidate whatever depends on
  the change. `test_no_private_application_attribute_access_in_ui`
  (`tests/test_ui_smoke.py`) is an AST sweep enforcing this — it fails
  the build, not just the convention.
- **Page widgets live in `ui/pages/`, one `QWidget` subclass per page,
  never a `MainWindow` mixin.** Each takes a `PageContext`
  (`ui/pages/context.py` — application, thread pool, busy-action
  registry, `navigate`, `notify`) and never reaches back into
  `MainWindow`; `MainWindow` itself is the shell (nav, timers, tray).
  [HISTORY §119](docs/HISTORY.md#119)
- **Five UI feedback channels, each with exactly one job — never blur
  them.** Activity strip (top): GLOBAL, cross-page, whatever
  `busy_actions` reports running anywhere, auto-hides when idle.
  `next_step_notice`: Dashboard-only persistent proactive guidance.
  `InlineNotice` (`dashboard_notice`/Library's `notice`/a page's own):
  persistent, dismissible — errors/warnings/results/confirmations,
  anything the user needs to still read a few seconds later. Page-local
  `status_label`: ephemeral, disposable progress text only — wiped
  unconditionally at the start of every `run_worker`/`run_busy_worker`
  call, so nothing worth re-reading belongs there. Tray notifications:
  background-attention, real OS popups independent of which page (if
  any) is focused. A new page's confirmation/result message goes on its
  own `InlineNotice`, never on its `status_label` — a real bug this
  round (`sharing_page.py`'s confirmation was wiped before it could be
  read) was exactly that mistake. [HISTORY §120](docs/HISTORY.md#120)

## Commands

```
uv sync              # install deps
uv run seeker         # run the CLI
uv run seeker-ui       # run the GUI (PySide6) — onboarding wizard on first launch
uv run pytest         # run tests
uv run mypy --strict src/  # type check — must stay clean
```

## Standing facts and gotchas

Present-tense rules that shape the next piece of code, grouped by area.
Each links to the HISTORY.md item where the full investigation lives.

### Spotify / OAuth

- `SpotifyClient` takes a `TokenSource` (`str | Callable[[], str]`), not a
  bare string. On a 401 it calls an optional `force_refresh` callable and
  retries **exactly once**; a second 401 raises
  `SpotifyAuthenticationError` rather than a raw `httpx` error.
  [HISTORY §92](docs/HISTORY.md#92)
- Spotify rotates PKCE refresh tokens — two installs sharing one
  account/client ID can invalidate each other's stored refresh token.
  [HISTORY §92](docs/HISTORY.md#92)
- Playlist track entries come from `entry["item"]`, gated by
  `item["type"] == "track"` (Feb 2026 API migration repurposed the old
  `"track"` key as a type flag).
  [HISTORY](docs/HISTORY.md#spotify-field-name-and-endpoint-history-get_playlist_tracks)
- `get_current_user_playlists` reads `playlist["items"]["total"]`, never
  `["tracks"]["total"]`.
  [HISTORY](docs/HISTORY.md#spotify-field-name-history-get_current_user_playlists)
- The token cache path is resolved via `platformdirs`, not
  CWD-relative — a double-clicked `.app`'s CWD can be unwritable.
  [HISTORY §43](docs/HISTORY.md#43)

### SoulSeek / slskd

- Two distinct credential pairs exist and are easy to confuse:
  `SLSKD_SLSK_USERNAME`/`PASSWORD` is the **Soulseek network** login;
  `SLSKD_USERNAME`/`PASSWORD` is the **web UI** login. Confirmed live
  against a real container. [HISTORY §23](docs/HISTORY.md#23)
- `GET /api/v0/searches/{id}` only returns populated `responses` with
  `?includeResponses=true` — without it you get a real `isComplete` but
  a silently empty `responses` array. [HISTORY §4](docs/HISTORY.md#4)
- A locked file's `request_download` succeeds immediately; the
  rejection only surfaces later via `get_download_status` as
  `"Completed, Rejected"`. Three distinct rejection shapes exist total
  (locked-file, a synchronous 404 at enqueue for a peer gone offline,
  and a slow log-only bad-credentials/kicked distinction — `/api/v0/
  application`'s `ServerState` carries no error/reason field at all, so
  `check_slskd_health` reads `/api/v0/logs` with a `since:` filter).
  [HISTORY §13](docs/HISTORY.md#13)
- `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection()` apply
  unconditionally to any `download_requests.role`, not just
  `role='upgrade'`. [HISTORY §13](docs/HISTORY.md#13)
- Exponential backoff plus a terminal `unavailable` status after 8
  attempts structurally bounds any future retry storm's rate,
  regardless of cause — added after a real, still-unexplained
  production storm (see Open issues, item 63).
  [HISTORY §66](docs/HISTORY.md#66)
- A generated slskd web UI login only takes effect on a genuinely fresh
  install — slskd silently refuses to let `SLSKD_USERNAME`/`PASSWORD`
  override an already-customised login. Confirmed live both ways: a
  fresh throwaway container accepts it (real `200` from
  `POST /api/v0/session`); a container with a pre-existing login
  returns a real `401` for the generated one.
  `docker_setup.check_slskd_web_login()` checks this directly; Settings
  only displays a credential once confirmed active.
  [HISTORY §116](docs/HISTORY.md#116),
  [§117](docs/HISTORY.md#117)
- The slskd web UI is bound to loopback only
  (`127.0.0.1:5030:5030`/`5031:5031`); `50300` must stay published on
  every interface for real incoming Soulseek peer connections.
  `SLSKD_REMOTE_CONFIGURATION=false`. [HISTORY §116](docs/HISTORY.md#116)
- §6.1's original HIGH severity assumed a vendor-default `slskd`/`slskd`
  web UI login; Kris's own machine had already changed it, so his real
  exposure was lower than assessed — but the fix stays correct and
  necessary, since a fresh install by anyone else lands on that
  default. [HISTORY §116](docs/HISTORY.md#116)

### Qt, threading, and UI

- `ui/workers.py`'s `Worker`: one shared, permanently-connected
  dispatcher QObject, never a fresh one per task —
  connect/disconnect cycling through Qt's mutex pool per call caused a
  real deadlock under heavy concurrent use. `setAutoDelete(False)` plus
  a `task_id`-only signal (never `self`) plus a deferred native delete
  are all independently required. [HISTORY §39](docs/HISTORY.md#39)
- A `Worker` must be kept alive via a strong reference
  (`_active_workers: set[Worker]`) until its own finished/error signal
  fires — `QThreadPool.start()` returning early lets GC collect it
  mid-flight. [HISTORY §22](docs/HISTORY.md#22)
- `Qt.ConnectionType.SingleShotConnection` is required on
  `run_worker`'s cross-thread connections — the reference cycle
  otherwise formed is invisible to Python's GC (the Qt/shiboken side
  isn't visible to the tracer), and a manual `disconnect()` from inside
  its own handler mid-emission segfaults. [HISTORY §32](docs/HISTORY.md#32)
- `WA_DeleteOnClose` on a top-level window must be cleared the moment a
  real tray icon exists, or the first close after that deletes the
  window's C++ object and "reopen from tray" breaks permanently.
  [HISTORY §114](docs/HISTORY.md#114)
- `QHeaderView::section:horizontal:last-child` is invalid Qt QSS (valid
  CSS, not Qt's dialect) and silently poisons the **entire**
  `::section` rule — use `:last` alone.
  [HISTORY §103](docs/HISTORY.md#103)
- Any `setStyleSheet()` call must carry a selector — a selector-less
  rule parses as a universal `*` rule and silently strips styling off
  every descendant widget's box model.
  [HISTORY §114](docs/HISTORY.md#114)
- `setSpan()` must be called **before** `setCellWidget()` on the
  span-owning cell, and no widget of any kind belongs on the cells it
  covers — a "blank placeholder" widget resolves to the same geometry
  as the real span-owning widget and paints over it.
  [HISTORY §77](docs/HISTORY.md#77)
- A bare `QProgressBar`/`QPushButton` handed straight to
  `setCellWidget` renders top-clamped or stretched to fill the whole
  cell — always wrap it in a centering container widget. A structural
  test walks every table for this.
  [HISTORY §104](docs/HISTORY.md#104)
- `QTableWidget::item { padding }` corrupts a `QPushButton` living
  inside a cell widget (safe on `QListWidget`). A plain `QWidget`
  subclass needs `WA_StyledBackground` to paint its own stylesheet
  background/border at all. [HISTORY §47](docs/HISTORY.md#47)
- Tests must exercise the real theme stack —
  `tests/conftest.py` calls `theme.apply_theme()` in a session-scoped
  autouse fixture — otherwise a `window.grab()` pixel/geometry
  assertion runs against Qt's default style, not the shipped
  Fusion+QSS+dark-palette one. [HISTORY §103](docs/HISTORY.md#103)
- Under the offscreen QPA test platform: `colorSchemeChanged` never
  actually fires, and a plain `QApplication.processEvents()` does
  **not** flush Qt's deferred deletion — use
  `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`.
  [HISTORY §109](docs/HISTORY.md#109),
  [§116](docs/HISTORY.md#116)
- A `.hide()`'n `QWidgetItem`'s `setGeometry()` is a real no-op —
  exclude hidden items from any `FlowLayout` geometry assertion.
  [HISTORY §79](docs/HISTORY.md#79)
- `get_config` on `TrackMatcher`/`DownloadService`/`MetadataService` is
  a **callable**, not a snapshot — a Settings change takes effect
  immediately, no restart. [HISTORY §28](docs/HISTORY.md#28)

### Database and migrations

- `local_files`' analysis/fingerprint columns (`bpm`, `camelot_key`,
  `key_confidence`, `fingerprint*`) are excluded from `upsert()`'s
  `ON CONFLICT DO UPDATE` — a routine scan must never wipe prior
  analysis. [HISTORY §11](docs/HISTORY.md#11),
  [§39](docs/HISTORY.md#39)
- `track_matches.confirmed_at` protects a human-confirmed match from
  being silently demoted by a later `match_all()` re-run, which
  otherwise has no provenance concept at all.
  [HISTORY §56](docs/HISTORY.md#56)
- Deleting a local file: DB row first, then the file on disk. Renaming
  one: the opposite order, file then DB row.
  [HISTORY §40](docs/HISTORY.md#40), [§67](docs/HISTORY.md#67)
- `Database.transaction()` opens a new connection per call — safe to
  use across threads. [HISTORY §22](docs/HISTORY.md#22)

### Packaging

- `sys.frozen` gates every bundled-resource path lookup via
  `sys._MEIPASS` (compose file, icons, everything) — the same pattern
  any future bundled-resource lookup should follow.
  [HISTORY §30](docs/HISTORY.md#30)
- One-folder PyInstaller mode over one-file, deliberately — numba's
  JIT cache only persists across runs in one-folder mode (~1s vs.
  ~18-21s every run in one-file). [HISTORY §30](docs/HISTORY.md#30)
- PyInstaller's `BUNDLE()`/`EXE()` already ad-hoc-sign by default with
  no `codesign_identity` given — call it "ad-hoc signed, not
  notarized," never "unsigned." [HISTORY §36](docs/HISTORY.md#36)
- Build identity: `packaging/build_dmg.py` writes a gitignored
  `src/seeker/_build_info_generated.py`; the tracked `_build_info.py`
  only `try/except ImportError`s it, falling back to `"dev"` — never
  write the tracked file directly (doing so once permanently dirtied
  the tree on every real build). [HISTORY §83](docs/HISTORY.md#83)
- GUI launches get launchd's bare minimal PATH —
  `docker_setup.ensure_full_path_environment()` merges `path_helper`
  output plus explicit Homebrew/Docker-Desktop fallbacks into
  `os.environ["PATH"]` once, at `Application.__init__`.
  [HISTORY §44](docs/HISTORY.md#44)

## Open issues

Genuinely open only — no "done" items, no flakes that resolved.

- **Item 63 — a real locked-file retry storm against production slskd
  (300+ retries of one row in ~18 min), root cause still
  unidentified.** Three dedicated follow-up runs individually and
  jointly ruled out locked-row presence, a zero-locked baseline, and
  heavy combined load as the trigger. One lead: a real one-off `500` on
  `/api/v0/transfers/downloads/batches` matching the storm's own error
  text, but as a single enqueue failure, not a cascade. The retry-rate
  bound added since (exponential backoff + terminal `unavailable` after
  8 attempts) means this storm shape can't recur even though *why* it
  happened is still unknown. [HISTORY §63](docs/HISTORY.md#63)
- **Item 70 — a real stress-test hang at production library scale
  (~3,100 files), root cause still unidentified.** Reproduced 3/3 times
  at production scale, always right after sync/scan/match settle,
  waiting on Duplicates' Compute Fingerprints — but not in 2/2 isolated
  repros, one at 1,500-file scale. A `faulthandler` watchdog never fired
  once across ~38 stuck minutes, implicating whole-process GIL
  starvation, not just a stuck Qt loop. **Answered (round 6): this is a
  separate defect from item 105's pytest-runner stall** — different
  symptom, trigger, and mechanism. Real Spotify sync duration and/or
  real DB size/content are the untested suspects.
  [HISTORY §70](docs/HISTORY.md#70)
- **Four unconfirmed round-8 test flakes.** Diagnose any recurrence
  directly — never reach for `pytest-rerunfailures`.
  - `test_close_event_falls_back_to_real_close_when_no_tray` — fired
    once across ~12 full-suite runs, clean since. Round 8 §14
    subsequently modified `closeEvent` directly — check that first if
    it recurs.
  - `test_review_tab_replace_button_calls_apply_upgrade_decision_with_delete_flag`
    — fired once after a `docker-compose.yml`-only commit, clean since.
  - `test_history_refresh_button_refetches` — timed out roughly 1-in-8
    to 1-in-10 full-suite runs. A real cause was found and fixed
    (pytest-qt's own teardown doesn't flush Qt's deferred deletion,
    letting a previous test's live `MainWindow` react to a later
    test's `applicationStateChanged`) via an autouse fixture, confirmed
    closed with a weakref/gc probe — but the flake recurred at least
    once **after** that fix, cause still unknown. Worth instrumenting
    `_run_busy_worker`/`QThreadPool` timing directly next time. One of
    the post-fix recurrences is a real, inspectable CI run
    (`34207858803`, 2026-09-08) — a live example if this needs
    instrumenting for real. [HISTORY §116](docs/HISTORY.md#116)
  - `test_fullscreen_close_policy_check_ignores_a_stale_request` — fired
    once during S13 (round 8, comment-triage-only session — nothing in
    that session touched close/fullscreen logic, so not a regression
    from it). Passed cleanly when re-run alone immediately after.
    Consistent with fullscreen-close instability informally noted
    across S11.2-S11.7 but never before named here specifically. **S14:
    a second, different fullscreen-close test
    (`test_reopening_after_a_fullscreen_close_restores_prior_geometry`)
    fired alongside it in the same full-suite run** (this session
    touched only `CLAUDE.md`/`README.md`, so again not a regression
    from the session's own work) — both passed cleanly re-run alone
    immediately after. Two different tests in the same fullscreen-close
    area failing together, only under the full suite, is stronger
    evidence of a real ordering/state-leak bug in that area than either
    single occurrence was; worth a dedicated diagnosis session if it
    recurs a third time.
- **Three registered library locations nest inside each other and
  double-index ~3,450 real files** — `add_location`/
  `add_location_from_path` only check exact path-string uniqueness, no
  containment check exists. A real user decision, deliberately left
  open. [HISTORY §93](docs/HISTORY.md#93)
- **`test_callback_server.py`: 3 real tests (`test_wait_for_callback_
  parses_code_and_state_from_real_request`,
  `..._captures_error_param`, `..._returns_404_but_keeps_waiting...`)
  fail on CI (`macos-latest`) with `httpx.ConnectTimeout` connecting to
  the test's own local `HTTPServer`, root cause unconfirmed.** Pass
  reliably locally. A thread-startup race was checked and ruled out (a
  too-early connection is refused instantly, not timed out at 5s).
  **S14 update: CI is not billing-blocked any more (see below) and
  `gh run view` now IS a live runner to check against** — all three
  runs inspected (`34207858803`, `34207444009`, `34206885872`,
  2026-09-08) reproduce exactly these 3 failures, consistently, nothing
  else related. Leading hypothesis on *why* — still UNVERIFIED, `gh`
  can't inspect macOS's own permission-prompt state — is macOS's Local
  Network permission prompt silently blocking an unsigned process's
  loopback listener in a non-interactive session.
  [HISTORY §117](docs/HISTORY.md#117)
- **CI is real and running (not billing-blocked) as of 2026-09-08 —
  the S1.1/§117 "never completed a real run" finding is superseded.**
  Confirmed live via `gh run list`/`gh run view`: three consecutive
  completed runs on `origin/main`, ruff/mypy clean on all three, pytest
  failing on exactly the two known issues above (never anything new).
  The 29-vs-1 skipped-test mismatch an earlier round left as an open
  question is now explained, not just observed: 29 = 28
  `@requires_x9_pro`-gated tests (no such drive on a GitHub runner) + 1
  `@requires_stress_opt_in` test (opt-in only) — exact arithmetic
  match. The 1 skip everywhere else is real-hardware machines running
  the x9_pro-gated tests for real and skipping only the opt-in stress
  test.

## Roadmap

Forward-looking only — see `docs/HISTORY.md` for everything shipped.

- **Round 8 — refactor, layering, dedup, `MainWindow` decomposition, and
  this doc pass — in progress.** Session map:
  `docs/round8/SESSION-PLAN.md`. Full plan:
  `docs/BRIEF-2026-09-08-refactor.md`. Security phase (done):
  `docs/BRIEF-2026-09-09-security.md`.
- **Linux packaging** (AppImage or `.deb`) — deprioritized, not scoped.
- **SoundCloud as a second source — deliberately deferred, not
  started.** Two disqualifying blockers found researching it:
  registering a SoundCloud API app requires a paid Artist Pro
  subscription, and it requires a confidential `client_secret` even for
  a native app — incompatible with a distributed `.dmg` holding no
  secret and no proxy server. If picked up: bring-your-own-credentials
  (Settings, like the existing Spotify field), source toggle top-right
  of the Dashboard. No code/schema/stubs exist yet.
- **UX proposals needing Kris's explicit yes** (brief §12.6–§12.10) —
  product decisions, not scheduled without approval.
- **The brief's §9.4** (long functions beyond `MainWindow`'s own
  decomposition) — optional; fold into a session that finishes early,
  or skip and say so.

## Working agreements

Hard-won, all five stay.

1. **Two-tier docs.** This file holds only present-tense standing facts
   short enough to read in full before starting; `docs/HISTORY.md`
   holds the full investigation narrative a future debugging session
   needs. When closing an item: a condensed note here (over ~8 lines
   belongs in HISTORY only, linked), and — only if genuine
   investigation happened — a matching HISTORY entry. Move, never
   delete: a "done" item's detail must land in HISTORY before it
   leaves this file.
2. **Checking whether a test failure is "pre-existing": always `git
   stash -u`, never a bare `git stash`.** A bare stash doesn't stash
   untracked files, so it can't see a defect living in one (e.g. a
   gitignored `_build_info_generated.py` from a real local build).
3. **The pre-existing-failure count is a tracked number, not a label.**
   Report the actual `pytest` summary line and name every failing test,
   every time — never a paraphrase like "green with N pre-existing
   failures." A count that changes between rounds is a regression to
   diagnose, never a new baseline to quietly adopt.
4. **A comment asserting platform or framework behavior must cite a
   real observation or say UNVERIFIED plainly.** This codebase has been
   burned twice by an unmarked confident claim turning out false (an
   invalid `:last-child` QSS selector that silently poisoned a whole
   rule; a macOS tray-click routing claim a real user's report
   disproved).
5. **Any `continue`/`skip` inside a sweep test must be justified in a
   comment that names what it excludes and why that exclusion can't
   hide the bug the test exists for.** A skip condition derived from
   the same state a bug corrupts is not a guard; it's a blindfold.

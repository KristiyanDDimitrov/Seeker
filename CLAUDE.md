# seeker

Personal DJ music library assistant. Syncs Spotify playlists to a local
SQLite cache (to spare Spotify's rate and quota limits), matches the
cached tracks against a scanned local library, searches SoulSeek (via
a self-hosted `slskd` daemon) for whatever is missing, downloads the
best-quality file, and tags matched files with Spotify's metadata. A
CLI (`seeker`) and a PySide6 GUI (`seeker-ui`) share one service
layer; `docs/cli.md` maps each command to its screen.

A portfolio project: code quality, structure and test coverage matter
as much as function. Prefer the idiomatic, correct approach over the
fastest one.

## Architecture

```
Presentation (cli.py, ui/*)
  -> Application / services (application.py, *_service.py)
    -> Repositories (database/repositories/*)
      -> Database (database/connection.py, database/schema.py)
```

Presentation code, CLI or UI, never imports or calls a repository: it
goes through `Application` or a service it exposes
(`application.sync_service`, `application.dashboard_service`). A
screen or command that needs data gets a service method, never a
result assembled from several repositories in Qt or CLI code; that gap
is why `dashboard_service.py` exists. [§22](docs/history/001-024.md#22)
`tests/test_layering.py` fails the build if `ui/`, `cli.py` or an
entry point imports `seeker.database`, `cli.py` imports `seeker.ui`,
anything but `ui/` and `main_ui.py` imports Qt, or `models/` imports
outside `models/`.

## Layout

The one module map is [docs/architecture.md → Module
map](docs/architecture.md#module-map), regenerated from the tree. In
short, under `src/seeker/`:

- `database/` (connection, schema, `repositories/`) · `models/` (dataclasses)
- `spotify/` · `soulseek/` (slskd client, download, poll, placement,
  review, Docker, sharing) · `library/` (scan, match, tags, duplicates)
- `audio/` · `files/` · shared modules (`matching.py`, `errors.py`, …)
- `ui/` — `main_window.py` (the shell), `pages/` (one per page),
  dialogs, theme, widgets · `application.py`, `cli.py`, `main*.py`

## Conventions

- Python 3.13; `uv` for env and build. Type hints everywhere; `mypy
  --strict` clean before work is done. Models are dataclasses, no
  getter/setter classes.
- slskd through its REST API, never a raw protocol library.
  `SoulseekClient` is synchronous `httpx`, the same pattern as
  `SpotifyClient`, tested the same way: mock the HTTP layer. No test
  hits a real API.
- DB access is raw SQL through repositories, no ORM, unless a
  deliberate decision adds SQLAlchemy.
- **Read discipline: never read a large file whole.** A
  `docs/history/*.md` file (~150 KB) or `ui/main_window.py` alone
  blows a session's budget: `grep -n`, then read the range. pytest:
  the summary line plus named failures. `git diff --stat` by default.
  Never re-read a file just edited.
- **`ruff check` is the gate; `ruff format` is deliberately not
  adopted.** The house style differs (an 8-space hang on wrapped
  compound headers) and reformatting would wreck `git blame`. Never
  run `ruff check --fix` with a narrowed `--select`: `RUF100` judges a
  `noqa` against only the enabled rules, so `--select RUF100 --fix`
  deletes every other directive (reproduced). A preview rule is
  selected by exact code: under `explicit-preview-rules`, `E30`
  selects none. [§115](docs/history/108-120.md#115),
  [§149](docs/history/121-150.md#149)
- **Indent: 8 spaces for a wrapped compound-statement header**
  (anything ending `:` with a body: `def`, `if`, `with`, `class`, …),
  **4 for everything else** (calls, `return`, assignments,
  comprehensions, imports). Trailing commas before a closing bracket.
  Line ceiling 88 (enforced; 79 was tried, 341 violations); prose and
  comments wrap at ~72–79. [§115](docs/history/108-120.md#115)
- **CI enforces what a local run may not:** `uv sync --locked` (a
  dependency change ships with its `uv.lock`); branch coverage ≥ 92 %
  (`--cov-fail-under`, the measured value minus one); actions
  SHA-pinned with a version comment, bumped by Dependabot; a
  dependency audit, `tools/audit_dependencies.py` (pip-audit over
  every locked group, weekly too), whose `audit_ignore.toml` entries
  each carry a reason and an expiry date. pip-audit cannot see native
  libraries: `docs/packaging.md` records them for each release.
  [§149](docs/history/121-150.md#149), [§167](docs/history/151-180.md#167),
  [§199](docs/history/181-210.md#199)
- **`assert` in `src/` narrows types and invariants; it never
  validates user input or an external response** (an `if`/`raise`
  does). `S101` is ignored on that basis.
  [§115](docs/history/108-120.md#115)
- **A fix starts with a failing test** that fails on unmodified
  `HEAD` for the stated reason. One commit per change; a refactor
  commit changes no behaviour, a behaviour commit refactors nothing.
  [§138](docs/history/121-150.md#138)
- **The user's real data is read-only to a session.** Never write the
  real database, `config.json`, the Spotify token, music files or
  slskd state; `sqlite3 -readonly "$HOME/Library/Application
  Support/Seeker/seeker.db"` is fine. A migration is rehearsed on a
  scratchpad copy with before and after counts, and runs for real
  only when Kris next launches the app. Never start, stop or recreate
  the slskd container (`docker inspect`, `docker compose … config`
  are fine). [§172](docs/history/151-180.md#172)
- **Credential files (`config.json`, the Spotify token cache) go through
  `files/atomic.py::write_text_locked()`:** a temp file 0600 from
  `os.open(O_EXCL)` (never chmod'd after), fsync'd, renamed; never a bare
  `write_text()`. No Keychain, deliberately: a dependency, a platform path
  and a migration to protect a 0600 file in the user's home; revisit only
  if this stops being a single-user app.
  [§116](docs/history/108-120.md#116), [§146](docs/history/121-150.md#146)
- **A tag write saves through `audio/tags.py::save_tags()`, never
  mutagen's `save()`.** Tags that outgrow the padding go through
  `files/atomic.py::rewrite_via_copy()`: mutagen shifts the audio in
  place, and a crash mid-shift corrupts MP3, FLAC and faststart M4A
  (measured). A FLAC key goes to both `INITIALKEY` and `KEY`.
  [§167](docs/history/151-180.md#167)
- **`.env` is read only by an entry point.** `config.py`'s values are
  functions over `os.environ`, read at call time; `main()` in
  `main.py`/`main_ui.py` calls `config.load_env_file()` (cwd upward;
  never when frozen). Tests set environment variables, never patch
  `config`. `.env` was committed twice; no history rewrite, since the
  client ID is PKCE-public and the one secret-shaped field was always
  a placeholder. [§146](docs/history/121-150.md#146)
- **A comment tells the next person what the code cannot.** What
  *happened* belongs in `docs/history/`; the test is shelf life. A
  comment, docstring or `--help` text never says "round N", "item N",
  "Roadmap item N" or "§x.y": it points at `HISTORY §N`, and `grep
  -rcE "Roadmap item|round [0-9]+|§[0-9]" src/` finds only those.
  [§119](docs/history/108-120.md#119), [§170](docs/history/151-180.md#170)
- **Services log, never `print` or `input`.** Each module has
  `logger = logging.getLogger(__name__)`; handlers exist only in
  `main.py` (`StreamHandler`) and `main_ui.py` (`RotatingFileHandler`
  under `platformdirs.user_log_dir("Seeker")`), which also installs
  `ui/error_hooks.py` (`sys.excepthook`/`threading.excepthook` at
  CRITICAL, Qt messages to `seeker.qt`). A message that is both
  user-facing and diagnostic: the service logs and returns a result,
  `cli.py` prints it. Prompts (the upgrade review too) live in
  `cli.py`; diagnostics are `logger.debug`, enabled per logger at the
  entry points (`SEEKER_DEBUG_POLL=1`). [§156](docs/history/151-180.md#156)
- **Text a user reads about a failure comes from
  `error_text.describe_error`**, in workers and the CLI alike. A new
  external failure kind gets a branch there, never ad hoc text at a
  call site; Seeker's own exception messages are kept, so write them
  as sentences. [§150](docs/history/121-150.md#150)
- **Every public error is a `SeekerError`** (`errors.py`), which
  `cli.run` catches as one. One raised by several modules is defined
  once in `errors.py`; any other sits beside its module.
  `tests/test_errors.py` fails the build. [§153](docs/history/151-180.md#153)
- **Download states are `DownloadStatus`/`DownloadRole`**
  (`models/download_request.py`, `StrEnum`s equal to the stored
  strings), grouped only through its named sets (`IN_FLIGHT`,
  `UNRESOLVED`, `STAMPS_COMPLETED_AT`, …); a new grouping is a new set
  there, never a literal at the call site. SQL takes them as
  parameters. [§153](docs/history/151-180.md#153)
- **A service result is a dataclass, never a string-keyed dict.** One the
  CLI or `ui/` reads lives in `models/` (`download_result`,
  `library_result`, `tag_result`, `fingerprint_result`); a count that must
  agree with a list derives from it (`failed` is `len(failures)`). Detail
  rows stay `{track_id, reason, message}` dicts.
  [§154](docs/history/151-180.md#154), [§155](docs/history/151-180.md#155)
- **`ui/` never touches `Application`'s underscore attributes**; it
  goes through a public method (`application.settings`,
  `update_settings(...)`, a service) so `Application` can invalidate
  what depends on the change. An AST sweep in
  `tests/test_ui_source_sweeps.py` fails the build.
- **One `QWidget` per page in `ui/pages/`, never a `MainWindow`
  mixin.** A page takes a `PageContext` (`ui/pages/context.py`) and
  never reaches into `MainWindow`, the shell (nav, timers, tray). A
  page owns its buttons' actions; the shell calls only public page
  methods (`poll_*`, `refresh_*`, `on_shown`, `focus_track`).
  Cross-page selection goes through `PageContext.playlist_selection`
  (`ui/playlist_selection.py`), which Dashboard and Library both
  write, playlist and track ids alike. `SLF001` is enforced over
  `src/`; its one `noqa` is `sys._MEIPASS`.
  [§119](docs/history/108-120.md#119), [§133](docs/history/121-150.md#133),
  [§162](docs/history/151-180.md#162), [§185](docs/history/181-210.md#185)
- **Five UI feedback channels, one job each.** The activity strip:
  whatever `busy_actions` reports running anywhere, hidden when idle.
  `next_step_notice`: the Dashboard's standing guidance. An
  `InlineNotice` (persistent, dismissible): errors, warnings, results,
  confirmations, anything read a few seconds later. A page's
  `status_label`: disposable progress only, wiped at the start of
  every `run_worker`/`run_busy_worker`, so a confirmation there is
  lost (Sharing's was). Tray notifications: OS popups for background
  attention. An action reports through the `FeedbackTarget`
  (`ui/notice.py`) of the page it started from (a panel reached from
  another page takes its caller's); a timer-driven `run_worker` never
  passes `status_label`. [§120](docs/history/108-120.md#120),
  [§150](docs/history/121-150.md#150)
- **No widget guesses whether its text is HTML.** Labels are
  `PlainLabel`, or `RichLabel` for Seeker's markup with data
  `html.escape`d; message boxes go through `plain_text.question`/
  `information`/`warning` or set `setTextFormat`; a data tooltip goes
  through `plain_tooltip()`. Peer filenames, usernames and slskd text
  otherwise render as markup. Five `ast` sweeps (`ui/`, `main_ui.py`) in
  `tests/test_plain_text.py`; the CLI passes peer strings through
  `cli.printable()`. [§148](docs/history/121-150.md#148)
- **The tracked Compose template is portable:** no `/Volumes/` or
  `/Users/` literal, every bind source a required variable
  (`${SLSKD_SHARE_PATH:?set by Seeker}`), the share mount read-only,
  the image pinned by tag and digest
  (`slskd/slskd:X.Y.Z@sha256:…`).
  `tests/test_compose_template.py` fails the build.
  [§140](docs/history/121-150.md#140)

## Commands

```
uv sync              # install deps
uv run seeker         # run the CLI
uv run seeker-ui       # run the GUI (PySide6) — onboarding wizard on first launch
uv run pytest         # run tests
uv run mypy --strict src/  # type check — must stay clean
uv run ruff check src tests tools  # lint — CI's exact gate, 0 findings
uv run python tools/screenshots.py  # every screen, both themes -> tools/.screens/
```

## Standing facts and gotchas

Present-tense rules, each linked to the HISTORY entry holding its
investigation; `docs/history/README.md` resolves any `§N`.

### Spotify / OAuth

- `SpotifyClient` takes a `TokenSource` (`str | Callable[[], str]`).
  On a 401 it calls an optional `force_refresh` and retries **exactly
  once**; a second 401 raises `SpotifyAuthenticationError`.
  Spotify rotates PKCE refresh tokens: two installs sharing a client
  ID can invalidate each other's. [§92](docs/history/072-107.md#92)
- **One token refresh at a time per process:** `get_valid_token`
  refreshes under `auth_manager._TOKEN_LOCK` and re-reads the token
  inside it, or two refreshes spend the same rotating token and send
  the loser to the browser. [§146](docs/history/121-150.md#146)
- Field names: playlist track entries come from `entry["item"]`, gated by
  `item["type"] == "track"` ([early
  fixes](docs/history/early-fixes.md#spotify-field-name-and-endpoint-history-get_playlist_tracks));
  `get_current_user_playlists` reads `playlist["items"]["total"]`, never
  `["tracks"]["total"]` ([early
  fixes](docs/history/early-fixes.md#spotify-field-name-history-get_current_user_playlists)).
- **A playlist's tracks are stale when `tracks_snapshot_id`** (the
  snapshot its cached tracks came from; NULL = never loaded) **differs
  from `snapshot_id`.** Only `sync_playlist_tracks` sets it.
  `refresh_playlists()` re-syncs stale *loaded* playlists only, to
  spare the API budget. The parser drops Spotify local files (no id);
  a repeated track keeps its first listing.
  [§141](docs/history/121-150.md#141)
- `callback_server._LoopbackHTTPServer` overrides `server_bind()` to
  skip `HTTPServer`'s reverse-DNS `getfqdn()` between `bind()` and
  `listen()`; keep it. CI's callback timeouts stopped at the commit
  that added it (mechanism unexplained). [§136](docs/history/121-150.md#136)
- The token cache path comes from `platformdirs`, never the cwd (a
  double-clicked `.app`'s cwd can be unwritable).
  [§43](docs/history/032-046.md#43)

### SoulSeek / slskd

- **Quitting Seeker mid-download stops only the reconciliation.**
  slskd transfers in its own container; Seeker enqueues over REST and
  reconciles in `poll_downloads()`. Observed: a transfer finished with
  no Seeker running and was placed on the next poll.
  [§123](docs/history/121-150.md#123)
- Two credential pairs: `SLSKD_SLSK_USERNAME`/`PASSWORD` is the
  **Soulseek network** login, `SLSKD_USERNAME`/`PASSWORD` the **web
  UI** login. [§23](docs/history/001-024.md#23)
- `GET /api/v0/searches/{id}` returns `responses` only with
  `?includeResponses=true`; without it `isComplete` is real and
  `responses` silently empty. [§4](docs/history/001-024.md#4)
- **Rejections come in three shapes:** a locked file's `request_download`
  succeeds and the rejection surfaces later in `get_download_status` as
  `"Completed, Rejected"`; a peer gone offline is a synchronous 404 at
  enqueue; bad credentials or a kick shows only in `/api/v0/logs`
  (`ServerState` has no reason field), so `check_slskd_health` reads the
  logs with a `since:` filter. `is_recognized_rejection()` applies to
  every `download_requests.role`. [§13](docs/history/001-024.md#13)
- Exponential backoff plus a terminal `unavailable` after 8 attempts
  bounds any retry storm, whatever its cause (item 63).
  [§66](docs/history/047-071.md#66)
- **A finished download is never guessed and never lands on an
  existing file.** slskd writes `<remote parent>/<basename>`, or
  `<stem>_<UtcNow.Ticks><suffix>` on a clash; `_locate_completed_file`
  accepts only the request's exact byte size and refuses an ambiguous
  match. Placement and renames share one collision rule,
  `files.placement.resolve_collision`. [§138](docs/history/121-150.md#138)
- **A destination subfolder is validated, never rewritten:**
  `validate_destination_subfolder` takes `/`-joined sanitized names
  and rejects `..`, absolute paths and unsafe names; `set_destination`,
  resolution and the dialog's preview all use it. Every Seeker-built
  name goes through `clean_path_component` (never a leading dot); a
  peer's basename too, at placement, through `clean_peer_filename`
  (no control or bidi character, 255 bytes), while the lookup still
  matches slskd's raw name. [§143](docs/history/121-150.md#143)
- **One bring-up: `Application.start_slskd(..., persist=)`**, for the
  wizard (saves after its health poll), Settings (saves at once) and
  `restart_slskd()` (the live share and saved login, else
  `SlskdStartRefusedError`, never a guess). Sharing's recreate calls
  `docker_setup.bring_up_slskd` directly, reusing the saved key and
  login. The app runs only the per-user Compose copy
  (`compose_file_path()`), seeded once, never re-seeded, never the
  tracked template; a recreate keeps the live `/app` data dir.
  [§140](docs/history/121-150.md#140)
- **slskd down is an outage, never a per-request failure.**
  `poll_downloads` turns any `httpx.TransportError` into
  `SlskdUnreachableError` and aborts: no row changed or counted
  failed, no locked-retry budget spent (a retry re-raises before
  `_advance_locked_retry`). A new slskd call in the poll
  keeps `except httpx.TransportError` ahead of `except Exception`.
  The UI reads `SlskdStatus` (`PageContext.slskd_status`), written only by the
  backend poll and edge-triggered: one tray notice per outage, the
  first good poll clears them all. [§151](docs/history/151-180.md#151),
  [§152](docs/history/151-180.md#152)
- **The daily sweep (`soulseek/sweep.py`) is the only re-search.** It
  runs `search_and_request`, `download_playlist`'s own per-track step,
  over loaded playlists with a destination: ≤ 50 searches, least
  recently searched first (`tracks.last_searched_at`, stamped before
  every search). An outage, a pause or its `stop` event stops it and
  records no `last_sweep_at`. Every search skips a (peer, file) that
  went `failed` or `unavailable` for that track within 30 days, a
  cancel included (`FAILED_CANDIDATE_COOLDOWN`). The GUI runs it
  from `ui/sweep_scheduler.py`: after the first poll that reaches
  slskd, then hourly, one at a time (`busy_actions`), stopped on quit
  (the pool's destructor would wait out a ~40 min sweep).
  [§202](docs/history/181-210.md#202), [§203](docs/history/181-210.md#203)
- **slskd's cancel answers `204` whatever the transfer's state**
  (unknown, finished or live), so `cancel_download` reads the state
  afterwards: a `Succeeded` transfer is left to the poll. A cancel
  supersedes the other rows of its role (backups too), never cascades.
  [§204](docs/history/181-210.md#204), [§205](docs/history/181-210.md#205)
- **A settled file falls back; a role never crosses.** Up to three
  unlocked backups ride behind it as `shortlisted` settled rows (ranks
  2–4). A failed or locked settled row, refused at enqueue too,
  activates the next one at once (`_cascade(track_id, role)`; the
  locked row keeps its retry loop); the first settled file placed
  supersedes the rest. An upgrade cascades only to upgrades. A
  person's choice gets no backups. [§206](docs/history/181-210.md#206),
  [§207](docs/history/181-210.md#207)
- **Every slskd URL path segment is `quote(…, safe="")`d:** a
  username comes from a remote peer, and a raw `?`, `#` or `../`
  reaches another endpoint. [§146](docs/history/121-150.md#146)
- **The web UI binds to loopback only** (`127.0.0.1:5030`/`5031`);
  `50300` stays published on every interface for incoming peers;
  `SLSKD_REMOTE_CONFIGURATION=false`. A fresh install otherwise
  exposes slskd's vendor-default `slskd`/`slskd` login. A generated
  web login takes effect only on a fresh install (an existing one
  answers it `401`, observed), so `check_slskd_web_login()` checks it
  and Settings shows a credential only once confirmed.
  [§116](docs/history/108-120.md#116), [§117](docs/history/108-120.md#117)

### Qt and threading

UI-only rules (workers, window lifecycle, widgets, theme, tables)
live in [`src/seeker/ui/CLAUDE.md`](src/seeker/ui/CLAUDE.md). Claude
Code documents loading it when a session reads files in `ui/`
(UNVERIFIED here); read it before any UI change regardless.

- **Every real quit passes one seam: `QEvent.Type.Quit` delivered to
  the `QApplication` itself, before `aboutToQuit`** (the tray's
  `app.quit()` and macOS ⌘Q/Dock alike, observed). An `eventFilter`
  there decides synchronously: `False` lets it proceed, `True`
  cancels; `aboutToQuit` cleanup is too late for either. Never
  re-post `app.quit()` from the filter: the process exits without
  `aboutToQuit` (observed). Reference: `MainWindow.eventFilter`
  through `WindowLifecycleController`. [§124](docs/history/121-150.md#124)
- **`MainWindow.thread_pool` is passed to every `run_worker`, never
  `globalInstance()`.** Its destructor waits for in-flight runnables
  (observed in isolation): `quit()` returns at once but the process
  lives as long as the slowest task. `cleanup_before_quit` logs the
  pool's active/max threads and its elapsed time
  (`seeker.ui.window_lifecycle`) for item 125.
  [§125](docs/history/121-150.md#125)
- `get_config` on `TrackMatcher`/`DownloadService`/`MetadataService`
  is a callable, not a snapshot: a Settings change applies at once
  ([§28](docs/history/025-031.md#28)). Match thresholds resolve
  through `matching.resolve_thresholds` (`is None`, never `or`: 0 is
  valid). [§179](docs/history/151-180.md#179)

### Testing

- **UI tests build over `tests/fakes.py`** (`FakeApplication`, the
  `Fake*` services, `make_track`); no UI test module imports
  from another. Pages in `tests/pages/`, the shell in `tests/shell/`,
  subprocess scripts in `tests/repro/`. No `__init__.py`, so **a test
  file's basename is unique across directories** (else "import file
  mismatch"). [§161](docs/history/151-180.md#161)
- **Tests run the real theme:** `conftest.py` applies `apply_theme()`
  session-wide, so `grab()` assertions see the shipped style.
  [§103](docs/history/072-107.md#103)
- **Local runs use Cocoa; CI uses `QT_QPA_PLATFORM=offscreen`** (an
  800×800 screen that fits restored windows to it). Reproduce a
  CI-only failure with `QT_QPA_PLATFORM=offscreen uv run pytest
  <test>`. Offscreen never fires `colorSchemeChanged`, and
  `processEvents()` does not flush deferred deletes:
  `QCoreApplication.sendPostedEvents(None,
  QEvent.Type.DeferredDelete)`. A hidden `QWidgetItem`'s
  `setGeometry()` is a no-op; exclude it from `FlowLayout`
  assertions. [§167](docs/history/151-180.md#167),
  [§109](docs/history/108-120.md#109), [§79](docs/history/072-107.md#79)
- **A UI test waits for its flow's real end, never the fake's call
  record**, which the worker writes before the main thread's finish
  handler runs. A late handler raises `RuntimeError: … already
  deleted` at setup of the *next* test; look at the one before it.
  [§128](docs/history/121-150.md#128), [§148](docs/history/121-150.md#148)
- **On Cocoa a test window may or may not become the active one**
  (timing, or another pytest process holding activation); offscreen
  never does. Never wait on `hasFocus()`. An active window hands a
  table keyboard focus, and Fusion tints its current item: sample a
  row's ground from a `NoFocus` table. [§201](docs/history/181-210.md#201)
- **Skips:** `tests/test_stress_e2e.py` (`requires_stress_opt_in`) runs
  only with `SEEKER_RUN_STRESS_TEST=1`: it drives real Spotify, slskd and
  the X9 Pro for minutes and mutates the production DB. Run it
  deliberately after worker, timer or connection lifecycle changes. CI
  skips 29: that one plus 28 `@requires_x9_pro`.
  [§32](docs/history/032-046.md#32)

### Database

- `local_files`' analysis columns (`bpm`, `camelot_key`,
  `key_confidence`, `fingerprint*`) are excluded from
  `upsert()`'s `ON CONFLICT DO UPDATE`: a scan never wipes analysis.
  [§11](docs/history/001-024.md#11), [§39](docs/history/032-046.md#39)
- **`local_files.has_art` is NULL until a read succeeds, never a
  guessed 0.** The scan reads it and re-reads an unchanged file whose
  value is NULL; tagging and Fix missing cover art set it only when
  they embedded a picture. [§185](docs/history/181-210.md#185)
- `track_matches.confirmed_at` protects a human-confirmed match from a
  later `match_all()`, but only while its `local_file_id` is set.
  [§56](docs/history/047-071.md#56)
- **A match pointing at no file is unmatched.** Every `local_files`
  delete goes through `LocalFileRepository` (`delete_by_id(s)`,
  `delete_all_for_location`), which resets dependent matches in the
  same transaction; never raw SQL (`ON DELETE SET NULL` leaves a
  score and confirmation pointing nowhere). Removing a location also clears
  playlist destinations (no `ON DELETE` on that FK) and, via
  `Application`, the default. [§139](docs/history/121-150.md#139)
- **A Review Reject is permanent, per track**
  (`rejected_local_matches`, `rejected_soulseek_candidates`);
  `match_all` and `download_playlist` fall through to the next best.
  A `manual:` track is saved just before its first download request,
  and `_migrate` deletes any without one. [§144](docs/history/121-150.md#144)
- **A `download_requests` row is dismissed, never deleted:** a failed
  or unavailable row carries a readable `failure_reason` (pass
  `failure_reason=` on every such transition) until "Clear finished"
  sets `dismissed_at`. [§145](docs/history/121-150.md#145)
- **Library locations never nest:** adding one inside or around another is
  refused, by resolved path and on-disk identity (APFS is
  case-insensitive). `LibraryService.merge_location` merges a nested pair:
  rows pair only for the same physical file (`same_file`), analysis moves
  only into an empty group of equal size and mtime, then removal's own
  deletes run. [§171](docs/history/151-180.md#171),
  [§172](docs/history/151-180.md#172)
- Delete a local file: DB row, then disk. Rename: disk, then DB row.
  [§40](docs/history/032-046.md#40), [§67](docs/history/047-071.md#67)
- **No slow work inside a write transaction.**
  `Database.transaction()` opens a connection per call (thread-safe,
  [§22](docs/history/001-024.md#22)). Walks, tag reads and fuzzy
  passes run outside it; writes go in short batches that re-check what
  changed meanwhile. One `?` per row is capped at 32,766 parameters:
  chunk (`delete_by_ids`). [§142](docs/history/121-150.md#142)
- A fingerprint is read only through
  `get_all_for_location_with_fingerprints`; the default `local_files`
  getters leave those columns out (the polls read ~32 MB otherwise).
  [§165](docs/history/151-180.md#165)

### Packaging

- `sys.frozen` gates every bundled-resource lookup through
  `sys._MEIPASS`. One-folder mode, deliberately: numba's JIT cache
  persists only there (~1 s against ~18–21 s a run).
  [§30](docs/history/025-031.md#30)
- PyInstaller ad-hoc-signs with no `codesign_identity`: say "ad-hoc
  signed, not notarized", never "unsigned".
  [§36](docs/history/032-046.md#36)
- `packaging/build_dmg.py` writes the gitignored
  `_build_info_generated.py`; the tracked `_build_info.py` only
  imports it (fallback `"dev"`). Never write the tracked file.
  [§83](docs/history/072-107.md#83)
- A GUI launch gets launchd's minimal PATH:
  `docker_setup.ensure_full_path_environment()` merges `path_helper`
  and Homebrew/Docker Desktop fallbacks once, in
  `Application.__init__`. [§44](docs/history/032-046.md#44)
- `login_item.py` (`SMAppService`) is a no-op outside a frozen `.app`
  (no bundle identifier); its status is read live, never stored.
  Register/unregister on a packaged build is UNVERIFIED.
  [§131](docs/history/121-150.md#131)

### Accepted risks

Each accepted in round 12's audit, with Kris's decision and the full
reason under its finding in `docs/rounds/round-12/AUDIT.md`
([§200](docs/history/181-210.md#200)). Revisit any of them if Seeker
stops being a single-user desktop app.

- **Peer files reach native decoders unsandboxed** (S-03): libsndfile
  for analysis, ffmpeg for fingerprints. No content-against-extension
  check, by decision. `docs/packaging.md` → "Native libraries" tracks
  their open advisories; a fix is taken at the next release.
- **No size cap on slskd, Spotify or GitHub JSON bodies** (S-09);
  only album art streams with one.
- **slskd's secrets sit in its container's environment** (S-10):
  reading them needs the Docker socket, and `config.json` holds the
  same values at 0600.
- **`docker`, `ffmpeg`, `open` and libchromaprint resolve from
  Homebrew prefixes** (S-11): planting one needs same-user access.

## Open issues

Genuinely open only, checked against every CI run on record (187, to
2026-10-08) in [§192](docs/history/181-210.md#192).

- **Item 63, a locked-file retry storm** against production slskd
  (300+ retries of one row in ~18 min), cause unknown; locked rows, a
  zero-locked baseline and heavy load are ruled out. Lead: one `500`
  on `/api/v0/transfers/downloads/batches` with the storm's error
  text. The backoff bounds it. [§63](docs/history/047-071.md#63)
- **Item 70, a stress-test hang at production scale (~3,100
  files)**, cause unknown: 3/3 at scale after sync/scan/match, on
  Duplicates' Compute Fingerprints; 0/2 isolated; `faulthandler`
  silent (GIL starvation?). Not item 105's pytest stall.
  Lead (UNVERIFIED): until S22 the 2 s Dashboard and 20 s history
  polls read all ~32 MB of fingerprints and the Dashboard rebuilt
  every row each tick; S41's stress run tests it.
  [§70](docs/history/047-071.md#70), [§165](docs/history/151-180.md#165),
  [§166](docs/history/151-180.md#166)
- **Item 125, a "not responding" quit hang**, once (close to tray,
  quit from the tray), unreproduced. Candidate: the thread pool's
  destructor (above). Next try: quit while a scan, fingerprint or
  search worker is running. [§125](docs/history/121-150.md#125)
- **`test_library_track_list_refreshes_after_a_tag_run` timed out
  twice on CI** (`37932732255`; `37977966814`'s first attempt, a
  commit that touched no `ui/` code); it does not reproduce locally,
  offscreen included. Lead (UNVERIFIED): `LibraryPage.refresh_tracks()`
  keeps no recency guard, so an earlier load landing last repaints
  stale statuses. [§201](docs/history/181-210.md#201),
  [§207](docs/history/181-210.md#207)
- **The real DB still holds three nested locations** (`Music`⊂`X9
  Pro`, `Test`⊂`X9 Pro`, `Test`⊂`Music`; ~3,450 files double-indexed).
  With the X9 Pro mounted, Kris runs Settings → Library → Fix…,
  keeping `Music` (rehearsed: 43 matches kept, 0 lost).
  [§172](docs/history/151-180.md#172)

## Roadmap

Forward-looking only; everything shipped is in `docs/history/`.

- **Round 12 ends in the v0.1.0 release.** Kris's walkthrough fixes,
  a security re-audit, the daily sweep, X1/X2, then round 11's carried
  release rows. Plan: `docs/rounds/round-12/SESSION-PLAN.md` (with
  `BRIEF.md`); every document: `docs/README.md`.
- **Windows and Linux packaging: written, never run on real
  hardware**; no Linux installer format is scoped
  ([docs/packaging.md](docs/packaging.md)).
- **SoundCloud: deferred.** Its API needs a paid Artist Pro account
  and a confidential `client_secret`, which a `.dmg` cannot hold. If
  picked up: bring-your-own credentials, a Dashboard source toggle.

## Working agreements

Hard-won, all five stay.

1. **Two-tier docs.** This file holds present-tense standing facts
   short enough to read in full; `docs/history/` holds the
   investigations. Closing an item: a condensed note here (anything
   over ~8 lines goes to HISTORY only, linked) and, if real
   investigation happened, a HISTORY entry. Move, never delete: the
   detail lands in HISTORY before it leaves here. A new entry appends
   to the last `docs/history/` file with `<a name="N"></a>` above its
   `### N — title`, plus a line in `docs/history/README.md`; link it
   as `docs/history/<file>#N`. [§137](docs/history/121-150.md#137)
2. **Is a failure pre-existing? `git stash -u`, never a bare `git
   stash`**, which leaves untracked files (a gitignored
   `_build_info_generated.py`, say) in place.
3. **The failure count is a tracked number.** Quote the `pytest`
   summary line and name every failing test, every time. A changed
   count is a regression to diagnose, never a new baseline.
4. **A comment asserting platform or framework behaviour cites an
   observation or says UNVERIFIED.** Unmarked confident claims have
   burned this codebase twice (the `:last-child` selector; a macOS
   tray-click claim a user's report disproved).
5. **A `continue` or skip in a sweep test names what it excludes and
   why that cannot hide the bug the test exists for.** A skip derived
   from the state a bug corrupts is a blindfold, not a guard.

# seeker

Personal DJ music library management assistant. Syncs Spotify playlists to a
local SQLite cache (to minimize API calls against Spotify's rate/quota
limits), matches cached tracks against a scanned local library, and — for
whatever's missing — searches SoulSeek (via a self-hosted `slskd` daemon)
to identify and download the highest-quality available file for each
track, then tags matched files with Spotify's canonical metadata. Ships
both a CLI (`seeker`) and a desktop GUI (`seeker-ui`, PySide6) over the
same service layer — see docs/cli.md for the command reference and which
screen covers each command.

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

`tests/test_layering.py` sweeps every import in `src/seeker/` and fails
the build: `ui/`, `cli.py` and the entry points never import
`seeker.database`; `cli.py` never imports `seeker.ui`; only `ui/` and
`main_ui.py` import Qt; `models/` imports only `models/`.

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
- **Read discipline — never read a large file whole.** A
  `docs/history/*.md` file (~150 KB each) and
  `src/seeker/ui/main_window.py` each blow a session's budget alone if
  read in full — `grep -n` for the symbol/section and read that range
  instead. `uv run pytest -q`,
  report only the summary line plus named failures. `git diff --stat`
  by default. Don't re-read a file just edited — Edit/Write error on
  failure already.
- **Lint yes, format no — `ruff format` is deliberately not adopted.**
  This codebase's hand-written house style doesn't match `ruff
  format`'s output (confirmed via `ruff format --diff`: 4-space hang vs.
  this project's 8-space compound-header hang) — reformatting the whole
  tree would destroy `git blame` project-wide for no gain. `ruff check`
  is the enforced gate. [HISTORY §115](docs/history/108-120.md#115)
- **Hanging indent, verified by sampling, not assumed: 8 spaces for a
  compound statement header that wraps** (`def`/`if`/`while`/`for`/
  `with`/`class`/etc. — anything ending `:` with an indented body
  next), **4 spaces for everything else** (calls, `return`/`raise`/
  `assert`, assignments, comprehensions, imports) — the header's own
  body is already +4, so its continuation goes +8 to stay visually
  distinct. Trailing commas before a closing bracket; ~72-column prose
  wrapping. [HISTORY §115 §4.8.1](docs/history/108-120.md#115)
- **Line length: `ruff`'s enforced ceiling is 88, but ~72-79 stays the
  house habit** for hand-wrapped prose/comments — 79 was tried as the
  enforced ceiling and reverted (341 real violations, not the 106
  first estimated; 88 is a ceiling the codebase can actually sit
  near-zero on). [HISTORY §115](docs/history/108-120.md#115)
- **CI enforces what a local run may not.** `uv sync --locked` (a
  `pyproject.toml` dependency change ships with its `uv.lock`); branch
  coverage at or above 92 % (`--cov-fail-under`, set to the measured
  value minus one; 93.79 % without the X9 Pro tests, which CI skips);
  actions SHA-pinned with a version comment, bumped by Dependabot.
  A ruff preview rule is selected by its exact code: under
  `explicit-preview-rules` a prefix such as `E30` selects none.
  [HISTORY §149](docs/history/121-150.md#149),
  [§167](docs/history/151-180.md#167)
- **`assert` in `src/` narrows types/logic invariants; it never
  validates user input or an external response** — `S101` is ignored
  project-wide on this basis, every real finding read individually. A
  new `assert` validating something user/externally controlled needs a
  real `if`/`raise` instead. [HISTORY §115](docs/history/108-120.md#115)
- **Never run `ruff check --fix` with a narrowed `--select`, especially
  not `--select RUF100` alone** — `RUF100` flags a `noqa` as unused
  against only the rules *enabled in that invocation*; narrowing to
  `RUF100` makes every other rule's directive read as unused and
  `--fix` deletes them all. Confirmed by direct reproduction.
  [HISTORY §115](docs/history/108-120.md#115)
- **Credential files (config.json, the Spotify token cache) go through
  `seeker/files/atomic.py::write_text_locked()`** — the temp file is
  0600 from `os.open(O_EXCL)` (never chmod'd after the write), fsync'd,
  then renamed; never a bare `write_text()`.
  [HISTORY §116](docs/history/108-120.md#116), [§146](docs/history/121-150.md#146)
- **A tag write is saved by `audio/tags.py::save_tags()`, never
  mutagen's own `save()`.** Tags that fit the padding save in place;
  tags that outgrow it go through `files/atomic.py::rewrite_via_copy()`,
  because mutagen grows a tag by shifting the audio in place and a
  crash mid-shift corrupts MP3, FLAC and faststart M4A (measured).
  A FLAC key goes to both `INITIALKEY` and `KEY`.
  [HISTORY §167](docs/history/151-180.md#167)
- **`.env` is read only by an entry point.** `config.py`'s values are
  functions over `os.environ`, read at call time; `main()` in `main.py`
  and `main_ui.py` calls `config.load_env_file()` (working directory
  upward; never in a frozen app). Tests set environment variables,
  never patch `config`. [HISTORY §146](docs/history/121-150.md#146)
- **Not using the macOS Keychain for the Spotify token — deliberate,
  not an omission.** It would add a dependency, a platform-specific
  path, and a migration, to protect a file that's already 0600 in the
  user's own per-account home directory. Revisit only if this stops
  being a single-user local app. [HISTORY §116](docs/history/108-120.md#116)
- **`.env` was committed twice in this repo's history, assessed, not a
  live secret.** The Spotify client ID it held is PKCE-public by design
  (this app has no client secret at all); the one field that could have
  been secret was always the literal placeholder `your_…`. Decision: no
  history rewrite.
- **A comment earns its place by telling the next person something the
  code cannot.** One that tells them what *happened* belongs in
  `docs/history/` instead. Test is shelf life, not length: is this
  still true and load-bearing next year, or a record of a decision?
  Applied across S12/S13's comment triage — see [HISTORY
  §119](docs/history/108-120.md#119) for the largest single example, the whole
  Phase 6 extraction story moved out of the page modules' docstrings.
- **Services use `logging`, never `print` — `print` is the CLI's own
  output channel, nothing else's.** Each service module gets its own
  `logger = logging.getLogger(__name__)`; handlers are configured in
  exactly two places, `main.py` (a `StreamHandler`) and `main_ui.py` (a
  `RotatingFileHandler` under `platformdirs.user_log_dir("Seeker")`) —
  never in library code. Where a message is both user-facing and
  diagnostic, the service logs and returns a structured result, and
  `cli.py` does the printing from that result. `main_ui.py` also
  installs `ui/error_hooks.py`: `sys.excepthook`/`threading.excepthook`
  log at CRITICAL, Qt messages go to `seeker.qt`. No service calls
  `print` or `input`: interactive prompts (the one-by-one upgrade
  review included) live in `cli.py`, and diagnostics are
  `logger.debug`, switched on per logger at the entry points
  (`SEEKER_DEBUG_POLL=1` for the poll trace).
  [HISTORY §156](docs/history/151-180.md#156)
- **`ui/` never reads or writes `Application`'s private
  (underscore-prefixed) attributes** — go through a public method
  (`application.settings`, `application.update_settings(...)`, a
  service) instead, so `Application` can invalidate whatever depends on
  the change. `test_no_private_application_attribute_access_in_ui`
  (`tests/test_ui_source_sweeps.py`) is an AST sweep enforcing this — it fails
  the build, not just the convention.
- **Page widgets live in `ui/pages/`, one `QWidget` subclass per page,
  never a `MainWindow` mixin.** Each takes a `PageContext`
  (`ui/pages/context.py` — application, thread pool, busy-action
  registry, `navigate`, `run_busy_worker`, and the rest) and never
  reaches back into `MainWindow`; `MainWindow` itself is the shell
  (nav, timers, tray). [HISTORY §119](docs/history/108-120.md#119)
  Cross-page selection state goes through
  `PageContext.playlist_selection` (`ui/playlist_selection.py`),
  never through one page reading another's attributes; Dashboard and
  Library both write it, the playlist and the track ids alike (both
  track tables write `track_ids`; Library's shows it, signals
  blocked). [HISTORY §133](docs/history/121-150.md#133),
  [§185](docs/history/181-210.md#185)
  A page owns the actions its own buttons start (Dashboard's Sync,
  Scan, Match, Download, Load tracks), and the shell calls only a
  page's **public** methods (`poll_*`, `refresh_*`, `on_shown`,
  `focus_track`). `SLF001` is enforced over `src/` (tests exempt): a
  new private reach across objects fails `ruff check`. The one `noqa`
  is PyInstaller's `sys._MEIPASS`.
  [HISTORY §162](docs/history/151-180.md#162)
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
  read) was exactly that mistake. [HISTORY §120](docs/history/108-120.md#120)
  An action reports through the `FeedbackTarget` (`ui/notice.py`) of
  the page it was **started from** — a panel reachable from another
  page takes one from its caller (TaggingPanel's Tag from a Dashboard
  row) — and a timer-driven `run_worker` never passes `status_label`.
  [HISTORY §150](docs/history/121-150.md#150)
- **Text a user reads about a failure comes from
  `error_text.describe_error`.** Workers emit it and the CLI prints
  it; a new external failure kind (a new HTTP peer, a new library's
  error) gets a branch there, never ad hoc text at a call site. Your
  own exception's message is kept as written, so write it as a
  sentence. [HISTORY §150](docs/history/121-150.md#150)
- **Every public error is a `SeekerError`** (`seeker/errors.py`), which
  `cli.run` catches as one. An error raised by more than one module
  lives in `errors.py`, defined once; any other stays beside its module
  and subclasses `SeekerError`. `tests/test_errors.py` sweeps `src/`
  and fails the build. [HISTORY §153](docs/history/151-180.md#153)
- **Download states are `DownloadStatus`/`DownloadRole`**
  (`models/download_request.py`, `StrEnum`, equal to the stored
  strings). Group them only through its named sets (`IN_FLIGHT`,
  `UNRESOLVED`, `STAMPS_COMPLETED_AT`, …); a new grouping is a new
  named set there, never a literal set at the call site. SQL takes the
  values as parameters. [HISTORY §153](docs/history/151-180.md#153)
- **A service result is a dataclass, never a string-keyed dict.**
  One the CLI or `ui/` reads lives in `models/` (`download_result`,
  `library_result`, `tag_result`, `fingerprint_result`); counts that
  must agree with a list are derived from it (`failed` is
  `len(failures)`). Detail rows stay `{track_id, reason, message}`
  dicts, as in `RenameResult`. [HISTORY §154](docs/history/151-180.md#154),
  [§155](docs/history/151-180.md#155)
- **No widget in `ui/` guesses whether its text is HTML.** Labels are
  `PlainLabel`, or `RichLabel` for Seeker's own markup with any data
  inside `html.escape`d; message boxes go through `plain_text.question`
  /`information`/`warning` or set `setTextFormat` by hand; a tooltip
  built from data goes through `plain_tooltip()`. Peer filenames,
  usernames and slskd text otherwise render as markup. Four `ast`
  sweeps in `tests/test_plain_text.py` fail the build. The CLI passes
  peer strings through `cli.printable()`.
  [HISTORY §148](docs/history/121-150.md#148)

## Commands

```
uv sync              # install deps
uv run seeker         # run the CLI
uv run seeker-ui       # run the GUI (PySide6) — onboarding wizard on first launch
uv run pytest         # run tests
uv run mypy --strict src/  # type check — must stay clean
uv run python tools/screenshots.py  # every screen, both themes -> tools/.screens/
```

## Standing facts and gotchas

Present-tense rules that shape the next piece of code, grouped by area.
Each links to the HISTORY entry where the full investigation lives;
`docs/history/README.md` resolves any `HISTORY §N` to its file.

### Spotify / OAuth

- `SpotifyClient` takes a `TokenSource` (`str | Callable[[], str]`), not a
  bare string. On a 401 it calls an optional `force_refresh` callable and
  retries **exactly once**; a second 401 raises
  `SpotifyAuthenticationError` rather than a raw `httpx` error.
  [HISTORY §92](docs/history/072-107.md#92)
- Spotify rotates PKCE refresh tokens — two installs sharing one
  account/client ID can invalidate each other's stored refresh token.
  [HISTORY §92](docs/history/072-107.md#92)
- **One token refresh at a time, per process.** `get_valid_token`
  refreshes under `auth_manager._TOKEN_LOCK` and re-reads the token
  inside it; two concurrent refreshes would spend the same rotating
  refresh token and send the loser to the browser.
  [HISTORY §146](docs/history/121-150.md#146)
- Playlist track entries come from `entry["item"]`, gated by
  `item["type"] == "track"` (Feb 2026 API migration repurposed the old
  `"track"` key as a type flag).
  [HISTORY](docs/history/early-fixes.md#spotify-field-name-and-endpoint-history-get_playlist_tracks)
- **A playlist's tracks are stale when `tracks_snapshot_id` (the
  snapshot its cached tracks came from; NULL = never loaded) differs
  from `snapshot_id`.** Only `sync_playlist_tracks` sets it; the list
  refresh never does. `refresh_playlists()` re-syncs stale *loaded*
  playlists only — never-loaded ones stay unloaded to protect the API
  budget. The parser drops Spotify local files (no id) and the sync
  keeps a repeated track's first listing.
  [HISTORY §141](docs/history/121-150.md#141)
- `get_current_user_playlists` reads `playlist["items"]["total"]`, never
  `["tracks"]["total"]`.
  [HISTORY](docs/history/early-fixes.md#spotify-field-name-history-get_current_user_playlists)
- `callback_server._LoopbackHTTPServer` overrides `server_bind()` to
  skip `HTTPServer`'s reverse-DNS `socket.getfqdn()` between `bind()`
  and `listen()` — keep it, never go back to a plain `HTTPServer`. The
  CI-only `test_callback_server.py` timeouts stopped at the commit that
  added it (all 39 CI runs since pass; mechanism still unexplained).
  [HISTORY §136](docs/history/121-150.md#136)
- The token cache path is resolved via `platformdirs`, not
  CWD-relative — a double-clicked `.app`'s CWD can be unwritable.
  [HISTORY §43](docs/history/032-046.md#43)

### SoulSeek / slskd

- **Quitting Seeker mid-download does not stop the transfer — only the
  reconciliation.** slskd runs the transfer in its own Docker
  container, independent of Seeker's process; Seeker only enqueues via
  slskd's REST API and later reconciles via
  `DownloadService.poll_downloads()`. Confirmed live (round 9 §2.1,
  not just architecture): a real download kept transferring to
  completion with zero `seeker` process running at all, then was
  correctly picked up and moved into the library on the next
  `poll_downloads()` call. Nothing is lost on quit; the finished file
  just waits in slskd's own directory until Seeker is next opened.
  [HISTORY §123](docs/history/121-150.md#123)
- Two distinct credential pairs exist and are easy to confuse:
  `SLSKD_SLSK_USERNAME`/`PASSWORD` is the **Soulseek network** login;
  `SLSKD_USERNAME`/`PASSWORD` is the **web UI** login. Confirmed live
  against a real container. [HISTORY §23](docs/history/001-024.md#23)
- `GET /api/v0/searches/{id}` only returns populated `responses` with
  `?includeResponses=true` — without it you get a real `isComplete` but
  a silently empty `responses` array. [HISTORY §4](docs/history/001-024.md#4)
- A locked file's `request_download` succeeds immediately; the
  rejection only surfaces later via `get_download_status` as
  `"Completed, Rejected"`. Three distinct rejection shapes exist total
  (locked-file, a synchronous 404 at enqueue for a peer gone offline,
  and a slow log-only bad-credentials/kicked distinction — `/api/v0/
  application`'s `ServerState` carries no error/reason field at all, so
  `check_slskd_health` reads `/api/v0/logs` with a `since:` filter).
  [HISTORY §13](docs/history/001-024.md#13)
- **A finished download is never guessed and never lands on an
  existing file.** slskd writes `<remote parent>/<basename>`, or
  `<stem>_<UtcNow.Ticks><suffix>` on a clash (its `FileService.MoveFile`);
  `_locate_completed_file` accepts only the request's exact byte size
  and refuses an ambiguous match. Placement goes through
  `files.placement.resolve_collision` — the one collision rule, shared
  with renames. [HISTORY §138](docs/history/121-150.md#138)
- **A destination subfolder is validated, never rewritten.**
  `validate_destination_subfolder` (`destination_resolution.py`)
  accepts folder names joined by `/` (nested is real), each already
  sanitized; it rejects `..`, absolute paths and unsafe names.
  `set_destination` and resolution both call it, and the dialog
  previews its result. Every Seeker-built file or folder name goes
  through `clean_path_component`, which never leaves a leading dot.
  [HISTORY §143](docs/history/121-150.md#143)
- **One slskd bring-up: `Application.start_slskd(..., persist=)`.**
  The wizard (saves after its health poll), Settings (saves at
  once) and `restart_slskd()` (Start slskd after an outage: the live
  share and saved login, else `SlskdStartRefusedError`, never a
  guess) all go through it. Sharing's
  recreate calls `docker_setup.bring_up_slskd` directly, since it
  reuses the saved key/login and the live `/app` dir. The app only
  ever runs the per-user Compose copy (`compose_file_path()`, dev and
  frozen alike), never the tracked template, and a recreate keeps a
  live container's `/app` data dir. The per-user copy is seeded once
  and never re-seeded. [HISTORY §140](docs/history/121-150.md#140)
- **slskd being down is an outage, never a per-request failure.**
  `poll_downloads` turns any `httpx.TransportError` into
  `SlskdUnreachableError` and aborts: nothing counted as failed, no
  row changed, no locked-retry budget spent (a retry re-raises the
  transport error before `_advance_locked_retry`). A new slskd call
  inside the poll keeps that order: `except httpx.TransportError`
  ahead of `except Exception`. The UI reads it from `SlskdStatus`
  (`PageContext.slskd_status`), written only by the backend poll and
  edge-triggered: the tray notifies once per outage, the first good
  poll clears every notice. [HISTORY §151](docs/history/151-180.md#151),
  [§152](docs/history/151-180.md#152)
- **Every slskd URL path segment is `quote(…, safe="")`d** — a
  username is chosen by a remote peer, and a raw `?`, `#` or `../`
  reaches a different endpoint. [HISTORY §146](docs/history/121-150.md#146)
- `RECOGNIZED_REJECTION_PATTERNS`/`is_recognized_rejection()` apply
  unconditionally to any `download_requests.role`, not just
  `role='upgrade'`. [HISTORY §13](docs/history/001-024.md#13)
- Exponential backoff plus a terminal `unavailable` status after 8
  attempts structurally bounds any future retry storm's rate,
  regardless of cause — added after a real, still-unexplained
  production storm (see Open issues, item 63).
  [HISTORY §66](docs/history/047-071.md#66)
- A generated slskd web UI login only takes effect on a genuinely fresh
  install — slskd silently refuses to let `SLSKD_USERNAME`/`PASSWORD`
  override an already-customised login. Confirmed live both ways: a
  fresh throwaway container accepts it (real `200` from
  `POST /api/v0/session`); a container with a pre-existing login
  returns a real `401` for the generated one.
  `docker_setup.check_slskd_web_login()` checks this directly; Settings
  only displays a credential once confirmed active.
  [HISTORY §116](docs/history/108-120.md#116),
  [§117](docs/history/108-120.md#117)
- The slskd web UI is bound to loopback only
  (`127.0.0.1:5030:5030`/`5031:5031`); `50300` must stay published on
  every interface for real incoming Soulseek peer connections.
  `SLSKD_REMOTE_CONFIGURATION=false`. [HISTORY §116](docs/history/108-120.md#116)
- §6.1's original HIGH severity assumed a vendor-default `slskd`/`slskd`
  web UI login; Kris's own machine had already changed it, so his real
  exposure was lower than assessed — but the fix stays correct and
  necessary, since a fresh install by anyone else lands on that
  default. [HISTORY §116](docs/history/108-120.md#116)

### Qt, threading, and UI

- **The single seam every real quit route passes through, confirmed
  live: `QEvent.Type.Quit` delivered to the `QApplication` instance
  itself, before `aboutToQuit`.** Both `tray.py`'s `_on_tray_quit()`
  (`app.quit()`) and the native macOS ⌘Q/Dock "Quit Seeker" menu item
  deliver this same event to the app object — an installed
  `QObject.eventFilter` catching it can decide synchronously whether
  to let that exact event proceed (return `False`) or cancel the quit
  outright (return `True`); `aboutToQuit`-connected cleanup
  (`cleanup_before_quit`) fires too late for either. Do NOT re-post a
  fresh `app.quit()` from inside the filter to "confirm and retry" —
  confirmed live this exits the process silently without `aboutToQuit`
  ever running, skipping all cleanup. `MainWindow.eventFilter`
  (`ui/main_window.py`, deciding through `WindowLifecycleController`)
  is the reference implementation — reusable for any future "confirm
  before a real quit" need.
  [HISTORY §124](docs/history/121-150.md#124)
- PySide6 reports an exception raised in a slot through
  `sys.excepthook` (observed live). pytest-qt swaps in its own hook
  per test, so a test of Seeker's hook needs
  `@pytest.mark.qt_no_exception_capture`. [HISTORY
  §150](docs/history/121-150.md#150)
- `ui/workers.py`'s `Worker`: one shared, permanently-connected
  dispatcher QObject, never a fresh one per task —
  connect/disconnect cycling through Qt's mutex pool per call caused a
  real deadlock under heavy concurrent use. `setAutoDelete(False)` plus
  a `task_id`-only signal (never `self`) plus a deferred native delete
  are all independently required. [HISTORY §39](docs/history/032-046.md#39)
- A `Worker` must be kept alive via a strong reference
  (`_active_workers: set[Worker]`) until its own finished/error signal
  fires — `QThreadPool.start()` returning early lets GC collect it
  mid-flight. [HISTORY §22](docs/history/001-024.md#22)
- `Qt.ConnectionType.SingleShotConnection` is required on
  `run_worker`'s cross-thread connections — the reference cycle
  otherwise formed is invisible to Python's GC (the Qt/shiboken side
  isn't visible to the tracer), and a manual `disconnect()` from inside
  its own handler mid-emission segfaults. [HISTORY §32](docs/history/032-046.md#32)
- **The window lifecycle is `WindowLifecycleController`'s alone**
  (`ui/window_lifecycle.py`): geometry, `_hidden_to_tray`,
  `_hide_request_id`, `_reopen_filled`, the Dock-icon calls, the quit
  confirmation and `cleanup_before_quit`. `MainWindow` keeps only what
  a QObject must own (`closeEvent`, `showEvent`, the QApplication
  `eventFilter`, the `applicationStateChanged` slot) and delegates;
  the tray reopens through `MainWindow.reopen()`. A test patching the
  Dock icon patches `window_lifecycle._set_dock_icon_visible`.
  [HISTORY §163](docs/history/151-180.md#163)
- `WA_DeleteOnClose` on a top-level window must be cleared the moment a
  real tray icon exists, or the first close after that deletes the
  window's C++ object and "reopen from tray" breaks permanently.
  [HISTORY §114](docs/history/108-120.md#114)
- `WA_DeleteOnClose`'s value is decided in exactly one place —
  `TrayController._build_tray_icon()` (`ui/tray.py`), both branches
  explicitly (`True` when no tray is available, `False` the moment one
  is built). `MainWindow.__init__` does not set it at all. A future
  change to this invariant belongs in that one method, not split
  between it and `__init__` again. [HISTORY §125](docs/history/121-150.md#125)
- A per-window `QThreadPool` (`MainWindow.thread_pool` — every real
  `run_worker` call takes it as an explicit argument, never
  `QThreadPool.globalInstance()`) blocks its own destructor on any
  in-flight runnable, confirmed live via an isolated probe: `quit()`
  itself always returns instantly, but the enclosing process stays
  alive exactly as long as the slowest running task takes once nothing
  else holds a reference to the pool. `cleanup_before_quit`
  (`WindowLifecycleController`, logger `seeker.ui.window_lifecycle`) logs this
  pool's active/max thread count at entry and its own elapsed time at
  exit, specifically to localize a future recurrence of the
  unreproduced "not responding" quit hang. [HISTORY
  §125](docs/history/121-150.md#125)
- `QHeaderView::section:horizontal:last-child` is invalid Qt QSS (valid
  CSS, not Qt's dialect) and silently poisons the **entire**
  `::section` rule — use `:last` alone.
  [HISTORY §103](docs/history/072-107.md#103)
- **A colour is read from `theme.active_palette()` at paint or render
  time, never cached** — the palette `apply_theme` last applied. There
  are no module-level colour names (`theme.ACCENT` is gone); prefer a
  QSS rule over reading a token at all. [HISTORY
  §181](docs/history/181-210.md#181)
- **A bundled line icon is a `QIcon` over `ui/icons.py`'s
  `TokenIconEngine`**, which swaps `currentColor` for a palette token
  on every draw (per mode and state, `IconColours`). The vendored
  Lucide files in `packaging/icons/lucide/` are never edited; a QSS
  `image:` still needs one file per palette (`_palette_icon`).
  [HISTORY §182](docs/history/181-210.md#182)
- **Only a real surface paints a background.** The generic `QWidget`
  rule sets text colour only; `QMainWindow`/`QDialog` paint `BG_APP`,
  cards and tables their own; `QLabel`/`QCheckBox`/`QRadioButton` are
  transparent. A new surface gets its own selector, never a
  background on a generic type, which bands every nested widget.
  Review a UI change in `tools/screenshots.py`'s images.
  [HISTORY §173](docs/history/151-180.md#173)
- **A button takes its size hint.** It goes in `theme.action_row()`
  (or a row ending in `addStretch()`), never alone in a vertical or
  form layout, where it stretches to the full width; a tall form
  scrolls rather than squeezing rows (Settings' tabs).
  `tests/shell/test_button_sizing.py` walks every harness screen and
  fails the build. [HISTORY §174](docs/history/151-180.md#174)
- **Focus is visible, and only keyboard focus.** `apply_theme` sets
  Fusion through `_SeekerStyle` (buttons are `TabFocus`: a click never
  focuses one), and every focusable control has a `:focus` rule. Test
  a focused look by painting through `style().drawControl()` with
  `State_HasFocus` on the option, never by real focus. A per-row
  button gets `cell_widget(..., row_label=)` and an icon-only control
  `setAccessibleName`; `tests/shell/test_keyboard_access.py` fails
  the build.
  [HISTORY §175](docs/history/151-180.md#175)
- **Every table declares a `theme.ColumnLayout`** whose stretch
  column is the one its rows are about (Track, Filename, Path).
  `fit_widths` keeps that column's content width (180 px floor, 40 %
  cap) and shrinks the widest other text columns first, never below
  a header; a viewport filter refits on resize. Cells are one line:
  `ElidedTextDelegate` shows the full text on hover only when elided,
  and `ColumnLayout.paths` columns elide in the middle. A list of
  names uses `elide_list_items`. `tests/shell/test_table_columns.py`
  walks every harness screen at 960×640.
  [HISTORY §176](docs/history/151-180.md#176)
- **An empty table shows `ui/empty_state.EmptyState`** (a glyph, one
  sentence, an optional action) inside its viewport, shown by the row
  count itself; never a spanned placeholder row or a status-label
  message. A page only changes its sentence (`set_text`) as the reason
  changes. A short marker on a row ("Upgrade") is a `BADGE_ROLE`
  pill on the primary cell, not a column of its own; quieter detail
  beside a cell's text (a candidate's quality and peer) is
  `SECONDARY_ROLE`, not a second line. Rows that come in groups band
  every other group with `BAND_ROLE` (the palette's AlternateBase,
  read at paint time) and span the group's own cells, never a
  group-number column. A state in a cell is its
  `status_lamp` lamp as the item's icon beside the label, never link
  styling; where the label must read in full, the view sets
  `set_secondary_min_share(view, 0.0)`. Determinate progress is
  `theme.style_meter` (amber segments, no label: the percentage is
  cell text); an in-table bar with no amount yet is
  `theme.set_busy_meter` (the same amber), and a bar goes back to busy
  only through `theme.set_indeterminate`, which drops the `::chunk`
  sheet. [HISTORY §177](docs/history/151-180.md#177),
  [§178](docs/history/151-180.md#178), [§184](docs/history/181-210.md#184)
- **A titled section is `theme.section_card`** (its title in the
  panel lettering, one muted sentence, then the controls), never a
  `QGroupBox`, whose title draws in the system font; none is left in
  `src/`. [HISTORY §189](docs/history/181-210.md#189)
- **Background reading goes behind a `ui/disclosure.Disclosure`,
  after the page's working content** (Sharing's "How sharing works"),
  closed by default, its state a `SeekerConfig` field written on the
  user's click only. Open, its body scrolls inside a share of the
  height rather than squeezing the tables.
  [HISTORY §187](docs/history/181-210.md#187)
- **Prose wraps at 80 characters through `theme.reading_column`**
  (Help, Support), which caps the whole column. Never cap one wrapped
  label inside a wider layout row: the row asks its height at the
  row's width and clips its last lines (`set_reading_measure` is only
  for a label that is a scroll area's whole content). A link takes
  `QPalette.Link`, which `build_qpalette` sets to `ACCENT`.
  [HISTORY §188](docs/history/181-210.md#188)
- Any `setStyleSheet()` call must carry a selector — a selector-less
  rule parses as a universal `*` rule and silently strips styling off
  every descendant widget's box model.
  [HISTORY §114](docs/history/108-120.md#114)
- `setSpan()` must be called **before** `setCellWidget()` on the
  span-owning cell, and no widget of any kind belongs on the cells it
  covers — a "blank placeholder" widget resolves to the same geometry
  as the real span-owning widget and paints over it.
  [HISTORY §77](docs/history/072-107.md#77)
- A bare `QProgressBar`/`QPushButton` handed straight to
  `setCellWidget` renders top-clamped or stretched to fill the whole
  cell — always wrap it in a centering container widget. A structural
  test walks every table for this.
  [HISTORY §104](docs/history/072-107.md#104)
- `QTableWidget::item { padding }` corrupts a `QPushButton` living
  inside a cell widget (safe on `QListWidget`). A plain `QWidget`
  subclass needs `WA_StyledBackground` to paint its own stylesheet
  background/border at all. [HISTORY §47](docs/history/047-071.md#47)
- Tests must exercise the real theme stack —
  `tests/conftest.py` calls `theme.apply_theme()` in a session-scoped
  autouse fixture — otherwise a `window.grab()` pixel/geometry
  assertion runs against Qt's default style, not the shipped
  Fusion+QSS+dark-palette one. [HISTORY §103](docs/history/072-107.md#103)
- Under the offscreen QPA test platform: `colorSchemeChanged` never
  actually fires, and a plain `QApplication.processEvents()` does
  **not** flush Qt's deferred deletion — use
  `QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`.
  [HISTORY §109](docs/history/108-120.md#109),
  [§116](docs/history/108-120.md#116)
- A `.hide()`'n `QWidgetItem`'s `setGeometry()` is a real no-op —
  exclude hidden items from any `FlowLayout` geometry assertion.
  [HISTORY §79](docs/history/072-107.md#79)
- `get_config` on `TrackMatcher`/`DownloadService`/`MetadataService` is
  a **callable**, not a snapshot — a Settings change takes effect
  immediately, no restart. [HISTORY §28](docs/history/025-031.md#28)
  The match thresholds resolve through `matching.resolve_thresholds`
  (`is None`, never `or`: 0 is a value Settings accepts).
  [HISTORY §179](docs/history/151-180.md#179)
- **One navigation model: the sidebar.** Every registered page has a
  sidebar button, and no page gets its own "← Back" (Settings' was
  removed). Settings' tabs are `SETTINGS_TAB_*` (General, Library,
  Connections, Matching); select one by constant, never by index.
  [HISTORY §179](docs/history/151-180.md#179)
- A `setCellWidget`-only column (no `QTableWidgetItem`) sorts as a
  silent no-op under click-to-sort — give it a `SortKeyItem`
  (`ui/table_sort.py`) if it has real data to order by (see
  Progress's fraction-complete key), never a bare display string.
  `theme.configure_columns` already vetoes sorting entirely on
  whichever column `ColumnLayout.actions` names, for every table, so
  a new Actions column needs no per-page handling at all.
  [HISTORY §122](docs/history/121-150.md#122)
- **Never synchronously rebuild a widget from a handler that can run
  inside that widget's own selection/data-changed emission** —
  directly or via a shared signal like `PlaylistSelection.changed`.
  Reproduced as a real SIGSEGV (Dashboard's `track_table` cleared
  from inside its own `itemSelectionChanged`); defer with
  `QTimer.singleShot(0, ...)`, as `_on_shared_selection_changed`
  does. [HISTORY §134](docs/history/121-150.md#134)
- **The Dashboard's track table rebuilds only when what its rows were
  built from changes** (`_RenderedRows`: the visible statuses plus
  the active palette, which the lamps bake in); a progress-only change
  updates bars, percentages and sort keys in place. Anything new a row bakes in at build time (a color, a
  setting) must join that key, or a change to it never reaches the
  table. `QTableWidget.setItem` measured ~2.4 ms a call at 500 rows —
  mutate an existing item on a hot path. [HISTORY
  §166](docs/history/151-180.md#166)
- **A button whose enabled state a render decides is never
  `run_worker`'s `button=`.** Its finish handler re-enables the button
  before `on_finished`, over any render that already ran; disable it
  on click and let the render set it (Downloads' Clear finished,
  reproduced deterministically). [HISTORY §145](docs/history/121-150.md#145)
- A page inside `MainWindow`'s `QStackedWidget` has no real geometry
  until first navigated to — restore saved splitter/size state from
  its first real `showEvent`, never its constructor
  (`ReviewPage._restore_splitter_state`). [HISTORY
  §132](docs/history/121-150.md#132)

### Testing

- **UI tests build over `tests/fakes.py`** (`FakeApplication`, the
  `Fake*` services, shared builders such as `make_track`); no UI test
  module imports from another. Page tests live in
  `tests/pages/`, `MainWindow`'s own in `tests/shell/`, and the six
  subprocess-only scripts in `tests/repro/`. No test directory has an
  `__init__.py`, so **a test file's basename must be unique across
  all of them** — a duplicate fails collection with "import file
  mismatch" (reproduced). [HISTORY §161](docs/history/151-180.md#161)
- **Local pytest runs on Cocoa; CI runs `QT_QPA_PLATFORM=offscreen`,
  whose screen is 800×800.** A UI test that passes locally and fails
  on CI is reproduced first with `QT_QPA_PLATFORM=offscreen uv run
  pytest <test>`; a window bigger than 800×800 is fitted to the
  screen when Qt restores its geometry.
  [HISTORY §167](docs/history/151-180.md#167)
- **Why one test always skips, and why that is correct:**
  `tests/test_stress_e2e.py` is gated by `requires_stress_opt_in` on
  `SEEKER_RUN_STRESS_TEST != "1"` — it drives the real Spotify/slskd/
  X9 Pro pipeline for real wall-clock minutes and mutates the real
  production database, so it must never run just because the
  infrastructure happens to be connected (see the file's own
  docstring). Run it deliberately via `SEEKER_RUN_STRESS_TEST=1 uv run
  pytest tests/test_stress_e2e.py` after any change to worker/timer/
  connection lifecycle code. [HISTORY §32](docs/history/032-046.md#32)

### Database and migrations

- `local_files`' analysis/fingerprint columns (`bpm`, `camelot_key`,
  `key_confidence`, `fingerprint*`) are excluded from `upsert()`'s
  `ON CONFLICT DO UPDATE` — a routine scan must never wipe prior
  analysis. [HISTORY §11](docs/history/001-024.md#11),
  [§39](docs/history/032-046.md#39)
- **`local_files.has_art` is NULL until a read succeeds, never a
  guessed 0.** The scanner reads it (a second, non-easy mutagen open)
  and re-reads an unchanged file whose value is NULL, counting it
  unchanged; tagging and Fix missing cover art set it only when they
  embedded a picture. [HISTORY §185](docs/history/181-210.md#185)
- `track_matches.confirmed_at` protects a human-confirmed match from
  being silently demoted by a later `match_all()` re-run, which
  otherwise has no provenance concept at all — but only while its
  `local_file_id` is set.
  [HISTORY §56](docs/history/047-071.md#56)
- **A match pointing at no file is unmatched, everywhere.** Every
  `local_files` delete goes through `LocalFileRepository`
  (`delete_by_id`/`delete_by_ids`/`delete_all_for_location`), which
  resets the dependent matches in the same transaction — never delete
  `local_files` rows with raw SQL, or the `ON DELETE SET NULL`
  cascade leaves a method/score/confirmation on a row pointing
  nowhere. Removing a location also clears playlist destinations
  (no `ON DELETE` on that FK) and, via `Application`, the default.
  [HISTORY §139](docs/history/121-150.md#139)
- **A Reject on the Review page is permanent, per track.** It writes
  `rejected_local_matches` or `rejected_soulseek_candidates`;
  `match_all` and `download_playlist` skip those pairs and fall
  through to the next best. Only a download request makes a
  `manual:` track real: it is saved just before its first request,
  and `_migrate` deletes any with no request.
  [HISTORY §144](docs/history/121-150.md#144)
- **A `download_requests` row is dismissed, never deleted.** A failed
  or unavailable row carries a readable `failure_reason` and stays on
  the Downloads page until "Clear finished" sets `dismissed_at`;
  deleting one would make a completed manual track an orphan for
  `_migrate`. Any new failed/unavailable transition passes
  `failure_reason=`. [HISTORY §145](docs/history/121-150.md#145)
- **Library locations never nest.** Adding one inside or around
  another is refused, by resolved path and on-disk identity (APFS is
  case-insensitive). A nested pair already registered is merged by
  `LibraryService.merge_location`: a merged row pairs only with the
  kept row for the same physical file (`same_file`), analysis moves
  only into an empty group with equal size and mtime, and the merged
  location then goes through removal's own deletes.
  [HISTORY §171](docs/history/151-180.md#171),
  [§172](docs/history/151-180.md#172)
- Deleting a local file: DB row first, then the file on disk. Renaming
  one: the opposite order, file then DB row.
  [HISTORY §40](docs/history/032-046.md#40), [§67](docs/history/047-071.md#67)
- `Database.transaction()` opens a new connection per call — safe to
  use across threads. [HISTORY §22](docs/history/001-024.md#22)
- **No slow work inside a write transaction.** Walks, tag reads and
  fuzzy passes run outside `Database.transaction()`; writes go in short
  batches, and the write re-checks what may have changed meanwhile
  (`match_all` keeps a confirmation made while it computed). Measured:
  a first scan holding one transaction made concurrent writers fail
  with "database is locked". Never bind one `?` per row either: SQLite
  caps a statement at 32,766 parameters, so chunk (`delete_by_ids`).
  [HISTORY §142](docs/history/121-150.md#142)

### Packaging

- `sys.frozen` gates every bundled-resource path lookup via
  `sys._MEIPASS` (compose file, icons, everything) — the same pattern
  any future bundled-resource lookup should follow.
  [HISTORY §30](docs/history/025-031.md#30)
- One-folder PyInstaller mode over one-file, deliberately — numba's
  JIT cache only persists across runs in one-folder mode (~1s vs.
  ~18-21s every run in one-file). [HISTORY §30](docs/history/025-031.md#30)
- PyInstaller's `BUNDLE()`/`EXE()` already ad-hoc-sign by default with
  no `codesign_identity` given — call it "ad-hoc signed, not
  notarized," never "unsigned." [HISTORY §36](docs/history/032-046.md#36)
- Build identity: `packaging/build_dmg.py` writes a gitignored
  `src/seeker/_build_info_generated.py`; the tracked `_build_info.py`
  only `try/except ImportError`s it, falling back to `"dev"` — never
  write the tracked file directly (doing so once permanently dirtied
  the tree on every real build). [HISTORY §83](docs/history/072-107.md#83)
- GUI launches get launchd's bare minimal PATH —
  `docker_setup.ensure_full_path_environment()` merges `path_helper`
  output plus explicit Homebrew/Docker-Desktop fallbacks into
  `os.environ["PATH"]` once, at `Application.__init__`.
  [HISTORY §44](docs/history/032-046.md#44)
- `login_item.py` (`SMAppService`) is a no-op outside a frozen `.app`
  — `is_supported()` needs `sys.frozen`, since a `uv run` process has
  no bundle identifier. Its status is always read live, never
  mirrored into `config.json`, so a System Settings revocation shows
  immediately. Real register/unregister on a packaged build is still
  UNVERIFIED. [HISTORY §131](docs/history/121-150.md#131)

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
  happened is still unknown. [HISTORY §63](docs/history/047-071.md#63)
- **Item 70 — a real stress-test hang at production library scale
  (~3,100 files), root cause still unidentified.** Reproduced 3/3 times
  at production scale, always right after sync/scan/match settle,
  waiting on Duplicates' Compute Fingerprints — but not in 2/2 isolated
  repros, one at 1,500-file scale. A `faulthandler` watchdog never fired
  once across ~38 stuck minutes, implicating whole-process GIL
  starvation, not just a stuck Qt loop. **Answered (round 6): this is a
  separate defect from item 105's pytest-runner stall** — different
  symptom, trigger, and mechanism. Real Spotify sync duration and/or
  real DB size/content are the untested suspects. A concrete lead
  (UNVERIFIED): until S22 the Dashboard's 2-second poll and the
  20-second history poll each read all ~32 MB of fingerprint text on
  a worker thread, and the Dashboard rebuilt every track row on the
  main thread each tick (§166); S41's stress run tests it.
  [HISTORY §70](docs/history/047-071.md#70),
  [§165](docs/history/151-180.md#165)
- **Item 125 — a real "not responding" quit hang, reported once,
  still unreproduced.** Kris closed the window (hid to tray correctly)
  then quit from the tray icon; the app reappeared in the Dock marked
  "not responding." Round 9 §2.3 mechanically confirmed the leading
  candidate mechanism in isolation — a per-window `QThreadPool` (the
  same shape `MainWindow.thread_pool` is) blocks its own destructor on
  any in-flight runnable, so `quit()` returning instantly does not mean
  the process actually exits — but did not reproduce Kris's specific
  sequence live. `cleanup_before_quit` now logs the real pool's
  active/max thread count at entry and elapsed time at exit
  specifically so a real recurrence is diagnosable from `seeker.log`
  alone. Next live attempt should bias toward quitting while a real
  background worker (scan/fingerprint/search) is provably still
  running. [HISTORY §125](docs/history/121-150.md#125)
- **Two unconfirmed round-8 test flakes** (the fullscreen-close pair
  is closed — see below). Diagnose any recurrence directly — never
  reach for `pytest-rerunfailures`.
  - `test_close_event_falls_back_to_real_close_when_no_tray` — fired
    once across ~12 full-suite runs, clean since. Round 8 §14
    subsequently modified `closeEvent` directly — check that first if
    it recurs.
  - **Closed, round 10 §6: the fullscreen-close pair**
    (`test_fullscreen_close_policy_check_ignores_a_stale_request` +
    `test_reopening_after_a_fullscreen_close_restores_maximized_not_
    fullscreen`, four recurrences). Traced live: offscreen Qt delivered
    a real `applicationStateChanged(ApplicationActive)` inside the
    test's own `qtbot.wait`, to the test's OWN closed window (not a
    zombie), which reopened it and called `set_dock_icon_visible(True)`.
    conftest's `_ignore_organic_application_state_changes` now drops
    signal-delivered calls (direct calls still reach the handler); two
    deterministic repro tests emit the real signal. PySide6 gotcha: a
    monkeypatched slot needs `functools.wraps` or `sender()` reads
    `None`. [HISTORY §130](docs/history/121-150.md#130)
  - `test_view_menu_focus_search_navigates_and_focuses_the_search_field`
    (added S15, §12.3/§12.5) — fails on real CI (`macos-latest`) with
    `assert False` on `search_artist_edit.hasFocus()`, confirmed on TWO
    consecutive real runs (`34340583368` at S15's own close-out commit
    `6f1ea0b`, before any S16 work existed; `34346738383` at S16's
    close-out `2b83554`) — not a regression from S16, and 2-for-2 on CI
    is stronger than a one-off. Passes reliably locally every time
    (confirmed across many full-suite runs this session). Consistent
    with a real focus-doesn't-land-without-a-real-window-manager gap
    under CI's headless/offscreen platform — plausible but UNVERIFIED;
    `QApplication.setActiveWindow`/a real `activateWindow()` call before
    the assertion is the next thing to try if it recurs.
- **Closed, S18: `test_download_button_disabled_with_no_playlist_selected`**
  (CI run `36758864929`). The button is enabled until a worker's
  render disables it; the test asserted after a bare `qtbot.wait(50)`.
  Reproduced with a 200 ms fact fetch; it now `waitUntil`s the
  disable. [HISTORY §161](docs/history/151-180.md#161)
- **Closed, round 10 §4: the review replace-button and history-refresh
  flakes were one root cause, not two — a fake's call counter increments
  on the worker thread before `_handle_task_finished` re-enables the
  triggering button on the main thread, so a test that clicks right
  after the counter hits its target can land the click on a still-
  disabled button (correct product behavior; the bug was in the test).
  §1.2 fixed the replace-button half by waiting on Review's own notice
  text; round 10 §4 fixed the history-refresh half the same way (wait
  for the button itself) and added a deterministic repro
  (`_block_event`/`_block_when_limit` on `FakeHistoryService`) so the
  race reproduces every run instead of ~1-in-8. [HISTORY
  §128](docs/history/121-150.md#128)
- **The real DB still holds three nested library locations**
  (`Music`⊂`x9-pro`, `Test`⊂`x9-pro`, `Test`⊂`Music`), double-indexing
  ~3,450 files. The guard, detection and merge exist; the merge needs
  the X9 Pro mounted, so Kris runs Settings → Library → Fix…, keeping `Music` (rehearsed on a copy: 43 matches kept, 0
  lost). [HISTORY §172](docs/history/151-180.md#172)
- **CI is real and running (not billing-blocked) as of 2026-09-08 —
  the S1.1/§117 "never completed a real run" finding is superseded.**
  Confirmed live via `gh run list`/`gh run view`: ruff/mypy clean on
  every run inspected so far. **S16 update, correcting the "never
  anything new" claim this bullet used to make:** two more real,
  CI-only pytest failures confirmed live since — the focus-search flake
  above, and `test_history_refresh_button_refetches` (already tracked
  above as a ~1-in-8 to 1-in-10 flake; this was one of those
  recurrences, not a new defect). Both are known/tracked, neither is a
  surprise, but "never anything new" was never re-verified after S14
  wrote it and turned out false the moment it was actually checked
  again — don't repeat an unverified claim as if re-confirmed.
  The 29-vs-1 skipped-test mismatch an earlier round left as an open
  question is now explained, not just observed: 29 = 28
  `@requires_x9_pro`-gated tests (no such drive on a GitHub runner) + 1
  `@requires_stress_opt_in` test (opt-in only) — exact arithmetic
  match. The 1 skip everywhere else is real-hardware machines running
  the x9_pro-gated tests for real and skipping only the opt-in stress
  test.

## Roadmap

Forward-looking only — see `docs/history/` for everything shipped.

- **Round 11 — the final polish round, ending in the v0.1.0 release —
  in progress.** Session map: `docs/rounds/round-11/SESSION-PLAN.md`;
  task text: `docs/rounds/round-11/BRIEF.md`; findings:
  `docs/rounds/round-11/AUDIT.md`. Every document: `docs/README.md`.
- **Linux packaging** (AppImage or `.deb`) — deprioritized, not scoped.
- **SoundCloud as a second source — deliberately deferred, not
  started.** Two disqualifying blockers found researching it:
  registering a SoundCloud API app requires a paid Artist Pro
  subscription, and it requires a confidential `client_secret` even for
  a native app — incompatible with a distributed `.dmg` holding no
  secret and no proxy server. If picked up: bring-your-own-credentials
  (Settings, like the existing Spotify field), source toggle top-right
  of the Dashboard. No code/schema/stubs exist yet.
- **The brief's §9.4** (long functions beyond `MainWindow`'s own
  decomposition) — optional; fold into a session that finishes early,
  or skip and say so.

## Working agreements

Hard-won, all five stay.

1. **Two-tier docs.** This file holds only present-tense standing facts
   short enough to read in full before starting; `docs/history/`
   holds the full investigation narrative a future debugging session
   needs. When closing an item: a condensed note here (over ~8 lines
   belongs in HISTORY only, linked), and — only if genuine
   investigation happened — a matching HISTORY entry. Move, never
   delete: a "done" item's detail must land in HISTORY before it
   leaves this file. A new entry appends to the last
   `docs/history/` file with `<a name="N"></a>` directly above its
   `### N — title`, plus one line in `docs/history/README.md`; link
   entries as `docs/history/<file>#N`, never by title slug.
   [HISTORY §137](docs/history/121-150.md#137)
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

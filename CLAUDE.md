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

- Python 3.13, pinned by `.python-version` (uv otherwise takes the
  newest: CI's runner got 3.15, which numba refuses,
  [§245](docs/history/241-270.md#245)); `uv` for env and build, one
  version pinned in three places (`[tool.uv] required-version`, setup-uv's
  `version:`, the `uv_build` range; `tests/test_uv_pin.py`,
  [§251](docs/history/241-270.md#251)). Type
  hints everywhere; `mypy --strict` clean, native and `--platform
  win32` ([§268](docs/history/241-270.md#268)), before work is done.
  Models are dataclasses, no getter/setter classes.
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
  each carry a reason and an expiry date. pip-audit silently skips a
  requirement whose marker is false where it runs, so the tool drops
  markers and audits one file per pin layer (every platform's pins).
  pip-audit cannot see native libraries: `docs/packaging.md` records
  them for each release.
  [§149](docs/history/121-150.md#149), [§167](docs/history/151-180.md#167),
  [§199](docs/history/181-210.md#199), [§253](docs/history/241-270.md#253)
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
- **Every program `src/` starts goes through `processes.run()` or
  `popen()`** (`from seeker import processes`): `CREATE_NO_WINDOW` on
  Windows, UTF-8 text with `errors="replace"`. They look `subprocess`
  up at call time, so a fake of `subprocess.run` still sees each call.
  `tests/test_subprocess_sweep.py` fails the build on a spawn named
  anywhere else. [§273](docs/history/271-300.md#273)
- **Text is UTF-8, never the locale's.** Every text read or write in
  the project's Python names `encoding="utf-8"` (`"utf-8-sig"` to read
  `config.json`, past a byte-order mark) or opens in a binary
  mode; ruff's PLW1514 and `tests/test_encoding_sweep.py` (over `src/`,
  `tests/`, `tools/`, `packaging/`) fail the build. When the settings
  (`config.json`), the Compose file or `slskd.yml` hold a byte that is
  not UTF-8, reading them raises `TextFileNotUtf8Error` and the file is
  left as it is: the settings never fall back to defaults, which a
  later save would write over the user's credentials. The Spotify
  token and the album-art cache, being caches, read as missing. The
  CLI's stdout and stderr are UTF-8 from `main()`. `PYTHONUTF8` and
  `PYTHONIOENCODING` stay unset in CI, tests and the app.
  [§274](docs/history/271-300.md#274)
- **Settings Seeker cannot read are left as they are, never replaced
  by defaults.** Only a missing `config.json` reads as defaults (a
  first run). One that cannot be read, is not UTF-8 or is not a JSON
  object raises `SettingsUnreadableError`, `TextFileNotUtf8Error` or
  `SettingsNotJsonError`, a sentence through `describe_error`, and
  nothing is written: every settings write loads the file first. A
  UTF-8 byte-order mark is read past, and the next save drops it. A
  wrongly typed value still takes its field's default, which the next
  save writes ([§146](docs/history/121-150.md#146)).
  [§N](docs/history/271-300.md#N)
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
uv run pytest         # run tests, offscreen; Kris alone prefixes QT_QPA_PLATFORM=cocoa
uv run mypy --strict src/  # type check — must stay clean
uv run mypy --strict --platform win32 src/  # the win32 branches too (CI's check runs both)
uv run ruff check src tests tools  # lint — CI's exact gate, 0 findings
uv run python tools/screenshots.py  # every screen, both themes -> tools/.screens/
# x86_64 under Rosetta (shares the real data folders, BRIEF §0.5; HISTORY §255):
uv python install cpython-3.13.15-macos-x86_64-none
UV_PROJECT_ENVIRONMENT=.venv-x86_64 uv sync --locked --python cpython-3.13.15-macos-x86_64-none
.venv-x86_64/bin/python -m pytest -q
```

## Standing facts and gotchas

Present-tense rules, each linked to the HISTORY entry holding its
investigation; `docs/history/README.md` resolves any `§N`.

### Topic files

Each topic's standing facts live beside its code. Read the file
before touching what it names. Claude Code loads a folder's file
as a system reminder when a session reads a file there with the
Read tool (observed 2026-11-02, `soulseek/`; a read through Bash,
UNVERIFIED). `docs/status.md` loads only when read.

- [`src/seeker/spotify/CLAUDE.md`](src/seeker/spotify/CLAUDE.md) —
  Spotify / OAuth: `spotify/`.
- [`src/seeker/soulseek/CLAUDE.md`](src/seeker/soulseek/CLAUDE.md) —
  SoulSeek / slskd: `soulseek/`, or anything that calls slskd.
- [`src/seeker/database/CLAUDE.md`](src/seeker/database/CLAUDE.md) —
  Database: `database/`, or a service's writes.
- [`src/seeker/ui/CLAUDE.md`](src/seeker/ui/CLAUDE.md) — Qt and
  threading (the quit seam, the thread pool, `stop`, live
  `get_config`), then UI-only rules: any UI change, or a service
  that takes a `stop` or `get_config`.
- [`tests/CLAUDE.md`](tests/CLAUDE.md) — Testing: writing or
  debugging a test.
- [`packaging/CLAUDE.md`](packaging/CLAUDE.md) — Packaging: the
  frozen app, the update check, the login item, a release.
- [`docs/status.md`](docs/status.md) — accepted risks, open issues,
  roadmap: planning, or a symptom that may be a known issue.

### Platforms

- **Intel pins and the x86_64 check.** The lock's Intel set is numba
  0.62.1, llvmlite 0.45.1, numpy 2.3.5 (arm64 gets newer); the
  commands under Commands create `.venv-x86_64` on Apple silicon,
  which runs under Rosetta with no `arch` prefix and shares the real
  data folders (never start the app from it; BRIEF §0.5). Rosetta
  exposes no AVX (llvmlite: `westmere`), so numba needs no
  `NUMBA_CPU_NAME`; that is Rosetta, not an Intel Mac. A Rosetta run
  cannot load arm64 Homebrew's libchromaprint: the 25 real-chromaprint
  tests skip through `tests/chromaprint_gate.py` unless an x86_64
  libchromaprint is on the loader path (this Mac has one in
  `/usr/local/lib`, observed 2026-11-03, so they run here;
  [§266](docs/history/241-270.md#266)), and
  `SEEKER_REQUIRE_CHROMAPRINT=1` makes a missing one fail instead (set
  it where the library must exist). Cold `analyze_audio` takes about 3x
  as long under Rosetta (67 s against 23 s, numba compiling).
  [§258](docs/history/241-270.md#258)
- **CI runs the suite on a real Intel Mac** (`check-intel`,
  `macos-15-intel`, ~20 min; the image retires fall 2027, then Rosetta
  only). A real Intel Mac has no `sysctl.proc_translated` key: it reads
  None, meaning native (observed in CI run `41501947860`).
  [§261](docs/history/241-270.md#261)
- **CI runs the suite on Windows, non-blocking.** `check-windows`
  (`windows-2025`, offscreen, about 16 min, no libchromaprint, so the
  25 fingerprint tests skip) has `continue-on-error: true` until the
  suite passes there; the change that makes it pass deletes that line.
  A module that cannot import shows as one ERROR hiding its tests. Its
  first run's 42 failures are numbered by cause in §268, and its
  addendum adds the second run's one new failure as entry 43; a row
  that fixes one cites its number. mypy decides `sys.platform` statically,
  so only `--platform win32` sees a `win32` branch.
  [§268](docs/history/241-270.md#268)

## Working agreements

Hard-won, all five stay.

1. **Two-tier docs.** This file and its topic files hold present-tense
   standing facts short enough to read in full; `docs/history/` holds the
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
   count is a regression to diagnose, never a new baseline. The
   tracked count is a bare run's, which is offscreen; a Cocoa run's
   is compared only with another Cocoa run's.
   [§267](docs/history/241-270.md#267)
4. **A comment asserting platform or framework behaviour cites an
   observation or says UNVERIFIED.** Unmarked confident claims have
   burned this codebase twice (the `:last-child` selector; a macOS
   tray-click claim a user's report disproved).
5. **A `continue` or skip in a sweep test names what it excludes and
   why that cannot hide the bug the test exists for.** A skip derived
   from the state a bug corrupts is a blindfold, not a guard.

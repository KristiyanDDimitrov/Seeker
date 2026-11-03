# seeker — test rules

Standing facts for the test suite, moved here from the root `CLAUDE.md`
so it stays short. Same rules as the root: present tense, each fact
linked to the HISTORY entry holding its investigation;
`docs/history/README.md` resolves any `§N`.

## Testing

- **UI tests build over `tests/fakes.py`** (`FakeApplication`, the
  `Fake*` services, `make_track`); no UI test module imports
  from another. Pages in `tests/pages/`, the shell in `tests/shell/`,
  subprocess scripts in `tests/repro/`. No `__init__.py`, so **a test
  file's basename is unique across directories** (else "import file
  mismatch"). [§161](../docs/history/151-180.md#161)
- **Tests run the real theme:** `conftest.py` applies `apply_theme()`
  session-wide, so `grab()` assertions see the shipped style.
  [§103](../docs/history/072-107.md#103)
- **Every run is offscreen unless its caller names a platform.**
  `conftest.py` sets `QT_QPA_PLATFORM=offscreen` (an 800×800 screen
  that fits restored windows to it) before any `QApplication` exists,
  over an empty value too, which Qt reads as Cocoa. So a bare `uv run
  pytest`, CI and every process a test starts agree.
  `QT_QPA_PLATFORM=cocoa uv run pytest` puts the windows
  on the desktop; only Kris runs that, by typing it. Offscreen never
  fires `colorSchemeChanged`, and
  `processEvents()` does not flush deferred deletes:
  `QCoreApplication.sendPostedEvents(None,
  QEvent.Type.DeferredDelete)`. A hidden `QWidgetItem`'s
  `setGeometry()` is a no-op; exclude it from `FlowLayout`
  assertions. [§167](../docs/history/151-180.md#167),
  [§109](../docs/history/108-120.md#109), [§79](../docs/history/072-107.md#79),
  [§267](../docs/history/241-270.md#267)
- **A UI test waits for its flow's real end, never the fake's call
  record**, which the worker writes before the main thread's finish
  handler runs. A late handler raises `RuntimeError: … already
  deleted` at setup of the *next* test; look at the one before it.
  [§128](../docs/history/121-150.md#128), [§148](../docs/history/121-150.md#148)
- **On Cocoa a test window may or may not become the active one**
  (timing, or another pytest process holding activation); offscreen
  never does. Never wait on `hasFocus()`. An active window hands a
  table keyboard focus, and Fusion tints its current item: sample a
  row's ground from a `NoFocus` table. [§201](../docs/history/181-210.md#201)
- **No test runs the real `docker`.** `conftest.py` refuses any
  `docker` spawn at `Popen` for the whole session (as a missing
  executable) and fails the test that tried, a leaked worker's too;
  fake `detect_docker_state`, `bring_up_slskd` or `subprocess.run`.
  A run once recreated Kris's slskd container. The stress test alone
  runs the read-only `docker inspect` (`allow_real_docker_inspect`);
  anything else of docker's stays refused there too.
  [§213](../docs/history/211-240.md#213), [§243](../docs/history/241-270.md#243)
- **Nothing a test runs opens on the desktop.** The same guard refuses
  `open`, `osascript` (which `webbrowser.open` runs on macOS through
  `os.popen`), `explorer`, `xdg-open` and `cmd /c start`, and a
  recording `QDesktopServices` handler takes every http, https, mailto
  and file link (a `setOpenExternalLinks` label's click); either fails
  the test that tried: fake `subprocess.run` or `webbrowser.open`, and
  don't click a link, or set a `QDesktopServices` URL handler (a label's
  click calls Qt's C++, past any Python fake of `openUrl`; observed
  offscreen 2026-11-03). A link of a new scheme joins conftest's
  `_URL_SCHEMES`. `tests/test_headless.py` reads every `subprocess`
  spawn in `src/` and runs each against a stand-in; a new program fails
  it until it joins conftest's `_DESKTOP_PROGRAMS` or the test's
  `OPENS_NOTHING`, with what it does. A spawn it cannot read (a
  computed command, `os.system`, `from subprocess import Popen`, an
  alias, `pty.spawn`, asyncio's, `QProcess`, Cocoa's,
  `multiprocessing`) fails it too: such a spawn may bind the real
  `Popen` before the guard, or never reach it. Its link test runs
  offscreen only: elsewhere a broken handler would open its links.
  [§267](../docs/history/241-270.md#267)
- **On Windows a test's `HOME` moves nothing of Seeker's.**
  `Path.expanduser()` reads `USERPROFILE` (observed on
  `check-windows`), and platformdirs 4.12.3's source resolves Seeker's
  data, log and cache folders from `WIN_PD_OVERRIDE_LOCAL_APPDATA`,
  else the known-folder API, never `HOME` (UNVERIFIED on Windows).
  Until R14-S2's conftest isolation lands, no suite runs on a Windows
  machine holding Seeker's data. [§268](../docs/history/241-270.md#268)
- **Skips:** `tests/test_stress_e2e.py` (`requires_stress_opt_in`) runs
  only with `SEEKER_RUN_STRESS_TEST=1`: it drives real Spotify, slskd and
  the X9 Pro for minutes and mutates the production DB. Run it
  deliberately after worker, timer or connection lifecycle changes. The
  28 real-file tests take `requires_x9_pro` from `tests/x9_pro_gate.py`
  and run only with `SEEKER_RUN_X9_PRO_TESTS=1` and the drive mounted:
  macOS guards a removable volume, and without the opt-in nothing looks
  at it. A bare run, like CI, skips 29: those 28 and the stress test.
  [§32](../docs/history/032-046.md#32), [§267](../docs/history/241-270.md#267)
- **A test needing a real libchromaprint takes `requires_chromaprint`
  from `tests/chromaprint_gate.py`**, never its own `skipif`. The skip
  also hides a library-lookup bug, so a runner that must have the
  library sets `SEEKER_REQUIRE_CHROMAPRINT=1` and the tests fail
  instead. [§258](../docs/history/241-270.md#258)
- conftest's autouse fixture sets `monkeypatch` up before a test's own
  fixtures, so its undo runs after their teardown. A fixture that
  restores state through a function a test may patch captures that
  function at setup. [§256](../docs/history/241-270.md#256)
- **A test never depends on a machine's ffmpeg.** `compute_fingerprint`
  gives a different error with and without one on PATH, and
  `check-intel` has none (Homebrew builds no Intel bottles, so no
  transitive install): a test of that path puts a failing `ffmpeg` on
  PATH or an empty PATH, as `test_duplicate_service.py` does. The
  `requires_ffmpeg` tests run in the arm64 `check` job only.
  [§262](../docs/history/241-270.md#262)
- **A test that ends with a worker in flight fails the next test, not
  itself:** the worker's Docker call lands between the next test's guard
  and its own fake, so the guard names the victim. Look at the test
  *before* the one that failed. `fakes.settle_workers(window)` waits and
  delivers results (`_show_short_page` calls it); `wait_for_workers`
  waits without processing events. [§264](../docs/history/241-270.md#264)
- **A Settings test that starts slskd fakes `check_slskd_web_login`**
  (`_fake_successful_bring_up` does): a start saves the default base URL
  127.0.0.1:5030, where a developer's own slskd listens, and the page
  POSTs a login there. [§264](../docs/history/241-270.md#264)
- **A flow's end is never read off `workers._callbacks`.** The registry is
  the whole process's, and a finish handler may start a worker of its own
  (Sharing's add ends in a refresh): wait on the outcome the flow produces
  or on `fakes.settle_workers(window)`. `tests/test_wait_sweeps.py` fails
  the build. [§265](../docs/history/241-270.md#265)
- **Every ceiling wait is bounded by `fakes.WAIT_MS`** (10 s). A ceiling
  wait returns as soon as its condition holds: `timeout=WAIT_MS` on
  pytest-qt's waits, `assert pool.waitForDone(WAIT_MS)`, `assert
  event.wait(WAIT_MS / 1000)`. Never a literal bound and never
  pytest-qt's default, because the Intel runner is 5 to 10 times slower
  on UI work. `tests/test_wait_sweeps.py` fails the build; a test file
  takes `from fakes import WAIT_MS` at module level and never rebinds
  it. Never lengthen a fixed delay (`qtbot.wait`) or a wait meant to
  time out. [§265](../docs/history/241-270.md#265),
  [§269](../docs/history/241-270.md#269)
- **A fake the code under test releases records whether it was
  released.** Its fallback (`cancel.wait(timeout=5.0)`, `stop.wait(5)`)
  is shorter than `WAIT_MS`, so the test's waits pass either way: keep
  the wait's result (`released`, `stopped`) and assert it.
  [§269](../docs/history/241-270.md#269)

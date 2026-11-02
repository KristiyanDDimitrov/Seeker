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
- **Local runs use Cocoa; CI uses `QT_QPA_PLATFORM=offscreen`** (an
  800×800 screen that fits restored windows to it). Reproduce a
  CI-only failure with `QT_QPA_PLATFORM=offscreen uv run pytest
  <test>`. Offscreen never fires `colorSchemeChanged`, and
  `processEvents()` does not flush deferred deletes:
  `QCoreApplication.sendPostedEvents(None,
  QEvent.Type.DeferredDelete)`. A hidden `QWidgetItem`'s
  `setGeometry()` is a no-op; exclude it from `FlowLayout`
  assertions. [§167](../docs/history/151-180.md#167),
  [§109](../docs/history/108-120.md#109), [§79](../docs/history/072-107.md#79)
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
- **Skips:** `tests/test_stress_e2e.py` (`requires_stress_opt_in`) runs
  only with `SEEKER_RUN_STRESS_TEST=1`: it drives real Spotify, slskd and
  the X9 Pro for minutes and mutates the production DB. Run it
  deliberately after worker, timer or connection lifecycle changes. CI
  skips 29: that one plus 28 `@requires_x9_pro`.
  [§32](../docs/history/032-046.md#32)
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

import functools
import importlib.util
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent


@pytest.fixture(autouse=True, scope="session")
def _apply_real_theme(qapp):
    """Roadmap item C1 (round 5) — found live while bisecting the
    header-divider bug: `theme.apply_theme()` was never called ANYWHERE
    in this whole test suite before this fixture. Every widget built
    by every UI test — including every prior "pixel-verified"
    `window.grab()` check (item 102's B2.2/B4.3/B6.5) — was rendered
    with Qt's un-styled default palette/style, not the real Fusion +
    QSS + dark-palette stack the shipped app actually applies in
    `main_ui.py`. Confirmed low-risk before adopting: running the full
    suite with this fixture added changed exactly one outcome (this
    round's own new header-divider test, which is specifically testing
    QSS the app had never once rendered under test) — every other test
    already passed against the real theme unchanged.
    """
    from seeker.ui import theme
    theme.apply_theme(qapp)


@pytest.fixture(autouse=True)
def _flush_deferred_widget_deletion(qapp):
    """Roadmap item 116 (round 8, §14.2) — found live wiring up
    MainWindow.applicationStateChanged: pytest-qt's own qtbot.addWidget
    teardown calls widget.close() THEN widget.deleteLater() on every
    test's window unconditionally (confirmed by reading pytestqt's own
    _close_widgets), but deleteLater() only actually destroys the
    underlying object once the event loop next processes posted
    events — nothing in this suite's own fixtures guaranteed that
    happened before the NEXT test's body ran. Ordinarily harmless (a
    still-alive-but-hidden previous test's MainWindow just sits there),
    but MainWindow.__init__ connects a bound method to the GLOBAL
    QApplication.applicationStateChanged signal, which (confirmed live,
    unlike C5.6's colorSchemeChanged connection — see item 109's own
    comment that colorSchemeChanged never actually fires under this
    offscreen platform) DOES organically fire during ordinary
    show()/close() calls even under QT_QPA_PLATFORM=offscreen: a
    still-undeleted previous test's window would react to a LATER,
    unrelated test's window activity by calling its own (stale)
    _on_tray_open_seeker(), interfering with that later test.
    Processing events at the START of every test flushes any deletion
    the PREVIOUS test's teardown already posted, so a test never
    starts with an earlier test's zombie window still connected.

    Confirmed live, not assumed: a plain `qapp.processEvents()` does
    NOT actually deliver a DeferredDelete event at all (verified with a
    weakref probe -- a widget survived two processEvents() calls
    untouched) — QCoreApplication.sendPostedEvents(None,
    QEvent.Type.DeferredDelete) is the call that actually does, and is
    what deleteLater()'s own documentation points to explicitly.
    """
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    yield


@pytest.fixture(autouse=True)
def _ignore_organic_application_state_changes(monkeypatch):
    """Round 10 §6 (HISTORY §130) — the fullscreen-close test pair's
    order-dependent failure, traced to its caller: offscreen Qt
    delivered a real applicationStateChanged(ApplicationActive) from
    inside a test's own qtbot.wait, with the window closed, so
    MainWindow's reopen handler ran `_on_tray_open_seeker()` —
    `set_dock_icon_visible(True)` plus a reopen — in the middle of a
    test that was not about reopening at all. Whether offscreen Qt
    sends one then depends on earlier tests' focus/activation history,
    which is why it only fired in the full suite.

    Drops only deliveries that arrive THROUGH the signal (`sender()`
    is the QApplication); a test calling
    `window._on_application_state_changed(...)` directly (sender()
    is None, confirmed by probe) still reaches the real handler, so
    the reopen contract stays tested. No test depends on an organic
    delivery — offscreen Qt cannot produce a real Dock click anyway.
    """
    from seeker.ui.main_window import MainWindow

    real_handler = MainWindow._on_application_state_changed

    # `functools.wraps` is load-bearing, not cosmetic: PySide6 resolves
    # a Python slot by `__name__`, and a renamed function gets
    # `sender() is None` even when the signal delivers it (confirmed by
    # probe) — which would silently let every organic delivery through.
    @functools.wraps(real_handler)
    def direct_calls_only(self, state):
        if self.sender() is not None:
            return
        real_handler(self, state)

    monkeypatch.setattr(
        MainWindow, "_on_application_state_changed", direct_calls_only,
    )


class _RealDockerRefused(FileNotFoundError):
    """Raised in place of running `docker`: callers already handle a
    missing executable, so the run stays deterministic while the
    fixture below fails the test."""


@pytest.fixture(autouse=True, scope="session")
def _docker_attempts():
    """Every `docker` command any test tries to run, refused.

    A test once reached the real `bring_up_slskd` and recreated the
    user's slskd container against pytest's temporary directories
    (HISTORY §213). Refusing at `Popen` covers `subprocess.run` and
    every other spawn, whatever the import path or thread, and stays in
    place for the whole session, so a worker outliving its test is
    refused too. A test that fakes `subprocess.run` never reaches it.
    """
    attempts: list[str] = []
    real_popen = subprocess.Popen

    class RefusingPopen(real_popen):
        def __init__(self, args, *pargs, **kwargs):
            argv = shlex.split(args) if isinstance(args, str) else list(args)
            if argv and Path(os.fsdecode(argv[0])).name == "docker":
                command = " ".join(os.fsdecode(part) for part in argv)
                attempts.append(command)
                raise _RealDockerRefused(
                    f"tests never run docker: {command!r}"
                )
            super().__init__(args, *pargs, **kwargs)

    subprocess.Popen = RefusingPopen
    yield attempts
    subprocess.Popen = real_popen


@pytest.fixture(autouse=True)
def _no_real_docker(_docker_attempts):
    """Fails the test that tried to run `docker` (or, for a worker
    that outlived its own test, the one running when it tried)."""
    _docker_attempts.clear()
    yield
    tried = list(_docker_attempts)
    _docker_attempts.clear()
    assert tried == [], (
        "a test tried to run the real docker; fake detect_docker_state, "
        f"bring_up_slskd or subprocess.run instead: {tried}"
    )


_SCREENSHOTS_TOOL = (
    Path(__file__).resolve().parent.parent / "tools" / "screenshots.py"
)


@pytest.fixture(scope="module")
def screenshots():
    """`tools/screenshots.py` as a module: its demo dataset and the
    steps that reach every screen."""
    spec = importlib.util.spec_from_file_location(
        "screenshots", _SCREENSHOTS_TOOL,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["screenshots"] = module
    spec.loader.exec_module(module)
    yield module
    del sys.modules["screenshots"]

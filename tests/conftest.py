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
def _force_dev_build_identity(monkeypatch):
    """Roadmap item RR1.2 — a real local packaging build leaves
    src/seeker/_build_info_generated.py behind (gitignored, never
    tracked — see _build_info.py's own docstring), which makes
    seeker._build_info.GIT_SHA/GIT_DESCRIBE/BUILT_AT read the real
    build's SHA/timestamp instead of the committed "dev" fallback.
    That's exactly what broke test_main_window_constructs_without_
    crashing and test_about_dialog_shows_build_identity in round 3 —
    both asserted the literal "dev" on the wrong assumption that "this
    test never runs against a real packaged build" (true) meant it was
    also safe from a build having happened at some point on the same
    machine (false, since the generated file just sits there
    afterward). Forced back to "dev" for every test in the whole
    suite, unconditionally — a developer's own local build must never
    be able to change what this suite reports, on this machine or
    anyone else's.
    """
    monkeypatch.setattr("seeker._build_info.GIT_SHA", "dev")
    monkeypatch.setattr("seeker._build_info.GIT_DESCRIBE", "dev")
    monkeypatch.setattr("seeker._build_info.BUILT_AT", "dev")

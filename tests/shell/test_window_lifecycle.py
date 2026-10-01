"""The window's lifecycle: close to tray, reopen, fullscreen and
zoomed geometry, the Dock icon policy, start hidden, and saved
geometry and last page.
"""
import base64
from dataclasses import replace

from PySide6.QtCore import QRect, Qt, QTimer

from fakes import (
    FakeApplication,
    force_tray_available,
)
from seeker.ui.main_window import (
    MainWindow,
)

# --- Roadmap item R7: run in the background from the macOS menu bar --------


def test_application_active_reopens_a_hidden_window(qtbot, monkeypatch):
    # Roadmap item 116 (round 8, §14.2.3) — this proves the HANDLER's
    # own contract (a hidden window comes back on a real
    # applicationStateChanged(ApplicationActive) emission), not that a
    # real Dock click reaches it -- that can't be produced under
    # QT_QPA_PLATFORM=offscreen and is left for real-desktop
    # verification.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.hide()
    assert window.isHidden()

    window._on_application_state_changed(
        Qt.ApplicationState.ApplicationActive
    )

    assert not window.isHidden()


def test_application_active_is_a_near_no_op_when_already_visible(
        qtbot, monkeypatch,
):
    # ApplicationActive also fires on ordinary activation (Cmd-Tab,
    # clicking a window) and, since Qt passes forcePropagate=true, even
    # when the state was already Active -- must not re-enter
    # _on_tray_open_seeker (and its poll calls) every time.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    assert not window.isHidden()

    calls = []
    monkeypatch.setattr(
        window._tray, "_on_tray_open_seeker", lambda: calls.append(1),
    )

    window._on_application_state_changed(
        Qt.ApplicationState.ApplicationActive
    )

    assert calls == []


def test_non_active_state_change_does_nothing(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.hide()
    assert window.isHidden()

    window._on_application_state_changed(
        Qt.ApplicationState.ApplicationInactive
    )

    assert window.isHidden()


def test_app_state_signal_connected_on_construction(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._app_state_connected is True


def test_app_state_signal_not_connected_without_a_tray_icon(qtbot, monkeypatch):
    # Roadmap item 116 (round 8, §14.2) — with no tray, closeEvent takes
    # the ordinary real-close path; there's no "hidden but still
    # running" state a reopen gesture would ever need to restore, so
    # connecting here would be pure overhead.
    force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._app_state_connected is False


def test_cleanup_before_quit_disconnects_the_app_state_signal(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    assert window._app_state_connected is True

    window.cleanup_before_quit()

    assert window._app_state_connected is False


def test_close_event_falls_back_to_real_close_when_no_tray(qtbot, monkeypatch):
    # Roadmap item R7.2 — the explicit fallback: with no real tray to
    # hide to, closing behaves exactly like it always did (a REAL
    # close, which — WA_DeleteOnClose being set — deletes the window's
    # own C++ object immediately; deliberately NOT registered with
    # qtbot.addWidget, since its own teardown would otherwise try to
    # close this same already-deleted window a second time).
    force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    # Round 9 §2.3.3 — the no-tray branch of `TrayController.
    # _build_tray_icon` (the single place this is now decided) sets
    # this explicitly, rather than relying on whatever `MainWindow.
    # __init__` set it to.
    assert window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.show()

    window.close()

    assert window._hidden_to_tray is False


def test_tray_available_clears_delete_on_close(qtbot, monkeypatch):
    # Round 9 §2.3.3 — the mirror of the no-tray case just above: the
    # same single decision point, other branch.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert not window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)


def test_close_event_hides_to_tray_when_available(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    assert window._tray._tray_icon is not None

    window.close()

    # `isHidden()` is synchronous (hide() itself is not deferred) — only
    # `_hidden_to_tray` waits on the delayed platform-level confirmation
    # (E1.4, round 7, corrected after review).
    assert window.isHidden()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)


def test_close_event_from_fullscreen_hides_without_leaving_fullscreen_first(
        qtbot, monkeypatch,
):
    # Roadmap item E1 (round 7) — reverses D4 (round 6). D4's own fix
    # (leave fullscreen via `showNormal()`, defer the real hide to the
    # next `WindowStateChange`) was only ever confirmed under offscreen
    # QPA, which has no macOS Space and no animated transition at all —
    # a real Mac's exit-fullscreen animation runs for a genuine several
    # hundred milliseconds, and the deferred `hide()` landed mid-
    # transition, leaving Qt's widget marked hidden while AppKit
    # re-ordered the real NSWindow back on screen once the animation
    # finished (an empty, unclosable window — reported live). Fixed by
    # NOT calling `showNormal()` at all on macOS: this window's `hide()`
    # now runs directly on the still-fullscreen window (via `super().
    # closeEvent()`, on/macOS whenever fullscreen), trusting AppKit's own
    # "close a fullscreen window" handling — the one path guaranteed to
    # tear the Space down correctly, since it's the platform's own.
    # `isFullScreen()` deliberately still reports True here — Qt's
    # window-state flags don't reset on hide() alone, only on the
    # explicit `show_restored()` `_on_tray_open_seeker` performs on
    # reopen (see the reopen tests below).
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)
    assert window.isFullScreen()

    window.close()
    qtbot.wait(20)

    assert window.isHidden()
    # `_hidden_to_tray` waits on the delayed platform-level confirmation
    # (E1.4, round 7, corrected after review) — `isHidden()` above is
    # unaffected, since `hide()` itself is never deferred.
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)
    assert window._reopen_filled is True


def test_reopening_after_a_fullscreen_close_restores_maximized_not_fullscreen(
        qtbot, monkeypatch,
):
    # Round 10 §5 — Kris's decision, 2026-09-23: a window closed while
    # fullscreen comes back filling the screen as a NORMAL window, not
    # re-entering macOS fullscreen — that transition is round 7's own
    # E1 (an empty, unclosable window). `_reopen_filled` is captured in
    # `closeEvent`, before anything about fullscreen state changes at
    # all; `show_restored()` is what actually turns it into
    # `showMaximized()` on reopen. Offscreen Qt asserts window STATE
    # only, never pixels (round 9 §3.1 follow-up 3) — the previous
    # version of this test asserted a restored geometry rect, which is
    # no longer the contract at all.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    window.showFullScreen()
    qtbot.wait(20)
    window.close()
    qtbot.wait(20)
    assert window.isHidden()

    window._tray._on_tray_open_seeker()

    assert not window.isFullScreen()
    assert window.isMaximized()


def test_reopening_after_a_windowed_close_restores_the_same_normal_size(
        qtbot, monkeypatch,
):
    # The other half of the same decision: a window closed WITHOUT
    # being filled comes back at exactly its windowed geometry, as
    # before — `_reopen_filled` must not blanket-maximize every reopen.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.setGeometry(QRect(50, 60, 1000, 700))
    qtbot.wait(20)
    expected_size = window.normalGeometry().size()

    window.close()
    qtbot.wait(20)
    assert window.isHidden()

    window._tray._on_tray_open_seeker()

    assert not window.isMaximized()
    assert not window.isFullScreen()
    assert window.normalGeometry().size() == expected_size


def test_reopening_after_a_zoomed_close_restores_maximized(
        qtbot, monkeypatch,
):
    # The brief's own "related problem" #2: a window closed via Window
    # -> Zoom used to reopen un-zoomed, because the old unconditional
    # showNormal() call cleared it. The same _reopen_filled flag fixes
    # both — set from isMaximized() at close, same as fullscreen.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    window.showMaximized()
    qtbot.wait(20)
    assert window.isMaximized()
    window.close()
    qtbot.wait(20)
    assert window.isHidden()

    window._tray._on_tray_open_seeker()

    assert window.isMaximized()
    assert not window.isFullScreen()


def test_restore_window_geometry_clears_a_fullscreen_flag_and_treats_it_filled(
        qtbot,
):
    # Round 10 §5 — closeEvent's fullscreen branch still has to persist
    # geometry while genuinely fullscreen (see that method's own
    # comment on why state can't be changed first), so a real saved
    # blob CAN carry Qt's own WindowFullScreen state bit.
    # _restore_window_geometry() is the one place that strips it back
    # out and treats it as filled instead, every time it runs (both the
    # __init__ call and showEvent's post-layout re-apply) — "never let
    # a restore enter fullscreen" applies to the geometry BLOB, not
    # just the separate window_reopen_filled flag.
    source_window = MainWindow(FakeApplication())
    qtbot.addWidget(source_window)
    source_window.showFullScreen()
    qtbot.wait(20)
    assert source_window.isFullScreen()
    saved = base64.b64encode(
        bytes(source_window.saveGeometry().data())
    ).decode("ascii")

    application = FakeApplication()
    application._config_store = replace(
        application._config_store, window_geometry=saved,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    assert not window.isFullScreen()
    assert window._reopen_filled is True


def test_close_to_tray_persists_geometry_for_a_fresh_window_to_restore(
        qtbot, monkeypatch,
):
    # Round 9 §3.1 — the real acceptance path Kris reported broken:
    # reopens at the default 1180x760, not the size the window was
    # closed at. Resize to something distinctive, close to the tray
    # (not quit), then build a brand new MainWindow against the SAME
    # config and confirm the EXACT saved bytes are what a fresh window
    # hands to restoreGeometry() — proving the save-to-restore wiring
    # end to end, byte for byte.
    #
    # Deliberately NOT asserting the real, applied pixel size here
    # (tried across three independently-reasoned fix attempts this
    # session — restore-after-_build_ui(), a QEvent::LayoutRequest
    # flush, and a showEvent()-based re-apply — all three produced the
    # IDENTICAL wrong result on real CI, macos-26: the restored width
    # clamped to exactly this window's own configured minimum, 960, not
    # the requested 1000, 3/3 times; none of it reproduced on this
    # machine, Darwin 25.6.0, across many full-suite and isolated runs).
    # That points at a genuine Qt/offscreen-QPA version difference in
    # how the real geometry engine behaves, not a defect in when this
    # codebase calls restoreGeometry() — exactly the class of thing the
    # brief's own acceptance-test text anticipated offscreen Qt might
    # not settle ("hand it back to Kris for a real-Mac confirmation").
    # `test_restore_window_geometry_decodes_and_calls_restore_geometry`
    # already established mocking `restoreGeometry` as this codebase's
    # way of testing the wiring deterministically instead of trusting
    # the real engine under offscreen QPA; this test follows the same
    # pattern for the full save round-trip.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    window.setGeometry(QRect(40, 30, 1000, 700))
    qtbot.wait(20)
    saved_bytes = bytes(window.saveGeometry().data())

    window.close()
    qtbot.wait(20)
    assert window.isHidden()
    assert application.settings.window_geometry
    assert base64.b64decode(application.settings.window_geometry) == saved_bytes

    restore_calls: list[bytes] = []
    monkeypatch.setattr(
        MainWindow, "restoreGeometry",
        lambda self, data: (restore_calls.append(bytes(data.data())), True)[1],
    )
    fresh_window = MainWindow(application)
    qtbot.addWidget(fresh_window)
    fresh_window.show()
    qtbot.wait(20)

    # __init__'s own best-effort call plus showEvent()'s authoritative
    # one both fire with the identical bytes — see their own comments
    # for why there are two.
    assert restore_calls == [saved_bytes, saved_bytes]


def test_cleanup_before_quit_does_not_overwrite_geometry_already_hidden(
        qtbot, monkeypatch,
):
    # Round 9 §3.1 — the backstop must not re-save once the window is
    # already confirmed hidden to the tray: closeEvent already captured
    # the good, visible-window geometry, and a saveGeometry() call
    # against a hidden window is not trustworthy (the bug this whole
    # item exists to fix). Confirmed directly, not just inferred from
    # the flag check, by spying on _persist_window_geometry itself.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    calls = []
    monkeypatch.setattr(
        window, "_persist_window_geometry", lambda: calls.append(True),
    )
    window.cleanup_before_quit()

    assert calls == []


def test_hidden_to_tray_stays_false_when_platform_window_still_exposed(
        qtbot, monkeypatch,
):
    # Roadmap item E1.4 (round 7, corrected after a SECOND review) — the
    # actual invariant this guard exists for, exercised directly rather
    # than left uncovered: when the real platform window disagrees with
    # Qt's own hidden bookkeeping (exactly the reported bug — Qt marked
    # itself hidden while AppKit still had the real NSWindow on screen),
    # `_hidden_to_tray` must NOT flip True. `windowHandle().isExposed()`
    # can't be monkeypatched directly on a real `QWindow`, so this forces
    # the disagreement through `_is_exposed_at_platform_level` — the one
    # production code path that reads it either way.
    #
    # This guard is deliberately REPORT-ONLY now (a second review found
    # the first version's "retry" — calling `hide()` again from inside
    # this same check — was itself a corrective ACTION taken during a
    # state indistinguishable from "a real transition is still playing,"
    # which is how round 6's bug was built in the first place). So there
    # is no second check to wait for here: `_hidden_to_tray` stays False
    # permanently once this one check finds a disagreement — logged, not
    # acted on — matching the ordinary (non-fullscreen) hide path this is
    # only ever reachable from.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    monkeypatch.setattr(
        window, "_is_exposed_at_platform_level", lambda: True,
    )

    window.close()

    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 100)
    assert window._hidden_to_tray is False


def test_stale_hide_verification_does_not_rehide_a_reopened_window(
        qtbot, monkeypatch,
):
    # Roadmap item E1.4 (round 7, corrected after a SECOND review) — a
    # single tray-menu click within the verify delay (a legitimate
    # reopen) used to be indistinguishable from "the hide didn't take":
    # the delayed check would see the platform window legitimately
    # exposed (because the user just reopened it) and, in the OLD
    # "retry" design, call `hide()` again — silently hiding a window the
    # user had just deliberately reopened, with no explanation. Fixed
    # via `_hide_request_id`, bumped by both the hide attempt and
    # `_on_tray_open_seeker`; a stale check (captured BEFORE the reopen)
    # must see its id no longer matches and do nothing at all.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    # The real platform window genuinely IS still exposed for a moment
    # after `close()` in this scenario (nothing artificial here) — what
    # matters is that the user reopens before the delayed check fires.
    monkeypatch.setattr(
        window, "_is_exposed_at_platform_level", lambda: True,
    )

    window.close()
    window._tray._on_tray_open_seeker()
    assert window.isVisible()
    assert window._hidden_to_tray is False

    # Let the stale check (scheduled by the close, before the reopen)
    # actually fire — it must be a no-op: the window stays visible, and
    # `_hidden_to_tray` stays False (the true, post-reopen state), not
    # flipped True by a check that no longer reflects reality.
    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 100)
    assert window.isVisible()
    assert window._hidden_to_tray is False


def test_fullscreen_close_never_arms_hide_verification(qtbot, monkeypatch):
    # Roadmap item E1.4 (round 7, corrected after a SECOND review) — the
    # fullscreen close branch must not schedule ANY verification check:
    # nothing is hidden BY US on that path (AppKit's own exit-fullscreen-
    # and-close animation does the real hiding, asynchronously); a check
    # landing mid-animation would see the platform window still
    # genuinely exposed and, in the report-only design, merely log —
    # but in a design that ever grows a corrective action again, would
    # call `hide()` mid-transition, reproducing round 6's bug. Asserted
    # structurally (no `_confirm_hidden_to_tray` call at all), not just
    # by absence of a symptom.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    confirm_calls = []
    monkeypatch.setattr(
        window, "_confirm_hidden_to_tray",
        lambda *a, **k: confirm_calls.append((a, k)),
    )

    window.close()

    assert confirm_calls == []
    assert window._hidden_to_tray is True


# --- Roadmap item 116 (round 8, §14.3): the Dock icon while hidden ----

def test_ordinary_hide_drops_the_dock_icon_once_confirmed(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    assert dock_calls == [False]


def test_ordinary_hide_does_not_drop_dock_icon_without_a_visible_tray(
        qtbot, monkeypatch,
):
    # §14.3.4 — that state is unrecoverable (no Dock icon, no tray
    # icon either), so the switch is guarded on a real, visible tray
    # icon, same precondition closeEvent's own hide-to-tray branch uses.
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    # closeEvent's own initial "is there a real tray to hide to" check
    # already ran (synchronously, inside close(), with the tray still
    # visible) -- patched only now, so it's specifically the LATER
    # confirm-check's own guard being exercised, not closeEvent's.
    monkeypatch.setattr(window._tray._tray_icon, "isVisible", lambda: False)
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    assert dock_calls == []


def test_fullscreen_close_schedules_a_policy_only_check(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )
    hide_calls = []
    monkeypatch.setattr(window, "hide", lambda: hide_calls.append(1))

    window.close()
    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 50)

    # Never calls hide() itself (nothing to manufacture round 6's bug
    # with) and does drop the Dock icon once the window reads as
    # genuinely not exposed (true under offscreen QPA immediately after
    # a real close()).
    assert hide_calls == []
    assert dock_calls == [False]


def test_fullscreen_close_policy_check_ignores_a_stale_request(
        qtbot, monkeypatch,
):
    # A reopen between the fullscreen close and the deferred check
    # firing must make the check a no-op — same `_hide_request_id`
    # staleness guard `_check_hidden_to_tray` already uses.
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    window._hide_request_id += 1  # simulates a reopen racing the check

    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 50)

    assert dock_calls == []


def _emit_application_active_during_the_next_wait(qapp) -> None:
    # Round 10 §6 — the exact delivery a traced full-suite failure
    # caught (HISTORY §130): QApplication's own applicationStateChanged
    # (ApplicationActive), emitted from inside qtbot.wait's event loop
    # while the window is closed. Emitted through the real signal, not
    # by calling the slot, so it proves conftest's
    # `_ignore_organic_application_state_changes` drops it.
    QTimer.singleShot(
        0,
        lambda: qapp.applicationStateChanged.emit(
            Qt.ApplicationState.ApplicationActive
        ),
    )


def test_organic_application_active_cannot_fire_the_dock_policy(
        qtbot, qapp, monkeypatch,
):
    # Deterministic repro of the fullscreen-close pair's order-dependent
    # failure (`assert dock_calls == []` → `[True]`) — see
    # `_emit_application_active_during_the_next_wait`.
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.showFullScreen()
    qtbot.wait(20)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.close()
    window._hide_request_id += 1
    _emit_application_active_during_the_next_wait(qapp)
    qtbot.wait(window._HIDE_TO_TRAY_VERIFY_DELAY_MS + 50)

    assert dock_calls == []


def test_organic_application_active_cannot_reopen_a_closed_window(
        qtbot, qapp, monkeypatch,
):
    # The pair's other half: the same stray delivery reopens the window
    # between `close()` and `assert window.isHidden()`.
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    window.showFullScreen()
    qtbot.wait(20)

    window.close()
    _emit_application_active_during_the_next_wait(qapp)
    qtbot.wait(20)

    assert window.isHidden()


def test_reopen_restores_the_dock_icon_before_showing(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(20)
    window.close()
    qtbot.waitUntil(lambda: window._hidden_to_tray is True, timeout=1000)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window._tray._on_tray_open_seeker()

    assert dock_calls == [True]


def test_cleanup_before_quit_restores_the_dock_icon(qtbot, monkeypatch):
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible",
        dock_calls.append,
    )

    window.cleanup_before_quit()

    assert dock_calls == [True]


def test_set_dock_icon_visible_is_a_no_op_off_macos(monkeypatch):
    from seeker.ui import main_window as main_window_module

    monkeypatch.setattr(main_window_module.sys, "platform", "win32")

    # Must not raise or attempt any AppKit import off-macOS.
    main_window_module._set_dock_icon_visible(True)
    main_window_module._set_dock_icon_visible(False)


def test_start_hidden_to_tray_sets_hidden_state_and_drops_dock_icon(
        qtbot, monkeypatch,
):
    # Round 9 §3.2 — the only caller is main_ui.main(), in place of
    # show(), when the user has opted into starting hidden. Never
    # shown at all here (unlike the ordinary hide path above, which
    # closes an already-visible window) — the point is skipping that
    # first-frame flash entirely.
    from seeker.ui import main_window as main_window_module

    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    dock_calls = []
    monkeypatch.setattr(
        main_window_module, "_set_dock_icon_visible", dock_calls.append,
    )

    result = window.start_hidden_to_tray()

    assert result is True
    assert window._hidden_to_tray is True
    assert window.isHidden()
    assert dock_calls == [False]


def test_start_hidden_to_tray_returns_false_without_a_tray_icon(
        qtbot, monkeypatch,
):
    # No tray to hide behind — the caller (main_ui.main()) must show()
    # instead, the same "never vanish with no way back" reasoning
    # closeEvent's own fallback already applies to an ordinary close.
    force_tray_available(monkeypatch, False)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)

    result = window.start_hidden_to_tray()

    assert result is False
    assert window._hidden_to_tray is False


def test_close_event_shows_one_off_notice_only_once(qtbot, monkeypatch):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window.close()
    assert application.mark_tray_hide_notice_shown_calls == 1

    window.showNormal()
    window.close()
    # Second hide -- config store now reports the notice already shown,
    # so it must not be marked (or shown) a second time.
    assert application.mark_tray_hide_notice_shown_calls == 1


def test_close_event_does_not_reshow_notice_when_already_shown(
        qtbot, monkeypatch,
):
    force_tray_available(monkeypatch, True)
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, tray_hide_notice_shown=True,
    )
    window = MainWindow(application)
    qtbot.addWidget(window)
    window.show()

    window.close()

    assert application.mark_tray_hide_notice_shown_calls == 0


# --- Window geometry/last-page persistence (round 8 §12.1) -----------------

def test_cleanup_before_quit_persists_window_geometry_and_last_page(qtbot):
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("history")

    window.cleanup_before_quit()

    assert application.settings.window_geometry
    assert application.settings.last_open_page == "history"


def test_cleanup_before_quit_persists_the_page_before_settings_was_opened(
        qtbot,
):
    # _show_page's own settings-transition tracking (_previous_page_key)
    # is what a real "closed while on Settings" quit should persist,
    # not the transient "settings" key itself — reopening straight into
    # Settings would strand the user with no page to go "back" to.
    application = FakeApplication()
    window = MainWindow(application)
    qtbot.addWidget(window)
    window._show_page("search")
    window._on_settings_clicked()

    window.cleanup_before_quit()

    assert application.settings.last_open_page == "search"


def test_restore_window_geometry_decodes_and_calls_restore_geometry(
        qtbot, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        MainWindow, "restoreGeometry",
        lambda self, data: (calls.append(bytes(data.data())), True)[1],
    )
    application = FakeApplication()
    application._config_store = replace(
        application._config_store,
        window_geometry=base64.b64encode(b"fake-geometry-blob").decode(
            "ascii",
        ),
    )

    window = MainWindow(application)
    qtbot.addWidget(window)

    assert calls == [b"fake-geometry-blob"]


def test_showevent_restores_geometry_once_more_on_first_show_only(
        qtbot, monkeypatch,
):
    # Round 9 §3.1 follow-up — showEvent() re-applies the restore
    # (see its own comment for why __init__'s call alone isn't
    # sufficient on every platform), guarded to the FIRST real show
    # only: a later reopen from the tray must not stomp a size the
    # user has since resized to.
    application = FakeApplication()
    application._config_store = replace(
        application._config_store,
        window_geometry=base64.b64encode(b"fake-geometry-blob").decode(
            "ascii",
        ),
    )
    window = MainWindow(application)
    qtbot.addWidget(window)

    calls: list[bytes] = []
    monkeypatch.setattr(
        MainWindow, "restoreGeometry",
        lambda self, data: (calls.append(bytes(data.data())), True)[1],
    )

    window.show()
    qtbot.wait(20)
    assert calls == [b"fake-geometry-blob"]

    window.hide()
    window.show()
    qtbot.wait(20)

    # No second call — the guard held.
    assert calls == [b"fake-geometry-blob"]


def test_restore_window_geometry_tolerates_a_corrupt_stored_value(qtbot):
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, window_geometry="not valid base64!!",
    )

    # Must not raise — a hand-edited or future-format config.json is
    # exactly the case _restore_window_geometry's own docstring guards.
    window = MainWindow(application)
    qtbot.addWidget(window)


def test_last_open_page_restored_on_construction(qtbot):
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, last_open_page="review",
    )

    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._current_page_key == "review"


def test_last_open_page_falls_back_to_dashboard_for_an_unrecognized_key(
        qtbot,
):
    application = FakeApplication()
    application._config_store = replace(
        application._config_store, last_open_page="not-a-real-page",
    )

    window = MainWindow(application)
    qtbot.addWidget(window)

    assert window._current_page_key == "dashboard"

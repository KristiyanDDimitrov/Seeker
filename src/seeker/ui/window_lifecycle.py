"""The main window's lifecycle: saved geometry, hiding to the menu bar
(and checking at the platform level that the hide took), the Dock icon
policy, and quitting.

`MainWindow` keeps the Qt overrides — `closeEvent`, `showEvent`, and
the `eventFilter` installed on the QApplication — because only the
QObject itself can receive them, and delegates each one here. The tray
(`ui/tray.py`) owns the icon, menu and notifications; reopening the
window from it goes through `MainWindow.reopen()`, which lands here, so
every write to the hidden-to-tray state happens in this one class.
HISTORY §113, §114, §124, §125, §129 and §130 record why each piece
looks the way it does.
"""

import base64
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox

from seeker.application import Application
from seeker.models.download_request import DownloadStatus
from seeker.ui.tray import TrayController, _set_dock_icon_visible

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowLifecycleHost:
    """What the lifecycle needs from the shell.

    `page_to_reopen` names the page saved with the geometry, so the
    next launch opens where the user was. `release_shell` is the
    shell's own part of a quit: its timers, the page state it persists
    and its connections to global signals.
    """
    application: Application
    window: QMainWindow
    thread_pool: QThreadPool
    tray: TrayController
    page_to_reopen: Callable[[], str]
    release_shell: Callable[[], None]


class WindowLifecycleController:
    def __init__(self, host: WindowLifecycleHost) -> None:
        self._host = host
        # R7.1 — set once the window is genuinely hidden-to-tray
        # (closeEvent), not just "not the active window"; R7.6 reads
        # this to skip re-render work while nobody can see it.
        self._hidden_to_tray = False
        # Round 9 §3.1 follow-up — guards `after_show()`'s own re-apply
        # of the restored geometry (see that method) to exactly the
        # FIRST real show, never a later one (reopening from the tray
        # must not stomp on a size the user has since resized to).
        self._window_geometry_restored_after_first_show = False
        # Round 10 §5 — replaces round 7's `_pre_fullscreen_geometry`.
        # Kris's decision (2026-09-23): a window closed fullscreen or
        # maximized/zoomed comes back FILLING THE SCREEN AS A NORMAL
        # WINDOW, never re-entering macOS fullscreen (that transition
        # is round 7's own E1 — an empty, unclosable window). Set in
        # `close_event` (both branches) as `isFullScreen() or
        # isMaximized()`, captured before anything changes window
        # state. Initialized from the persisted setting so a fresh
        # relaunch honors the same reopen behavior a live reopen would
        # (`show_restored()`'s only caller besides `reopen` is
        # `main_ui.py`'s first `window.show_restored()`);
        # `restore_window_geometry()` can also set this True later, if
        # the geometry blob itself still carries Qt's own fullscreen
        # state bit — see that method's own comment.
        self._reopen_filled = host.application.settings.window_reopen_filled
        # Roadmap item E1.4 (round 7, corrected after a second review) —
        # a monotonic counter, bumped on every hide-to-tray attempt AND
        # every deliberate reopen (`reopen`). A delayed verification
        # check captures this value when scheduled and bails if it no
        # longer matches by the time the timer fires — otherwise a
        # stale check landing after the user has ALREADY reopened the
        # window (a single tray-menu click within the verify delay)
        # would see the platform window legitimately exposed, conclude
        # the hide "didn't take," and hide the window right back out
        # from under the user with no explanation. A stale check must
        # never act.
        self._hide_request_id = 0

    def is_hidden_to_tray(self) -> bool:
        return self._hidden_to_tray

    def restore_window_geometry(self) -> None:
        # Round 8 §12.1 — a corrupt/foreign base64 blob (a hand-edited
        # config.json, or a value from some future format this version
        # doesn't understand) must never raise; restoreGeometry()
        # itself already reports success/failure via its return value
        # rather than throwing, so a bad value is just left as the
        # resize() default MainWindow.__init__ set.
        encoded = self._host.application.settings.window_geometry
        if not encoded:
            return

        try:
            raw = base64.b64decode(encoded)
        except (ValueError, TypeError):
            return

        self._host.window.restoreGeometry(QByteArray(raw))
        # Round 10 §5 — closeEvent's fullscreen branch has to persist
        # geometry while genuinely fullscreen (see that method's own
        # comment on why window state can't be changed before AppKit's
        # own close animation runs), so a real saved blob CAN still
        # carry Qt's own WindowFullScreen state bit — restoreGeometry()
        # above just re-applied it. Stripped back out and treated as
        # filled instead, every time this runs (both the MainWindow.__init__ call
        # and after_show()'s post-layout re-apply below): Kris's decision
        # is "never re-enter fullscreen on a restore," full stop, not
        # just "the window_reopen_filled flag says so."
        if self._host.window.windowState() & Qt.WindowState.WindowFullScreen:
            self._host.window.setWindowState(
                (self._host.window.windowState() & ~Qt.WindowState.WindowFullScreen)
                | Qt.WindowState.WindowMaximized
            )
            self._reopen_filled = True

    def _persist_window_geometry(self) -> None:
        # Round 8 §12.1 — called from cleanup_before_quit, the one real
        # cleanup path for every quit route (see that method's own
        # comment); hiding to the tray does not destroy this window, so
        # there is nothing to lose on that path and no reason to persist
        # on every resize/move.
        encoded = base64.b64encode(
            self._host.window.saveGeometry().data()
        ).decode("ascii")
        self._host.application.update_settings(
            window_geometry=encoded,
            last_open_page=self._host.page_to_reopen(),
            window_reopen_filled=self._reopen_filled,
        )

    def show_restored(self) -> None:
        """Show the window the way it was closed — round 10 §5, the
        single method that owns "come back filled or windowed."
        Replaces the old `showNormal()` + pre-fullscreen-geometry
        `setGeometry()` pair `_on_tray_open_seeker` used to run
        directly; `main_ui.py`'s first show honors the same flag
        (loaded from settings at construction — see `_reopen_filled`'s
        own comment) so a relaunch behaves like a live reopen.
        """
        if self._reopen_filled:
            self._host.window.showMaximized()
        else:
            self._host.window.showNormal()

    def reopen(self) -> None:
        """Bring the window back from the menu bar (the tray's Open
        Seeker, a tray click, or a Dock reopen)."""
        # Roadmap item E1.4 (round 7) — a deliberate reopen invalidates
        # any still-pending hide-verification check (see
        # `_hide_request_id`'s own comment at its declaration) — without
        # this, a check scheduled by an earlier `close_event` could
        # still fire after the user has already reopened the window,
        # see it legitimately exposed, and hide it right back out from
        # under them.
        self._hide_request_id += 1
        self._hidden_to_tray = False
        # Roadmap item 116 (round 8, §14.3.3) — order matters: the
        # window must be shown by an app that is already Regular, or it
        # can come up behind other applications.
        _set_dock_icon_visible(True)
        # Round 10 §5 — give back the window filled (maximized) or
        # windowed exactly as the user left it, never re-entering
        # fullscreen; see `show_restored()`'s own docstring.
        self.show_restored()
        self._host.window.raise_()
        self._host.window.activateWindow()

    def confirm_quit_if_downloads_active(self) -> bool:
        # UI -> service, as always: the count comes from
        # DashboardService.get_active_downloads() (a cheap local DB
        # read — see downloads_page.py's own comment on this same
        # call), never a repository queried directly here. "In
        # progress" mirrors downloads_page.active_downloads_count's own
        # definition (status == "downloading") rather than inventing a
        # second one.
        active = self._host.application.dashboard_service.get_active_downloads()
        count = sum(
            1 for download in active
            if download.request.status == DownloadStatus.DOWNLOADING
        )
        if count == 0:
            return True
        return self._show_quit_confirmation(count)

    def _show_quit_confirmation(self, count: int) -> bool:
        # Round 9 §2.1 (HISTORY §123) established what's actually true
        # before this copy was written: quitting stops Seeker's own
        # reconciliation, not the transfer itself — slskd keeps the
        # download running in its own container regardless. Nothing is
        # ever lost, so the word "lose" does not belong here.
        noun = "download" if count == 1 else "downloads"
        box = QMessageBox(self._host.window)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Quit Seeker?")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"{count} {noun} still in progress.")
        box.setInformativeText(
            "Seeker hands transfers to SoulSeek, which keeps running "
            "after you quit — but Seeker won't file the finished "
            "tracks into your library until you open it again."
        )
        quit_button = box.addButton(
            "Quit Anyway", QMessageBox.ButtonRole.DestructiveRole,
        )
        keep_open_button = box.addButton(
            "Keep Seeker Open", QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(keep_open_button)
        box.exec()
        return box.clickedButton() is quit_button

    def cleanup_before_quit(self) -> None:
        # Roadmap item R7.7 — the one real cleanup path for every quit
        # route (tray Quit, real ⌘Q/dock-quit — both reach here via
        # QApplication.aboutToQuit, connected once in main_ui.py).
        # Deliberately NOT an attempt at roadmap item 70's own open,
        # unresolved stress-test hang — this stops timers/hides the
        # tray icon so a real quit doesn't leave anything running past
        # the window closing, but does not change poll_downloads/
        # fingerprinting internals at all.
        #
        # Round 9 §2.3 — instrumentation for the reported "not
        # responding" quit hang (unreproduced live; mechanically
        # confirmed via a standalone QThreadPool probe that a slow
        # in-flight runnable blocks the pool's own destructor for
        # exactly its remaining runtime — see HISTORY §125). This
        # method's own body finishes quickly regardless (nothing here
        # waits on `self._host.thread_pool`), so a future real recurrence
        # logging "starting" but never "finished" points at something
        # IN this method; both logged quickly but the process still
        # hangs afterward points at teardown of `self._host.thread_pool`
        # itself once this method returns and `window` goes out of
        # scope. Logs `self._host.thread_pool` specifically, not
        # `QThreadPool.globalInstance()` — every real worker here runs
        # on the per-window pool built in `MainWindow.__init__`, so the global
        # instance's own count would always read 0 regardless.
        started_at = time.monotonic()
        logger.info(
            "cleanup_before_quit: starting, thread_pool active=%d max=%d",
            self._host.thread_pool.activeThreadCount(),
            self._host.thread_pool.maxThreadCount(),
        )

        self._host.release_shell()

        # Round 9 §3.1 — this is now a BACKSTOP, not the primary save
        # path: `close_event` already persists geometry while the window
        # is still visible, immediately before hiding to the tray (both
        # branches). Skip an already-hidden window here rather than
        # overwriting that good value with whatever saveGeometry()
        # reports against a non-visible window. Gated on
        # `_hidden_to_tray` rather than Qt's own `isHidden()`
        # deliberately — `isHidden()` reads True for a widget that was
        # simply never shown at all (confirmed live), which would wrongly
        # skip the quit-without-closing route (the window is genuinely
        # visible there, just never explicitly hidden-to-tray) and every
        # existing test that constructs a `MainWindow` without a real
        # `show()`. `_hidden_to_tray` starts False and only flips True
        # once this window has actually been hidden to the tray, which is
        # exactly the state this backstop needs to distinguish.
        if not self._hidden_to_tray:
            self._persist_window_geometry()

        # Roadmap item 116 (round 8, §14.3.4) — a quit must never leave
        # the process in Accessory mode mid-teardown; unconditional, not
        # gated on any hidden-state tracking, so a quit from ANY state
        # (visible, hidden, mid-fullscreen-close) always restores it.
        _set_dock_icon_visible(True)

        self._host.tray.hide_icon()

        logger.info(
            "cleanup_before_quit: finished in %.3fs",
            time.monotonic() - started_at,
        )

    # Roadmap item 116 (round 8, §14.5) — corrected: the previous
    # comment here claimed "400ms is comfortably above" a stated
    # 0.5-1s fullscreen-animation range, which is backwards (400 is
    # below all of it) and was itself never measured. This item DID
    # measure the ORDINARY (non-fullscreen) close path for real on a
    # real Mac (a real AXCloseButton click to the Dock icon actually
    # disappearing, confirmed via `lsappinfo`): ~530ms including real
    # AppleScript/process-launch overhead around this delay, consistent
    # with 400ms not being a bad value for THAT path. The
    # fullscreen-exit-animation duration this constant's old comment
    # was actually trying to describe is UNVERIFIED — the real macOS
    # fullscreen-close affordance hides its close button from the
    # accessibility tree while fullscreen (confirmed: `window 1`
    # exposes only an `AXRaise` action, no close action, while
    # AXFullScreen is true), so it couldn't be triggered
    # programmatically to time it in this session. Left at 400ms
    # (untuned) rather than replaced with an unmeasured guess either
    # way — this constant only governs the ORDINARY hide path in
    # practice, since the fullscreen branch (closeEvent, below) arms no
    # verification timer of its own; see
    # _schedule_dock_icon_policy_check_after_fullscreen_close for that
    # path's own, separately-reasoned reuse of this same delay.
    _HIDE_TO_TRAY_VERIFY_DELAY_MS = 400

    def after_show(self) -> None:
        """Run from `MainWindow.showEvent`, after the base class's own
        show handling."""
        # Round 9 §3.1 follow-up — a real CI-only failure (macos-26,
        # run 34479709317) that this machine's offscreen suite never
        # reproduced despite real effort: even called after _build_ui()
        # (see that call's own comment), the MainWindow.__init__-time
        # restoreGeometry() lost to the central widget's own first
        # layout activation on that runner, coming back clamped to
        # exactly this window's configured minimum width — the same
        # symptom class as the original bug, just later, and a
        # QEvent::LayoutRequest flush between _build_ui() and the
        # restore (tried first) did not fix it either, so something
        # about restoreGeometry()'s OWN resize re-triggers layout
        # activation rather than only the initial one.
        #
        # Re-applying the restore here, once, wins unconditionally
        # instead of relying on event-queue ordering: Qt activates a
        # widget's layout as part of its own show handling before
        # delivering the QShowEvent, so by the time this method runs,
        # first activation has already happened — restoreGeometry()
        # here is provably the last write, not a guess about timing.
        # Guarded to the first real show only: a later show (reopening
        # from the tray) must not stomp a size the user has since
        # resized to.
        if not self._window_geometry_restored_after_first_show:
            self._window_geometry_restored_after_first_show = True
            self.restore_window_geometry()
            # Round 10 §5 — enforced deterministically LAST, after the
            # geometry re-apply above: `restore_window_geometry()`'s
            # own `restoreGeometry()` call can decide a Normal window
            # state on its own (e.g. a geometry blob saved before
            # `window_reopen_filled` existed, disagreeing with a since-
            # set flag) — this makes sure that can never un-maximize a
            # window `show_restored()` already filled moments earlier.
            # A no-op whenever the two already agree, which is the
            # ordinary case.
            if self._reopen_filled:
                self._host.window.showMaximized()

    def start_hidden_to_tray(self) -> bool:
        """Round 9 §3.2's "start hidden in the menu bar" option — the
        only caller is `main_ui.main()`, in place of `window.show()`,
        when the user has opted into starting hidden. Never calls
        show() at all rather than showing then immediately hiding,
        which would flash a real window on screen for one frame first;
        the saved geometry is picked up normally the next time the
        window IS shown (`after_show`'s own restore), since it never
        ran here.

        Returns whether it actually started hidden. On False (no tray
        icon exists to hide behind), the caller must show() instead —
        a launch with neither a visible window nor a tray icon would
        make the app unreachable, the same reasoning `closeEvent`
        already applies to an ordinary close.
        """
        if not self._host.tray.is_icon_visible():
            return False

        self._hidden_to_tray = True
        _set_dock_icon_visible(False)
        return True

    def close_event(self, event: QCloseEvent) -> None:
        # Roadmap item R7.1/R7.2 — hides to the menu bar instead of
        # quitting, but ONLY when there's a real tray icon to hide to;
        # with none available (or not actually shown), this falls
        # through to Qt's ordinary close behavior unchanged — the
        # explicit fallback the brief itself asks for.
        if not self._host.tray.is_icon_visible():
            QMainWindow.closeEvent(self._host.window, event)
            return

        # Roadmap item E1.4 (round 7) — a new hide attempt invalidates
        # any earlier one's still-pending verification (see
        # `_hide_request_id`'s own comment at its declaration).
        self._hide_request_id += 1

        # Round 10 §5 — captured before anything below changes window
        # state (both branches use this same value), so it reflects
        # how the user actually left the window, not whatever's left
        # after hide()/AppKit's own close handling runs. Kris's
        # decision, 2026-09-23: a reopen fills the screen as a normal
        # window either way — it never re-enters fullscreen.
        window = self._host.window
        reopen_filled = window.isFullScreen() or window.isMaximized()

        # Roadmap item E1 (round 7) — reverses D4 (round 6). D4's
        # "exit fullscreen, defer the hide to the next WindowStateChange"
        # was only ever confirmed under offscreen QPA, which has no
        # macOS Space and no animated transition at all — the deferred
        # `hide()` there lands instantly, with nothing to race. On a
        # real Mac the exit is a genuine multi-hundred-millisecond
        # AppKit animation; `hide()` firing mid-transition left Qt's
        # widget marked hidden while AppKit re-ordered the real NSWindow
        # back on screen once the animation finished — an empty,
        # unclosable window with a native title bar Qt no longer thinks
        # exists (reported live; see HISTORY §114, E1).
        #
        # Fixed by not intercepting the close at all while fullscreen:
        # let AppKit's own "close a fullscreen window" handling run,
        # which tears down the Space correctly because it's the
        # platform's own path, not anything this app has to get right
        # itself. `setQuitOnLastWindowClosed(False)` (main_ui.py) keeps
        # the app alive in the tray exactly as before. `WA_
        # DeleteOnClose` is handled once, where the tray icon is built
        # (`_build_tray_icon`) — not here; see that comment.
        if sys.platform == "darwin" and self._host.window.isFullScreen():
            self._reopen_filled = reopen_filled
            # Round 9 §3.1 — persisted here, while the window is still
            # genuinely visible, rather than left solely to
            # cleanup_before_quit's backstop: in Kris's real flow the
            # window is already hidden to the tray by the time a quit
            # follows, and saveGeometry() against a non-visible window
            # is not the geometry the user actually wants back.
            self._persist_window_geometry()
            self._host.tray.show_hide_notice_once()
            QMainWindow.closeEvent(self._host.window, event)
            # Roadmap item E1.4 (round 7, corrected after a SECOND
            # review) — this branch does NOT arm the verify timer.
            # Nothing is being hidden BY US here: `super().closeEvent()`
            # just accepted the close, and it's AppKit's own exit-
            # fullscreen-and-close animation that does the actual
            # hiding, asynchronously, over the next ~0.5-1s. A verify
            # check landing inside that window would see the platform
            # window still genuinely exposed (the animation is still
            # playing, not stuck), conclude the hide "didn't take," and
            # call `hide()` again MID-TRANSITION — which is exactly the
            # operation that produced round 6's empty, unclosable
            # window in the first place. A safety net that can
            # manufacture the exact failure it exists to detect, on the
            # one path that has never run on real hardware, is worse
            # than no safety net. There is nothing left to verify on
            # this path anyway: AppKit's own close handling is the
            # thing being trusted, not a `hide()` call this class made
            # itself.
            self._hidden_to_tray = True
            # Roadmap item 116 (round 8, §14.3.2) — a POLICY-ONLY
            # deferred check, deliberately separate from
            # _confirm_hidden_to_tray above: it never calls hide() and
            # never touches _hidden_to_tray, so it cannot manufacture
            # the exact failure this branch's own comment just
            # described. Dropping the Dock icon is safe to attempt here
            # precisely because it takes no corrective action on the
            # window itself.
            self._schedule_dock_icon_policy_check_after_fullscreen_close(
                self._hide_request_id
            )
            return

        event.ignore()
        self._reopen_filled = reopen_filled
        # Round 9 §3.1 — persisted while still visible, before hide()
        # below makes it not; see the fullscreen branch above for the
        # same reasoning.
        self._persist_window_geometry()
        self._host.window.hide()
        self._host.tray.show_hide_notice_once()
        self._confirm_hidden_to_tray(self._hide_request_id)

    def _confirm_hidden_to_tray(self, request_id: int) -> None:
        # Roadmap item E1.4 (round 7, corrected after review) — the
        # first version of this guard probed `self.isVisible()`, which
        # is Qt's OWN bookkeeping: `hide()` sets it synchronously and
        # unconditionally, so it reads False on the very next line on
        # every platform regardless of what the real platform window is
        # doing — dead code, confirmed by review, with no test having
        # caught it (nothing could: it can never disagree with the call
        # that just ran). Worse than dead code: that bookkeeping is
        # EXACTLY what lied in the original bug (Qt marked itself hidden
        # while AppKit still had the real NSWindow on screen) — a guard
        # built on the lying witness can only ever agree with it.
        #
        # The real platform window's own reported exposure
        # (`QWindow.isExposed()` — updated by the platform plugin from
        # real show/hide/expose notifications, not by a widget's own
        # "did something call hide()" flag) is the witness that can
        # actually disagree. `_hidden_to_tray` is deliberately NOT set
        # True until it's confirmed: every poll/render method in this
        # class gates on that flag (R7.6), and setting it optimistically
        # before confirmation is exactly how the original bug went
        # silent (rendering stopped into a window the user could still
        # see). Only reachable from the ordinary (non-fullscreen) hide
        # path — see the fullscreen branch above for why THAT path
        # deliberately arms no verification at all.
        #
        # `request_id` is captured here, at schedule time, and
        # re-checked when the timer fires (round 7, corrected after a
        # SECOND review) — a single tray-menu click within this delay
        # (a legitimate reopen via `reopen`) must not let
        # a now-stale check see the platform window legitimately
        # exposed, conclude the EARLIER hide "didn't take," and hide the
        # window right back out from under the user with no
        # explanation. A stale check must never act.
        QTimer.singleShot(
            self._HIDE_TO_TRAY_VERIFY_DELAY_MS,
            lambda: self._check_hidden_to_tray(request_id),
        )

    def _is_exposed_at_platform_level(self) -> bool:
        # Split out from `_check_hidden_to_tray` so a test can force the
        # "Qt says hidden, the platform still disagrees" case directly
        # (monkeypatching a real `QWindow`'s own `isExposed()` isn't
        # practical) — this is the one production code path that reads
        # it either way.
        handle = self._host.window.windowHandle()
        return handle is not None and handle.isExposed()

    def _check_hidden_to_tray(self, request_id: int) -> None:
        # This delayed callback's target (`self`) can be gone by the
        # time it fires — most visibly in tests, where qtbot tears a
        # window down well before a real-world delay would elapse, but
        # in principle any real close racing a real quit too. Mirrors
        # `ui/workers.py`'s own `_emit_or_drop` finding: wrapping the
        # actual use in `try/except RuntimeError` is the confirmed-safe
        # boundary for a deleted Qt object (a clean, catchable
        # exception, never corruption) — not a preceding `isValid`
        # check, which that item's own research showed still races in
        # the cross-thread case. This callback runs entirely on the GUI
        # thread with nothing else able to delete `self` mid-call, so
        # there's no real race here either way; wrapping anyway keeps
        # this in line with the one pattern this codebase already
        # trusts for "the widget a deferred callback targets might not
        # exist anymore."
        try:
            if request_id != self._hide_request_id:
                # Stale — a newer hide attempt or a reopen has happened
                # since this check was scheduled. See `_hide_request_id`
                # and `_confirm_hidden_to_tray`'s own comments.
                return

            if not self._is_exposed_at_platform_level():
                self._hidden_to_tray = True
                # Roadmap item 116 (round 8, §14.3.2) — the ordinary
                # hide path: confirmed genuinely hidden at the platform
                # level, so drop the Dock icon here. Guarded on a real,
                # VISIBLE tray icon (§14.3.4) — that state is otherwise
                # unrecoverable: no Dock icon, and no tray icon either.
                if self._host.tray.is_icon_visible():
                    _set_dock_icon_visible(False)
                return

            # Roadmap item E1.4 (round 7, corrected after a SECOND
            # review) — the first version of this branch called
            # `self._host.window.hide()` again here as a "retry." That is a
            # corrective ACTION taken during a state this guard cannot
            # distinguish from "AppKit's own transition is still
            # playing" — indistinguishable, in fact, from the exact
            # fullscreen-close scenario the branch above now deliberately
            # never reaches this method for. Report-only: log the
            # disagreement and leave `_hidden_to_tray` False, so
            # rendering continues into a window that might genuinely
            # still be visible (R7.6) — the strictly safer failure
            # mode, and the one that would have made round 6's bug
            # VISIBLE (a window rendering fine, just not hidden as
            # expected) instead of silently wrong (a window marked
            # hidden while the app stopped updating it).
            logger.warning(
                "Window still exposed at the platform level after "
                "hide() -- _hidden_to_tray left False."
            )
        except RuntimeError:
            return

    # Roadmap item 116 (round 8, §14.3.2) — one reschedule only: the
    # fullscreen-exit-and-close animation is a one-shot transition, not
    # an open-ended wait; if it hasn't finished by the second check,
    # something else is going on and this stops trying rather than
    # polling forever.
    _DOCK_ICON_POLICY_CHECK_MAX_ATTEMPTS = 2

    def _schedule_dock_icon_policy_check_after_fullscreen_close(
            self, request_id: int, attempt: int = 1,
    ) -> None:
        QTimer.singleShot(
            self._HIDE_TO_TRAY_VERIFY_DELAY_MS,
            lambda: self._check_dock_icon_policy_after_fullscreen_close(
                request_id, attempt,
            ),
        )

    def _check_dock_icon_policy_after_fullscreen_close(
            self, request_id: int, attempt: int,
    ) -> None:
        # Mirrors `_check_hidden_to_tray`'s own RuntimeError-on-a-
        # deleted-Qt-object handling — same reasoning, same boundary.
        try:
            if request_id != self._hide_request_id:
                # Stale — a reopen has happened since this was
                # scheduled. See `_hide_request_id`'s own comment.
                return

            if not self._is_exposed_at_platform_level():
                if self._host.tray.is_icon_visible():
                    _set_dock_icon_visible(False)
                return

            if attempt >= self._DOCK_ICON_POLICY_CHECK_MAX_ATTEMPTS:
                # The animation is still playing well past what this
                # class expected — give up rather than poll forever.
                # No corrective ACTION is being skipped here (this
                # check never took one), only a further check.
                return

            self._schedule_dock_icon_policy_check_after_fullscreen_close(
                request_id, attempt + 1,
            )
        except RuntimeError:
            return

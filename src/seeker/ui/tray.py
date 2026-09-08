"""Tray icon, menu, and notifications — round 8 Phase 6 (§9.3.2).

Moved verbatim off MainWindow, **except** `closeEvent` and the
hide-to-tray verification (`_confirm_hidden_to_tray`,
`_is_exposed_at_platform_level`, `_check_hidden_to_tray`,
`_hide_request_id`, plus the two dock-icon-policy-after-fullscreen-close
methods, which share that same staying state) — that logic is round 7's
E1, it is genuinely subtle, and it is about the *window*, not the tray.
Those stay on MainWindow; see its own module docstring / §9.3.2.

`_show_tray_hide_notice_once` moved here despite being called from the
staying `closeEvent` — it only ever shows a tray notification message,
which is squarely this module's own concern, not verification logic.
MainWindow reaches it through `TrayController.show_hide_notice_once()`.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect, Qt, QThreadPool
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QSystemTrayIcon

from seeker.application import Application
from seeker.models.history_event import DOWNLOADED, HistoryEvent
from seeker.ui.workers import run_worker

# Roadmap item R7.5 — an unreachable slskd must not emit a tray
# notification on every 20s backend-poll error; untuned, same
# "reasonable starting guess" convention as every other threshold here.
ERROR_NOTIFICATION_COOLDOWN_SECONDS = 300.0


@dataclass(frozen=True)
class TrayHost:
    """What the tray needs from the shell beyond its own state. Same
    "grep every method being moved for what it actually touches"
    methodology as DashboardHost/ReviewHost/TaggingPanelHost.

    `application`/`thread_pool`/`window` are real, stable references
    (never reassigned) — same direct-reference treatment PageContext
    already gives `application`/`thread_pool` and ReviewHost gives
    `status_label`. `window` is used only for the handful of genuinely
    generic QMainWindow operations reopening needs (showNormal/raise_/
    activateWindow/isVisible/setGeometry) — not as a back door to
    MainWindow's own private state.

    `get_hidden_to_tray`/`set_hidden_to_tray`/`bump_hide_request_id`/
    `get_pre_fullscreen_geometry`/`clear_pre_fullscreen_geometry` are
    genuinely shared mutable state with MainWindow's own closeEvent and
    hide-to-tray verification (staying there per this module's own
    docstring) — get/set callables, not values captured once, since
    both sides read AND write them. Same shape as PageContext's own
    `is_hidden_to_tray`.

    `set_dock_icon_visible` is a real seam, not just style: routed
    through a MainWindow method (bound at construction, resolved by
    name at call time against main_window.py's own module globals)
    rather than this module calling its own `_set_dock_icon_visible`
    import directly, because test_ui_smoke.py's
    `test_reopen_restores_the_dock_icon_before_showing` monkeypatches
    `main_window_module._set_dock_icon_visible` — a patch that can only
    intercept a call whose bare-name lookup happens in that module's
    own namespace. Confirmed live: without this indirection the call
    executes in tray.py's namespace instead and the test's patch never
    fires.
    """
    application: Application
    thread_pool: QThreadPool
    window: QMainWindow
    navigate: Callable[[str], None]
    render_activity_strip: Callable[[], None]
    set_dock_icon_visible: Callable[[bool], None]
    trigger_backend_poll: Callable[[], None]
    poll_selected_playlist: Callable[[], None]
    poll_active_downloads: Callable[[], None]
    poll_review_items: Callable[[], None]
    poll_next_step: Callable[[], None]
    get_hidden_to_tray: Callable[[], bool]
    set_hidden_to_tray: Callable[[bool], None]
    bump_hide_request_id: Callable[[], None]
    get_pre_fullscreen_geometry: Callable[[], QRect | None]
    clear_pre_fullscreen_geometry: Callable[[], None]
    needs_review_count: Callable[[], int]
    pending_upgrades_count: Callable[[], int]
    active_downloads_count: Callable[[], int]


class TrayController:
    def __init__(self, host: TrayHost) -> None:
        self._host = host
        # R7.5 — de-duplicates "N item(s) need your decision" so it
        # only fires on a genuine INCREASE, never every poll tick the
        # count happens to still be positive.
        self._last_notified_review_count = 0
        # R7.5 — the newest HistoryEvent.occurred_at already accounted
        # for, seeded once (silently, no notification) right after
        # construction so pre-existing history never floods a first
        # notification the moment the tray icon appears.
        self._last_notified_download_at: str | None = None
        self._last_error_notification_at: float | None = None

        self._tray_icon: QSystemTrayIcon | None = None
        self._build_tray_icon()

    def is_icon_visible(self) -> bool:
        return self._tray_icon is not None and self._tray_icon.isVisible()

    def hide_icon(self) -> None:
        if self._tray_icon is not None:
            self._tray_icon.hide()

    # --- Roadmap item R7: run in the background from the macOS menu bar ----

    def _build_tray_icon(self) -> None:
        # R7.2 — guarded on real availability; a platform/session with
        # no tray (this app's own offscreen test environment included —
        # confirmed live, not assumed: QSystemTrayIcon.
        # isSystemTrayAvailable() reports False under QT_QPA_PLATFORM=
        # offscreen) falls back to today's ordinary quit-on-close
        # behavior untouched — closeEvent below checks self._tray_icon
        # is not None before doing anything different.
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = None
            return

        icon_path = _resolve_tray_icon_path()
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        # macOS "template image" convention — a monochrome glyph whose
        # alpha channel Qt/AppKit recolor automatically for the current
        # menu bar appearance (light/dark), instead of showing a fixed-
        # color icon that can read wrong against either.
        #
        # Roadmap item 98 (B9) — setIsMask(True) against the full-colour
        # app `.icns` (the original approach here) produced a solid
        # filled squircle: setIsMask discards colour and stamps only the
        # ALPHA channel, and the app icon's alpha is one opaque rounded
        # square. `seeker_menubar_Template.png`/`...@2x.png` is a real,
        # derived-not-redrawn template asset instead — reproducible if
        # the app icon ever changes: the 1024px `seeker_icon.icns`
        # artwork was thresholded on luminance (a flat background at
        # 13.6 vs. artwork consistently > 30 gave a clean split), the
        # faint background circle dropped, the result cropped to the
        # artwork's own bounding box, the two brow strokes dilated
        # slightly (thin strokes otherwise don't survive an 18px
        # downscale), and the whole thing re-emitted as solid black
        # pixels with the glyph carried entirely in the alpha channel —
        # exactly what a template image is. Checked at real menu-bar
        # size composited against both a light and a dark background
        # before adopting it.
        icon.setIsMask(True)

        self._tray_icon = QSystemTrayIcon(icon, self._host.window)
        self._tray_icon.setToolTip("Seeker")

        # Roadmap item E1 (round 7, corrected after review) — the real
        # invariant is "a window with a live tray icon to reopen from
        # must never be deleted on close," which belongs HERE, where
        # that tray icon is created (once, for the life of the
        # session), not inside one specific close branch. `WA_
        # DeleteOnClose` (set at construction — see its own comment
        # there) was written back when this window's only real close
        # happened once, at app exit; every close path that reaches
        # `event.ignore()` first (the ordinary hide-to-tray path) never
        # actually triggers it regardless, but the fullscreen-close
        # path (E1.2) deliberately lets a real close complete — with
        # this attribute still set, Qt would schedule the actual C++
        # object for deletion right after, silently breaking `_on_tray_
        # open_seeker` (and this tray icon/menu) the next time the user
        # tries to reopen. Clearing it here, the moment a tray icon
        # exists, covers every current and future close path that
        # reaches this point with a tray present — not just the one
        # branch that happened to need it first.
        self._host.window.setAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose, False
        )

        menu = QMenu()

        self._tray_status_action = menu.addAction("Idle")
        self._tray_status_action.setEnabled(False)
        menu.addSeparator()

        self._tray_pause_action = menu.addAction("Pause downloads")
        self._tray_pause_action.setCheckable(True)
        self._tray_pause_action.setChecked(self._host.application.downloads_paused)
        self._tray_pause_action.toggled.connect(self._on_tray_pause_toggled)

        self._tray_review_action = menu.addAction("Review")
        self._tray_review_action.triggered.connect(
            lambda: self._on_tray_open_page("review")
        )
        self._tray_upgrades_action = menu.addAction("Upgrades")
        self._tray_upgrades_action.triggered.connect(
            lambda: self._on_tray_open_page("review")
        )
        menu.addSeparator()

        # Roadmap item 98 (B9.5) — "Check now" was ambiguous with Help
        # menu's "Check for updates…" (a completely different action —
        # this one triggers an immediate slskd download/upload status
        # poll, not an app-update check). Renamed plainly, with a
        # tooltip, so the two "check"s can't be confused.
        check_now_action = menu.addAction("Check downloads now")
        check_now_action.setToolTip(
            "Refresh download/upload status immediately, instead of "
            "waiting for the next automatic check."
        )
        check_now_action.triggered.connect(self._on_tray_check_now)
        open_action = menu.addAction("Open Seeker")
        open_action.triggered.connect(self._on_tray_open_seeker)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._on_tray_quit)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_icon_activated)
        self._tray_icon.show()

    def _on_tray_icon_activated(
            self,
            reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        # Roadmap item D5 (round 6) — this comment used to assert, with
        # no recorded observation behind it, that macOS routes a
        # left-click straight to the context menu and Trigger never
        # fires there. A real user's report (confirmed live: a single
        # left-click on the menu bar icon both opened the context menu
        # AND restored the window) is direct evidence that's false on
        # PySide6 6.11/macOS — the exact "confident, unverified platform
        # claim" failure mode this project has now hit twice (see
        # CLAUDE.md's own standing convention on comments like this).
        # Handled explicitly instead of assumed away: Trigger is skipped
        # outright on macOS, so a left-click does only what AppKit
        # already does with it (open the context menu) and nothing
        # else — matching how an ordinary macOS menu bar extra behaves.
        # Windows/Linux keep the original behavior, where Trigger is the
        # only signal a left-click produces at all.
        if sys.platform == "darwin":
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_tray_open_seeker()

    def _on_tray_pause_toggled(self, checked: bool) -> None:
        self._host.application.set_downloads_paused(checked)
        self._render_tray_menu()

    def _on_tray_open_page(self, key: str) -> None:
        self._on_tray_open_seeker()
        self._host.navigate(key)

    def _on_tray_check_now(self) -> None:
        self._host.trigger_backend_poll()

    def _on_tray_open_seeker(self) -> None:
        # Roadmap item E1.4 (round 7) — a deliberate reopen invalidates
        # any still-pending hide-verification check (see
        # `_hide_request_id`'s own comment at its declaration) — without
        # this, a check scheduled by an earlier `closeEvent` could still
        # fire after the user has already reopened the window from here,
        # see it legitimately exposed, and hide it right back out from
        # under them.
        self._host.bump_hide_request_id()
        self._host.set_hidden_to_tray(False)
        # Roadmap item 116 (round 8, §14.3.3) — order matters: the
        # window must be shown by an app that is already Regular, or it
        # can come up behind other applications.
        self._host.set_dock_icon_visible(True)
        self._host.window.showNormal()
        # D4.2 — give back the exact window the user had before it was
        # hidden, rather than whatever `showNormal()` alone resolves to
        # after a fullscreen-exit-then-hide cycle.
        pre_fullscreen_geometry = self._host.get_pre_fullscreen_geometry()
        if pre_fullscreen_geometry is not None:
            self._host.window.setGeometry(pre_fullscreen_geometry)
            self._host.clear_pre_fullscreen_geometry()
        self._host.window.raise_()
        self._host.window.activateWindow()
        # Roadmap item R7.6 — the poll methods skip their own work
        # while hidden; catch up immediately on reopen rather than
        # waiting up to POLL_INTERVAL_MS for the next tick to notice
        # the window is visible again.
        self._host.poll_selected_playlist()
        self._host.poll_active_downloads()
        self._host.poll_review_items()
        self._host.poll_next_step()
        self._host.render_activity_strip()

    def on_application_state_changed(
            self, state: Qt.ApplicationState,
    ) -> None:
        # Roadmap item 116 (round 8, §14.2) — see the connection's own
        # comment in MainWindow.__init__ for why this signal exists at
        # all. Two things about this guard, both deliberate:
        #
        # ApplicationActive is not reopen-specific — it also fires on
        # ordinary activation (Cmd-Tab, clicking a window), and because
        # Qt passes forcePropagate=true it fires even when the state was
        # already Active. `not self._host.window.isVisible()` narrows it
        # to the case that matters; in every other case `_on_tray_
        # open_seeker()` would have been a near-no-op anyway.
        #
        # Guards on `isVisible()`, not `_hidden_to_tray` — that flag is
        # deliberately not set True until `_check_hidden_to_tray`
        # confirms the hide at the platform level
        # (`_HIDE_TO_TRAY_VERIFY_DELAY_MS` later), so on the ordinary
        # hide path it stays False for that whole window. A user who
        # closes the window and immediately clicks the Dock icon must
        # still get it back; gating on `_hidden_to_tray` would ignore
        # them for the first `_HIDE_TO_TRAY_VERIFY_DELAY_MS`.
        #
        # This proves the HANDLER's own contract (a hidden window comes
        # back on ApplicationActive) — it does not and cannot prove a
        # real Dock click reaches it, which no headless test can. See
        # this item's own real-desktop verification checklist.
        if state != Qt.ApplicationState.ApplicationActive:
            return
        if self._host.window.isVisible():
            return
        self._on_tray_open_seeker()

    def _on_tray_quit(self) -> None:
        # Roadmap item R7.7 — a real quit request, same as ⌘Q/dock
        # "Quit Seeker". Goes straight to QApplication.quit() (posts a
        # real quit event) rather than self.close() — close() would
        # re-enter this window's own closeEvent, which hides to the
        # tray instead of quitting, exactly the behavior a Quit click
        # must bypass. The actual cleanup lives in MainWindow's own
        # cleanup_before_quit(), connected once to QApplication.
        # aboutToQuit in main_ui.py, so it fires for every real quit
        # route uniformly, not just this one.
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _render_tray_menu(self) -> None:
        if self._tray_icon is None:
            return

        parts = []
        active_downloads_count = self._host.active_downloads_count()
        if active_downloads_count > 0:
            plural = "s" if active_downloads_count != 1 else ""
            parts.append(f"{active_downloads_count} downloading{plural}")

        status_text = ", ".join(parts) if parts else "Idle"

        if self._host.application.downloads_paused:
            status_text += " (paused)"

        self._tray_status_action.setText(status_text)
        needs_review_count = self._host.needs_review_count()
        self._tray_review_action.setText(
            f"Review ({needs_review_count})"
            if needs_review_count else "Review"
        )
        pending_upgrades_count = self._host.pending_upgrades_count()
        self._tray_upgrades_action.setText(
            f"Upgrades ({pending_upgrades_count})"
            if pending_upgrades_count else "Upgrades"
        )

        # Mirrors the config store, not local UI state — a pause
        # toggled from elsewhere (a future Settings/Dashboard control)
        # must still show correctly here without this menu having
        # caused it. blockSignals so re-syncing the checked state
        # can't itself re-trigger _on_tray_pause_toggled's own save.
        self._tray_pause_action.blockSignals(True)
        self._tray_pause_action.setChecked(self._host.application.downloads_paused)
        self._tray_pause_action.blockSignals(False)

    def show_hide_notice_once(self) -> None:
        # Roadmap item E1 (round 7, corrected after review) — was
        # duplicated (the fullscreen branch and the ordinary hide path
        # in closeEvent each had their own copy of this, including the
        # user-facing string) — the exact "two implementations of one
        # behavior" shape this project's own CLAUDE.md already warns
        # about (item 104/C3's Dashboard-vs-Downloads progress bar).
        assert self._tray_icon is not None
        if self._host.application.settings.tray_hide_notice_shown:
            return
        self._tray_icon.showMessage(
            "Seeker",
            "Seeker is still running in the menu bar. Use the menu "
            "bar icon to reopen it, or Quit from there to exit.",
            QSystemTrayIcon.MessageIcon.Information,
        )
        self._host.application.mark_tray_hide_notice_shown()

    def seed_notification_cutoff(self) -> None:
        # Roadmap item R7.5 — silently records the newest existing
        # HistoryEvent so pre-existing download history never floods a
        # notification the instant the tray icon appears; only a
        # DOWNLOADED event with a NEWER occurred_at than this counts as
        # "new" from here on (get_recent_events sorts newest-first).
        run_worker(
            self._host.thread_pool,
            lambda: self._host.application.history_service.get_recent_events(
                limit=1
            ),
            on_finished=self._on_notification_cutoff_seeded,
        )

    def _on_notification_cutoff_seeded(
            self,
            events: list[HistoryEvent],
    ) -> None:
        if events:
            self._last_notified_download_at = events[0].occurred_at

    def check_for_download_notifications(self) -> None:
        # Roadmap item R7.5 — batched per playlist, built from
        # HistoryService's own existing derived DOWNLOADED events (item
        # 54), not a new source of truth; runs on the real 20s backend-
        # poll cycle (the only cycle that can actually produce a newly-
        # completed download), never its own timer.
        if self._tray_icon is None:
            return

        if not self._host.application.settings.notify_downloads_finished:
            return

        if self._last_notified_download_at is None:
            # Seeding hasn't completed yet (or found nothing) — skip
            # this cycle rather than risk treating all of history as
            # "new" the moment it does land.
            return

        run_worker(
            self._host.thread_pool,
            lambda: self._host.application.history_service.get_recent_events(
                limit=50
            ),
            on_finished=self._on_download_notification_events,
        )

    def _on_download_notification_events(
            self,
            events: list[HistoryEvent],
    ) -> None:
        cutoff = self._last_notified_download_at
        assert cutoff is not None

        new_events = [
            event for event in events
            if event.occurred_at > cutoff and event.event_type == DOWNLOADED
        ]

        if new_events and self._tray_icon is not None:
            counts_by_playlist: dict[str, int] = {}
            for event in new_events:
                counts_by_playlist[event.playlist_name] = (
                    counts_by_playlist.get(event.playlist_name, 0) + 1
                )

            message = "\n".join(
                f"{playlist}: {count} track{'s' if count != 1 else ''} "
                f"downloaded"
                for playlist, count in counts_by_playlist.items()
            )
            self._tray_icon.showMessage(
                "Seeker", message, QSystemTrayIcon.MessageIcon.Information,
            )

        if events:
            self._last_notified_download_at = events[0].occurred_at

    def check_for_needs_decision_notification(self, total: int) -> None:
        # Roadmap item R7.5 — fires only on a genuine INCREASE from the
        # last-seen total, never on every poll tick the count happens
        # to still be positive (that would notify every 2s for as long
        # as anything sits unreviewed).
        if (
                self._tray_icon is not None
                and self._host.application.settings.notify_needs_decision
                and total > self._last_notified_review_count
        ):
            plural = "s" if total != 1 else ""
            self._tray_icon.showMessage(
                "Seeker",
                f"{total} item{plural} need your decision on the Review "
                f"page.",
                QSystemTrayIcon.MessageIcon.Information,
            )

        self._last_notified_review_count = total

    def notify_error(self, message: str) -> None:
        # Roadmap item R7.5 — rate-limited so an unreachable slskd
        # can't emit a notification every single 20s backend-poll tick.
        if self._tray_icon is None:
            return

        if not self._host.application.settings.notify_errors:
            return

        now = time.monotonic()

        if (
                self._last_error_notification_at is not None
                and now - self._last_error_notification_at
                < ERROR_NOTIFICATION_COOLDOWN_SECONDS
        ):
            return

        self._last_error_notification_at = now
        self._tray_icon.showMessage(
            "Seeker", message, QSystemTrayIcon.MessageIcon.Warning,
        )


def _resolve_tray_icon_path() -> Path:
    """Roadmap item R7.2/98 (B9.1) — same sys.frozen/sys._MEIPASS branch
    as docker_setup.py's compose_file_path(): an ordinary `uv run
    seeker-ui` dev run resolves against this file's own real location
    in the source tree; a packaged build resolves against the
    icons/ directory seeker.spec bundles as a real PyInstaller `datas`
    entry (this file previously only fed EXE()/BUNDLE()'s own icon= at
    BUILD time — nothing made it available to the running process at
    runtime, which would have left a real packaged build's tray icon
    blank).

    Points at the real template asset (`seeker_menubar_Template.png` —
    Qt auto-picks up `...@2x.png` via its own high-DPI file
    convention), not the full-colour app `.icns` — see B9's own
    CLAUDE.md entry for why setIsMask(True) on the app icon produced a
    solid filled squircle instead of a legible glyph. The `.icns` stays
    the app/Dock icon (BUNDLE()'s own icon= in seeker.spec), unaffected
    by this."""
    if not getattr(sys, "frozen", False):
        return (
            Path(__file__).resolve().parent.parent.parent.parent
            / "packaging" / "icons" / "seeker_menubar_Template.png"
        )

    return Path(sys._MEIPASS) / "icons" / "seeker_menubar_Template.png"  # type: ignore[attr-defined]


def _set_dock_icon_visible(visible: bool) -> None:
    """Roadmap item 116 (round 8, §14.3) — the Dock icon while hidden to
    the menu bar. No-op off macOS. The mechanism is NSApplication's own
    activation policy: Regular (Dock icon + menu bar) while the window
    is up, Accessory (menu bar extra only, no Dock icon) while it's
    hidden.

    Deliberately NOT `LSUIElement` in the Info.plist, which is what
    Apple's own DTS engineers recommend when asked this: `Accessory`/
    `LSUIElement` means no Dock icon AND NO MENU BAR, ever — including
    while the window is open and in use, which would take the Help
    menu, the application menu, and Cmd-Q with it. Switching the policy
    at runtime gives exactly the described behavior instead: icon while
    the window is up, none while it's not.

    This is still a platform claim, and this project has been wrong
    about confident unverified platform claims twice already (see
    CLAUDE.md's own standing convention). Programmatic
    setActivationPolicy_() calls around NSApplicationMain at LAUNCH
    have reported real flakiness (icons lingering, or flashing before
    disappearing) per Apple's own developer forums — the reasoning for
    calling it here instead, at runtime, on the main thread, in
    response to a window closing/reopening, is that this is a
    materially different situation and the pattern menu-bar apps
    normally use — but verify live before trusting a comment that says
    it works.
    """
    if sys.platform != "darwin":
        return

    # Deferred import is deliberate — matches how this project's other
    # genuine heavy/platform-only dependency deferrals are already
    # scoped (docker_setup.py's TokenStore-inside-_load_token,
    # auth_manager.py's webbrowser-inside-_authorize).
    from AppKit import (  # noqa: PLC0415
        NSApp,
        NSApplicationActivationPolicyAccessory,
        NSApplicationActivationPolicyRegular,
    )

    # Real, confirmed-live gap, not a defensive-for-nothing check:
    # NSApp() returns None under this project's own offscreen test
    # platform (no real NSApplication is ever created there), and
    # nothing guarantees a real Cocoa NSApplication has been created by
    # the moment this runs in every possible caller order either.
    app = NSApp()
    if app is None:
        return

    app.setActivationPolicy_(
        NSApplicationActivationPolicyRegular if visible
        else NSApplicationActivationPolicyAccessory
    )

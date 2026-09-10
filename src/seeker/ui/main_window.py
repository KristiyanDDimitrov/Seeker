import base64
import logging
import math
import sys
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QThreadPool,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.models.library_location import LibraryLocation
from seeker.ui import help_text, theme
from seeker.ui.busy_actions import BusyActionRegistry
from seeker.ui.dialogs import (
    AboutDialog,
    DestinationDialog,
)
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.dashboard_page import (
    DashboardHost,
    DashboardPage,
    # Roadmap item 9.3 (round 8, Phase 6) — both moved to
    # dashboard_page.py with the rest of Dashboard, but
    # tests/test_next_step.py imports both from THIS module's own
    # namespace (same re-export shape as the Bulk*Dialogs above) —
    # neither is used directly below any more since S11.4 deleted the
    # delegating _render_next_step stub that used to need the type
    # annotation.
    _decide_next_step,  # noqa: F401
    _NextStepFacts,  # noqa: F401
)
from seeker.ui.pages.downloads_page import DownloadsPage
from seeker.ui.pages.duplicates_page import DuplicatesPage
from seeker.ui.pages.history_page import HistoryPage
from seeker.ui.pages.library_page import LibraryHost, LibraryPage
from seeker.ui.pages.review_page import (
    ReviewHost,
    ReviewPage,
)
from seeker.ui.pages.search_page import SearchPage
from seeker.ui.pages.sharing_page import SharingPage
from seeker.ui.pages.static_pages import HelpPage, SupportPage
from seeker.ui.settings_window import SettingsPage
from seeker.ui.tray import (
    TrayController,
    TrayHost,
    _set_dock_icon_visible,
)
from seeker.ui.workers import run_worker
from seeker.update_check import UpdateCheckResult, UpdateStatus, check_for_update

logger = logging.getLogger(__name__)


# Untuned constant — matches the ~2s cadence already observed against
# real slskd elsewhere in this project (see CLAUDE.md); revisit once
# real usage data exists, same convention as every other threshold here.
POLL_INTERVAL_MS = 2_000

# Untuned constant — this timer makes real network calls to slskd (via
# poll_downloads()), so it deliberately runs far less often than the
# local-DB-only display refresh above. 15-30s starting range per the
# task brief; revisit once real usage data exists.
BACKEND_POLL_INTERVAL_MS = 20_000

# Untuned constant — a fixed sidebar width narrow enough to leave real
# room for content, wide enough that "Duplicates" (the longest nav
# label) never wraps or clips.
SIDEBAR_WIDTH = 200

# key -> (nav label, page title). One source of truth for both the
# sidebar button text (via _update_nav_badge, which appends a live
# count to the label half) and the page header's own title — a nav
# label and its page title only ever differ if a future page wants
# them to (none do yet).
_NAV_PAGES = (
    ("dashboard", "Dashboard"),
    ("library", "Library"),
    ("search", "Search"),
    ("downloads", "Downloads"),
    ("review", "Review"),
    ("duplicates", "Duplicates"),
    ("sharing", "Sharing"),
    ("history", "History"),
)

# Roadmap item 65 (Phase 2.2) — human-readable label for each
# busy_actions key, shown on the global activity strip. Any key with no
# entry here falls back to a generic "Working…" rather than a raw key
# string leaking into the UI.
_BUSY_ACTION_LABELS: dict[str, str] = {
    "sync": "Refreshing playlists…",
    "scan": "Scanning library and matching tracks…",
    "match": "Re-matching library…",
    "download": "Requesting downloads…",
    "sync_tracks": "Loading tracks…",
    "tag_selected": "Tagging selected tracks…",
    "tag_playlist": "Tagging playlist…",
    "compute_fingerprints": "Computing fingerprints…",
    "find_duplicates": "Searching for duplicates…",
    "sharing_refresh": "Checking sharing status…",
    "history_refresh": "Loading history…",
    "search_manual": "Searching SoulSeek…",
    "download_manual": "Requesting download…",
}


_THEME_MODE_LABELS = {
    "system": "Follow system",
    "light": "Light",
    "dark": "Dark",
}
_THEME_MODE_CYCLE = ("system", "light", "dark")


class _ThemeToggleButton(QPushButton):
    """Roadmap item C5.10 (round 5) — a conventional sun/moon/split-
    circle glyph set, drawn with `QPainter` rather than shipped as SVG/
    PNG assets, so it's resolution-independent and tints with the
    active palette for free (reads `theme.TEXT_MUTED` fresh on every
    paint — this widget draws its own glyph rather than using a
    palette-driven QSS icon).

    A logo-derived glyph (one eye from the mark, solid/outlined/half-
    filled per mode) was tried first and rejected: at real sidebar
    size the eye shape is a flat sliver whose outline carries no eye
    identity, and a half-fill reads as a broken shape, not a state —
    inspected at real size on both grounds before deciding against it.
    A three-state control with no label is otherwise a guess, so the
    tooltip always names the mode in words; the icon alone shows
    which of the three is CURRENT, not a boolean on/off.
    """

    def __init__(self, mode: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(28, 28)
        # Roadmap item E3.6 (round 7) — a selector-less setStyleSheet()
        # string is the exact mechanism item E3 found stripping borders
        # off a QProgressBar's track (Qt parses it as a universal `*`
        # rule). This button paints its own glyph with no children, so
        # there was never anything for it to cascade onto — but scoped
        # via objectName anyway, so the new ui-wide regression test
        # (theme.py's own selector-less-setStyleSheet sweep) can't be
        # tripped by a control that happens to be safe today only
        # because it's childless.
        self.setObjectName("themeToggleButton")
        self._mode = mode
        self._update_tooltip()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._update_tooltip()
        self.update()

    def _update_tooltip(self) -> None:
        label = _THEME_MODE_LABELS.get(self._mode, self._mode)
        self.setToolTip(f"Theme: {label} (click to change)")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height()) - 8
        rect = QRectF(
            (self.width() - side) / 2, (self.height() - side) / 2,
            side, side,
        )
        pen_color = QColor(theme.TEXT_MUTED)
        pen = painter.pen()
        pen.setColor(pen_color)
        pen.setWidthF(max(1.5, side * 0.09))
        painter.setPen(pen)

        if self._mode == "light":
            self._paint_sun(painter, rect)
        elif self._mode == "dark":
            self._paint_moon(painter, rect)
        else:
            self._paint_split_circle(painter, rect, pen_color)
        painter.end()

    def _paint_sun(self, painter: QPainter, rect: QRectF) -> None:
        core = rect.adjusted(
            rect.width() * 0.28, rect.height() * 0.28,
            -rect.width() * 0.28, -rect.height() * 0.28,
        )
        painter.setBrush(painter.pen().color())
        painter.drawEllipse(core)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        center = rect.center()
        radius = rect.width() / 2
        for i in range(8):
            angle = i * math.pi / 4
            p1 = QPointF(
                center.x() + math.cos(angle) * radius * 0.75,
                center.y() + math.sin(angle) * radius * 0.75,
            )
            p2 = QPointF(
                center.x() + math.cos(angle) * radius,
                center.y() + math.sin(angle) * radius,
            )
            painter.drawLine(p1, p2)

    def _paint_moon(self, painter: QPainter, rect: QRectF) -> None:
        full = QPainterPath()
        full.addEllipse(rect)
        cutout = QPainterPath()
        offset = rect.width() * 0.32
        cutout.addEllipse(rect.translated(offset, -offset * 0.4))
        crescent = full.subtracted(cutout)
        painter.setBrush(painter.pen().color())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(crescent)

    def _paint_split_circle(
            self, painter: QPainter, rect: QRectF, pen_color: QColor,
    ) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect)
        # Right half filled (the "on" side), left half left as an
        # outline only — reads as a real half-filled circle, the
        # conventional "system/auto" glyph.
        half = QPainterPath()
        half.moveTo(rect.center())
        half.arcTo(rect, 90, 180)
        half.closeSubpath()
        painter.setBrush(pen_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(half)


def _build_nav_button(label: str) -> QPushButton:
    # A checkable, flat QPushButton rather than a bespoke widget —
    # QPushButton is already painted through Qt's style system (unlike
    # a plain QWidget, which needs WA_StyledBackground — see notice.py/
    # the sidebar's own comment), so its checked state can be styled
    # directly via the `[navItem="true"]:checked` QSS rule with no
    # extra plumbing. Text-only badge counts (via _update_nav_badge)
    # rather than a separate sibling widget, to keep one exclusive
    # QButtonGroup member per nav item instead of a composite row.
    button = QPushButton(label)
    button.setCheckable(True)
    button.setFlat(True)
    button.setProperty("navItem", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class MainWindow(QMainWindow):
    def __init__(self, application: Application):
        super().__init__()
        # Round 9 §2.3.3 — WA_DeleteOnClose is decided exactly once,
        # entirely inside `TrayController._build_tray_icon()`
        # (ui/tray.py), for BOTH branches (tray available or not): True
        # when no tray icon exists to reopen from (a parentless
        # top-level QMainWindow's close() only hides it by default,
        # never actually destroys it, unless this is set — tests
        # construct and close MainWindow repeatedly and rely on this),
        # False the moment a real tray icon exists (see that method's
        # own comment for why a window with a live tray icon to reopen
        # from must never actually be deleted on close). Previously set
        # True here unconditionally and then conditionally flipped False
        # inside `_build_tray_icon` — a real latent bug (round 9 §2.3):
        # if tray construction ever raised or was skipped, a window
        # still carrying True from here could be destroyed by a stray
        # close, leaving `qt_app.aboutToQuit.connect(window.
        # cleanup_before_quit)` (main_ui.py) bound to a dead object.
        # Not the reported §2.3 hang (a tray icon clearly existed there)
        # but worth closing regardless — one decision, one place, both
        # branches covered unconditionally.
        self.application = application
        self.thread_pool = QThreadPool()
        # Roadmap item 65 (Phase 2.1) — the single source of truth for
        # "is this named action currently running," consulted by every
        # poll-driven render method so it can skip a button whose own
        # action is still in flight instead of fighting run_worker's own
        # busy-disable (the proven mechanism behind Phase 0's 0.1 bug).
        self.busy_actions = BusyActionRegistry()
        # Roadmap item 65 (Phase 2.2/2.3) — keyed the same as
        # busy_actions; populated by a run_worker(on_progress=...)
        # callback (via _on_activity_progress), consulted by
        # _render_activity_strip. Empty for every action wired in Phase
        # 2 itself — Phase 7's fingerprinting/duplicate-search progress
        # is the first real producer.
        self._activity_progress: dict[str, tuple[str, int, int]] = {}
        self._backend_poll_in_progress = False
        # Roadmap item R7 — menu-bar background operation. The tray
        # menu's own status line and "Review (N)"/"Upgrades (N)" items
        # read `self._review_page._needs_review_count`/
        # `_pending_upgrades_count` directly (their own delegating
        # properties deleted at the test-split session, S11.5, §9.3.4)
        # — real ReviewPage state (round 8 Phase 6), built from data
        # its own poll already fetches, never a third source of truth
        # (R7.3's own explicit instruction). `_pending_review_focus_track_id`/
        # `selected_playlist`/`_current_track_statuses`/the next-step
        # dismissal keys all moved to page modules with the rest of
        # their own pages the same way. The downloading count itself
        # lives on DownloadsPage; read via `self._downloads_page.
        # active_downloads_count` directly (its own delegating property
        # was deleted at the test-split session, S11.3, §9.3.4).
        # R7.1 — set once the window is genuinely hidden-to-tray
        # (closeEvent), not just "not the active window"; R7.6 reads
        # this to skip re-render work while nobody can see it.
        self._hidden_to_tray = False
        # Roadmap item E1 (round 7) — captured in `closeEvent` before a
        # fullscreen window is allowed to close for real, so `_on_tray_
        # open_seeker` can restore the pre-fullscreen size/position
        # instead of whatever a bare reopen resolves to.
        self._pre_fullscreen_geometry: QRect | None = None
        # Roadmap item E1.4 (round 7, corrected after a second review) —
        # a monotonic counter, bumped on every hide-to-tray attempt AND
        # every deliberate reopen (`_on_tray_open_seeker`). A delayed
        # verification check captures this value when scheduled and
        # bails if it no longer matches by the time the timer fires —
        # otherwise a stale check landing after the user has ALREADY
        # reopened the window (a single tray-menu click within the
        # verify delay) would see the platform window legitimately
        # exposed, conclude the hide "didn't take," and hide the window
        # right back out from under the user with no explanation. A
        # stale check must never act.
        self._hide_request_id = 0

        # Roadmap item C5 (round 5) — the persisted mode ("system" by
        # default); the real resolved Palette is already active by the
        # time MainWindow is constructed (main_ui.py's own
        # apply_theme() call happens before any window exists). Read
        # here, before _build_ui(), so _build_sidebar() can hand the
        # theme toggle its real starting icon rather than a guess.
        self._theme_mode = application.theme_mode
        self._system_scheme_connected = False
        # Roadmap item D2 (round 6) — re-entrancy guard: `apply_theme`'s
        # own `setColorScheme()` call emits `colorSchemeChanged`, and
        # while mode == "system" that signal is connected back to
        # `_on_system_color_scheme_changed` — without this flag, that
        # handler re-enters `_apply_theme_mode` DURING the outer call's
        # own `theme.apply_theme()`, re-resolving and re-applying the
        # system palette before the outer call's chosen mode ever gets
        # to apply its own stylesheet. See `_apply_theme_mode` for the
        # full fix (D2.2/D2.3).
        self._applying_theme = False

        # Roadmap item 9.3.2/9.3.3 (round 8, Phase 6) — the tray/
        # notification group, extracted to ui/tray.py; its own seam
        # construction is verbose enough (many callables — see
        # TrayHost's own docstring for why) that it belongs in a
        # dedicated builder, the same shape __init__ already uses for
        # _build_ui()/_build_sidebar()/_build_help_menu(), rather than
        # inline here.
        self._tray = self._build_tray_controller()

        # Roadmap item 116 (round 8, §14.2) — macOS routes every
        # "reopen a running app" gesture (Dock icon click, double-click
        # in Finder/Applications, Spotlight, `open -a Seeker`) through
        # NSApplicationDelegate's own applicationShouldHandleReopen:
        # hasVisibleWindows:. Qt's Cocoa platform plugin handles that
        # selector itself by emitting exactly this signal
        # (Qt::ApplicationActive, forcePropagate=true so it fires even
        # when the state is already Active) and returning YES — it
        # never shows a window on its own. Showing one is this
        # application's job; this signal is the only notification it
        # gets. A connection to a GLOBAL object (QApplication), not this
        # window, so it must be torn down explicitly in
        # cleanup_before_quit — same shape as _system_scheme_connected
        # just above.
        #
        # Gated on a real tray icon existing: with none (self._tray.
        # _tray_icon is None), closeEvent takes the ordinary real-close path
        # (super().closeEvent()) rather than hiding — there is no
        # "hidden but still running" state for a reopen gesture to ever
        # need to restore, so connecting here would be pure overhead
        # (and, in this project's own offscreen test suite, needless
        # extra exposure to a real, confirmed-live subtlety: this
        # signal DOES fire organically from ordinary show()/close()
        # calls even under QT_QPA_PLATFORM=offscreen, unlike
        # colorSchemeChanged — see conftest.py's own
        # _flush_deferred_widget_deletion for the full story).
        app = QApplication.instance()
        self._app_state_connected = False
        if app is not None and self._tray._tray_icon is not None:
            # applicationStateChanged is a QGuiApplication signal;
            # QApplication.instance()'s declared return type is the
            # narrower QCoreApplication — real at runtime (this app
            # always constructs a QApplication, itself a QGuiApplication
            # subclass), just not visible to mypy from the stub alone.
            assert isinstance(app, QGuiApplication)
            # Connected to MainWindow's OWN delegating stub
            # (`_on_application_state_changed` below), not
            # `self._tray.on_application_state_changed` directly —
            # confirmed live this is not just style: PySide/Qt only
            # auto-disconnects a signal from a bound method whose
            # `__self__` is a real QObject (this window) when that
            # QObject is destroyed. `TrayController` is a plain Python
            # object, so a direct connection to its method survives a
            # torn-down MainWindow in tests that never call
            # cleanup_before_quit, and a later applicationStateChanged
            # delivery then hits a deleted C++ object
            # (`self._host.window.isVisible()` in tray.py) — a real,
            # reproduced RuntimeError, not a hypothetical one.
            app.applicationStateChanged.connect(
                self._on_application_state_changed
            )
            self._app_state_connected = True

        # Round 9 §2.2 — the one seam both real quit routes pass
        # through. Confirmed live (HISTORY §123): tray.py's
        # `_on_tray_quit()` (`app.quit()`) and the native macOS ⌘Q/Dock
        # "Quit Seeker" menu item both deliver a `QEvent.Type.Quit` to
        # the QApplication instance itself, before `aboutToQuit` fires
        # — `cleanup_before_quit`'s own `aboutToQuit` hook is too late
        # to cancel anything (nothing about a quit already in progress
        # can be undone from there), but an installed event filter can
        # still decide, synchronously, whether THIS Quit event is
        # allowed to proceed: returning `True` from `eventFilter`
        # consumes it and no quit happens at all; returning `False`
        # lets this exact event continue on to `aboutToQuit` unchanged
        # — no QApplication subclass or re-posted `quit()` call needed.
        if app is not None:
            app.installEventFilter(self)

        # Roadmap item 98 (B10) — reversed from item 81 (0.1): a commit
        # SHA in the one string a user reads most often looked like a
        # bug even when it wasn't one. Build identity already has its
        # correct home — Help -> About Seeker (below) already renders
        # GIT_SHA/GIT_DESCRIBE/BUILT_AT — so the title stays the plain
        # app name.
        self.setWindowTitle("Seeker")
        self.resize(1180, 760)
        self.setMinimumSize(960, 640)

        self._build_ui()
        # Round 9 §3.1 — moved from before _build_ui() (round 8 §12.1's
        # original placement). restoreGeometry() ran against a window
        # with no central widget/layout yet; layout activation on first
        # show then resized the window to the layout's own size hint,
        # discarding the restored geometry and landing the user back on
        # something close to the resize() default above — confirmed
        # live as the actual cause of the round-9 report ("reopens at
        # default size, not the size it was closed at"). Qt's own docs
        # for QWidget::restoreGeometry() describe it as reproducing a
        # window's size/position as previously saved; nothing in that
        # contract survives a layout that hasn't been installed yet
        # deciding the size afterward. restoreGeometry() itself still
        # silently no-ops on a missing/corrupt value, leaving whatever
        # _build_ui() left in place, so there's nothing to validate here
        # beyond the base64 decode itself.
        self._restore_window_geometry()

        # Roadmap item C5.6 — subscribes to the OS's own appearance
        # changes when (and only when) the persisted mode is "system",
        # so the app follows the Mac flipping at sunset with no
        # restart. Deliberately after _build_ui(): the toggle/wordmark
        # already exist by now, so a signal firing mid-construction
        # (unlikely, but not impossible) can't reach a half-built UI.
        self._sync_system_scheme_subscription()
        self._dashboard_page._render_no_playlist_selected()
        self._dashboard_page._load_playlists()
        self._downloads_page._poll_active_downloads()
        self._review_page._poll_review_items()
        self._dashboard_page._poll_next_step()
        self._tray.seed_notification_cutoff()

        # DB-polling pattern for live status: rebuild the visible model
        # each tick rather than diffing for minimal repaints — an
        # acceptable v1 simplification, matching this project's habit
        # of shipping a working real version before optimizing.
        #
        # Roadmap item R2 — this tradeoff is now ONLY accepted for pure
        # DISPLAY state (table contents, labels, nav badges), never for
        # user INPUT: a rebuild used to destroy every checkbox/radio in
        # a polled table on every tick, not just "reset one mid-click"
        # as first assumed — a real reported bug, not a theoretical
        # edge case. The Review tab's "delete old file" checkbox and
        # the Duplicates "keep" radio selection now survive a rebuild
        # via a small state map keyed by stable identity (request_id /
        # the group's own member file ids — never row index), restored
        # on render and pruned when the underlying row is gone
        # (`_upgrade_delete_checked`, `_duplicates_keep_selection`). The
        # real long-term fix is diffing rows instead of rebuilding them
        # wholesale; the state map is the honest scoped fix on top of
        # the existing rebuild-every-tick pattern, not a claim that the
        # underlying pattern itself is now safe for any future
        # interactive control added to a polled table without the same
        # treatment.
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._dashboard_page._poll_selected_playlist)
        self.poll_timer.timeout.connect(
            self._downloads_page._poll_active_downloads
        )
        self.poll_timer.timeout.connect(self._review_page._poll_review_items)
        self.poll_timer.timeout.connect(self._dashboard_page._poll_next_step)
        # Roadmap item 65 (Phase 2.2) — a periodic safety-net refresh on
        # top of the explicit begin()/end()-adjacent calls already made
        # at every busy-action call site; catches nothing new today (all
        # of those already call _render_activity_strip() synchronously)
        # but keeps the strip correct even if a future action forgets to.
        self.poll_timer.timeout.connect(self._render_activity_strip)
        # Roadmap item R7.3 — the tray menu's live status line/counts;
        # cheap (reads counts the other poll methods already set, no
        # new DB/network work of its own) so it stays on the fast 2s
        # tick like the rest of this timer's display refresh, not the
        # slow backend one.
        self.poll_timer.timeout.connect(self._tray._render_tray_menu)
        self.poll_timer.start()

        # Separate, slower timer: the only thing in this app that causes
        # poll_downloads() (real slskd network calls) to run without an
        # explicit `seeker downloads status` invocation. poll_downloads()
        # was built with exactly this kind of unattended calling in mind
        # (no input() anywhere — see CLAUDE.md's guardrail tests), so
        # this is safe to fire on a bare timer with no user interaction.
        self.backend_poll_timer = QTimer(self)
        self.backend_poll_timer.setInterval(BACKEND_POLL_INTERVAL_MS)
        self.backend_poll_timer.timeout.connect(self._trigger_backend_poll)
        self.backend_poll_timer.timeout.connect(
            self._sharing_page._trigger_sharing_poll
        )
        self.backend_poll_timer.start()

    def _build_tray_controller(self) -> TrayController:
        # Roadmap item 9.3.2 (round 8, Phase 6) — the tray/notification
        # group, extracted to ui/tray.py. `window`/`poll_*`/`navigate`/
        # `render_activity_strip` are lambdas or bound methods rather
        # than values captured now, since the pages they reach
        # (`_downloads_page`/`_review_page`/`_dashboard_page`) don't
        # exist yet at this point in construction (this runs before
        # _build_ui()) — TrayController only calls them later, on a
        # real reopen. `get_hidden_to_tray`/`set_hidden_to_tray`/
        # `bump_hide_request_id`/`get_pre_fullscreen_geometry`/
        # `clear_pre_fullscreen_geometry` are genuinely shared mutable
        # state with closeEvent/the hide-to-tray verification below
        # (staying on MainWindow — see tray.py's own module docstring
        # for why), same read-through-a-seam shape as PageContext's
        # `is_hidden_to_tray`.
        return TrayController(TrayHost(
            application=self.application,
            thread_pool=self.thread_pool,
            window=self,
            navigate=self._show_page,
            render_activity_strip=self._render_activity_strip,
            set_dock_icon_visible=self._set_dock_icon_visible_policy,
            trigger_backend_poll=self._trigger_backend_poll,
            # Deliberately still lambdas, not bound-method references:
            # `_downloads_page`/`_review_page`/`_dashboard_page` don't
            # exist yet at this point (they're built by _build_ui(),
            # which itself needs self._tray already constructed — see
            # ReviewHost below) — a bound-method reference here would
            # raise immediately, so these stay real lambdas for
            # genuinely deferred attribute lookup, not an unnecessary
            # wrap ruff's PLW0108 would otherwise flag.
            poll_selected_playlist=(
                lambda: self._dashboard_page._poll_selected_playlist()  # noqa: PLW0108
            ),
            poll_active_downloads=(
                lambda: self._downloads_page._poll_active_downloads()  # noqa: PLW0108
            ),
            poll_review_items=(
                lambda: self._review_page._poll_review_items()  # noqa: PLW0108
            ),
            poll_next_step=(
                lambda: self._dashboard_page._poll_next_step()  # noqa: PLW0108
            ),
            get_hidden_to_tray=lambda: self._hidden_to_tray,
            set_hidden_to_tray=self._set_hidden_to_tray,
            bump_hide_request_id=self._bump_hide_request_id,
            get_pre_fullscreen_geometry=lambda: self._pre_fullscreen_geometry,
            clear_pre_fullscreen_geometry=self._clear_pre_fullscreen_geometry,
            needs_review_count=lambda: self._review_page._needs_review_count,
            pending_upgrades_count=(
                lambda: self._review_page._pending_upgrades_count
            ),
            active_downloads_count=(
                lambda: self._downloads_page.active_downloads_count
            ),
        ))

    def _build_ui(self) -> None:
        self._build_view_menu()
        self._build_window_menu()
        self._build_help_menu()

        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        shell_layout.addWidget(self._build_sidebar())

        # Roadmap item 65 (Phase 2.2) — a persistent activity strip
        # lives between the sidebar/header and the page content itself,
        # visible regardless of which page the user has navigated to
        # (button state alone is invisible once you've left the page a
        # long-running action was started from). A separate column
        # rather than widening shell_layout further, so the strip spans
        # only the content area, not the sidebar.
        content_column = QWidget()
        content_column_layout = QVBoxLayout(content_column)
        content_column_layout.setContentsMargins(0, 0, 0, 0)
        content_column_layout.setSpacing(0)

        self.activity_strip = self._build_activity_strip()
        content_column_layout.addWidget(self.activity_strip)

        self.stacked_widget = QStackedWidget()
        content_column_layout.addWidget(self.stacked_widget, 1)

        shell_layout.addWidget(content_column, 1)

        # Roadmap item 9.2 (round 8, Phase 6 prep) — the seam a migrated
        # page gets instead of reaching past it to MainWindow directly.
        # See PageContext's own docstring for why run_busy_worker/
        # update_nav_badge/is_hidden_to_tray/render_activity_strip are
        # here despite not being in the brief's original four-field
        # sketch.
        page_context = PageContext(
            application=self.application,
            thread_pool=self.thread_pool,
            busy_actions=self.busy_actions,
            navigate=self._show_page,
            run_busy_worker=self._run_busy_worker,
            update_nav_badge=self._update_nav_badge,
            is_hidden_to_tray=lambda: self._hidden_to_tray,
            render_activity_strip=self._render_activity_strip,
        )

        self._page_indices: dict[str, int] = {}
        self._dashboard_page = DashboardPage(
            page_context,
            DashboardHost(
                on_download_clicked=self._on_download_clicked,
                on_sync_clicked=self._on_sync_clicked,
                on_scan_clicked=self._on_scan_clicked,
                on_match_clicked=self._on_match_clicked,
                on_sync_tracks_clicked=self._on_sync_tracks_clicked,
                open_settings=self._on_settings_clicked,
                navigate_to_review=lambda track_id: self._show_page(
                    "review", focus_track_id=track_id,
                ),
                on_tag_track_clicked=self._on_tag_track_clicked,
                on_retag_track_clicked=self._on_retag_track_clicked,
                on_tag_playlist_clicked=self._on_tag_playlist_clicked,
            ),
        )
        self._register_page("dashboard", self._dashboard_page)
        self._library_page = LibraryPage(
            page_context,
            LibraryHost(
                get_selected_playlist=lambda: self._dashboard_page.selected_playlist,
                get_selected_track_ids=self._dashboard_page._selected_track_ids,
                refresh_track_table=self._dashboard_page._poll_selected_playlist,
            ),
        )
        self._register_page("library", self._library_page)
        self._search_page = SearchPage(page_context)
        self._register_page("search", self._search_page)
        self._downloads_page = DownloadsPage(page_context)
        self._register_page("downloads", self._downloads_page)
        self._review_page = ReviewPage(
            page_context,
            ReviewHost(
                status_label=self._dashboard_page.status_label,
                refresh_track_table=self._dashboard_page._poll_selected_playlist,
                check_for_needs_decision_notification=(
                    self._tray.check_for_needs_decision_notification
                ),
            ),
        )
        self._register_page("review", self._review_page)
        self._duplicates_page = DuplicatesPage(page_context)
        self._register_page("duplicates", self._duplicates_page)
        self._sharing_page = SharingPage(page_context)
        self._register_page("sharing", self._sharing_page)

        self._history_page = HistoryPage(page_context)
        self._register_page("history", self._history_page)
        self._help_page = HelpPage(page_context)
        self._register_page("help", self._help_page)
        self._support_page = SupportPage(page_context)
        self._register_page("support", self._support_page)

        # Roadmap item 56 Phase 3 — Settings reversed from item 48's
        # separate-dialog decision into a real page, hosted the same
        # way as everything else here. header_extra is _build_page's
        # own extension point (see its docstring), used only by this
        # page today.
        self.settings_back_button = QPushButton("← Back")
        self.settings_back_button.setToolTip(help_text.TOOLTIP_SETTINGS_BACK)
        self.settings_back_button.clicked.connect(
            self._on_settings_back_clicked
        )
        self.settings_page = SettingsPage(
            self.application, on_about_requested=self._on_about_clicked,
            on_theme_mode_changed=self._apply_theme_mode,
        )
        self._register_page("settings", build_page(
            "Settings", help_text.SETTINGS_WINDOW_SUBTITLE,
            self.settings_page, header_extra=self.settings_back_button,
        ))
        self._settings_page_index = self._page_indices["settings"]

        # Locations load lazily, on every real show of this page rather
        # than eagerly in _build_ui() — every MainWindow construction
        # runs _build_ui() once, and an eager worker here was confirmed
        # live to compound into a real, reproducible deadlock (Qt's
        # internal connection-list mutex vs. the GIL) under the rapid,
        # repeated MainWindow construction this project's own test
        # suite does — see CLAUDE.md/docs/HISTORY.md item 39. A real
        # page SHOW (unlike construction) is comparatively rare and
        # human-paced, so refreshing on every one (roadmap item 56
        # Phase 6.1 — a location added since the last visit must
        # actually appear) doesn't reintroduce that hazard; only the
        # original "fetch at construction time" trigger did.
        self._duplicates_page_index = self._page_indices["duplicates"]
        # Roadmap item 62 (Phase 7.6) — lazy-loaded like Duplicates
        # (first real page SHOW, never at construction — see item 39's
        # deadlock), but ALSO joins the standing 20s backend_poll_timer
        # once visited, same shape as Downloads' own real-slskd-call
        # poll — sharing status/uploads are live external state, not a
        # one-shot local read like Duplicates/History. The visited/
        # in-progress flags and the ETA tracker live on SharingPage
        # itself now (round 8 Phase 6); only the page index stays here,
        # for _on_page_changed's dispatch.
        self._sharing_page_index = self._page_indices["sharing"]
        # Same lazy-load-on-first-real-visit reasoning as Duplicates
        # above — a plain, cheap local-DB read, but there's no reason
        # to pay it on every MainWindow construction when a real user
        # may never open this page in a given session.
        self._history_page_index = self._page_indices["history"]
        self._history_loaded = False
        # Tracks the currently-shown page key so the Settings back
        # button (roadmap item 56 Phase 3) knows where to return to,
        # and so _on_page_changed can detect "we just left Settings"
        # regardless of which navigation path was used (sidebar click,
        # back button, or a CTA/double-click action — every one of them
        # goes through _show_page).
        self._current_page_key = "dashboard"
        self._previous_page_key = "dashboard"
        self.stacked_widget.currentChanged.connect(self._on_page_changed)

        self.setCentralWidget(shell)
        # Round 8 §12.1 — restore the last-open page; an unrecognized/
        # missing key (a fresh install, or a page a later version
        # removed) falls back to the hardcoded "dashboard" default.
        restored_page = self.application.settings.last_open_page
        self._show_page(
            restored_page if restored_page in self._page_indices
            else "dashboard"
        )

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_indices[key] = self.stacked_widget.addWidget(widget)

    def _restore_window_geometry(self) -> None:
        # Round 8 §12.1 — a corrupt/foreign base64 blob (a hand-edited
        # config.json, or a value from some future format this version
        # doesn't understand) must never raise; restoreGeometry()
        # itself already reports success/failure via its return value
        # rather than throwing, so a bad value is just left as the
        # resize() default from the caller above.
        encoded = self.application.settings.window_geometry
        if not encoded:
            return

        try:
            raw = base64.b64decode(encoded)
        except (ValueError, TypeError):
            return

        self.restoreGeometry(QByteArray(raw))

    def _persist_window_geometry(self) -> None:
        # Round 8 §12.1 — called from cleanup_before_quit, the one real
        # cleanup path for every quit route (see that method's own
        # comment); hiding to the tray does not destroy this window, so
        # there is nothing to lose on that path and no reason to persist
        # on every resize/move.
        encoded = base64.b64encode(
            self.saveGeometry().data()
        ).decode("ascii")
        # Settings is reached FROM a nav page rather than being one
        # itself (_show_page's own settings-transition tracking already
        # treats it this way, via _previous_page_key) — persisting the
        # page the user was actually on before that detour reopens on
        # the page they meant to return to, not a transient stop.
        page_key = (
            self._previous_page_key
            if self._current_page_key == "settings"
            else self._current_page_key
        )
        self.application.update_settings(
            window_geometry=encoded, last_open_page=page_key,
        )

    # History's own delegating properties (window.history_table, etc.)
    # were deleted at the test-split session (S11.1, §9.3.4) — its
    # tests now address self._history_page directly. Search's and
    # Sharing's own delegating properties/methods were deleted the same
    # way at S11.2, Downloads' and TaggingPanel's own at S11.3, and
    # Dashboard's own at S11.4 — their tests now address
    # self._search_page/self._sharing_page/self._downloads_page/
    # self._dashboard_page directly. TaggingPanel itself moved again
    # (round 8 §12.6, Library split) — tests now address
    # self._library_page(._tagging_panel) instead.

    def _show_page(self, key: str, focus_track_id: str | None = None) -> None:
        # Roadmap item 56 Phase 3 — every navigation path in this app
        # (sidebar click, the Settings back button, a Dashboard CTA
        # action, a double-click) already goes through this one method,
        # so it's the single place both the back button's "where to
        # return to" and the settings-exit invalidation (§3.3) can hook
        # into without needing a Settings-specific special case at each
        # call site.
        if key == "settings" and self._current_page_key != "settings":
            self._previous_page_key = self._current_page_key
        elif self._current_page_key == "settings" and key != "settings":
            self._invalidate_after_leaving_settings()

        self._current_page_key = key
        self.stacked_widget.setCurrentIndex(self._page_indices[key])

        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)

        if key == "review" and focus_track_id is not None:
            self._review_page._pending_review_focus_track_id = focus_track_id
            # The Review tables are already on the standing 2s
            # poll_timer regardless of which page is visible (item 48's
            # pattern) — this explicit call just avoids making the user
            # wait up to 2s to see the row get selected.
            self._review_page._poll_review_items()

    def _on_settings_back_clicked(self) -> None:
        self._show_page(self._previous_page_key)

    def _invalidate_after_leaving_settings(self) -> None:
        # Roadmap item 56 Phase 3 §3.3 — a Settings change can affect
        # the Duplicates page's location combo (a location added/
        # removed) and the Dashboard's own next-step CTA (Spotify/
        # library-location/threshold facts). Both already have a real
        # refresh method; this just calls them immediately on exit
        # rather than waiting for their own standing poll/lazy-load to
        # eventually catch up. Phase 6.1 (Duplicates combo refresh)
        # later reuses this exact same _refresh_duplicates_locations()
        # call, not a second one.
        self._duplicates_page._refresh_duplicates_locations()
        self._dashboard_page._poll_next_step()

    def _build_activity_strip(self) -> QWidget:
        # Roadmap item 65 (Phase 2.2) — hidden whenever nothing is
        # running (the common case); see _render_activity_strip for what
        # populates it.
        strip = QWidget()
        strip.setObjectName("activityStrip")
        # A plain QWidget subclass doesn't paint its own stylesheet
        # background by default in Qt (item 47's identical
        # WA_StyledBackground finding, same fix here).
        strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Roadmap item C5.3 — the #activityStrip rule now lives in the
        # global stylesheet (theme.py's build_stylesheet), not baked
        # into a per-instance string here, so it re-colors on a runtime
        # theme switch automatically.

        layout = QHBoxLayout(strip)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_XS,
            theme.SPACING_MD, theme.SPACING_XS,
        )
        layout.setSpacing(theme.SPACING_SM)

        self.activity_strip_label = QLabel("")
        layout.addWidget(self.activity_strip_label)

        # Untuned fixed width — wide enough to read a real percentage
        # without dominating the strip.
        self.activity_strip_bar = QProgressBar()
        self.activity_strip_bar.setFixedWidth(160)
        self.activity_strip_bar.setTextVisible(False)
        layout.addWidget(self.activity_strip_bar)

        layout.addStretch()

        strip.hide()
        return strip

    def _render_activity_strip(self) -> None:
        # Roadmap item R7.6 — a visual-only header strip; pure waste to
        # keep updating while nobody can see it.
        if self._hidden_to_tray:
            return

        running = sorted(self.busy_actions.running_keys())

        if not running:
            self.activity_strip.hide()
            return

        self.activity_strip.show()

        if len(running) > 1:
            # Multiple actions running at once — a real count, not an
            # invented merged progress number (roadmap item 65's own
            # explicit instruction: don't fold unrelated work into one
            # fake percentage).
            self.activity_strip_label.setText(
                f"{len(running)} actions running"
            )
            self.activity_strip_bar.setRange(0, 0)
            return

        key = running[0]
        label = _BUSY_ACTION_LABELS.get(key, "Working…")
        progress = self._activity_progress.get(key)

        if progress is not None:
            stage, current, total = progress
            self.activity_strip_label.setText(
                f"{label} {stage} ({current}/{total})" if stage else
                f"{label} ({current}/{total})"
            )
            self.activity_strip_bar.setRange(0, total)
            self.activity_strip_bar.setValue(current)
            theme.style_determinate_progress_bar(self.activity_strip_bar)
        else:
            self.activity_strip_label.setText(label)
            self.activity_strip_bar.setRange(0, 0)  # indeterminate

    def _on_activity_progress(
            self, key: str, stage: str, current: int, total: int,
    ) -> None:
        # Roadmap item 65 (Phase 2.3's real consumer) — populated by any
        # run_worker(..., on_progress=...) caller that also passes a
        # matching key through here (none yet in this phase; Phase 7's
        # fingerprinting/duplicate-search progress is the first real
        # producer). Cleared the moment the action itself ends, via
        # _run_busy_worker's own wrapped_finished/wrapped_error.
        self._activity_progress[key] = (stage, current, total)
        self._render_activity_strip()

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebarPanel")
        # A plain QWidget subclass doesn't paint its own stylesheet
        # background by default in Qt (see notice.py's identical
        # WA_StyledBackground fix, found live in Phase 3) — the
        # `#sidebarPanel` QSS rule below would otherwise silently do
        # nothing.
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        # Roadmap item C5.3 — the #sidebarPanel rule now lives in the
        # global stylesheet (theme.py's build_stylesheet); see
        # #activityStrip's identical fix just above.

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(
            theme.SPACING_MD, theme.SPACING_LG,
            theme.SPACING_MD, theme.SPACING_LG,
        )
        layout.setSpacing(theme.SPACING_XS)

        wordmark_row = QHBoxLayout()
        wordmark_row.setContentsMargins(0, 0, 0, 0)
        # Roadmap item E4 (round 7) — reverses C4 (round 5)/D1 (round
        # 6). The custom-painted `_Wordmark` widget's own committed
        # `sizeHint()` (reserving real ascent+descent) contradicted what
        # a real Mac actually rendered — the label was still clipped at
        # the bottom in a live screenshot, with no way to settle the
        # contradiction offscreen. A plain QLabel reserves its own
        # font's ascent/descent internally and cannot exhibit this class
        # of bug at all; styled entirely via `QLabel#wordmark` in
        # `build_stylesheet` (theme.py), so it re-themes for free on
        # `setStyleSheet()` with no `retint()`/`on_theme_changed()` call
        # needed. The brow-strokes-over-"ee" idea is deliberately not
        # carried forward — see HISTORY §E4 for why the asset stays,
        # dormant, in the repo rather than deleted outright.
        self._wordmark = QLabel("Seeker")
        self._wordmark.setObjectName("wordmark")
        wordmark_row.addWidget(self._wordmark)
        wordmark_row.addStretch()
        # Roadmap item C5.10/C5.11 — right-aligned on the wordmark's own
        # row, cycling system -> light -> dark -> system.
        self._theme_toggle = _ThemeToggleButton(self._theme_mode)
        self._theme_toggle.clicked.connect(self._on_theme_toggle_clicked)
        wordmark_row.addWidget(self._theme_toggle)
        layout.addLayout(wordmark_row)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}

        for key, label in _NAV_PAGES:
            button = _build_nav_button(label)
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            button.clicked.connect(
                lambda _checked=False, key=key: self._show_page(key)
            )
            layout.addWidget(button)

        layout.addStretch()

        help_button = _build_nav_button("Help")
        self._nav_group.addButton(help_button)
        self._nav_buttons["help"] = help_button
        help_button.clicked.connect(lambda: self._show_page("help"))
        layout.addWidget(help_button)

        # Roadmap item 64 — directly below Help, same individually-built
        # pattern (a simple _show_page(key) lambda, no initial-tab-aware
        # handler needed).
        support_button = _build_nav_button("Support")
        self._nav_group.addButton(support_button)
        self._nav_buttons["support"] = support_button
        support_button.clicked.connect(lambda: self._show_page("support"))
        layout.addWidget(support_button)

        # Roadmap item 56 Phase 3 — reversed from item 48's "Settings
        # deliberately stays a separate dialog" decision: in fullscreen,
        # a second window reads as a dead end with no way back to the
        # shell. Now a real, checkable, nav-group page like Help, just
        # built individually (like Help) rather than via the generic
        # _NAV_PAGES loop, since it needs the initial_tab-aware handler
        # below, not the loop's plain `_show_page(key)`.
        self.settings_button = _build_nav_button("Settings")
        self._nav_group.addButton(self.settings_button)
        self._nav_buttons["settings"] = self.settings_button
        self.settings_button.setToolTip(help_text.TOOLTIP_OPEN_SETTINGS)
        # clicked emits a bool (checked state) — never connect it
        # directly to _on_settings_clicked, whose first real parameter
        # is initial_tab, not a checked flag.
        self.settings_button.clicked.connect(
            lambda: self._on_settings_clicked()  # noqa: PLW0108
        )
        layout.addWidget(self.settings_button)

        return sidebar

    # --- Roadmap item C5 (round 5): theme mode --------------------------

    def _on_theme_toggle_clicked(self) -> None:
        current_index = _THEME_MODE_CYCLE.index(self._theme_mode)
        next_mode = _THEME_MODE_CYCLE[
                (current_index + 1) % len(_THEME_MODE_CYCLE)
        ]
        self._apply_theme_mode(next_mode)

    def _apply_theme_mode(self, mode: str, persist: bool = True) -> None:
        """The one entry point every theme-mode change routes through —
        the sidebar toggle, Settings' three-way radio control, and the
        system `colorSchemeChanged` signal (when subscribed) all call
        this, never `theme.apply_theme()` directly. Keeps the toggle
        icon, Settings' own radios, and the persisted config in sync in
        every direction (C5.12).

        Roadmap item D2 (round 6) — ordering is load-bearing, not
        cosmetic. `self._theme_mode` is set and the system-scheme
        subscription is synced BEFORE `theme.apply_theme()` runs, so an
        explicit light/dark choice has already disconnected
        `_on_system_color_scheme_changed` by the time
        `apply_theme()`'s own `setColorScheme()` call emits
        `colorSchemeChanged` — that signal used to reach the still-
        connected handler mid-call, which re-resolved and silently
        re-applied the SYSTEM palette over whatever this call was
        trying to set, while the mode/icon/settings still ended up
        showing the originally-requested mode (the exact reported
        symptom: only the icon changed). `_applying_theme` is a second,
        independent guard (D2.3) for the "system" -> "system" path,
        where the subscription legitimately stays connected throughout.
        """
        self._theme_mode = mode
        self._sync_system_scheme_subscription()

        app = QApplication.instance()
        assert isinstance(app, QApplication)
        self._applying_theme = True
        try:
            theme.apply_theme(app, mode)
        finally:
            self._applying_theme = False

        if persist:
            self.application.set_theme_mode(mode)

        self._theme_toggle.set_mode(mode)
        self.settings_page.sync_theme_mode(mode)
        self.on_theme_changed()

    def _sync_system_scheme_subscription(self) -> None:
        # Roadmap item C5.6 — subscribed ONLY while mode is "system":
        # an explicit light/dark choice must never be silently
        # overridden by the OS flipping its own appearance later.
        style_hints = QGuiApplication.styleHints()
        if self._theme_mode == "system" and not self._system_scheme_connected:
            style_hints.colorSchemeChanged.connect(
                self._on_system_color_scheme_changed
            )
            self._system_scheme_connected = True
        elif self._theme_mode != "system" and self._system_scheme_connected:
            style_hints.colorSchemeChanged.disconnect(
                self._on_system_color_scheme_changed
            )
            self._system_scheme_connected = False

    def _on_system_color_scheme_changed(self, scheme: object) -> None:
        # The OS flipped appearance while mode == "system" — re-resolve
        # rather than reading `scheme` directly, so this stays correct
        # even if Qt's own Unknown-scheme fallback (DARK) is in play.
        #
        # Roadmap item D2.4 (round 6) — a blunt handler that re-applies
        # unconditionally is a handler waiting to be re-broken by the
        # next re-entrancy path someone finds. Two independent bail-outs:
        # `_theme_mode != "system"` (the subscription should already be
        # disconnected whenever this is true, but a handler must not
        # depend on that alone) and `_applying_theme` (this signal firing
        # as a direct side effect of `_apply_theme_mode`'s own in-flight
        # `theme.apply_theme()` call, not a genuine later OS change).
        if self._theme_mode != "system" or self._applying_theme:
            return
        self._apply_theme_mode("system", persist=False)

    def on_theme_changed(self) -> None:
        """Roadmap item C5.4 — re-applies anything that bakes a color
        into a specific widget instance rather than reading it fresh
        through the global stylesheet (see theme.py's own module
        docstring for the taxonomy). QSS-driven widgets need nothing
        here — `QApplication.setStyleSheet()` (already called by
        `_apply_theme_mode` above) re-polishes every one of them
        automatically.
        """
        # Roadmap item E4 (round 7) — the wordmark used to be a custom-
        # painted `_Wordmark` widget needing an explicit re-tint call
        # here (QSvgRenderer has no currentColor). It's a plain
        # QLabel#wordmark now, styled entirely through the global
        # stylesheet, which `_apply_theme_mode`'s own
        # `setStyleSheet()` call above already re-polishes for free —
        # nothing left to do here for it.
        self._theme_toggle.update()

        # Roadmap item C5.3 point 3 — QColor(theme.ACCENT)/setForeground
        # calls baked into table items ARE re-computed on every one of
        # these render calls, which the 2s poll_timer already re-runs
        # regularly (self-healing within ~2s) — but re-running them
        # here too means the switch is correct IMMEDIATELY, not after
        # up to a 2s wait.
        self._dashboard_page._poll_selected_playlist()
        self._downloads_page._poll_active_downloads()
        self._review_page._poll_review_items()
        self._render_activity_strip()

    def _update_nav_badge(self, key: str, count: int) -> None:
        label = dict(_NAV_PAGES).get(key) or key.capitalize()
        button = self._nav_buttons[key]
        button.setText(f"{label}  ({count})" if count > 0 else label)

    def _build_view_menu(self) -> None:
        # Round 8 §12.3/§12.5 — ⌘1-⌘7 for the nav pages, plus ⌘R
        # refresh, ⌘F focus search and ⌘, Settings, all surfaced here
        # for discoverability rather than left as invisible shortcuts.
        view_menu = self.menuBar().addMenu("&View")

        for index, (key, label) in enumerate(_NAV_PAGES, start=1):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.triggered.connect(
                lambda _checked=False, key=key: self._show_page(key)
            )
            view_menu.addAction(action)

        view_menu.addSeparator()

        refresh_action = QAction("Refresh", self)
        refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        refresh_action.triggered.connect(self._on_sync_clicked)
        view_menu.addAction(refresh_action)

        focus_search_action = QAction("Focus Search", self)
        focus_search_action.setShortcut(QKeySequence("Ctrl+F"))
        focus_search_action.triggered.connect(self._on_focus_search_clicked)
        view_menu.addAction(focus_search_action)

        view_menu.addSeparator()

        toggle_theme_action = QAction("Toggle Theme", self)
        toggle_theme_action.triggered.connect(self._on_theme_toggle_clicked)
        view_menu.addAction(toggle_theme_action)

        # triggered emits a bool — _on_settings_clicked's first real
        # parameter is initial_tab, not a checked flag (same reasoning
        # as settings_button's own connection in _build_sidebar).
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut(
            QKeySequence(QKeySequence.StandardKey.Preferences)
        )
        settings_action.triggered.connect(
            lambda: self._on_settings_clicked()  # noqa: PLW0108
        )
        view_menu.addAction(settings_action)

    def _on_focus_search_clicked(self) -> None:
        self._show_page("search")
        self._search_page.search_artist_edit.setFocus()

    def _build_window_menu(self) -> None:
        # Round 8 §12.5 — the standard macOS Window-menu pair; Qt
        # supplies the rest of the app's window management for free.
        window_menu = self.menuBar().addMenu("&Window")

        minimize_action = QAction("Minimize", self)
        minimize_action.setShortcut(QKeySequence("Ctrl+M"))
        minimize_action.triggered.connect(self.showMinimized)
        window_menu.addAction(minimize_action)

        zoom_action = QAction("Zoom", self)
        zoom_action.triggered.connect(self._on_zoom_clicked)
        window_menu.addAction(zoom_action)

    def _on_zoom_clicked(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _build_help_menu(self) -> None:
        menu_bar = self.menuBar()
        help_menu = menu_bar.addMenu("&Help")

        about_action = QAction(help_text.ABOUT_MENU_TEXT, self)
        about_action.triggered.connect(self._on_about_clicked)
        help_menu.addAction(about_action)

        # Real, live GitHub call — user-triggered ONLY (this one menu
        # action), never on a timer or anywhere near startup/
        # construction. See update_check.py's own docstring for why.
        self.check_for_updates_action = QAction(
            help_text.CHECK_FOR_UPDATES_MENU_TEXT, self,
        )
        self.check_for_updates_action.triggered.connect(
            self._on_check_for_updates_clicked
        )
        help_menu.addAction(self.check_for_updates_action)

    def _on_about_clicked(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    def _on_check_for_updates_clicked(self) -> None:
        self.check_for_updates_action.setEnabled(False)
        run_worker(
            self.thread_pool,
            check_for_update,
            on_finished=self._show_update_check_result,
            on_error=self._on_update_check_error,
        )

    def _show_update_check_result(self, result: UpdateCheckResult) -> None:
        self.check_for_updates_action.setEnabled(True)

        box = QMessageBox(self)
        box.setWindowTitle(help_text.UPDATE_CHECK_DIALOG_TITLE)

        if result.status == UpdateStatus.UP_TO_DATE:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(
                f"You're up to date (v{result.installed_version})."
            )
        elif result.status == UpdateStatus.UPDATE_AVAILABLE:
            box.setIcon(QMessageBox.Icon.Information)
            text = (
                f"A new version is available: {result.latest_version} "
                f"(you have v{result.installed_version})."
            )
            if result.release_url:
                text += f"<br><a href=\"{result.release_url}\">" \
                        f"View the release</a>"
                box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(text)
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"Couldn't check for updates: {result.reason}")

        box.exec()

    def _on_update_check_error(self, message: str) -> None:
        # check_for_update() itself never raises (see its own
        # docstring) — this only exists as a defensive fallback for a
        # failure in run_worker's own dispatch, not an expected path.
        self.check_for_updates_action.setEnabled(True)
        QMessageBox.warning(
            self, help_text.UPDATE_CHECK_DIALOG_TITLE,
            f"Couldn't check for updates: {message}",
        )

    def _on_page_changed(self, index: int) -> None:
        # Roadmap item 56 Phase 6.1 — was gated by
        # _duplicates_locations_loaded to fire at most once ever (the
        # original fix for a real, confirmed Qt/GIL deadlock — item 39
        # — triggered by fetching at MainWindow *construction* time).
        # A page SHOW is a different, human-paced trigger — the same
        # distinction item 39's own addendum already draws — so
        # refreshing on every show (a location added since the last
        # visit must actually appear) doesn't reintroduce that
        # construction-time hazard. Settings' own exit (§3.3) already
        # calls this same method directly; both paths now land on it.
        if index == self._duplicates_page_index:
            self._duplicates_page._refresh_duplicates_locations()
            self._duplicates_page._refresh_duplicates_milestone()

        if index == self._sharing_page_index:
            self._sharing_page._sharing_page_visited = True
            self._sharing_page._refresh_sharing()

        if index == self._history_page_index and not self._history_loaded:
            self._history_loaded = True
            self._history_page._refresh_history()

    def _trigger_backend_poll(self) -> None:
        if self._backend_poll_in_progress:
            # A previous poll_downloads() call (real slskd network
            # calls) is still running — a slow or hanging response must
            # not cause a second, overlapping writer to start on top of
            # it. Skip this tick; the next one will try again.
            return

        if not self.application.soulseek_configured:
            return

        self._backend_poll_in_progress = True

        def on_poll_finished(_: object) -> None:
            self._backend_poll_in_progress = False
            self._downloads_page._sample_download_progress()
            # A settled download completing during this real poll (Phase
            # 1's indexing fix) flips a track straight to IN_LIBRARY —
            # refresh the selected playlist's own track table right now
            # rather than waiting up to POLL_INTERVAL_MS for the next
            # 2s display tick to happen to catch it.
            self._dashboard_page._poll_selected_playlist()
            # Roadmap item R7.5 — checked on the same real 20s cycle
            # that can actually produce a newly-completed download, not
            # a new timer of its own.
            self._tray.check_for_download_notifications()

        def on_poll_error(_: str) -> None:
            self._backend_poll_in_progress = False
            self._tray.notify_error(
                "Seeker couldn't reach slskd — check that it's running."
            )

        run_worker(
            self.thread_pool,
            self.application.download_service.poll_downloads,
            on_finished=on_poll_finished,
            on_error=on_poll_error,
        )

    def _run_busy_worker(
            self,
            key: str,
            button: QPushButton,
            fn: Callable[[], Any] | Callable[[Callable[[str, int, int], None]], Any],
            *,
            busy_text: str | None = None,
            status_label: QLabel | None = None,
            on_finished: Callable[[Any], None] | None = None,
            on_error: Callable[[str], None] | None = None,
            reports_progress: bool = False,
    ) -> None:
        # Roadmap item 65 (Phase 2.1) — the shared shape for a long-
        # running action that should register in busy_actions/the
        # activity strip: begin() before submitting, end() on every real
        # completion path (success or error) so it's never left marked
        # running past its own task. Replaces passing button= directly to
        # run_worker() for every call site converted to use this — the
        # registry, not run_worker itself, now owns that button's
        # enable/disable + text for the duration.
        self.busy_actions.begin(key, button, busy_text)
        self._render_activity_strip()

        def wrapped_finished(result: Any) -> None:
            self.busy_actions.end(key)
            self._activity_progress.pop(key, None)
            self._render_activity_strip()
            if on_finished is not None:
                on_finished(result)

        def wrapped_error(message: str) -> None:
            self.busy_actions.end(key)
            self._activity_progress.pop(key, None)
            self._render_activity_strip()
            if on_error is not None:
                on_error(message)

        run_worker(
            self.thread_pool, fn, status_label=status_label,
            on_finished=wrapped_finished, on_error=wrapped_error,
            on_progress=(
                (lambda stage, current, total:
                 self._on_activity_progress(key, stage, current, total))
                if reports_progress else None
            ),
        )

    def _on_sync_clicked(self) -> None:
        self._run_busy_worker(
            "sync", self._dashboard_page.sync_button,
            self.application.sync_service.sync_playlists,
            status_label=self._dashboard_page.status_label,
            on_finished=lambda _: self._dashboard_page._load_playlists(),
        )

    def _on_scan_clicked(self) -> None:
        # scan_and_match() chains scan_all() + match_all() into one
        # background call (roadmap item 56) — a plain scan used to leave
        # newly-found files with no track_matches row at all until a
        # separate, non-obvious "Re-match library" click. run_worker()'s
        # single dispatcher gives no safe way to push a genuine live
        # "now matching..." update partway through one background call
        # (see ui/workers.py's own docstring on why a per-task signal was
        # deliberately removed) — this sets an immediate placeholder
        # instead, replaced by the real combined result once the whole
        # call finishes.
        self._run_busy_worker(
            "scan", self._dashboard_page.scan_button,
            self.application.library_service.scan_and_match,
            busy_text="Scanning…",
            status_label=self._dashboard_page.status_label,
            on_finished=self._on_scan_and_match_finished,
        )
        self._dashboard_page.status_label.setText(
            "Scanning library, then matching tracks…"
        )

    def _on_scan_and_match_finished(self, result: dict[str, int]) -> None:
        self._dashboard_page.status_label.setText(
            f"Scanned: {result['added']} added, {result['updated']} "
            f"updated, {result['removed']} removed. "
            f"Matched: {result['auto']} auto, "
            f"{result['needs_review']} needs review, "
            f"{result['unmatched']} unmatched."
        )
        self._dashboard_page._poll_selected_playlist()

    def _on_match_clicked(self) -> None:
        self._run_busy_worker(
            "match", self._dashboard_page.match_button,
            self.application.track_matcher.match_all,
            status_label=self._dashboard_page.status_label,
            on_finished=lambda _: self._dashboard_page._poll_selected_playlist(),
        )

    def _set_download_button_busy(self) -> None:
        # Idempotent (BusyActionRegistry.begin() no-ops if already
        # running) — safe to call again at every hop of the download
        # chain below, matching this method's own pre-registry behavior.
        self.busy_actions.begin(
            "download", self._dashboard_page.download_button, "Starting download…",
        )
        self._render_activity_strip()

    def _reset_download_button(self) -> None:
        self.busy_actions.end("download")
        self._render_activity_strip()

    def _on_download_clicked(self) -> None:
        if self._dashboard_page.selected_playlist is None:
            self._dashboard_page.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist = self._dashboard_page.selected_playlist
        playlist_name = playlist.name

        # Roadmap item 56 Phase 5.1 — the button previously gave no
        # feedback at all that anything had started, across this
        # entire multi-step chain (resolvability check, maybe a
        # destination dialog, then the real download). Disabled +
        # relabeled here and re-asserted at the top of every
        # continuation below (run_worker's own success-path
        # `button.setEnabled(True)` would otherwise flip it back on
        # between hops) so it never reads "enabled but says Starting
        # download…" at any point in the chain; reset on every real
        # exit path (cancelled dialog, no locations, real completion,
        # or a genuine error via on_error).
        self._set_download_button_busy()

        # Roadmap item 65 (Phase 3.2) — a playlist with its OWN
        # destination already set (`playlist.download_location_id`,
        # already loaded on the Playlist itself — no extra query needed)
        # always skips straight to the real download; the prompt below
        # is only for a playlist that would otherwise silently fall
        # through to the configured default (roadmap item 6 §3's own
        # earlier fallback), so the user gets to see and confirm — or
        # change — where it's actually going, once per playlist.
        if playlist.download_location_id is not None:
            self._start_download(playlist_name)
            return

        # Fetches both the real current fallback (to pre-fill the
        # dialog with the exact path it would already use — shares
        # DownloadService._resolve_destination with the real move step
        # via get_resolved_destination, so this can never drift into a
        # second, different notion of "resolvable") and every registered
        # location (for the picker), in one round trip.
        run_worker(
            self.thread_pool,
            lambda: (
                self.application.download_service
                .get_resolved_destination(playlist_name),
                self.application.library_service.list_locations(),
            ),
            on_finished=lambda result: self._open_destination_dialog(
                playlist_name, result[1], result[0],
            ),
            on_error=lambda _message: self._reset_download_button(),
        )

    def _open_destination_dialog(
            self,
            playlist_name: str,
            locations: list[tuple[LibraryLocation, bool]],
            resolved: tuple[LibraryLocation, str | None] | None = None,
    ) -> None:
        if not locations:
            self._reset_download_button()
            self._dashboard_page.dashboard_notice.show_message(
                help_text.NO_LOCATIONS_FOR_DESTINATION_DIALOG,
                kind="warning",
            )
            return

        location_objects = [location for location, _ in locations]

        # Roadmap item 65 (Phase 3.2) — when the real fallback already
        # resolves (`resolved` given), pre-fill with exactly what it
        # would use: that location, and its real subfolder (already
        # sanitized by _resolve_destination — never re-sanitized here).
        # Falls back to the app-wide configured default (item 6 §3's
        # original behavior) only when nothing resolved at all.
        if resolved is not None:
            prefill_location, prefill_subfolder = resolved
            default_location_id: int | None = prefill_location.id
        else:
            prefill_subfolder = None
            default_location_id = (
                self.application.settings.default_download_location_id
            )

        dialog = DestinationDialog(
            self, playlist_name, location_objects, default_location_id,
            initial_subfolder=prefill_subfolder,
        )

        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._reset_download_button()
            return

        location_id = dialog.selected_location_id()

        if location_id is None:
            self._reset_download_button()
            return

        subfolder = dialog.selected_subfolder()
        remember_for_playlist = dialog.remember_for_playlist()

        def do_persist() -> None:
            if remember_for_playlist:
                location = next(
                    loc for loc in location_objects if loc.id == location_id
                )
                self.application.download_service.set_destination(
                    playlist_name, location.name, subfolder,
                )
            else:
                # Not remembered specifically for this playlist — the
                # only other real destination concept is the app-wide
                # default (roadmap item 6 §1), so this becomes that.
                # Deliberately always True for the subfolder-per-
                # playlist toggle here: the field was prefilled with
                # the playlist's own name, so treating this choice as
                # "per playlist" matches what was actually shown,
                # even if the text was hand-edited to something else
                # for this one confirmation.
                self.application.persist_default_destination(
                    location_id, True,
                )

        self._set_download_button_busy()

        run_worker(
            self.thread_pool,
            do_persist,
            on_finished=lambda _: self._start_download(playlist_name),
            on_error=lambda _message: self._reset_download_button(),
        )

    def _start_download(self, playlist_name: str) -> None:
        self._set_download_button_busy()

        run_worker(
            self.thread_pool,
            lambda: self.application.download_service.download_playlist(
                playlist_name
            ),
            status_label=self._dashboard_page.status_label,
            on_finished=self._on_download_finished,
            on_error=lambda _message: self._reset_download_button(),
        )

    def _on_download_finished(self, result: dict[str, Any]) -> None:
        self._reset_download_button()
        self._dashboard_page._poll_selected_playlist()

        # Roadmap item 66 (Phase 4.2) — the real fix for "Requested 16,
        # skipped 12 (no candidates found)" when several of those 12 had
        # in fact become real Review candidates: help_text.py's own
        # formatter names each outcome separately rather than folding
        # them into one generic figure.
        message = help_text.format_download_result_message(result)
        kind = "success" if result["requested"] else "info"
        self._dashboard_page.dashboard_notice.show_message(message, kind=kind)

    def _on_sync_tracks_clicked(self) -> None:
        if self._dashboard_page.selected_playlist is None:
            return

        playlist = self._dashboard_page.selected_playlist

        def do_sync() -> Any:
            self.application.sync_service.sync_playlist_tracks(playlist)

        self._run_busy_worker(
            "sync_tracks", self._dashboard_page.sync_tracks_button, do_sync,
            status_label=self._dashboard_page.status_label,
            on_finished=lambda _: self._dashboard_page._poll_selected_playlist(),
        )

    # Round 8 §12.6 — Dashboard's own track-table row actions (a Tag
    # button, the context menu's Re-tag) and its "next step" CTA's own
    # tag_playlist action all reach TaggingPanel through DashboardHost,
    # now that it lives on the Library page rather than on Dashboard
    # itself. Thin bound-method wrappers, not lambdas passed directly
    # at DashboardHost construction time, because self._library_page
    # doesn't exist yet at that point (ruff PLW0108 flags the
    # equivalent lambda as an unnecessary wrapper around a call that
    # LOOKS resolvable now but isn't).
    def _on_tag_track_clicked(self, track_id: str, button: QPushButton) -> None:
        self._library_page._tagging_panel._on_tag_track_clicked(track_id, button)

    def _on_retag_track_clicked(self, track_id: str) -> None:
        self._library_page._tagging_panel._on_retag_track_clicked(track_id)

    def _on_tag_playlist_clicked(self) -> None:
        self._library_page._tagging_panel._on_tag_playlist_clicked()

    def _on_settings_clicked(self, initial_tab: str | None = None) -> None:
        # Roadmap item 56 Phase 3 — self.settings_page is a single,
        # long-lived page built once in _build_ui() (item 22's "held
        # reference" concern that used to apply to a per-open
        # SettingsWindow no longer applies at all: this widget is never
        # constructed-and-discarded).
        if initial_tab is not None:
            self.settings_page.select_tab(initial_tab)

        self._show_page("settings")

    # --- Roadmap item R7: run in the background from the macOS menu bar ----
    #
    # Roadmap item 9.3.2 (round 8, Phase 6) — the tray/notification
    # group (icon/menu build, activation, pause/open/check/quit
    # actions, application-reopen handling, and every notification)
    # moved verbatim to `ui/tray.py`'s `TrayController`, constructed as
    # `self._tray` in __init__. What stays here — closeEvent and the
    # hide-to-tray verification below — is round 7's E1, genuinely
    # subtle, and about the *window*, not the tray; see tray.py's own
    # module docstring. `_on_application_state_changed` also stays: it
    # is the real QObject-bound slot `applicationStateChanged` is
    # connected to (see that connect() call's own comment) — a plain
    # `TrayController` method can't hold that connection safely.

    def _set_hidden_to_tray(self, value: bool) -> None:
        self._hidden_to_tray = value

    def _bump_hide_request_id(self) -> None:
        self._hide_request_id += 1

    def _clear_pre_fullscreen_geometry(self) -> None:
        self._pre_fullscreen_geometry = None

    def _set_dock_icon_visible_policy(self, visible: bool) -> None:
        # A real seam, not just style — see TrayHost's own
        # `set_dock_icon_visible` docstring for why this bare-name call
        # must execute in THIS module's namespace rather than
        # tray.py's own.
        _set_dock_icon_visible(visible)

    def _on_application_state_changed(
            self, state: Qt.ApplicationState,
    ) -> None:
        self._tray.on_application_state_changed(state)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Round 9 §2.2 — installed on the QApplication instance itself
        # (see __init__'s own comment on this same mechanism); every
        # other event passes through untouched via the base
        # implementation, same pattern as any other QObject-level
        # filter in this codebase would use.
        if (
            watched is QApplication.instance()
            and event.type() == QEvent.Type.Quit
        ):
            return not self._confirm_quit_if_downloads_active()
        return super().eventFilter(watched, event)

    def _confirm_quit_if_downloads_active(self) -> bool:
        # UI -> service, as always: the count comes from
        # DashboardService.get_active_downloads() (a cheap local DB
        # read — see downloads_page.py's own comment on this same
        # call), never a repository queried directly here. "In
        # progress" mirrors downloads_page.active_downloads_count's own
        # definition (status == "downloading") rather than inventing a
        # second one.
        active = self.application.dashboard_service.get_active_downloads()
        count = sum(
            1 for download in active
            if download.request.status == "downloading"
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
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Quit Seeker?")
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
        # waits on `self.thread_pool`), so a future real recurrence
        # logging "starting" but never "finished" points at something
        # IN this method; both logged quickly but the process still
        # hangs afterward points at teardown of `self.thread_pool`
        # itself once this method returns and `window` goes out of
        # scope. Logs `self.thread_pool` specifically, not
        # `QThreadPool.globalInstance()` — every real worker here runs
        # on the per-window pool built in `__init__`, so the global
        # instance's own count would always read 0 regardless.
        started_at = time.monotonic()
        logger.info(
            "cleanup_before_quit: starting, thread_pool active=%d max=%d",
            self.thread_pool.activeThreadCount(),
            self.thread_pool.maxThreadCount(),
        )

        self.poll_timer.stop()
        self.backend_poll_timer.stop()

        # Round 9 §3.1 — this is now a BACKSTOP, not the primary save
        # path: `closeEvent` already persists geometry while the window
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

        # Roadmap item C5.6 — a real Qt signal connection to a
        # GLOBAL object (QGuiApplication.styleHints(), not this
        # window), so it must be torn down explicitly rather than
        # relying on this window's own destruction to drop it.
        if self._system_scheme_connected:
            QGuiApplication.styleHints().colorSchemeChanged.disconnect(
                self._on_system_color_scheme_changed
            )
            self._system_scheme_connected = False

        # Roadmap item 116 (round 8, §14.2) — same reasoning as
        # _system_scheme_connected just above: a connection to the
        # GLOBAL QApplication instance, not this window. Disconnects
        # the same MainWindow-owned stub that was connected in
        # __init__ (see that connect() call's own comment for why it's
        # not `self._tray.on_application_state_changed` directly).
        if self._app_state_connected:
            app = QApplication.instance()
            if app is not None:
                assert isinstance(app, QGuiApplication)
                app.applicationStateChanged.disconnect(
                    self._on_application_state_changed
                )
            self._app_state_connected = False

        # Roadmap item 116 (round 8, §14.3.4) — a quit must never leave
        # the process in Accessory mode mid-teardown; unconditional, not
        # gated on any hidden-state tracking, so a quit from ANY state
        # (visible, hidden, mid-fullscreen-close) always restores it.
        _set_dock_icon_visible(True)

        self._tray.hide_icon()

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

    def closeEvent(self, event: QCloseEvent) -> None:
        # Roadmap item R7.1/R7.2 — hides to the menu bar instead of
        # quitting, but ONLY when there's a real tray icon to hide to;
        # with none available (or not actually shown), this falls
        # through to Qt's ordinary close behavior unchanged — the
        # explicit fallback the brief itself asks for.
        if not self._tray.is_icon_visible():
            super().closeEvent(event)
            return

        # Roadmap item E1.4 (round 7) — a new hide attempt invalidates
        # any earlier one's still-pending verification (see
        # `_hide_request_id`'s own comment at its declaration).
        self._hide_request_id += 1

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
        # exists (reported live; see docs/HISTORY.md#E1).
        #
        # Fixed by not intercepting the close at all while fullscreen:
        # let AppKit's own "close a fullscreen window" handling run,
        # which tears down the Space correctly because it's the
        # platform's own path, not anything this app has to get right
        # itself. `setQuitOnLastWindowClosed(False)` (main_ui.py) keeps
        # the app alive in the tray exactly as before. `WA_
        # DeleteOnClose` is handled once, where the tray icon is built
        # (`_build_tray_icon`) — not here; see that comment.
        if sys.platform == "darwin" and self.isFullScreen():
            self._pre_fullscreen_geometry = self.normalGeometry()
            # Round 9 §3.1 — persisted here, while the window is still
            # genuinely visible, rather than left solely to
            # cleanup_before_quit's backstop: in Kris's real flow the
            # window is already hidden to the tray by the time a quit
            # follows, and saveGeometry() against a non-visible window
            # is not the geometry the user actually wants back.
            self._persist_window_geometry()
            self._tray.show_hide_notice_once()
            super().closeEvent(event)
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
        # Round 9 §3.1 — persisted while still visible, before hide()
        # below makes it not; see the fullscreen branch above for the
        # same reasoning.
        self._persist_window_geometry()
        self.hide()
        self._tray.show_hide_notice_once()
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
        # (a legitimate reopen via `_on_tray_open_seeker`) must not let
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
        handle = self.windowHandle()
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
                if self._tray.is_icon_visible():
                    _set_dock_icon_visible(False)
                return

            # Roadmap item E1.4 (round 7, corrected after a SECOND
            # review) — the first version of this branch called
            # `self.hide()` again here as a "retry." That is a
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
                if self._tray.is_icon_visible():
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

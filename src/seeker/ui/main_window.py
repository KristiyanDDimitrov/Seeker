import html
import logging
import math
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
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
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
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
from seeker.soulseek.client import SlskdUnreachableError
from seeker.ui import help_text, plain_text, theme
from seeker.ui.busy_actions import BusyActionRegistry
from seeker.ui.dialogs import (
    AboutDialog,
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
from seeker.ui.plain_text import PlainLabel, plain_tooltip
from seeker.ui.playlist_selection import PlaylistSelection
from seeker.ui.settings_window import SettingsPage
from seeker.ui.slskd_status import START_SLSKD_KEY, SlskdStatus
from seeker.ui.tray import TrayController, TrayHost
from seeker.ui.window_lifecycle import (
    WindowLifecycleController,
    WindowLifecycleHost,
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
    START_SLSKD_KEY: "Starting slskd…",
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
        self.setToolTip(plain_tooltip(f"Theme: {label} (click to change)"))

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
        # round9 §7.1 — the shared playlist/track selection Dashboard
        # writes and Library reads, replacing LibraryHost/TaggingPanel
        # Host's prior read-only reach into DashboardPage's own
        # attributes.
        self.playlist_selection = PlaylistSelection()
        # Written only by _trigger_backend_poll.
        self.slskd_status = SlskdStatus()
        # Roadmap item 65 (Phase 2.2/2.3) — keyed the same as
        # busy_actions; populated by a run_worker(on_progress=...)
        # callback (via _on_activity_progress), consulted by
        # _render_activity_strip. Empty for every action wired in Phase
        # 2 itself — Phase 7's fingerprinting/duplicate-search progress
        # is the first real producer.
        self._activity_progress: dict[str, tuple[str, int, int]] = {}
        self._backend_poll_in_progress = False
        # The tray menu's status line and "Review (N)"/"Upgrades (N)"
        # items read ReviewPage's `needs_review_count`/
        # `pending_upgrades_count` and DownloadsPage's
        # `active_downloads_count` — built from data each page's own
        # poll already fetches, never a third source of truth.

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
        self._lifecycle = WindowLifecycleController(WindowLifecycleHost(
            application=self.application,
            window=self,
            thread_pool=self.thread_pool,
            tray=self._tray,
            page_to_reopen=self._page_to_reopen,
            release_shell=self._release_for_quit,
        ))

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
        # Gated on a real tray icon existing: with none (not
        # self._tray.has_icon), closeEvent takes the ordinary real-close path
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
        if app is not None and self._tray.has_icon:
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
        # default size, not the size it was closed at"). This call is a
        # best-effort default so the window doesn't flash at the
        # resize() default above before it's ever shown; `showEvent()`
        # below is what actually wins the race on real hardware — see
        # its own comment. restoreGeometry() itself still silently
        # no-ops on a missing/corrupt value, leaving whatever's in
        # place, so there's nothing to validate here beyond the base64
        # decode itself.
        self._lifecycle.restore_window_geometry()

        # Roadmap item C5.6 — subscribes to the OS's own appearance
        # changes when (and only when) the persisted mode is "system",
        # so the app follows the Mac flipping at sunset with no
        # restart. Deliberately after _build_ui(): the toggle/wordmark
        # already exist by now, so a signal firing mid-construction
        # (unlikely, but not impossible) can't reach a half-built UI.
        self._sync_system_scheme_subscription()
        self._dashboard_page.load_playlists()
        self._downloads_page.poll_active_downloads()
        self._review_page.poll_review_items()
        self._dashboard_page.poll_next_step()
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
        self.poll_timer.timeout.connect(self._dashboard_page.poll_selected_playlist)
        self.poll_timer.timeout.connect(
            self._downloads_page.poll_active_downloads
        )
        self.poll_timer.timeout.connect(self._review_page.poll_review_items)
        self.poll_timer.timeout.connect(self._dashboard_page.poll_next_step)
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
        self.poll_timer.timeout.connect(self._tray.render_tray_menu)
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
            self._sharing_page.poll_sharing
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
        # real reopen. Reopening the window itself goes through
        # `window.reopen()`, so the hide-to-tray state stays owned by
        # the lifecycle controller alone.
        return TrayController(TrayHost(
            application=self.application,
            thread_pool=self.thread_pool,
            window=self,
            navigate=self._show_page,
            render_activity_strip=self._render_activity_strip,
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
                lambda: self._dashboard_page.poll_selected_playlist()  # noqa: PLW0108
            ),
            poll_active_downloads=(
                lambda: self._downloads_page.poll_active_downloads()  # noqa: PLW0108
            ),
            poll_review_items=(
                lambda: self._review_page.poll_review_items()  # noqa: PLW0108
            ),
            poll_next_step=(
                lambda: self._dashboard_page.poll_next_step()  # noqa: PLW0108
            ),
            needs_review_count=lambda: self._review_page.needs_review_count,
            pending_upgrades_count=(
                lambda: self._review_page.pending_upgrades_count
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
            is_hidden_to_tray=self._lifecycle.is_hidden_to_tray,
            render_activity_strip=self._render_activity_strip,
            playlist_selection=self.playlist_selection,
            slskd_status=self.slskd_status,
        )

        self._page_indices: dict[str, int] = {}
        self._dashboard_page = DashboardPage(
            page_context,
            DashboardHost(
                open_settings=self._on_settings_clicked,
                navigate_to_review=lambda track_id: self._show_page(
                    "review", focus_track_id=track_id,
                ),
                # Lambdas, not bound methods: the Library page is built
                # after this one, so the lookup has to wait for a click.
                tag_track=lambda track_id, button, feedback: (  # noqa: PLW0108
                    self._library_page.tag_track(track_id, button, feedback)
                ),
                retag_track=lambda track_id, feedback: (  # noqa: PLW0108
                    self._library_page.retag_track(track_id, feedback)
                ),
                tag_playlist=lambda feedback: (  # noqa: PLW0108
                    self._library_page.tag_playlist(feedback)
                ),
            ),
        )
        self._register_page("dashboard", self._dashboard_page)
        self._library_page = LibraryPage(
            page_context,
            LibraryHost(
                refresh_track_table=self._dashboard_page.poll_selected_playlist,
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
                refresh_track_table=self._dashboard_page.poll_selected_playlist,
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

    def _page_to_reopen(self) -> str:
        # Settings is reached FROM a nav page rather than being one
        # itself (_show_page's own settings-transition tracking already
        # treats it this way, via _previous_page_key) — persisting the
        # page the user was actually on before that detour reopens on
        # the page they meant to return to, not a transient stop.
        return (
            self._previous_page_key
            if self._current_page_key == "settings"
            else self._current_page_key
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
            self._review_page.focus_track(focus_track_id)

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
        # later reuses this exact same refresh_locations()
        # call, not a second one.
        self._duplicates_page.refresh_locations()
        self._dashboard_page.poll_next_step()

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

        self.activity_strip_label = PlainLabel("")
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
        if self._lifecycle.is_hidden_to_tray():
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
        self._wordmark = PlainLabel("Seeker")
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
        self._dashboard_page.poll_selected_playlist()
        self._downloads_page.poll_active_downloads()
        self._review_page.poll_review_items()
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
        # The pages are built after the menus, so the lookup waits for
        # the shortcut.
        refresh_action.triggered.connect(
            lambda _checked=False: self._dashboard_page.refresh_playlists()
        )
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
        # The version, URL and reason come from GitHub's response.
        box.setTextFormat(Qt.TextFormat.PlainText)

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
                text = (
                    f"{html.escape(text)}<br>"
                    f'<a href="{html.escape(result.release_url)}">'
                    f"View the release</a>"
                )
                box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(text)
        elif result.status == UpdateStatus.NO_RELEASES_PUBLISHED:
            # Round 9 §4.2a — a repo with nothing published yet isn't a
            # fault, so this gets its own honest, un-alarming rendering
            # rather than falling into the UNAVAILABLE branch's Warning
            # icon and "Couldn't check for updates:" framing.
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(result.reason or "No releases have been published yet.")
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(f"Couldn't check for updates: {result.reason}")

        box.exec()

    def _on_update_check_error(self, message: str) -> None:
        # check_for_update() itself never raises (see its own
        # docstring) — this only exists as a defensive fallback for a
        # failure in run_worker's own dispatch, not an expected path.
        self.check_for_updates_action.setEnabled(True)
        plain_text.warning(
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
            self._duplicates_page.refresh_locations()
            self._duplicates_page.refresh_milestone()

        if index == self._sharing_page_index:
            self._sharing_page.on_shown()

        if index == self._history_page_index and not self._history_loaded:
            self._history_loaded = True
            self._history_page.refresh_history()

        if index == self._settings_page_index:
            self.settings_page.refresh_login_item_state()

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

        def poll() -> SlskdUnreachableError | None:
            # Returned, not raised: on_error only receives text, and an
            # outage is state to show, not an error to report.
            try:
                self.application.download_service.poll_downloads()
            except SlskdUnreachableError as outage:
                return outage
            return None

        def on_poll_finished(outage: SlskdUnreachableError | None) -> None:
            self._backend_poll_in_progress = False

            if outage is None:
                self.slskd_status.mark_reachable()
            elif self.slskd_status.mark_unreachable(str(outage)):
                self._tray.notify_outage(str(outage))

            self._downloads_page.sample_download_progress()
            # A settled download completing during this real poll (Phase
            # 1's indexing fix) flips a track straight to IN_LIBRARY —
            # refresh the selected playlist's own track table right now
            # rather than waiting up to POLL_INTERVAL_MS for the next
            # 2s display tick to happen to catch it.
            self._dashboard_page.poll_selected_playlist()
            # Roadmap item R7.5 — checked on the same real 20s cycle
            # that can actually produce a newly-completed download, not
            # a new timer of its own.
            self._tray.check_for_download_notifications()

        def on_poll_error(message: str) -> None:
            self._backend_poll_in_progress = False
            self._tray.notify_error(message)

        run_worker(
            self.thread_pool,
            poll,
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

    def _on_settings_clicked(self, initial_tab: str | None = None) -> None:
        # Roadmap item 56 Phase 3 — self.settings_page is a single,
        # long-lived page built once in _build_ui() (item 22's "held
        # reference" concern that used to apply to a per-open
        # SettingsWindow no longer applies at all: this widget is never
        # constructed-and-discarded).
        if initial_tab is not None:
            self.settings_page.select_tab(initial_tab)

        self._show_page("settings")

    # --- The window lifecycle (ui/window_lifecycle.py) ------------------
    #
    # The tray/notification group lives in `ui/tray.py`'s
    # `TrayController` (`self._tray`); geometry, hide-to-tray and quit
    # live in `ui/window_lifecycle.py`'s `WindowLifecycleController`
    # (`self._lifecycle`). What stays here is what only this QObject
    # can do: the Qt event overrides, the event filter on the
    # QApplication, and `_on_application_state_changed`, the real
    # QObject-bound slot `applicationStateChanged` is connected to
    # (see that connect() call's own comment) — a plain Python
    # object's method can't hold that connection safely.

    def show_restored(self) -> None:
        """Show the window filled or windowed, the way it was closed."""
        self._lifecycle.show_restored()

    def reopen(self) -> None:
        """Bring the window back from the menu bar."""
        self._lifecycle.reopen()

    def start_hidden_to_tray(self) -> bool:
        """Start in the menu bar without ever showing the window;
        False when there is no tray icon to start behind."""
        return self._lifecycle.start_hidden_to_tray()

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
            return not self._lifecycle.confirm_quit_if_downloads_active()
        return super().eventFilter(watched, event)

    def cleanup_before_quit(self) -> None:
        # Connected to QApplication.aboutToQuit in main_ui.py: the one
        # cleanup path every quit route reaches.
        self._lifecycle.cleanup_before_quit()

    def _release_for_quit(self) -> None:
        # The shell's own part of cleanup_before_quit (see
        # WindowLifecycleHost.release_shell).
        self.poll_timer.stop()
        self.backend_poll_timer.stop()

        # Round 9 §6 — unlike window geometry, there is no
        # hide-to-tray visibility race to guard against: the Review
        # page's splitter keeps reporting its real current sizes
        # whether or not MainWindow itself is visible, since hiding to
        # the tray never destroys either widget. Unconditional, unlike
        # the lifecycle's `_hidden_to_tray` gate on geometry.
        self._review_page.persist_splitter_state()

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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._lifecycle.after_show()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._lifecycle.close_event(event)

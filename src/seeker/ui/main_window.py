import logging
import math
import sys
import time
from collections.abc import Callable
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
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
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from seeker.application import Application
from seeker.library.duplicate_service import (
    BulkDuplicateResolutionResult,
    DuplicateGroup,
    GroupResolutionPlan,
)
from seeker.models.active_download import ActiveDownload
from seeker.models.history_event import DOWNLOADED, HistoryEvent
from seeker.models.library_location import LibraryLocation
from seeker.models.needs_review_match import NeedsReviewMatch
from seeker.models.playlist import Playlist
from seeker.models.soulseek_file import SoulseekFile
from seeker.models.track_status import TrackStatus
from seeker.sharing_service import LocationShareState, UploadStatus
from seeker.soulseek.download_service import (
    BulkUpgradeReplaceResult,
)
from seeker.ui import help_text, theme
from seeker.ui.busy_actions import BusyActionRegistry
from seeker.ui.dialogs import (
    AboutDialog,
    # Roadmap item 9.3 (round 8, Phase 6) — no longer constructed here
    # (BulkReplaceUpgradesDialog moved to review_page.py with the rest
    # of Review; RenamePreviewDialog moved to tagging_panel.py with the
    # rest of Tagging), but test_ui_smoke.py imports both from THIS
    # module's own namespace (`from seeker.ui.main_window import
    # BulkReplaceUpgradesDialog`), not from seeker.ui.dialogs directly.
    # Kept as deliberate re-exports until the test-split session
    # repoints those imports (S11, §9.3.4) — dropped alongside it, not
    # before.
    BulkReplaceUpgradesDialog,  # noqa: F401
    BulkResolveDuplicatesDialog,
    DestinationDialog,
    RenamePreviewDialog,  # noqa: F401
)
from seeker.ui.download_eta import DownloadEtaTracker
from seeker.ui.flow_layout import FlowLayout
from seeker.ui.formatting import format_file_size
from seeker.ui.notice import InlineNotice
from seeker.ui.pages.context import PageContext, build_page
from seeker.ui.pages.dashboard_page import (
    DashboardHost,
    DashboardPage,
    # Roadmap item 9.3 (round 8, Phase 6) — _decide_next_step moved to
    # dashboard_page.py with the rest of Dashboard, but
    # tests/test_next_step.py imports it from THIS module's own
    # namespace (same re-export shape as RenamePreviewDialog above).
    # _NextStepFacts is genuinely used below (the delegating
    # _render_next_step stub's type annotation), so it needs no noqa.
    _decide_next_step,  # noqa: F401
    _NextStepFacts,
)
from seeker.ui.pages.downloads_page import DownloadsPage
from seeker.ui.pages.history_page import HistoryPage
from seeker.ui.pages.review_page import (
    NeedsReviewCandidates,
    PendingUpgrades,
    ReviewHost,
    ReviewPage,
)
from seeker.ui.pages.search_page import SearchPage
from seeker.ui.pages.sharing_page import SharingPage
from seeker.ui.pages.static_pages import HelpPage, SupportPage
from seeker.ui.settings_window import SettingsPage
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

# Roadmap item R7.5 — an unreachable slskd must not emit a tray
# notification on every 20s backend-poll error; untuned, same
# "reasonable starting guess" convention as every other threshold here.
ERROR_NOTIFICATION_COOLDOWN_SECONDS = 300.0

# Roadmap item 56 Phase 6.3 — a sentinel QButtonGroup id for the "Keep
# all" option, sharing the same group as the per-file keep radios so
# selecting one deselects the others (the exact behavior the user
# asked to keep). Real local_file ids are always positive
# (AUTOINCREMENT starts at 1), so 0 can never collide with one — and,
# confirmed live, -1 specifically CANNOT be used here: QButtonGroup.
# addButton(button, id=-1) doesn't set the id to -1 at all — Qt treats
# -1 as its own "auto-assign an id" sentinel and silently substitutes a
# different, Qt-generated negative id (checkedId() returned -2 in a
# real, direct repro), breaking any comparison against a real -1
# constant.
KEEP_ALL_DUPLICATES_ID = 0

# Roadmap item 68 (Phase 7.1) — named constants for the duplicates
# table's real column layout, replacing literal indices scattered
# across the render path. Three independent investigations (item 61
# Phase 6.2, and this block's own Phase 0.5 — both a real-service/
# real-libchromaprint repro and a 15-group/45-row real-scale repro at
# the real default window size) could NOT reproduce a genuine index-vs-
# header mismatch; this hardening exists so that bug CLASS becomes
# structurally impossible regardless, and so the regression test can
# resolve "Actions" by its real header text instead of sharing the same
# literal the render code uses (a test that shares the code's own
# mistake proves nothing).
class _DuplicatesColumn(IntEnum):
    GROUP = 0
    LOCATION = 1
    PATH = 2
    FORMAT = 3
    BITRATE = 4
    SIMILARITY = 5
    KEEP = 6
    ACTIONS = 7


_DUPLICATES_COLUMN_HEADERS = [
    "Group", "Location", "Path", "Format", "Bitrate", "Similarity",
    "Keep", "Actions",
]

# Roadmap item 8.1 (round 8, Phase 5) — the declarative layout each
# table used to write out by hand across a `_configure_*_columns`/
# `_size_*_columns` pair; see `theme.ColumnLayout`.
_DUPLICATES_COLUMNS = theme.ColumnLayout(
    stretch=(_DuplicatesColumn.PATH,),
    fit_content=(
        _DuplicatesColumn.GROUP, _DuplicatesColumn.LOCATION,
        _DuplicatesColumn.FORMAT, _DuplicatesColumn.BITRATE,
        _DuplicatesColumn.SIMILARITY, _DuplicatesColumn.KEEP,
    ),
    actions=_DuplicatesColumn.ACTIONS,
)


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
        # See SettingsWindow's identical fix (CLAUDE.md's broad
        # end-to-end stress test entry) — a parentless top-level
        # QMainWindow's close() only hides it by default, never
        # actually destroys it, unless this is set. MainWindow is
        # normally only closed once (app exit), but tests construct
        # and close it repeatedly — this matters there even if it's
        # rarely the operational hot path in real usage. Confirmed
        # this specific attribute was never the cause of a real,
        # separately-found segfault (see workers.py's own
        # SingleShotConnection fix) — isolated by temporarily removing
        # each of the two changes independently against the full test
        # suite before concluding which one was actually responsible.
        # Roadmap item E1 (round 7) — "normally only closed once" is no
        # longer quite true: `_build_tray_icon()` clears this attribute
        # again, permanently, the moment a real tray icon exists — see
        # that method's own comment for why a window with a live tray
        # icon to reopen from must never actually be deleted on close.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
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
        # read the `_needs_review_count`/`_pending_upgrades_count`
        # delegating properties below — real ReviewPage state
        # (round 8 Phase 6), built from data its own poll already
        # fetches, never a third source of truth (R7.3's own explicit
        # instruction). `_pending_review_focus_track_id`/
        # `selected_playlist`/`_current_track_statuses`/the next-step
        # dismissal keys all moved to page modules with the rest of
        # their own pages the same way. The downloading count itself
        # lives on DownloadsPage; read via the `_active_downloads_count`
        # delegating property below.
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
        self._tray_icon: QSystemTrayIcon | None = None
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

        self._build_tray_icon()

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
        # Gated on a real tray icon existing: with none (self._tray_icon
        # is None), closeEvent takes the ordinary real-close path
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
        if app is not None and self._tray_icon is not None:
            # applicationStateChanged is a QGuiApplication signal;
            # QApplication.instance()'s declared return type is the
            # narrower QCoreApplication — real at runtime (this app
            # always constructs a QApplication, itself a QGuiApplication
            # subclass), just not visible to mypy from the stub alone.
            assert isinstance(app, QGuiApplication)
            app.applicationStateChanged.connect(
                self._on_application_state_changed
            )
            self._app_state_connected = True

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
        self._seed_notification_cutoff()

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
        self.poll_timer.timeout.connect(self._poll_selected_playlist)
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
        self.poll_timer.timeout.connect(self._render_tray_menu)
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

    def _build_ui(self) -> None:
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
            ),
        )
        self._register_page("dashboard", self._dashboard_page)
        self._search_page = SearchPage(page_context)
        self._register_page("search", self._search_page)
        self._downloads_page = DownloadsPage(page_context)
        self._register_page("downloads", self._downloads_page)
        self._review_page = ReviewPage(
            page_context,
            ReviewHost(
                status_label=self.status_label,
                refresh_track_table=self._dashboard_page._poll_selected_playlist,
                check_for_needs_decision_notification=(
                    self._check_for_needs_decision_notification
                ),
            ),
        )
        self._register_page("review", self._review_page)
        self._register_page("duplicates", build_page(
            "Duplicates", help_text.DUPLICATES_TAB_SUBTITLE,
            self._build_duplicates_content(),
        ))
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
        self._show_page("dashboard")

    def _register_page(self, key: str, widget: QWidget) -> None:
        self._page_indices[key] = self.stacked_widget.addWidget(widget)

    # Roadmap item 9.3 (round 8, Phase 6) — temporary delegating
    # properties for every HistoryPage attribute test_ui_smoke.py
    # touches by name (window.history_table, etc.), so moving the page
    # out from under MainWindow proves behaviour-neutral (full suite
    # green with zero test edits) before any test is repointed at the
    # page widget directly. Deleted, alongside that repointing, at the
    # test-split session (S11, §9.3.4) — not before, per SESSION-PLAN.md.
    @property
    def history_table(self) -> QTableWidget:
        return self._history_page.history_table

    @property
    def history_filter_combo(self) -> QComboBox:
        return self._history_page.history_filter_combo

    @property
    def history_refresh_button(self) -> QPushButton:
        return self._history_page.history_refresh_button

    @property
    def history_status_label(self) -> QLabel:
        return self._history_page.history_status_label

    # Same temporary-delegation pattern as History above, for every
    # SearchPage attribute/method test_ui_smoke.py touches by name.
    @property
    def search_artist_edit(self) -> QLineEdit:
        return self._search_page.search_artist_edit

    @property
    def search_title_edit(self) -> QLineEdit:
        return self._search_page.search_title_edit

    @property
    def search_status_label(self) -> QLabel:
        return self._search_page.search_status_label

    @property
    def search_results_table(self) -> QTableWidget:
        return self._search_page.search_results_table

    @property
    def download_best_button(self) -> QPushButton:
        return self._search_page.download_best_button

    def _on_search_clicked(self) -> None:
        self._search_page._on_search_clicked()

    def _render_search_results(
            self, artist: str, title: str, files: list[SoulseekFile],
    ) -> None:
        self._search_page._render_search_results(artist, title, files)

    # Same temporary-delegation pattern for every SharingPage attribute/
    # method test_ui_smoke.py touches by name.
    @property
    def sharing_summary_label(self) -> QLabel:
        return self._sharing_page.sharing_summary_label

    @property
    def sharing_locations_table(self) -> QTableWidget:
        return self._sharing_page.sharing_locations_table

    @property
    def sharing_uploads_table(self) -> QTableWidget:
        return self._sharing_page.sharing_uploads_table

    def _render_sharing_locations_table(
            self, reconciliation: list[LocationShareState],
    ) -> None:
        self._sharing_page._render_sharing_locations_table(reconciliation)

    def _render_sharing_uploads_table(
            self, uploads: list[UploadStatus],
    ) -> None:
        self._sharing_page._render_sharing_uploads_table(uploads)

    # Same temporary-delegation pattern for every DownloadsPage
    # attribute test_ui_smoke.py touches by name, plus `_eta_tracker`/
    # `_active_downloads_count` — neither is a widget, but both are
    # read directly off a fresh MainWindow instance by existing tests
    # (window._eta_tracker.record(...), window._active_downloads_count),
    # same as History/Search/Sharing's own private-attribute reads.
    @property
    def downloads_table(self) -> QTableWidget:
        return self._downloads_page.downloads_table

    @property
    def downloads_eta_label(self) -> QLabel:
        return self._downloads_page.downloads_eta_label

    @property
    def _eta_tracker(self) -> DownloadEtaTracker:
        return self._downloads_page._eta_tracker

    @property
    def _active_downloads_count(self) -> int:
        return self._downloads_page.active_downloads_count

    # Same temporary-delegation pattern for every DashboardPage
    # attribute test_ui_smoke.py touches by name, plus `selected_
    # playlist` (a real read/write attribute, not a widget — needs a
    # setter too, since existing tests assign it directly on a fresh
    # MainWindow instance) and `_track_empty_panel` (a private widget
    # reference a couple of tests compare identity against).
    @property
    def next_step_notice(self) -> InlineNotice:
        return self._dashboard_page.next_step_notice

    @property
    def dashboard_notice(self) -> InlineNotice:
        return self._dashboard_page.dashboard_notice

    @property
    def playlist_list(self) -> QListWidget:
        return self._dashboard_page.playlist_list

    @property
    def track_table(self) -> QTableWidget:
        return self._dashboard_page.track_table

    @property
    def track_table_card(self) -> QWidget:
        return self._dashboard_page.track_table_card

    @property
    def track_area_stack(self) -> QStackedWidget:
        return self._dashboard_page.track_area_stack

    @property
    def _track_empty_panel(self) -> QWidget:
        return self._dashboard_page._track_empty_panel

    @property
    def track_empty_label(self) -> QLabel:
        return self._dashboard_page.track_empty_label

    @property
    def sync_tracks_button(self) -> QPushButton:
        return self._dashboard_page.sync_tracks_button

    @property
    def status_label(self) -> QLabel:
        return self._dashboard_page.status_label

    @property
    def download_button(self) -> QPushButton:
        return self._dashboard_page.download_button

    @property
    def sync_button(self) -> QPushButton:
        return self._dashboard_page.sync_button

    @property
    def scan_button(self) -> QPushButton:
        return self._dashboard_page.scan_button

    @property
    def match_button(self) -> QPushButton:
        return self._dashboard_page.match_button

    @property
    def selected_playlist(self) -> Playlist | None:
        return self._dashboard_page.selected_playlist

    @selected_playlist.setter
    def selected_playlist(self, value: Playlist | None) -> None:
        self._dashboard_page.selected_playlist = value

    # Same temporary-delegation pattern for every TaggingPanel
    # attribute test_ui_smoke.py touches by name. TaggingPanel is a
    # sub-widget of DashboardPage rather than its own registered page,
    # so the delegation is two hops (MainWindow -> DashboardPage ->
    # TaggingPanel) rather than one.
    @property
    def analyze_audio_checkbox(self) -> QCheckBox:
        return self._dashboard_page._tagging_panel.analyze_audio_checkbox

    @property
    def bpm_min_edit(self) -> QLineEdit:
        return self._dashboard_page._tagging_panel.bpm_min_edit

    @property
    def bpm_max_edit(self) -> QLineEdit:
        return self._dashboard_page._tagging_panel.bpm_max_edit

    @property
    def force_retag_checkbox(self) -> QCheckBox:
        return self._dashboard_page._tagging_panel.force_retag_checkbox

    @property
    def tag_selected_button(self) -> QPushButton:
        return self._dashboard_page._tagging_panel.tag_selected_button

    @property
    def tag_playlist_button(self) -> QPushButton:
        return self._dashboard_page._tagging_panel.tag_playlist_button

    @property
    def fix_missing_art_button(self) -> QPushButton:
        return self._dashboard_page._tagging_panel.fix_missing_art_button

    @property
    def fill_missing_art_urls_button(self) -> QPushButton:
        return self._dashboard_page._tagging_panel.fill_missing_art_urls_button

    @property
    def rename_files_button(self) -> QPushButton:
        return self._dashboard_page._tagging_panel.rename_files_button

    @property
    def tagging_results(self) -> QPlainTextEdit:
        return self._dashboard_page._tagging_panel.tagging_results

    @property
    def tagging_controls_layout(self) -> FlowLayout:
        return self._dashboard_page._tagging_panel.tagging_controls_layout

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
        self._refresh_duplicates_locations()
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
        self._poll_selected_playlist()
        self._downloads_page._poll_active_downloads()
        self._review_page._poll_review_items()
        self._render_activity_strip()

    def _update_nav_badge(self, key: str, count: int) -> None:
        label = dict(_NAV_PAGES).get(key) or key.capitalize()
        button = self._nav_buttons[key]
        button.setText(f"{label}  ({count})" if count > 0 else label)

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

    # Roadmap item 9.3 (round 8, Phase 6) — temporary delegating
    # methods for DashboardPage's own _render_tag_result/
    # _on_retag_track_clicked (themselves delegating to TaggingPanel),
    # called directly on a fresh MainWindow instance by test_ui_smoke.py.
    def _render_tag_result(self, result: dict[str, Any]) -> None:
        self._dashboard_page._render_tag_result(result)

    def _on_retag_track_clicked(self, track_id: str) -> None:
        self._dashboard_page._on_retag_track_clicked(track_id)

    def _build_duplicates_content(self) -> QWidget:
        # Fingerprint computation + clustering/scoring were built and
        # live-verified first, read-only, per roadmap item 5's own
        # build order; the delete action below (item 40) is the later,
        # explicitly-scoped follow-up. Scoped to one library location
        # at a time (the location combo below), never merged across all
        # of them.
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        # Roadmap item 56 Phase 6.4 — persistent, cumulative, and
        # celebratory. Hidden entirely at zero — "an empty milestone is
        # worse than no milestone" (the brief's own framing, matching
        # this app's existing "blank, not a misleading control"
        # precedent for a genuinely-nothing-to-show state).
        self.duplicates_milestone_label = QLabel("")
        self.duplicates_milestone_label.hide()
        layout.addWidget(self.duplicates_milestone_label)

        controls = QHBoxLayout()

        self.duplicates_location_combo = QComboBox()
        self.duplicates_location_combo.setToolTip(
            help_text.TOOLTIP_DUPLICATES_LOCATION_COMBO
        )
        self.duplicates_location_combo.currentIndexChanged.connect(
            self._on_duplicates_location_changed
        )
        controls.addWidget(self.duplicates_location_combo)

        # Roadmap item 77 (P9) — the combo above used to be disabled in
        # folder-scope mode (reversed: see item 68 Phase 7.2's original
        # comment here, and CLAUDE.md item 77). It stays enabled now —
        # once resolve_folder_scopes() does most-specific-wins matching
        # (P8.2), the selected location is a genuinely useful tiebreak
        # preference for an ambiguous (nested-location) folder, not
        # dead weight the user had to uncheck-then-recheck around.
        self.duplicates_folders_checkbox = QCheckBox("Only these folders…")
        self.duplicates_folders_checkbox.setToolTip(
            help_text.TOOLTIP_DUPLICATES_FOLDERS_CHECKBOX
        )
        self.duplicates_folders_checkbox.toggled.connect(
            self._on_duplicates_folders_toggled
        )
        controls.addWidget(self.duplicates_folders_checkbox)

        self.compute_fingerprints_button = QPushButton("Compute fingerprints")
        self.compute_fingerprints_button.setToolTip(
            help_text.TOOLTIP_COMPUTE_FINGERPRINTS
        )
        self.compute_fingerprints_button.clicked.connect(
            self._on_compute_fingerprints_clicked
        )
        controls.addWidget(self.compute_fingerprints_button)

        self.find_duplicates_button = QPushButton("Find duplicates")
        self.find_duplicates_button.setToolTip(
            help_text.TOOLTIP_FIND_DUPLICATES
        )
        self.find_duplicates_button.clicked.connect(
            self._on_find_duplicates_clicked
        )
        controls.addWidget(self.find_duplicates_button)

        layout.addLayout(controls)

        # Roadmap item 68 (Phase 7.2) — hidden by default; shown only
        # when "Only these folders…" is checked. A plain QListWidget of
        # real absolute paths, resolved against registered locations
        # only at scope-count/run time (resolve_folder_scopes), not on
        # every add — an unregistered folder is a run-time error, not
        # something that blocks merely listing it.
        self.duplicates_folders_panel = QWidget()
        folders_panel_layout = QVBoxLayout(self.duplicates_folders_panel)
        folders_panel_layout.setContentsMargins(0, 0, 0, 0)

        self.duplicates_folders_list = QListWidget()
        folders_panel_layout.addWidget(
            theme.make_card(self.duplicates_folders_list)
        )

        folders_buttons_row = QHBoxLayout()

        self.duplicates_add_folder_button = QPushButton("Add folder…")
        self.duplicates_add_folder_button.setToolTip(
            help_text.TOOLTIP_DUPLICATES_ADD_FOLDER
        )
        self.duplicates_add_folder_button.clicked.connect(
            self._on_add_duplicates_folder_clicked
        )
        folders_buttons_row.addWidget(self.duplicates_add_folder_button)

        self.duplicates_remove_folder_button = QPushButton("Remove selected")
        self.duplicates_remove_folder_button.setToolTip(
            help_text.TOOLTIP_DUPLICATES_REMOVE_FOLDER
        )
        self.duplicates_remove_folder_button.clicked.connect(
            self._on_remove_duplicates_folder_clicked
        )
        folders_buttons_row.addWidget(self.duplicates_remove_folder_button)

        folders_panel_layout.addLayout(folders_buttons_row)

        # Shown BEFORE a real, potentially ~10-minute-at-real-scale run
        # (item 39's own real number) — see
        # help_text.format_duplicates_scope_count's own docstring.
        self.duplicates_scope_count_label = QLabel("")
        folders_panel_layout.addWidget(self.duplicates_scope_count_label)

        self.duplicates_folders_panel.setVisible(False)
        layout.addWidget(self.duplicates_folders_panel)

        duplicates_status_row = QHBoxLayout()
        self.duplicates_status_label = QLabel("")
        duplicates_status_row.addWidget(self.duplicates_status_label)
        duplicates_status_row.addStretch()
        # Roadmap item R3.2 — "Resolve all groups". Real count set in
        # _render_duplicate_groups, never stale against the table.
        self.resolve_all_duplicates_button = QPushButton("Resolve all groups")
        self.resolve_all_duplicates_button.setToolTip(
            help_text.TOOLTIP_RESOLVE_ALL_DUPLICATES
        )
        self.resolve_all_duplicates_button.setEnabled(False)
        self.resolve_all_duplicates_button.clicked.connect(
            self._on_resolve_all_duplicates_clicked
        )
        duplicates_status_row.addWidget(self.resolve_all_duplicates_button)
        layout.addLayout(duplicates_status_row)

        self.duplicates_table = QTableWidget(
                0,
                len(_DUPLICATES_COLUMN_HEADERS),
        )
        self.duplicates_table.setHorizontalHeaderLabels(
            _DUPLICATES_COLUMN_HEADERS
        )
        theme.apply_table_defaults(self.duplicates_table)
        layout.addWidget(theme.make_card(self.duplicates_table))
        self._configure_duplicates_columns()

        # QButtonGroup instances (one per duplicate group, so only one
        # radio per group can be selected) have no Qt parent-child
        # ownership tie to the table cells their radios live in -- kept
        # alive here for the same reason ui/workers.py's _callbacks
        # keeps a Worker reference until its own completion, and item
        # 22's docstring on that pattern more generally: a Qt object
        # with nothing else referencing it is a live GC/use-after-free
        # hazard, not just a style preference. Reset on every render.
        self._duplicate_button_groups: list[QButtonGroup] = []
        self._current_duplicate_groups: list[DuplicateGroup] = []
        # Roadmap item R2.2 — same rebuild-destroys-state bug as R2.1,
        # for the Duplicates "keep" radio selection: a group has no
        # stable id of its own (it's recomputed fresh by clustering, or
        # locally re-derived after a delete — see
        # _on_delete_duplicates_finished), so the group's OWN set of
        # member local_file ids is used as the key instead — stable
        # across the poll rebuild and across a local re-render, since
        # neither changes which files belong to a still-open group.
        # Value is the checked button's id — either a real
        # local_file.id or the KEEP_ALL_DUPLICATES_ID sentinel. Pruned
        # to only still-present groups on every render (R2.3).
        self._duplicates_keep_selection: dict[frozenset[int], int] = {}
        self._current_duplicates_location_name: str | None = None
        self._duplicates_locations_by_name: dict[str, LibraryLocation] = {}
        # Roadmap item 68 (Phase 7.2) — resolved by local_file.location_id
        # at render time so the LOCATION column (and the delete flow's
        # own path resolution below) reads correctly per-file even for a
        # pooled, cross-location folder-scope result — a single "current
        # location" no longer holds for those.
        self._duplicates_locations_by_id: dict[int, LibraryLocation] = {}
        # Persisted across page shows deliberately (never reset in
        # _on_page_changed) — same "don't lose it on every revisit"
        # precedent as the location combo's own selection.
        self._duplicates_folder_paths: list[str] = []

        return tab

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
            self._refresh_duplicates_locations()
            self._refresh_duplicates_milestone()

        if index == self._sharing_page_index:
            self._sharing_page._sharing_page_visited = True
            self._sharing_page._refresh_sharing()

        if index == self._history_page_index and not self._history_loaded:
            self._history_loaded = True
            self._history_page._refresh_history()

    def _refresh_duplicates_locations(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.library_service.list_locations,
            on_finished=self._render_duplicates_locations,
        )

    def _refresh_duplicates_milestone(self) -> None:
        run_worker(
            self.thread_pool,
            self.application.duplicate_service.get_cleanup_totals,
            on_finished=self._render_duplicates_milestone,
        )

    def _render_duplicates_milestone(self, totals: tuple[int, int]) -> None:
        files_deleted, bytes_freed = totals

        if bytes_freed == 0 and files_deleted == 0:
            self.duplicates_milestone_label.hide()
            return

        self.duplicates_milestone_label.setText(
            f"You've reclaimed {format_file_size(bytes_freed)} across "
            f"{files_deleted} file{'s' if files_deleted != 1 else ''}."
        )
        self.duplicates_milestone_label.show()

    def _render_duplicates_locations(
            self,
            locations: list[tuple[Any, bool]],
    ) -> None:
        # Preserve the current selection across a refresh (Phase 6.1)
        # when that location still exists — losing it on every page
        # revisit would be a real regression of its own.
        previously_selected = self._selected_duplicates_location()

        self.duplicates_location_combo.clear()
        # Roadmap item 56 Phase 6.3/6.4 — the real LibraryLocation
        # (path for the delete-confirmation dialog's exact full paths
        # and the table's own Location column; id for the reclaimed-
        # space milestone's cleanup record). Neither is carried on
        # LocalFile/DuplicateFile at all (only location_id, and not
        # even that on the milestone side), and find_duplicate_groups()
        # is already scoped to one location per call, so this is
        # resolved once here rather than plumbed through the service
        # layer.
        self._duplicates_locations_by_name = {
            location.name: location for location, _ in locations
        }
        self._duplicates_locations_by_id = {
            location.id: location
            for location, _ in locations
            if location.id is not None
        }

        for location, _ in locations:
            self.duplicates_location_combo.addItem(
                location.name, location.name
            )

        if previously_selected is not None:
            index = self.duplicates_location_combo.findData(
                previously_selected
            )
            if index >= 0:
                self.duplicates_location_combo.setCurrentIndex(index)

    def _selected_duplicates_location(self) -> str | None:
        name = self.duplicates_location_combo.currentData()
        return str(name) if name is not None else None

    def _selected_duplicates_location_id(self) -> int | None:
        # Roadmap item 77 (P9) — the combo stays enabled in folder-scope
        # mode now, and its selection is passed through as
        # resolve_folder_scopes()'s tiebreak preference (P8.2) rather
        # than being dead weight while checked.
        name = self._selected_duplicates_location()
        if name is None:
            return None
        location = self._duplicates_locations_by_name.get(name)
        return location.id if location else None

    def _selected_duplicates_folders(self) -> list[str]:
        if not self.duplicates_folders_checkbox.isChecked():
            return []
        return list(self._duplicates_folder_paths)

    def _on_duplicates_folders_toggled(self, checked: bool) -> None:
        self.duplicates_folders_panel.setVisible(checked)
        self._refresh_duplicates_folder_scope_count()

    def _on_duplicates_location_changed(self) -> None:
        # Roadmap item 77 (P9) — a location-combo change can change
        # which real location a tied folder scope resolves to (P8.2's
        # tiebreak), so the scope count must reflect it live, not just
        # sit stale until the next folder is added/removed.
        self._refresh_duplicates_folder_scope_count()

    def _on_add_duplicates_folder_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose a folder to add to the scope"
        )

        if not path or path in self._duplicates_folder_paths:
            return

        self._duplicates_folder_paths.append(path)
        self.duplicates_folders_list.addItem(path)
        self._refresh_duplicates_folder_scope_count()

    def _on_remove_duplicates_folder_clicked(self) -> None:
        for item in self.duplicates_folders_list.selectedItems():
            path = item.text()
            self.duplicates_folders_list.takeItem(
                self.duplicates_folders_list.row(item)
            )
            if path in self._duplicates_folder_paths:
                self._duplicates_folder_paths.remove(path)

        self._refresh_duplicates_folder_scope_count()

    def _refresh_duplicates_folder_scope_count(self) -> None:
        if (
                not self.duplicates_folders_checkbox.isChecked()
                or not self._duplicates_folder_paths
        ):
            self.duplicates_scope_count_label.setText("")
            return

        folders = list(self._duplicates_folder_paths)
        preferred_location_id = self._selected_duplicates_location_id()

        def compute_summary() -> Any:
            service = self.application.duplicate_service
            scopes = service.resolve_folder_scopes(
                folders, preferred_location_id=preferred_location_id,
            )
            return service.summarize_scopes(scopes)

        run_worker(
            self.thread_pool, compute_summary,
            on_finished=lambda summary: self.duplicates_scope_count_label.setText(
                help_text.format_duplicates_scope_count(summary)
            ),
            on_error=self.duplicates_scope_count_label.setText,
        )

    def _on_compute_fingerprints_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            preferred_location_id = self._selected_duplicates_location_id()
            self._run_busy_worker(
                "compute_fingerprints", self.compute_fingerprints_button,
                lambda progress: self._compute_fingerprints_for_folders(
                    folders, progress, preferred_location_id,
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._render_fingerprint_result,
                reports_progress=True,
            )
            self.duplicates_status_label.setText(
                f"Computing fingerprints for {len(folders)} folder(s)..."
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        self._run_busy_worker(
            "compute_fingerprints", self.compute_fingerprints_button,
            lambda progress: (
                self.application.duplicate_service.compute_fingerprints(
                    location_name, progress=progress,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_fingerprint_result,
            reports_progress=True,
        )
        self.duplicates_status_label.setText(
            f"Computing fingerprints for '{location_name}'..."
        )

    def _compute_fingerprints_for_folders(
            self,
            folders: list[str],
            progress: Callable[[str, int, int], None],
            preferred_location_id: int | None = None,
    ) -> dict[str, Any]:
        # Roadmap item 68 (Phase 7.2/7.3) — compute_fingerprints() is
        # itself scoped to one library location per call; folder mode
        # can span more than one (find_duplicate_groups_across_scopes'
        # own cross-location pooling), so this groups the resolved
        # scopes by location, calls it once per location, and translates
        # each call's own 1..N progress into a running offset against
        # the real combined total — so the activity strip still reads
        # 1..total once, not resetting partway through.
        service = self.application.duplicate_service
        scopes = service.resolve_folder_scopes(
            folders, preferred_location_id=preferred_location_id,
        )
        total = service.count_files_for_scopes(scopes)

        folders_by_location: dict[str, list[str]] = {}
        for scope in scopes:
            folders_by_location.setdefault(
                scope.location.name, [],
            ).append(scope.folder_relative_path)

        combined: dict[str, Any] = {
            "computed": 0,
            "skipped_already_computed": 0,
            "failed": 0,
            "details": [],
        }
        completed_before = 0

        for location_name, relative_folders in folders_by_location.items():
            def report(
                    stage: str, current: int, _total: int,
                    offset: int = completed_before,
            ) -> None:
                progress(stage, offset + current, total)

            result = service.compute_fingerprints(
                location_name, folders=relative_folders, progress=report,
            )
            combined["computed"] += result["computed"]
            combined["skipped_already_computed"] += (
                result["skipped_already_computed"]
            )
            combined["failed"] += result["failed"]
            combined["details"].extend(result["details"])
            completed_before += (
                result["computed"]
                + result["skipped_already_computed"]
                + result["failed"]
            )

        return combined

    def _render_fingerprint_result(self, result: dict[str, Any]) -> None:
        self.duplicates_status_label.setText(
            help_text.format_fingerprint_result_message(result)
        )

    def _on_find_duplicates_clicked(self) -> None:
        folders = self._selected_duplicates_folders()

        if folders:
            # No single location applies to a pooled, possibly
            # cross-location result — _render_duplicate_groups resolves
            # each row's location individually via
            # _duplicates_locations_by_id instead.
            self._current_duplicates_location_name = None
            preferred_location_id = self._selected_duplicates_location_id()

            self._run_busy_worker(
                "find_duplicates", self.find_duplicates_button,
                lambda progress: (
                    self.application.duplicate_service
                    .find_duplicate_groups_across_scopes(
                        self.application.duplicate_service
                        .resolve_folder_scopes(
                            folders,
                            preferred_location_id=preferred_location_id,
                        ),
                        progress=progress,
                    )
                ),
                status_label=self.duplicates_status_label,
                on_finished=self._render_duplicate_groups,
                reports_progress=True,
            )
            self.duplicates_status_label.setText(
                f"Searching for duplicates in {len(folders)} folder(s)..."
            )
            return

        location_name = self._selected_duplicates_location()

        if location_name is None:
            self.duplicates_status_label.setText(
                "Select a library location first."
            )
            return

        # Roadmap item 56 Phase 6.3 — the delete-confirmation dialog's
        # full paths need a real location; captured here rather than
        # re-read from the combo later, so a combo selection change
        # while this search is still running can't attach the wrong
        # location name to the results it eventually renders. (The
        # LOCATION column itself resolves per-file, not from this — see
        # item 68.)
        self._current_duplicates_location_name = location_name

        self._run_busy_worker(
            "find_duplicates", self.find_duplicates_button,
            lambda progress: (
                self.application.duplicate_service.find_duplicate_groups(
                    location_name, progress=progress,
                )
            ),
            status_label=self.duplicates_status_label,
            on_finished=self._render_duplicate_groups,
            reports_progress=True,
        )
        self.duplicates_status_label.setText(
            f"Searching for duplicates in '{location_name}'..."
        )

    def _on_duplicates_keep_toggled(
            self, group_key: frozenset[int], button_id: int, checked: bool,
    ) -> None:
        if checked:
            self._duplicates_keep_selection[group_key] = button_id

    def _render_duplicate_groups(self, groups: list[DuplicateGroup]) -> None:
        self._duplicate_button_groups = []
        # Kept so a single-group resolution can drop just that group and
        # re-render locally afterward — see _on_delete_duplicates_finished's
        # own docstring for why re-fetching via find_duplicate_groups()
        # after every resolution is not an option at real scale.
        self._current_duplicate_groups = groups

        # Roadmap item 73 (P4) — setRowCount() does NOT clear spans, so
        # a stale span from a PREVIOUS render (different group shapes)
        # could silently hide a real Actions widget under a new row that
        # happens to land inside an old span's coverage. Confirmed via
        # grep: this was never called anywhere in this file before.
        self.duplicates_table.clearSpans()

        # Roadmap item R2.3 — prune selection state for groups no
        # longer present (resolved, or no longer clustered together).
        # Runs even for an empty `groups` list (the early-return branch
        # right below) — a "no duplicates found" render must not leave
        # stale selections sitting in the map forever either.
        live_group_keys = {
            frozenset(f.local_file.id for f in group.files)
            for group in groups
        }
        self._duplicates_keep_selection = {
            key: value
            for key, value in self._duplicates_keep_selection.items()
            if key in live_group_keys
        }

        self.resolve_all_duplicates_button.setEnabled(len(groups) > 0)
        self.resolve_all_duplicates_button.setText(
            f"Resolve all groups ({len(groups)})" if groups
            else "Resolve all groups"
        )

        if not groups:
            self.duplicates_table.setRowCount(0)
            self.duplicates_status_label.setText(
                "No duplicates found. Run Compute fingerprints first if "
                "you haven't yet."
            )
            return

        self.duplicates_status_label.setText(
            f"Found {len(groups)} duplicate group(s)."
        )

        total_rows = sum(len(group.files) for group in groups)
        self.duplicates_table.setRowCount(total_rows)

        # Roadmap item 73 (P4) — every real Actions widget built this
        # render, so its true widest sizeHint() can size the ACTIONS
        # column for real below (a per-group extra button — see
        # _build_duplicate_group_actions — means this isn't always the
        # same width for every group).
        action_widgets: list[QWidget] = []

        row = 0
        for group_index, group in enumerate(groups, start=1):
            # group.files is already ranked best-quality-first (see
            # DuplicateGroup's own docstring) -- files[0] is this
            # group's own recommendation for which copy to keep,
            # pre-selected below but never auto-applied: the radio can
            # still be moved to any other file in the group before
            # Delete is ever clicked.
            button_group = QButtonGroup(self.duplicates_table)
            self._duplicate_button_groups.append(button_group)
            group_first_row = row

            # Roadmap item R2.2 — this group's stable key (its own
            # member file ids) and whatever was selected for it before
            # the last rebuild, if anything. Recorded back into the map
            # on every real toggle, not just read once here — the user
            # can change their mind more than once before Delete.
            group_key = frozenset(
                f.local_file.id for f in group.files
                if f.local_file.id is not None
            )
            previously_selected_id = self._duplicates_keep_selection.get(
                group_key
            )
            button_group.idToggled.connect(
                lambda button_id, checked, group_key=group_key: (
                    self._on_duplicates_keep_toggled(
                        group_key, button_id, checked,
                    )
                )
            )

            for file_index, duplicate_file in enumerate(group.files):
                local_file = duplicate_file.local_file
                quality = duplicate_file.quality
                assert local_file.id is not None

                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.GROUP,
                    QTableWidgetItem(str(group_index)),
                )
                # Location + full relative path (roadmap item 56 Phase
                # 6.3) — "the same file in two folders" is a judgement
                # the user needs the real path to make, not just a
                # bare filename. Resolved PER FILE (roadmap item 68,
                # Phase 7.2) rather than from one outer variable — a
                # pooled, cross-location folder-scope result can put
                # files from two different real locations in the same
                # group.
                file_location = self._duplicates_locations_by_id.get(
                    local_file.location_id
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.LOCATION,
                    QTableWidgetItem(
                        file_location.name if file_location else "—"
                    ),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.PATH,
                    QTableWidgetItem(local_file.relative_path),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.FORMAT,
                    QTableWidgetItem(local_file.format),
                )
                bitrate_text = (
                    f"{quality.bitrate_kbps} kbps"
                    if quality.bitrate_kbps
                    else "—"
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.BITRATE,
                    QTableWidgetItem(bitrate_text),
                )
                self.duplicates_table.setItem(
                    row, _DuplicatesColumn.SIMILARITY,
                    QTableWidgetItem(f"{group.similarity:.1%}"),
                )

                keep_radio = QRadioButton()
                keep_radio.setToolTip(help_text.TOOLTIP_KEEP_FILE_RADIO)
                # Roadmap item R2.2 — restore the user's own prior
                # selection for this group when there is one; only fall
                # back to the "best quality first" default when nothing
                # was ever chosen for it.
                keep_radio.setChecked(
                    local_file.id == previously_selected_id
                    if previously_selected_id is not None
                    else file_index == 0
                )
                # The button's own id IS the local_file_id -- checkedId()
                # below reads it back directly, no separate id-to-file
                # mapping needed.
                button_group.addButton(keep_radio, id=local_file.id)
                self.duplicates_table.setCellWidget(
                    row, _DuplicatesColumn.KEEP, keep_radio,
                )

                row += 1

            # Roadmap item 77 (P7, 5th report) -- setSpan() BEFORE
            # setCellWidget() for the group's first row, so the real
            # widget's geometry is computed against the final spanned
            # rect, not a single-cell rect that a later setSpan() call
            # then silently changes underneath it. And no widget of any
            # kind (blank or otherwise) goes on the covered rows: a
            # blank QWidget() there used to get resolved by Qt's own
            # span geometry to the EXACT SAME rect as the real widget
            # (visualRect() resolves every cell inside a span to the
            # whole span's rect) and, being added to the viewport
            # later, painted over it -- confirmed live via
            # childAt(center of the Actions cell) returning the blank
            # widget, not the real one, before this fix. The span
            # itself is what makes the covered rows read as blank; no
            # cell widget is needed there at all.
            self.duplicates_table.setSpan(
                group_first_row, _DuplicatesColumn.ACTIONS,
                len(group.files), 1,
            )
            group_actions_widget = self._build_duplicate_group_actions(
                group, button_group, previously_selected_id,
            )
            action_widgets.append(group_actions_widget)
            self.duplicates_table.setCellWidget(
                group_first_row, _DuplicatesColumn.ACTIONS,
                group_actions_widget,
            )

        self._size_duplicates_columns(action_widgets)

    def _configure_duplicates_columns(self) -> None:
        """Roadmap item 73 (P4) — a real, live-measured floor for the
        Actions column, closing the actual reported bug: at the app's
        real 960x640 minimum window size, against real production
        duplicate groups, this widget's own visibleRegion() was
        confirmed (0,0,0,0) — fully invisible, not merely clipped —
        because NOTHING in this app ever set a column width, so
        Actions (column 7 of 8) got whatever tiny sliver
        setStretchLastSection's leftover-space math happened to leave
        it. Fixed mode + an explicit width DERIVED from the real
        widget's own sizeHint() (never a magic number) makes this
        column immune to that squeeze regardless of window width.

        Roadmap item E2 (round 7) — split off from `_size_duplicates_
        columns` so an empty table gets this layout at construction,
        not only on its first populated render.
        """
        theme.configure_columns(self.duplicates_table, _DUPLICATES_COLUMNS)

    def _size_duplicates_columns(
            self, action_widgets: list[QWidget],
    ) -> None:
        theme.size_columns(
            self.duplicates_table, _DUPLICATES_COLUMNS, action_widgets,
        )

    def _build_duplicate_group_actions(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
            previously_selected_id: int | None,
    ) -> QWidget:
        # Roadmap item 56 Phase 6.3 — "the same file living in several
        # folders is sometimes deliberate." An additional button in the
        # group's EXISTING QButtonGroup (a sentinel id, not a separate
        # control/group) so the "selecting one deselects the others"
        # behavior is preserved and simply extended, not reimplemented.
        keep_all_radio = QRadioButton("Keep all")
        keep_all_radio.setToolTip(help_text.TOOLTIP_KEEP_ALL_DUPLICATES_RADIO)
        # Roadmap item R2.2 — same preserved-selection treatment as the
        # per-file keep radios above.
        keep_all_radio.setChecked(
            previously_selected_id == KEEP_ALL_DUPLICATES_ID
        )
        button_group.addButton(keep_all_radio, id=KEEP_ALL_DUPLICATES_ID)

        confirm_checkbox = QCheckBox("Confirm delete")
        confirm_checkbox.setToolTip(
            help_text.TOOLTIP_DELETE_DUPLICATES_CHECKBOX
        )

        delete_button = QPushButton("Delete")
        delete_button.setToolTip(help_text.TOOLTIP_DELETE_DUPLICATES_BUTTON)
        delete_button.clicked.connect(
            lambda: self._on_delete_duplicates_clicked(
                group, button_group, confirm_checkbox, delete_button,
            )
        )

        def _update_delete_enabled() -> None:
            # "Keep all" selected means there is nothing to delete.
            delete_button.setEnabled(
                button_group.checkedId() != KEEP_ALL_DUPLICATES_ID
            )

        button_group.buttonToggled.connect(
            lambda _button, _checked: _update_delete_enabled()
        )
        _update_delete_enabled()

        return theme.cell_widget(
                keep_all_radio,
                confirm_checkbox,
                delete_button,
        )

    def _on_delete_duplicates_clicked(
            self,
            group: DuplicateGroup,
            button_group: QButtonGroup,
            confirm_checkbox: QCheckBox,
            button: QPushButton,
    ) -> None:
        if not confirm_checkbox.isChecked():
            # The standing rule against touching a file without
            # confirmation applies in full here: a click alone is only
            # the FIRST signal (which file to keep); the checkbox is
            # the second, explicit one, mirroring the Review tab's own
            # Replace + "Delete old file" checkbox pair. Neither one
            # alone deletes anything.
            self.duplicates_status_label.setText(
                "Check \"Confirm delete\" before deleting duplicate "
                "files."
            )
            return

        keep_id = button_group.checkedId()

        if keep_id == KEEP_ALL_DUPLICATES_ID:
            # Defense in depth — the Delete button is already disabled
            # in this state, but nothing structurally prevents this
            # method being reached some other way.
            return

        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        # Roadmap item 68 (Phase 7.2) — resolved PER FILE via
        # local_file.location_id rather than one "current location":
        # a pooled, cross-location folder-scope group can hold files
        # from more than one real registered location.
        # Roadmap item 56 Phase 6.3 — deleting real user files warrants
        # naming them: the exact full paths about to be deleted, not
        # just a bare count, in a second, explicit confirmation.
        paths_to_delete = [
            str(
                Path(
                    self._duplicates_locations_by_id[
                        duplicate_file.local_file.location_id
                    ].path
                ) / duplicate_file.local_file.relative_path
            )
            for duplicate_file in group.files
            if duplicate_file.local_file.id in delete_ids
            and duplicate_file.local_file.location_id
            in self._duplicates_locations_by_id
        ]

        # Purely informational provenance on the resulting
        # duplicate_cleanups row (DuplicateService.delete_local_files'
        # own docstring) — the KEPT file's location is the most
        # meaningful single answer to "where did this cleanup happen"
        # for a pooled, possibly cross-location group.
        keep_duplicate_file = next(
            (
                duplicate_file for duplicate_file in group.files
                if duplicate_file.local_file.id == keep_id
            ),
            None,
        )
        location_id = (
            keep_duplicate_file.local_file.location_id
            if keep_duplicate_file is not None else None
        )

        confirmed = QMessageBox.question(
            self,
            help_text.DELETE_DUPLICATES_CONFIRM_TITLE,
            help_text.format_delete_duplicates_confirm_body(paths_to_delete),
        )

        if confirmed != QMessageBox.StandardButton.Yes:
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.delete_local_files(
                delete_ids, keep_id, location_id,
            ),
            button=button,
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_delete_duplicates_finished(
                result, group,
            ),
        )

    def _on_delete_duplicates_finished(
            self,
            result: dict[str, Any],
            group: DuplicateGroup,
    ) -> None:
        # Deliberately NOT a find_duplicate_groups() re-fetch after every
        # single-group resolution. That call recomputes the ENTIRE
        # location's clustering from scratch every time, by design (item
        # 39 — never persisted, so a moved/rescanned file can't leave a
        # stale group behind) — real, live-verified cost against a real
        # ~3,100-file/344-group library was ~10 minutes (see
        # docs/HISTORY.md item 39). Re-running that after every single
        # group would make resolving a real library's worth of
        # duplicates one at a time completely impractical (344 groups x
        # ~10 minutes each). Instead, drop just the resolved group from
        # the in-memory list this tab already holds and re-render from
        # that — no backend call at all.
        message = f"Deleted: {result['deleted']}, Failed: {result['failed']}."

        if result["failed"] > 0:
            # A partial failure means the DB/disk state for this group
            # may not actually match "fully resolved" (see
            # DuplicateService.delete_local_files' own per-item
            # semantics) — leave it visible rather than assuming it's
            # gone, so the user can see it's still there and retry.
            self.duplicates_status_label.setText(message)
            return

        self._current_duplicate_groups = [
            g for g in self._current_duplicate_groups if g is not group
        ]
        # _render_duplicate_groups sets its own "Found N group(s)"/"No
        # duplicates found" status text -- overwritten here afterward so
        # the deletion result is what the user actually sees.
        self._render_duplicate_groups(self._current_duplicate_groups)
        self.duplicates_status_label.setText(
            f"{message} {self.duplicates_status_label.text()}"
        )
        # A real deletion just happened (delete_local_files already
        # recorded it) — refresh the milestone total immediately rather
        # than waiting for the next page revisit.
        self._refresh_duplicates_milestone()

    def _build_group_resolution_plan(
            self, group: DuplicateGroup, keep_id: int,
    ) -> tuple[GroupResolutionPlan, str, list[str]] | None:
        """Roadmap item R3.2 — the same per-group plan (real per-file
        location resolution, real absolute paths) `_on_delete_
        duplicates_clicked` builds for a single group, factored out so
        "Resolve all groups" can build the identical plan for every
        group without a second, drifting copy. `None` when there's
        nothing to delete or the keep selection doesn't resolve to a
        real file in this group (shouldn't happen for a real render,
        but never trusted blindly for a batch that deletes real files).
        """
        delete_ids = [
            duplicate_file.local_file.id
            for duplicate_file in group.files
            if duplicate_file.local_file.id is not None
            and duplicate_file.local_file.id != keep_id
        ]

        if not delete_ids:
            return None

        keep_duplicate_file = next(
            (
                duplicate_file for duplicate_file in group.files
                if duplicate_file.local_file.id == keep_id
            ),
            None,
        )

        if keep_duplicate_file is None:
            return None

        location_id = keep_duplicate_file.local_file.location_id
        keep_location = self._duplicates_locations_by_id.get(location_id)
        keep_path = (
            str(
                Path(keep_location.path)
                / keep_duplicate_file.local_file.relative_path
            )
            if keep_location is not None
            else keep_duplicate_file.local_file.relative_path
        )

        delete_paths = [
            str(
                Path(
                    self._duplicates_locations_by_id[
                        duplicate_file.local_file.location_id
                    ].path
                ) / duplicate_file.local_file.relative_path
            )
            for duplicate_file in group.files
            if duplicate_file.local_file.id in delete_ids
            and duplicate_file.local_file.location_id
            in self._duplicates_locations_by_id
        ]

        plan = GroupResolutionPlan(
            delete_local_file_ids=delete_ids,
            keep_local_file_id=keep_id,
            location_id=location_id,
        )

        return plan, keep_path, delete_paths

    def _on_resolve_all_duplicates_clicked(self) -> None:
        # Roadmap item R3.2/R3.3 — built fresh from what's actually on
        # screen right now (the current groups AND the current keep
        # selections), never a stale plan from an earlier click.
        groups = self._current_duplicate_groups

        plans_with_labels: list[
                tuple[GroupResolutionPlan, str, list[str]]
        ] = []
        resolved_groups: list[DuplicateGroup] = []

        for group in groups:
            group_key = frozenset(
                f.local_file.id for f in group.files
                if f.local_file.id is not None
            )
            default_keep_id = (
                group.files[0].local_file.id if group.files else None
            )
            keep_id = self._duplicates_keep_selection.get(
                group_key, default_keep_id,
            )

            if keep_id is None or keep_id == KEEP_ALL_DUPLICATES_ID:
                # "Keep all" (or no resolvable keep target at all) is
                # never turned into a plan — skipped, not overridden.
                continue

            built = self._build_group_resolution_plan(group, keep_id)

            if built is None:
                continue

            plans_with_labels.append(built)
            resolved_groups.append(group)

        dialog = BulkResolveDuplicatesDialog(self, plans_with_labels)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        if not plans_with_labels or not dialog.confirm_checkbox.isChecked():
            # Defense in depth — the confirm button is already disabled
            # in either state, but nothing structurally prevents this
            # method being reached some other way.
            return

        plans = [plan for plan, _, _ in plans_with_labels]

        run_worker(
            self.thread_pool,
            lambda: self.application.duplicate_service.resolve_groups(plans),
            button=self.resolve_all_duplicates_button,
            status_label=self.duplicates_status_label,
            on_finished=lambda result: self._on_bulk_resolve_duplicates_finished(
                result, resolved_groups,
            ),
        )

    def _on_bulk_resolve_duplicates_finished(
            self,
            result: BulkDuplicateResolutionResult,
            attempted_groups: list[DuplicateGroup],
    ) -> None:
        QMessageBox.information(
            self,
            help_text.BULK_RESOLVE_DUPLICATES_DIALOG_TITLE,
            help_text.format_bulk_resolve_duplicates_result(result),
        )

        # Same "drop resolved groups locally, never a full
        # find_duplicate_groups() re-fetch" discipline as the
        # single-group flow (_on_delete_duplicates_finished's own
        # docstring) — a group that partially failed stays visible,
        # per plan_outcomes, so the user can see it's still there and
        # retry rather than assuming it's gone.
        succeeded_groups = {
            id(group)
            for group, succeeded in zip(
                attempted_groups, result.plan_outcomes, strict=True,
            )
            if succeeded
        }
        self._current_duplicate_groups = [
            group for group in self._current_duplicate_groups
            if id(group) not in succeeded_groups
        ]
        self._render_duplicate_groups(self._current_duplicate_groups)

        if result.files_deleted > 0:
            self._refresh_duplicates_milestone()

    # Roadmap item 9.3 (round 8, Phase 6) — temporary delegating
    # methods for DashboardPage's own attributes/methods
    # test_ui_smoke.py touches directly on a fresh MainWindow instance
    # (window._poll_selected_playlist(...), etc.). Deleted, alongside
    # repointing those tests at the page widget directly, at the
    # test-split session (S11, §9.3.4) — not before.
    def _poll_selected_playlist(self) -> None:
        self._dashboard_page._poll_selected_playlist()

    def _render_track_statuses(self, statuses: list[TrackStatus]) -> None:
        self._dashboard_page._render_track_statuses(statuses)

    def _on_track_table_cell_double_clicked(
            self, row: int, column: int,
    ) -> None:
        self._dashboard_page._on_track_table_cell_double_clicked(row, column)

    def _on_track_table_context_menu(self, position: Any) -> None:
        self._dashboard_page._on_track_table_context_menu(position)

    def _render_next_step(self, facts: _NextStepFacts) -> None:
        self._dashboard_page._render_next_step(facts)

    def _on_next_step_action(self, action: str) -> None:
        self._dashboard_page._on_next_step_action(action)

    # Roadmap item 9.3 (round 8, Phase 6) — temporary delegating method
    # for DownloadsPage's own `_render_active_downloads`, called
    # directly on a fresh MainWindow instance by test_ui_smoke.py
    # (window._render_active_downloads(...)). Deleted, alongside
    # repointing those tests at the page widget directly, at the
    # test-split session (S11, §9.3.4) — not before.
    def _render_active_downloads(
            self,
            downloads: list[ActiveDownload],
    ) -> None:
        self._downloads_page._render_active_downloads(downloads)

    # Roadmap item 9.3 (round 8, Phase 6) — temporary delegating
    # methods for ReviewPage's own attributes/methods
    # test_ui_smoke.py touches directly on a fresh MainWindow instance
    # (window._render_review_items(...), etc.). Deleted, alongside
    # repointing those tests at the page widget directly, at the
    # test-split session (S11, §9.3.4) — not before.
    def _render_review_items(
            self,
            data: tuple[
                NeedsReviewCandidates, PendingUpgrades,
                list[NeedsReviewMatch],
            ],
    ) -> None:
        self._review_page._render_review_items(data)

    def _render_needs_review_candidates(
            self,
            candidates: NeedsReviewCandidates,
    ) -> None:
        self._review_page._render_needs_review_candidates(candidates)

    def _render_pending_upgrades(self, upgrades: PendingUpgrades) -> None:
        self._review_page._render_pending_upgrades(upgrades)

    def _render_local_needs_review_matches(
            self,
            matches: list[NeedsReviewMatch],
    ) -> None:
        self._review_page._render_local_needs_review_matches(matches)

    def _on_bulk_replace_upgrades_finished(
            self, result: BulkUpgradeReplaceResult,
    ) -> None:
        self._review_page._on_bulk_replace_upgrades_finished(result)

    @property
    def review_needs_table(self) -> QTableWidget:
        return self._review_page.review_needs_table

    @property
    def review_upgrades_table(self) -> QTableWidget:
        return self._review_page.review_upgrades_table

    @property
    def review_local_table(self) -> QTableWidget:
        return self._review_page.review_local_table

    @property
    def replace_all_upgrades_button(self) -> QPushButton:
        return self._review_page.replace_all_upgrades_button

    @property
    def _upgrade_delete_checked(self) -> set[int]:
        return self._review_page._upgrade_delete_checked

    @property
    def _needs_review_count(self) -> int:
        return self._review_page._needs_review_count

    @property
    def _pending_upgrades_count(self) -> int:
        return self._review_page._pending_upgrades_count

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
            self._poll_selected_playlist()
            # Roadmap item R7.5 — checked on the same real 20s cycle
            # that can actually produce a newly-completed download, not
            # a new timer of its own.
            self._check_for_download_notifications()

        def on_poll_error(_: str) -> None:
            self._backend_poll_in_progress = False
            self._notify_error(
                "Seeker couldn't reach slskd — check that it's running."
            )

        run_worker(
            self.thread_pool,
            self.application.download_service.poll_downloads,
            on_finished=on_poll_finished,
            on_error=on_poll_error,
        )

    # Same temporary-delegation pattern as _render_active_downloads
    # above, for DownloadsPage's own `_record_eta_samples`
    # (window._record_eta_samples(...) in test_ui_smoke.py).
    def _record_eta_samples(self, downloads: list[ActiveDownload]) -> None:
        self._downloads_page._record_eta_samples(downloads)

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
            "sync", self.sync_button,
            self.application.sync_service.sync_playlists,
            status_label=self.status_label,
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
            "scan", self.scan_button,
            self.application.library_service.scan_and_match,
            busy_text="Scanning…",
            status_label=self.status_label,
            on_finished=self._on_scan_and_match_finished,
        )
        self.status_label.setText("Scanning library, then matching tracks…")

    def _on_scan_and_match_finished(self, result: dict[str, int]) -> None:
        self.status_label.setText(
            f"Scanned: {result['added']} added, {result['updated']} "
            f"updated, {result['removed']} removed. "
            f"Matched: {result['auto']} auto, "
            f"{result['needs_review']} needs review, "
            f"{result['unmatched']} unmatched."
        )
        self._poll_selected_playlist()

    def _on_match_clicked(self) -> None:
        self._run_busy_worker(
            "match", self.match_button,
            self.application.track_matcher.match_all,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
        )

    def _set_download_button_busy(self) -> None:
        # Idempotent (BusyActionRegistry.begin() no-ops if already
        # running) — safe to call again at every hop of the download
        # chain below, matching this method's own pre-registry behavior.
        self.busy_actions.begin(
            "download", self.download_button, "Starting download…",
        )
        self._render_activity_strip()

    def _reset_download_button(self) -> None:
        self.busy_actions.end("download")
        self._render_activity_strip()

    def _on_download_clicked(self) -> None:
        if self.selected_playlist is None:
            self.dashboard_notice.show_message(
                "Select a playlist first.", kind="warning",
            )
            return

        playlist = self.selected_playlist
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
            self.dashboard_notice.show_message(
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
            status_label=self.status_label,
            on_finished=self._on_download_finished,
            on_error=lambda _message: self._reset_download_button(),
        )

    def _on_download_finished(self, result: dict[str, Any]) -> None:
        self._reset_download_button()
        self._poll_selected_playlist()

        # Roadmap item 66 (Phase 4.2) — the real fix for "Requested 16,
        # skipped 12 (no candidates found)" when several of those 12 had
        # in fact become real Review candidates: help_text.py's own
        # formatter names each outcome separately rather than folding
        # them into one generic figure.
        message = help_text.format_download_result_message(result)
        kind = "success" if result["requested"] else "info"
        self.dashboard_notice.show_message(message, kind=kind)

    def _on_sync_tracks_clicked(self) -> None:
        if self.selected_playlist is None:
            return

        playlist = self.selected_playlist

        def do_sync() -> Any:
            self.application.sync_service.sync_playlist_tracks(playlist)

        self._run_busy_worker(
            "sync_tracks", self.sync_tracks_button, do_sync,
            status_label=self.status_label,
            on_finished=lambda _: self._poll_selected_playlist(),
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

        self._tray_icon = QSystemTrayIcon(icon, self)
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
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        menu = QMenu()

        self._tray_status_action = menu.addAction("Idle")
        self._tray_status_action.setEnabled(False)
        menu.addSeparator()

        self._tray_pause_action = menu.addAction("Pause downloads")
        self._tray_pause_action.setCheckable(True)
        self._tray_pause_action.setChecked(self.application.downloads_paused)
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
        self.application.set_downloads_paused(checked)
        self._render_tray_menu()

    def _on_tray_open_page(self, key: str) -> None:
        self._on_tray_open_seeker()
        self._show_page(key)

    def _on_tray_check_now(self) -> None:
        self._trigger_backend_poll()

    def _on_tray_open_seeker(self) -> None:
        # Roadmap item E1.4 (round 7) — a deliberate reopen invalidates
        # any still-pending hide-verification check (see
        # `_hide_request_id`'s own comment at its declaration) — without
        # this, a check scheduled by an earlier `closeEvent` could still
        # fire after the user has already reopened the window from here,
        # see it legitimately exposed, and hide it right back out from
        # under them.
        self._hide_request_id += 1
        self._hidden_to_tray = False
        # Roadmap item 116 (round 8, §14.3.3) — order matters: the
        # window must be shown by an app that is already Regular, or it
        # can come up behind other applications.
        _set_dock_icon_visible(True)
        self.showNormal()
        # D4.2 — give back the exact window the user had before it was
        # hidden, rather than whatever `showNormal()` alone resolves to
        # after a fullscreen-exit-then-hide cycle.
        if self._pre_fullscreen_geometry is not None:
            self.setGeometry(self._pre_fullscreen_geometry)
            self._pre_fullscreen_geometry = None
        self.raise_()
        self.activateWindow()
        # Roadmap item R7.6 — the poll methods skip their own work
        # while hidden; catch up immediately on reopen rather than
        # waiting up to POLL_INTERVAL_MS for the next tick to notice
        # the window is visible again.
        self._poll_selected_playlist()
        self._downloads_page._poll_active_downloads()
        self._review_page._poll_review_items()
        self._dashboard_page._poll_next_step()
        self._render_activity_strip()

    def _on_application_state_changed(
            self, state: Qt.ApplicationState,
    ) -> None:
        # Roadmap item 116 (round 8, §14.2) — see the connection's own
        # comment in __init__ for why this signal exists at all. Two
        # things about this guard, both deliberate:
        #
        # ApplicationActive is not reopen-specific — it also fires on
        # ordinary activation (Cmd-Tab, clicking a window), and because
        # Qt passes forcePropagate=true it fires even when the state was
        # already Active. `not self.isVisible()` narrows it to the case
        # that matters; in every other case `_on_tray_open_seeker()`
        # would have been a near-no-op anyway.
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
        if self.isVisible():
            return
        self._on_tray_open_seeker()

    def _on_tray_quit(self) -> None:
        # Roadmap item R7.7 — a real quit request, same as ⌘Q/dock
        # "Quit Seeker". Goes straight to QApplication.quit() (posts a
        # real quit event) rather than self.close() — close() would
        # re-enter this window's own closeEvent, which hides to the
        # tray instead of quitting, exactly the behavior a Quit click
        # must bypass. The actual cleanup lives in
        # cleanup_before_quit(), connected once to QApplication.
        # aboutToQuit in main_ui.py, so it fires for every real quit
        # route uniformly, not just this one.
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def cleanup_before_quit(self) -> None:
        # Roadmap item R7.7 — the one real cleanup path for every quit
        # route (tray Quit, real ⌘Q/dock-quit — both reach here via
        # QApplication.aboutToQuit, connected once in main_ui.py).
        # Deliberately NOT an attempt at roadmap item 70's own open,
        # unresolved stress-test hang — this stops timers/hides the
        # tray icon so a real quit doesn't leave anything running past
        # the window closing, but does not change poll_downloads/
        # fingerprinting internals at all.
        self.poll_timer.stop()
        self.backend_poll_timer.stop()

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
        # GLOBAL QApplication instance, not this window.
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

        if self._tray_icon is not None:
            self._tray_icon.hide()

    def _render_tray_menu(self) -> None:
        if self._tray_icon is None:
            return

        parts = []
        if self._active_downloads_count > 0:
            plural = "s" if self._active_downloads_count != 1 else ""
            parts.append(f"{self._active_downloads_count} downloading{plural}")

        status_text = ", ".join(parts) if parts else "Idle"

        if self.application.downloads_paused:
            status_text += " (paused)"

        self._tray_status_action.setText(status_text)
        self._tray_review_action.setText(
            f"Review ({self._needs_review_count})"
            if self._needs_review_count else "Review"
        )
        self._tray_upgrades_action.setText(
            f"Upgrades ({self._pending_upgrades_count})"
            if self._pending_upgrades_count else "Upgrades"
        )

        # Mirrors the config store, not local UI state — a pause
        # toggled from elsewhere (a future Settings/Dashboard control)
        # must still show correctly here without this menu having
        # caused it. blockSignals so re-syncing the checked state
        # can't itself re-trigger _on_tray_pause_toggled's own save.
        self._tray_pause_action.blockSignals(True)
        self._tray_pause_action.setChecked(self.application.downloads_paused)
        self._tray_pause_action.blockSignals(False)

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
        if self._tray_icon is None or not self._tray_icon.isVisible():
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
            self._show_tray_hide_notice_once()
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
        self.hide()
        self._show_tray_hide_notice_once()
        self._confirm_hidden_to_tray(self._hide_request_id)

    def _show_tray_hide_notice_once(self) -> None:
        # Roadmap item E1 (round 7, corrected after review) — was
        # duplicated (the fullscreen branch above and the ordinary hide
        # path each had their own copy of this, including the
        # user-facing string) — the exact "two implementations of one
        # behavior" shape this project's own CLAUDE.md already warns
        # about (item 104/C3's Dashboard-vs-Downloads progress bar).
        assert self._tray_icon is not None
        if self.application.settings.tray_hide_notice_shown:
            return
        self._tray_icon.showMessage(
            "Seeker",
            "Seeker is still running in the menu bar. Use the menu "
            "bar icon to reopen it, or Quit from there to exit.",
            QSystemTrayIcon.MessageIcon.Information,
        )
        self.application.mark_tray_hide_notice_shown()

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
                if self._tray_icon is not None and self._tray_icon.isVisible():
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
                if (
                        self._tray_icon is not None
                        and self._tray_icon.isVisible()
                ):
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

    def _seed_notification_cutoff(self) -> None:
        # Roadmap item R7.5 — silently records the newest existing
        # HistoryEvent so pre-existing download history never floods a
        # notification the instant the tray icon appears; only a
        # DOWNLOADED event with a NEWER occurred_at than this counts as
        # "new" from here on (get_recent_events sorts newest-first).
        run_worker(
            self.thread_pool,
            lambda: self.application.history_service.get_recent_events(limit=1),
            on_finished=self._on_notification_cutoff_seeded,
        )

    def _on_notification_cutoff_seeded(
            self,
            events: list[HistoryEvent],
    ) -> None:
        if events:
            self._last_notified_download_at = events[0].occurred_at

    def _check_for_download_notifications(self) -> None:
        # Roadmap item R7.5 — batched per playlist, built from
        # HistoryService's own existing derived DOWNLOADED events (item
        # 54), not a new source of truth; runs on the real 20s backend-
        # poll cycle (the only cycle that can actually produce a newly-
        # completed download), never its own timer.
        if self._tray_icon is None:
            return

        if not self.application.settings.notify_downloads_finished:
            return

        if self._last_notified_download_at is None:
            # Seeding hasn't completed yet (or found nothing) — skip
            # this cycle rather than risk treating all of history as
            # "new" the moment it does land.
            return

        run_worker(
            self.thread_pool,
            lambda: self.application.history_service.get_recent_events(limit=50),
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

    def _check_for_needs_decision_notification(self, total: int) -> None:
        # Roadmap item R7.5 — fires only on a genuine INCREASE from the
        # last-seen total, never on every poll tick the count happens
        # to still be positive (that would notify every 2s for as long
        # as anything sits unreviewed).
        if (
                self._tray_icon is not None
                and self.application.settings.notify_needs_decision
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

    def _notify_error(self, message: str) -> None:
        # Roadmap item R7.5 — rate-limited so an unreachable slskd
        # can't emit a notification every single 20s backend-poll tick.
        if self._tray_icon is None:
            return

        if not self.application.settings.notify_errors:
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
